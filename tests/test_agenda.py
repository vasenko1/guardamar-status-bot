import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.agenda import (
    extract_event_links,
    normalize_event_page,
    recurring_events,
    requires_market_exception_check,
)


class AgendaNormalizationTests(unittest.TestCase):
    def test_extracts_unique_official_event_links(self):
        payload = b"""
        <a href="/espectaculo/48/concierto.html">One</a>
        <a href="//www.agendaguardamar.com/espectaculo/48/concierto.html">
          Duplicate
        </a>
        <a href="https://example.com/espectaculo/1/other.html">Other</a>
        """

        self.assertEqual(
            extract_event_links(payload),
            (
                "https://www.agendaguardamar.com/"
                "espectaculo/48/concierto.html",
            ),
        )

    def test_normalizes_only_event_scheduled_today(self):
        payload = b"""
        <script type="application/ld+json">
        {
          "@type": "TheaterEvent",
          "name": "SPANISH BRASS. TOP SECRET",
          "startDate": "2026-08-05T22:00",
        }
        </script>
        """

        event = normalize_event_page(payload, date(2026, 8, 5))

        self.assertIsNotNone(event)
        self.assertEqual(event.title, "SPANISH BRASS. TOP SECRET")
        self.assertEqual(event.starts_at.hour, 22)
        self.assertIsNone(
            normalize_event_page(payload, date(2026, 8, 6))
        )

    def test_adds_official_market_only_on_wednesdays(self):
        timezone = ZoneInfo("Europe/Madrid")

        events = recurring_events(
            datetime(2026, 7, 29, 8, 0, tzinfo=timezone)
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Рынок")
        self.assertEqual(events[0].place, "парковка La Redonda")
        self.assertEqual(events[0].starts_at.hour, 7)
        self.assertEqual(events[0].ends_at.hour, 13)
        self.assertEqual(events[0].ends_at.minute, 30)
        self.assertEqual(
            recurring_events(
                datetime(2026, 7, 30, 8, 0, tzinfo=timezone)
            ),
            (),
        )

        winter = recurring_events(
            datetime(2026, 12, 2, 8, 0, tzinfo=timezone)
        )
        self.assertEqual(winter[0].starts_at.hour, 8)

    def test_moves_market_to_tuesday_before_a_holiday_wednesday(self):
        timezone = ZoneInfo("Europe/Madrid")

        moved = recurring_events(
            datetime(2026, 6, 23, 8, 0, tzinfo=timezone)
        )

        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].title, "Рынок")
        self.assertEqual(
            recurring_events(
                datetime(2026, 6, 24, 8, 0, tzinfo=timezone)
            ),
            (),
        )

    def test_omits_market_when_annual_calendar_is_not_reviewed(self):
        timezone = ZoneInfo("Europe/Madrid")

        self.assertEqual(
            recurring_events(
                datetime(2027, 7, 28, 8, 0, tzinfo=timezone)
            ),
            (),
        )

    def test_adds_campo_market_every_sunday(self):
        timezone = ZoneInfo("Europe/Madrid")

        events = recurring_events(
            datetime(2026, 8, 2, 8, 0, tzinfo=timezone)
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Рынок Campo de Guardamar")
        self.assertEqual(events[0].starts_at.hour, 7)
        self.assertEqual(events[0].ends_at.hour, 16)
        self.assertEqual(events[0].place, "Camino del Raso, 15")
        self.assertFalse(
            requires_market_exception_check(
                datetime(2026, 8, 2, 8, 0, tzinfo=timezone)
            )
        )


if __name__ == "__main__":
    unittest.main()
