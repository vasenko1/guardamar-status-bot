import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.sports_notifications import SportsNotificationError
from telegrambot.sports_notifications_runner import _accepted_catalog, run


MADRID = ZoneInfo("Europe/Madrid")


def _catalog(moment):
    return {"observed_at": moment.isoformat(), "activities": []}


class SportsNotificationRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_guide_state_means_no_accepted_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(_accepted_catalog(Path(directory) / "missing.json"))

    def test_invalid_guide_sporttia_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            path.write_text(
                json.dumps({"version": 1, "sporttia_catalog": {"bad": True}}),
                encoding="utf-8",
            )
            with self.assertRaises(SportsNotificationError):
                _accepted_catalog(path)

    async def test_runner_only_passes_accepted_local_state_to_notification_sync(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        accepted = _catalog(moment)
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
                "telegrambot.sports_notifications_runner._accepted_catalog",
                return_value=accepted,
            ) as read_catalog,
            patch(
                "telegrambot.sports_notifications_runner.PinnedGuideState.read",
                return_value={"judo": 500},
            ) as read_pinned,
            patch(
                "telegrambot.sports_notifications_runner.sync_sports_notifications",
                new=sync,
            ),
        ):
            result = await run(moment)

        self.assertEqual(result, "baseline")
        read_catalog.assert_called_once_with(Path("/tmp/guide.json"))
        read_pinned.assert_called_once_with("-100123")
        sync.assert_awaited_once_with(
            "token",
            "-100123",
            accepted,
            {"judo": 500},
            moment,
        )


if __name__ == "__main__":
    unittest.main()
