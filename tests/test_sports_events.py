import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.sports_events import (
    build_sports_events_card,
    current_sports_events,
    valid_sports_events_catalog,
)
from telegrambot.facv import FACV_URL
from telegrambot.pesca_cv import PESCA_CV_URL


MADRID = ZoneInfo("Europe/Madrid")


class SportsEventsTests(unittest.TestCase):
    def _catalog(self):
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
                        "end": "2026-11-28",
                        "place": "Guardamar · Playa",
                        "organizer": "FED. ESPAÑOLA PESCA Y C.",
                        "level": "NACIONAL",
                        "source_url": PESCA_CV_URL,
                    }
                ],
            },
        }

    def test_catalog_and_card_are_compact_activity_first_output(self):
        catalog = self._catalog()
        self.assertTrue(valid_sports_events_catalog(catalog))
        events = current_sports_events(catalog, date(2026, 9, 17))
        self.assertEqual([item["sport"] for item in events], ["chess", "fishing"])
        text = build_sports_events_card(events, "https://t.me/c/1/99")
        self.assertIn("🏆 <b>Спортивные мероприятия</b>", text)
        self.assertIn("♟ <b>Open Futuro</b>", text)
        self.assertIn("🎣 <b>Mar Costa Dúos</b>", text)
        self.assertIn("23–28 ноября 2026", text)
        self.assertIn("https://t.me/c/1/99", text)
        self.assertEqual(text.count(FOOTER), 1)
        self.assertNotIn("Club Dama", text)
        self.assertNotIn("FED. ESPAÑOLA PESCA Y C.", text)
        self.assertLess(len(text), 4096)

    def test_past_events_drop_from_last_good_snapshot(self):
        catalog = self._catalog()
        events = current_sports_events(catalog, date(2026, 11, 29))
        self.assertEqual(events, ())

    def test_empty_card_is_quiet_and_durable(self):
        text = build_sports_events_card(())
        self.assertIn("Сейчас ближайшие мероприятия", text)
        self.assertEqual(text.count(FOOTER), 1)


if __name__ == "__main__":
    unittest.main()
