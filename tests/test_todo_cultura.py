import json
import unittest
import urllib.parse
from datetime import date
from email.message import Message
from unittest.mock import patch

from telegrambot.todo_cultura import (
    TodoCulturaError,
    _participation,
    _read_latest_program,
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

    def test_selects_dated_candidate_instead_of_latest_guardamar_item(self):
        programme = (
            "<p>El Ayuntamiento de Guardamar publica la agenda municipal.</p>"
            "<p>Sábado 8 de agosto</p>"
            f"<p>{'Programa cultural. ' * 20}</p>"
            "<p>Domingo 9 de agosto</p><p>Otro evento.</p>"
        )
        payload = json.dumps([
            {
                "modified": "2026-08-07T09:10:00",
                "link": "https://todoculturavegabaja.es/eventos/routine/",
                "title": {"rendered": "Actividades juveniles"},
                "content": {"rendered": (
                    "<p>El Ayuntamiento de Guardamar publica la agenda "
                    "municipal.</p><p>Domingo 9 de agosto</p>"
                    f"<p>{'Otro programa. ' * 20}</p>"
                )},
            },
            {
                "modified": "2026-08-07T09:00:00",
                "link": "https://todoculturavegabaja.es/eventos/drums/",
                "title": {"rendered": "Taller de baterías"},
                "content": {"rendered": programme},
            },
        ]).encode()
        opener = _Opener(_Response(payload))
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=opener,
        ):
            program = _read_latest_program(date(2026, 8, 8))

        self.assertTrue(program.source_url.endswith("/drums/"))
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(opener.request.full_url).query
        )
        self.assertEqual(query["search"], ["Guardamar 8 de agosto"])
        self.assertEqual(query["per_page"], ["3"])

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
        payload = json.dumps([{
            "modified": "2026-08-05T09:00:00",
            "link": "https://todoculturavegabaja.es/eventos/guardamar/",
            "content": {"rendered": rendered},
        }]).encode()
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=_Opener(_Response(payload)),
        ):
            program = _read_latest_program(date(2026, 8, 5))

        self.assertEqual(len(program.admissions), 1)
        self.assertEqual(program.admissions[0].price_cents, 1500)
        self.assertTrue(program.admissions[0].event_url.endswith(
            "/spanish-brass-top-secret.html"
        ))

    def test_reads_one_bounded_attributed_programme(self):
        text = (
            "El Ayuntamiento de Guardamar del Segura publica la agenda "
            "municipal."
        )
        payload = json.dumps([{
            "modified": "2026-08-05T09:00:00",
            "link": "https://todoculturavegabaja.es/eventos/guardamar/",
            "title": {"rendered": "Guardamar"},
            "content": {"rendered": (
                f"<p>{text}</p><p>Miércoles 5 de agosto</p>"
                f"<p>{'Evento cultural. ' * 30}</p>"
                "<p>Jueves 6 de agosto</p><p>Otro evento.</p>"
            )},
        }]).encode()
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=_Opener(_Response(payload)),
        ):
            program = _read_latest_program(date(2026, 8, 5))

        self.assertIn("Evento cultural", program.text)
        self.assertEqual(len(program.sha256), 64)

    def test_rejects_unattributed_general_article(self):
        payload = json.dumps([{
            "link": "https://todoculturavegabaja.es/eventos/other/",
            "title": {"rendered": "Other"},
            "content": {"rendered": "<p>Not a programme</p>"},
        }]).encode()
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=_Opener(_Response(payload)),
        ):
            with self.assertRaises(TodoCulturaError) as raised:
                _read_latest_program(date(2026, 8, 5))

        self.assertEqual(raised.exception.diagnostic_code, "NOT-PROGRAMME")

    def test_rejects_daily_section_larger_than_llm_input_limit(self):
        text = (
            "El Ayuntamiento de Guardamar publica la agenda municipal.\n"
            "Miércoles 5 de agosto\n"
            + "Actividad cultural. " * 800
            + "\nJueves 6 de agosto\nOtra actividad"
        )
        payload = json.dumps([{
            "link": "https://todoculturavegabaja.es/eventos/guardamar/",
            "title": {"rendered": "Guardamar"},
            "content": {"rendered": f"<p>{text}</p>"},
        }]).encode()
        with patch(
            "telegrambot.todo_cultura.urllib.request.build_opener",
            return_value=_Opener(_Response(payload)),
        ):
            with self.assertRaises(TodoCulturaError) as raised:
                _read_latest_program(date(2026, 8, 5))

        self.assertEqual(raised.exception.diagnostic_code, "DAILY-SIZE")


if __name__ == "__main__":
    unittest.main()
