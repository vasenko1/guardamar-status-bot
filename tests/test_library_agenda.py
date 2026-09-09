import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.digest import build_message
from telegrambot.library_agenda import (
    _write_snapshot,
    extract_events,
    extract_teaser,
    fetch_today_library_events,
)
from telegrambot.models import MorningDigest


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 9, 7, 30, tzinfo=TZ)
LIST = b'''<div class="registro pagina1"><span class="fecha"><h4>
7 de septiembre - 23 de septiembre de 2026</h4></span>
<a href="/Bibliotecas/guardamardelsegura/actividades-programas/Agenda-de-actividades/exposicion-dibujos.html"><li class="titulo"><h3>Exposici\xc3\xb3n de dibujos de Jos\xc3\xa9 Luis Narbaiza: Amigos y conocidos</h3></li></a>
<div class="list-opc"><li>Hall de la Biblioteca P\xc3\xbablica Municipal</li></div>
</ul><div class="row numActividades">'''
DETAIL = b'''<div class="column detalle"><p>Esta colecci\xc3\xb3n re\xc3\xbane una selecci\xc3\xb3n de retratos realizados por Jos\xc3\xa9 Luis Narbaiza, pintor amateur con un especial dominio del dibujo a carboncillo y a l\xc3\xa1piz.<br />Otra frase.</p></div>'''


class LibraryAgendaTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_active_exhibition_from_list(self):
        records = extract_events(LIST, NOW)
        event, link = records[0]
        self.assertEqual(len(records), 1)
        self.assertEqual(event.active_until.isoformat(), "2026-09-23")
        self.assertEqual(event.place, "Hall de la Biblioteca P\xfablica Municipal")
        self.assertTrue(link.endswith("exposicion-dibujos.html"))

    def test_keeps_one_complete_factual_sentence(self):
        self.assertEqual(
            extract_teaser(DETAIL),
            "Esta colecci\xf3n re\xfane una selecci\xf3n de retratos realizados por Jos\xe9 Luis Narbaiza, pintor amateur con un especial dominio del dibujo a carboncillo y a l\xe1piz.",
        )

    async def test_reviewed_teaser_and_title_render_from_snapshot(self):
        event = extract_events(LIST, NOW)[0][0]
        event = event.__class__(**{**event.__dict__, "teaser": extract_teaser(DETAIL)})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            translations = Path(directory) / "translations.json"
            _write_snapshot(path, NOW, (event,))
            events = await fetch_today_library_events(NOW, path, translations)

        message = build_message(MorningDigest(
            weather=None, warnings=(), warnings_available=False, events=events
        ), now=NOW)
        self.assertIn("Выставка рисунков José Luis Narbaiza", message)
        self.assertIn("Портреты José Luis Narbaiza, выполненные углём и карандашом.", message)
        self.assertIn("Biblioteca Municipal (Hall)", message)


if __name__ == "__main__":
    unittest.main()
