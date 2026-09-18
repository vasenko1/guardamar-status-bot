import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.digest import build_event_section
from telegrambot.event_translations import _key
from telegrambot.municipal_agenda import (
    SourceEvent,
    _bounded_synopsis_excerpt,
    _enrich_todo_cinema_synopses,
    _snapshot_data,
    _todo_cinema_synopsis_candidates,
    _write_snapshot,
    extract_official_cinema,
    fetch_today_municipal_events,
)
from telegrambot.todo_cultura import TodoCulturaProgram


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 18, 7, 30, tzinfo=TZ)

PROGRAMME = (
    "AGENDA CULTURAL SEPTIEMBRE 2026 CINE "
    "Lunes, 14 de septiembre a las 18:00 h. Biblioteca Pública Municipal. "
    "RESPECT (Liesl Tommy, 2021. USA) + 12/ Drama / 144 min "
    "Entrada libre hasta completar aforo "
    "Viernes, 18 de septiembre a las 19:00 h. Escuela de Música. "
    "TODOS NOS LLAMAMOS ALI (Rainer Werner Fassbinder, 1973. Alemania) "
    "+ 13 / Drama / 93 min Entrada libre con invitación en www.agendaguardamar.com "
    "Lunes, 21 de septiembre a las 18:00 h. Biblioteca Pública Municipal. "
    "EL CLUB DE LOS MILAGROS (Thaddeus O’Sullivan, 2023. Reino Unido-Irlanda) "
    "+ 7 / Drama-Comedia / 85 min Entrada libre hasta completar aforo. "
    "Viernes, 25 de septiembre a las 19:00 h. Escuela de Música. "
    "ROMERÍA (Carla Simón, 2025. España) + 16 / Drama / 111 min "
    "Entrada libre con invitación en www.agendaguardamar.com "
    "Lunes, 28 de septiembre a las 18:00 h. Biblioteca Pública Municipal. "
    "FIN DE FIESTA (Elena Manrique, 2024. España-Bélgica) "
    "+ 16 / Tragicomedia / 97 min Entrada libre hasta completar aforo "
    "CONCIERTO CORAL"
)

ALI_SYNOPSIS = (
    "En un café al que acuden los trabajadores inmigrantes, Emmi Kurowski, "
    "una viuda de unos sesenta años, conoce a Salem, un marroquí treintañero. "
    "Inducido por la dueña del bar, Salem invita a Emmi a bailar, hablan, "
    "la acompaña a casa y, al día siguiente, se queda a vivir con ella. "
    "Esta relación provoca un gran escándalo."
)
RESPECT_SYNOPSIS = (
    "Biopic de la legendaria cantante Aretha Franklin que sigue su carrera "
    "desde la infancia, cuando cantaba góspel en el coro de la iglesia de su "
    "padre, hasta que consiguió su enorme fama internacional."
)
CLUB_SYNOPSIS = (
    "Ballyfermot, Irlanda, 1960. Una pequeña comunidad de las afueras de "
    "Dublín sigue su propio ritmo, arraigada en las tradiciones de lealtad, "
    "fe y unión. Las mujeres de Ballyfermot sólo tienen un sueño tentador "
    "para saborear la libertad."
)


def programme(*rows):
    return TodoCulturaProgram(
        text="",
        sha256="x",
        source_url="https://todoculturavegabaja.es/eventos/agenda/",
        modified="2026-09-18T00:00:00",
        dates=tuple(dict.fromkeys(row[0] for row in rows)),
        event_rows=tuple(rows),
    )


