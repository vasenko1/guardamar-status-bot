import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.chess_school import (
    _extract_snapshot as extract_chess,
    valid_chess_school_snapshot,
)
from telegrambot.dinamizacion import (
    _campaign_from_feed,
    _extract_snapshot as extract_dinamizacion,
    _form_link,
    refresh_dinamizacion_snapshot,
    valid_dinamizacion_snapshot,
)
from telegrambot.literary_group import (
    _extract_snapshot as extract_literary,
    valid_literary_group_snapshot,
)
from telegrambot.pinned import (
    PINNED_MESSAGE_KEYS,
    PinnedGuideState,
    build_activities,
    build_chess_activity,
    build_dinamizacion_activity,
    build_literary_activity,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 18, 16, 30, tzinfo=MADRID)
CAMPAIGN = (
    "https://www.guardamardelsegura.es/2026/09/07/"
    "programa-dinamizacion-social-2026-2027/"
)
FORM = "https://docs.google.com/forms/d/e/test/viewform"


def _chess_snapshot():
    payload = """
    <html><body>
    <p>la actividad de la ESCUELA DE AJEDREZ, que dirige PROMOCHESS ESPAÑA,
    es todos los martes y jueves en horario de 16:00 a 20:00 horas,
    por niveles: INICIACIÓN – AVANZADO, para lo que hay que contactar.</p>
    </body></html>
    """.encode("utf-8")
    return extract_chess(payload, NOW)


def _literary_snapshot():
    payload = (
        "<html><body>Tertulia Literaria de Guardamar. "
        "Todos los martes de 11:00 a 13:00 en el salón de actos "
        "de la Biblioteca Pública Municipal.</body></html>"
    ).encode("utf-8")
    return extract_literary(payload, NOW)


def _form_payload():
    return """
    <html><body>
    <h1>INSCRIPCIÓN AL PROGRAMA DE DINAMIZACIÓN SOCIAL. 2026-2027</h1>
    <div>PLAZO DE INSCRIPCIÓN: del 9 al 16 de septiembre de 2026</div>
    <div>Si quedan plazas libres al finalizar el plazo, la inscripción continuará abierta hasta completarlas.</div>
    <div>Si no consta en el padrón municipal de Guardamar del Segura, podrá participar únicamente si quedan plazas disponibles.</div>
    <span>2h/semana. MOVIMIENTO CONSCIENTE. Grupo 1: lunes y miércoles, 11:15–12:15 h</span>
    <span>2h/semana. MOVIMIENTO CONSCIENTE. Grupo 2: lunes y miércoles, 12:15–13:15 h</span>
    <span>2h/semana. USO DEL MOVIL. Grupo 1: martes y jueves. 9:30 a 10:30 h. (a partir del 10 de noviembre)</span>
    <span>2h/semana. USO DEL MOVIL. Grupo 2: martes y jueves. 10:30 a 11:30 h. (a partir del 10 de noviembre)</span>
    <span>4h/semana. ARTE RECICLADO CREATIVO. Lunes y miércoles de 16:30 a 18:30h.</span>
    <span>2h/semana. PINTURA TEXTIL — Viernes, 16:30–18:30 h</span>
    <span>3h/semana. SENDERISMO para MAYORES — Grupo 1: lunes y miércoles, 16:00–17:30 h</span>
    <span>3h/semana. SENDERISMO para MAYORES — Grupo 2: lunes y miércoles, 17:30–19:00 h</span>
    <span>3h/semana. MEMORIA para MAYORES — Grupo 1: martes y jueves, 16:30–18:00 h</span>
    <span>3h/semana. MEMORIA para MAYORES — Grupo 2: martes y jueves, 18:00–19:30 h</span>
    <span>2h/semana. INFORMÁTICA para MAYORES — Grupo 1: lunes y miércoles, 17:00–18:00 h</span>
    <span>2h/semana. INFORMÁTICA para MAYORES — Grupo 2: lunes y miércoles, 18:00–19:00 h</span>
    <span>1 h 30 min/semana. ESCUELA DE EMOCIONES — Miércoles 9:30–11:00 h (14 oct - 16 dic 2026).</span>
    <div>¿Quiere indicarnos alguna observación?</div>
    </body></html>
    """.encode("utf-8")


def _dinamizacion_snapshot():
    return extract_dinamizacion(_form_payload(), CAMPAIGN, FORM, "2026/27", NOW)


