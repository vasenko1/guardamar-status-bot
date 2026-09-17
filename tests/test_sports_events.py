import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.facv import FACV_URL, FacvSourceError
from telegrambot.pesca_cv import PESCA_CV_URL, PescaCvSourceError
from telegrambot.sports_events import (
    build_sports_events_card,
    current_sports_events,
    refresh_sports_events_catalog,
    valid_sports_events_catalog,
)


MADRID = ZoneInfo("Europe/Madrid")


def _catalog():
    observed = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID).isoformat()
    return {
        "observed_at": observed,
        "facv": {
            "observed_at": observed,
            "events": [
                {
                    "sport": "chess",
                    "title": "Open Futuro",
                    "start": "2026-10-03",
                    "end": "2026-10-03",
                    "place": "Guardamar del Segura",
                    "organizer": "Club Dama",
                    "source_url": FACV_URL,
                }
            ],
        },
        "pesca_cv": {
            "observed_at": observed,
            "events": [
                {
                    "sport": "fishing",
                    "title": "Mar Costa Dúos",
                    "start": "2026-11-23",
                    "end": "2026-11-29",
                    "place": "Guardamar · Playa",
                    "organizer": "FED. ESPAÑOLA PESCA Y C.",
                    "level": "NACIONAL",
                    "source_url": PESCA_CV_URL,
                }
            ],
        },
    }


class SportsEventsTests(unittest.TestCase):
    def test_catalog_and_card_are_compact_activity_first_output(self):
        catalog = _catalog()
        self.assertTrue(valid_sports_events_catalog(catalog))
        events = current_sports_events(catalog, date(2026, 9, 17))
        self.assertEqual([item["sport"] for item in events], ["chess", "fishing"])
        text = build_sports_events_card(events, "https://t.me/c/1/99")
        self.assertIn("🏆 <b>Спортивные мероприятия</b>", text)
        self.assertIn("♟ <b>Open Futuro</b>", text)
        self.assertIn("🎣 <b>Mar Costa Dúos</b>", text)
        self.assertIn("23–29 ноября 2026", text)
        self.assertIn("Источник и подробности", text)
        self.assertIn("https://t.me/c/1/99", text)
        self.assertEqual(text.count(FOOTER), 1)
        self.assertNotIn("Club Dama", text)
        self.assertNotIn("FED. ESPAÑOLA PESCA Y C.", text)
        self.assertLess(len(text), 4096)

    def test_past_events_drop_from_last_good_snapshot(self):
        events = current_sports_events(_catalog(), date(2026, 11, 30))
        self.assertEqual(events, ())

    def test_empty_card_is_quiet_and_durable(self):
        text = build_sports_events_card(())
        self.assertIn("Сейчас ближайшие мероприятия", text)
        self.assertEqual(text.count(FOOTER), 1)


class SportsEventsRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_source_failures_preserve_exact_previous_observation(self):
        previous = _catalog()
        now = datetime(2026, 9, 18, 8, 0, tzinfo=MADRID)
        with patch(
            "telegrambot.sports_events.fetch_facv_snapshot",
            AsyncMock(side_effect=FacvSourceError("offline", code="HTTP")),
        ), patch(
            "telegrambot.sports_events.fetch_pesca_cv_snapshot",
            AsyncMock(side_effect=PescaCvSourceError("offline", code="HTTP")),
        ):
            refreshed = await refresh_sports_events_catalog(previous, now)
        self.assertEqual(refreshed, previous)
        self.assertEqual(refreshed["observed_at"], previous["observed_at"])

    async def test_one_success_refreshes_catalog_and_retains_other_last_good(self):
        previous = _catalog()
        now = datetime(2026, 9, 18, 8, 0, tzinfo=MADRID)
        facv = {
            "observed_at": now.isoformat(),
            "events": [],
        }
        with patch(
            "telegrambot.sports_events.fetch_facv_snapshot",
            AsyncMock(return_value=facv),
        ), patch(
            "telegrambot.sports_events.fetch_pesca_cv_snapshot",
            AsyncMock(side_effect=PescaCvSourceError("offline", code="HTTP")),
        ):
            refreshed = await refresh_sports_events_catalog(previous, now)
        self.assertEqual(refreshed["observed_at"], now.isoformat())
        self.assertEqual(refreshed["facv"], facv)
        self.assertEqual(refreshed["pesca_cv"], previous["pesca_cv"])


if __name__ == "__main__":
    unittest.main()
