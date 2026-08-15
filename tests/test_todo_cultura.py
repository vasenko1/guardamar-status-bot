import json
import unittest
import urllib.parse
from datetime import date
from email.message import Message
from unittest.mock import patch

from telegrambot.todo_cultura import (
    TodoCulturaError,
    _admissions,
    _bounded_candidates,
    _date_sections,
    _event_time,
    _metadata_candidate,
    _metadata_query,
    _participation,
    _read_documents,
    _read_program_window,
    _ticket_url,
)


class _Response:
    def __init__(self, payload, content_type="application/json"):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]

    def geturl(self):
        return "https://todoculturavegabaja.es/wp-json/wp/v2/mec-events"


class _Opener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return self.response


class TodoCulturaTests(unittest.TestCase):
    def test_event_time_does_not_read_compact_date_list_as_clock(self):
        self.assertEqual(
            _event_time("5,6 y 7 de agosto a las 22:00 h"),
            "22:00",
        )

    def test_event_time_uses_start_of_time_range(self):
        self.assertEqual(_event_time("19 a 21 h.: Taller"), "19:00")

    def test_metadata_candidate_uses_date_mentioned_in_excerpt(self):
        candidate = _metadata_candidate({
            "id": 128245,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "title": {"rendered": "Agenda municipal de Guardamar"},
            "excerpt": {"rendered": "Actividades del 12 de agosto"},
        }, date(2026, 8, 7))

        self.assertEqual(candidate["dates"], ["2026-08-12"])
        self.assertFalse(candidate["detail_checked"])
        self.assertEqual(candidate["detail_priority"], 0)

    def test_bounded_index_retains_partially_processed_large_section(self):
        candidates = [{
            "id": identifier,
            "modified_gmt": f"2026-08-14T10:{identifier % 60:02d}:00",
            "dates": ["2026-08-16"],
            "processed_dates": [],
            "detail_checked": False,
        } for identifier in range(1, 102)]
        candidates.append({
            "id": 999,
            "modified_gmt": "2026-08-01T10:00:00",
            "dates": ["2026-08-16"],
            "processed_dates": [],
            "processed_chunks": {"2026-08-16": ["a" * 64]},
            "detail_checked": True,
        })

        bounded = _bounded_candidates(candidates, date(2026, 8, 15))

        self.assertEqual(len(bounded), 100)
        self.assertIn(999, {candidate["id"] for candidate in bounded})

    def test_metadata_prioritizes_event_local_participation_facts(self):
        candidate = _metadata_candidate({
            "id": 128582,
            "modified_gmt": "2026-08-10T16:50:52",
            "link": "https://todoculturavegabaja.es/eventos/guitarras/",
            "title": {"rendered": (
                "Taller de guitarras eléctricas para jóvenes "
                "de 12 a 30 años"
            )},
            "excerpt": {"rendered": (
                "Sábado 15 de agosto. Inscripciones en el centro."
            )},
        }, date(2026, 8, 15))

        self.assertEqual(candidate["dates"], ["2026-08-15"])
        self.assertEqual(candidate["detail_priority"], 3)

    def test_metadata_without_date_is_not_selected_for_full_download(self):
        metadata = [{
            "id": 128245,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/noticia/",
            "title": {"rendered": "Guardamar cultura"},
            "excerpt": {"rendered": "Toda la información municipal"},
        }]
        with (
            patch(
                "telegrambot.todo_cultura._read_metadata",
                return_value=metadata,
            ),
            patch("telegrambot.todo_cultura._read_documents") as details,
        ):
            window = _read_program_window(date(2026, 8, 7), {})

        details.assert_called_once_with([])
        self.assertEqual(window.programs, ())
        self.assertTrue(
            window.source_state["candidates"][0]["detail_checked"]
        )

    def test_incremental_query_overlaps_cursor_by_five_minutes(self):
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(
                _metadata_query("2026-08-07T10:00:00")
            ).query
        )

        self.assertEqual(
            query["modified_after"], ["2026-08-07T09:55:00"]
        )
        self.assertIn("modified_gmt", query["_fields"][0])
        self.assertEqual(query["order"], ["asc"])

    def test_date_sections_roll_january_into_next_year(self):
        sections = _date_sections(
            ["Viernes 1 de enero", "19:00: Concierto"],
            2026,
            date(2026, 12, 29),
        )

        self.assertIn(date(2027, 1, 1), sections)

    def test_splits_inline_first_event_from_date_heading(self):
        sections = _date_sections([
            "– Lunes 10 de agosto, 8:30 a 14 horas: Taller juvenil",
            "Inscripciones: Centro Social Juvenil 609 00 67 54",
            "Martes 11 de agosto",
            "19:00: Concierto",
        ], 2026)

        self.assertIn(date(2026, 8, 10), sections)
        self.assertIn("8:30 a 14 horas", sections[date(2026, 8, 10)])
        self.assertNotIn("Concierto", sections[date(2026, 8, 10)])

    def test_processes_only_new_edge_date_from_saved_candidate(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "candidates": [{
                "id": 128245,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": [f"2026-08-{day:02d}" for day in range(9, 16)],
                "processed_dates": [
                    f"2026-08-{day:02d}" for day in range(9, 15)
                ],
                "detail_checked": True,
            }],
        }
        rendered = (
            "<p>El Ayuntamiento de Guardamar publica la agenda municipal.</p>"
            "<p>Sábado 15 de agosto</p>"
            "<p>19:00: Taller de música para jóvenes.</p>"
        )
        document = {
            "id": 128245,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "content": {"rendered": rendered},
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ) as details,
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        details.assert_called_once_with([128245])
        self.assertEqual(len(window.programs), 1)
        self.assertEqual(window.programs[0].dates, (date(2026, 8, 15),))
        candidate = window.source_state["candidates"][0]
        self.assertIn("2026-08-15", candidate["processed_dates"])

    def test_unchanged_complete_window_makes_no_detail_request(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "candidates": [{
                "id": 128245,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": ["2026-08-09", "2026-08-10"],
                "processed_dates": ["2026-08-09", "2026-08-10"],
                "detail_checked": True,
            }],
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch("telegrambot.todo_cultura._read_documents") as details,
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        details.assert_called_once_with([])
        self.assertEqual(window.programs, ())

    def test_parser_upgrade_reopens_previously_covered_dates(self):
        prior = {
            "parser_version": 4,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "covered_dates": ["2026-08-09"],
            "candidates": [{
                "id": 128245,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": ["2026-08-09"],
                "processed_dates": ["2026-08-09"],
                "detail_checked": True,
            }],
        }
        document = {
            "id": 128245,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p>"
                "<p>22:30: Concierto benéfico de Trivox.</p>"
            )},
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ) as details,
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        details.assert_called_once_with([128245])
        self.assertEqual(window.programs[0].dates, (date(2026, 8, 9),))
        self.assertEqual(window.source_state["parser_version"], 8)

    def test_same_date_candidates_are_each_processed(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "candidates": [
                {
                    "id": 2,
                    "modified_gmt": "2026-08-07T10:00:00",
                    "link": "https://todoculturavegabaja.es/eventos/new/",
                    "dates": ["2026-08-09"],
                    "processed_dates": [],
                    "detail_checked": True,
                },
                {
                    "id": 1,
                    "modified_gmt": "2026-08-06T10:00:00",
                    "link": "https://todoculturavegabaja.es/eventos/old/",
                    "dates": ["2026-08-09"],
                    "processed_dates": [],
                    "detail_checked": True,
                },
            ],
        }
        documents = [{
            "id": identifier,
            "modified_gmt": modified,
            "link": link,
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p>"
                f"<p>19:00: Evento {identifier}.</p>"
            )},
        } for identifier, modified, link in (
            (2, "2026-08-07T10:00:00", prior["candidates"][0]["link"]),
            (1, "2026-08-06T10:00:00", prior["candidates"][1]["link"]),
        )]
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=documents,
            ),
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        self.assertEqual(len(window.programs), 1)
        self.assertIn("Evento 2", window.programs[0].text)
        self.assertIn("Evento 1", window.programs[0].text)
        self.assertTrue(all(
            "2026-08-09" in candidate["processed_dates"]
            for candidate in window.source_state["candidates"]
        ))
        self.assertIn("2026-08-09", window.source_state["covered_dates"])

    def test_actionable_older_candidate_wins_one_of_three_bounded_slots(self):
        metadata = []
        for identifier, modified, title in (
            (4, "2026-08-14T12:00:00", "Concierto cuatro"),
            (3, "2026-08-14T11:00:00", "Concierto tres"),
            (2, "2026-08-14T10:00:00", "Concierto dos"),
            (
                1,
                "2026-08-10T10:00:00",
                "Taller de guitarra para jóvenes de 12 a 30 años",
            ),
        ):
            metadata.append({
                "id": identifier,
                "modified_gmt": modified,
                "link": (
                    "https://todoculturavegabaja.es/eventos/"
                    f"{identifier}/"
                ),
                "title": {"rendered": title},
                "excerpt": {"rendered": "Sábado 15 de agosto"},
            })
        documents = [{
            "id": item["id"],
            "modified_gmt": item["modified_gmt"],
            "link": item["link"],
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Sábado 15 de agosto</p>"
                f"<p>19:00: Evento {item['id']}.</p>"
            )},
        } for item in metadata]
        selected_ids = []

        def selected_documents(identifiers):
            selected_ids.extend(identifiers)
            return [
                item for item in documents if item["id"] in identifiers
            ]

        with (
            patch(
                "telegrambot.todo_cultura._read_metadata",
                return_value=metadata,
            ),
            patch(
                "telegrambot.todo_cultura._read_documents",
                side_effect=selected_documents,
            ),
        ):
            _read_program_window(date(2026, 8, 15), {})

        self.assertEqual(len(selected_ids), 3)
        self.assertIn(1, selected_ids)
        self.assertNotIn(2, selected_ids)

    def test_parser_upgrade_refreshes_priority_for_unchanged_candidates(self):
        metadata = []
        prior_candidates = []
        for identifier, modified, title in (
            (4, "2026-08-14T12:00:00", "Concierto cuatro"),
            (3, "2026-08-14T11:00:00", "Concierto tres"),
            (2, "2026-08-14T10:00:00", "Concierto dos"),
            (
                1,
                "2026-08-10T10:00:00",
                "Taller de guitarra para jóvenes de 12 a 30 años",
            ),
        ):
            link = f"https://todoculturavegabaja.es/eventos/{identifier}/"
            metadata.append({
                "id": identifier,
                "modified_gmt": modified,
                "link": link,
                "title": {"rendered": title},
                "excerpt": {"rendered": "Sábado 15 de agosto"},
            })
            prior_candidates.append({
                "id": identifier,
                "modified_gmt": modified,
                "link": link,
                "dates": ["2026-08-15"],
                "processed_dates": ["2026-08-15"],
                "detail_checked": True,
            })
        selected_ids = []

        def selected_documents(identifiers):
            selected_ids.extend(identifiers)
            return [{
                "id": identifier,
                "modified_gmt": next(
                    item["modified_gmt"] for item in metadata
                    if item["id"] == identifier
                ),
                "link": (
                    "https://todoculturavegabaja.es/eventos/"
                    f"{identifier}/"
                ),
                "content": {"rendered": (
                    "<p>El Ayuntamiento de Guardamar publica la agenda "
                    "municipal.</p><p>Sábado 15 de agosto</p>"
                    f"<p>19:00: Evento {identifier}.</p>"
                )},
            } for identifier in identifiers]

        with (
            patch(
                "telegrambot.todo_cultura._read_metadata",
                return_value=metadata,
            ),
            patch(
                "telegrambot.todo_cultura._read_documents",
                side_effect=selected_documents,
            ),
        ):
            window = _read_program_window(date(2026, 8, 15), {
                "parser_version": 6,
                "cursor_modified_gmt": "2026-08-14T12:00:00",
                "covered_dates": ["2026-08-15"],
                "candidates": prior_candidates,
            })

        self.assertEqual(len(selected_ids), 3)
        self.assertIn(1, selected_ids)
        self.assertNotIn(2, selected_ids)
        guitar = next(
            candidate for candidate in window.source_state["candidates"]
            if candidate["id"] == 1
        )
        self.assertEqual(guitar["detail_priority"], 2)
        self.assertIn("2026-08-15", guitar["processed_dates"])

    def test_changed_publication_reopens_already_processed_date(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "covered_dates": ["2026-08-09"],
            "candidates": [{
                "id": 128245,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": ["2026-08-09"],
                "processed_dates": ["2026-08-09"],
                "detail_checked": True,
            }],
        }
        metadata = [{
            "id": 128245,
            "modified_gmt": "2026-08-08T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "title": {"rendered": "Guardamar"},
            "excerpt": {"rendered": "<p>Domingo 9 de agosto</p>"},
        }]
        document = {
            "id": 128245,
            "modified_gmt": "2026-08-08T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p>"
                "<p>20:00: Concierto actualizado.</p>"
            )},
        }
        with (
            patch(
                "telegrambot.todo_cultura._read_metadata",
                return_value=metadata,
            ),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ),
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        self.assertEqual(window.programs[0].dates, (date(2026, 8, 9),))
        self.assertIn("Concierto actualizado", window.programs[0].text)

    def test_binds_explicit_registration_to_preceding_workshop(self):
        details = _participation(
            "Sábado 8 de agosto\n"
            "19 a 21 h.: Actividades del Centro Social Juvenil (CSJ) "
            "para jóvenes de 12 a 30 años.\n"
            "Más información: Wasap 609 00 67 54.\n"
            "19 a 21 h.: Taller de baterías para jóvenes de 12 a 30 años.\n"
            "Los participantes podrán aprender desde cero.\n"
            "Inscripciones: Centro Social Juvenil y Whatsapp 609 00 67 54"
        )

        self.assertEqual(len(details), 1)
        self.assertIn("Taller de baterías", details[0].title_hint)
        self.assertEqual(
            details[0].registration_contact,
            "Centro Social Juvenil или WhatsApp 609 00 67 54",
        )
        self.assertEqual(
            details[0].participation_note,
            "для молодёжи 12–30 лет; можно начать с нуля",
        )
        self.assertEqual(details[0].start_time, "19:00")

    def test_preserves_explicit_beginner_improvement_and_group_format(self):
        details = _participation(
            "Sábado 15 de agosto\n"
            "19 a 21 h.: Taller de guitarras eléctricas para jóvenes "
            "de 12 a 30 años.\n"
            "Se puede aprender desde cero o mejorar acordes, escalas, "
            "ritmos, solos, técnica, improvisación y práctica en grupo.\n"
            "Inscripciones: Centro Social Juvenil y WhatsApp 609 00 67 54"
        )

        self.assertEqual(len(details), 1)
        self.assertEqual(
            details[0].participation_note,
            "для молодёжи 12–30 лет; можно начать с нуля или "
            "улучшить технику и игру в группе",
        )

    def test_program_binds_participation_to_its_dated_section(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-14T10:00:00",
            "candidates": [{
                "id": 1,
                "modified_gmt": "2026-08-14T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/guitarra/",
                "dates": ["2026-08-15"],
                "processed_dates": [],
                "detail_checked": True,
            }],
        }
        document = {
            "id": 1,
            "modified_gmt": "2026-08-14T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/guitarra/",
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Sábado 15 de agosto</p>"
                "<p>19:00: Taller de guitarra para jóvenes de 12 a 30 "
                "años.</p><p>Inscripciones: WhatsApp 600 00 00 00</p>"
            )},
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ),
        ):
            window = _read_program_window(date(2026, 8, 15), prior)

        detail = window.programs[0].participation[0]
        self.assertEqual(detail.event_dates, (date(2026, 8, 15),))
        self.assertEqual(detail.start_time, "19:00")

    def test_generic_information_is_not_registration(self):
        details = _participation(
            "Sábado 8 de agosto\n"
            "19 a 21 h.: Taller de baterías para jóvenes de 12 a 30 años.\n"
            "Más información: Wasap 609 00 67 54."
        )

        self.assertEqual(details, ())

    def test_binds_email_only_registration_age_and_flexible_capacity(self):
        details = _participation(
            "Sábado 22 de agosto\n"
            "08:00: Ruta para niños entre 6 y 14 años.\n"
            "Las plazas están limitadas.\n"
            "Inscripciones: actividades@example.es"
        )

        self.assertEqual(len(details), 1)
        self.assertEqual(
            details[0].registration_contact,
            "actividades@example.es",
        )
        self.assertEqual(
            details[0].participation_note,
            "для участников 6–14 лет",
        )
        self.assertTrue(details[0].capacity_limited)

    def test_binds_minimum_age_from_registration_row(self):
        details = _participation(
            "Jueves 20 de agosto\n"
            "11:30: Taller para edades a partir de 4 años.\n"
            "Reservas: 966 72 71 70"
        )

        self.assertEqual(len(details), 1)
        self.assertEqual(
            details[0].participation_note,
            "для участников от 4 лет",
        )

    def test_reads_explicit_price_linked_to_official_event(self):
        rendered = (
            "<p>El Ayuntamiento de Guardamar publica la agenda municipal.</p>"
            "<p>Miércoles 5 de agosto</p>"
            "<p>Concierto de Spanish Brass. "
            "El precio de la entrada es de <strong>15 euros</strong>. "
            "Compra en <a href=\"https://www.agendaguardamar.com/"
            "espectaculo/48/spanish-brass-top-secret.html\">Agenda</a>.</p>"
            f"<p>{'Programa cultural. ' * 20}</p>"
            "<p>Jueves 6 de agosto</p><p>Otro evento.</p>"
        )
        admissions = _admissions(rendered, date(2026, 8, 14))

        self.assertEqual(len(admissions), 1)
        self.assertEqual(admissions[0].price_cents, 1500)
        self.assertTrue(admissions[0].ticket_url.endswith(
            "/spanish-brass-top-secret.html"
        ))

    def test_reads_giglon_price_and_binds_it_to_preceding_event(self):
        rendered = (
            "<p>Viernes 14 de agosto</p>"
            "<p>– <strong>22,30 h.</strong>: Concierto benéfico a favor de "
            "Alicante contra el cáncer, tributo a Il Divo, por Trivox.</p>"
            "<p>El precio de las entradas es de <strong>20 euros</strong>. "
            "Venta en <a href=\"https://www.giglon.com/todos?"
            "idEvent=concierto-benefico-trivox\">Giglon</a>.</p>"
        )

        admissions = _admissions(rendered)

        self.assertEqual(len(admissions), 1)
        self.assertIn("Concierto benéfico", admissions[0].title_hint)
        self.assertEqual(admissions[0].price_cents, 2000)
        self.assertEqual(
            admissions[0].ticket_url,
            "https://www.giglon.com/todos?idEvent=concierto-benefico-trivox",
        )
        self.assertEqual(admissions[0].event_date, date(2026, 8, 14))

    def test_reads_ticket_only_from_same_official_event_paragraph(self):
        admissions = _admissions(
            "<p><strong>Viernes, 14 de agosto a las 22:30 h. Parque "
            "Reina Sofía.</strong><br>TRIVOX (Tributo a Il Divo)<br>"
            "Concierto benéfico para la lucha contra el cáncer<br>"
            "Entradas en <a href=\"https://www.giglon.com/\">Giglon</a></p>",
            date(2026, 8, 13),
        )

        self.assertEqual(len(admissions), 1)
        self.assertIsNone(admissions[0].price_cents)
        self.assertEqual(admissions[0].ticket_url, "https://www.giglon.com/")
        self.assertEqual(admissions[0].event_date, date(2026, 8, 14))

    def test_inline_dated_event_replaces_previous_price_anchor(self):
        admissions = _admissions(
            "<p>– 21:30 h.: Sesión de baile de verano.</p>"
            "<p>Miércoles 2 de septiembre, 20 horas: Representación de la "
            "obra de teatro La balada de los tres inocentes.</p>"
            "<p>El precio de las entradas es de 8 euros.</p>",
            date(2026, 8, 13),
        )

        self.assertIn("Representación", admissions[0].title_hint)
        self.assertEqual(admissions[0].event_date, date(2026, 9, 2))

    def test_reads_event_local_free_admission_without_link(self):
        admissions = _admissions(
            "<p>– 21,30 h.: Sesión de baile de verano.</p>"
            "<p>La entrada es libre.</p>"
        )

        self.assertEqual(admissions[0].price_cents, 0)
        self.assertIsNone(admissions[0].ticket_url)

    def test_reads_compact_official_price_format(self):
        admissions = _admissions(
            "<p>Miércoles 19 de agosto, a las 20:30 h. Casa de Cultura. "
            "RECITAL FLAMENCO: AL ALIMÓN<br>Precio: 5 €</p>",
            date(2026, 8, 13),
        )

        self.assertEqual(admissions[0].price_cents, 500)
        self.assertEqual(admissions[0].event_date, date(2026, 8, 19))

    def test_a_las_event_row_replaces_previous_admission_anchor(self):
        admissions = _admissions(
            "<p>22:30 h.: Concierto Trivox</p>"
            "<p>A las 20 h.: Teatro Beta</p>"
            "<p>Precio: 8 €</p>",
            date(2026, 8, 30),
        )

        self.assertEqual(len(admissions), 1)
        self.assertIn("Teatro Beta", admissions[0].title_hint)
        self.assertEqual(admissions[0].start_time, "20:00")

    def test_expands_multidate_admission_lists(self):
        admissions = _admissions(
            "<p>27, 28 y 29 de agosto, 20 h.: Teatro de verano</p>"
            "<p>Precio: 8 €</p>",
            date(2026, 8, 20),
        )

        self.assertEqual(admissions[0].event_dates, (
            date(2026, 8, 27),
            date(2026, 8, 28),
            date(2026, 8, 29),
        ))

    def test_sale_window_dates_do_not_become_performance_dates(self):
        admissions = _admissions(
            "<p>27, 28 y 29 de agosto / 2, 3 y 4 de septiembre "
            "a las 20:00 h. Casa de Cultura. LA BALADA. "
            "Venta de entradas del 24 al 31 de agosto y del 1 al 4 de "
            "septiembre de 17:30 h a 19:30 h. Precio: 8 €</p>",
            date(2026, 8, 20),
        )

        self.assertEqual(admissions[0].event_dates, (
            date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 29),
            date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4),
        ))
        self.assertEqual(admissions[0].start_time, "20:00")

    def test_dated_free_event_does_not_borrow_previous_anchor(self):
        admissions = _admissions(
            "<p>5, 6 y 7 de agosto a las 22:00 h. Festival</p>"
            "<p>Del 19 de junio al 14 de agosto. MEDITERRÁNEO, EL "
            "LENGUAJE DEL AGUA. Entrada libre. Horario de visitas: "
            "lunes a viernes de 9:00 h a 20:00 h</p>",
            date(2026, 8, 13),
        )

        self.assertEqual(len(admissions), 1)
        self.assertIn("MEDITERRÁNEO", admissions[0].title_hint)
        self.assertNotIn("Festival", admissions[0].title_hint)

    def test_reads_common_explicit_free_admission_variants(self):
        for wording in (
            "Entrada libre",
            "Acceso libre",
            "El acceso es gratuito",
            "Entradas gratuitas",
            "Los accesos son gratuitos",
        ):
            with self.subTest(wording=wording):
                admissions = _admissions(
                    f"<p>20 h.: Concierto Alpha</p><p>{wording}</p>"
                )
                self.assertEqual(admissions[0].price_cents, 0)

    def test_ticket_url_rejects_userinfo_and_ports(self):
        for candidate in (
            "https://operator@giglon.com/event",
            "https://giglon.com:443/event",
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNone(_ticket_url(
                    f'<a href="{candidate}">Entradas</a>'
                ))

    def test_incomplete_detail_batch_is_rejected(self):
        payload = json.dumps([{"id": 1}]).encode()
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=_Opener(_Response(payload)),
        ):
            with self.assertRaises(TodoCulturaError) as raised:
                _read_documents([1, 2])

        self.assertEqual(raised.exception.diagnostic_code, "INVALID")

    def test_oversized_section_is_split_and_advances_state(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "candidates": [{
                "id": 1,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": ["2026-08-09"],
                "processed_dates": [],
                "detail_checked": True,
            }],
        }
        document = {
            "id": 1,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p><p>"
                + "Actividad cultural. " * 800
                + "</p>"
            )},
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ),
        ):
            window = _read_program_window(date(2026, 8, 9), prior)

        self.assertEqual(len(window.programs), 2)
        self.assertTrue(all(
            len(program.text) <= 12_000 for program in window.programs
        ))
        candidate = window.source_state["candidates"][0]
        self.assertIn("2026-08-09", candidate["processed_dates"])
        self.assertEqual(candidate["processed_chunks"], {})

    def test_very_large_section_makes_bounded_progress_across_runs(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-07T10:00:00",
            "candidates": [{
                "id": 1,
                "modified_gmt": "2026-08-07T10:00:00",
                "link": "https://todoculturavegabaja.es/eventos/programa/",
                "dates": ["2026-08-09"],
                "processed_dates": [],
                "detail_checked": True,
            }],
        }
        document = {
            "id": 1,
            "modified_gmt": "2026-08-07T10:00:00",
            "link": "https://todoculturavegabaja.es/eventos/programa/",
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p><p>"
                + "".join(
                    f"Actividad cultural {index}. "
                    for index in range(2400)
                )
                + "</p>"
            )},
        }
        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                return_value=[document],
            ),
        ):
            first = _read_program_window(date(2026, 8, 9), prior)
            second = _read_program_window(
                date(2026, 8, 9), first.source_state
            )

        first_candidate = first.source_state["candidates"][0]
        second_candidate = second.source_state["candidates"][0]
        self.assertEqual(len(first.programs), 3)
        self.assertNotIn("2026-08-09", first_candidate["processed_dates"])
        self.assertEqual(
            len(first_candidate["processed_chunks"]["2026-08-09"]), 3
        )
        self.assertGreaterEqual(len(second.programs), 1)
        self.assertIn("2026-08-09", second_candidate["processed_dates"])
        self.assertEqual(second_candidate["processed_chunks"], {})

    def test_combined_limit_defers_one_page_without_losing_progress(self):
        prior = {
            "parser_version": 8,
            "cursor_modified_gmt": "2026-08-08T10:00:00",
            "candidates": [{
                "id": identifier,
                "modified_gmt": modified,
                "link": f"https://todoculturavegabaja.es/eventos/{identifier}/",
                "dates": ["2026-08-09"],
                "processed_dates": [],
                "detail_checked": True,
            } for identifier, modified in (
                (1, "2026-08-07T10:00:00"),
                (2, "2026-08-08T10:00:00"),
            )],
        }
        documents = [{
            "id": candidate["id"],
            "modified_gmt": candidate["modified_gmt"],
            "link": candidate["link"],
            "content": {"rendered": (
                "<p>El Ayuntamiento de Guardamar publica la agenda "
                "municipal.</p><p>Domingo 9 de agosto</p><p>"
                + f"Evento {candidate['id']}. " * 900
                + "</p>"
            )},
        } for candidate in prior["candidates"]]

        def selected_documents(identifiers):
            return [item for item in documents if item["id"] in identifiers]

        with (
            patch("telegrambot.todo_cultura._read_metadata", return_value=[]),
            patch(
                "telegrambot.todo_cultura._read_documents",
                side_effect=selected_documents,
            ),
        ):
            first = _read_program_window(date(2026, 8, 9), prior)
            second = _read_program_window(
                date(2026, 8, 9), first.source_state
            )

        first_processed = {
            candidate["id"]
            for candidate in first.source_state["candidates"]
            if candidate["processed_dates"]
        }
        second_processed = {
            candidate["id"]
            for candidate in second.source_state["candidates"]
            if candidate["processed_dates"]
        }
        self.assertEqual(len(first.programs), 1)
        self.assertEqual(len(first_processed), 1)
        self.assertEqual(len(second.programs), 1)
        self.assertEqual(second_processed, {1, 2})


if __name__ == "__main__":
    unittest.main()
