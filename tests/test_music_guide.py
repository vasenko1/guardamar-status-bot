import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.music_school import (
    SCHOOL_EMAIL,
    SCHOOL_MAP_URL,
    SCHOOL_PHONE,
)
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


MADRID = ZoneInfo("Europe/Madrid")
SCHEDULE_URL = (
    "https://amguardamar.es/2026/07/15/"
    "horarios-asignaturas-conjuntas-curso-2026-2027/"
)
JARDIN_FORM = "https://cutt.ly/AMG_Matricula_JM_2627"


def _catalog():
    return {
        "observed_at": datetime(2026, 9, 17, 16, 30, tzinfo=MADRID).isoformat(),
        "season": "2026/27",
        "schedule_url": SCHEDULE_URL,
        "jardin_registration": {
            "start": "2026-09-01",
            "end": "2026-09-17",
            "url": JARDIN_FORM,
        },
        "school_registration": {
            "start": "2026-09-01",
            "end": "2026-09-07",
            "url": "https://cutt.ly/AMG_Matricula_EM_2627",
        },
    }


def _messages():
    result = {
        key: number
        for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
    }
    for offset, key in enumerate(MUSIC_ACTIVITY_KEYS):
        result[key] = 300 + offset
    return result


def _last_edit(edit_mock, message_id):
    matches = [
        call.args[1]
        for call in edit_mock.await_args_list
        if call.args[0] == message_id
    ]
    return matches[-1]


class MusicCardUxTests(unittest.TestCase):
    def test_basics_matches_existing_activity_card_rhythm(self):
        school_link = "https://t.me/c/123/90"
        activities_link = "https://t.me/c/123/91"
        text = build_music_activity(
            "music_basics",
            _catalog(),
            date(2026, 9, 17),
            activities_link,
            school_link,
        )

        self.assertIn("🎶 <b>Музыкальное развитие и грамота</b>", text)
        self.assertIn("• <b>Jardín Musical</b> · 3–6 лет", text)
        self.assertIn("1 час в неделю · занятия Пн–Чт", text)
        self.assertIn(JARDIN_FORM, text)
        self.assertIn("• <b>Lenguaje Musical</b> · с 7 лет", text)
        self.assertIn("2 часа в неделю", text)
        self.assertIn("• <b>Lenguaje Musical para Adultos</b> · 18+", text)
        self.assertIn(SCHEDULE_URL, text)
        self.assertNotIn("drive.google.com", text)
        self.assertGreaterEqual(text.count(school_link), 3)
        self.assertNotIn(SCHOOL_PHONE, text)
        self.assertNotIn(SCHOOL_EMAIL, text)
        self.assertIn(f'href="{activities_link}"', text)
        self.assertTrue(text.endswith(FOOTER))

    def test_expired_jardin_registration_disappears_without_negative_status(self):
        text = build_music_activity(
            "music_basics",
            _catalog(),
            date(2026, 9, 18),
            "https://t.me/c/123/91",
            "https://t.me/c/123/90",
        )
        self.assertNotIn(JARDIN_FORM, text)
        self.assertNotIn("закрыт", text.casefold())
        self.assertNotIn("закрыта", text.casefold())
        self.assertIn("📍", text)

    def test_vocal_and_instruments_stay_compact_and_do_not_invent_schedule(self):
        vocal = build_music_activity(
            "music_vocal",
            _catalog(),
            date(2026, 9, 17),
            None,
            "https://t.me/c/123/90",
        )
        instruments = build_music_activity(
            "music_instruments",
            _catalog(),
            date(2026, 9, 17),
            None,
            "https://t.me/c/123/90",
        )

        self.assertIn("Técnica Vocal / Coro", vocal)
        self.assertIn(SCHEDULE_URL, vocal)
        self.assertIn("Духовые инструменты", instruments)
        self.assertIn("деревянные · медные", instruments)
        self.assertIn(
            "ударные · дульсайна · виолончель · гитара · Piano Complementario",
            instruments,
        )
        self.assertNotIn(SCHEDULE_URL, instruments)
        self.assertNotIn("30–45", instruments)
        self.assertNotIn(SCHOOL_PHONE, vocal + instruments)

    def test_school_card_owns_contacts_map_and_reverse_activity_links(self):
        links = {
            "music_basics": "https://t.me/c/123/101",
            "music_vocal": "https://t.me/c/123/102",
            "music_instruments": "https://t.me/c/123/103",
        }
        text = build_music_school(links, "https://t.me/c/123/50")

        self.assertIn(SCHOOL_MAP_URL.replace("&", "&amp;"), text)
        self.assertIn(f"<code>{SCHOOL_PHONE}</code>", text)
        self.assertIn(f"<code>{SCHOOL_EMAIL}</code>", text)
        for link in links.values():
            self.assertIn(link, text)
        self.assertIn("К списку мест", text)
        self.assertTrue(text.endswith(FOOTER))

    def test_activity_index_adds_one_visual_music_section(self):
        links = {
            "music_basics": "https://t.me/c/123/101",
            "music_vocal": "https://t.me/c/123/102",
            "music_instruments": "https://t.me/c/123/103",
        }
        text = build_activities(
            swimming_link="https://t.me/c/123/10",
            root_link="https://t.me/c/123/1",
            football_link="https://t.me/c/123/11",
            music_links=links,
        )
        self.assertEqual(text.count("🎵 <b>Музыка</b>"), 1)
        self.assertLess(text.index("⚽"), text.index("🎵 <b>Музыка</b>"))
        for link in links.values():
            self.assertIn(link, text)
        self.assertIn("⬅️", text)
        self.assertTrue(text.endswith(FOOTER))


class MusicGuideRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def _publish_with_deleted(self, key, replacement):
        chat_id = "-100123"
        messages = _messages()
        deleted_id = messages[key]
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)

            async def edit(message_id, message):
                if message_id == deleted_id:
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
                AsyncMock(return_value=replacement),
                edit_mock,
                AsyncMock(),
                music_school_catalog=_catalog(),
                local_day=date(2026, 9, 17),
            )
        return chat_id, result, edit_mock

    async def test_deleted_music_activity_relinks_index_and_school(self):
        chat_id, result, edit = await self._publish_with_deleted(
            "music_basics", 990
        )
        link = telegram_message_link(chat_id, 990)
        self.assertEqual(result["music_basics"], 990)
        self.assertIn(link, _last_edit(edit, result["activities"]))
        self.assertIn(link, _last_edit(edit, result["music_school"]))

    async def test_deleted_music_school_relinks_all_music_cards_and_places(self):
        chat_id, result, edit = await self._publish_with_deleted(
            "music_school", 991
        )
        link = telegram_message_link(chat_id, 991)
        self.assertEqual(result["music_school"], 991)
        self.assertIn(link, _last_edit(edit, result["places"]))
        for key in MUSIC_ACTIVITY_KEYS:
            self.assertIn(link, _last_edit(edit, result[key]))


if __name__ == "__main__":
    unittest.main()
