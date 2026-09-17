import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.facv import FACV_URL
from telegrambot.guide import GuideState
from telegrambot.pesca_cv import PESCA_CV_URL
from telegrambot.pinned import (
    PinnedGuideState,
    build_root,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.state import StateError


MADRID = ZoneInfo("Europe/Madrid")


def _sports_catalog():
    observed = datetime(2026, 9, 17, 18, 0, tzinfo=MADRID).isoformat()
    return {
        "observed_at": observed,
        "facv": {"observed_at": observed, "events": []},
        "pesca_cv": {
            "observed_at": observed,
            "events": [
                {
                    "sport": "fishing",
                    "title": "MAR COSTA",
                    "start": "2026-10-17",
                    "end": "2026-10-17",
                    "place": "Guardamar · Zona B - Centro, La Roqueta Y Moncayo",
                    "organizer": "DELEGACIÓ PROV. ALACANT",
                    "level": "PROVINCIAL",
                    "source_url": PESCA_CV_URL,
                },
                {
                    "sport": "fishing",
                    "title": "Mar Costa Dúos",
                    "start": "2026-11-23",
                    "end": "2026-11-29",
                    "place": "Guardamar · Playa",
                    "organizer": "FED. ESPAÑOLA PESCA Y C.",
                    "level": "NACIONAL",
                    "source_url": PESCA_CV_URL,
                },
            ],
        },
    }


class SportsGuideIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_root_adds_sports_events_only_when_link_exists(self):
        base = build_root()
        linked = build_root(sports_events_link="https://t.me/c/1/777")
        self.assertNotIn("Спортивные мероприятия", base)
        self.assertIn("🏆", linked)
        self.assertIn("Спортивные мероприятия", linked)
        self.assertIn("https://t.me/c/1/777", linked)

    async def test_publish_creates_one_aggregate_card_and_links_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            edit = AsyncMock()
            pin = AsyncMock()
            messages = await publish_pinned_guide(
                "-100123",
                state,
                send,
                edit,
                pin,
                sports_events_catalog=_sports_catalog(),
                local_day=date(2026, 9, 17),
            )

            self.assertIn("sports_events", messages)
            sports_id = messages["sports_events"]
            root_id = messages["root"]
            self.assertIn("🏆 <b>Спортивные мероприятия</b>", sent[sports_id - 1])
            self.assertIn("17 октября 2026", sent[sports_id - 1])
            self.assertIn("23–29 ноября 2026", sent[sports_id - 1])

            sports_link = telegram_message_link("-100123", sports_id)
            root_edits = [
                call.args[1]
                for call in edit.await_args_list
                if call.args[0] == root_id
            ]
            self.assertTrue(any(sports_link in text for text in root_edits))
            pin.assert_awaited_with(root_id)

    async def test_no_events_do_not_create_a_new_sports_card(self):
        observed = datetime(2026, 9, 17, 18, 0, tzinfo=MADRID).isoformat()
        empty_catalog = {
            "observed_at": observed,
            "facv": {"observed_at": observed, "events": []},
        }
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            messages = await publish_pinned_guide(
                "-100123",
                state,
                send,
                AsyncMock(),
                AsyncMock(),
                sports_events_catalog=empty_catalog,
                local_day=date(2026, 9, 17),
            )
            self.assertNotIn("sports_events", messages)
            self.assertFalse(
                any("🏆 <b>Спортивные мероприятия</b>" in item for item in sent)
            )


class SportsGuideStateTests(unittest.TestCase):
    def test_sports_catalog_and_attempt_day_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            state = GuideState(Path(directory) / "guide.json")
            state.write(
                {
                    "sports_events_catalog": _sports_catalog(),
                    "sports_events_last_attempt_day": "2026-09-17",
                }
            )
            loaded = state.read()
            self.assertEqual(
                loaded["sports_events_last_attempt_day"], "2026-09-17"
            )
            self.assertIn("pesca_cv", loaded["sports_events_catalog"])

    def test_invalid_sports_attempt_day_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state = GuideState(Path(directory) / "guide.json")
            state.write({"sports_events_last_attempt_day": "17-09-2026"})
            with self.assertRaises(StateError):
                state.read()


if __name__ == "__main__":
    unittest.main()
