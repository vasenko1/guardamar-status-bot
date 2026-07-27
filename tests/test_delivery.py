import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.delivery import attempt_delivery
from telegrambot.state import PublicationState

MADRID = ZoneInfo("Europe/Madrid")


class DeliveryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_is_persisted_and_duplicate_does_no_work(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 7, 26, 8, 0, tzinfo=MADRID)
            calls = {"produce": 0, "deliver": 0}

            async def produce():
                calls["produce"] += 1
                return "digest"

            async def deliver(message):
                self.assertEqual(message, "digest")
                calls["deliver"] += 1

            first = await attempt_delivery(
                now, state, produce, deliver
            )
            second = await attempt_delivery(
                now, state, produce, deliver
            )

            self.assertEqual(first, "success")
            self.assertEqual(second, "duplicate")
            self.assertEqual(calls, {"produce": 1, "deliver": 1})
            self.assertEqual(
                state.last_successful_date(),
                now.date(),
            )

    async def test_unsafe_digest_is_skipped_without_telegram(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 7, 26, 8, 0, tzinfo=MADRID)
            delivered = False

            async def produce():
                raise RuntimeError("source unavailable")

            async def deliver(message):
                nonlocal delivered
                delivered = True

            result = await attempt_delivery(
                now, state, produce, deliver
            )

            self.assertEqual(result, "skipped")
            self.assertFalse(delivered)
            self.assertIsNone(state.last_successful_date())

    async def test_telegram_failure_is_not_persisted_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 7, 26, 8, 0, tzinfo=MADRID)
            attempts = 0

            async def produce():
                return "digest"

            async def deliver(message):
                nonlocal attempts
                attempts += 1
                raise RuntimeError("telegram unavailable")

            first = await attempt_delivery(
                now, state, produce, deliver
            )
            second = await attempt_delivery(
                now, state, produce, deliver
            )

            self.assertEqual(first, "failure")
            self.assertEqual(second, "failure")
            self.assertEqual(attempts, 2)
            self.assertIsNone(state.last_successful_date())


if __name__ == "__main__":
    unittest.main()
