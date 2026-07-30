import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.delivery import (
    attempt_delivery,
    publish_morning,
    publish_update,
)
from telegrambot.__main__ import _beach_ready_for_update
from telegrambot.models import BeachStatus
from telegrambot.state import PublicationState

MADRID = ZoneInfo("Europe/Madrid")


class DeliveryRunTests(unittest.IsolatedAsyncioTestCase):
    def test_partial_beach_status_waits_until_final_attempt(self):
        now = datetime(2026, 7, 29, 10, 20, tzinfo=MADRID)
        partial = BeachStatus(
            flag_color="yellow",
            sea_temperature_c=27,
            source_date=now.date(),
            nearby_flags=(("Centre", "yellow"), ("Vivers", "yellow")),
            updated_times=(
                ("Centre", now.time().replace(second=0, microsecond=0)),
                ("Vivers", now.time().replace(second=0, microsecond=0)),
            ),
        )

        self.assertFalse(
            _beach_ready_for_update(partial, now, final_attempt=False)
        )
        self.assertTrue(
            _beach_ready_for_update(partial, now, final_attempt=True)
        )

    def test_three_preferred_beaches_publish_before_final_attempt(self):
        now = datetime(2026, 7, 29, 10, 20, tzinfo=MADRID)
        complete = BeachStatus(
            flag_color="yellow",
            sea_temperature_c=27,
            source_date=now.date(),
            nearby_flags=(
                ("Centre", "yellow"),
                ("Roqueta", "yellow"),
                ("Vivers", "yellow"),
            ),
            updated_times=(
                ("Centre", now.time().replace(second=0, microsecond=0)),
                ("Roqueta", now.time().replace(second=0, microsecond=0)),
                ("Vivers", now.time().replace(second=0, microsecond=0)),
            ),
        )

        self.assertTrue(
            _beach_ready_for_update(complete, now, final_attempt=False)
        )

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

    async def test_update_waits_for_safebeach_before_final_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            morning = datetime(2026, 7, 29, 7, 30, tzinfo=MADRID)
            state.mark_morning(morning.date(), 10, morning, "morning")
            mayor_calls = 0

            async def mayor(since):
                nonlocal mayor_calls
                mayor_calls += 1

            result = await publish_update(
                datetime(2026, 7, 29, 10, 20, tzinfo=MADRID),
                state,
                None,
                False,
                mayor,
                lambda beach, notice: None,
                lambda message: None,
                lambda message_id: None,
            )

            self.assertEqual(result, "waiting")
            self.assertEqual(mayor_calls, 0)

    async def test_update_sends_first_then_deletes_and_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            morning = datetime(2026, 7, 29, 7, 30, tzinfo=MADRID)
            state.mark_morning(morning.date(), 10, morning, "morning")
            actions = []
            beach = BeachStatus(
                flag_color="green",
                sea_temperature_c=27,
                nearby_flags=(
                    ("Vivers", "green"),
                    ("Centre", "green"),
                    ("Roqueta", "yellow"),
                ),
            )

            async def produce(status, notice):
                return "updated"

            async def deliver(message):
                actions.append(("send", message))
                return 20

            async def delete(message_id):
                actions.append(("delete", message_id))

            async def mayor(since):
                return None

            first = await publish_update(
                datetime(2026, 7, 29, 10, 15, tzinfo=MADRID),
                state,
                beach,
                False,
                mayor,
                produce,
                deliver,
                delete,
            )
            second = await publish_update(
                datetime(2026, 7, 29, 10, 20, tzinfo=MADRID),
                state,
                beach,
                False,
                mayor,
                produce,
                deliver,
                delete,
            )

            self.assertEqual(first, "success")
            self.assertEqual(second, "duplicate")
            self.assertEqual(
                actions,
                [("send", "updated"), ("delete", 10)],
            )

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
