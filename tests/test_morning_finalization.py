import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.delivery import publish_morning
from telegrambot.state import PublicationState, StateError


MADRID = ZoneInfo("Europe/Madrid")


class MorningFinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalizer_runs_after_record_creation_under_same_state_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            state = PublicationState(path)
            competitor = PublicationState(path)
            now = datetime(2026, 9, 14, 7, 30, tzinfo=MADRID)
            observed = []

            async def produce():
                return "morning"

            async def deliver(message):
                self.assertEqual(message, "morning")
                return 101

            async def finalize():
                observed.append(state.morning_record(now.date())["morning_message_id"])
                with self.assertRaises(StateError):
                    with competitor.exclusive_run():
                        pass
                state.mark_morning_environment(
                    now.date(), 2, None, cold_level=1
                )

            result = await publish_morning(
                now, state, produce, deliver, finalize
            )

            self.assertEqual(result, "success")
            self.assertEqual(observed, [101])
            self.assertEqual(
                state.morning_environment(now.date())[:2],
                (2, 1),
            )

    async def test_finalizer_failure_does_not_reclassify_delivered_morning(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 9, 14, 7, 30, tzinfo=MADRID)

            async def finalize():
                raise OSError("snapshot storage unavailable")

            result = await publish_morning(
                now,
                state,
                lambda: _return("morning"),
                lambda message: _return(101),
                finalize,
            )

            self.assertEqual(result, "success")
            self.assertEqual(
                state.morning_record(now.date())["morning_message_id"],
                101,
            )


async def _return(value):
    return value


if __name__ == "__main__":
    unittest.main()
