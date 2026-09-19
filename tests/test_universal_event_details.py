"""Official cinema facts and the shared standalone-event presentation."""

import asyncio
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.digest import build_event_section
from telegrambot.event_translations import _key
from telegrambot.library_agenda import _LibraryRecord, _write_snapshot as write_library
from telegrambot.library_agenda import fetch_today_library_events
from telegrambot.models import Event
from telegrambot.morning import _merge_events
from telegrambot.municipal_agenda import (
    SourceEvent, _load_snapshot, _snapshot_data, _write_snapshot,
    extract_official_agenda_text, extract_official_cinema,
    fetch_today_municipal_events, merge_text_and_poster_events,
    refresh_municipal_catalog,
)
from telegrambot.todo_cultura import TodoCulturaError

TZ = ZoneInfo("Europe/Madrid")
PROGRAMME = (
    "AGENDA CULTURAL SEPTIEMBRE 2026 CINE "
    "Lunes, 14 de septiembre a las 18:00 h. Biblioteca Pública Municipal. "
    "RESPECT (Liesl Tommy, 2021. USA) + 12/ Drama / 144 min "
    "Entrada libre hasta completar aforo "
    "Lunes, 21 de septiembre a las 18:00 h. Biblioteca Pública Municipal. "
    "EL CLUB DE LOS MILAGROS (Thaddeus O’Sullivan, 2023. Reino Unido-Irlanda) "
    "+ 7 / Drama-Comedia / 85 min Entrada libre hasta completar aforo. "
    "Dilluns, 28 de setembre a les 18.00 h. Biblioteca Pública Municipal. "
    "FIN DE FIESTA (Elena Manrique, 2024. España-Bélgica) "
    "+ 16 / Tragicomedia / 97 min Entrada libre hasta completar aforo "
    "CONCIERTO CORAL Sábado, 19 de septiembre a las 20:00 h."
)
FUTURE = (
    "AGENDA CULTURAL OCTUBRE 2026 CINE "
    "Lunes, 5 de octubre a las 18:00 h. Biblioteca Pública Municipal. "
    "PELÍCULA NUEVA (Directora Desconocida, 2026. España) "
    "+13 / Comedia / 103 min Entrada libre hasta completar aforo "
    "CONCIERTO CORAL"
)


def event_lines(event):
    return "\n".join(build_event_section((event,), "Eventos"))