class OfficialCinemaSectionTests(unittest.TestCase):
    def test_all_current_september_films_are_structured(self):
        events = extract_official_cinema(PROGRAMME, "2026-09")
        self.assertEqual(len(events), 5)
        by_day = {event.start_date.day: event for event in events}

        self.assertEqual(by_day[14].duration_minutes, 144)
        self.assertEqual(by_day[14].audience_label, "12+")
        self.assertEqual(
            by_day[14].details,
            ("Drama", "США", "реж. Liesl Tommy"),
        )
        self.assertTrue(by_day[14].capacity_limited)
        self.assertEqual(by_day[14].access_note, "до заполнения зала")
        self.assertTrue(by_day[14].title_es.startswith("Cine de los Lunes:"))

        ali = by_day[18]
        self.assertEqual(ali.place, "Escola de Música")
        self.assertEqual(ali.duration_minutes, 93)
        self.assertEqual(ali.audience_label, "13+")
        self.assertEqual(
            ali.details,
            ("Drama", "Германия", "реж. Rainer Werner Fassbinder"),
        )
        self.assertEqual(ali.ticket_price_cents, 0)
        self.assertFalse(ali.capacity_limited)
        self.assertIsNone(ali.access_note)
        self.assertEqual(ali.title_es, "Cine: TODOS NOS LLAMAMOS ALI")

        romeria = by_day[25]
        self.assertEqual(romeria.duration_minutes, 111)
        self.assertEqual(romeria.audience_label, "16+")
        self.assertEqual(
            romeria.details,
            ("Drama", "Испания", "реж. Carla Simón"),
        )
        self.assertFalse(romeria.capacity_limited)

        self.assertEqual(
            by_day[21].details,
            (
                "Drama-Comedia",
                "Великобритания–Ирландия",
                "реж. Thaddeus O’Sullivan",
            ),
        )
        self.assertEqual(
            by_day[28].details,
            ("Tragicomedia", "Испания–Бельгия", "реж. Elena Manrique"),
        )

    def test_declared_weekday_must_match_calendar(self):
        broken = PROGRAMME.replace(
            "Viernes, 18 de septiembre",
            "Jueves, 18 de septiembre",
        )
        events = extract_official_cinema(broken, "2026-09")
        self.assertNotIn(18, {event.start_date.day for event in events})


class SynopsisExcerptTests(unittest.TestCase):
    def test_examples_keep_source_only_meaningful_excerpt(self):
        ali = _bounded_synopsis_excerpt(ALI_SYNOPSIS)
        self.assertTrue(ali.endswith("treintañero."))
        self.assertNotIn("Inducido", ali)
        self.assertLessEqual(len(ali), 220)

        self.assertEqual(
            _bounded_synopsis_excerpt(RESPECT_SYNOPSIS),
            RESPECT_SYNOPSIS,
        )

        club = _bounded_synopsis_excerpt(CLUB_SYNOPSIS)
        self.assertTrue(club.startswith("Ballyfermot, Irlanda, 1960."))
        self.assertIn("fe y unión.", club)
        self.assertNotIn("Las mujeres", club)
        self.assertLessEqual(len(club), 220)

    def test_long_single_sentence_is_word_bounded_with_ellipsis(self):
        source = " ".join(["palabra"] * 80) + "."
        excerpt = _bounded_synopsis_excerpt(source)
        self.assertLessEqual(len(excerpt), 211)
        self.assertTrue(excerpt.endswith("…"))
        self.assertFalse(excerpt.endswith(" …"))

    def test_too_short_value_is_omitted(self):
        self.assertIsNone(_bounded_synopsis_excerpt("Muy breve."))


