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
from telegrambot.municipal_agenda import (
    MunicipalAgendaError,
    SourceEvent,
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


class TodoPartialRefreshTests(unittest.IsolatedAsyncioTestCase):
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
