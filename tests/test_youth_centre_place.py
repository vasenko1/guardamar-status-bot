import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from telegrambot.branding import FOOTER
from telegrambot.pinned import (
    PINNED_MESSAGE_KEYS,
    PINNED_PARENT_KEYS,
    PinnedGuideState,
    YOUTH_CENTRE_MAP_URL,
    _render_messages,
    build_places,
    build_youth_centre,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.telegram import TelegramError


class YouthCentreContentTests(unittest.TestCase):
    def test_places_links_to_youth_centre(self):
        youth_link = "https://t.me/c/1/40"
        places = build_places(
            "https://t.me/c/1/30",
            "https://t.me/c/1/20",
            youth_link,
        )

        self.assertIn("Centro Social Juvenil", places)
        self.assertIn(youth_link, places)
        self.assertIn("Пространство для подростков и молодёжи", places)

    def test_youth_centre_card_is_inclusive_bounded_and_sourced(self):
        places_link = "https://t.me/c/1/30"
        message = build_youth_centre(places_link)

        self.assertLessEqual(len(message), 4096)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertIn("Пространство для подростков и молодёжи", message)
        self.assertIn("12 до 30 лет", message)
        self.assertNotIn("для ребят", message)
        self.assertIn("Режим работы в сентябре 2026", message)
        for hours in (
            "Пн–Пт: 08:30–14:00",
            "Ср–Чт: 17:00–21:00",
            "Пт: 17:00–22:00",
            "Сб: 17:00–22:00",
        ):
            self.assertIn(hours, message)
        self.assertIn(YOUTH_CENTRE_MAP_URL, message)
        self.assertIn("Открыть на карте", message)
        self.assertNotIn("Calle Molivent", message)
        self.assertNotIn("Agenda municipal", message)
        self.assertIn("<code>609006754</code>", message)
        self.assertIn("<code>juventudguardamar@gmail.com</code>", message)
        self.assertNotIn("96 535 71 91", message)
        self.assertNotIn("96 562 97 51", message)
        self.assertIn(places_link, message)
        self.assertIn("⬅️", message)
        self.assertIn("К списку мест", message)

    def test_youth_centre_is_a_managed_child_of_places(self):
        self.assertIn("youth_centre", PINNED_MESSAGE_KEYS)
        self.assertEqual(PINNED_PARENT_KEYS["youth_centre"], "places")

        chat_id = "-100123"
        messages = {
            key: number
            for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }
        rendered = _render_messages(chat_id, messages)

        self.assertIn(
            telegram_message_link(chat_id, messages["youth_centre"]),
            rendered["places"],
        )
        self.assertIn(
            telegram_message_link(chat_id, messages["places"]),
            rendered["youth_centre"],
        )


class YouthCentreRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recreated_youth_centre_rewrites_places_link(self):
        chat_id = "-100123"
        messages = {
            key: number
            for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }
        old_youth = messages["youth_centre"]

        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)

            async def edit(message_id, message):
                if message_id == old_youth:
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
                AsyncMock(return_value=99),
                edit_mock,
                AsyncMock(),
            )

        self.assertEqual(result["youth_centre"], 99)
        youth_link = telegram_message_link(chat_id, 99)
        place_edits = [
            call.args[1]
            for call in edit_mock.await_args_list
            if call.args[0] == messages["places"]
        ]
        self.assertIn(youth_link, place_edits[-1])


if __name__ == "__main__":
    unittest.main()
