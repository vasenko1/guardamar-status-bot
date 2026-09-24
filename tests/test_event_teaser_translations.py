import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.event_translations import (
    cached_translation,
    prepare_translations,
    reviewed_translation,
)
from telegrambot.gemini import GeminiError


TZ = ZoneInfo("Europe/Madrid")


class ReviewedEventTranslationTests(unittest.TestCase):
    def test_the_miracle_club_titles_have_reviewed_russian_copy(self):
        self.assertEqual(
            reviewed_translation("Cine de los Lunes: El club de los milagros"),
            "Кино по понедельникам: «Клуб чудес»",
        )
        self.assertEqual(
            reviewed_translation(
                "Sesión de cine con la película ‘El club de los milagros’ "
                "en la biblioteca municipal"
            ),
            "Показ фильма «Клуб чудес»",
        )


class EventTeaserTranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_titles_and_teasers_use_separate_translation_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            title_translate = AsyncMock(return_value=["Все мы зовемся Али"])
            teaser_translate = AsyncMock(return_value=[
                "В кафе вдова Эмми знакомится с молодым марокканцем Салемом.",
                "Будут анимация, музыка, бар и подарки.",
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
                        (
                            "municipal_activity_teaser",
                            "Habrá animación, música, barra y regalos.",
                        ),
                    ),
                    path,
                    datetime(2026, 9, 18, 8, 0, tzinfo=TZ),
                )

            self.assertEqual(count, 3)
            title_translate.assert_awaited_once_with(
                "key",
                ["Todos nos llamamos Ali"],
            )
            teaser_translate.assert_awaited_once_with(
                "key",
                [
                    "En un café Emmi conoce a Salem.",
                    "Habrá animación, música, barra y regalos.",
                ],
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
            self.assertEqual(
                cached_translation(
                    path,
                    "municipal_activity_teaser",
                    "Habrá animación, música, barra y regalos.",
                ),
                "Будут анимация, музыка, бар и подарки.",
            )

    async def test_teaser_failure_does_not_block_non_cinema_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            title_translate = AsyncMock(return_value=["Концерт Alpha"])
            teaser_translate = AsyncMock(side_effect=GeminiError("offline"))
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
                        ("municipal_agenda", "Concierto Alpha"),
                        (
                            "municipal_cinema_teaser",
                            "Una descripción suficientemente larga del filme.",
                        ),
                    ),
                    path,
                    datetime(2026, 9, 18, 8, 0, tzinfo=TZ),
                )

            self.assertEqual(count, 1)
            self.assertEqual(
                cached_translation(path, "municipal_agenda", "Concierto Alpha"),
                "Концерт Alpha",
            )
            self.assertIsNone(cached_translation(
                path,
                "municipal_cinema_teaser",
                "Una descripción suficientemente larga del filme.",
            ))

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


    async def test_title_batch_failure_recovers_individual_cache_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            translator = AsyncMock(side_effect=[
                GeminiError("invalid batch"),
                ["Перевод Alpha"],
                GeminiError("invalid single"),
                ["Перевод Gamma"],
            ])
            with patch(
                "telegrambot.event_translations.translate_event_titles",
                new=translator,
            ):
                count = await prepare_translations(
                    "key",
                    (
                        ("municipal_agenda", "Evento Alpha"),
                        ("agenda_guardamar", "Evento Beta"),
                        ("library_agenda", "Evento Gamma"),
                    ),
                    path,
                    datetime(2026, 9, 24, 23, 55, tzinfo=TZ),
                )

            self.assertEqual(count, 2)
            self.assertEqual(translator.await_count, 4)
            self.assertEqual(
                translator.await_args_list[0].args,
                ("key", ["Evento Alpha", "Evento Beta", "Evento Gamma"]),
            )
            self.assertEqual(
                cached_translation(path, "municipal_agenda", "Evento Alpha"),
                "Перевод Alpha",
            )
            self.assertIsNone(
                cached_translation(path, "agenda_guardamar", "Evento Beta")
            )
            self.assertEqual(
                cached_translation(path, "library_agenda", "Evento Gamma"),
                "Перевод Gamma",
            )

    async def test_title_recovery_is_bounded_to_twelve_individual_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            items = tuple(
                ("agenda_guardamar", f"Evento {index}")
                for index in range(14)
            )
            translator = AsyncMock(side_effect=[
                GeminiError("invalid batch"),
                *[[f"Перевод {index}"] for index in range(12)],
            ])
            with patch(
                "telegrambot.event_translations.translate_event_titles",
                new=translator,
            ):
                count = await prepare_translations(
                    "key",
                    items,
                    path,
                    datetime(2026, 9, 24, 23, 55, tzinfo=TZ),
                )

            self.assertEqual(count, 12)
            self.assertEqual(translator.await_count, 13)
            self.assertEqual(
                cached_translation(path, "agenda_guardamar", "Evento 11"),
                "Перевод 11",
            )
            self.assertIsNone(
                cached_translation(path, "agenda_guardamar", "Evento 12")
            )
            self.assertIsNone(
                cached_translation(path, "agenda_guardamar", "Evento 13")
            )


if __name__ == "__main__":
    unittest.main()