class TodoCulturaSynopsisSafetyTests(unittest.TestCase):
    def test_single_explicit_synopsis_marker_becomes_candidate(self):
        row = (
            "2026-09-18\n"
            "– 19 h.: Sesión de cine en la Escola de Música con la película "
            "alemana titulada ‘Todos nos llamamos Ali’.\n"
            "La sinopsis de la cinta es la siguiente: " + ALI_SYNOPSIS + "\n"
            "La entrada es gratuita con invitación."
        )
        candidates = _todo_cinema_synopsis_candidates((
            programme((date(2026, 9, 18), "19:00", row)),
        ))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], date(2026, 9, 18))
        self.assertEqual(candidates[0][1], "19:00")
        self.assertTrue(candidates[0][3].endswith("treintañero."))

    def test_multiple_synopsis_markers_fail_closed(self):
        row = (
            "2026-07-29\n"
            "– 22 h.: Sesión de cine con la película ‘Gremlins’.\n"
            "La sinopsis de la cinta es la siguiente: Un joven recibe un mogwai.\n"
            "La sinopsis de la cinta ganadora de cuatro Oscars es la siguiente: "
            "Un pequeño ser de otro planeta se queda abandonado en la Tierra."
        )
        candidates = _todo_cinema_synopsis_candidates((
            programme((date(2026, 7, 29), "22:00", row)),
        ))
        self.assertEqual(candidates, ())

    def test_multiple_synopsis_markers_in_one_line_fail_closed(self):
        row = (
            "2026-07-29\n"
            "– 22 h.: Sesión de cine con la película ‘Gremlins’.\n"
            "La sinopsis de la cinta es la siguiente: Un joven recibe un mogwai. "
            "La sinopsis de otra cinta es la siguiente: "
            "Un pequeño ser de otro planeta se queda abandonado en la Tierra."
        )
        candidates = _todo_cinema_synopsis_candidates((
            programme((date(2026, 7, 29), "22:00", row)),
        ))
        self.assertEqual(candidates, ())

    def test_synopsis_is_attached_only_to_verified_cinema_occurrence(self):
        cinema = SourceEvent(
            "Cine: TODOS NOS LLAMAMOS ALI",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Escuela de Música",
            "event",
            ("turismo_html", "turismo_cinema"),
        )
        ordinary = SourceEvent(
            "Todos nos llamamos Ali",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Casa de Cultura",
            "event",
            ("mupi",),
        )
        row = (
            "2026-09-18\n"
            "– 19 h.: Sesión de cine en la Escola de Música con la película "
            "alemana titulada ‘Todos nos llamamos Ali’.\n"
            "La sinopsis de la cinta es la siguiente: " + ALI_SYNOPSIS
        )
        program = programme((date(2026, 9, 18), "19:00", row))
        enriched = _enrich_todo_cinema_synopses(
            (cinema, ordinary),
            (program,),
        )
        self.assertIsNotNone(enriched[0].teaser_es)
        self.assertIn("todo_cultura_synopsis", enriched[0].sources)
        self.assertIsNone(enriched[1].teaser_es)

    def test_conflicting_synopses_fail_closed(self):
        cinema = SourceEvent(
            "Cine: TODOS NOS LLAMAMOS ALI",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Escuela de Música",
            "event",
            ("turismo_html", "turismo_cinema"),
        )
        row_a = (
            "2026-09-18\n"
            "– 19 h.: Sesión de cine con la película ‘Todos nos llamamos Ali’.\n"
            "La sinopsis de la cinta es la siguiente: " + ALI_SYNOPSIS
        )
        row_b = (
            "2026-09-18\n"
            "– 19 h.: Sesión de cine con la película ‘Todos nos llamamos Ali’.\n"
            "La sinopsis de la cinta es la siguiente: "
            "Una descripción distinta y suficientemente larga para ser válida."
        )
        enriched = _enrich_todo_cinema_synopses(
            (cinema,),
            (
                programme((date(2026, 9, 18), "19:00", row_a)),
                programme((date(2026, 9, 18), "19:00", row_b)),
            ),
        )
        self.assertIsNone(enriched[0].teaser_es)


class CinemaRenderPipelineTests(unittest.TestCase):
    def test_verified_metadata_and_translated_synopsis_render_together(self):
        source = SourceEvent(
            "Cine: TODOS NOS LLAMAMOS ALI",
            date(2026, 9, 18),
            date(2026, 9, 18),
            "19:00",
            None,
            "Escola de Música",
            "event",
            ("turismo_html", "turismo_cinema", "todo_cultura_synopsis"),
            ticket_price_cents=0,
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/2/"
                "todos-nos-llamamos-ali.html"
            ),
            teaser_es=_bounded_synopsis_excerpt(ALI_SYNOPSIS),
            duration_minutes=93,
            audience_label="13+",
            details=("Drama", "Германия", "реж. Rainer Werner Fassbinder"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "municipal.json"
            cache = root / "translations.json"
            _write_snapshot(state, _snapshot_data("", "", NOW, (source,)))
            cache.write_text(json.dumps({
                "version": 1,
                "entries": {
                    _key("municipal_agenda", source.title_es): {
                        "translation": "Кино: Все мы зовемся Али",
                    },
                    _key("municipal_cinema_teaser", source.teaser_es): {
                        "translation": (
                            "В кафе для рабочих-иммигрантов вдова Эмми "
                            "знакомится с молодым марокканцем Салемом."
                        ),
                    },
                },
            }, ensure_ascii=False), encoding="utf-8")
            events = __import__("asyncio").run(fetch_today_municipal_events(
                NOW,
                "",
                state,
                translation_cache_path=cache,
            ))

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.title, "🎬 Все мы зовемся Али")
        rendered = "\n".join(build_event_section(events, "События"))
        self.assertIn(
            "Драма • Германия • реж. Rainer Werner Fassbinder • 93 мин • 13+",
            rendered,
        )
        self.assertIn("вдова Эмми", rendered)
        self.assertIn("📍 ", rendered)
        self.assertIn("Escola de Música", rendered)
        self.assertIn(
            '<a href="https://www.agendaguardamar.com/entradas/2/'
            'todos-nos-llamamos-ali.html">Бесплатно · Получить билет</a>',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
