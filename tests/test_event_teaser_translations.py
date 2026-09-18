import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.event_translations import cached_translation, prepare_translations


TZ = ZoneInfo("Europe/Madrid")


class EventTeaserTranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_titles_and_teasers_use_separate_translation_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            title_translate = AsyncMock(return_value=["Все мы зовемся Али"])
            teaser_translate = AsyncMock(return_value=[
                "В кафе вдова Эмми знакомится с молодым марокканцем Салемом."
            ])
            with (
                patch(
                    "telegrambot.event_translations.translate_event_titles",
                    new=title_translate,
                ),
                patch(
                    "telegrambot.event_translations.translate_event_teasers",
                    new=teaser_translate,
                ),
            ):
                count = await prepare_translations(
                    "key",
                    (
                        ("municipal_agenda", "Todos nos llamamos Ali"),
                        (
                            "municipal_cinema_teaser",
                            "En un café Emmi conoce a Salem.",
                        ),
                    ),
                    path,
                    datetime(2026, 9, 18, 8, 0, tzinfo=TZ),
                )

            self.assertEqual(count, 2)
            title_translate.assert_awaited_once_with(
                "key",
                ["Todos nos llamamos Ali"],
            )
            teaser_translate.assert_awaited_once_with(
                "key",
                ["En un café Emmi conoce a Salem."],
            )
            self.assertEqual(
                cached_translation(
                    path,
                    "municipal_agenda",
                    "Todos nos llamamos Ali",
                ),
                "Все мы зовемся Али",
            )
            self.assertEqual(
                cached_translation(
                    path,
                    "municipal_cinema_teaser",
                    "En un café Emmi conoce a Salem.",
                ),
                "В кафе вдова Эмми знакомится с молодым марокканцем Салемом.",
            )

    async def test_cached_teaser_is_not_retranslated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            teaser = "Una mujer conoce a un hombre."
            translator = AsyncMock(return_value=["Женщина знакомится с мужчиной."])
            with patch(
                "telegrambot.event_translations.translate_event_teasers",
                new=translator,
            ):
                await prepare_translations(
                    "key",
                    (("municipal_cinema_teaser", teaser),),
                    path,
                    datetime(2026, 9, 18, 8, 0, tzinfo=TZ),
                )
                await prepare_translations(
                    "key",
                    (("municipal_cinema_teaser", teaser),),
                    path,
                    datetime(2026, 9, 18, 9, 0, tzinfo=TZ),
                )
            self.assertEqual(translator.await_count, 1)


if __name__ == "__main__":
    unittest.main()
