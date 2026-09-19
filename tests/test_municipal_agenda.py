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
    _expand_explicit_todo_dates,
    _explicit_fiesta_article_events,
    _strict_quoted_todo_activity,
    _turismo_programme_events,
    _unmatched_todo_rows,
    _read_turismo_programme,
    _enrich_admissions,
    _enrich_cultura_teasers,
    _enrich_todo_participation,
    _enrich_todo_summaries,
    _facebook_fingerprint,
    _apply_reviewed_corrections,
    _apply_reviewed_daily_schedules,
    _load_snapshot,
    _merge_transition_events,
    _normalize_exhibition_opening_times,
    _snapshot_data,
    _write_snapshot,
    _sanitize_generic_agenda_ticket_url,
    extract_poster_url,
    extract_official_agenda_text,
    extract_official_exhibitions,
    intersect_verified_poster_events,
    merge_text_and_poster_events,
    _poster_month,
    fetch_today_municipal_events,
    normalize_extraction,
    normalize_extraction_candidates,
    refresh_municipal_catalog,
)
from telegrambot.gemini import GeminiError
from telegrambot.facebook import FacebookError, FacebookPost
from telegrambot.digest import build_event_section
from telegrambot.todo_cultura import (
    TodoCulturaAdmission,
    TodoCulturaError,
    TodoCulturaParticipation,
    TodoCulturaProgram,
    TodoCulturaSummary,
    TodoCulturaWindow,
    _participation,
)

TZ = ZoneInfo("Europe/Madrid")


class ExplicitTodoDatesTest(unittest.TestCase):
    def test_same_time_different_event_does_not_cover_missing_row(self):
        tour = SourceEvent(
            title_es="Visita guiada Castillo y Molino",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 12),
            start_time="10:00",
            end_time=None,
            place=None,
            category="event",
            sources=("todo_cultura",),
        )
        rows = (
            (date(2026, 9, 12), "10:00", "2026-09-12\n– 10 h.: Visita guiada Castillo y Molino"),
            (date(2026, 9, 12), "10:00", "2026-09-12\n– 10 a 14 h.: Torneo de Tenis de Mesa"),
        )
        self.assertEqual(_unmatched_todo_rows(rows, (tour,)), rows[1:])

    def test_official_fiesta_article_has_dated_programme_without_ocr(self):
        text = (
            "El sábado 12 de septiembre concentra los actos. Tras el disparo "
            "de cohetes de las 13:00 horas, la entrada de bandas comenzará "
            "a las 18:30 y el Desfile Multicolor saldrá a las 19:00 horas. "
            "Continuará con fuegos artificiales, Fiesta del Vino a las "
            "21:00 horas y actuaciones desde las 23:00 horas. Participarán "
            "la Escuela Chari Candela, Retropop, DJ y Hora Loca, además de "
            "Gamburrino para mayores y Gamburrino Juvenil para jóvenes. "
            "El domingo 13 habrá chocolate con mona de madrugada, "
            "Despertà a las 6:00 horas y cierre con Charanga a las 10:00 "
            "horas. Es importante consultar cambios."
        )
        events = _explicit_fiesta_article_events(text, 2026)
        self.assertEqual(len(events), 9)
        self.assertEqual(events[2].start_time, "19:00")
        self.assertIsNone(events[3].start_time)
        self.assertEqual(events[-1].start_date, date(2026, 9, 13))

    def test_strict_activity_recovery_uses_only_row_facts(self):
        row = (
            "2026-09-12\n"
            "– 11 a 13 h.: Actividad con el título ‘Aprender a dibujar de cero "
            "a realista’ para jóvenes en el Centro Social Juvenil."
        )
        event = _strict_quoted_todo_activity(
            date(2026, 9, 12), "11:00", row
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.title_es, "Aprender a dibujar de cero a realista")
        self.assertEqual(event.end_time, "13:00")
        self.assertEqual(event.place, "Centro Social Juvenil")

    def test_future_named_saturdays_survive_rolling_window(self):
        route = SourceEvent(
            title_es="Ruta gratuita al punto geodésico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 12),
            start_time="08:30",
            end_time=None,
            place="Guardamar",
            category="event",
            sources=("todo_cultura",),
        )
        row = (
            "Sábado 12 de septiembre\n"
            "– 8,30 horas: Ruta gratuita al punto geodésico.\n"
            "El resto de las fechas serán los sábados 19 y 26 de septiembre."
        )
        result = _expand_explicit_todo_dates(
            (route,), ((date(2026, 9, 12), "08:30", row),)
        )
        self.assertEqual(
            [event.start_date for event in result],
            [date(2026, 9, 12), date(2026, 9, 19), date(2026, 9, 26)],
        )

    def test_does_not_invent_non_matching_weekday(self):
        event = SourceEvent(
            title_es="Ruta gratuita al punto geodésico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 12),
            start_time="08:30",
            end_time=None,
            place=None,
            category="event",
            sources=("todo_cultura",),
        )
        row = (
            "Sábado 12 de septiembre\n"
            "– 8,30 horas: Ruta gratuita al punto geodésico.\n"
            "El resto de las fechas serán los sábados 18 de septiembre."
        )
        self.assertEqual(
            _expand_explicit_todo_dates(
                (event,), ((date(2026, 9, 12), "08:30", row),)
            ),
            (event,),
        )


class TurismoProgrammeFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_url_replaced_poster_is_read_again(self):
        text = (
            "El sábado 12 de septiembre: disparo de cohetes de las 13:00 "
            "horas, la entrada de bandas comenzará a las 18:30 y el "
            "Desfile Multicolor saldrá a las 19:00 horas. Después fuegos "
            "artificiales, Fiesta del Vino a las 21:00 horas y actuaciones "
            "desde las 23:00 horas. Participarán la Escuela Chari Candela, "
            "Retropop, DJ y Hora Loca, además de Gamburrino para mayores "
            "y Gamburrino Juvenil para jóvenes. El domingo 13 habrá "
            "chocolate con mona de madrugada, Despertà a las 6:00 horas "
            "y cierre con Charanga a las 10:00 horas. Es importante."
        )
        existing = _explicit_fiesta_article_events(text, 2026)
        prior = {
            "article_url": "https://guardamarturismo.com/article",
            "poster_url": "https://guardamarturismo.com/poster.jpg",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "poster_sha256": hashlib.sha256(b"old-image").hexdigest(),
            "extractor_version": 2,
        }
        extraction = AsyncMock(side_effect=GeminiError("offline"))
        with patch(
            "telegrambot.municipal_agenda._read_turismo_programme",
            return_value=(prior["article_url"], prior["poster_url"], text),
        ), patch(
            "telegrambot.municipal_agenda.fetch_bounded",
            return_value=(b"new-image", prior["poster_url"], "image/jpeg"),
        ), patch(
            "telegrambot.municipal_agenda.extract_agenda_events",
            new=extraction,
        ):
            await _turismo_programme_events(
                "test", date(2026, 9, 12), existing, prior
            )
        extraction.assert_awaited_once()

    async def test_official_article_survives_image_extraction_failure(self):
        text = (
            "El sábado 12 de septiembre: disparo de cohetes de las 13:00 "
            "horas, la entrada de bandas comenzará a las 18:30 y el "
            "Desfile Multicolor saldrá a las 19:00 horas. Después, fuegos "
            "artificiales, Fiesta del Vino a las 21:00 horas y actuaciones "
            "desde las 23:00 horas. Participarán la Escuela Chari Candela, "
            "Retropop, DJ y Hora Loca, además de Gamburrino para mayores "
            "y Gamburrino Juvenil para jóvenes. El domingo 13 habrá "
            "chocolate con mona de madrugada, Despertà a las 6:00 horas "
            "y cierre con Charanga a las 10:00 horas. Es importante."
        )
        with patch(
            "telegrambot.municipal_agenda._read_turismo_programme",
            return_value=("https://guardamarturismo.com/article", "https://guardamarturismo.com/poster.jpg", text),
        ), patch(
            "telegrambot.municipal_agenda.fetch_bounded",
            return_value=(b"image", "https://guardamarturismo.com/poster.jpg", "image/jpeg"),
        ), patch(
            "telegrambot.municipal_agenda.extract_agenda_events",
            new=AsyncMock(side_effect=GeminiError("offline")),
        ):
            events, state = await _turismo_programme_events(
                "test", date(2026, 9, 12), (), {}
            )
        self.assertEqual(len(events), 9)
        self.assertIsNone(next(e for e in events if e.title_es == "Fuegos artificiales").start_time)
        self.assertEqual(state["extractor_version"], 1)


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
        programme_patcher = patch(
            "telegrambot.municipal_agenda._turismo_programme_events",
            new=AsyncMock(side_effect=lambda _key, _day, prior, state: (
                prior, state
            )),
        )
        programme_patcher.start()
        self.addCleanup(programme_patcher.stop)
        patcher = patch(
            "telegrambot.municipal_agenda.fetch_program_window",
            new=AsyncMock(side_effect=TodoCulturaError(
                "offline in unit tests",
                code="NETWORK",
                description="test source unavailable",
            )),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        facebook_patcher = patch(
            "telegrambot.municipal_agenda.fetch_facebook_posts",
            new=AsyncMock(return_value=()),
        )
        facebook_patcher.start()
        self.addCleanup(facebook_patcher.stop)

    def test_timed_text_enriches_untimed_monthly_poster_occurrence(self):
        day = date(2026, 9, 12)
        poster = SourceEvent(
            "Torneo de Presentación del Club Tenis de Mesa Guardamar",
            day, day, None, None, "Guardamar del Segura", "event",
            ("mupi",),
        )
        programme = SourceEvent(
            "Torneo de presentación del Club Tenis de Mesa Guardamar",
            day, day, "10:00", "14:30", "Pabellón Sant Jaume", "event",
            ("todo_cultura",),
        )
        merged = merge_text_and_poster_events((poster,), (programme,))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start_time, "10:00")
        self.assertEqual(merged[0].end_time, "14:30")
        self.assertEqual(merged[0].place, "Pabellón Sant Jaume")

    def test_current_exhibition_obeys_official_weekend_opening_days(self):
        exhibition = SourceEvent(
            "IMBORRABLE", date(2026, 9, 1), date(2026, 10, 16),
            None, None, "Casa de Cultura", "exhibition", ("turismo_html",),
        )
        saturday = _apply_reviewed_daily_schedules(
            (exhibition,), date(2026, 9, 12)
        )
        sunday = _apply_reviewed_daily_schedules(
            (exhibition,), date(2026, 9, 13)
        )
        self.assertEqual(saturday[0].start_time, "10:00")
        self.assertEqual(saturday[0].end_time, "14:00")
        self.assertEqual(sunday, ())

    def test_discovers_full_size_poster_from_official_wordpress_article(self):
        post = [{
            "title": {"rendered": "Programa Fiestas del Campo 2026"},
            "link": "https://guardamarturismo.com/programa-campo/",
            "content": {"rendered": (
                "<p>El sábado 12 de septiembre hay actos.</p>"
                "[vc_btn link=\"url:https%3A%2F%2Fguardamarturismo.com%2F"
                "wp-content%2Fuploads%2F2026%2F08%2FCARTEL-OK-"
                "fiestas-del-campo-2026.jpg-1-scaled.jpeg|target:_blank\"]"
            )},
        }]
        with patch(
            "telegrambot.municipal_agenda.fetch_bounded",
            return_value=(json.dumps(post).encode(), "", "application/json"),
        ):
            found = _read_turismo_programme(date(2026, 9, 12))
        self.assertIsNotNone(found)
        self.assertTrue(found[1].endswith("-1-scaled.jpeg"))

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

    def test_corroborating_source_can_make_same_title_self_contained(self):
        official = SourceEvent(
            "TRIVOX (Tributo a Il Divo)",
            date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("turismo_html",),
        )
        supplement = SourceEvent(
            "Concierto benéfico TRIVOX, tributo a Il Divo, a favor de "
            "Alicante contra el cáncer",
            date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("todo_cultura",),
        )

        merged = merge_text_and_poster_events((official,), (supplement,))

        self.assertEqual(merged[0].title_es, supplement.title_es)
        self.assertEqual(
            merged[0].sources, ("turismo_html", "todo_cultura")
        )

    def test_corroborating_source_cannot_replace_event_identity(self):
        official = SourceEvent(
            "TRIVOX", date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("turismo_html",),
        )
        conflicting = SourceEvent(
            "Concierto de otra banda con repertorio clásico",
            date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("todo_cultura",),
        )

        merged = merge_text_and_poster_events((official,), (conflicting,))

        self.assertEqual(merged[0].title_es, "TRIVOX")

    def test_mupi_cannot_enrich_primary_html_title(self):
        official = SourceEvent(
            "TRIVOX", date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("turismo_html",),
        )
        poster = SourceEvent(
            "TRIVOX gran gala inventada solidaria",
            date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("mupi",),
        )

        merged = merge_text_and_poster_events((official,), (poster,))

        self.assertEqual(merged[0].title_es, "TRIVOX")

    def test_same_occurrence_merge_preserves_todo_summary(self):
        day = date(2026, 9, 19)
        official = SourceEvent(
            "III Chupinazo", day, day, "11:00", "15:00",
            "Plaza de la Constitución", "event", ("turismo_html",),
        )
        supplement = SourceEvent(
            "III Chupinazo de Guardamar", day, day, "11:00", "15:00",
            "Plaza de la Constitución", "event",
            ("todo_cultura", "todo_cultura_summary"),
            teaser_es="Habrá animación, música, fiesta, barra, dj's y regalos.",
        )

        merged = merge_text_and_poster_events((official,), (supplement,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0].teaser_es,
            "Habrá animación, música, fiesta, barra, dj's y regalos.",
        )

    def test_unrelated_todo_event_at_same_slot_remains_distinct(self):
        official = SourceEvent(
            "Concierto Alpha", date(2026, 8, 30), date(2026, 8, 30),
            "22:30", None, "Casa de Cultura", "event", ("turismo_html",),
        )
        supplement = SourceEvent(
            "Teatro Beta", date(2026, 8, 30), date(2026, 8, 30),
            "22:30", None, "Casa de Cultura", "event", ("todo_cultura",),
            ticket_price_cents=1200,
            ticket_url="https://www.giglon.com/event/beta",
        )

        merged = merge_text_and_poster_events((official,), (supplement,))

        self.assertEqual(len(merged), 2)
        self.assertIsNone(merged[0].ticket_price_cents)
        self.assertEqual(merged[1].ticket_price_cents, 1200)

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

    def test_same_title_and_time_at_different_places_are_not_merged(self):
        first = SourceEvent(
            "Actividad juvenil", date(2026, 8, 5), date(2026, 8, 5),
            "19:00", None, "Centro Social Juvenil", "event",
            ("turismo_html",),
        )
        second = SourceEvent(
            "Actividad juvenil", date(2026, 8, 5), date(2026, 8, 5),
            "19:00", None, "Castillo", "event", ("todo_cultura",),
        )

        merged = merge_text_and_poster_events((first,), (second,))

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
            "Concierto Spanish Brass «Top secret»",
            1500,
            "https://www.agendaguardamar.com/espectaculo/48/"
            "spanish-brass-top-secret.html",
        ),)

        enriched = _enrich_admissions(
            (spanish_brass, other), admissions
        )

        self.assertEqual(enriched[0].ticket_price_cents, 1500)
        self.assertIn("spanish-brass", enriched[0].ticket_url)
        self.assertIn("todo_cultura_detail", enriched[0].sources)
        self.assertIsNone(enriched[1].ticket_price_cents)

    def test_generic_event_name_does_not_borrow_another_events_price(self):
        generic = SourceEvent(
            "Concierto", date(2026, 8, 5), date(2026, 8, 5), "22:00", None,
            "Castillo", "event", ("todo_cultura",),
        )
        admissions = (TodoCulturaAdmission(
            "22:30: Concierto benéfico de Trivox",
            2000,
            "https://www.giglon.com/todos?idEvent=trivox",
            event_date=date(2026, 8, 5),
        ),)

        enriched = _enrich_admissions((generic,), admissions)

        self.assertIsNone(enriched[0].ticket_price_cents)
        self.assertIsNone(enriched[0].ticket_url)

    def test_admission_date_prevents_cross_day_enrichment(self):
        event = SourceEvent(
            "Concierto benéfico de Trivox",
            date(2026, 8, 14), date(2026, 8, 14), "22:30", None,
            "Parque Reina Sofía", "event", ("todo_cultura",),
        )
        admission = TodoCulturaAdmission(
            "22:30: Concierto benéfico de Trivox",
            2000,
            "https://www.giglon.com/todos?idEvent=trivox",
            event_date=date(2026, 8, 15),
        )

        enriched = _enrich_admissions((event,), (admission,))

        self.assertIsNone(enriched[0].ticket_price_cents)
        self.assertIsNone(enriched[0].ticket_url)

    def test_admission_time_selects_only_matching_session(self):
        early = SourceEvent(
            "Teatro Beta", date(2026, 8, 30), date(2026, 8, 30),
            "18:00", None, "Casa de Cultura", "event", ("todo_cultura",),
        )
        late = SourceEvent(
            "Teatro Beta", date(2026, 8, 30), date(2026, 8, 30),
            "20:00", None, "Casa de Cultura", "event", ("todo_cultura",),
        )
        admission = TodoCulturaAdmission(
            "20 h.: Teatro Beta", 800,
            "https://www.giglon.com/event/beta-20",
            event_date=date(2026, 8, 30), start_time="20:00",
        )

        enriched = _enrich_admissions((early, late), (admission,))

        self.assertIsNone(enriched[0].ticket_price_cents)
        self.assertEqual(enriched[1].ticket_price_cents, 800)

    def test_timeless_admission_is_withheld_for_multiple_sessions(self):
        sessions = tuple(
            SourceEvent(
                "Teatro Beta", date(2026, 8, 30), date(2026, 8, 30),
                start_time, None, "Casa de Cultura", "event",
                ("todo_cultura",),
            )
            for start_time in ("18:00", "20:00")
        )
        admission = TodoCulturaAdmission(
            "Teatro Beta", 800,
            "https://www.giglon.com/event/beta",
            event_date=date(2026, 8, 30),
        )

        enriched = _enrich_admissions(sessions, (admission,))

        self.assertTrue(all(
            event.ticket_price_cents is None for event in enriched
        ))

    def test_todo_registration_enriches_matching_occurrence_only(self):
        drums = SourceEvent(
            "Taller de baterías", date(2026, 8, 8), date(2026, 8, 8),
            "19:00", "21:00", "Centro Social Juvenil", "event",
            ("mupi",),
        )
        other = SourceEvent(
            "Visita Memoria de arena", date(2026, 8, 8),
            date(2026, 8, 8), "10:00", "12:00", "Castillo", "event",
            ("turismo_html",),
        )
        details = (TodoCulturaParticipation(
            title_hint=(
                "19 a 21 h.: Taller de baterías para jóvenes de 12 a 30 años"
            ),
            registration_contact=(
                "Centro Social Juvenil или WhatsApp 609 00 67 54"
            ),
            participation_note="для молодёжи 12–30 лет",
            evidence="Inscripciones: Centro Social Juvenil y Whatsapp 609 00 67 54",
        ),)

        enriched = _enrich_todo_participation(
            (drums, other), details, date(2026, 8, 8)
        )

        self.assertEqual(
            enriched[0].registration_contact,
            "Centro Social Juvenil или WhatsApp 609 00 67 54",
        )
        self.assertEqual(
            enriched[0].participation_note, "для молодёжи 12–30 лет"
        )
        self.assertIn("todo_cultura_detail", enriched[0].sources)
        self.assertIsNone(enriched[1].registration_contact)

    def test_sep12_route_and_drawing_fields_survive_normalization(self):
        day = date(2026, 9, 12)
        route = SourceEvent(
            "Free tour guiada y gratuita al punto geodésico",
            day, day, "08:30", None, None, "event", ("todo_cultura",),
        )
        drawing = SourceEvent(
            "Aprender a dibujar de cero a realista",
            day, day, "11:00", "13:00", "Centro Social Juvenil",
            "event", ("todo_cultura",),
        )
        details = _participation(
            "8,30 horas: Free tour guiada y gratuita al punto geodésico.\n"
            "La ruta es de dificultad baja-moderada.\n"
            "Inscripciones y reservas: talentojovenguardamar@gmail.com\n"
            "11 a 13 h.: Actividad 'Aprender a dibujar de cero a realista' "
            "para jóvenes de 12 a 30 años.\n"
            "Las plazas son limitadas.\n"
            "Para apuntarse: Whatsapp 609 00 67 54"
        )
        enriched = _enrich_todo_participation((route, drawing), details, day)
        self.assertEqual(
            enriched[0].registration_contact,
            "talentojovenguardamar@gmail.com",
        )
        self.assertEqual(
            enriched[0].details,
            ("Сложность маршрута: низкая–средняя",),
        )
        self.assertIsNone(enriched[0].participation_note)
        self.assertEqual(
            enriched[1].registration_contact,
            "WhatsApp 609 00 67 54",
        )
        self.assertTrue(enriched[1].capacity_limited)

    def test_todo_summary_enriches_only_matching_occurrence(self):
        day = date(2026, 9, 19)
        chupinazo = SourceEvent(
            "III Chupinazo", day, day, "11:00", "15:00",
            "Plaza de la Constitución", "event", ("todo_cultura",),
        )
        concert = SourceEvent(
            "Concierto coral", day, day, "20:00", None,
            "Escuela de Música", "event", ("todo_cultura",),
        )
        details = (
            TodoCulturaSummary(
                title_hint="11 a 15 h.: III Chupinazo en Plaza de la Constitución",
                teaser_es="Habrá animación, música, fiesta, barra, dj's y regalos.",
                event_dates=(day,),
                start_time="11:00",
            ),
        )

        enriched = _enrich_todo_summaries(
            (chupinazo, concert), details, day
        )

        self.assertEqual(
            enriched[0].teaser_es,
            "Habrá animación, música, fiesta, barra, dj's y regalos.",
        )
        self.assertIn("todo_cultura_summary", enriched[0].sources)
        self.assertIsNone(enriched[1].teaser_es)

    def test_todo_summary_matches_short_title_by_time_and_place(self):
        day = date(2026, 9, 19)
        chupinazo = SourceEvent(
            "Chupinazo del Segura", day, day, "11:00", "15:00",
            "Plaza del Ayuntamiento", "event", ("todo_cultura",),
        )
        other_same_time = SourceEvent(
            "Visita al Molino", day, day, "11:00", "12:00",
            "Molino de San Antonio", "event", ("todo_cultura",),
        )
        details = (
            TodoCulturaSummary(
                title_hint=(
                    "11 a 15 h.: III chupinazo de inicio de las fiestas "
                    "patronales en honor a la Virgen del Rosario en la "
                    "plaza del Ayuntamiento"
                ),
                teaser_es="Habrá animación, música, fiesta, barra, dj’s y regalos.",
                event_dates=(day,),
                start_time="11:00",
            ),
        )

        enriched = _enrich_todo_summaries(
            (chupinazo, other_same_time), details, day
        )

        self.assertEqual(
            enriched[0].teaser_es,
            "Habrá animación, música, fiesta, barra, dj’s y regalos.",
        )
        self.assertIsNone(enriched[1].teaser_es)

    def test_todo_summary_does_not_overwrite_existing_teaser(self):
        day = date(2026, 9, 19)
        existing = SourceEvent(
            "III Chupinazo", day, day, "11:00", "15:00",
            "Plaza de la Constitución", "event", ("turismo_html",),
            teaser_es="Descripción oficial existente.",
        )
        details = (
            TodoCulturaSummary(
                title_hint="11 a 15 h.: III Chupinazo",
                teaser_es="Habrá animación, música y regalos.",
                event_dates=(day,),
                start_time="11:00",
            ),
        )

        enriched = _enrich_todo_summaries((existing,), details, day)

        self.assertEqual(enriched[0].teaser_es, "Descripción oficial existente.")

    def test_todo_summary_without_time_is_withheld_for_multiple_sessions(self):
        day = date(2026, 9, 19)
        sessions = tuple(
            SourceEvent(
                "Festival Alpha", day, day, start, None,
                "Plaza", "event", ("todo_cultura",),
            )
            for start in ("11:00", "18:00")
        )
        details = (
            TodoCulturaSummary(
                title_hint="Festival Alpha",
                teaser_es="Habrá música y actividades para toda la familia.",
                event_dates=(day,),
            ),
        )

        enriched = _enrich_todo_summaries(sessions, details, day)

        self.assertTrue(all(event.teaser_es is None for event in enriched))

    def test_todo_registration_does_not_leak_to_same_title_other_time(self):
        sessions = tuple(
            SourceEvent(
                "Taller de guitarra", date(2026, 8, 20),
                date(2026, 8, 20), start_time, None,
                "Centro Social Juvenil", "event", ("todo_cultura",),
            )
            for start_time in ("17:00", "19:00")
        )
        detail = TodoCulturaParticipation(
            title_hint="19:00: Taller de guitarra",
            registration_contact="WhatsApp 600 00 00 00",
            event_dates=(date(2026, 8, 20),),
            start_time="19:00",
        )

        enriched = _enrich_todo_participation(
            sessions, (detail,), date(2026, 8, 20)
        )

        self.assertIsNone(enriched[0].registration_contact)
        self.assertEqual(
            enriched[1].registration_contact, "WhatsApp 600 00 00 00"
        )

    def test_timeless_registration_is_withheld_for_multiple_sessions(self):
        sessions = tuple(
            SourceEvent(
                "Taller de guitarra", date(2026, 8, 20),
                date(2026, 8, 20), start_time, None,
                "Centro Social Juvenil", "event", ("todo_cultura",),
            )
            for start_time in ("17:00", "19:00")
        )
        detail = TodoCulturaParticipation(
            title_hint="Taller de guitarra",
            registration_contact="WhatsApp 600 00 00 00",
            event_dates=(date(2026, 8, 20),),
        )

        enriched = _enrich_todo_participation(
            sessions, (detail,), date(2026, 8, 20)
        )

        self.assertTrue(all(
            event.registration_contact is None for event in enriched
        ))

    def test_omits_generic_youth_centre_opening_but_keeps_named_events(self):
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
                    "title_es": "Voluntariado medioambiental de verano",
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
                {
                    "title_es": "Exposición de pintura Luz mediterránea",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-31",
                    "start_time": None,
                    "end_time": None,
                    "place": "Casa de Cultura",
                    "category": "exhibition",
                },
            ],
        }, "2026-08", "todo_cultura")

        self.assertEqual([event.title_es for event in result], [
            "Actividades del Centro Social Juvenil",
            "Concierto Spanish Brass",
            "Exposición de pintura Luz mediterránea",
        ])

    def test_official_exhibition_ranges_have_deterministic_fallback(self):
        programme = (
            "AGENDA CULTURAL SEPTIEMBRE 2026 EXPOSICIONES "
            "Hasta el 16 de octubre. Sala de exposiciones de Casa de "
            "Cultura. IMBORRABLE Exposición pictórica de Jaime Aniorte. "
            "Horario: De lunes a viernes de 10:00 h a 14:00 h. "
            "Del 7 al 23 de septiembre. Hall de la Biblioteca Pública "
            "Municipal. AMIGOS Y CONOCIDOS Exposición de dibujos de José "
            "Luis Narbaiza. TEATRO 2 de septiembre, a las 20:00h."
        )

        events = extract_official_exhibitions(programme, "2026-09")

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].title_es, "IMBORRABLE")
        self.assertEqual(events[0].start_date, date(2026, 9, 1))
        self.assertEqual(events[0].end_date, date(2026, 10, 16))
        self.assertEqual(events[1].title_es, "AMIGOS Y CONOCIDOS")
        self.assertEqual(events[1].start_date, date(2026, 9, 7))
        self.assertEqual(events[1].end_date, date(2026, 9, 23))
        self.assertTrue(all(event.category == "exhibition" for event in events))

    def test_official_exhibition_opening_is_a_distinct_occurrence(self):
        programme = (
            "AGENDA CULTURAL SEPTIEMBRE 2026 EXPOSICIONES "
            "Del 25 de septiembre al 16 de octubre. Biblioteca Pública "
            "Municipal. CALENDARIO SOLIDARIO ADIMAR 2027 Exposición "
            "fotográfica Inauguración: viernes 25 de septiembre a las "
            "20:00 h. TEATRO 2 de septiembre, a las 20:00h."
        )

        events = extract_official_exhibitions(programme, "2026-09")

        self.assertEqual(len(events), 2)
        exhibition = next(
            event for event in events if event.category == "exhibition"
        )
        opening = next(
            event for event in events
            if event.category == "exhibition_opening"
        )
        self.assertEqual(exhibition.start_date, date(2026, 9, 25))
        self.assertEqual(exhibition.end_date, date(2026, 10, 16))
        self.assertIsNone(exhibition.start_time)
        self.assertEqual(opening.start_date, date(2026, 9, 25))
        self.assertEqual(opening.end_date, date(2026, 9, 25))
        self.assertEqual(opening.start_time, "20:00")
        self.assertIn("CALENDARIO SOLIDARIO ADIMAR 2027", opening.title_es)

    def test_opening_time_is_not_reused_as_daily_exhibition_time(self):
        exhibition = SourceEvent(
            "CALENDARIO SOLIDARIO ADIMAR 2027",
            date(2026, 9, 25),
            date(2026, 10, 16),
            "20:00",
            None,
            "Biblioteca Pública Municipal",
            "exhibition",
            ("turismo_html",),
        )
        opening = SourceEvent(
            "Inauguración de la exposición CALENDARIO SOLIDARIO ADIMAR 2027",
            date(2026, 9, 25),
            date(2026, 9, 25),
            "20:00",
            None,
            "Biblioteca Pública Municipal",
            "exhibition_opening",
            ("turismo_html", "turismo_exhibition_opening"),
        )

        normalized = _normalize_exhibition_opening_times(
            (exhibition, opening)
        )

        self.assertIsNone(normalized[0].start_time)
        self.assertEqual(normalized[1].start_time, "20:00")

    async def test_opening_replaces_generic_exhibition_only_on_first_day(self):
        exhibition = SourceEvent(
            "CALENDARIO SOLIDARIO ADIMAR 2027",
            date(2026, 9, 25),
            date(2026, 10, 16),
            None,
            None,
            "Biblioteca Pública Municipal",
            "exhibition",
            ("turismo_html",),
        )
        opening = SourceEvent(
            "Inauguración de la exposición CALENDARIO SOLIDARIO ADIMAR 2027",
            date(2026, 9, 25),
            date(2026, 9, 25),
            "20:00",
            None,
            "Biblioteca Pública Municipal",
            "exhibition_opening",
            ("turismo_html", "turismo_exhibition_opening"),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            translations = Path(directory) / "translations.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    "",
                    "",
                    datetime(2026, 9, 25, 5, 10, tzinfo=TZ),
                    (exhibition, opening),
                ),
            )
            first_day = await fetch_today_municipal_events(
                datetime(2026, 9, 25, 7, 0, tzinfo=TZ),
                "",
                path,
                translation_cache_path=translations,
            )
            next_day = await fetch_today_municipal_events(
                datetime(2026, 9, 26, 7, 0, tzinfo=TZ),
                "",
                path,
                translation_cache_path=translations,
            )

        self.assertEqual(len(first_day), 1)
        self.assertEqual(first_day[0].category, "exhibition_opening")
        self.assertEqual(
            first_day[0].starts_at.strftime("%H:%M"), "20:00"
        )
        self.assertEqual(len(next_day), 1)
        self.assertEqual(next_day[0].category, "exhibition")
        self.assertIsNone(next_day[0].starts_at)

    async def test_invalid_structured_text_keeps_official_exhibitions(self):
        page = b"""
        <h2>AGENDA CULTURAL SEPTIEMBRE 2026</h2>
        <p>EXPOSICIONES Del 7 al 23 de septiembre. Hall de la Biblioteca
        Publica Municipal. AMIGOS Y CONOCIDOS Exposicion de dibujos.</p>
        <p>TEATRO</p><p>Ver Agenda</p>
        """
        invalid_result = {
            "month": "2026-09",
            "events": [{
                "title_es": "Dato inventado",
                "start_date": "2026-09-08",
                "end_date": "2026-09-08",
                "start_time": None,
                "end_time": None,
                "place": "Lugar inexistente",
                "category": "event",
                "evidence_es": "texto que no aparece en la fuente",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(page, "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=AsyncMock(return_value=invalid_result),
                ),
            ):
                events = await refresh_municipal_catalog(
                    "key", datetime(2026, 9, 8, tzinfo=TZ), path
                )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title_es, "AMIGOS Y CONOCIDOS")
        self.assertEqual(events[0].start_date, date(2026, 9, 7))
        self.assertEqual(events[0].end_date, date(2026, 9, 23))

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

    def test_text_title_requires_exact_supporting_quotation(self):
        source_text = (
            "2026-08-14 22:30: Concierto benéfico de Trivox, tributo a Il "
            "Divo, a favor de Alicante contra el cáncer. Parque Reina Sofía."
        )
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": (
                    "Concierto benéfico Trivox, tributo a Il Divo, a favor "
                    "de Alicante contra el cáncer"
                ),
                "start_date": "2026-08-14",
                "end_date": "2026-08-14",
                "start_time": "22:30",
                "end_time": None,
                "place": "Parque Reina Sofía",
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        events = normalize_extraction_candidates(
            result, "2026-08", "todo_cultura", source_text
        )

        self.assertEqual(len(events), 1)

    def test_text_title_with_unsupported_claim_is_rejected(self):
        source_text = "2026-08-14 22:30: Concierto de Trivox."
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto benéfico gratuito de Trivox para UNICEF",
                "start_date": "2026-08-14",
                "end_date": "2026-08-14",
                "start_time": "22:30",
                "end_time": None,
                "place": None,
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                result, "2026-08", "todo_cultura", source_text
            )

    def test_text_title_rejects_one_unsupported_material_word(self):
        source_text = (
            "30 de agosto 22:30 h. Concierto especial Trivox. "
            "Casa de Cultura."
        )
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto especial Trivox gratuito",
                "start_date": "2026-08-30",
                "end_date": "2026-08-30",
                "start_time": "22:30",
                "end_time": None,
                "place": "Casa de Cultura",
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                result, "2026-08", "turismo_html", source_text
            )

    def test_text_title_rejects_unsupported_short_name(self):
        source_text = (
            "30 de agosto 22:30 h. Concierto Trivox. Casa de Cultura."
        )
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto DJ Trivox",
                "start_date": "2026-08-30",
                "end_date": "2026-08-30",
                "start_time": "22:30",
                "end_time": None,
                "place": "Casa de Cultura",
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                result, "2026-08", "turismo_html", source_text
            )

    def test_text_event_rejects_unsupported_schedule_and_place(self):
        source_text = "30 de agosto. Concierto Trivox."
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto Trivox",
                "start_date": "2026-08-30",
                "end_date": "2026-08-30",
                "start_time": "03:00",
                "end_time": "05:00",
                "place": "Aeropuerto de Alicante",
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                result, "2026-08", "turismo_html", source_text
            )

    def test_calendar_day_does_not_count_as_zero_minute_time_evidence(self):
        source_text = "19 de agosto. Concierto Trivox. Casa de Cultura."
        result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto Trivox",
                "start_date": "2026-08-19",
                "end_date": "2026-08-19",
                "start_time": "19:00",
                "end_time": None,
                "place": "Casa de Cultura",
                "evidence_es": source_text,
                "category": "event",
            }],
        }

        with self.assertRaises(MunicipalAgendaError):
            normalize_extraction_candidates(
                result, "2026-08", "turismo_html", source_text
            )

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

    def test_keeps_multiday_municipal_campaign(self):
        result = {
            "month": "2026-07",
            "events": [{
                "title_es": "Campaña de voluntariado medioambiental",
                "start_date": "2026-07-01",
                "end_date": "2026-08-31",
                "start_time": None,
                "end_time": None,
                "place": "Guardamar",
                "category": "municipal_service",
            }],
        }

        events = normalize_extraction(result, "2026-07")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].category, "municipal_service")
        self.assertEqual(events[0].end_date, date(2026, 8, 31))

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

    def test_snapshot_round_trips_participation_details(self):
        event = SourceEvent(
            "Taller de baterías", date(2026, 8, 8), date(2026, 8, 8),
            "19:00", "21:00", "Centro Social Juvenil", "event",
            ("mupi", "todo_cultura_detail"),
            ticket_price_cents=2000,
            ticket_url=(
                "https://www.giglon.com/todos?idEvent=taller-baterias"
            ),
            participation_note="для молодёжи 12–30 лет",
            registration_contact=(
                "Centro Social Juvenil или WhatsApp 609 00 67 54"
            ),
            capacity_limited=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                "https://www.guardamardelsegura.es/mupi.jpg",
                "abc",
                datetime(2026, 8, 8, tzinfo=TZ),
                (event,),
            ))
            loaded = _load_snapshot(path)["_events"][0]

        self.assertEqual(loaded.participation_note, "для молодёжи 12–30 лет")
        self.assertEqual(loaded.ticket_price_cents, 2000)
        self.assertEqual(
            loaded.ticket_url,
            "https://www.giglon.com/todos?idEvent=taller-baterias",
        )
        self.assertEqual(
            loaded.registration_contact,
            "Centro Social Juvenil или WhatsApp 609 00 67 54",
        )
        self.assertTrue(loaded.capacity_limited)
        self.assertIn("todo_cultura_detail", loaded.sources)

    def test_snapshot_round_trips_admission_evidence(self):
        event = SourceEvent(
            "Concierto Alpha", date(2026, 8, 30), date(2026, 8, 30),
            "20:00", None, "Casa de Cultura", "event",
            ("todo_cultura",), ticket_price_cents=800,
            ticket_url="https://www.giglon.com/event/alpha",
            admission_evidence="Concierto Alpha. Precio: 8 €.",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 8, 13, tzinfo=TZ), (event,)
            ))
            loaded = _load_snapshot(path)["_events"][0]

        self.assertEqual(
            loaded.admission_evidence,
            "Concierto Alpha. Precio: 8 €.",
        )

    def test_snapshot_rejects_ticket_url_with_userinfo(self):
        event = SourceEvent(
            "Concierto Alpha", date(2026, 8, 30), date(2026, 8, 30),
            "20:00", None, "Casa de Cultura", "event",
            ("todo_cultura",),
            ticket_url="https://operator@giglon.com/event/alpha",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 8, 13, tzinfo=TZ), (event,)
            ))

            with self.assertRaises(MunicipalAgendaError):
                _load_snapshot(path)

    def test_snapshot_loader_omits_generic_youth_centre_opening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            path.write_text(json.dumps({
                "version": 2,
                "fetched_at": datetime(2026, 8, 5, tzinfo=TZ).isoformat(),
                "events": [
                    {
                        "title_es": "Actividades del Centro Social Juvenil (CSJ)",
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

        self.assertEqual(
            [event.title_es for event in loaded["_events"]],
            ["SPANISH BRASS"],
        )

    def test_snapshot_keeps_generic_title_after_specific_enrichment(self):
        event = SourceEvent(
            "Actividades del Centro Social Juvenil (CSJ)",
            date(2026, 9, 11), date(2026, 9, 11), "08:30", "14:00",
            "calle Molivent", "event", ("todo_cultura",),
            participation_note=(
                "для молодёжи 12–30 лет; доступны настольные игры, "
                "пинг-понг и аэрохоккей"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 9, 11, tzinfo=TZ), (event,)
            ))

            loaded = _load_snapshot(path)

        self.assertEqual(loaded["_events"][0].title_es, event.title_es)
        self.assertEqual(loaded["_events"][0].place, "Centro Social Juvenil")
        self.assertEqual(loaded["_events"][0].place_query, "calle Molivent")

    async def test_cached_cultura_failure_is_visible_but_successful_no_match_is_quiet(self):
        event = SourceEvent(
            "IMBORRABLE", date(2026, 9, 1), date(2026, 10, 16),
            None, None, "Casa de Cultura", "exhibition",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            translations = Path(directory) / "translations.json"
            sources = {"cultura_guardamar": {
                "checked_at": datetime(2026, 9, 11, tzinfo=TZ).isoformat(),
                "diagnostic": {
                    "code": "CULTURA-ENRICHMENT-MARKUP",
                    "source": "Cultura Guardamar",
                    "description": "лента Facebook временно недоступна",
                },
            }}
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 9, 11, tzinfo=TZ), (event,), sources
            ))
            diagnostics = []
            await fetch_today_municipal_events(
                datetime(2026, 9, 11, tzinfo=TZ), "", path, diagnostics,
                translations,
            )
            self.assertEqual(
                [item.code for item in diagnostics],
                ["CULTURA-ENRICHMENT-MARKUP"],
            )

            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 9, 11, tzinfo=TZ), (event,),
                {"cultura_guardamar": {"checked_at": "2026-09-11T05:10:00+02:00"}},
            ))
            diagnostics = []
            await fetch_today_municipal_events(
                datetime(2026, 9, 11, tzinfo=TZ), "", path, diagnostics,
                translations,
            )
            self.assertEqual(diagnostics, [])

    async def test_cultura_teaser_reaches_final_event_rendering(self):
        event = SourceEvent(
            "IMBORRABLE", date(2026, 9, 1), date(2026, 10, 16),
            None, None, "Casa de Cultura", "exhibition",
            ("turismo_html", "cultura_guardamar"),
            teaser_es="El paisaje conserva las huellas de todo lo que ha sido.",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            translations = Path(directory) / "translations.json"
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 9, 11, tzinfo=TZ), (event,)
            ))
            with (
                patch(
                    "telegrambot.municipal_agenda.cached_title",
                    return_value="Неизгладимый",
                ),
                patch(
                    "telegrambot.municipal_agenda.cached_translation",
                    return_value="Пейзаж хранит следы всего, чем он был.",
                ),
            ):
                events = await fetch_today_municipal_events(
                    datetime(2026, 9, 11, tzinfo=TZ), "", path,
                    translation_cache_path=translations,
                )
        rendered = "\n".join(build_event_section(events, "События"))
        self.assertIn("Пейзаж хранит следы всего, чем он был.", rendered)

    async def test_todo_activity_summary_uses_dedicated_teaser_cache_key(self):
        event = SourceEvent(
            "III Chupinazo", date(2026, 9, 19), date(2026, 9, 19),
            "11:00", "15:00", "Plaza de la Constitución", "event",
            ("todo_cultura", "todo_cultura_summary"),
            teaser_es="Habrá animación, música, fiesta, barra, dj's y regalos.",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            translations = Path(directory) / "translations.json"
            _write_snapshot(path, _snapshot_data(
                "", "", datetime(2026, 9, 19, tzinfo=TZ), (event,)
            ))
            with (
                patch(
                    "telegrambot.municipal_agenda.cached_title",
                    return_value="III Chupinazo",
                ),
                patch(
                    "telegrambot.municipal_agenda.cached_translation",
                    return_value="Анимация, музыка, праздник, бар, DJ и подарки.",
                ) as translated,
            ):
                events = await fetch_today_municipal_events(
                    datetime(2026, 9, 19, 8, 0, tzinfo=TZ), "", path,
                    translation_cache_path=translations,
                )

        translated.assert_called_once_with(
            translations,
            "municipal_activity_teaser",
            "Habrá animación, música, fiesta, barra, dj's y regalos.",
        )
        rendered = "\n".join(build_event_section(events, "События"))
        self.assertIn(
            "Анимация, музыка, праздник, бар, DJ и подарки.",
            rendered,
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

        routes = [
            event for event in corrected if "Rutas nocturnas" in event.title_es
        ]
        self.assertEqual(
            [(event.start_date.day, event.start_time) for event in routes],
            [(14, "22:15"), (21, "22:15"), (28, "22:15")],
        )
        self.assertFalse(any(
            "open de ajedrez" in event.title_es.casefold()
            for event in corrected
        ))
        exhibitions = [
            event for event in corrected if event.category == "exhibition"
        ]
        self.assertEqual(len(exhibitions), 2)
        workshops = [
            event for event in corrected
            if event.place == "Centro Social Juvenil"
        ]
        self.assertEqual(
            [(event.start_date.day, event.start_time) for event in workshops],
            [(15, "19:00"), (22, "19:00"), (29, "19:00")],
        )
        guitar = next(
            event for event in workshops if event.start_date.day == 15
        )
        self.assertIn("12–30 лет", guitar.participation_note)
        self.assertIn("игру в группе", guitar.participation_note)
        self.assertEqual(
            guitar.registration_contact,
            "Centro Social Juvenil или WhatsApp 609 00 67 54",
        )

    def test_reviewed_active_events_for_current_day(self):
        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            (),
        )
        scheduled = _apply_reviewed_daily_schedules(
            corrected,
            date(2026, 8, 14),
        )
        active = [
            event for event in scheduled
            if event.start_date <= date(2026, 8, 14) <= event.end_date
        ]

        self.assertEqual(
            [event.title_es for event in active],
            [
                "Concierto benéfico: TRIVOX (Tributo a Il Divo) para la "
                "lucha contra el cáncer",
                "Exposición de pintura y escultura: "
                "Mediterráneo, el lenguaje del agua",
                "Exposición de pintura «Luz a pesar del dolor» "
                "de Vira Degliarenko",
                "Rutas nocturnas: senderismo y dinámica grupal",
                "Feria de Comercio 2026: talleres, ajedrez gigante, "
                "ELBOX GRM y Dirty Piks",
            ],
        )
        self.assertEqual(active[0].ticket_price_cents, 2000)
        self.assertIn("idEvent=concierto-benefico-trivox", active[0].ticket_url)
        self.assertEqual(active[1].start_time, "09:00")
        self.assertEqual(active[1].end_time, "20:00")

    def test_reviewed_fallback_keeps_each_fair_act_at_its_own_time(self):
        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            (),
        )
        fair = [
            event for event in corrected
            if event.start_date == date(2026, 8, 16)
            and event.place == "Avenida de los Pinos"
        ]

        self.assertEqual(
            [(event.start_time, event.end_time) for event in fair],
            [
                ("18:30", None),
                ("18:30", "21:30"),
                ("19:30", None),
                ("22:00", None),
            ],
        )
        self.assertTrue(any("galletas" in event.title_es for event in fair))
        self.assertTrue(any("40 Duros" in event.title_es for event in fair))

    def test_reviewed_poster_filter_never_erases_richer_text_events(self):
        extracted = (
            SourceEvent(
                "FERIA DEL COMERCIO",
                date(2026, 8, 13), date(2026, 8, 16),
                None, None, "Avda. Els Pins", "event", ("mupi",),
            ),
            SourceEvent(
                "Taller de galletas a cargo de Magia en azúcar",
                date(2026, 8, 16), date(2026, 8, 16),
                "18:30", None, "Avenida de los Pinos", "event",
                ("todo_cultura",),
            ),
            SourceEvent(
                "Bingo solidario a beneficio de Virgen del Rosario",
                date(2026, 8, 16), date(2026, 8, 16),
                "18:30", "21:30", "Avenida de los Pinos", "event",
                ("todo_cultura",),
            ),
            SourceEvent(
                "Clase de cerámica a cargo de Atmósfera",
                date(2026, 8, 16), date(2026, 8, 16),
                "19:30", None, "Avenida de los Pinos", "event",
                ("todo_cultura",),
            ),
            SourceEvent(
                "Actuación musical del grupo 40 Duros",
                date(2026, 8, 16), date(2026, 8, 16),
                "22:00", None, "Avenida de los Pinos", "event",
                ("todo_cultura",),
            ),
        )

        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
            ),
            extracted,
        )
        active = [
            event for event in corrected
            if event.start_date <= date(2026, 8, 16) <= event.end_date
            and "todo_cultura" in event.sources
        ]

        self.assertEqual(len(active), 4)
        self.assertEqual(
            [(event.start_time, event.end_time) for event in active],
            [
                ("18:30", None),
                ("18:30", "21:30"),
                ("19:30", None),
                ("22:00", None),
            ],
        )
        self.assertTrue(all(
            event.place == "Avenida de los Pinos" for event in active
        ))
        self.assertFalse(any(
            "bingo solidario y concierto" in event.title_es.casefold()
            for event in active
        ))
        self.assertFalse(any(
            event.title_es == "FERIA DEL COMERCIO" for event in corrected
        ))

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

    def test_normalizes_recurring_evening_event_details(self):
        events = (
            SourceEvent(
                "Actividad ‘Labores a la fresca’",
                date(2026, 8, 13), date(2026, 8, 13), "18:00", "20:00",
                "Casa de Cultura", "event",
            ),
            SourceEvent(
                "BALL D’ESTIU",
                date(2026, 8, 13), date(2026, 8, 13), "21:30", None,
                "Auditorio Orquesta GÚMAR. Parque Reina Sofía", "event",
            ),
        )

        scheduled = _apply_reviewed_daily_schedules(
            events, date(2026, 8, 13)
        )

        self.assertEqual(
            scheduled[0].title_es,
            "Labores a la fresca: ‘Yo te enseño, tú me enseñas’",
        )
        self.assertEqual(scheduled[0].place, "Casa de Cultura")
        self.assertEqual(scheduled[0].ticket_price_cents, 0)
        self.assertEqual(
            scheduled[1].place,
            "Parque Reina Sofía (Auditorio Orquesta GÚMAR)",
        )
        self.assertEqual(scheduled[1].end_time, "23:30")
        self.assertEqual(scheduled[1].ticket_price_cents, 0)

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

    def test_normalizes_reviewed_night_route_details(self):
        events = (
            SourceEvent(
                "Rutas nocturnas: senderismo y dinámica grupal",
                date(2026, 8, 14), date(2026, 8, 14),
                "22:15", "00:15", None, "event",
            ),
        )

        scheduled = _apply_reviewed_daily_schedules(
            events, date(2026, 8, 14)
        )

        self.assertEqual(
            scheduled[0].place, "Место старта сообщит инструктор"
        )
        self.assertEqual(scheduled[0].ticket_price_cents, 0)
        self.assertEqual(
            scheduled[0].participation_note,
            "с собой: спортивная обувь, вода и фонарик",
        )
        self.assertEqual(
            scheduled[0].registration_contact, "633 14 57 75"
        )
        self.assertTrue(scheduled[0].capacity_limited)

    def test_night_route_details_do_not_leak_to_another_event(self):
        event = SourceEvent(
            "Taller de música electrónica",
            date(2026, 8, 7), date(2026, 8, 7),
            "19:00", "21:00", "Centro Social Juvenil", "event",
        )

        scheduled = _apply_reviewed_daily_schedules(
            (event,), date(2026, 8, 7)
        )

        self.assertIsNone(scheduled[0].registration_contact)
        self.assertIsNone(scheduled[0].participation_note)
        self.assertFalse(scheduled[0].capacity_limited)

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

    def test_transition_keeps_materialized_reviewed_admission_details(self):
        prior = SourceEvent(
            title_es="TRIVOX",
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 14),
            start_time="22:30",
            end_time=None,
            place="Parque Reina Sofía",
            category="event",
            sources=("mupi_reviewed",),
            ticket_price_cents=2000,
            ticket_url="https://www.giglon.com/event/trivox",
            admission_evidence="Precio: 20 euros. Venta en Giglon.",
        )

        merged = _merge_transition_events(
            (), (prior,), date(2026, 8, 10)
        )

        self.assertEqual(merged[0].ticket_price_cents, 2000)
        self.assertEqual(
            merged[0].ticket_url,
            "https://www.giglon.com/event/trivox",
        )
        self.assertIn("20 euros", merged[0].admission_evidence)

    async def test_legacy_route_difficulty_is_preserved_without_snapshot_migration(self):
        day = date(2026, 9, 19)
        legacy_note = (
            "маршрут низкой–средней сложности; "
            "возьмите воду и удобную обувь"
        )
        route = SourceEvent(
            "Free tour guiada", day, day, "08:30", None, None, "event",
            ("todo_cultura",), participation_note=legacy_note,
        )
        full = SourceEvent(
            "Ruta con detalles completos", day, day, "09:30", None, None,
            "event", ("todo_cultura",), participation_note=legacy_note,
            details=("факт 1", "факт 2", "факт 3"),
        )
        with (
            patch(
                "telegrambot.municipal_agenda._cached_current_events",
                new=AsyncMock(return_value=(route, full)),
            ),
            patch(
                "telegrambot.municipal_agenda.translate_event_titles",
                new=AsyncMock(return_value=["Бесплатная экскурсия", "Маршрут"]),
            ),
        ):
            events = await fetch_today_municipal_events(
                datetime(2026, 9, 19, 7, 0, tzinfo=TZ),
                "key",
                Path("unused.json"),
            )

        self.assertEqual(
            events[0].details,
            ("Сложность маршрута: низкая–средняя",),
        )
        self.assertEqual(
            events[0].participation_note,
            "возьмите воду и удобную обувь",
        )
        self.assertEqual(events[1].details, ("факт 1", "факт 2", "факт 3"))
        self.assertEqual(events[1].participation_note, legacy_note)

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

    async def test_facebook_event_survives_unchanged_missing_post_and_failure(self):
        official = SourceEvent(
            "Programa municipal", date(2026, 8, 5), date(2026, 8, 5),
            "18:00", None, "Casa de Cultura", "event", ("mupi",),
        )
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        post = FacebookPost(
            source_id="https://www.facebook.com/GuardamarAyuntamiento/posts/pfbid-test",
            permalink="https://www.facebook.com/GuardamarAyuntamiento/posts/pfbid-test",
            published_at=datetime(2026, 8, 1, tzinfo=TZ),
            text=(
                "5 de agosto 20:00 Concierto de verano. "
                "Parque Reina Sofía. Entrada libre."
            ),
            image_urls=("https://cdn.example.test/poster.jpg",),
        )
        extracted = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto de verano",
                "start_date": "2026-08-05",
                "end_date": "2026-08-05",
                "start_time": "20:00",
                "end_time": None,
                "place": "Parque Reina Sofía",
                "evidence_es": (
                    "5 de agosto 20:00 Concierto de verano. "
                    "Parque Reina Sofía."
                ),
                "category": "event",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                poster_url, "poster-hash", datetime(2026, 8, 1, tzinfo=TZ),
                (official,), {"mupi": {"url": poster_url, "sha256": "poster-hash"}},
            ))
            fetch = AsyncMock(side_effect=(
                (post,), (), (post,), (), (), (),
                FacebookError("offline", code="NETWORK"), FacebookError("offline", code="NETWORK"),
            ))
            extract_text = AsyncMock(return_value=extracted)
            with (
                patch("telegrambot.municipal_agenda._read_url", return_value=(page, "text/html")),
                patch("telegrambot.municipal_agenda.fetch_facebook_posts", new=fetch),
                patch("telegrambot.municipal_agenda.extract_agenda_text_events", new=extract_text),
            ):
                first = await _current_events("key", datetime(2026, 8, 5, tzinfo=TZ), path)
                second = await _current_events("key", datetime(2026, 8, 5, 6, tzinfo=TZ), path)
                third = await _current_events("key", datetime(2026, 8, 5, 7, tzinfo=TZ), path)
                fourth = await _current_events("key", datetime(2026, 8, 5, 8, tzinfo=TZ), path)

        self.assertEqual(extract_text.await_count, 1)
        self.assertIn("Concierto de verano", [event.title_es for event in first])
        self.assertEqual([event.title_es for event in first], [event.title_es for event in second])
        self.assertEqual([event.title_es for event in second], [event.title_es for event in third])
        self.assertEqual([event.title_es for event in third], [event.title_es for event in fourth])

    def test_facebook_fingerprint_ignores_ephemeral_image_query(self):
        first = FacebookPost(
            "id", "https://www.facebook.com/page/posts/id", None, "Texto",
            ("https://cdn.example.test/poster.jpg?token=old",),
        )
        second = FacebookPost(
            "id", "https://www.facebook.com/page/posts/id", None, "Texto",
            ("https://cdn.example.test/poster.jpg?token=new",),
        )
        self.assertEqual(_facebook_fingerprint(first), _facebook_fingerprint(second))

    def test_cultura_post_enriches_only_matching_existing_event(self):
        event = SourceEvent("IMBORRABLE", date(2026, 9, 1), date(2026, 10, 16), None, None, "Casa de Cultura", "exhibition")
        other = SourceEvent("Otro evento", date(2026, 9, 1), date(2026, 9, 1), None, None, None, "event")
        post = FacebookPost("id", "https://www.facebook.com/culturaguardamar/posts/id", None,
            "IMBORRABLE. Una muestra que reúne su particular mirada a través del color, las formas y diferentes composiciones que no dejan indiferente.")
        enriched = _enrich_cultura_teasers((event, other), (post,), ())
        self.assertEqual(enriched[0].teaser_es, "Una muestra que reúne su particular mirada a través del color, las formas y diferentes composiciones que no dejan indiferente.")
        self.assertIsNone(enriched[1].teaser_es)

    async def test_old_html_extractor_version_forces_one_refresh(self):
        prior = SourceEvent(
            "Concierto Alpha", date(2026, 8, 30), date(2026, 8, 30),
            "20:00", None, "Casa de Cultura", "event",
            ("turismo_html",),
        )
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        programme = (
            "AGENDA CULTURAL AGOSTO 2026 30 de agosto 20 h. "
            "Concierto Alpha. Casa de Cultura. " + "Programa oficial. " * 8
        )
        page = (
            f'<h2>{programme}</h2><a href="{poster_url}">poster</a>'
        ).encode()
        page_text, _ = extract_official_agenda_text(page)
        extraction_result = {
            "month": "2026-08",
            "events": [{
                "title_es": "Concierto Alpha",
                "start_date": "2026-08-30",
                "end_date": "2026-08-30",
                "start_time": "20:00",
                "end_time": None,
                "place": "Casa de Cultura",
                "evidence_es": (
                    "30 de agosto 20 h. Concierto Alpha. Casa de Cultura."
                ),
                "category": "event",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                poster_url, "poster-hash",
                datetime(2026, 8, 13, tzinfo=TZ), (prior,), {
                    "turismo_html": {
                        "sha256": hashlib.sha256(
                            page_text.encode("utf-8")
                        ).hexdigest(),
                        "extractor_version": 1,
                    },
                    "mupi": {"url": poster_url, "sha256": "poster-hash"},
                },
            ))
            extract_text = AsyncMock(return_value=extraction_result)
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(page, "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=extract_text,
                ),
            ):
                await _current_events(
                    "key", datetime(2026, 8, 13, tzinfo=TZ), path
                )
            stored = json.loads(path.read_text(encoding="utf-8"))

        extract_text.assert_awaited_once()
        self.assertEqual(
            stored["sources"]["turismo_html"]["extractor_version"], 4
        )

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
            text=(
                "Miércoles 5 de agosto\n19 h.: Taller juvenil. "
                "Centro Social Juvenil."
            ),
            sha256="todo-hash",
            source_url="https://todoculturavegabaja.es/eventos/guardamar/",
            modified="2026-08-04T22:40:40",
        )
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        page = f'<a href="{poster_url}">poster</a>'.encode()
        first_window = TodoCulturaWindow(
            programs=(TodoCulturaProgram(
                **{**todo.__dict__, "dates": (date(2026, 8, 5),)}
            ),),
            source_state={
                "parser_version": 4,
                "cursor_modified_gmt": "2026-08-04T22:40:40",
                "candidates": [],
            },
        )
        fetch_todo = AsyncMock(side_effect=(
            first_window,
            TodoCulturaWindow((), first_window.source_state),
        ))
        extract_text = AsyncMock(return_value={
            "month": "2026-08",
            "events": [{
                "title_es": "Taller juvenil",
                "start_date": "2026-08-05",
                "end_date": "2026-08-05",
                "start_time": "19:00",
                "end_time": None,
                "place": "Centro Social Juvenil",
                "evidence_es": (
                    "Miércoles 5 de agosto 19 h.: Taller juvenil. "
                    "Centro Social Juvenil."
                ),
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
                    "telegrambot.municipal_agenda.fetch_program_window",
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
        self.assertEqual(fetch_todo.await_args_list[0].args[0], date(2026, 8, 5))
        extract_text.assert_awaited_once_with("key", todo.text)
        self.assertEqual(
            [event.title_es for event in current],
            ["Concierto oficial", "Taller juvenil"],
        )
        self.assertEqual(
            stored["sources"]["todo_cultura"]["parser_version"], 4
        )

    async def test_incomplete_todo_still_enriches_verified_cinema_synopsis(self):
        programme_text = (
            "AGENDA CULTURAL SEPTIEMBRE 2026 CINE "
            "Viernes, 18 de septiembre a las 19:00 h. Escuela de Música. "
            "TODOS NOS LLAMAMOS ALI (Rainer Werner Fassbinder, 1973. Alemania) "
            "+ 13 / Drama / 93 min Entrada libre con invitación "
            "CONCIERTO CORAL"
        )
        page = f"<article>{programme_text}</article>".encode()
        official_text, month = extract_official_agenda_text(page)
        old_todo_state = {
            "parser_version": 12,
            "cursor_modified_gmt": "2026-09-17T08:00:00",
            "covered_dates": ["2026-09-18"],
            "candidates": [],
        }
        old = SourceEvent(
            "Cine: TODOS NOS LLAMAMOS ALI",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Escola de Música",
            "event",
            ("turismo_html", "turismo_cinema"),
            ticket_price_cents=0,
            ticket_url="https://www.agendaguardamar.com/index.html",
            duration_minutes=93,
            audience_label="13+",
            details=("Drama",),
        )
        ali_row = (
            "2026-09-18\n"
            "– 19 h.: Sesión de cine en la Escola de Música con la película "
            "alemana titulada ‘Todos nos llamamos Ali’.\n"
            "La sinopsis de la cinta es la siguiente: "
            "En un café al que acuden trabajadores inmigrantes, Emmi conoce "
            "a Salem, un marroquí treintañero."
        )
        unmatched_row = (
            "2026-09-18\n"
            "– 20 h.: Actividad experimental sin coincidencia."
        )
        program = TodoCulturaProgram(
            text=ali_row + "\n" + unmatched_row,
            sha256="todo-hash",
            source_url="https://todoculturavegabaja.es/eventos/agenda/",
            modified="2026-09-18T08:00:00",
            dates=(date(2026, 9, 18),),
            event_rows=(
                (date(2026, 9, 18), "19:00", ali_row),
                (date(2026, 9, 18), "20:00", unmatched_row),
            ),
        )
        window = TodoCulturaWindow(
            programs=(program,),
            source_state={
                **old_todo_state,
                "parser_version": 13,
                "cursor_modified_gmt": "2026-09-18T08:00:00",
            },
        )
        empty = {"month": "2026-09", "events": []}
        now = datetime(2026, 9, 18, 5, 10, tzinfo=TZ)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(path, _snapshot_data(
                "", "", now, (old,), {
                    "turismo_html": {
                        "sha256": hashlib.sha256(
                            official_text.encode()
                        ).hexdigest(),
                        "month": month,
                        "extractor_version": 4,
                    },
                    "todo_cultura": old_todo_state,
                },
            ))
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(page, "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_program_window",
                    new=AsyncMock(return_value=window),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=AsyncMock(side_effect=(empty, empty)),
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
                current = await refresh_municipal_catalog("key", now, path)
            stored = json.loads(path.read_text(encoding="utf-8"))

        cinema = next(
            event for event in current if "turismo_cinema" in event.sources
        )
        self.assertIn("todo_cultura_synopsis", cinema.sources)
        self.assertIn("Emmi conoce a Salem", cinema.teaser_es)
        self.assertIsNone(cinema.ticket_url)
        self.assertEqual(
            stored["sources"]["todo_cultura"]["cursor_modified_gmt"],
            old_todo_state["cursor_modified_gmt"],
        )

    def test_generic_agenda_ticket_url_is_removed_from_stale_event(self):
        generic = SourceEvent(
            "Evento",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Casa de Cultura",
            "event",
            ("turismo_html",),
            ticket_url="https://www.agendaguardamar.com/index.html",
        )
        specific = SourceEvent(
            "Evento",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Casa de Cultura",
            "event",
            ("turismo_html",),
            ticket_url=(
                "https://www.agendaguardamar.com/espectaculo/48/alpha.html"
            ),
        )

        self.assertIsNone(
            _sanitize_generic_agenda_ticket_url(generic).ticket_url
        )
        self.assertEqual(
            _sanitize_generic_agenda_ticket_url(specific).ticket_url,
            specific.ticket_url,
        )

    async def test_todo_llm_failure_does_not_advance_incremental_state(self):
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
        poster_url = (
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/08/MUPI-AGOSTO-2026.jpg"
        )
        old_todo_state = {
            "parser_version": 4,
            "cursor_modified_gmt": "2026-08-04T08:00:00",
            "candidates": [],
        }
        advanced_state = {
            **old_todo_state,
            "cursor_modified_gmt": "2026-08-05T08:00:00",
        }
        first_program = TodoCulturaProgram(
            text="Miércoles 5 de agosto\n19:00: Taller juvenil",
            sha256="todo-hash-1",
            source_url=(
                "https://todoculturavegabaja.es/eventos/guardamar-1/"
            ),
            modified="2026-08-05T08:00:00",
            dates=(date(2026, 8, 5),),
        )
        second_program = TodoCulturaProgram(
            text="Miércoles 5 de agosto\n20:00: Segundo taller",
            sha256="todo-hash-2",
            source_url=(
                "https://todoculturavegabaja.es/eventos/guardamar-2/"
            ),
            modified="2026-08-05T08:00:00",
            dates=(date(2026, 8, 5),),
        )
        window = TodoCulturaWindow(
            programs=(first_program, second_program),
            source_state=advanced_state,
        )
        first_extraction = {
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
        }
        page = f'<a href="{poster_url}">poster</a>'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    poster_url,
                    "poster-hash",
                    datetime(2026, 8, 4, tzinfo=TZ),
                    (official,),
                    {
                        "mupi": {
                            "url": poster_url,
                            "sha256": "poster-hash",
                        },
                        "todo_cultura": old_todo_state,
                    },
                ),
            )
            with (
                patch(
                    "telegrambot.municipal_agenda._read_url",
                    return_value=(page, "text/html"),
                ),
                patch(
                    "telegrambot.municipal_agenda.fetch_program_window",
                    new=AsyncMock(return_value=window),
                ),
                patch(
                    "telegrambot.municipal_agenda.extract_agenda_text_events",
                    new=AsyncMock(side_effect=(
                        first_extraction,
                        GeminiError("temporarily down"),
                    )),
                ),
            ):
                current = await _current_events(
                    "key", datetime(2026, 8, 5, 5, 10, tzinfo=TZ), path
                )
            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual([event.title_es for event in current], [
            "Concierto oficial"
        ])
        self.assertEqual(
            stored["sources"]["todo_cultura"]["cursor_modified_gmt"],
            old_todo_state["cursor_modified_gmt"],
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
            self.assertEqual(json.loads(path.read_text())["version"], 4)

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
