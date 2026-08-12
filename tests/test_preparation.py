import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.aemet_snapshot import load_snapshot, write_snapshot
from telegrambot.branding import FOOTER, with_footer
from telegrambot.digest import build_message
from telegrambot.event_translations import (
    cached_title,
    prepare_translations,
    reviewed_translation,
    spanish_fallback,
)
from telegrambot.models import Event, MorningDigest, Warning, Weather

MADRID = ZoneInfo("Europe/Madrid")


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 4, 7, 15, tzinfo=MADRID)

    def _digest(self):
        return MorningDigest(
            weather=Weather(None, 24, 32, "NE", 7, None),
            warnings=(Warning(
                "Tormentas", "yellow", self.now + timedelta(hours=2),
                self.now - timedelta(hours=1),
            ),),
            warnings_available=True,
        )

    def test_aemet_snapshot_is_same_day_and_age_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aemet.json"
            write_snapshot(path, self._digest(), self.now)
            self.assertIsNotNone(load_snapshot(
                path, self.now + timedelta(minutes=45),
                max_age=timedelta(minutes=60),
            ))
            self.assertIsNone(load_snapshot(
                path, self.now + timedelta(minutes=61),
                max_age=timedelta(minutes=60),
            ))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    async def test_translation_cache_translates_only_missing_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"
            translator = AsyncMock(return_value=["Праздник районов"])
            with patch(
                "telegrambot.event_translations.translate_event_titles",
                translator,
            ):
                first = await prepare_translations(
                    "key", [("municipal", "FIESTAS DE BARRIO")],
                    path, self.now,
                )
                second = await prepare_translations(
                    "key", [("municipal", "FIESTAS DE BARRIO")],
                    path, self.now + timedelta(minutes=30),
                )
            self.assertEqual((first, second), (1, 0))
            translator.assert_awaited_once()
            self.assertEqual(
                cached_title(path, "municipal", "FIESTAS DE BARRIO"),
                "Праздник районов",
            )

    def test_spanish_fallback_only_normalizes_all_caps(self):
        self.assertEqual(
            spanish_fallback("  RUTAS   NOCTURNAS  "),
            "Rutas Nocturnas",
        )
        self.assertEqual(
            spanish_fallback("Memoria de arena"), "Memoria de arena"
        )

    def test_reviewed_current_event_titles_do_not_depend_on_llm(self):
        self.assertEqual(
            reviewed_translation("BALL D’ESTIU"),
            "Летний танцевальный вечер Ball d’Estiu",
        )
        self.assertEqual(
            reviewed_translation(
                "Rutas nocturnas: senderismo y dinámica grupal"
            ),
            "Ночной пешеходный маршрут (8 км) для молодёжи 12–30 лет",
        )
        self.assertEqual(
            reviewed_translation(
                "Exposición de pintura «Luz a pesar del dolor» "
                "de Vira Degliarenko"
            ),
            "Выставка живописи «Свет вопреки боли» — Вира Дегляренко",
        )

    def test_reviewed_title_overrides_empty_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translations.json"

            self.assertEqual(
                cached_title(path, "municipal_agenda", "BALL D’ESTIU"),
                "Летний танцевальный вечер Ball d’Estiu",
            )

    def test_message_can_publish_events_without_weather(self):
        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=False,
            events=(Event("Fiestas de barrio", self.now),),
        ), now=self.now)
        self.assertIn("События дня", message)
        self.assertNotIn("Погода от AEMET", message)

    def test_expired_cached_warning_is_not_rendered(self):
        digest = self._digest()
        message = build_message(
            digest,
            now=self.now + timedelta(hours=3),
        )
        self.assertNotIn("Предупреждения AEMET", message)

    def test_long_event_list_drops_complete_tail_records(self):
        events = tuple(
            Event(
                f"Мероприятие {index} " + "очень длинное название " * 8,
                self.now,
                place="Очень длинное место проведения " * 5,
            )
            for index in range(30)
        )
        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=False,
            events=events,
        ), now=self.now)
        self.assertLessEqual(len(message), 4096)
        self.assertEqual(message.count("📍"), message.count("• "))

    def test_brand_footer_is_appended_exactly_once(self):
        message = with_footer(with_footer("Текст"))
        self.assertEqual(message.count(FOOTER), 1)
        self.assertTrue(message.endswith(FOOTER))

    def test_ticket_row_is_complete_and_html_safe(self):
        event = Event(
            "Экскурсия",
            self.now,
            place="Castillo de Guardamar",
            ticket_price_cents=500,
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/12/tour.html"
                "?webfecha=05/08/2026&webhora=10:00"
            ),
        )

        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=False,
            events=(event,),
        ), now=self.now)

        self.assertIn("🎟", message)
        self.assertIn("Билет 5 €", message)
        self.assertIn("&amp;webhora=10:00", message)

    def test_free_admission_is_compact(self):
        message = build_message(MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=False,
            events=(Event(
                "Actividad familiar",
                self.now,
                ticket_price_cents=0,
            ),),
        ), now=self.now)

        self.assertIn("🎟 Бесплатно", message)


if __name__ == "__main__":
    unittest.main()