class OfficialCinemaFactsTests(unittest.TestCase):
    def test_current_three_films_are_deterministic(self):
        events = extract_official_cinema(PROGRAMME, "2026-09")
        self.assertEqual(len(events), 3)
        for event, title, duration, audience, genre in zip(
            events,
            ("RESPECT", "EL CLUB DE LOS MILAGROS", "FIN DE FIESTA"),
            (144, 85, 97), ("12+", "7+", "16+"),
            ("Drama", "Drama-Comedia", "Tragicomedia"),
        ):
            self.assertIn(title, event.title_es)
            self.assertEqual(event.duration_minutes, duration)
            self.assertEqual(event.audience_label, audience)
            self.assertEqual(event.details, (genre,))
            self.assertEqual(event.ticket_price_cents, 0)
            self.assertTrue(event.capacity_limited)
            self.assertEqual(event.access_note, "до заполнения зала")
            self.assertEqual(event.start_time, "18:00")
        self.assertEqual(events[2].start_date, date(2026, 9, 28))

    def test_unknown_future_film_and_missing_facts(self):
        event, = extract_official_cinema(FUTURE, "2026-10")
        self.assertIn("PELÍCULA NUEVA", event.title_es)
        self.assertEqual(event.duration_minutes, 103)
        self.assertEqual(event.audience_label, "13+")
        self.assertEqual(
            event.details,
            ("Comedia",),
        )
        self.assertEqual(event.ticket_price_cents, 0)
        self.assertTrue(event.capacity_limited)
        self.assertEqual(event.access_note, "до заполнения зала")
        generic = SourceEvent(
            "Cine de los Lunes", event.start_date, event.end_date,
            event.start_time, None, "Biblioteca Municipal", "event", ("mupi",),
        )
        merged = merge_text_and_poster_events((event,), (generic,))
        self.assertEqual(len(merged), 1)
        self.assertIn("PELÍCULA NUEVA", merged[0].title_es)
        no_duration, = extract_official_cinema(
            FUTURE.replace("103 min", "sin duración"), "2026-10"
        )
        self.assertIsNone(no_duration.duration_minutes)
        self.assertEqual(no_duration.details, ())
        no_genre, = extract_official_cinema(
            FUTURE.replace("Comedia / ", ""), "2026-10"
        )
        self.assertEqual(no_genre.duration_minutes, 103)
        self.assertEqual(no_genre.details, ())
        paid, = extract_official_cinema(
            FUTURE.replace(
                "Entrada libre hasta completar aforo", "Precio: 5 €"
            ), "2026-10"
        )
        self.assertEqual(paid.ticket_price_cents, 500)
        self.assertFalse(paid.capacity_limited)

    def test_municipal_snapshot_and_library_merge_preserve_facts(self):
        source, = extract_official_cinema(PROGRAMME, "2026-09")[:1]
        generic = SourceEvent(
            "Cine de los Lunes", source.start_date, source.end_date,
            "18:00", None, "Biblioteca Municipal", "event", ("mupi",),
        )
        municipal = merge_text_and_poster_events((source,), (generic,))
        self.assertEqual(len(municipal), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            municipal_path = root / "municipal.json"
            library_path = root / "library.json"
            cache_path = root / "translations.json"
            now = datetime(2026, 9, 14, 7, 30, tzinfo=TZ)
            _write_snapshot(municipal_path, _snapshot_data("", "", now, municipal))
            raw_library_title = "El cine de los lunes: Respect: su voz lo cambió todo"
            raw_teaser = "La película muestra su camino desde el góspel."
            library_event = Event(
                raw_library_title, now.replace(hour=18, minute=0),
                now.replace(hour=20, minute=0), "Biblioteca Pública Municipal",
                teaser=raw_teaser,
            )
            write_library(library_path, now, (
                _LibraryRecord(library_event,
                    "https://www.bibliotecaspublicas.es/guardamardelsegura/"
                    "actividades-programas/Agenda-de-actividades.html", True),
            ))
            cache_path.write_text(json.dumps({"version": 1, "entries": {
                _key("municipal_agenda", source.title_es): {
                    "translation": "Непригодный перевод",
                },
                _key("library_agenda", raw_library_title): {
                    "translation": "Кино по понедельникам: Respect: её голос изменил всё",
                },
                _key("library_agenda_teaser", raw_teaser): {
                    "translation": "Фильм рассказывает о её пути от госпела.",
                },
            }}))
            self.assertEqual(_load_snapshot(municipal_path)["_events"][0].duration_minutes, 144)
            municipal_events = asyncio.run(fetch_today_municipal_events(
                now, "", municipal_path, translation_cache_path=cache_path,
            ))
            self.assertEqual(
                municipal_events[0].title,
                "Кино по понедельникам: «Respect»",
            )
            library_events = asyncio.run(fetch_today_library_events(
                now, library_path, cache_path,
            ))
            merged = _merge_events(municipal_events, library_events)

        self.assertEqual(len(merged), 1)
        event = merged[0]
        self.assertEqual(event.title, "Кино по понедельникам: «Respect»")
        self.assertEqual(event.duration_minutes, 144)
        self.assertEqual(event.audience_label, "12+")
        self.assertEqual(event.details, ("Драма",))
        self.assertEqual(event.ticket_price_cents, 0)
        self.assertTrue(event.capacity_limited)
        self.assertIn("госпела", event.teaser)
        rendered = event_lines(event)
        self.assertIn("<b>18:00</b>", rendered)
        self.assertNotIn("20:00", rendered)
        self.assertIn("Драма • 144 мин • 12+", rendered)
        self.assertIn("🎟 Бесплатно · до заполнения зала", rendered)
        self.assertIn("Biblioteca", rendered)

    def test_every_current_film_replaces_only_its_generic_mupi_row(self):
        for source, genre in zip(
            extract_official_cinema(PROGRAMME, "2026-09"),
            ("Драма", "Драма-комедия", "Трагикомедия"),
        ):
            with self.subTest(day=source.start_date):
                generic = SourceEvent(
                    "Cine de los Lunes", source.start_date, source.end_date,
                    "18:00", None, "Biblioteca Municipal", "event", ("mupi",),
                )
                merged = merge_text_and_poster_events((source,), (generic,))
                self.assertEqual(len(merged), 1)
                self.assertIn("turismo_cinema", merged[0].sources)
                self.assertIn("mupi", merged[0].sources)
                self.assertEqual(merged[0].duration_minutes,
                                 source.duration_minutes)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "municipal.json"
                    now = datetime.combine(source.start_date,
                                           datetime.min.time(), TZ)
                    _write_snapshot(path, _snapshot_data("", "", now, merged))
                    normalized = asyncio.run(fetch_today_municipal_events(
                        now, "", path,
                        translation_cache_path=Path(directory) / "translations.json",
                    ))
                self.assertEqual(len(normalized), 1)
                rendered = event_lines(normalized[0])
                self.assertIn(genre, rendered)
                self.assertIn(f"{source.duration_minutes} мин", rendered)
                self.assertIn(source.audience_label, rendered)
                self.assertIn("Бесплатно · до заполнения зала", rendered)

    def test_old_snapshot_without_optional_fields(self):
        event = SourceEvent(
            "Экскурсия", date(2026, 9, 14), date(2026, 9, 14),
            "10:00", None, "Castillo", "event", ("turismo_html",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.json"
            data = _snapshot_data("", "", datetime(2026, 9, 14, tzinfo=TZ), (event,))
            for field in ("duration_minutes", "audience_label", "details"):
                data["events"][0].pop(field)
            path.write_text(json.dumps(data))
            restored, = _load_snapshot(path)["_events"]
        self.assertIsNone(restored.duration_minutes)
        self.assertIsNone(restored.audience_label)
        self.assertEqual(restored.details, ())


class SharedRendererTests(unittest.TestCase):
    def test_optional_fact_combinations_and_plain_event(self):
        when = datetime(2026, 10, 5, 18, tzinfo=TZ)
        for event, expected in (
            (Event("A", when, duration_minutes=103, audience_label="13+"), "103 мин • 13+"),
            (Event("B", when, duration_minutes=103, details=("Драма",)), "Драма • 103 мин"),
            (Event("C", when, duration_minutes=103), "103 мин"),
            (Event("D", when, details=("Драма",)), "Драма"),
        ):
            rendered = event_lines(event)
            self.assertIn("  " + expected, rendered)
            self.assertNotIn("  •", rendered)
        plain = event_lines(Event("Концерт", when, when.replace(hour=20), "Площадь"))
        self.assertIn("18:00–20:00", plain)
        self.assertNotIn("  •", plain)

    def test_distance_and_difficulty_details_are_route_safe(self):
        when = datetime(2026, 9, 19, 10, tzinfo=TZ)

        conflicting = Event(
            "Экскурсия",
            when,
            duration_minutes=120,
            details=(
                "1,5 км",
                "1 км",
                "Сложность маршрута: низкая–средняя",
                "Для всей семьи",
            ),
        )
        rendered_conflicting = event_lines(conflicting)
        self.assertIn("≈ 1,5 км • Для всей семьи • 120 мин", rendered_conflicting)
        self.assertNotIn("≈ 1 км", rendered_conflicting)
        self.assertIn(
            "\n  Сложность маршрута: низкая–средняя",
            rendered_conflicting,
        )
        self.assertNotIn(
            "120 мин • Сложность маршрута",
            rendered_conflicting,
        )

        agreeing = Event(
            "Экскурсия",
            when,
            details=("1,5 км", "1.50 км", "Низкая сложность"),
        )
        rendered_agreeing = event_lines(agreeing)
        self.assertEqual(rendered_agreeing.count("1,5 км"), 1)
        self.assertNotIn("≈ 1,5 км", rendered_agreeing)
        self.assertNotIn("1.50 км", rendered_agreeing)
        self.assertIn("Низкая сложность", rendered_agreeing)

        difficulty_conflict = Event(
            "Экскурсия",
            when,
            details=(
                "Сложность маршрута: низкая",
                "Сложность маршрута: средняя",
                "1 км",
            ),
        )
        rendered_difficulty_conflict = event_lines(difficulty_conflict)
        self.assertIn("1 км", rendered_difficulty_conflict)
        self.assertNotIn("Сложность маршрута:", rendered_difficulty_conflict)

        out_of_scope = Event(
            "Спортивный маршрут",
            when,
            details=("250 км", "Сложность маршрута: экстремальная"),
        )
        rendered_out_of_scope = event_lines(out_of_scope)
        self.assertIn("250 км", rendered_out_of_scope)
        self.assertNotIn("Сложность маршрута:", rendered_out_of_scope)

    def test_universal_excursion_and_grouped_programme(self):
        when = datetime(2026, 10, 5, 10, tzinfo=TZ)
        excursion = Event(
            "Экскурсия",
            when,
            duration_minutes=90,
            audience_label="8+",
            route="замок — археологический комплекс",
        )
        rendered_excursion = event_lines(excursion)
        self.assertIn(
            "Маршрут: замок — археологический комплекс",
            rendered_excursion,
        )
        self.assertIn("90 мин • 8+", rendered_excursion)
        self.assertNotIn("🧭", rendered_excursion)
        self.assertNotIn("🚶", rendered_excursion)
        grouped = Event("Праздничный концерт", when, programme_title="Праздник")
        self.assertIn("• 🎉 Праздник", event_lines(grouped))

    def test_safe_richer_title_and_metadata_union(self):
        when = datetime(2026, 10, 5, 18, tzinfo=TZ)
        generic = Event("Кино по понедельникам", when, place="Biblioteca Municipal")
        specific = Event("Кино по понедельникам: «Новый фильм»", when,
            place="Biblioteca Municipal", duration_minutes=103,
            audience_label="13+", details=("Драма",))
        merged = _merge_events((generic,), (specific,))
        self.assertEqual(len(merged), 1)
        self.assertIn("Новый фильм", merged[0].title)
        self.assertEqual(merged[0].details, ("Драма",))
        excursion = _merge_events(
            (Event("Экскурсия", when),),
            (Event("Экскурсия «Память песка»", when),),
        )
        self.assertEqual(excursion[0].title, "Экскурсия «Память песка»")
        unrelated = _merge_events(
            (Event("Концерт муниципального оркестра", when),),
            (Event("Музыкальный вечер в парке", when),),
        )
        self.assertEqual(len(unrelated), 2)


class UnchangedTextRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_matching_hash_still_adds_cinema_without_model(self):
        page = f"<article>{PROGRAMME}</article>".encode()
        programme, month = extract_official_agenda_text(page)
        previous = SourceEvent(
            "Exposición de pintura", date(2026, 9, 14),
            date(2026, 9, 14), None, None, "Casa de Cultura",
            "exhibition", ("turismo_html",),
        )
        generic = SourceEvent(
            "Cine de los Lunes", date(2026, 9, 14),
            date(2026, 9, 14), "18:00", None,
            "Biblioteca Municipal", "event", ("mupi",),
        )
        now = datetime(2026, 9, 14, 5, 10, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "municipal.json"
            _write_snapshot(path, _snapshot_data(
                "", "", now, (previous, generic), {
                    "turismo_html": {
                        "sha256": hashlib.sha256(programme.encode()).hexdigest(),
                        "month": month,
                        "extractor_version": 4,
                    },
                },
            ))
            with (
                patch("telegrambot.municipal_agenda._read_url",
                      return_value=(page, "text/html")),
                patch("telegrambot.municipal_agenda.extract_agenda_text_events",
                      new=AsyncMock(side_effect=AssertionError("model called"))) as model,
                patch("telegrambot.municipal_agenda.fetch_program_window",
                      new=AsyncMock(side_effect=TodoCulturaError(
                          "offline", code="NETWORK", description="offline"
                      ))),
                patch("telegrambot.municipal_agenda.fetch_facebook_posts",
                      new=AsyncMock(return_value=())),
                patch("telegrambot.municipal_agenda._turismo_programme_events",
                      new=AsyncMock(return_value=((), {}))),
            ):
                result = await refresh_municipal_catalog("key", now, path)
            model.assert_not_awaited()
            cinema = [e for e in result if "turismo_cinema" in e.sources]
            self.assertEqual(len(cinema), 3)
            self.assertEqual(cinema[0].duration_minutes, 144)
            self.assertEqual(len([
                e for e in result if e.start_date == date(2026, 9, 14)
                and "Cine" in e.title_es
            ]), 1)
            self.assertEqual(_load_snapshot(path)["_events"][0].duration_minutes, 144)


if __name__ == "__main__":
    unittest.main()
