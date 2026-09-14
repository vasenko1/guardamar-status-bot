import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.environment_updates import (
    build_environment_update,
    build_meteosalud_update,
)
from telegrambot.models import AirQualitySummary, PollenSummary


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 14, 10, 25, tzinfo=MADRID)


class EnvironmentUpdateTests(unittest.TestCase):
    def test_same_air_category_is_silent_even_if_pollutants_change(self):
        old = AirQualitySummary(("PM10",), "днём", category=3)
        new = AirQualitySummary(("PM2.5",), "во второй половине дня", category=3)
        self.assertIsNone(build_environment_update(old, new, None, None, NOW))

    def test_air_worsening_lists_multiple_pollutants_and_attribution(self):
        new = AirQualitySummary(
            ("PM10", "PM2.5", "NO₂"),
            "во второй половине дня",
            dust_related=True,
            category=4,
        )
        message = build_environment_update(None, new, None, None, NOW)
        self.assertIn("PM10, PM2.5 и NO₂", message)
        self.assertIn("Возможно влияние переносимой пыли", message)
        self.assertIn("CAMS / Copernicus, 2026", message)
        self.assertNotIn("guardamar-cams-data", message)
        self.assertNotIn("дыма от пожаров", message)

    def test_air_clearing_is_silent_after_old_period_ended(self):
        old = AirQualitySummary(("NO₂",), "утром", category=3)
        afternoon = NOW.replace(hour=13)
        self.assertIsNone(
            build_environment_update(old, None, None, None, afternoon)
        )

    def test_air_clearing_before_period_end_is_published(self):
        old = AirQualitySummary(("PM10",), "днём", category=3)
        message = build_environment_update(old, None, None, None, NOW)
        self.assertIn("С воздухом стало лучше", message)
        self.assertIn("больше не прогнозируется", message)

    def test_pollen_period_only_change_is_silent(self):
        old = PollenSummary(("оливы",), "днём")
        new = PollenSummary(("оливы",), "во второй половине дня")
        self.assertIsNone(build_environment_update(None, None, old, new, NOW))

    def test_ragweed_is_presence_only(self):
        pollen = PollenSummary((), None, True, "во второй половине дня")
        message = build_environment_update(None, None, None, pollen, NOW)
        self.assertIn("Амброзия ожидается", message)
        self.assertNotIn("высокий уровень амброзии", message.casefold())

    def test_air_and_pollen_are_combined_into_one_message(self):
        air = AirQualitySummary(("PM10",), "днём", category=3)
        pollen = PollenSummary(("оливы",), "днём")
        message = build_environment_update(None, air, None, pollen, NOW)
        self.assertIn("Есть пара уточнений", message)
        self.assertIn("PM10", message)
        self.assertIn("оливы", message)
        self.assertEqual(message.count("CAMS / Copernicus"), 1)

    def test_new_author_messages_have_no_em_dash(self):
        air = AirQualitySummary(("PM10", "PM2.5"), "днём", category=3)
        pollen = PollenSummary(("оливы",), "днём")
        messages = (
            build_environment_update(None, air, None, pollen, NOW),
            build_meteosalud_update(2, None, NOW),
            build_meteosalud_update(None, 2, NOW),
        )
        self.assertTrue(all("\u2014" not in message for message in messages))

    def test_meteosalud_zero_is_silent_and_risk_is_compact(self):
        self.assertIsNone(build_meteosalud_update(0, 0, NOW))
        message = build_meteosalud_update(2, None, NOW)
        self.assertIn("средний риск жары", message)
        self.assertIn("Ministerio de Sanidad", message)


if __name__ == "__main__":
    unittest.main()
