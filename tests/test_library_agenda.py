import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.digest import build_message
from telegrambot.library_agenda import (
    LibraryAgendaError,
    _LibraryRecord,
    _write_snapshot,
    extract_events,
    extract_teaser,
    fetch_today_library_events,
)
from telegrambot.models import MorningDigest


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 9, 7, 30, tzinfo=TZ)
LIST = b'''<div class="registro pagina1"><div class="row actividades">
<div class="list-info"><span class="fecha"><h4>
7 de septiembre - 23 de septiembre de 2026</h4></span></div>
<div class="list-desc"><img src="/poster.jpg"><a href="/Bibliotecas/guardamardelsegura/actividades-programas/Agenda-de-actividades/exposicion-dibujos.html"><li class="titulo"><h3>Exposici\xc3\xb3n de dibujos de Jos\xc3\xa9 Luis Narbaiza: Amigos y conocidos</h3></li></a></div>
<div class="list-opc"><li>Hall de la Biblioteca P\xc3\xbablica Municipal</li></div>
</div></div>'''
SINGLE = b'''<div class="registro pagina1"><div class="row actividades">
<div class="list-info"><span class="fecha"><h4>Lunes, 14 de septiembre de 2026</h4></span><span class="hora"><h4>18:00 - 20:00</h4></span></div>
<div class="list-desc"><a href="/Bibliotecas/guardamardelsegura/actividades-programas/Agenda-de-actividades/El-cine-de-los-lunes.html"><li class="titulo"><h3>El cine de los lunes: Respect: su voz lo cambi\xc3\xb3 todo</h3></li></a></div>
<div class="list-opc"><li>Biblioteca P\xc3\xbablica Municipal</li></div>
</div></div>'''
DETAIL = b'''<div class="column detalle"><p>Esta colecci\xc3\xb3n re\xc3\xbane una selecci\xc3\xb3n de retratos realizados por Jos\xc3\xa9 Luis Narbaiza, pintor amateur con un especial dominio del dibujo a carboncillo y a l\xc3\xa1piz.<br />Otra frase.</p></div>'''
DETAIL_TWO = b'''<div class="column detalle"><p>Esta exposici\xc3\xb3n presenta una segunda colecci\xc3\xb3n de obras locales.</p></div>'''
SECOND_ACTIVE = b'''<div class="registro pagina1"><div class="row actividades">
<div class="list-info"><span class="fecha"><h4>8 de septiembre - 24 de septiembre de 2026</h4></span></div>
<div class="list-desc"><a href="/Bibliotecas/guardamardelsegura/actividades-programas/Agenda-de-actividades/segunda.html"><li class="titulo"><h3>Segunda exposici\xc3\xb3n</h3></li></a></div>
<div class="list-opc"><li>Biblioteca P\xc3\xbablica Municipal</li></div>
</div></div>'''


class LibraryAgendaTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_active_exhibition_from_list(self):
        records = extract_events(LIST, NOW)
        event, link = records[0]
        self.assertEqual(len(records), 1)
        self.assertEqual(event.active_until.isoformat(), "2026-09-23")
        self.assertEqual(event.place, "Hall de la Biblioteca P\xfablica Municipal")
        self.assertTrue(link.endswith("exposicion-dibujos.html"))

    def test_extracts_single_date_time_and_absolute_detail_url(self):
        event, link = extract_events(SINGLE, NOW)[0]

        self.assertEqual(event.title, "El cine de los lunes: Respect: su voz lo cambi\xf3 todo")
        self.assertEqual(event.starts_at.isoformat(), "2026-09-14T18:00:00+02:00")
        self.assertEqual(event.ends_at.isoformat(), "2026-09-14T20:00:00+02:00")
        self.assertEqual(event.place, "Biblioteca P\xfablica Municipal")
        self.assertEqual(
            link,
            "https://www.bibliotecaspublicas.es/Bibliotecas/guardamardelsegura/"
            "actividades-programas/Agenda-de-actividades/El-cine-de-los-lunes.html",
        )

    def test_omits_finished_range_but_keeps_range_already_started(self):
        self.assertEqual(len(extract_events(LIST, NOW)), 1)
        finished = datetime(2026, 9, 24, 7, 30, tzinfo=TZ)
        self.assertEqual(extract_events(LIST, finished), ())

    async def test_new_future_event_reads_its_detail_immediately(self):
        from telegrambot.library_agenda import refresh_library_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            with patch(
                "telegrambot.library_agenda._read_page",
                side_effect=[SINGLE, DETAIL],
            ) as read_page:
                events = await refresh_library_catalog(NOW, path)

        self.assertEqual(len(events), 1)
        self.assertEqual(read_page.call_count, 2)
        self.assertIsNotNone(events[0].teaser)

    async def test_new_events_each_read_a_detail_but_unchanged_events_do_not(self):
        from telegrambot.library_agenda import refresh_library_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            with patch(
                "telegrambot.library_agenda._read_page",
                side_effect=[LIST + SECOND_ACTIVE, DETAIL, DETAIL_TWO, LIST + SECOND_ACTIVE],
            ) as read_page:
                first = await refresh_library_catalog(NOW, path)
                second = await refresh_library_catalog(NOW, path)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(read_page.call_count, 4)
        self.assertEqual(first[0].teaser, extract_teaser(DETAIL))
        self.assertEqual(first[1].teaser, extract_teaser(DETAIL_TWO))

    async def test_changed_card_and_failed_detail_are_retried_without_losing_events(self):
        from telegrambot.library_agenda import refresh_library_catalog

        changed = LIST.replace(b"Amigos y conocidos", b"Amigos y familia")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            with patch(
                "telegrambot.library_agenda._read_page",
                side_effect=[
                    LIST,
                    DETAIL,
                    changed,
                    DETAIL_TWO,
                    LIST,
                    LibraryAgendaError("offline"),
                    LIST,
                    DETAIL,
                ],
            ) as read_page:
                first = await refresh_library_catalog(NOW, path)
                changed_events = await refresh_library_catalog(NOW, path)
                retained_after_failure = await refresh_library_catalog(NOW, path)
                retried = await refresh_library_catalog(NOW, path)

        self.assertEqual(len(first), 1)
        self.assertEqual(changed_events[0].title, "Exposición de dibujos de José Luis Narbaiza: Amigos y familia")
        self.assertEqual(changed_events[0].teaser, extract_teaser(DETAIL_TWO))
        self.assertEqual(len(retained_after_failure), 1)
        self.assertIsNone(retained_after_failure[0].teaser)
        self.assertEqual(retried[0].teaser, extract_teaser(DETAIL))
        self.assertEqual(read_page.call_count, 8)

    async def test_one_failed_new_detail_does_not_block_another_new_event(self):
        from telegrambot.library_agenda import refresh_library_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            with patch(
                "telegrambot.library_agenda._read_page",
                side_effect=[
                    LIST + SECOND_ACTIVE,
                    LibraryAgendaError("offline"),
                    DETAIL_TWO,
                ],
            ):
                events = await refresh_library_catalog(NOW, path)

        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0].teaser)
        self.assertEqual(events[1].teaser, extract_teaser(DETAIL_TWO))

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
            _write_snapshot(path, NOW, (_LibraryRecord(
                event,
                "https://www.bibliotecaspublicas.es/Bibliotecas/guardamardelsegura/"
                "actividades-programas/Agenda-de-actividades/exposicion-dibujos.html",
                True,
            ),))
            events = await fetch_today_library_events(NOW, path, translations)

        message = build_message(MorningDigest(
            weather=None, warnings=(), warnings_available=False, events=events
        ), now=NOW)
        self.assertIn("Выставка рисунков José Luis Narbaiza", message)
        self.assertIn("Портреты José Luis Narbaiza, выполненные углём и карандашом.", message)
        self.assertIn("Biblioteca Municipal (Hall)", message)


if __name__ == "__main__":
    unittest.main()
