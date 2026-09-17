import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.digest import build_event_section
from telegrambot.models import Event
from telegrambot.morning import _merge_events

MADRID = ZoneInfo("Europe/Madrid")


class FederationEventPipelineTests(unittest.TestCase):
    def test_same_federation_and_municipal_event_is_not_duplicated(self):
        municipal = Event(
            title="Open Dama Guardamar",
            starts_at=None,
            place="Guardamar del Segura",
            active_until=date(2026, 9, 20),
        )
        federation = Event(
            title="Open Dama Guardamar",
            starts_at=None,
            place="Guardamar del Segura",
            active_until=date(2026, 9, 20),
        )

        merged = _merge_events((municipal,), (federation,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Open Dama Guardamar")

    def test_realistic_duplicate_keeps_municipal_time_and_federation_range(self):
        municipal = Event(
            title="Open Dama Guardamar 2026",
            starts_at=datetime(2026, 9, 20, 10, 0, tzinfo=MADRID),
            place="Guardamar del Segura",
        )
        federation = Event(
            title="Open Dama Guardamar",
            starts_at=None,
            place="Guardamar del Segura",
            active_until=date(2026, 9, 20),
            is_final_day=True,
        )

        merged = _merge_events((municipal,), (federation,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0].starts_at,
            datetime(2026, 9, 20, 10, 0, tzinfo=MADRID),
        )
        self.assertEqual(merged[0].active_until, date(2026, 9, 20))
        self.assertTrue(merged[0].is_final_day)

    def test_final_day_does_not_repeat_active_until_date(self):
        event = Event(
            title="Mar Costa Dúos",
            starts_at=None,
            place="Guardamar · Playa",
            active_until=date(2026, 11, 29),
            is_final_day=True,
        )

        rendered = "\n".join(build_event_section(
            (event,), "📅 <b>События дня:</b>"
        ))

        self.assertIn("Последний день: Mar Costa Dúos", rendered)
        self.assertNotIn("До 29 ноября", rendered)

    def test_distinct_federation_events_remain_distinct(self):
        chess = Event(
            title="Open Dama Guardamar",
            starts_at=None,
            place="Guardamar del Segura",
        )
        fishing = Event(
            title="Mar Costa Dúos",
            starts_at=None,
            place="Guardamar · Playa",
        )

        merged = _merge_events((chess,), (fishing,))

        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
