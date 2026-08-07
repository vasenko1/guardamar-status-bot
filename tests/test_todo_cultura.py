import json
import unittest
import urllib.parse
from datetime import date
from email.message import Message
from unittest.mock import patch

from telegrambot.todo_cultura import (
    TodoCulturaError,
    _admissions,
    _date_sections,
    _metadata_candidate,
    _metadata_query,
    _participation,
    _read_documents,
    _read_program_window,
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
            "parser_version": 4,
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
            "parser_version": 4,
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

    def test_covering_date_marks_older_duplicate_candidate_processed(self):
        prior = {
            "parser_version": 4,
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
        self.assertNotIn("Evento 1", window.programs[0].text)
        self.assertTrue(all(
            "2026-08-09" in candidate["processed_dates"]
            for candidate in window.source_state["candidates"]
        ))
        self.assertIn("2026-08-09", window.source_state["covered_dates"])

    def test_changed_publication_reopens_already_processed_date(self):
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
            details[0].participation_note, "для молодёжи 12–30 лет"
        )

    def test_generic_information_is_not_registration(self):
        details = _participation(
            "Sábado 8 de agosto\n"
            "19 a 21 h.: Taller de baterías para jóvenes de 12 a 30 años.\n"
            "Más información: Wasap 609 00 67 54."
        )

        self.assertEqual(details, ())

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
        admissions = _admissions(rendered)

        self.assertEqual(len(admissions), 1)
        self.assertEqual(admissions[0].price_cents, 1500)
        self.assertTrue(admissions[0].event_url.endswith(
            "/spanish-brass-top-secret.html"
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

    def test_oversized_rolling_sections_do_not_advance_state(self):
        prior = {
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
            with self.assertRaises(TodoCulturaError) as raised:
                _read_program_window(date(2026, 8, 9), prior)

        self.assertEqual(raised.exception.diagnostic_code, "DAILY-SIZE")


if __name__ == "__main__":
    unittest.main()
