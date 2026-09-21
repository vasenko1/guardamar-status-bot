import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, call, patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import (
    _produce_message,
    _run_command,
    _send_operational_update,
)
from telegrambot.environment import (
    CAMS_DATA_URL,
    EnvironmentError,
    _required_utc_hours,
    _write_cams_cache,
    accepted_cams_cache_path,
    candidate_cams_cache_path,
    fetch_cams,
    ensure_accepted_cams_snapshot,
    parse_cams_payload,
    persist_cams_snapshot,
)
from telegrambot.models import AirQualitySummary, BeachNotice, BeachStatus
from telegrambot.operational_updates import (
    OperationalUpdateState,
    build_beach_root_message,
    confirmed_beach_status,
)
from telegrambot.state import PublicationState
from telegrambot.telegram import TelegramError, _response_error


MADRID = ZoneInfo("Europe/Madrid")
CORE_VARIABLES = (
    "particulate_matter_2.5um",
    "particulate_matter_10um",
    "ozone",
    "nitrogen_dioxide",
    "sulphur_dioxide",
)


def _cams_payload(now: datetime, base: datetime) -> bytes:
    units = {name: "µg/m3" for name in CORE_VARIABLES}
    start = _required_utc_hours(now)[0]
    rows = []
    for offset in range(80):
        timestamp = start + timedelta(hours=offset)
        rows.append({
            "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "kind": "analysis" if timestamp < base else "forecast",
            "values": {
                "particulate_matter_2.5um": 8.0,
                "particulate_matter_10um": 15.0,
                "ozone": 60.0,
                "nitrogen_dioxide": 20.0,
                "sulphur_dioxide": 20.0,
            },
        })
    return json.dumps({
        "schema_version": 1,
        "provider": "Copernicus Atmosphere Monitoring Service (CAMS)",
        "product": "cams-europe-air-quality-forecasts",
        "model": "ensemble",
        "forecast_base_utc": base.isoformat().replace("+00:00", "Z"),
        "units": units,
        "hourly": rows,
    }).encode()


def _beach_status(flags, *, jellyfish=None, hour=12, minute=0, day=None):
    jellyfish = jellyfish or {}
    source_day = day or date(2026, 9, 14)
    return BeachStatus(
        flag_color=None,
        sea_temperature_c=None,
        nearby_flags=tuple(flags.items()),
        jellyfish_beaches=tuple(
            name for name, present in jellyfish.items() if present
        ),
        jellyfish_states=tuple(jellyfish.items()),
        updated_times=tuple(
            (name, time(hour, minute)) for name in flags
        ),
        source_date=source_day,
    )


class CamsAcceptedSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 4, 10, 25, tzinfo=MADRID)
        self.old_base = datetime(2026, 8, 3, tzinfo=timezone.utc)
        self.new_base = datetime(2026, 8, 4, tzinfo=timezone.utc)

    async def test_reconstruction_reads_accepted_snapshot_not_mutable_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cams.json"
            accepted_path = accepted_cams_cache_path(cache_path)
            cache_path.write_bytes(_cams_payload(self.now, self.new_base))
            accepted_path.write_bytes(_cams_payload(self.now, self.old_base))

            _, _, selected = await fetch_cams(
                "",
                cache_path,
                self.now,
                allow_remote=False,
                remaining_day=True,
            )

            self.assertEqual(selected, self.old_base)
            self.assertEqual(
                parse_cams_payload(cache_path.read_bytes(), self.now)[1],
                self.new_base,
            )
            self.assertFalse(
                candidate_cams_cache_path(cache_path, self.old_base).exists()
            )

    def test_accepted_snapshot_can_be_repaired_from_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cams.json"
            accepted_path = accepted_cams_cache_path(cache_path)
            candidate_path = candidate_cams_cache_path(cache_path, self.old_base)
            candidate_path.write_bytes(_cams_payload(self.now, self.old_base))
            accepted_path.write_bytes(_cams_payload(self.now, self.new_base))

            ensure_accepted_cams_snapshot(cache_path, self.now, self.old_base)

            self.assertEqual(
                parse_cams_payload(accepted_path.read_bytes(), self.now)[1],
                self.old_base,
            )

    def test_promotion_requires_the_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cams.json"
            accepted_path = accepted_cams_cache_path(cache_path)
            cache_path.write_bytes(_cams_payload(self.now, self.new_base))

            with self.assertRaises(EnvironmentError):
                persist_cams_snapshot(
                    cache_path, accepted_path, self.now, self.old_base
                )
            self.assertFalse(accepted_path.exists())

    def test_exact_candidate_survives_mutable_cache_race(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cams.json"
            accepted_path = accepted_cams_cache_path(cache_path)
            candidate_path = candidate_cams_cache_path(
                cache_path, self.old_base
            )
            candidate_path.write_bytes(_cams_payload(self.now, self.old_base))
            cache_path.write_bytes(_cams_payload(self.now, self.new_base))

            persist_cams_snapshot(
                cache_path, accepted_path, self.now, self.old_base
            )

            self.assertEqual(
                parse_cams_payload(accepted_path.read_bytes(), self.now)[1],
                self.old_base,
            )

    def test_atomic_write_does_not_reuse_the_legacy_fixed_temp_name(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cams.json"
            legacy_temp = Path(directory) / ".cams.json.tmp"
            legacy_temp.write_bytes(b"other-process")
            payload = _cams_payload(self.now, self.old_base)

            _write_cams_cache(cache_path, payload)

            self.assertEqual(legacy_temp.read_bytes(), b"other-process")
            self.assertEqual(cache_path.read_bytes(), payload)

    def test_publication_state_has_no_cams_file_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            cache_path = Path(directory) / "cams.json"
            cache_path.write_bytes(_cams_payload(self.now, self.old_base))
            state = PublicationState(state_path)
            state.mark_morning(self.now.date(), 10, self.now)
            with patch.dict(
                os.environ, {"CAMS_CACHE_PATH": str(cache_path)}, clear=False
            ):
                state.mark_cams_environment(
                    self.now.date(), self.old_base, None, None
                )

            self.assertEqual(
                state.morning_environment(self.now.date())[2], self.old_base
            )
            self.assertFalse(accepted_cams_cache_path(cache_path).exists())


class PreviewIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_uses_disposable_cams_cache(self):
        now = datetime(2026, 9, 14, 12, 0, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            production_cache = Path(directory) / "cams.json"
            production_cache.write_bytes(b"production-cache")
            captured = {}

            async def produce(*args, **kwargs):
                preview_cache = kwargs["cams_cache_path"]
                captured["path"] = preview_cache
                self.assertEqual(preview_cache.read_bytes(), b"production-cache")
                preview_cache.write_bytes(b"preview-only")
                return "preview"

            with (
                patch.dict(os.environ, {
                    "CAMS_CACHE_PATH": str(production_cache),
                }),
                patch("telegrambot.__main__.produce_message", new=produce),
            ):
                self.assertEqual(await _produce_message("key", now), "preview")

            self.assertEqual(production_cache.read_bytes(), b"production-cache")
            self.assertFalse(captured["path"].exists())


class LateEnvironmentTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 10, 40, tzinfo=MADRID)
        self.old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        self.new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        self.old_air = AirQualitySummary(
            ("PM10",), "во второй половине дня", category=3
        )
        self.new_air = AirQualitySummary(
            ("PM10",), "во второй половине дня", category=4
        )

    def _state(self, directory: str) -> Path:
        state_path = Path(directory) / "delivery.json"
        state = PublicationState(state_path)
        state.mark_morning(self.now.date(), 10, self.now)
        state.mark_cams_environment(
            self.now.date(), self.old_base, self.old_air, None
        )
        return state_path

    async def test_telegram_failure_keeps_old_semantic_baseline_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = self._state(directory)
            fetch = AsyncMock(side_effect=[
                (self.old_air, None, self.old_base),
                (self.new_air, None, self.new_base),
                (self.old_air, None, self.old_base),
                (self.new_air, None, self.new_base),
            ])
            sent = AsyncMock(side_effect=[
                TelegramError(
                    "temporary failure",
                    retryable=True,
                    code="HTTP-500",
                    status=500,
                ),
                30,
            ])
            promote = patch("telegrambot.__main__._promote_cams_snapshot")
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.fetch_cams", new=fetch),
                patch("telegrambot.__main__.ensure_accepted_cams_snapshot"),
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_meteosalud_cold",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.in_query_window",
                    return_value=False,
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                promote as promoted,
            ):
                clock.now.return_value = self.now
                self.assertEqual(await _run_command("update"), 0)
                self.assertEqual(
                    PublicationState(state_path).morning_environment(
                        self.now.date()
                    )[2],
                    self.old_base,
                )
                promoted.assert_not_called()

                self.assertEqual(await _run_command("update"), 0)

            self.assertEqual(sent.await_count, 2)
            self.assertEqual(fetch.await_count, 4)
            self.assertEqual(
                PublicationState(state_path).morning_environment(
                    self.now.date()
                )[2],
                self.new_base,
            )
            promoted.assert_called_once()

    async def test_snapshot_failure_after_send_does_not_repeat_public_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = self._state(directory)
            fetch = AsyncMock(side_effect=[
                (self.old_air, None, self.old_base),
                (self.new_air, None, self.new_base),
            ])
            sent = AsyncMock(return_value=30)
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.fetch_cams", new=fetch),
                patch("telegrambot.__main__.ensure_accepted_cams_snapshot"),
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_meteosalud_cold",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.in_query_window",
                    return_value=False,
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch(
                    "telegrambot.__main__._promote_cams_snapshot",
                    side_effect=EnvironmentError("disk failure"),
                ),
            ):
                clock.now.return_value = self.now
                self.assertEqual(await _run_command("update"), 0)

            sent.assert_awaited_once()
            self.assertEqual(
                PublicationState(state_path).morning_environment(
                    self.now.date()
                )[2],
                self.new_base,
            )


class MayorBeachLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_newer_mayor_notice_refreshes_existing_root(self):
        from telegrambot.__main__ import _refresh_mayor_beach_notice

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 9, 14, 16, 0, tzinfo=MADRID)
            state.mark_morning(
                now.date(),
                100,
                datetime(2026, 9, 14, 7, 30, tzinfo=MADRID),
            )
            state.mark_beach_message(
                now.date(), 200, _beach_status({"Montcaio": "green"})
            )
            notice = BeachNotice(
                "Купание запрещено.",
                True,
                datetime(2026, 9, 14, 15, 30, tzinfo=MADRID),
            )
            edited = []

            async def edit(_token, _chat, message_id, message):
                edited.append((message_id, message))

            with (
                patch(
                    "telegrambot.__main__.latest_beach_notice",
                    new=AsyncMock(return_value=notice),
                ) as latest,
                patch("telegrambot.__main__.edit_message", new=edit),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(return_value=201),
                ),
            ):
                result = await _refresh_mayor_beach_notice(
                    now, state, "token", "chat"
                )

            self.assertEqual(result, "refreshed")
            self.assertEqual(latest.await_args.args[1], datetime(
                2026, 9, 14, 7, 30, tzinfo=MADRID
            ))
            self.assertEqual(edited[0][0], 200)
            self.assertIn("⛔ Ограничение купания", edited[0][1])
            self.assertNotIn("✅ Купание разрешено", edited[0][1])
            _, stored_notice = state.beach_root_facts(now.date())
            self.assertEqual(stored_notice, notice)

    async def test_out_of_season_monitor_does_not_check_mayor(self):
        now = datetime(2026, 10, 1, 15, 0, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            operational_path = Path(directory) / "operational.json"
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 100, now.replace(hour=7, minute=30))
            state.mark_cams_environment(
                now.date(), datetime(2026, 10, 1, tzinfo=timezone.utc), None, None
            )
            mayor = AsyncMock(return_value=None)
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(operational_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.latest_beach_notice", new=mayor),
                patch("telegrambot.__main__.fetch_meteosalud", new=AsyncMock(return_value=None)),
                patch("telegrambot.__main__.fetch_meteosalud_cold", new=AsyncMock(return_value=None)),
                patch("telegrambot.__main__.fetch_warnings", new=AsyncMock(return_value=())),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("monitor-updates"), 0)
            mayor.assert_not_awaited()

    async def test_existing_notice_timestamp_bounds_next_mayor_check(self):
        from telegrambot.__main__ import _refresh_mayor_beach_notice

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 9, 14, 18, 0, tzinfo=MADRID)
            state.mark_morning(
                now.date(), 100,
                datetime(2026, 9, 14, 7, 30, tzinfo=MADRID),
            )
            previous = BeachNotice(
                "Купание запрещено.", True,
                datetime(2026, 9, 14, 15, 30, tzinfo=MADRID),
            )
            state.mark_beach_message(
                now.date(), 200, _beach_status({"Montcaio": "red"}), previous
            )
            with patch(
                "telegrambot.__main__.latest_beach_notice",
                new=AsyncMock(return_value=None),
            ) as latest:
                result = await _refresh_mayor_beach_notice(
                    now, state, "token", "chat"
                )
            self.assertEqual(result, "no_update")
            self.assertEqual(latest.await_args.args[1], previous.published_at)


