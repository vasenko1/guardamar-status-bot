import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.am_guardamar import (
    _is_public_future_candidate,
    _post_fields,
    fetch_today_am_guardamar_events,
    refresh_am_guardamar_catalog,
)
from telegrambot.municipal_agenda import MunicipalAgendaError


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 10, 7, 30, tzinfo=TZ)


def _post(*, identifier=42, modified="2026-09-09T12:00:00", title="Concierto de otoño", content=None):
    return {
        "id": identifier,
        "date": "2026-09-09T10:00:00",
        "modified": modified,
        "link": "https://amguardamar.es/2026/09/09/concierto-otono/",
        "title": {"rendered": title},
        "content": {"rendered": content or (
            "<p>El sábado 20 de septiembre de 2026 a las 20:00, la Banda "
            "ofrecerá el Concierto de otoño en la Plaza de la Constitución "
            "de Guardamar.</p>"
        )},
        "excerpt": {"rendered": "<p>Concierto público.</p>"},
        "categories": [1], "tags": [], "featured_media": 0, "_links": {},
    }


def _extraction():
    evidence = (
        "El sábado 20 de septiembre de 2026 a las 20:00, la Banda ofrecerá "
        "el Concierto de otoño en la Plaza de la Constitución de Guardamar."
    )
    return {"month": "2026-09", "events": [{
        "title_es": "Concierto de otoño",
        "start_date": "2026-09-20", "end_date": "2026-09-20",
        "start_time": "20:00", "end_time": None,
        "place": "Plaza de la Constitución", "evidence_es": evidence,
        "category": "event", "ticket_price_cents": None, "ticket_url": None,
        "participation_note": None, "registration_contact": None,
        "capacity_limited": False, "admission_evidence": None,
    }]}


class AmGuardamarTests(unittest.IsolatedAsyncioTestCase):
    def test_reads_wordpress_fields_and_plain_text(self):
        post = _post_fields(_post())

        self.assertEqual(post["id"], 42)
        self.assertEqual(post["date"], "2026-09-09T10:00:00")
        self.assertEqual(post["modified"], "2026-09-09T12:00:00")
        self.assertEqual(post["link"], "https://amguardamar.es/2026/09/09/concierto-otono/")
        self.assertIn("Concierto de otoño", post["text"])
        self.assertNotIn("<p>", post["text"])
        self.assertEqual(post["categories"], [1])
        self.assertEqual(post["featured_media"], 0)

    def test_keeps_public_future_concert_but_rejects_enrolment(self):
        self.assertEqual(_is_public_future_candidate(_post_fields(_post()), NOW), "2026-09")
        registration = _post_fields(_post(
            identifier=43,
            title="Matrícula de la Escuela de Música",
            content=(
                "<p>La matrícula estará abierta hasta el 20 de septiembre de "
                "2026 en Guardamar. El alumnado podrá participar en conciertos.</p>"
            ),
        ))
        self.assertIsNone(_is_public_future_candidate(registration, NOW))

        scholarship = _post_fields(_post(
            identifier=44,
            title="Convocatoria de Becas CaixaBank",
            content="<p>Solicitud hasta el 1 de octubre de 2026 en Guardamar.</p>",
        ))
        self.assertIsNone(_is_public_future_candidate(scholarship, NOW))

    async def test_refresh_preserves_id_modified_link_and_event(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "am.json"
            with (
                patch("telegrambot.am_guardamar._read_posts", return_value=[_post()]),
                patch("telegrambot.am_guardamar.extract_agenda_text_events", new=AsyncMock(return_value=_extraction())) as extract,
            ):
                events = await refresh_am_guardamar_catalog("key", NOW, state)
                repeated = await refresh_am_guardamar_catalog("key", NOW, state)
                today = await fetch_today_am_guardamar_events(
                    datetime(2026, 9, 20, 7, 30, tzinfo=TZ), state,
                    Path(directory) / "translations.json",
                )
            stored = state.read_text(encoding="utf-8")

        self.assertEqual(len(events), 1)
        self.assertEqual(len(repeated), 1)
        extract.assert_awaited_once()
        self.assertIn('"id":42', stored)
        self.assertIn('"modified":"2026-09-09T12:00:00"', stored)
        self.assertIn('"link":"https://amguardamar.es/2026/09/09/concierto-otono/"', stored)
        self.assertIn('"categories":[1]', stored)
        self.assertEqual(today[0].title, "Concierto de otoño")
        self.assertEqual(today[0].starts_at.hour, 20)

    async def test_invalid_one_post_does_not_block_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "am.json"
            with (
                patch("telegrambot.am_guardamar._read_posts", return_value=[_post()]),
                patch(
                    "telegrambot.am_guardamar.extract_agenda_text_events",
                    new=AsyncMock(return_value=_extraction()),
                ),
                patch(
                    "telegrambot.am_guardamar.normalize_extraction_candidates",
                    side_effect=MunicipalAgendaError("invalid candidate"),
                ),
            ):
                events = await refresh_am_guardamar_catalog("key", NOW, state)

            stored = state.read_text(encoding="utf-8")

        self.assertEqual(events, ())
        self.assertIn('"posts":[]', stored)


if __name__ == "__main__":
    unittest.main()
