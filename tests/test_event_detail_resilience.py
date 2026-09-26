import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.digest import build_message
from telegrambot.event_places import canonical_event_place
from telegrambot.event_urls import normalize_registration_url
from telegrambot.models import Event, MorningDigest
from telegrambot.morning import _merge_events
from telegrambot.municipal_agenda import (
    MunicipalAgendaError,
    SourceEvent,
    _annotate_todo_source_sessions,
    _load_snapshot,
    _merge_todo_incremental_state,
    _todo_session_parent_from_row,
    _session_source_plan,
    merge_text_and_poster_events,
    municipal_translation_items,
    _apply_reviewed_daily_schedules,
    _snapshot_data,
    _write_snapshot,
    normalize_extraction_candidates,
    refresh_municipal_catalog,
)
from telegrambot.todo_cultura import (
    TodoCulturaParticipation,
    TodoCulturaProgram,
    TodoCulturaWindow,
    _activity_summaries,
    _registration_participation,
)


TZ = ZoneInfo("Europe/Madrid")


class RegistrationUrlTests(unittest.TestCase):
    def test_registration_policy_is_separate_and_strict(self):
        direct = (
            "https://docs.google.com/forms/d/e/"
            "1FAIpQLSeuEAYwiqX3XncM4Q4z5s1mjaJgoeHzbbzqWqsAdWrHA_UOrA/"
            "viewform?usp=dialog"
        )
        short = "https://forms.gle/AbCdEf12345"

        self.assertEqual(normalize_registration_url(direct), direct)
        self.assertEqual(normalize_registration_url(short), short)
        self.assertIsNone(
            normalize_registration_url("https://docs.google.com/document/d/abc")
        )
        self.assertIsNone(
            normalize_registration_url("https://example.com/forms/abc")
        )
        self.assertIsNone(
            normalize_registration_url("http://forms.gle/AbCdEf12345")
        )

    def test_digest_renders_registration_link_as_registration_not_ticket(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Эскейп-рум «Тайна музея»",
                starts_at=datetime(2026, 9, 26, 11, 0, tzinfo=TZ),
                registration_url=(
                    "https://docs.google.com/forms/d/e/ABC/viewform?usp=dialog"
                ),
                capacity_limited=True,
            ),),
        )

        message = build_message(digest)

        self.assertIn(">Регистрация</a>", message)
        self.assertIn("места ограничены", message)
        self.assertNotIn(">Билеты</a>", message)


class SessionGroupingTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _escape_rows():
        day = date(2026, 9, 26)
        common = (
            "para niños de entre 8 y 12 años en el "
            "Museo Arqueológico de Guardamar (MAG)."
        )
        return (
            (
                day,
                "11:00",
                "2026-09-26\n"
                "– 11 a 11,45 h.: Primer turno para el ‘Escape room’ "
                "con el título ‘El misterio del museo de Guardamar’ "
                + common,
            ),
            (
                day,
                "12:00",
                "2026-09-26\n"
                "– 12 a 12,45 h.: Segund0 turno para el ‘Escape room’ "
                "con el título ‘El misterio del museo de Guardamar’ "
                + common,
            ),
            (
                day,
                "13:00",
                "2026-09-26\n"
                "– 13 a 13,45 h.: Tercer turno para el ‘Escape room’ "
                "con el título ‘El misterio del museo de Guardamar’ "
                + common,
            ),
        )

    @staticmethod
    def _escape_events(*, audience="для участников 8–12 лет"):
        day = date(2026, 9, 26)
        common = dict(
            start_date=day,
            end_date=day,
            place="Museo Arqueológico",
            category="event",
            sources=("todo_cultura",),
            teaser_es=(
                "Los participantes de la actividad resolverán enigmas "
                "por las salas del museo."
            ),
            audience_label=audience,
            capacity_limited=True,
        )
        return (
            SourceEvent(
                title_es=(
                    "Escape room El misterio del museo de Guardamar "
                    "(primer turno)"
                ),
                start_time="11:00",
                end_time="11:45",
                registration_url="https://forms.gle/ONE",
                **common,
            ),
            SourceEvent(
                title_es=(
                    "Escape room para niños 'El misterio del museo de "
                    "Guardamar' (Segundo turno)"
                ),
                start_time="12:00",
                end_time="12:45",
                registration_url="https://forms.gle/TWO",
                **common,
            ),
            SourceEvent(
                title_es=(
                    "Escape room para niños 'El misterio del museo de "
                    "Guardamar' (Tercer turno)"
                ),
                start_time="13:00",
                end_time="13:45",
                registration_url="https://forms.gle/THREE",
                **common,
            ),
        )

    def _annotated_escape_events(self):
        return _annotate_todo_source_sessions(
            self._escape_events(),
            self._escape_rows(),
        )

    def test_live_todo_rows_define_identity_before_translation(self):
        annotated = self._annotated_escape_events()
        plan = _session_source_plan(annotated)

        self.assertTrue(all(
            event.session_source_key is not None for event in annotated
        ))
        self.assertEqual(
            len({event.session_source_key for event in annotated}),
            1,
        )
        self.assertEqual(
            [item[0] for item in plan],
            ["Escape room El misterio del museo de Guardamar"] * 3,
        )
        self.assertEqual(len({item[1] for item in plan}), 1)
        self.assertIsNotNone(plan[0][1])

    def test_raw_source_identity_survives_extractor_title_variation(self):
        first, second, third = self._escape_events()
        second = SourceEvent(
            **{
                **second.__dict__,
                "title_es": (
                    "Escape room infantil 'El misterio del museo de "
                    "Guardamar' (Segundo turno)"
                ),
                "audience_label": "для участников 13–16 лет",
                "teaser_es": None,
            }
        )

        annotated = _annotate_todo_source_sessions(
            (first, second, third),
            self._escape_rows(),
        )
        plan = _session_source_plan(annotated)

        # Extracted wording may vary, but it only maps verified source
        # evidence to an occurrence. The raw Todo rows define the family.
        self.assertEqual(
            len({event.session_source_key for event in annotated}),
            1,
        )
        self.assertEqual(len({group for _, group in plan}), 1)
        self.assertIsNotNone(plan[0][1])

    def test_known_subset_groups_without_claiming_completeness(self):
        first, _, third = self._escape_events()
        first_row, _, third_row = self._escape_rows()

        annotated = _annotate_todo_source_sessions(
            (first, third),
            (first_row, third_row),
        )
        plan = _session_source_plan(annotated)

        self.assertEqual(plan[0][1], plan[1][1])
        self.assertIsNotNone(plan[0][1])

    def test_conflicting_known_places_block_raw_source_grouping(self):
        first, second, third = self._escape_events()
        second = SourceEvent(
            **{**second.__dict__, "place": "Casa de Cultura"}
        )

        annotated = _annotate_todo_source_sessions(
            (first, second, third),
            self._escape_rows(),
        )
        plan = _session_source_plan(annotated)

        self.assertTrue(all(event.session_source_key is None for event in annotated))
        self.assertTrue(all(group is None for _, group in plan))

    def test_same_library_and_date_do_not_merge_unrelated_activities(self):
        day = date(2026, 9, 26)
        events = (
            SourceEvent(
                "Exposición fotográfica",
                day, day, "10:00", "14:00",
                "Biblioteca Pública Municipal", "exhibition",
            ),
            SourceEvent(
                "Proyección de cine",
                day, day, "17:00", "19:00",
                "Biblioteca Pública Municipal", "event",
            ),
            SourceEvent(
                "Taller infantil",
                day, day, "19:30", "20:30",
                "Biblioteca Pública Municipal", "event",
            ),
        )
        rows = (
            (day, "10:00", "2026-09-26\n– 10 h.: Exposición fotográfica."),
            (day, "17:00", "2026-09-26\n– 17 h.: Proyección de cine."),
            (day, "19:30", "2026-09-26\n– 19,30 h.: Taller infantil."),
        )

        annotated = _annotate_todo_source_sessions(events, rows)
        plan = _session_source_plan(annotated)

        self.assertTrue(all(event.session_source_key is None for event in annotated))
        self.assertEqual(
            plan,
            tuple((event.title_es, None) for event in events),
        )

    def test_same_time_unrelated_event_does_not_steal_escape_row(self):
        day = date(2026, 9, 26)
        guided = SourceEvent(
            "Visita guiada al Molino de San Antonio",
            day, day, "11:00", "12:00",
            "Molino de San Antonio", "event",
            sources=("todo_cultura",),
        )
        events = (guided, *self._escape_events())
        rows = (
            (
                day,
                "11:00",
                "2026-09-26\n"
                "– 11 a 12 h.: Visita guiada al Molino de San Antonio "
                "con entrada libre.",
            ),
            *self._escape_rows(),
        )

        annotated = _annotate_todo_source_sessions(events, rows)

        self.assertIsNone(annotated[0].session_source_key)
        escape = annotated[1:]
        self.assertTrue(all(event.session_source_key for event in escape))
        self.assertEqual(len({event.session_source_key for event in escape}), 1)

    def test_ambiguous_same_time_session_row_does_not_create_identity(self):
        day = date(2026, 9, 26)
        first = SourceEvent(
            "Escape room del museo (primer turno)",
            day, day, "11:00", "11:45",
            "Museo Arqueológico", "event",
            sources=("todo_cultura",),
        )
        duplicate = SourceEvent(
            "Escape room del museo para niños (primer turno)",
            day, day, "11:00", "11:45",
            "Museo Arqueológico", "event",
            sources=("todo_cultura",),
        )
        second = SourceEvent(
            "Escape room del museo (segundo turno)",
            day, day, "12:00", "12:45",
            "Museo Arqueológico", "event",
            sources=("todo_cultura",),
        )
        rows = (
            (
                day, "11:00",
                "2026-09-26\n"
                "– 11 h.: Primer turno para Escape room del museo.",
            ),
            (
                day, "12:00",
                "2026-09-26\n"
                "– 12 h.: Segundo turno para Escape room del museo.",
            ),
        )

        annotated = _annotate_todo_source_sessions(
            (first, duplicate, second),
            rows,
        )

        self.assertTrue(all(
            event.session_source_key is None for event in annotated
        ))

    def test_two_raw_families_with_same_display_title_stay_separate(self):
        day = date(2026, 9, 26)
        events = tuple(
            SourceEvent(
                title_es=f"Escape room X ({ordinal} turno)",
                start_date=day,
                end_date=day,
                start_time=start,
                end_time=None,
                place="Museo Arqueológico",
                category="event",
                sources=("todo_cultura",),
            )
            for ordinal, start in (
                ("primer", "11:00"),
                ("segundo", "12:00"),
                ("primer", "17:00"),
                ("segundo", "18:00"),
            )
        )
        rows = (
            (day, "11:00", "2026-09-26\n– 11 h.: Primer turno para Escape room X para niños de 6 a 8 años."),
            (day, "12:00", "2026-09-26\n– 12 h.: Segundo turno para Escape room X para niños de 6 a 8 años."),
            (day, "17:00", "2026-09-26\n– 17 h.: Primer turno para Escape room X para niños de 9 a 12 años."),
            (day, "18:00", "2026-09-26\n– 18 h.: Segundo turno para Escape room X para niños de 9 a 12 años."),
        )

        annotated = _annotate_todo_source_sessions(events, rows)
        plan = _session_source_plan(annotated)

        keys = [event.session_source_key for event in annotated]
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[2], keys[3])
        self.assertNotEqual(keys[0], keys[2])
        group_keys = [group for _, group in plan]
        self.assertEqual(group_keys[0], group_keys[1])
        self.assertEqual(group_keys[2], group_keys[3])
        self.assertNotEqual(group_keys[0], group_keys[2])

    def test_suffix_marker_is_supported_but_not_required_for_live_source(self):
        day = date(2026, 9, 26)
        row = (
            "2026-09-26\n"
            "– 11 h.: Escape room del museo (primer turno)"
        )

        self.assertEqual(
            _todo_session_parent_from_row(row),
            "Escape room del museo",
        )

    def test_general_numeric_and_spanish_session_markers_are_supported(self):
        numeric = (
            "2026-09-26\n"
            "– 18 h.: 7º pase para Escape room nocturno."
        )
        spanish = (
            "2026-09-26\n"
            "– 19 h.: Séptimo turno para Escape room nocturno."
        )
        numbered = (
            "2026-09-26\n"
            "– 20 h.: Turno 12 de Escape room nocturno."
        )

        self.assertEqual(
            _todo_session_parent_from_row(numeric),
            "Escape room nocturno",
        )
        self.assertEqual(
            _todo_session_parent_from_row(spanish),
            "Escape room nocturno",
        )
        self.assertEqual(
            _todo_session_parent_from_row(numbered),
            "Escape room nocturno",
        )

    def test_source_merge_preserves_raw_identity_when_title_marker_is_lost(self):
        todo = self._annotated_escape_events()
        day = date(2026, 9, 26)
        generic = tuple(
            SourceEvent(
                title_es=(
                    "Escape room El misterio del museo de Guardamar "
                    "para niños de 8 a 12 años"
                ),
                start_date=day,
                end_date=day,
                start_time=start,
                end_time=end,
                place="Museo Arqueológico",
                category="event",
                sources=("mupi",),
            )
            for start, end in (
                ("11:00", "11:45"),
                ("12:00", "12:45"),
                ("13:00", "13:45"),
            )
        )

        # Use the Todo occurrence as the text candidate in the same direction
        # as the production municipal merge: source identity must survive even
        # when another source owns the final display title.
        merged = merge_text_and_poster_events(generic, todo)

        self.assertTrue(all(event.session_source_key for event in merged))
        self.assertEqual(
            len({event.session_source_key for event in merged}),
            1,
        )
        plan = _session_source_plan(merged)
        self.assertEqual(len({group for _, group in plan}), 1)
        self.assertIsNotNone(plan[0][1])

    def test_snapshot_round_trip_preserves_raw_source_session_identity(self):
        events = self._annotated_escape_events()
        now = datetime(2026, 9, 26, 10, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "municipal.json"
            _write_snapshot(
                state_path,
                _snapshot_data("", "", now, events),
            )
            loaded = _load_snapshot(state_path)

        self.assertIsNotNone(loaded)
        loaded_events = loaded["_events"]
        self.assertEqual(
            len({event.session_source_key for event in loaded_events}),
            1,
        )
        self.assertTrue(all(
            event.session_parent_title_es
            == "Escape room El misterio del museo de Guardamar"
            for event in loaded_events
        ))
        plan = _session_source_plan(loaded_events)
        self.assertEqual(len({group for _, group in plan}), 1)
        self.assertIsNotNone(plan[0][1])

    def test_fresh_unique_non_session_rows_clear_stale_session_metadata(self):
        day = date(2026, 9, 26)
        stale = tuple(
            SourceEvent(
                title_es=title,
                start_date=day,
                end_date=day,
                start_time=start,
                end_time=None,
                place="Museo Arqueológico",
                category="event",
                sources=("todo_cultura",),
                session_source_key="todo_cultura:" + "a" * 64,
                session_parent_title_es="Escape room antiguo",
            )
            for title, start in (
                ("Taller infantil A", "11:00"),
                ("Taller infantil B", "12:00"),
            )
        )
        rows = (
            (
                day,
                "11:00",
                "2026-09-26\n– 11 h.: Taller infantil A.",
            ),
            (
                day,
                "12:00",
                "2026-09-26\n– 12 h.: Taller infantil B.",
            ),
        )

        refreshed = _annotate_todo_source_sessions(stale, rows)

        self.assertTrue(all(
            event.session_source_key is None
            and event.session_parent_title_es is None
            for event in refreshed
        ))
        self.assertTrue(all(
            group is None
            for _, group in _session_source_plan(refreshed)
        ))

    def test_ambiguous_fresh_row_does_not_erase_last_known_session_metadata(self):
        day = date(2026, 9, 26)
        source_key = "todo_cultura:" + "b" * 64
        events = (
            SourceEvent(
                "Escape room del museo (primer turno)",
                day, day, "11:00", "11:45",
                "Museo Arqueológico", "event",
                sources=("todo_cultura",),
                session_source_key=source_key,
                session_parent_title_es="Escape room del museo",
            ),
            SourceEvent(
                "Escape room del museo para niños (primer turno)",
                day, day, "11:00", "11:45",
                "Museo Arqueológico", "event",
                sources=("todo_cultura",),
                session_source_key=source_key,
                session_parent_title_es="Escape room del museo",
            ),
        )
        rows = ((
            day,
            "11:00",
            "2026-09-26\n– 11 h.: Primer turno para Escape room del museo.",
        ),)

        refreshed = _annotate_todo_source_sessions(events, rows)

        self.assertEqual(
            [event.session_source_key for event in refreshed],
            [source_key, source_key],
        )

    def test_legacy_parent_without_source_key_is_ignored_not_corrupt(self):
        events = self._escape_events()
        now = datetime(2026, 9, 26, 10, 0, tzinfo=TZ)
        data = _snapshot_data("", "", now, events)
        for raw in data["events"]:
            raw["session_parent_title_es"] = "Legacy parent"
            raw.pop("session_source_key", None)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "municipal.json"
            _write_snapshot(state_path, data)
            loaded = _load_snapshot(state_path)

        self.assertIsNotNone(loaded)
        self.assertTrue(all(
            event.session_source_key is None
            and event.session_parent_title_es is None
            for event in loaded["_events"]
        ))

    async def test_translation_queue_contains_parent_title_once(self):
        events = self._annotated_escape_events()
        now = datetime(2026, 9, 26, 10, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "municipal.json"
            _write_snapshot(
                state_path,
                _snapshot_data("", "", now, events),
            )

            items = await municipal_translation_items(now, state_path)

        self.assertEqual(
            items.count((
                "municipal_agenda",
                "Escape room El misterio del museo de Guardamar",
            )),
            1,
        )
        self.assertFalse(any("(primer turno)" in value.casefold() for _, value in items))
        self.assertFalse(any("(segundo turno)" in value.casefold() for _, value in items))
        self.assertFalse(any("(tercer turno)" in value.casefold() for _, value in items))

    def test_merge_preserves_session_key_from_later_event(self):
        when = datetime(2026, 9, 26, 11, 0, tzinfo=TZ)
        plain = Event("Эскейп-рум «Тайна музея»", when)
        session = Event(
            "Эскейп-рум «Тайна музея»",
            when,
            session_group_key="session:test",
        )

        merged = _merge_events((plain,), (session,))

        self.assertEqual(merged[0].session_group_key, "session:test")

    def test_merge_clears_conflicting_session_keys(self):
        when = datetime(2026, 9, 26, 11, 0, tzinfo=TZ)
        first = Event(
            "Эскейп-рум «Тайна музея»",
            when,
            session_group_key="session:a",
        )
        conflicting = Event(
            "Эскейп-рум «Тайна музея»",
            when,
            session_group_key="session:b",
        )

        merged = _merge_events((first,), (conflicting,))

        self.assertIsNone(merged[0].session_group_key)

    def test_digest_compacts_known_sessions_with_outer_span_and_new_order(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        urls = (
            "https://docs.google.com/forms/d/e/ONE/viewform",
            "https://docs.google.com/forms/d/e/TWO/viewform",
            "https://docs.google.com/forms/d/e/THREE/viewform",
        )
        events = tuple(
            Event(
                title="Эскейп-рум «Тайна музея Гуардамара»",
                starts_at=day.replace(hour=hour),
                ends_at=day.replace(hour=hour, minute=45),
                place="Museo Arqueológico",
                registration_url=url,
                capacity_limited=True,
                teaser="Разгадайте загадки и тайны музея.",
                participation_note="для участников 8–12 лет",
                session_group_key="session:escape",
            )
            for hour, url in zip((11, 12, 13), urls)
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertEqual(
            message.count("Эскейп-рум «Тайна музея Гуардамара»"), 1
        )
        self.assertIn(
            "<b>11:00–13:45</b> — "
            "Эскейп-рум «Тайна музея Гуардамара»",
            message,
        )
        self.assertNotIn("3 сеанса", message)
        self.assertIn("🕐 Сеансы:", message)
        self.assertEqual(message.count(">Регистрация</a>"), 3)
        self.assertEqual(message.count("места ограничены"), 1)
        self.assertEqual(message.count("Разгадайте загадки и тайны музея."), 1)
        self.assertEqual(message.count("для участников 8–12 лет"), 1)
        self.assertEqual(message.count("Museo Arqueológico"), 1)
        self.assertIn("<b>11:00–11:45</b>", message)
        self.assertIn("<b>12:00–12:45</b>", message)
        self.assertIn("<b>13:00–13:45</b>", message)

        teaser_pos = message.index("Разгадайте загадки и тайны музея.")
        audience_pos = message.index("ℹ️ для участников 8–12 лет")
        sessions_pos = message.index("🕐 Сеансы:")
        place_pos = message.index("Museo Arqueológico")
        capacity_pos = message.index("🎟 места ограничены")
        self.assertLess(teaser_pos, audience_pos)
        self.assertLess(audience_pos, sessions_pos)
        self.assertLess(sessions_pos, place_pos)
        self.assertLess(place_pos, capacity_pos)

    def test_translation_variation_does_not_break_existing_group_identity(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        events = (
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=11),
                session_group_key="session:escape",
            ),
            Event(
                "Квест «Загадка музея»",
                day.replace(hour=12),
                session_group_key="session:escape",
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertIn("🕐 Сеансы:", message)
        self.assertIn("<b>11:00</b>", message)
        self.assertIn("<b>12:00</b>", message)
        self.assertNotIn("Квест «Загадка музея»", message)

    def test_conflicting_presentation_facts_do_not_split_group(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        events = (
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=11),
                place="Museo Arqueológico",
                audience_label="8–12 лет",
                teaser="Общее описание.",
                session_group_key="session:escape",
            ),
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=12),
                place="Museo Arqueológico",
                audience_label="13–16 лет",
                session_group_key="session:escape",
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertIn("🕐 Сеансы:", message)
        self.assertIn("8–12 лет", message)
        self.assertIn("13–16 лет", message)
        self.assertEqual(message.count("Общее описание."), 1)

    def test_session_header_omits_outer_span_when_an_end_is_unknown(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        events = (
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=11),
                ends_at=day.replace(hour=11, minute=45),
                session_group_key="session:escape",
            ),
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=12),
                session_group_key="session:escape",
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertIn("• Эскейп-рум «Тайна музея»", message)
        self.assertNotIn("<b>11:00–12:00</b>", message)
        self.assertIn("<b>11:00–11:45</b>", message)
        self.assertIn("<b>12:00</b>", message)

    def test_cross_midnight_session_keeps_verified_end_time(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        events = (
            Event(
                "Ночная программа",
                day.replace(hour=21),
                ends_at=day.replace(hour=22),
                session_group_key="session:night",
            ),
            Event(
                "Ночная программа",
                day.replace(hour=23),
                ends_at=day.replace(day=27, hour=1),
                session_group_key="session:night",
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertIn("<b>21:00–22:00</b>", message)
        self.assertIn("<b>23:00–01:00</b>", message)
        self.assertNotIn("2 сеанса", message)

    def test_known_subset_of_sessions_still_renders_as_one_activity(self):
        day = datetime(2026, 9, 26, tzinfo=TZ)
        events = (
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=11),
                session_group_key="session:escape",
            ),
            Event(
                "Эскейп-рум «Тайна музея»",
                day.replace(hour=13),
                session_group_key="session:escape",
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=events,
        ))

        self.assertIn("🕐 Сеансы:", message)
        self.assertIn("<b>11:00</b>", message)
        self.assertIn("<b>13:00</b>", message)
        self.assertNotIn("2 сеанса", message)



class TodoRegistrationExtractionTests(unittest.TestCase):
    def test_three_escape_sessions_keep_distinct_registration_forms(self):
        rendered = """
        <p>El Ayuntamiento de Guardamar publica la agenda municipal.</p>
        <p>Sábado 26 de septiembre</p>
        <p>11 a 11,45 h.: Primer turno para Escape Room “El Misterio del
        Museo de Guardamar” para niños de entre 8 y 12 años.</p>
        <p>Los participantes de la actividad se convertirán en investigadores
        y deberán resolver enigmas, pistas y misterios por las salas.</p>
        <p>Las plazas son limitadas.</p>
        <p>Inscripción: <a href="https://docs.google.com/forms/d/e/ONE/viewform">
        Pinchad aquí</a></p>
        <p>12 a 12,45 h.: Segund0 turno para Escape Room “El Misterio del
        Museo de Guardamar” para niños de entre 8 y 12 años.</p>
        <p>Los participantes de la actividad se convertirán en investigadores
        y deberán resolver enigmas, pistas y misterios por las salas.</p>
        <p>Las plazas son limitadas.</p>
        <p>Inscripción: <a href="https://docs.google.com/forms/d/e/TWO/viewform">
        Pinchad aquí</a></p>
        <p>13 a 13,45 h.: Tercer turno para Escape Room “El Misterio del
        Museo de Guardamar” para niños de entre 8 y 12 años.</p>
        <p>Los participantes de la actividad se convertirán en investigadores
        y deberán resolver enigmas, pistas y misterios por las salas.</p>
        <p>Las plazas son limitadas.</p>
        <p>Inscripción: <a href="https://docs.google.com/forms/d/e/THREE/viewform">
        Pinchad aquí</a></p>
        """
        details = _registration_participation(
            rendered, date(2026, 9, 26)
        )

        self.assertEqual([item.start_time for item in details], [
            "11:00", "12:00", "13:00",
        ])
        self.assertEqual(
            [item.registration_url for item in details],
            [
                "https://docs.google.com/forms/d/e/ONE/viewform",
                "https://docs.google.com/forms/d/e/TWO/viewform",
                "https://docs.google.com/forms/d/e/THREE/viewform",
            ],
        )
        self.assertTrue(all(item.capacity_limited for item in details))
        self.assertTrue(all(
            item.participation_note == "для участников 8–12 лет"
            for item in details
        ))
        self.assertTrue(all(
            item.event_dates == (date(2026, 9, 26),)
            for item in details
        ))

    def test_escape_activity_summary_accepts_explicit_participant_description(self):
        section = (
            "2026-09-26\n"
            "– 11 a 11,45 h.: Primer turno para Escape Room "
            "‘El Misterio del Museo de Guardamar’.\n"
            "Los participantes de la actividad se convertirán en "
            "investigadores y deberán resolver enigmas, pistas y misterios "
            "por las distintas salas del museo."
        )

        summaries = _activity_summaries(section)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].start_time, "11:00")
        self.assertTrue(
            summaries[0].teaser_es.startswith(
                "Los participantes de la actividad"
            )
        )


class TodoEvidenceTests(unittest.TestCase):
    def test_todo_title_accepts_one_source_digit_typo_only(self):
        evidence = (
            "26 de septiembre de 2026 a las 12:00 h. "
            "Segund0 turno Escape Room."
        )
        raw = {
            "month": "2026-09",
            "events": [{
                "title_es": "Segundo turno Escape Room",
                "start_date": "2026-09-26",
                "end_date": "2026-09-26",
                "start_time": "12:00",
                "end_time": None,
                "place": None,
                "evidence_es": evidence,
                "category": "event",
            }],
        }

        accepted = normalize_extraction_candidates(
            raw, "2026-09", "todo_cultura", evidence
        )
        self.assertEqual(len(accepted), 1)

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                raw, "2026-09", "turismo_html", evidence
            )


class TodoIncrementalStateTests(unittest.TestCase):
    def test_partial_state_advances_only_completed_candidate_progress(self):
        previous = {
            "parser_version": 19,
            "cursor_modified_gmt": "2026-09-25T08:00:00",
            "covered_dates": [],
            "candidates": [{
                "id": 1,
                "dates": ["2026-09-26"],
                "processed_dates": [],
                "processed_chunks": {},
                "detail_checked": False,
                "scope": "local",
            }, {
                "id": 2,
                "dates": ["2026-09-26"],
                "processed_dates": [],
                "processed_chunks": {},
                "detail_checked": False,
                "scope": "local",
            }],
        }
        attempted = {
            "parser_version": 20,
            "cursor_modified_gmt": "2026-09-26T08:00:00",
            "covered_dates": ["2026-09-26"],
            "candidates": [{
                "id": 1,
                "dates": ["2026-09-26"],
                "dates_source": "detail",
                "processed_dates": ["2026-09-26"],
                "processed_chunks": {},
                "detail_checked": True,
                "scope": "local",
            }, {
                "id": 2,
                "dates": ["2026-09-26"],
                "dates_source": "detail",
                "processed_dates": ["2026-09-26"],
                "processed_chunks": {},
                "detail_checked": True,
                "scope": "local",
            }],
        }

        merged = _merge_todo_incremental_state(
            previous,
            attempted,
            completed_candidate_ids={1, 2},
            failed_candidate_ids={2},
        )

        self.assertEqual(
            merged["cursor_modified_gmt"],
            previous["cursor_modified_gmt"],
        )
        self.assertEqual(merged["parser_version"], 20)
        by_id = {item["id"]: item for item in merged["candidates"]}
        self.assertEqual(by_id[1]["processed_dates"], ["2026-09-26"])
        self.assertEqual(by_id[2]["processed_dates"], [])
        self.assertEqual(by_id[2]["dates_source"], "detail")
        self.assertTrue(by_id[2]["detail_checked"])
        self.assertEqual(merged["covered_dates"], ["2026-09-26"])


class TodoPartialRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_persists_live_escape_identity_from_raw_rows(self):
        local_day = date(2026, 9, 26)
        rows = SessionGroupingTests._escape_rows()
        program = TodoCulturaProgram(
            text="\n".join(row for _, _, row in rows),
            sha256="todo-live-session",
            source_url="https://todoculturavegabaja.es/eventos/guardamar/",
            modified="2026-09-26T10:00:00",
            dates=(local_day,),
            event_rows=rows,
        )
        window = TodoCulturaWindow(
            programs=(program,),
            source_state={
                "parser_version": 19,
                "cursor_modified_gmt": "2026-09-26T10:00:00",
                "covered_dates": ["2026-09-26"],
                "candidates": [],
            },
        )
        raw_events = []
        for event, (_, _, row) in zip(
            SessionGroupingTests._escape_events(),
            rows,
        ):
            evidence = " ".join(row.split())
            raw_events.append({
                "title_es": event.title_es,
                "start_date": "2026-09-26",
                "end_date": "2026-09-26",
                "start_time": event.start_time,
                "end_time": event.end_time,
                "place": "Museo Arqueológico",
                "evidence_es": evidence,
                "category": "event",
            })
        extracted = {"month": "2026-09", "events": raw_events}
        now = datetime(2026, 9, 26, 10, 15, tzinfo=TZ)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "municipal.json"
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(b"<html>sin agenda</html>", "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_official_agenda_text",
                    side_effect=MunicipalAgendaError(
                        "no text month",
                        code="NO-TEXT-MONTH",
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_program_window",
                    new=AsyncMock(return_value=window),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=AsyncMock(return_value=extracted),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_facebook_posts",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.municipal_agenda._turismo_programme_events",
                    new=AsyncMock(return_value=((), {})),
                ),
            ):
                current = await refresh_municipal_catalog(
                    "key", now, state_path
                )

            loaded = _load_snapshot(state_path)

        escape = tuple(
            event for event in current
            if event.start_time in {"11:00", "12:00", "13:00"}
        )
        self.assertEqual(len(escape), 3)
        self.assertEqual(
            len({event.session_source_key for event in escape}),
            1,
        )
        self.assertNotIn(None, {event.session_source_key for event in escape})
        self.assertTrue(all(
            event.session_parent_title_es
            == "Escape room El misterio del museo de Guardamar"
            for event in escape
        ))

        self.assertIsNotNone(loaded)
        loaded_escape = tuple(
            event for event in loaded["_events"]
            if event.start_time in {"11:00", "12:00", "13:00"}
        )
        plan = _session_source_plan(loaded_escape)
        self.assertEqual(len({group for _, group in plan}), 1)
        self.assertIsNotNone(plan[0][1])

    async def test_partial_rows_are_kept_without_advancing_todo_state(self):
        local_day = date(2026, 9, 26)
        old_state = {
            "parser_version": 17,
            "cursor_modified_gmt": "2026-09-25T08:00:00",
            "covered_dates": ["2026-09-26"],
            "candidates": [],
        }
        advanced_state = {
            **old_state,
            "cursor_modified_gmt": "2026-09-26T08:00:00",
        }
        prior_route = SourceEvent(
            title_es="Free tour guiada y gratuita al punto geodésico",
            start_date=local_day,
            end_date=local_day,
            start_time="08:30",
            end_time=None,
            place=None,
            category="event",
            sources=("todo_cultura",),
        )
        route_row = (
            "2026-09-26\n"
            "– 8,30 horas: Free tour guiada y gratuita al punto geodésico."
        )
        escape_row = (
            "2026-09-26\n"
            "– 11 h.: Escape Room primer turno."
        )
        missing_row = (
            "2026-09-26\n"
            "– 12 h.: Fila todavía no recuperable."
        )
        program = TodoCulturaProgram(
            text="\n".join((route_row, escape_row, missing_row)),
            sha256="todo-partial",
            source_url="https://todoculturavegabaja.es/eventos/guardamar/",
            modified="2026-09-26T08:00:00",
            dates=(local_day,),
            event_rows=(
                (local_day, "08:30", route_row),
                (local_day, "11:00", escape_row),
                (local_day, "12:00", missing_row),
            ),
            participation=(TodoCulturaParticipation(
                title_hint=(
                    "– 8,30 horas: Free tour guiada y gratuita "
                    "al punto geodésico."
                ),
                registration_contact="talentojovenguardamar@gmail.com",
                participation_note="возьмите воду и удобную обувь",
                event_dates=(local_day,),
                start_time="08:30",
                difficulty_label="Сложность маршрута: низкая–средняя",
            ),),
        )
        window = TodoCulturaWindow(
            programs=(program,),
            source_state=advanced_state,
        )
        extracted = {
            "month": "2026-09",
            "events": [{
                "title_es": "Escape Room primer turno",
                "start_date": "2026-09-26",
                "end_date": "2026-09-26",
                "start_time": "11:00",
                "end_time": None,
                "place": None,
                "evidence_es": (
                    "2026-09-26 – 11 h.: Escape Room primer turno."
                ),
                "category": "event",
            }],
        }
        empty = {"month": "2026-09", "events": []}
        now = datetime(2026, 9, 26, 5, 10, tzinfo=TZ)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "municipal.json"
            _write_snapshot(
                state_path,
                _snapshot_data(
                    "",
                    "",
                    now,
                    (prior_route,),
                    {"todo_cultura": old_state},
                ),
            )
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(b"<html>sin agenda</html>", "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_official_agenda_text",
                    side_effect=MunicipalAgendaError(
                        "no text month",
                        code="NO-TEXT-MONTH",
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_program_window",
                    new=AsyncMock(return_value=window),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=AsyncMock(side_effect=(extracted, empty)),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_facebook_posts",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.municipal_agenda._turismo_programme_events",
                    new=AsyncMock(return_value=((), {})),
                ),
            ):
                current = await refresh_municipal_catalog(
                    "key", now, state_path
                )

            stored = json.loads(state_path.read_text(encoding="utf-8"))

        titles = {event.title_es: event for event in current}
        self.assertIn(
            "Free tour guiada y gratuita al punto geodésico", titles
        )
        self.assertIn("Escape Room primer turno", titles)
        route = titles["Free tour guiada y gratuita al punto geodésico"]
        self.assertEqual(
            route.registration_contact,
            "talentojovenguardamar@gmail.com",
        )
        self.assertEqual(
            route.participation_note,
            "возьмите воду и удобную обувь",
        )
        self.assertIn(
            "Сложность маршрута: низкая–средняя",
            route.details,
        )
        self.assertEqual(
            stored["sources"]["todo_cultura"]["cursor_modified_gmt"],
            old_state["cursor_modified_gmt"],
        )
        self.assertNotIn(
            "incomplete_session_dates",
            stored["sources"]["todo_cultura"],
        )


class ReviewedScheduleAndPlaceTests(unittest.TestCase):
    def test_adimar_is_hidden_weekend_and_scheduled_on_weekdays(self):
        exhibition = SourceEvent(
            title_es="CALENDARIO SOLIDARIO ADIMAR 2027",
            start_date=date(2026, 9, 25),
            end_date=date(2026, 10, 16),
            start_time=None,
            end_time=None,
            place="Biblioteca Pública Municipal",
            category="exhibition",
            sources=("turismo_html",),
        )

        saturday = _apply_reviewed_daily_schedules(
            (exhibition,), date(2026, 9, 26)
        )
        monday = _apply_reviewed_daily_schedules(
            (exhibition,), date(2026, 9, 28)
        )

        self.assertEqual(saturday, ())
        self.assertEqual(len(monday), 1)
        self.assertEqual(monday[0].start_time, "09:00")
        self.assertEqual(monday[0].end_time, "20:00")
        self.assertEqual(
            monday[0].participation_note,
            "в будни перерыв 13:30–17:00",
        )

    def test_adimar_opening_is_not_matched_by_range_schedule(self):
        opening = SourceEvent(
            title_es=(
                "Inauguración de la exposición "
                "CALENDARIO SOLIDARIO ADIMAR 2027"
            ),
            start_date=date(2026, 9, 25),
            end_date=date(2026, 9, 25),
            start_time="20:00",
            end_time=None,
            place="Biblioteca Pública Municipal",
            category="exhibition_opening",
            sources=("turismo_html",),
        )
        self.assertEqual(
            _apply_reviewed_daily_schedules(
                (opening,), date(2026, 9, 25)
            ),
            (opening,),
        )

    def test_museum_variants_share_compact_display_name(self):
        variants = (
            "Museo Arqueológico de Guardamar",
            "Museo Arqueológico de Guardamar (MAG)",
            "Museo Arqueológico Guardamar del Segura",
            "Museo Arqueológico de Guardamar del Segura",
        )
        self.assertEqual(
            {canonical_event_place(value) for value in variants},
            {"Museo Arqueológico"},
        )


if __name__ == "__main__":
    unittest.main()
