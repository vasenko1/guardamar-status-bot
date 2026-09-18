import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.recurring_notifications import RecurringNotificationError
from telegrambot.recurring_notifications_runner import (
    _accepted_snapshots,
    run,
)


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 18, 16, 30, tzinfo=MADRID)


def chess():
    return {
        "observed_at": NOW.isoformat(),
        "source_url": "https://ajedrezdamadeguardamar.com/cuotas/",
        "days": ["tuesday", "thursday"],
        "start_time": "16:00",
        "end_time": "20:00",
        "level_from": "INICIACIÓN",
        "level_to": "AVANZADO",
    }


class RecurringNotificationRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_guide_state_returns_no_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _accepted_snapshots(Path(directory) / "missing.json")
        self.assertEqual(result, {})

    def test_invalid_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            path.write_text(
                json.dumps({
                    "version": 1,
                    "chess_school_snapshot": {"bad": True},
                }),
                encoding="utf-8",
            )
            with self.assertRaises(RecurringNotificationError):
                _accepted_snapshots(path)

    async def test_runner_only_passes_accepted_local_state(self):
        snapshots = {"chess": chess()}
        sync = AsyncMock(return_value="baseline")
        with (
            patch.dict(
                "os.environ",
                {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "-100123",
                    "GUIDE_STATE_PATH": "/tmp/guide.json",
                    "PINNED_GUIDE_STATE_PATH": "/tmp/pinned.json",
                },
                clear=False,
            ),
            patch(
                "telegrambot.recurring_notifications_runner._accepted_snapshots",
                return_value=snapshots,
            ) as accepted,
            patch(
                "telegrambot.recurring_notifications_runner.PinnedGuideState.read",
                return_value={"chess": 501},
            ) as pinned,
            patch(
                "telegrambot.recurring_notifications_runner.sync_recurring_notifications",
                new=sync,
            ),
        ):
            result = await run(NOW)

        self.assertEqual(result, "baseline")
        accepted.assert_called_once_with(Path("/tmp/guide.json"))
        pinned.assert_called_once_with("-100123")
        sync.assert_awaited_once_with(
            "token",
            "-100123",
            snapshots,
            {"chess": 501},
            NOW,
        )


if __name__ == "__main__":
    unittest.main()