class BeachRootTests(unittest.TestCase):
    def test_single_green_flag_uses_separate_meaning_line(self):
        status = _beach_status({"Montcaio": "green"})
        message = build_beach_root_message(status, None)
        self.assertIn("🏖 <b>Пляжи Гуардамара сегодня</b>", message)
        self.assertIn(
            "🟢 Зелёный флаг\n<b>Montcaio</b>\n✅ Купание разрешено",
            message,
        )
        self.assertNotIn("Пока это весь свежий статус", message)
        self.assertNotIn("—", message)

    def test_all_green_uses_compact_all_beaches_form(self):
        status = _beach_status({
            "Centre": "green", "Roqueta": "green", "Vivers": "green",
            "Montcaio": "green", "Camp": "green", "Ortigues": "green",
        })
        message = build_beach_root_message(status, None)
        self.assertIn(
            "🟢 На всех пляжах зелёные флаги\n✅ Купание разрешено",
            message,
        )
        self.assertNotIn("<b>Centre / Babilònia</b>", message)

    def test_mixed_flags_are_grouped_red_yellow_green(self):
        status = _beach_status({
            "Centre": "yellow", "Roqueta": "red", "Vivers": "yellow",
            "Montcaio": "green", "Camp": "green", "Ortigues": "green",
        })
        message = build_beach_root_message(status, None)
        red = "🔴 Красный флаг\n<b>Roqueta</b>\n⛔ Купание запрещено"
        yellow = (
            "🟡 Жёлтые флаги\n<b>Centre / Babilònia</b>, <b>Vivers</b>\n"
            "⚠️ Купаться с осторожностью"
        )
        green = (
            "🟢 Зелёные флаги\n<b>Montcaio</b>, <b>Camp</b>, <b>Ortigues</b>\n"
            "✅ Купание разрешено"
        )
        self.assertIn(red, message)
        self.assertIn(yellow, message)
        self.assertIn(green, message)
        self.assertLess(message.index(red), message.index(yellow))
        self.assertLess(message.index(yellow), message.index(green))
        self.assertNotIn("—", message)

    def test_long_group_wraps_after_three_beaches(self):
        status = _beach_status({
            "Centre": "green", "Roqueta": "green", "Vivers": "green",
            "Montcaio": "green", "Camp": "green",
        })
        message = build_beach_root_message(status, None)
        self.assertIn(
            "🟢 Зелёные флаги\n"
            "<b>Centre / Babilònia</b>, <b>Roqueta</b>, <b>Vivers</b>\n"
            "<b>Montcaio</b>, <b>Camp</b>\n✅ Купание разрешено",
            message,
        )

    def test_bathing_prohibition_suppresses_permission_meaning(self):
        status = _beach_status({"Montcaio": "green"})
        notice = BeachNotice(
            "Купание временно запрещено.", True,
            datetime(2026, 9, 14, 11, 0, tzinfo=MADRID),
        )
        message = build_beach_root_message(status, notice)
        self.assertIn("🟢 Зелёный флаг\n<b>Montcaio</b>", message)
        self.assertNotIn("✅ Купание разрешено", message)
        self.assertIn("⛔ Ограничение купания", message)

    def test_mayor_caution_suppresses_full_green_permission(self):
        status = _beach_status({"Montcaio": "green"})
        notice = BeachNotice(
            "Купание разрешено с осторожностью.",
            False,
            datetime(2026, 9, 14, 13, 0, tzinfo=MADRID),
        )
        message = build_beach_root_message(status, notice)
        self.assertNotIn("✅ Купание разрешено", message)
        self.assertIn("Купание разрешено с осторожностью.", message)

    def test_mayor_caution_is_suppressed_while_confirmed_red_remains(self):
        status = _beach_status({"Roqueta": "red", "Montcaio": "green"})
        notice = BeachNotice(
            "Купание разрешено с осторожностью.",
            False,
            datetime(2026, 9, 14, 15, 30, tzinfo=MADRID),
        )
        message = build_beach_root_message(status, notice)
        self.assertIn("🔴 Красный флаг\n<b>Roqueta</b>\n⛔ Купание запрещено", message)
        self.assertNotIn("Купание разрешено с осторожностью.", message)
        self.assertNotIn("✅ Купание разрешено", message)

    def test_confirmed_snapshot_keeps_prior_beaches_when_one_change_is_ready(self):
        state = OperationalUpdateState.empty("2026-09-14")
        state["beaches"] = {
            "Centre": {"flag": "green", "jellyfish": False},
            "Roqueta": {"flag": "yellow", "jellyfish": False},
        }
        state["beach_ready"] = [{
            "beach": "Roqueta", "field": "flag", "old": "yellow", "new": "red",
        }]
        status = confirmed_beach_status(
            state, datetime(2026, 9, 14, 12, 5, tzinfo=MADRID)
        )
        self.assertEqual(
            status.nearby_flags,
            (("Centre", "green"), ("Roqueta", "red")),
        )