class SourceParserTests(unittest.TestCase):
    def test_chess_extracts_current_schedule_and_levels(self):
        snapshot = _chess_snapshot()
        self.assertTrue(valid_chess_school_snapshot(snapshot))
        self.assertEqual(snapshot["start_time"], "16:00")
        self.assertEqual(snapshot["end_time"], "20:00")
        self.assertEqual(snapshot["level_from"], "INICIACIÓN")
        self.assertEqual(snapshot["level_to"], "AVANZADO")

    def test_literary_extracts_weekly_schedule(self):
        snapshot = _literary_snapshot()
        self.assertTrue(valid_literary_group_snapshot(snapshot))
        self.assertEqual(snapshot["day"], "tuesday")
        self.assertEqual(snapshot["start_time"], "11:00")
        self.assertEqual(snapshot["end_time"], "13:00")

    def test_rss_discovers_latest_dinamizacion_campaign(self):
        payload = f"""
        <rss><channel>
          <item><title>Otra noticia</title><link>https://www.guardamardelsegura.es/other/</link></item>
          <item>
            <title>PROGRAMA DINAMIZACIÓN SOCIAL 2026 / 2027</title>
            <link>{CAMPAIGN}</link>
          </item>
        </channel></rss>
        """.encode("utf-8")
        self.assertEqual(
            _campaign_from_feed(payload),
            (CAMPAIGN, "2026/27"),
        )

    def test_detail_requires_one_google_form_link(self):
        detail = (
            f'<html><a href="{FORM}">Inscripción online</a></html>'
        ).encode("utf-8")
        self.assertEqual(_form_link(detail, CAMPAIGN), FORM)

    def test_dinamizacion_normalizes_all_current_groups(self):
        snapshot = _dinamizacion_snapshot()
        self.assertTrue(valid_dinamizacion_snapshot(snapshot))
        self.assertEqual(snapshot["registration_start"], "2026-09-09")
        self.assertEqual(snapshot["registration_end"], "2026-09-16")
        self.assertTrue(snapshot["registration_until_full"])
        self.assertTrue(snapshot["resident_priority"])
        self.assertEqual(len(snapshot["groups"]), 8)
        mobile = next(item for item in snapshot["groups"] if item["key"] == "mobile")
        self.assertEqual(mobile["start_date"], "2026-11-10")
        self.assertEqual(
            mobile["schedules"],
            ["Вт/Чт · 09:30–10:30", "Вт/Чт · 10:30–11:30"],
        )
        emotions = next(
            item for item in snapshot["groups"]
            if item["key"] == "emotions_school"
        )
        self.assertEqual(emotions["start_date"], "2026-10-14")
        self.assertEqual(emotions["end_date"], "2026-12-16")


class DinamizacionRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_reads_known_form_directly(self):
        previous = _dinamizacion_snapshot()
        later = NOW.replace(hour=17)
        with patch(
            "telegrambot.dinamizacion._fetch",
            return_value=_form_payload(),
        ) as fetch:
            refreshed = await refresh_dinamizacion_snapshot(previous, later)

        self.assertTrue(valid_dinamizacion_snapshot(refreshed))
        self.assertEqual(refreshed["observed_at"], later.isoformat())
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], FORM)


class CardRenderingTests(unittest.TestCase):
    def test_activity_index_adds_one_compact_recurring_section(self):
        text = build_activities(
            recurring_links={
                "chess": "https://t.me/c/123/201",
                "literary_group": "https://t.me/c/123/202",
                "dinamizacion": "https://t.me/c/123/203",
            }
        )
        self.assertIn("🧩 <b>Другие занятия</b>", text)
        self.assertIn("Шахматы", text)
        self.assertIn("Литературное творчество", text)
        self.assertIn("Муниципальные занятия и мастерские", text)

    def test_chess_card_is_compact_and_does_not_advertise_provider(self):
        text = build_chess_activity(_chess_snapshot())
        self.assertIn("Вторник и четверг · 16:00–20:00", text)
        self.assertIn("Информация о занятиях", text)
        self.assertNotIn("606742956", text)
        self.assertNotIn("PROMOCHESS", text)

    def test_literary_card_uses_only_published_schedule(self):
        text = build_literary_activity(_literary_snapshot())
        self.assertIn("Каждый вторник · 11:00–13:00", text)
        self.assertNotIn("бесплат", text.casefold())
        self.assertNotIn("регистра", text.casefold())

    def test_dinamizacion_card_uses_post_deadline_cautious_wording(self):
        text = build_dinamizacion_activity(
            _dinamizacion_snapshot(),
            date(2026, 9, 18),
        )
        self.assertIn("Основной период записи завершился 16 сентября.", text)
        self.assertIn(
            "запись может продолжаться, пока остаются места",
            text,
        )
        self.assertNotIn("места есть", text.casefold())
        self.assertIn("Приоритет — жителям Guardamar.", text)
        self.assertIn("С 10 ноября", text)
        self.assertIn("14 октября — 16 декабря", text)
        self.assertLessEqual(len(text), 4096)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_chess_card_is_recreated_and_index_relinked(self):
        chat_id = "-100123"
        messages = {
            key: number
            for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }
        messages["chess"] = 500
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)

            async def edit(message_id, text):
                if message_id == 500:
                    raise TelegramError(
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    )

            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                chat_id,
                state,
                AsyncMock(return_value=999),
                edit_mock,
                AsyncMock(),
                chess_school_snapshot=_chess_snapshot(),
                local_day=date(2026, 9, 18),
            )

        self.assertEqual(result["chess"], 999)
        new_link = telegram_message_link(chat_id, 999)
        index_edits = [
            call.args[1]
            for call in edit_mock.await_args_list
            if call.args[0] == result["activities"]
        ]
        self.assertTrue(index_edits)
        self.assertIn(new_link, index_edits[-1])


if __name__ == "__main__":
    unittest.main()
