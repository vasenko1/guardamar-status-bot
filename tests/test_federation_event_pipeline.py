import unittest
from datetime import date

from telegrambot.models import Event
from telegrambot.morning import _merge_events


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