class BeachRootRetryTests(unittest.IsolatedAsyncioTestCase):
    def _publication_state(self, directory: str, now: datetime) -> Path:
        path = Path(directory) / "delivery.json"
        state = PublicationState(path)
        state.mark_morning(now.date(), 10, now)
        state.mark_beach_message(
            now.date(),
            20,
            _beach_status({"Centre": "green"}, day=now.date()),
        )
        return path

    def _monitor_state(self, directory: str, now: datetime, *, initial=False) -> Path:
        path = Path(directory) / "operational.json"
        state = OperationalUpdateState(path)
        value = OperationalUpdateState.empty(now.date().isoformat())
        value["warnings_initialized"] = True
        if initial:
            value["beach_ready"] = [{
                "beach": "Montcaio",
                "field": "flag",
                "old": None,
                "new": "green",
                "initial": True,
            }]
        else:
            value["beaches"] = {
                "Centre": {"flag": "green", "jellyfish": False}
            }
            value["latest_beaches"] = {
                "Centre": {"flag": "green", "jellyfish": False}
            }
            value["beach_ready"] = [{
                "beach": "Centre",
                "field": "flag",
                "old": "green",
                "new": "yellow",
            }]
        state.write(value)
        return path

    async def test_failed_reply_is_retried_before_ready_change_is_cleared(self):
        now = datetime(2026, 9, 14, 12, 5, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            publication_path = self._publication_state(directory, now)
            monitor_path = self._monitor_state(directory, now)
            sent = AsyncMock(side_effect=[
                TelegramError(
                    "temporary failure",
                    retryable=True,
                    code="HTTP-500",
                    status=500,
                ),
                30,
            ])
            edited = AsyncMock()
            env = {
                "TELEGRAM_BOT_TOKEN": "telegram",
                "TELEGRAM_CHAT_ID": "group",
                "MORNING_DIGEST_STATE_PATH": str(publication_path),
                "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
            }
            with (
                patch.dict(os.environ, env),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.edit_message", new=edited),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("monitor-updates"), 1)
                ready_after_failure = OperationalUpdateState(
                    monitor_path
                ).read(now)["beach_ready"]
                self.assertTrue(ready_after_failure)

                self.assertEqual(await _run_command("monitor-updates"), 0)

            edited.assert_not_awaited()
            self.assertEqual(sent.await_count, 2)
            self.assertEqual(sent.await_args.kwargs["reply_to_message_id"], 20)
            self.assertEqual(
                OperationalUpdateState(monitor_path).read(now)["beach_ready"],
                [],
            )
            root_status, _ = PublicationState(
                publication_path
            ).beach_root_facts(now.date())
            self.assertEqual(root_status.nearby_flags, (("Centre", "green"),))

    async def test_missing_root_during_reply_recreates_root_before_retry(self):
        now = datetime(2026, 9, 14, 12, 5, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            publication_path = self._publication_state(directory, now)
            monitor_path = self._monitor_state(directory, now)
            missing = TelegramError(
                "missing",
                retryable=False,
                code="MESSAGE-NOT-FOUND",
                status=400,
            )
            edited = AsyncMock(side_effect=[missing])
            sent = AsyncMock(side_effect=[missing, 30, 31])
            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(publication_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.edit_message", new=edited),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("monitor-updates"), 0)

            edited.assert_awaited_once()
            self.assertEqual(sent.await_count, 3)
            self.assertEqual(
                sent.await_args_list[0],
                call(
                    "telegram",
                    "group",
                    unittest.mock.ANY,
                    disable_notification=False,
                    reply_to_message_id=20,
                ),
            )
            self.assertNotIn("reply_to_message_id", sent.await_args_list[1].kwargs)
            self.assertEqual(sent.await_args_list[2].kwargs["reply_to_message_id"], 30)
            self.assertEqual(
                PublicationState(publication_path).beach_message_id(now.date()),
                30,
            )
            self.assertEqual(
                OperationalUpdateState(monitor_path).read(now)["beach_ready"],
                [],
            )

    async def test_initial_confirmed_status_creates_only_the_beach_root(self):
        now = datetime(2026, 9, 14, 12, 5, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            publication_path = Path(directory) / "delivery.json"
            PublicationState(publication_path).mark_morning(now.date(), 10, now)
            monitor_path = self._monitor_state(directory, now, initial=True)
            sent = AsyncMock(return_value=21)
            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(publication_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=AsyncMock()),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("monitor-updates"), 0)

            sent.assert_awaited_once()
            root_text = sent.await_args.args[2]
            self.assertIn("🟢 Зелёный флаг\n<b>Montcaio</b>\n✅ Купание разрешено", root_text)
            self.assertEqual(
                OperationalUpdateState(monitor_path).read(now)["beach_ready"],
                [],
            )
            self.assertEqual(
                PublicationState(publication_path).beach_message_id(now.date()),
                21,
            )


class TelegramReplyClassificationTests(unittest.IsolatedAsyncioTestCase):
    def test_real_missing_reply_variants_are_classified_narrowly(self):
        for description in (
            "Bad Request: reply message not found",
            "Bad Request: message to be replied not found",
        ):
            with self.subTest(description=description):
                error = _response_error({"description": description}, 400)
                self.assertEqual(error.diagnostic_code, "MESSAGE-NOT-FOUND")
        malformed = _response_error(
            {"description": "Bad Request: can't parse entities"}, 400
        )
        self.assertEqual(malformed.diagnostic_code, "HTTP-400")

    async def test_missing_reply_can_be_propagated_when_root_must_be_recovered(self):
        missing = TelegramError(
            "missing",
            retryable=False,
            code="MESSAGE-NOT-FOUND",
            status=400,
        )
        sent = AsyncMock(side_effect=missing)
        with patch("telegrambot.__main__.send_message", new=sent):
            with self.assertRaises(TelegramError):
                await _send_operational_update(
                    "token",
                    "group",
                    "update",
                    20,
                    fallback_if_missing=False,
                )
        sent.assert_awaited_once()


class RuntimeWrapperTests(unittest.TestCase):
    def test_lifecycle_wrappers_remain_simple_one_shot_launchers(self):
        commands = {
            "run-daily.sh": "telegrambot morning",
            "update-daily.sh": "telegrambot update",
            "monitor-updates.sh": "telegrambot monitor-updates",
        }
        for filename, command in commands.items():
            with self.subTest(filename=filename):
                text = (Path("termux") / filename).read_text(encoding="utf-8")
                self.assertIn(command, text)
                self.assertIn("exec ./.venv/bin/python", text)
                self.assertNotIn("guardamar-status-runtime.lock", text)
                self.assertNotIn("acquire_runtime_lock", text)


if __name__ == "__main__":
    unittest.main()
