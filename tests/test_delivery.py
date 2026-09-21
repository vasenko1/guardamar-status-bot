import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.delivery import (
    publish_morning,
    publish_update,
    refresh_beach_root,
)
from telegrambot.models import BeachNotice, BeachStatus
from telegrambot.state import PublicationState
from telegrambot.telegram import TelegramError

MADRID = ZoneInfo("Europe/Madrid")


class DeliveryRunTests(unittest.IsolatedAsyncioTestCase):
    def _partial_status(self, now, names):
        return BeachStatus(
            flag_color="yellow" if "Centre" in names else None,
            sea_temperature_c=27 if "Centre" in names else None,
            source_date=now.date(),
            nearby_flags=tuple((name, "yellow") for name in names),
            updated_times=tuple(
                (name, now.time().replace(second=0, microsecond=0))
                for name in names
            ),
        )

    async def test_beach_root_refreshes_without_duplicate_and_recreates_if_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
            state.mark_morning(now.date(), 10, now)
            notice = BeachNotice("Купание запрещено", True, now)
            first = self._partial_status(now, ("Centre",))
            fuller = self._partial_status(now, ("Centre", "Roqueta"))
            sent = AsyncMock(side_effect=[20, 30])
            edited = AsyncMock()
            render = lambda status, saved_notice: (
                f"root {status.nearby_flags} {saved_notice.text if saved_notice else ''}"
            )

            self.assertEqual((await refresh_beach_root(
                now, state, first, notice, render, sent, edited
            )), ("created", 20))
            self.assertEqual((await refresh_beach_root(
                now, state, fuller, None, render, sent, edited
            )), ("refreshed", 20))
            sent.assert_awaited_once()
            self.assertIn("Купание запрещено", edited.await_args.args[1])
            self.assertEqual(
                state.beach_root_facts(now.date())[0].nearby_flags,
                fuller.nearby_flags,
            )

            edited.side_effect = TelegramError(
                "gone", retryable=False, code="MESSAGE-NOT-FOUND", status=400
            )
            self.assertEqual((await refresh_beach_root(
                now, state, fuller, None, render, sent, edited
            )), ("created", 30))
            self.assertEqual(state.beach_message_id(now.date()), 30)

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
                return 10

            first = await publish_morning(
                now, state, produce, deliver
            )
            second = await publish_morning(
                now, state, produce, deliver
            )

            self.assertEqual(first, "success")
            self.assertEqual(second, "duplicate")
            self.assertEqual(calls, {"produce": 1, "deliver": 1})
            self.assertEqual(
                state.last_successful_date(),
                now.date(),
            )
            self.assertEqual(
                state.morning_record(now.date())["morning_message_id"],
                10,
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
                return 10

            result = await publish_morning(
                now, state, produce, deliver
            )

            self.assertEqual(result, "failure")
            self.assertFalse(delivered)
            self.assertIsNone(state.last_successful_date())

    async def test_update_waits_for_safebeach_before_final_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            morning = datetime(2026, 7, 29, 7, 30, tzinfo=MADRID)
            state.mark_morning(morning.date(), 10, morning)
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

    async def test_new_environment_data_can_trigger_update_without_beach(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            morning = datetime(2026, 7, 29, 7, 30, tzinfo=MADRID)
            state.mark_morning(morning.date(), 10, morning)
            delivered = []

            async def deliver(message):
                delivered.append(message)
                return 20

            async def no_notice(since):
                return None

            async def produce(beach, notice):
                return "updated environment"

            async def delete(message_id):
                return None

            result = await publish_update(
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID),
                state,
                None,
                False,
                no_notice,
                produce,
                deliver,
                delete,
                force_update=True,
            )

            self.assertEqual(result, "success")
            self.assertEqual(delivered, ["updated environment"])

    async def test_update_sends_first_then_deletes_and_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            morning = datetime(2026, 7, 29, 7, 30, tzinfo=MADRID)
            state.mark_morning(morning.date(), 10, morning)
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

            first = await publish_morning(
                now, state, produce, deliver
            )
            second = await publish_morning(
                now, state, produce, deliver
            )

            self.assertEqual(first, "failure")
            self.assertEqual(second, "failure")
            self.assertEqual(attempts, 2)
            self.assertIsNone(state.last_successful_date())


if __name__ == "__main__":
    unittest.main()
