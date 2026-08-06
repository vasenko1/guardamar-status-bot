import json
import hashlib
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.municipal_agenda import (
    MunicipalAgendaError,
    SourceEvent,
    _current_events,
    _enrich_todo_admissions,
    _cached_current_events,
    _apply_reviewed_corrections,
    _apply_reviewed_daily_schedules,
    _load_snapshot,
    _merge_reviewed_text_agenda,
    _merge_transition_events,
    _snapshot_data,
    _write_snapshot,
    extract_poster_url,
    extract_official_agenda_text,
    intersect_verified_poster_events,
    merge_text_and_poster_events,
    _poster_month,
    fetch_today_municipal_events,
    normalize_extraction,
    normalize_extraction_candidates,
)
from telegrambot.gemini import GeminiError
from telegrambot.todo_cultura import (
    TodoCulturaAdmission,
    TodoCulturaError,
    TodoCulturaProgram,
)

TZ = ZoneInfo("Europe/Madrid")


def extraction():
    return {
        "month": "2026-07",
        "events": [
            {
                "title_es": "Concierto en el castillo",
                "start_date": "2026-07-27",
                "end_date": None,
                "start_time": "21:00",
                "end_time": "23:00",
                "place": "Castillo",
                "category": "event",
            },
            {
                "title_es": "Entropía",
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "start_time": None,
                "end_time": None,
                "place": "Biblioteca",
                "category": "exhibition",
            },
            {
                "title_es": "Ecoparque móvil",
                "start_date": "2026-07-27",
                "end_date": None,
                "start_time": "09:00",
                "end_time": "12:00",
                "place": None,
                "category": "municipal_service",
            },
        ],
    }


class MunicipalAgendaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch(
            "telegrambot.municipal_agenda.fetch_latest_program",
            new=AsyncMock(side_effect=TodoCulturaError(
                "offline in unit tests",
                code="NETWORK",
                description="test source unavailable",
            )),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_extracts_declared_month_and_only_programme_section(self):
        payload = b"""
        <nav>irrelevant</nav>
        <h2>AGENDA CULTURAL AGOSTO 2026</h2>
        <p>Jueves 6 de agosto a las 19:30. Concierto municipal en la plaza.
        Entrada libre. Actividad organizada por el Ayuntamiento.</p>
        <p>Ver Agenda</p><footer>irrelevant footer</footer>
        """

        text, month = extract_official_agenda_text(payload)

        self.assertEqual(month, "2026-08")
        self.assertIn("Concierto", text)
        self.assertNotIn("footer", text)

    def test_poster_month_prefers_filename_over_upload_directory(self):
        self.assertEqual(
            _poster_month(
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            "2026-08",
        )

    def test_text_event_wins_and_records_poster_provenance(self):
        text_event = SourceEvent(
            "Música a les Places: Dixi Project",
            date(2026, 8, 6),
            date(2026, 8, 6),
            "19:30",
            None,
            "Plaça dels Llauradors",
            "event",
            ("turismo_html",),
        )
        poster_event = SourceEvent(
            "Dixi Project, música de los años 20",
            date(2026, 8, 6),
            date(2026, 8, 6),
            "19:30",
            None,
            "Plaza Labradores",
            "event",
            ("mupi",),
        )

        merged = merge_text_and_poster_events((text_event,), (poster_event,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title_es, text_event.title_es)
        self.assertEqual(merged[0].sources, ("turismo_html", "mupi"))

    def test_text_event_suppresses_conflicting_poster_at_same_place_time(self):
        text_event = SourceEvent(
            "SPANISH BRASS",
            date(2026, 8, 5),
            date(2026, 8, 5),
            "22:00",
            None,
            "Castell de Guardamar",
            "event",
            ("turismo_html",),
        )
        poster_event = SourceEvent(
            "ESTIVAL CASTELL - TOP SECRET",
            date(2026, 8, 5),
            date(2026, 8, 5),
            "22:00",
            None,
            "Castillo de Guardamar",
            "event",
            ("mupi",),
        )

        merged = merge_text_and_poster_events((text_event,), (poster_event,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title_es, "SPANISH BRASS")
        self.assertEqual(merged[0].sources, ("turismo_html", "mupi"))

    def test_same_titled_sessions_at_different_times_are_not_merged(self):
        morning = SourceEvent(
            "Actividad juvenil", date(2026, 8, 5), date(2026, 8, 5),
            "08:30", "14:00", "Centro", "event", ("turismo_html",),
        )
        evening = SourceEvent(
            "Actividad juvenil", date(2026, 8, 5), date(2026, 8, 5),
            "17:00", "21:00", "Centro", "event", ("todo_cultura",),
        )

        merged = merge_text_and_poster_events((morning,), (evening,))

        self.assertEqual(len(merged), 2)

    def test_todo_admission_enriches_matching_event_only(self):
        spanish_brass = SourceEvent(
            "Concierto Spanish Brass «Top secret»",
            date(2026, 8, 5), date(2026, 8, 5), "22:00", None,
            "Castell de Guardamar", "event", ("todo_cultura",),
        )
        other = SourceEvent(
            "Exposición Mediterráneo", date(2026, 8, 5),
            date(2026, 8, 5), None, None, "Casa de Cultura",
            "exhibition", ("todo_cultura",),
        )
        admissions = (TodoCulturaAdmission(
            "https://www.agendaguardamar.com/espectaculo/48/"
            "spanish-brass-top-secret.html",
            1500,
        ),)

        enriched = _enrich_todo_admissions(
            (spanish_brass, other), admissions
        )

        self.assertEqual(enriched[0].ticket_price_cents, 1500)
        self.assertIsNone(enriched[1].ticket_price_cents)

    def test_routine_youth_hours_and_vague_campaign_are_omitted(self):
        result = normalize_extraction_candidates({
            "month": "2026-08",
            "events": [
                {
                    "title_es": "Actividades del Centro Social Juvenil",
                    "start_date": "2026-08-05",
                    "end_date": "2026-08-05",
                    "start_time": "08:30",
                    "end_time": "14:00",
                    "place": "Centro Social Juvenil",
                    "category": "event",
                },
                {
                    "title_es": "Campaña de voluntariado medioambiental",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-31",
                    "start_time": None,
                    "end_time": None,
                    "place": None,
                    "category": "event",
                },
                {
                    "title_es": "Concierto Spanish Brass",
                    "start_date": "2026-08-05",
                    "end_date": "2026-08-05",
                    "start_time": "22:00",
                    "end_time": None,
                    "place": "Castell de Guardamar",
                    "category": "event",
                },
            ],
        }, "2026-08", "todo_cultura")

        self.assertEqual([event.title_es for event in result], [
            "Concierto Spanish Brass"
        ])

    def test_poster_fact_requires_independent_agreement(self):
        first = SourceEvent(
            "Concierto M3SICA",
            date(2026, 8, 8),
            date(2026, 8, 8),
            "22:00",
            None,
            "Plaza Porticada",
            "event",
            ("mupi",),
        )
        verified = SourceEvent(
            "Concierto Música",
            date(2026, 8, 8),
            date(2026, 8, 8),
            "22:00",
            None,
            "Plaza Porticada",
            "event",
            ("mupi",),
        )

        self.assertEqual(
            intersect_verified_poster_events((first,), (verified,)),
            (),
        )

    def test_poster_fact_uses_verified_spelling_after_agreement(self):
        first = SourceEvent(
            "Concierto de música en la plaza",
            date(2026, 8, 8),
            date(2026, 8, 8),
            "22:00",
            None,
            "Plaza Porticada",
            "event",
            ("mupi",),
        )
        verified = SourceEvent(
            "Concierto de música en Plaza Porticada",
            date(2026, 8, 8),
            date(2026, 8, 8),
            "22:00",
            None,
            "Plaza Porticada",
            "event",
            ("mupi",),
        )

        accepted = intersect_verified_poster_events((first,), (verified,))

        self.assertEqual(accepted, (verified,))

    def test_candidate_normalization_keeps_valid_sibling(self):
        result = {
            "month": "2026-08",
            "events": [
                {
                    "title_es": "Concierto confirmado",
                    "start_date": "2026-08-08",
                    "end_date": "2026-08-08",
                    "start_time": "22:00",
                    "end_time": None,
                    "place": "Plaza Porticada",
                    "category": "event",
                },
                {
                    "title_es": "Fecha imposible",
                    "start_date": "2026-10-08",
                    "end_date": "2026-10-08",
                    "start_time": None,
                    "end_time": None,
                    "place": None,
                    "category": "event",
                },
            ],
        }

        events = normalize_extraction_candidates(result, "2026-08", "mupi")

        self.assertEqual([event.title_es for event in events], [
            "Concierto confirmado"
        ])

    def test_finds_only_official_mupi_poster(self):
        page = b"""
        <a href="https://example.com/MUPI-JULIO.jpg">bad</a>
        <a href="https://www.guardamardelsegura.es/wp-content/uploads/2026/07/MUPI-JULIO-2026-scaled.jpg">poster</a>
        """
        self.assertIn("MUPI-JULIO-2026", extract_poster_url(page))

    def test_normalizes_events_and_excludes_services(self):
        events = normalize_extraction(extraction())
        self.assertEqual([event.title_es for event in events], [
            "Concierto en el castillo",
            "Entropía",
        ])

    def test_rejects_ocr_month_different_from_poster(self):
        with self.assertRaises(MunicipalAgendaError) as raised:
            normalize_extraction(extraction(), "2026-08")
        self.assertEqual(raised.exception.diagnostic_code, "MONTH")

    def test_rejects_event_beyond_poster_and_next_month(self):
        result = extraction()
        result["events"][0]["start_date"] = "2026-09-01"
        result["events"][0]["end_date"] = "2026-09-01"
        with self.assertRaises(MunicipalAgendaError) as raised:
            normalize_extraction(result, "2026-07")
        self.assertEqual(raised.exception.diagnostic_code, "MONTH")

    def test_snapshot_contains_source_facts_not_translation(self):
        events = normalize_extraction(extraction())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            data = _snapshot_data(
                "https://www.guardamardelsegura.es/wp-content/uploads/MUPI.jpg",
                "abc",
                datetime(2026, 7, 27, tzinfo=TZ),
                events,
            )
            _write_snapshot(path, data)
            loaded = _load_snapshot(path)
            raw = json.loads(path.read_text())
        self.assertEqual(len(loaded["_events"]), 2)
        self.assertNotIn("title_ru", path.read_text() if path.exists() else json.dumps(raw))
        self.assertEqual(raw["events"][0]["title_es"], "Concierto en el castillo")

    def test_snapshot_loader_skips_entries_removed_by_new_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            path.write_text(json.dumps({
                "version": 2,
                "fetched_at": datetime(2026, 8, 5, tzinfo=TZ).isoformat(),
                "events": [
                    {
                        "title_es": "Actividades del Centro Social Juvenil",
                        "start_date": "2026-08-05",
                        "end_date": "2026-08-05",
                        "start_time": "08:30",
                        "end_time": "14:00",
                        "place": "Centro Social Juvenil",
                        "category": "event",
                        "sources": [],
                    },
                    {
                        "title_es": "SPANISH BRASS",
                        "start_date": "2026-08-05",
                        "end_date": "2026-08-05",
                        "start_time": "22:00",
                        "end_time": None,
                        "place": "Castell de Guardamar",
                        "category": "event",
                        "sources": ["todo_cultura"],
                    },
                ],
            }), encoding="utf-8")

            loaded = _load_snapshot(path)

        self.assertEqual(len(loaded["_events"]), 1)
        self.assertEqual(loaded["_events"][0].title_es, "SPANISH BRASS")

    def test_repairs_reviewed_entropia_facts_without_reprocessing_poster(self):
        incorrect = (
            normalize_extraction(
                {
                    "events": [
                        {
                            "title_es": "Exposición de pintura: Conchi Montes",
                            "start_date": "2026-07-03",
                            "end_date": "2026-07-29",
                            "start_time": "09:00",
                            "end_time": "14:00",
                            "place": "Biblioteca Municipal",
                            "category": "exhibition",
                        }
                    ]
                }
            )
        )

        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-JULIO-2026.jpg"
            ),
            incorrect,
        )

        self.assertEqual(
            corrected[0].title_es,
            "Exposición de pintura «Entropía» de Conchi Montes",
        )
        self.assertEqual(corrected[0].start_time, "08:00")
        self.assertEqual(corrected[0].end_time, "14:00")
        self.assertEqual(
            corrected[0].place,
            "Biblioteca Pública Municipal",
        )

    def test_repairs_reviewed_august_poster_facts(self):
        incorrect = (
            SourceEvent(
                "Exposición del 24 Open de ajedrez Villa de Guardamar",
                date(2026, 8, 1),
                date(2026, 8, 8),
                None,
                None,
                "Polideportivo Municipal Guardamar",
                "exhibition",
                ("mupi",),
            ),
            SourceEvent(
                "Rutas nocturnas y dinámica grupal",
                date(2026, 8, 1),
                date(2026, 8, 1),
                None,
                None,
                "Guardamar del Segura",
                "event",
                ("mupi",),
            ),
        )

        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            incorrect,
        )

        tennis = next(
            event for event in corrected if "Torneo de tenis" in event.title_es
        )
        routes = [
            event for event in corrected if "Rutas nocturnas" in event.title_es
        ]
        self.assertEqual(tennis.start_date, date(2026, 8, 1))
        self.assertIsNone(tennis.start_time)
        self.assertEqual(
            [(event.start_date.day, event.start_time) for event in routes],
            [(7, "22:15"), (14, "22:15"), (21, "22:15"), (28, "22:15")],
        )
        self.assertFalse(any(
            "ajedrez" in event.title_es.casefold() for event in corrected
        ))
        labores = next(
            event
            for event in corrected
            if "Labores a la fresca" in event.title_es
        )
        self.assertEqual(labores.start_date, date(2026, 8, 6))
        self.assertEqual((labores.start_time, labores.end_time), (
            "18:00", "20:00"
        ))
        self.assertEqual(labores.ticket_price_cents, 0)
        workshops = [
            event for event in corrected
            if event.place == "Centro Social Juvenil"
        ]
        self.assertEqual(
            [(event.start_date.day, event.start_time) for event in workshops],
            [(1, "19:00"), (8, "19:00"), (15, "19:00"),
             (22, "19:00"), (29, "19:00")],
        )

    def test_august_first_day_keeps_only_reviewed_active_events(self):
        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            (),
        )
        scheduled = _apply_reviewed_daily_schedules(
            corrected,
            date(2026, 8, 1),
        )
        active = [
            event for event in scheduled
            if event.start_date <= date(2026, 8, 1) <= event.end_date
        ]

        self.assertEqual(
            [event.title_es for event in active],
            [
                "Torneo de tenis 24.º Open Real Villa de Guardamar, "
                "Memorial Pepe y Juan Tendero 2026",
                "Exposición de pintura y escultura: "
                "Mediterráneo, el lenguaje del agua",
                "Taller de cultura K-Pop y TikTok",
            ],
        )
        self.assertEqual(active[1].start_time, "10:00")
        self.assertEqual(active[1].end_time, "14:00")

    def test_keeps_entropia_when_site_advances_to_august_poster(self):
        august_events = normalize_extraction(
            {
                "events": [
                    {
                        "title_es": "Evento de agosto",
                        "start_date": "2026-08-01",
                        "end_date": "2026-08-01",
                        "start_time": None,
                        "end_time": None,
                        "place": None,
                        "category": "event",
                    }
                ]
            }
        )

        merged = _merge_reviewed_text_agenda(august_events)

        entropia = next(
            event for event in merged if "Entropía" in event.title_es
        )
        self.assertEqual(entropia.end_date, datetime(2026, 7, 29).date())
        self.assertEqual(entropia.start_time, "08:00")

    def test_uses_published_mediterraneo_visiting_hours(self):
        event = SourceEvent(
            title_es=(
                "EXPOSICIÓN DE PINTURA: "
                "MEDITERRÁNEO, EL LENGUAJE DEL AGUA"
            ),
            start_date=datetime(2026, 6, 19).date(),
            end_date=datetime(2026, 8, 14).date(),
            start_time=None,
            end_time=None,
            place="Casa de Cultura",
            category="exhibition",
        )

        weekday = _apply_reviewed_daily_schedules(
            (event,), datetime(2026, 7, 30).date()
        )
        saturday = _apply_reviewed_daily_schedules(
            (event,), datetime(2026, 8, 1).date()
        )
        sunday = _apply_reviewed_daily_schedules(
            (event,), datetime(2026, 8, 2).date()
        )

        self.assertEqual(weekday[0].start_time, "09:00")
        self.assertEqual(weekday[0].end_time, "20:00")
        self.assertEqual(saturday[0].start_time, "10:00")
        self.assertEqual(saturday[0].end_time, "14:00")
        self.assertEqual(sunday, ())
        self.assertEqual(
            weekday[0].title_es,
            (
                "Exposición de pintura y escultura: "
                "Mediterráneo, el lenguaje del agua"
            ),
        )

    def test_normalizes_reviewed_august_sixth_event_details(self):
        events = (
            SourceEvent(
                "EXPLORADOR DE EMOCIONES: “La alegría que hay en ti”, de Cat Deeley",
                date(2026, 8, 6), date(2026, 8, 6), "11:30", None,
                "Biblioteca Infantil Municipal", "event",
            ),
            SourceEvent(
                "Actividad ‘Labores a la fresca’",
                date(2026, 8, 6), date(2026, 8, 6), "18:00", "20:00",
                "Casa de Cultura", "event",
            ),
            SourceEvent(
                "DIXI PROJECT",
                date(2026, 8, 6), date(2026, 8, 6), "19:30", None,
                "Plaça dels Llauradors", "event",
            ),
            SourceEvent(
                "BALL D’ESTIU",
                date(2026, 8, 6), date(2026, 8, 6), "21:30", "23:30",
                "Auditorio Orquesta GÚMAR. Parque Reina Sofía", "event",
            ),
            SourceEvent(
                "KIKI MORENTE",
                date(2026, 8, 6), date(2026, 8, 6), "22:00", None,
                "Castell de Guardamar", "event",
            ),
        )

        scheduled = _apply_reviewed_daily_schedules(
            events, date(2026, 8, 6)
        )

        self.assertIn("de Cat Deeley", scheduled[0].title_es)
        self.assertEqual(scheduled[1].ticket_price_cents, 0)
        self.assertEqual(
            scheduled[2].title_es,
            "DIXI PROJECT: Viaje por la música de los años 20",
        )
        self.assertIsNone(scheduled[2].ticket_price_cents)
        self.assertEqual(
            scheduled[3].place,
            "Parque Reina Sofía (Auditorio Orquesta GÚMAR)",
        )
        self.assertEqual(scheduled[3].ticket_price_cents, 0)
        self.assertEqual(scheduled[4].ticket_price_cents, 2500)
        self.assertEqual(
            scheduled[4].title_es,
            "KIKI MORENTE EN CONCIERTO. ESTIVAL AL CASTELL",
        )

    def test_vira_exhibition_uses_only_published_weekday_hours(self):
        event = SourceEvent(
            title_es="Exposición de pintura Luz a pesar del dolor - Vira Degliarenko",
            start_date=date(2026, 7, 31),
            end_date=date(2026, 8, 21),
            start_time="08:00",
            end_time="14:00",
            place="Biblioteca Municipal",
            category="exhibition",
        )

        weekday = _apply_reviewed_daily_schedules((event,), date(2026, 8, 3))
        saturday = _apply_reviewed_daily_schedules((event,), date(2026, 8, 1))

        self.assertEqual(weekday[0].start_time, "08:00")
        self.assertEqual(weekday[0].end_time, "14:00")
        self.assertEqual(weekday[0].place, "Biblioteca Municipal")
        self.assertEqual(saturday, ())

    def test_spanish_brass_price_is_restored_for_legacy_snapshot(self):
        event = SourceEvent(
            title_es="Concierto Spanish Brass «Top Secret»",
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            start_time="22:00",
            end_time=None,
            place="Castell de Guardamar",
            category="music",
        )

        scheduled = _apply_reviewed_daily_schedules(
            (event,), date(2026, 8, 5)
        )

        self.assertEqual(scheduled[0].ticket_price_cents, 1500)

    def test_spanish_brass_price_is_not_applied_to_another_date(self):
        event = SourceEvent(
            title_es="Concierto Spanish Brass",
            start_date=date(2026, 8, 6),
            end_date=date(2026, 8, 6),
            start_time="22:00",
            end_time=None,
            place="Castell de Guardamar",
            category="music",
        )

        scheduled = _apply_reviewed_daily_schedules(
            (event,), date(2026, 8, 6)
        )

        self.assertIsNone(scheduled[0].ticket_price_cents)

    def test_keeps_prior_month_events_for_seven_day_transition(self):
        new = SourceEvent(
            title_es="Evento de agosto",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 2),
            start_time="20:00",
            end_time=None,
            place="Casa de Cultura",
            category="event",
        )
        prior_today = SourceEvent(
            title_es="Fiestas de Barrio",
            start_date=date(2026, 7, 31),
            end_date=date(2026, 7, 31),
            start_time="19:00",
            end_time=None,
            place="parque C/ Berlín",
            category="event",
        )
        prior_too_far = SourceEvent(
            title_es="Evento lejano",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 20),
            start_time="19:00",
            end_time=None,
            place=None,
            category="event",
        )

        merged = _merge_transition_events(
            (new,),
            (prior_today, prior_too_far),
            date(2026, 7, 31),
        )

        self.assertEqual(
            [event.title_es for event in merged],
            ["Evento de agosto", "Fiestas de Barrio"],
        )

    async def test_marks_only_last_day_of_multiday_event(self):
        source = SourceEvent(
            title_es="Exposición",
            start_date=datetime(2026, 8, 1).date(),
            end_date=datetime(2026, 8, 14).date(),
            start_time="09:00",
            end_time="20:00",
            place="Casa de Cultura",
            category="exhibition",
        )
        with (
            patch(
                "telegrambot.municipal_agenda._cached_current_events",
                new=AsyncMock(return_value=(source,)),
            ),
            patch(
                "telegrambot.municipal_agenda.translate_event_titles",
                new=AsyncMock(return_value=["Выставка"]),
            ),
        ):
            events = await fetch_today_municipal_events(
                datetime(2026, 8, 14, 8, 0, tzinfo=TZ),
                "key",
                Path("unused.json"),
            )

        self.assertTrue(events[0].is_final_day)

    async def test_batch_translation_failure_recovers_titles_individually(self):
        first = SourceEvent(
            title_es="Primera actividad",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            start_time="10:00",
            end_time=None,
            place="Castillo",
            category="event",
        )
        second = SourceEvent(
            title_es="Segunda actividad",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            start_time="21:00",
            end_time=None,
            place="Plaza",
            category="event",
        )
        diagnostics = []
        translate = AsyncMock(side_effect=[
            GeminiError("invalid translations"),
            ["Первое мероприятие"],
            ["Второе мероприятие"],
        ])
        with (
            patch(
                "telegrambot.municipal_agenda._cached_current_events",
                new=AsyncMock(return_value=(first, second)),
            ),
            patch(
                "telegrambot.municipal_agenda.translate_event_titles",
                new=translate,
            ),
        ):
            events = await fetch_today_municipal_events(
                datetime(2026, 8, 1, 7, 30, tzinfo=TZ),
                "key",
                Path("unused.json"),
                diagnostics,
            )

        self.assertEqual(
            [event.title for event in events],
            ["Первое мероприятие", "Второе мероприятие"],
        )
        self.assertEqual(translate.await_count, 3)
        self.assertEqual(diagnostics, [])

    async def test_unchanged_poster_uses_snapshot_without_ocr(self):
        events = normalize_extraction(extraction())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            url = (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-JULIO-2026-scaled.jpg"
            )
            _write_snapshot(
                path,
                _snapshot_data(
                    url,
                    "abc",
                    datetime(2026, 7, 26, tzinfo=TZ),
                    events,
                    {"mupi": {"url": url, "sha256": "abc"}},
                ),
            )
            page = f'<a href="{url}">poster</a>'.encode()
            with patch(
                "telegrambot.municipal_agenda._read_url",
                return_value=(page, "text/html"),
            ), patch(
                "telegrambot.municipal_agenda.extract_agenda_events",
                new=AsyncMock(),
            ) as ocr:
                current = await _current_events(
                    "key", datetime(2026, 7, 27, tzinfo=TZ), path
                )
        self.assertEqual(len(current), 2)
        ocr.assert_not_awaited()

    async def test_todo_cultura_adds_only_requested_daily_section(self):
        official = SourceEvent(
            title_es="Concierto oficial",
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            start_time="22:00",
            end_time=None,
            place="Castillo",
            category="event",
            sources=("mupi",),
        )
        todo = TodoCulturaProgram(
            text="Miércoles 5 de agosto\n19 h.: Taller juvenil.",
            sha256="todo-hash",
            source_url="https://todoculturavegabaja.es/eventos/guardamar/",
            modified="2026-08-04T22:40:40",
        )
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        fetch_todo = AsyncMock(return_value=todo)
        extract_text = AsyncMock(return_value={
            "month": "2026-08",
            "events": [{
                "title_es": "Taller juvenil",
                "start_date": "2026-08-05",
                "end_date": "2026-08-05",
                "start_time": "19:00",
                "end_time": None,
                "place": "Centro Social Juvenil",
                "category": "event",
            }],
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    poster_url,
                    "poster-hash",
                    datetime(2026, 8, 4, tzinfo=TZ),
                    (official,),
                    {"mupi": {"url": poster_url, "sha256": "poster-hash"}},
                ),
            )
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(page, "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_latest_program",
                    new=fetch_todo,
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=extract_text,
                ),
            ):
                current = await _current_events(
                    "key", datetime(2026, 8, 5, 5, 10, tzinfo=TZ), path
                )
                await _current_events(
                    "key", datetime(2026, 8, 5, 10, 10, tzinfo=TZ), path
                )

            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(fetch_todo.await_count, 2)
        self.assertEqual(fetch_todo.await_args_list[0].args, (date(2026, 8, 5),))
        extract_text.assert_awaited_once_with("key", todo.text)
        self.assertEqual(
            [event.title_es for event in current],
            ["Concierto oficial", "Taller juvenil"],
        )
        self.assertEqual(
            stored["sources"]["todo_cultura"]["sha256"], "todo-hash"
        )

    async def test_site_failure_uses_snapshot_and_translates_selected_events(self):
        events = normalize_extraction(extraction())
        diagnostics = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    "https://www.guardamardelsegura.es/wp-content/uploads/MUPI.jpg",
                    "abc",
                    datetime(2026, 7, 26, tzinfo=TZ),
                    events,
                ),
            )
            with patch(
                "telegrambot.municipal_agenda._read_url",
                side_effect=MunicipalAgendaError("offline"),
            ), patch(
                "telegrambot.municipal_agenda.translate_event_titles",
                new=AsyncMock(
                    return_value=["Концерт в замке", "Выставка «Энтропия»"]
                ),
            ):
                current = await fetch_today_municipal_events(
                    datetime(2026, 7, 27, tzinfo=TZ),
                    "key",
                    path,
                    diagnostics,
                )
        self.assertEqual(current[0].title, "Концерт в замке")
        self.assertEqual(current[0].starts_at.hour, 21)
        self.assertEqual(current[0].ends_at.hour, 23)
        self.assertEqual(current[1].place, "Biblioteca")
        self.assertEqual(current[1].category, "exhibition")
        self.assertEqual(diagnostics, [])

    async def test_corrupt_snapshot_is_rebuilt_from_official_poster(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            path.write_text("{broken", encoding="utf-8")
            poster_url = (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/08/MUPI-AGOSTO-2026.jpg"
            )
            page = f'<a href="{poster_url}">poster</a>'.encode()
            diagnostics = []

            def read_url(url, allowed_hosts, limit):
                if "agenda-cultural" in url:
                    return page, "text/html"
                return b"poster", "image/jpeg"

            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    side_effect=read_url,
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_events",
                    new=AsyncMock(
                        return_value={
                            "month": "2026-08",
                            "events": [{
                                "title_es": "Concierto",
                                "start_date": "2026-08-01",
                                "end_date": "2026-08-01",
                                "start_time": "21:00",
                                "end_time": None,
                                "place": "Castillo",
                                "category": "event",
                            }]
                        }
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.verify_agenda_poster_events",
                    new=AsyncMock(
                        return_value={
                            "month": "2026-08",
                            "events": [{
                                "title_es": "Concierto",
                                "start_date": "2026-08-01",
                                "end_date": "2026-08-01",
                                "start_time": "21:00",
                                "end_time": None,
                                "place": "Castillo",
                                "category": "event",
                            }],
                        }
                    ),
                ),
            ):
                current = await _current_events(
                    "key",
                    datetime(2026, 8, 1, tzinfo=TZ),
                    path,
                    diagnostics,
                )

            self.assertEqual(current[0].title_es, "Concierto")
            self.assertEqual(
                diagnostics[0].code,
                "MUNI-AGENDA-SNAPSHOT-CORRUPT",
            )
            self.assertEqual(json.loads(path.read_text())["version"], 2)

    async def test_snapshot_write_failure_keeps_new_events(self):
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        diagnostics = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    side_effect=(
                        (page, "text/html"),
                        (b"poster", "image/jpeg"),
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_events",
                    new=AsyncMock(
                        return_value={
                            "month": "2026-08",
                            "events": [{
                                "title_es": "Concierto",
                                "start_date": "2026-08-01",
                                "end_date": "2026-08-01",
                                "start_time": "21:00",
                                "end_time": None,
                                "place": "Castillo",
                                "category": "event",
                            }],
                        }
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.verify_agenda_poster_events",
                    new=AsyncMock(
                        return_value={
                            "month": "2026-08",
                            "events": [{
                                "title_es": "Concierto",
                                "start_date": "2026-08-01",
                                "end_date": "2026-08-01",
                                "start_time": "21:00",
                                "end_time": None,
                                "place": "Castillo",
                                "category": "event",
                            }],
                        }
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda._write_snapshot",
                    side_effect=OSError("disk full"),
                ),
            ):
                current = await _current_events(
                    "key",
                    datetime(2026, 8, 1, tzinfo=TZ),
                    path,
                    diagnostics,
                )
        self.assertEqual(current[0].title_es, "Concierto")
        self.assertEqual(
            diagnostics[0].code,
            "MUNI-AGENDA-SNAPSHOT-WRITE",
        )

    async def test_same_poster_is_rechecked_when_local_month_changes(self):
        events = normalize_extraction(extraction())
        poster = b"same poster"
        poster_hash = hashlib.sha256(poster).hexdigest()
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    poster_url,
                    poster_hash,
                    datetime(2026, 7, 31, tzinfo=TZ),
                    events,
                    {"mupi": {
                        "url": poster_url,
                        "sha256": poster_hash,
                    }},
                ),
            )
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    side_effect=(
                        (page, "text/html"),
                        (poster, "image/jpeg"),
                    ),
                ) as read_url,
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_events",
                    new=AsyncMock(),
                ) as ocr,
            ):
                await _current_events(
                    "key",
                    datetime(2026, 8, 1, tzinfo=TZ),
                    path,
                )

            self.assertEqual(read_url.call_count, 1)
            ocr.assert_not_awaited()
            refreshed = json.loads(path.read_text())
            self.assertTrue(
                refreshed["fetched_at"].startswith("2026-08-01")
            )

    async def test_first_ocr_failure_remains_optional_source_error(self):
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    side_effect=(
                        (page, "text/html"),
                        (b"poster", "image/jpeg"),
                    ),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_events",
                    new=AsyncMock(
                        side_effect=GeminiError(
                            "quota",
                            code="API-RESOURCE_EXHAUSTED",
                            description="Gemini исчерпал квоту",
                        )
                    ),
                ),
            ):
                with self.assertRaises(MunicipalAgendaError) as raised:
                    await _current_events(
                        "key",
                        datetime(2026, 8, 1, tzinfo=TZ),
                        path,
                    )

            self.assertEqual(
                raised.exception.diagnostic_code,
                "API-RESOURCE_EXHAUSTED",
            )


if __name__ == "__main__":
    unittest.main()
