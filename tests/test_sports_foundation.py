import unittest
from dataclasses import fields
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.models import Event
from telegrambot.morning import _merge_events
from telegrambot.sports_presentation import (
    sport_display_title,
    sport_presentation,
)


MADRID = ZoneInfo("Europe/Madrid")
WHEN = datetime(2026, 10, 17, 18, 0, tzinfo=MADRID)


class SportsFoundationTests(unittest.TestCase):
    def test_sport_is_last_optional_event_field(self):
        event = Event("Событие", WHEN)

        self.assertEqual(fields(Event)[-1].name, "sport")
        self.assertIsNone(event.sport)

    def test_merge_preserves_known_sport_from_matching_event(self):
        municipal = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
        )
        federation = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
            sport="chess",
        )

        merged = _merge_events((municipal,), (federation,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].sport, "chess")

    def test_merge_does_not_join_different_known_sports(self):
        chess = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
            sport="chess",
        )
        fishing = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
            sport="fishing",
        )

        merged = _merge_events((chess,), (fishing,))

        self.assertEqual(len(merged), 2)
        self.assertEqual({event.sport for event in merged}, {"chess", "fishing"})

    def test_merge_still_joins_same_sport_duplicates(self):
        first = Event(
            "Open Dama",
            WHEN,
            place="Centro Social",
            sport="chess",
        )
        second = Event(
            "Open Dama Guardamar",
            WHEN,
            place="Centro Social",
            details=("Partidas rápidas",),
            sport="chess",
        )

        merged = _merge_events((first,), (second,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].sport, "chess")
        self.assertEqual(merged[0].details, ("Partidas rápidas",))

    def test_presentation_is_deterministic_and_does_not_mutate_source_title(self):
        event = Event(
            "Open Dama Guardamar",
            WHEN,
            sport="chess",
        )

        title = sport_display_title(event)

        self.assertEqual(title, "♟ Шахматы — Open Dama Guardamar")
        self.assertEqual(event.title, "Open Dama Guardamar")
        self.assertEqual(event.sport, "chess")

    def test_non_sport_title_is_unchanged(self):
        event = Event("Концерт", WHEN)

        self.assertEqual(sport_display_title(event), "Концерт")

    def test_only_accepted_codes_are_supported(self):
        self.assertEqual(sport_presentation("fishing").label_ru, "Спортивная рыбалка")
        with self.assertRaisesRegex(ValueError, "unsupported sport code"):
            sport_presentation("football")


if __name__ == "__main__":
    unittest.main()
