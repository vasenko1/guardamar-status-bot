import unittest
from datetime import date, datetime
from email.message import Message
from zoneinfo import ZoneInfo
from unittest.mock import patch

from telegrambot.agenda import (
    AgendaError,
    _read_page,
    extract_event_links,
    fetch_today_events,
    normalize_event_page,
    recurring_events,
    requires_market_exception_check,
)


class _Response:
    status = 200

    def __init__(
        self,
        payload=b"<html></html>",
        content_type="text/html",
        url="https://www.agendaguardamar.com/page.html",
    ):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return self.payload[:limit]

    def geturl(self):
        return self.url


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


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
          "endDate": "2026-08-05T23:30",
          "location": {"@type": "Place", "name": "Castillo"}
        }
        </script>
        """

        event = normalize_event_page(payload, date(2026, 8, 5))

        self.assertIsNotNone(event)
        self.assertEqual(event.title, "SPANISH BRASS. TOP SECRET")
        self.assertEqual(event.starts_at.hour, 22)
        self.assertEqual(event.ends_at.hour, 23)
        self.assertEqual(event.ends_at.minute, 30)
        self.assertEqual(event.place, "Castillo")
        self.assertIsNone(
            normalize_event_page(payload, date(2026, 8, 6))
        )

    def test_reads_nested_json_ld_graph_but_not_unrelated_json(self):
        payload = b"""
        <script>window.data = {"name": "Wrong"};</script>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [{
            "@type": "Event",
            "name": "Official event",
            "startDate": "2026-08-05T19:30",
            "location": {"name": "Casa de Cultura"}
          }]
        }
        </script>
        """

        event = normalize_event_page(payload, date(2026, 8, 5))

        self.assertIsNotNone(event)
        self.assertEqual(event.title, "Official event")
        self.assertEqual(event.place, "Casa de Cultura")

    def test_rejects_non_event_json_ld_and_omits_publisher_place(self):
        non_event = b"""
        <script type="application/ld+json">
        {"@type":"Offer","name":"Not an event",
         "startDate":"2026-08-05T19:30"}
        </script>
        """
        event = b"""
        <script type="application/ld+json">
        {"@type":"TheaterEvent","name":"Guided tour",
         "startDate":"2026-08-05T19:30",
         "location":{"name":"ayuntamientoguardamardelsegura"}}
        </script>
        """

        self.assertIsNone(
            normalize_event_page(non_event, date(2026, 8, 5))
        )
        normalized = normalize_event_page(event, date(2026, 8, 5))
        self.assertIsNotNone(normalized)
        self.assertIsNone(normalized.place)

    def test_repairs_only_known_official_json_ld_punctuation(self):
        payload = b"""
        <script type="application/ld+json">
        {
          "@type": "TheaterEvent",
          "name": "Official malformed event",
          "location": {"name": "Castillo"},"
          "startDate": "2026-08-05T22:00",
          "workPerformed": {"name": "Official malformed event",}
        }
        </script>
        """

        event = normalize_event_page(payload, date(2026, 8, 5))

        self.assertIsNotNone(event)
        self.assertEqual(event.title, "Official malformed event")
        self.assertEqual(event.starts_at.hour, 22)

    def test_json_repair_does_not_modify_text_inside_strings(self):
        payload = b"""
        <script type="application/ld+json">
        {
          "@type": "Event",
          "name": "Comma,} stays",
          "startDate": "2026-08-05T22:00",
          "keywords": ["one",],
        }
        </script>
        """

        event = normalize_event_page(payload, date(2026, 8, 5))

        self.assertIsNotNone(event)
        self.assertEqual(event.title, "Comma,} stays")

    def test_wraps_low_level_read_failure_as_source_error(self):
        class BrokenResponse(_Response):
            def read(self, limit):
                raise OSError("connection reset")

        with patch(
            "telegrambot.agenda.urllib.request.build_opener",
            return_value=_Opener(BrokenResponse()),
        ):
            with self.assertRaises(AgendaError) as raised:
                _read_page(
                    "https://www.agendaguardamar.com/page.html"
                )

        self.assertEqual(raised.exception.diagnostic_code, "NETWORK")

    def test_rejects_non_html_agenda_response(self):
        with patch(
            "telegrambot.agenda.urllib.request.build_opener",
            return_value=_Opener(
                _Response(content_type="application/json")
            ),
        ):
            with self.assertRaises(AgendaError) as raised:
                _read_page(
                    "https://www.agendaguardamar.com/page.html"
                )

        self.assertEqual(
            raised.exception.diagnostic_code,
            "CONTENT-TYPE",
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


class AgendaCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_when_all_event_pages_fail(self):
        index = (
            b'<a href="/espectaculo/1/a.html">A</a>'
            b'<a href="/espectaculo/2/b.html">B</a>'
        )

        def read_page(url):
            if url.endswith("PROGRAMACION-ESPECTACULOS.html"):
                return index
            raise AgendaError("unavailable", code="HTTP-503")

        with patch(
            "telegrambot.agenda._read_page",
            side_effect=read_page,
        ):
            with self.assertRaises(AgendaError) as raised:
                await fetch_today_events(
                    datetime(
                        2026,
                        8,
                        5,
                        7,
                        tzinfo=ZoneInfo("Europe/Madrid"),
                    )
                )

        self.assertEqual(
            raised.exception.diagnostic_code,
            "DETAILS-UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
