import unittest
from datetime import date

from telegrambot.course_notifications import (
    CourseNotificationError,
    _empty_state,
    _record,
    build_message,
    collect_changes,
)


def record(
    record_id="sporttia:1",
    source="sporttia",
    course_key="sporttia:judo",
    card_key="judo",
    title="Дзюдо",
    emoji="🥋",
    group="1-я группа",
    observed_day="2026-09-20",
    registrations=(),
    until_full=False,
    schedule="Вт/Чт · 18:00–19:00",
    venue="Palau Sant Jaume",
    audience="7–12 лет",
):
    return _record(
        record_id=record_id,
        source=source,
        course_key=course_key,
        card_key=card_key,
        title=title,
        emoji=emoji,
        group=group,
        observed_day=observed_day,
        registrations=registrations,
        until_full=until_full,
        schedule=schedule,
        venue=venue,
        audience=audience,
    )


def baseline_state(*records):
    state = _empty_state()
    state["baseline"] = {item["record_id"]: item for item in records}
    state["known_sources"] = sorted({item["source"] for item in records})
    state["known_course_keys"] = sorted({item["course_key"] for item in records})
    state["known_record_ids"] = sorted(item["record_id"] for item in records)
    return state


class CourseNotificationCollectionTests(unittest.TestCase):
    def test_first_run_is_silent_baseline(self):
        current = record(
            registrations=[{"start": "2026-09-20", "end": "2026-09-30"}],
        )
        result = collect_changes(
            {current["record_id"]: current},
            {"sporttia"},
            _empty_state(),
            date(2026, 9, 20),
            {"judo": 501},
        )
        self.assertIsNone(result["pending"])
        self.assertIn(current["record_id"], result["baseline"])

    def test_opening_and_closing_are_separate_semantic_messages(self):
        opening = record(
            registrations=[{"start": "2026-09-20", "end": "2026-09-30"}],
        )
        closing = record(
            record_id="sporttia:2",
            course_key="sporttia:multisport",
            card_key="multisport",
            title="Мультиспорт",
            emoji="🏃",
            registrations=[{"start": "2026-09-01", "end": "2026-09-20"}],
        )
        previous_opening = record(registrations=[
            {"start": "2026-09-20", "end": "2026-09-30"}
        ])
        previous_closing = record(
            record_id="sporttia:2",
            course_key="sporttia:multisport",
            card_key="multisport",
            title="Мультиспорт",
            emoji="🏃",
            registrations=[{"start": "2026-09-01", "end": "2026-09-20"}],
        )
        state = baseline_state(previous_opening, previous_closing)
        result = collect_changes(
            {
                opening["record_id"]: opening,
                closing["record_id"]: closing,
            },
            {"sporttia"},
            state,
            date(2026, 9, 20),
            {"judo": 501, "multisport": 502},
        )
        kinds = [item["kind"] for item in result["pending"]["messages"]]
        self.assertEqual(
            kinds,
            ["registration_closing", "registration_opening"],
        )

    def test_single_day_registration_is_only_opening_message(self):
        current = record(registrations=[
            {"start": "2026-09-20", "end": "2026-09-20"}
        ])
        state = baseline_state(current)
        result = collect_changes(
            {current["record_id"]: current},
            {"sporttia"},
            state,
            date(2026, 9, 20),
            {"judo": 501},
        )
        kinds = [item["kind"] for item in result["pending"]["messages"]]
        self.assertEqual(kinds, ["registration_opening"])
        self.assertEqual(
            result["pending"]["messages"][0]["events"][0]["type"],
            "registration_single_day",
        )

    def test_new_course_with_opening_is_not_duplicated_as_new_course(self):
        existing = record()
        current_new = record(
            record_id="sporttia:99",
            course_key="sporttia:rhythmic_gymnastics",
            card_key="rhythmic_gymnastics",
            title="Художественная гимнастика",
            emoji="🤸",
            registrations=[{"start": "2026-09-20", "end": "2026-09-28"}],
        )
        state = baseline_state(existing)
        result = collect_changes(
            {
                existing["record_id"]: existing,
                current_new["record_id"]: current_new,
            },
            {"sporttia"},
            state,
            date(2026, 9, 20),
            {"judo": 501, "rhythmic_gymnastics": 503},
        )
        kinds = [item["kind"] for item in result["pending"]["messages"]]
        self.assertEqual(kinds, ["registration_opening"])

    def test_new_source_does_not_announce_existing_catalog(self):
        existing = record()
        state = baseline_state(existing)
        new_source = record(
            record_id="future:1",
            source="future",
            course_key="future:ceramics",
            card_key="ceramics",
            title="Керамика",
            emoji="🎨",
            group=None,
            schedule=None,
            venue=None,
            audience=None,
        )
        result = collect_changes(
            {
                existing["record_id"]: existing,
                new_source["record_id"]: new_source,
            },
            {"sporttia", "future"},
            state,
            date(2026, 9, 20),
            {"judo": 501, "ceramics": 600},
        )
        self.assertIsNone(result["pending"])
        self.assertIn("future", result["known_sources"])

    def test_new_source_can_still_emit_real_same_day_opening(self):
        existing = record()
        state = baseline_state(existing)
        new_source = record(
            record_id="future:1",
            source="future",
            course_key="future:ceramics",
            card_key="ceramics",
            title="Керамика",
            emoji="🎨",
            group=None,
            schedule=None,
            venue=None,
            audience=None,
            registrations=[{"start": "2026-09-20", "end": "2026-09-25"}],
        )
        result = collect_changes(
            {
                existing["record_id"]: existing,
                new_source["record_id"]: new_source,
            },
            {"sporttia", "future"},
            state,
            date(2026, 9, 20),
            {"judo": 501, "ceramics": 600},
        )
        self.assertEqual(
            [item["kind"] for item in result["pending"]["messages"]],
            ["registration_opening"],
        )

    def test_disappearing_record_is_silent_and_last_good_baseline_is_kept(self):
        existing = record()
        state = baseline_state(existing)
        result = collect_changes(
            {},
            {"sporttia"},
            state,
            date(2026, 9, 20),
            {"judo": 501},
        )
        self.assertIsNone(result["pending"])
        self.assertEqual(result["baseline"][existing["record_id"]], existing)

    def test_stale_snapshot_never_emits_date_event(self):
        current = record(
            observed_day="2026-09-19",
            registrations=[{"start": "2026-09-20", "end": "2026-09-30"}],
        )
        state = baseline_state(current)
        result = collect_changes(
            {current["record_id"]: current},
            {"sporttia"},
            state,
            date(2026, 9, 20),
            {"judo": 501},
        )
        self.assertIsNone(result["pending"])

    def test_registration_extension_is_registration_change(self):
        old = record(registrations=[
            {"start": "2026-09-01", "end": "2026-09-20"}
        ])
        current = record(registrations=[
            {"start": "2026-09-01", "end": "2026-09-30"}
        ])
        result = collect_changes(
            {current["record_id"]: current},
            {"sporttia"},
            baseline_state(old),
            date(2026, 9, 21),
            {"judo": 501},
        )
        self.assertEqual(
            [item["kind"] for item in result["pending"]["messages"]],
            ["registration_changes"],
        )

    def test_missing_internal_card_fails_closed(self):
        old = record(schedule="Вт/Чт · 18:00–19:00")
        current = record(schedule="Вт/Чт · 19:00–20:00")
        with self.assertRaises(CourseNotificationError):
            collect_changes(
                {current["record_id"]: current},
                {"sporttia"},
                baseline_state(old),
                date(2026, 9, 20),
                {},
            )


