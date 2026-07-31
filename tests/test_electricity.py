import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from telegrambot.electricity import (
    DailyPrices,
    ElectricityError,
    HourlyPrice,
    build_explanation_message,
    build_price_message,
    fetch_prices,
    normalize_prices,
    publish_prices,
)
from telegrambot.state import PublicationState
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
        self.assertIn("<pre>00  🟠 0,185 │ 12  🟡 0,115", message)
        self.assertIn("20  🔴 0,292", message)
        self.assertIn("19  🟠 0,272", message)
        self.assertIn("21:00–22:00 · 0,322 €/кВт·ч", message)
        self.assertIn("период с 11:00 до 17:00", message)
        self.assertNotIn("сегодня", message.casefold())

    def test_explanation_documents_official_and_highlight_colors(self):
        message = build_explanation_message()
        self.assertIn("самый дорогой диапазон", message)
        self.assertIn("ESIOS / Red Eléctrica", message)

    async def test_publishes_main_and_reply_once(self):
        sent = []

        async def collect():
            return _daily()

        async def send_main(message):
            sent.append((message, None))
            return 42

        async def send_reply(message, reply_id):
            sent.append((message, reply_id))
            return 43

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "electricity.json")
            result = await publish_prices(
                TARGET, state, collect, send_main, send_reply
            )
            duplicate = await publish_prices(
                TARGET, state, collect, send_main, send_reply
            )
        self.assertEqual(result, "success")
        self.assertEqual(duplicate, "duplicate")
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1][1], 42)

    async def test_reply_failure_does_not_duplicate_main(self):
        async def collect():
            return _daily()

        async def send_main(message):
            return 42

        async def fail_reply(message, reply_id):
            raise TelegramError("failed", retryable=True)

        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "electricity.json")
            result = await publish_prices(
                TARGET, state, collect, send_main, fail_reply
            )
            self.assertTrue(state.is_published(TARGET))
        self.assertEqual(result, "success-without-explanation")
