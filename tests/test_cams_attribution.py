import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.digest import _cams_attribution as morning_attribution
from telegrambot.environment_updates import _cams_attribution as update_attribution


MADRID = ZoneInfo("Europe/Madrid")


class CamsAttributionTests(unittest.TestCase):
    def test_morning_attribution_uses_processed_for_guardamar_wording(self):
        message = morning_attribution(2026)
        self.assertIn("Источник: <a href=", message)
        self.assertIn(
            "данные CAMS (Copernicus), обработанные для Гуардамара, 2026",
            message,
        )
        self.assertIn(
            "ЕС и ECMWF не несут ответственности за их использование.", message
        )
        self.assertNotIn("Изменённые данные", message)

    def test_late_update_attribution_matches_morning_wording(self):
        message = update_attribution(
            datetime(2026, 9, 17, 10, 30, tzinfo=MADRID)
        )
        self.assertIn(
            "Источник: данные CAMS (Copernicus), обработанные для Гуардамара, 2026",
            message,
        )
        self.assertIn(
            "ЕС и ECMWF не несут ответственности за их использование.", message
        )
        self.assertNotIn("Изменённые данные", message)


if __name__ == "__main__":
    unittest.main()
