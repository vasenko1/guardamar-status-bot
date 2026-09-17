import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

from telegrambot.branding import FOOTER
from telegrambot.pinned import (
    MUSIC_ACTIVITY_KEYS,
    PINNED_MESSAGE_KEYS,
    PinnedGuideState,
    build_activities,
    build_music_activity,
    build_music_school,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.telegram import TelegramError


CATALOG = {
    "observed_at": "2026-09-17T12:00:00+02:00",
    "season": "2026/27",
    "schedule_url": (
        "https://amguardamar.es/2026/07/15/"
        "horarios-asignaturas-conjuntas-curso-2026-2027/"
    ),
    "jardin_registration": {
        "start": "2026-09-01",
        "end": "2026-09-17",
        "url": "https://cutt.ly/AMG_Matricula_JM_2627",
    },
    "school_registration": {
        "start": "2026-09-01",
        "end": "2026-09-07",
        "url": "https://cutt.ly/AMG_Matricula_EM_2627",
    },
}


class MusicPinnedRenderingTests(unittest.TestCase):
    def test_music_basics_matches_compact_activity_ux(self):
        text = build_music_activity(
            "music_basics",
            CATALOG,
            date(2026, 9, 17),
            activities_link="https://t.me/c/123/7559",
            school_link="https://t.me/c/123/7600",
        )
        self.assertIn("🎶 <b>Музыкальное развитие и грамота</b>", text)
        self.assertIn("• <b>Jardín Musical</b> · 3–6 лет", text)
        self.assertIn("1 час в неделю · занятия Пн–Чт", text)
        self.assertIn("https://cutt.ly/AMG_Matricula_JM_2627", text)
        self.assertIn("• <b>Lenguaje Musical</b> · с 7 лет", text)
        self.assertIn("2 часа в неделю", text)
        self.assertIn("• <b>Lenguaje Musical para Adultos</b> · 18+", text)
        self.assertIn("Расписание групп 2026/27", text)
        self.assertNotIn("drive.google.com", text)
        self.assertEqual(text.count("https://t.me/c/123/7600"), 3)
        self.assertNotIn("966726044", text)
        self.assertNotIn("escuela@amguardamar.es", text)
        self.assertIn("⬅️ <a href=\"https://t.me/c/123/7559\"><b>К занятиям и секциям</b></a>", text)
        self.assertTrue(text.endswith(FOOTER))

    def test_jardin_registration_disappears_after_explicit_deadline(self):
        text = build_music_activity(
            "music_basics", CATALOG, date(2026, 9, 18)
        )
        self.assertNotIn("Записаться", text)
        self.assertIn("📍", text)
        self.assertIn("Escuela de Música", text)

    def test_vocal_and_instruments_keep_contacts_on_school_card_only(self):
        vocal = build_music_activity(
            "music_vocal", CATALOG, date(2026, 9, 17), school_link="https://t.me/c/123/7600"
        )
        instruments = build_music_activity(
            "music_instruments", CATALOG, date(2026, 9, 17), school_link="https://t.me/c/123/7600"
        )
        self.assertIn("Técnica Vocal / Coro", vocal)
        self.assertIn("Расписание групп 2026/27", vocal)
        self.assertIn("Духовые инструменты", instruments)
        self.assertIn("Другие инструменты", instruments)
        for text in (vocal, instruments):
            self.assertNotIn("966726044", text)
            self.assertNotIn("escuela@amguardamar.es", text)
            self.assertIn("Escuela de Música", text)
            self.assertTrue(text.endswith(FOOTER))

    def test_school_card_owns_contacts_map_and_reverse_activity_links(self):
        links = {
            "music_basics": "https://t.me/c/123/7601",
            "music_vocal": "https://t.me/c/123/7602",
            "music_instruments": "https://t.me/c/123/7603",
        }
        text = build_music_school(links, "https://t.me/c/123/7500")
        self.assertIn("🎼 <b>Escuela de Música</b>", text)
        self.assertIn("Открыть на карте", text)
        self.assertIn("<code>966726044</code>", text)
        self.assertIn("<code>escuela@amguardamar.es</code>", text)
        for link in links.values():
            self.assertIn(link, text)
        self.assertIn("⬅️ <a href=\"https://t.me/c/123/7500\"><b>К списку мест</b></a>", text)
        self.assertTrue(text.endswith(FOOTER))

    def test_activities_index_adds_one_visual_music_group(self):
        text = build_activities(
            music_links={
                "music_basics": "https://t.me/c/123/7601",
                "music_vocal": "https://t.me/c/123/7602",
                "music_instruments": "https://t.me/c/123/7603",
            }
        )
        self.assertEqual(text.count("🎵 <b>Музыка</b>"), 1)
        self.assertLess(text.index("Музыкальное развитие и грамота"), text.index("Вокал и хор"))
        self.assertLess(text.index("Вокал и хор"), text.index("Музыкальные инструменты"))
        self.assertTrue(text.endswith(FOOTER))


class MusicPinnedRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_school_card_recreates_and_relinks_music_cards(self):
        chat_id = "-100123"
        messages = {
            key: number for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }
        for offset, key in enumerate(MUSIC_ACTIVITY_KEYS):
            messages[key] = 300 + offset
        deleted_id = messages["music_school"]

        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)

            async def edit(message_id, message):
                if message_id == deleted_id:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                chat_id,
                state,
                AsyncMock(return_value=999),
                edit_mock,
                AsyncMock(),
                music_school_catalog=CATALOG,
                local_day=date(2026, 9, 17),
            )

        self.assertEqual(result["music_school"], 999)
        school_link = telegram_message_link(chat_id, 999)
        for key in MUSIC_ACTIVITY_KEYS:
            rendered = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == result[key]
            ][-1]
            self.assertIn(school_link, rendered)


if __name__ == "__main__":
    unittest.main()
