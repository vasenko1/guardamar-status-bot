import json
import os
import stat
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegrambot.electricity import (
    DailyPrices,
    ElectricityError,
    HourlyPrice,
    _best_green_window,
    _colors,
    _load_price_snapshot,
    _price,
    _write_price_snapshot,
    build_explanation_message,
    build_price_message,
    fetch_prices,
    load_or_fetch_prices,
    normalize_prices,
    publish_prices,
    TIMEZONE,
)
from telegrambot.__main__ import _run_command
from telegrambot._transport import BoundedFetchError, _BoundedRedirectHandler
from telegrambot.state import PublicationState
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


TARGET = date(2026, 8, 1)


def _payload(missing=None):
    values = []
    for hour in range(24):
        if hour == missing:
            continue
        for geo_id, geo_name in ((8741, "Península"), (8744, "Ceuta")):
            values.append({
                "value": 49 + hour * 10,
                "datetime": f"2026-08-01T{hour:02d}:00:00+02:00",
                "geo_id": geo_id,
                "geo_name": geo_name,
            })
    return json.dumps({"indicator": {"values": values}}).encode()


def _daily():
    values = [
        Decimal("0.185"), Decimal("0.181"), Decimal("0.182"),
        Decimal("0.182"), Decimal("0.182"), Decimal("0.183"),
        Decimal("0.192"), Decimal("0.195"), Decimal("0.211"),
        Decimal("0.167"), Decimal("0.183"), Decimal("0.135"),
        Decimal("0.115"), Decimal("0.097"), Decimal("0.049"),
        Decimal("0.057"), Decimal("0.106"), Decimal("0.136"),
        Decimal("0.239"), Decimal("0.272"), Decimal("0.292"),
        Decimal("0.322"), Decimal("0.239"), Decimal("0.223"),
    ]
    return DailyPrices(
        TARGET, tuple(HourlyPrice(hour, value) for hour, value in enumerate(values))
    )


class ElectricityTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_peninsula_and_converts_mwh_to_kwh(self):
        result = normalize_prices(_payload(), TARGET)
        self.assertEqual(len(result.hours), 24)
        self.assertEqual(result.hours[0].eur_kwh, Decimal("0.049"))
        self.assertEqual(result.hours[23].eur_kwh, Decimal("0.279"))

    def test_rejects_incomplete_day(self):
        with self.assertRaises(ElectricityError) as raised:
            normalize_prices(_payload(missing=7), TARGET)
        self.assertEqual(raised.exception.diagnostic_code, "INCOMPLETE")

    def test_non_finite_price_is_rejected_without_decimal_crash(self):
        payload = json.loads(_payload())
        payload["indicator"]["values"][0]["value"] = "NaN"
        with self.assertRaises(ElectricityError) as raised:
            normalize_prices(json.dumps(payload).encode(), TARGET)
        self.assertEqual(raised.exception.diagnostic_code, "INCOMPLETE")

    def test_normalized_snapshot_round_trip_is_private_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            _write_price_snapshot(path, _daily())
            loaded = _load_price_snapshot(path, TARGET)
            mode = stat.S_IMODE(os.stat(path).st_mode)

        self.assertEqual(loaded, _daily())
        self.assertEqual(mode, 0o600)

    def test_snapshot_decimal_serialization_stays_bounded(self):
        unusual = DailyPrices(
            TARGET,
            tuple(
                HourlyPrice(hour, Decimal("0E-100000"))
                for hour in range(24)
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            _write_price_snapshot(path, unusual)
            size = path.stat().st_size
            loaded = _load_price_snapshot(path, TARGET)

        self.assertLess(size, 16_384)
        self.assertEqual(loaded, unusual)

    def test_esios_redirects_are_rejected_before_following(self):
        # ESIOS passes follow_redirects=False, which installs a handler
        # with no allowed-URL predicate: every redirect must fail closed.
        handler = _BoundedRedirectHandler(None)

        with self.assertRaises(BoundedFetchError) as raised:
            handler.redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://example.com/collect",
            )

        self.assertEqual(raised.exception.code, "REDIRECT")

    def test_snapshot_for_another_date_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            _write_price_snapshot(path, _daily())
            loaded = _load_price_snapshot(path, date(2026, 8, 2))

        self.assertIsNone(loaded)

    def test_rejects_corrupt_or_oversized_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ElectricityError) as corrupt:
                _load_price_snapshot(path, TARGET)
            path.write_bytes(b"x" * 16_385)
            with self.assertRaises(ElectricityError) as oversized:
                _load_price_snapshot(path, TARGET)

        self.assertEqual(
            corrupt.exception.diagnostic_code, "SNAPSHOT-INVALID"
        )
        self.assertEqual(
            oversized.exception.diagnostic_code, "SNAPSHOT-INVALID"
        )

    async def test_complete_snapshot_avoids_api_even_without_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            _write_price_snapshot(path, _daily())
            with patch(
                "telegrambot.electricity.fetch_prices"
            ) as fetch:
                loaded = await load_or_fetch_prices("", TARGET, path)

        self.assertEqual(loaded, _daily())
        fetch.assert_not_called()

    async def test_fetches_once_then_reuses_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            with patch(
                "telegrambot.electricity.fetch_prices",
                new_callable=AsyncMock,
                return_value=_daily(),
            ) as fetch:
                first = await load_or_fetch_prices("key", TARGET, path)
                second = await load_or_fetch_prices("key", TARGET, path)

        self.assertEqual(first, _daily())
        self.assertEqual(second, _daily())
        self.assertEqual(fetch.await_count, 1)

    async def test_corrupt_snapshot_is_replaced_after_complete_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            path.write_text("not-json", encoding="utf-8")
            with patch(
                "telegrambot.electricity.fetch_prices",
                new_callable=AsyncMock,
                return_value=_daily(),
            ) as fetch:
                loaded = await load_or_fetch_prices("key", TARGET, path)
            stored = _load_price_snapshot(path, TARGET)

        self.assertEqual(loaded, _daily())
        self.assertEqual(stored, _daily())
        self.assertEqual(fetch.await_count, 1)

    async def test_snapshot_write_failure_prevents_unstored_publication(self):
        failure = ElectricityError(
            "write failed", code="SNAPSHOT-WRITE", retryable=True
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity_prices.json"
            with patch(
                "telegrambot.electricity.fetch_prices",
                new_callable=AsyncMock,
                return_value=_daily(),
            ), patch(
                "telegrambot.electricity._write_price_snapshot",
                side_effect=failure,
            ):
                with self.assertRaises(ElectricityError) as raised:
                    await load_or_fetch_prices("key", TARGET, path)

        self.assertEqual(
            raised.exception.diagnostic_code, "SNAPSHOT-WRITE"
        )

    async def test_published_cli_invocation_does_not_touch_esios(self):
        target = (datetime.now(TIMEZONE) + timedelta(days=1)).date()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "electricity.json"
            PublicationState(state_path).mark_electricity_published(target)
            environment = {
                "ELECTRICITY_STATE_PATH": str(state_path),
                "ELECTRICITY_SNAPSHOT_PATH": str(
                    Path(directory) / "electricity_prices.json"
                ),
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "telegrambot.__main__.load_or_fetch_prices",
                new_callable=AsyncMock,
            ) as collect:
                result = await _run_command("electricity")

        self.assertEqual(result, 0)
        collect.assert_not_awaited()

    async def test_cli_creates_explanation_then_replies_with_table(self):
        target = (datetime.now(TIMEZONE) + timedelta(days=1)).date()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "electricity.json"
            environment = {
                "ELECTRICITY_STATE_PATH": str(state_path),
                "ELECTRICITY_SNAPSHOT_PATH": str(
                    Path(directory) / "electricity_prices.json"
                ),
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "telegrambot.__main__.load_or_fetch_prices",
                new_callable=AsyncMock,
                return_value=DailyPrices(target, _daily().hours),
            ), patch(
                "telegrambot.__main__.send_message",
                new_callable=AsyncMock,
                side_effect=(101, 102),
            ) as send:
                result = await _run_command("electricity")

            state = PublicationState(state_path)
            published = state.is_published(target)
            anchor_id = state.electricity_explanation_message_id()

        self.assertEqual(result, 0)
        self.assertEqual(send.await_count, 2)
        self.assertNotIn("reply_to_message_id", send.await_args_list[0].kwargs)
        self.assertEqual(
            send.await_args_list[1].kwargs["reply_to_message_id"], 101
        )
        self.assertTrue(published)
        self.assertEqual(anchor_id, 101)

    async def test_cli_updates_persistent_explanation(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "electricity.json"
            PublicationState(state_path).mark_electricity_explanation(101)
            environment = {
                "ELECTRICITY_STATE_PATH": str(state_path),
                "ELECTRICITY_SNAPSHOT_PATH": str(
                    Path(directory) / "electricity_prices.json"
                ),
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "telegrambot.__main__.edit_message",
                new_callable=AsyncMock,
            ) as edit, patch(
                "telegrambot.__main__.load_or_fetch_prices",
                new_callable=AsyncMock,
            ) as collect:
                result = await _run_command(
                    "electricity-update-explanation"
                )

        self.assertEqual(result, 0)
        collect.assert_not_awaited()
        edit.assert_awaited_once()
        self.assertEqual(edit.await_args.args[:3], ("token", "chat", 101))
        self.assertIn(
            "Это не окончательная стоимость", edit.await_args.args[3]
        )

    async def test_preview_shares_publication_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "electricity.json"
            environment = {
                "ELECTRICITY_STATE_PATH": str(state_path),
                "ELECTRICITY_SNAPSHOT_PATH": str(
                    Path(directory) / "electricity_prices.json"
                ),
            }
            with PublicationState(state_path).exclusive_run(), patch.dict(
                os.environ, environment, clear=False
            ), patch(
                "telegrambot.__main__.load_or_fetch_prices",
                new_callable=AsyncMock,
            ) as collect:
                with self.assertRaises(StateError):
                    await _run_command("electricity-preview")

        collect.assert_not_awaited()

    async def test_snapshot_and_publication_paths_must_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            shared_path = str(Path(directory) / "electricity.json")
            environment = {
                "ELECTRICITY_STATE_PATH": shared_path,
                "ELECTRICITY_SNAPSHOT_PATH": shared_path,
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "telegrambot.__main__.load_or_fetch_prices",
                new_callable=AsyncMock,
            ) as collect:
                with self.assertRaises(ValueError):
                    await _run_command("electricity-preview")

        collect.assert_not_awaited()

    async def test_transient_collection_failure_is_left_to_scheduler(self):
        transient = ElectricityError(
            "temporary", code="HTTP-503", retryable=True
        )
        with patch(
            "telegrambot.electricity._request_payload",
            side_effect=transient,
        ) as request:
            with self.assertRaises(ElectricityError):
                await fetch_prices("key", TARGET)
        self.assertEqual(request.call_count, 1)

    async def test_permanent_collection_failure_is_not_retried(self):
        permanent = ElectricityError(
            "unauthorized", code="HTTP-401", retryable=False
        )
        with patch(
            "telegrambot.electricity._request_payload",
            side_effect=permanent,
        ) as request:
            with self.assertRaises(ElectricityError):
                await fetch_prices("key", TARGET)
        self.assertEqual(request.call_count, 1)

    def test_message_is_for_tomorrow_and_table_is_monospace(self):
        message = build_price_message(_daily())
        self.assertIn("Цены на электричество завтра", message)
        self.assertIn("Суббота, 1 августа", message)
        self.assertIn("<pre>00  🟡 0,185 │ 12  🟢 0,115", message)
        self.assertIn("20  🔴 0,292", message)
        self.assertIn("19  🔴 0,272", message)
        self.assertIn("21:00–22:00 · 0,322 €/кВт·ч", message)
        self.assertIn("период с 11:00 до 18:00", message)
        self.assertNotIn("запланировать\nна период", message)
        self.assertIn("период с 11:00 до 18:00.", message)
        self.assertTrue(message.endswith("обЪявления Гуардамар</b></a>"))
        self.assertLess(message.index("По часам"), message.index("Выгоднее"))
        self.assertLess(message.index("Выгоднее"), message.index("Дороже"))
        self.assertLess(message.index("Дороже"), message.index("Энергоёмкие"))
        self.assertNotIn("Для PVPC", message)
        self.assertNotIn("Источник:", message)
        self.assertNotIn("сегодня", message.casefold())

    def test_colors_use_daily_price_thirds(self):
        colors = _colors(_daily().hours)
        self.assertEqual(sum(color == "🟢" for color in colors.values()), 8)
        self.assertEqual(sum(color == "🟡" for color in colors.values()), 8)
        self.assertEqual(sum(color == "🔴" for color in colors.values()), 8)
        self.assertEqual(colors[14], "🟢")
        self.assertEqual(colors[0], "🟡")
        self.assertEqual(colors[21], "🔴")

    def test_equal_boundary_prices_are_not_split_between_colors(self):
        prices = tuple(
            HourlyPrice(hour, Decimal("0.100") if 6 <= hour < 18 else (
                Decimal("0.050") if hour < 6 else Decimal("0.200")
            ))
            for hour in range(24)
        )
        colors = _colors(prices)
        self.assertEqual({colors[hour] for hour in range(6, 18)}, {"🟡"})

    def test_prices_equal_at_display_precision_keep_the_same_color(self):
        values = (
            [Decimal("0.100")] * 7
            + [Decimal("0.1426"), Decimal("0.1434")]
            + [Decimal("0.180")] * 7
            + [Decimal("0.250")] * 8
        )
        prices = tuple(
            HourlyPrice(hour, value) for hour, value in enumerate(values)
        )

        colors = _colors(prices)

        self.assertEqual(colors[7], "🟢")
        self.assertEqual(colors[8], "🟢")

    def test_display_price_does_not_render_negative_zero(self):
        self.assertEqual(_price(Decimal("-0.0004")), "0,000")
        self.assertEqual(_price(Decimal("-0.0005")), "-0,001")

    def test_adjacent_visible_extremes_are_rendered_as_full_periods(self):
        values = [Decimal("0.150") + Decimal(hour) / 1000 for hour in range(24)]
        values[13] = Decimal("0.0026")
        values[14] = Decimal("0.0034")
        values[21] = Decimal("0.2356")
        values[22] = Decimal("0.2364")
        data = DailyPrices(TARGET, tuple(
            HourlyPrice(hour, value) for hour, value in enumerate(values)
        ))

        message = build_price_message(data)

        self.assertIn("13:00–15:00 · 0,003 €/кВт·ч", message)
        self.assertIn("21:00–23:00 · 0,236 €/кВт·ч", message)

    def test_disjoint_visible_extremes_are_all_rendered(self):
        values = [Decimal("0.150") + Decimal(hour) / 1000 for hour in range(24)]
        values[2] = Decimal("0.0027")
        values[13] = Decimal("0.0026")
        values[14] = Decimal("0.0034")
        data = DailyPrices(TARGET, tuple(
            HourlyPrice(hour, value) for hour, value in enumerate(values)
        ))

        message = build_price_message(data)

        self.assertIn("02:00–03:00, 13:00–15:00 · 0,003 €/кВт·ч", message)

    def test_recommendation_uses_continuous_green_hours(self):
        values = (
            "0.189", "0.188", "0.184", "0.167", "0.166", "0.175",
            "0.191", "0.195", "0.208", "0.174", "0.202", "0.194",
            "0.182", "0.170", "0.108", "0.108", "0.102", "0.126",
            "0.220", "0.260", "0.296", "0.316", "0.234", "0.224",
        )
        prices = tuple(
            HourlyPrice(hour, Decimal(value))
            for hour, value in enumerate(values)
        )
        colors = _colors(prices)

        self.assertEqual(colors[12], "🟡")
        self.assertEqual(_best_green_window(prices, colors), (13, 18))

    def test_visibly_equal_green_windows_prefer_the_earlier_period(self):
        values = [Decimal("0.200")] * 24
        for hour, value in {
            0: "0.1004", 1: "0.1004",
            4: "0.1003", 5: "0.1003",
            8: "0.1002", 9: "0.1002",
            12: "0.1001", 13: "0.1001",
        }.items():
            values[hour] = Decimal(value)
        prices = tuple(
            HourlyPrice(hour, value) for hour, value in enumerate(values)
        )
        colors = _colors(prices)

        self.assertEqual(_best_green_window(prices, colors), (0, 2))

    def test_recommendation_is_omitted_without_green_hours(self):
        prices = tuple(
            HourlyPrice(hour, Decimal("0.100"))
            for hour in range(24)
        )
        data = DailyPrices(TARGET, prices)

        message = build_price_message(data)
        self.assertNotIn("Энергоёмкие дела", message)
        self.assertIn("Одинаковая цена весь день", message)
        self.assertNotIn("Выгоднее всего", message)
        self.assertNotIn("Дороже всего", message)

    def test_explanation_documents_relative_daily_colors(self):
        message = build_explanation_message()
        self.assertIn("Самые дешёвые часы этого дня", message)
        self.assertIn("Средние по цене часы", message)
        self.assertIn("Самые дорогие часы этого дня", message)
        self.assertIn("сравнивают часы только между собой", message)
        self.assertIn("Цена меняется каждый час вслед за оптовым рынком", message)
        self.assertIn("на неё влияют спрос", message)
        self.assertIn("объём солнечной и ветровой энергии", message)
        self.assertIn("стоимость работы энергосистемы", message)
        self.assertIn("PVPC — регулируемый тариф", message)
        self.assertIn("в типе договора должно быть указано PVPC", message)
        self.assertIn("Это не окончательная стоимость", message)
        self.assertIn("фиксированный тариф", message)
        self.assertIn("почасовые цены не применяются", message)
        self.assertNotIn("индексированном тарифе", message)
        self.assertNotIn("0,10", message)
        self.assertIn("ESIOS / Red Eléctrica", message)

    async def test_publishes_main_and_reply_once(self):
        sent = []
        collections = 0

        async def collect():
            nonlocal collections
            collections += 1
            return _daily()

        async def send_main(message, reply_id):
            sent.append((message, reply_id))
            return 42

        async def send_explanation(message):
            sent.append((message, None))
            return 43

        async def collect_next():
            return DailyPrices(TARGET + timedelta(days=1), _daily().hours)

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "electricity.json")
            result = await publish_prices(
                TARGET, state, collect, send_main, send_explanation
            )
            duplicate = await publish_prices(
                TARGET, state, collect, send_main, send_explanation
            )
            next_day = TARGET + timedelta(days=1)
            result_next = await publish_prices(
                next_day,
                state,
                collect_next,
                send_main,
                send_explanation,
            )
        self.assertEqual(result, "success")
        self.assertEqual(duplicate, "duplicate")
        self.assertEqual(result_next, "success")
        self.assertEqual(collections, 1)
        self.assertEqual(len(sent), 3)
        self.assertIn("Как читать таблицу", sent[0][0])
        self.assertIn("Цены на электричество завтра", sent[1][0])
        self.assertIsNone(sent[0][1])
        self.assertEqual(sent[1][1], 43)
        self.assertEqual(sent[2][1], 43)

    async def test_explanation_failure_does_not_publish_table(self):
        async def collect():
            return _daily()

        async def send_main(message, reply_id):
            self.fail("table sent without a persistent explanation")

        async def fail_explanation(message):
            raise TelegramError("failed", retryable=True)

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "electricity.json")
            with self.assertRaises(TelegramError):
                await publish_prices(
                    TARGET, state, collect, send_main, fail_explanation
                )
            self.assertFalse(state.is_published(TARGET))
            self.assertIsNone(
                state.electricity_explanation_message_id()
            )

    async def test_table_failure_reuses_created_explanation_on_retry(self):
        sent_explanations = 0
        table_attempts = 0

        async def collect():
            return _daily()

        async def send_explanation(message):
            nonlocal sent_explanations
            sent_explanations += 1
            return 43

        async def send_main(message, reply_id):
            nonlocal table_attempts
            table_attempts += 1
            self.assertEqual(reply_id, 43)
            if table_attempts == 1:
                raise TelegramError("failed", retryable=True)
            return 44

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "electricity.json")
            with self.assertRaises(TelegramError):
                await publish_prices(
                    TARGET, state, collect, send_main, send_explanation
                )
            result = await publish_prices(
                TARGET, state, collect, send_main, send_explanation
            )

        self.assertEqual(result, "success")
        self.assertEqual(sent_explanations, 1)
        self.assertEqual(table_attempts, 2)