class CourseNotificationMessageTests(unittest.TestCase):
    def test_opening_links_only_to_internal_course_card(self):
        event = {
            "type": "registration_open",
            "record_id": "sporttia:1",
            "course_key": "sporttia:judo",
            "card_key": "judo",
            "title": "Дзюдо",
            "emoji": "🥋",
            "group": "1-я группа",
            "start": "2026-09-20",
            "end": "2026-09-30",
            "until_full": False,
        }
        message = build_message(
            "registration_opening",
            [event],
            "-100123",
            {"judo": 501},
        )
        self.assertIn("Открылась запись", message)
        self.assertIn("https://t.me/c/123/501", message)
        self.assertNotIn("sporttia", message.casefold())
        self.assertEqual(message.count(FOOTER := "обЪявления Гуардамар"), 1)

    def test_closing_until_full_does_not_claim_absolute_deadline(self):
        event = {
            "type": "registration_close",
            "record_id": "dinamizacion:textile_painting",
            "course_key": "dinamizacion:textile_painting",
            "card_key": "dinamizacion",
            "title": "Роспись по ткани",
            "emoji": "🤝",
            "group": None,
            "start": "2026-09-09",
            "end": "2026-09-20",
            "until_full": True,
        }
        message = build_message(
            "registration_closing",
            [event],
            "-100123",
            {"dinamizacion": 503},
        )
        self.assertIn("основной период записи", message)
        self.assertIn("при наличии мест", message)
        self.assertNotIn("последний день подачи заявки", message)

    def test_course_changes_group_multiple_fields_for_one_course(self):
        events = [
            {
                "type": "course_changed",
                "record_id": "sporttia:1",
                "course_key": "sporttia:judo",
                "card_key": "judo",
                "title": "Дзюдо",
                "emoji": "🥋",
                "group": "1-я группа",
                "changed_fields": ["schedule"],
            },
            {
                "type": "course_changed",
                "record_id": "sporttia:2",
                "course_key": "sporttia:judo",
                "card_key": "judo",
                "title": "Дзюдо",
                "emoji": "🥋",
                "group": "2-я группа",
                "changed_fields": ["venue"],
            },
        ]
        message = build_message(
            "course_changes",
            events,
            "-100123",
            {"judo": 501},
        )
        self.assertEqual(message.count("https://t.me/c/123/501"), 1)
        self.assertIn("расписание", message)
        self.assertIn("место занятий", message)


if __name__ == "__main__":
    unittest.main()
