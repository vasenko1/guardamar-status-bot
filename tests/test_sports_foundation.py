import unittest
from dataclasses import fields
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.models import Event
from telegrambot.morning import _merge_events, _morning_events_without_sport
from telegrambot.sports_presentation import (
    split_sport_events,
    sport_display_title,
    sport_is_plannable,
    sport_presentation,
)


MADRID = ZoneInfo("Europe/Madrid")
WHEN = datetime(2026, 10, 17, 18, 0, tzinfo=MADRID)


class SportsFoundationTests(unittest.TestCase):
    def test_slice_e_appends_status_after_existing_sport_slot(self):
        event = Event("Событие", WHEN)
        field_names = [field.name for field in fields(Event)]

        self.assertEqual(
            field_names.index("sport"),
            field_names.index("programme_display_title") + 1,
        )
        self.assertEqual(field_names[-1], "occurrence_status")
        self.assertIsNone(event.sport)
        self.assertIsNone(event.occurrence_status)

    def test_merge_preserves_source_proven_occurrence_status(self):
        first = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
            sport="chess",
        )
        correction = Event(
            "Турнир Guardamar",
            WHEN,
            place="Centro Social",
            occurrence_status="cancelled",
            sport="chess",
        )

        merged = _merge_events((first,), (correction,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].occurrence_status, "cancelled")

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

    def test_mixed_programme_parent_is_not_duplicated_into_sports(self):
        programme = "Fiestas del Barrio"
        ordinary = Event(
            "Concierto",
            WHEN,
            programme_title=programme,
            programme_order=1,
        )
        sport = Event(
            "Carrera",
            WHEN,
            programme_title=programme,
            programme_order=2,
            sport="chess",
        )

        ordinary_events, sports = split_sport_events((ordinary, sport))

        self.assertEqual(ordinary_events[0].programme_title, programme)
        self.assertIsNone(sports[0].programme_title)
        self.assertIn("♟ Шахматы — Carrera", sports[0].title)

    def test_wholly_sport_programme_keeps_group_identity(self):
        first = Event(
            "Ronda 1",
            WHEN,
            programme_title="Open local",
            programme_order=1,
            sport="chess",
        )
        second = Event(
            "Ronda 2",
            WHEN,
            programme_title="Open local",
            programme_order=2,
            sport="chess",
        )

        ordinary, sports = split_sport_events((first, second))

        self.assertEqual(ordinary, ())
        self.assertEqual(
            {event.programme_title for event in sports},
            {"Open local"},
        )

    def test_cancelled_sport_is_not_plannable(self):
        event = Event(
            "Mar Costa",
            WHEN,
            occurrence_status="cancelled",
            sport="fishing",
        )

        self.assertFalse(sport_is_plannable(event))
        self.assertTrue(sport_is_plannable(Event("Шахматы", WHEN, sport="chess")))

    def test_morning_filter_removes_only_sports(self):
        events = (
            Event("Концерт", WHEN),
            Event("Open Dama", WHEN, sport="chess"),
        )

        self.assertEqual(
            _morning_events_without_sport(events),
            (events[0],),
        )

    def test_only_accepted_codes_are_supported(self):
        self.assertEqual(sport_presentation("fishing").label_ru, "Спортивная рыбалка")
        with self.assertRaisesRegex(ValueError, "unsupported sport code"):
            sport_presentation("football")


if __name__ == "__main__":
    unittest.main()
