import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.digest import build_warning_section
from telegrambot.models import Warning

MADRID = ZoneInfo("Europe/Madrid")


class AemetMorningWarningUxTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 17, 7, 0, tzinfo=MADRID)
        self.start = datetime(2026, 9, 17, 3, 0, tzinfo=MADRID)
        self.end = datetime(2026, 9, 17, 14, 59, tzinfo=MADRID)

    def _warning(
        self,
        event,
        *,
        code=None,
        value=None,
        description=None,
        level="orange",
        starts_at=None,
        ends_at=None,
        probability="40–70%",
    ):
        return Warning(
            event=event,
            level=level,
            starts_at=starts_at or self.start,
            ends_at=ends_at or self.end,
            description=description,
            probability=probability,
            parameter_code=code,
            parameter_value=value,
            parameter_unit="mm" if code in {"P1", "P2"} else None,
        )

    def test_p1_p2_and_storm_share_one_period_without_duplicate_rain(self):
        message = build_warning_section(
            (
                self._warning(
                    "Lluvias",
                    code="P1",
                    value=60,
                    description="Precipitación acumulada en una hora: 60 mm.",
                ),
                self._warning(
                    "Lluvias",
                    code="P2",
                    value=120,
                    description="Precipitación acumulada en 12 horas: 120 mm.",
                ),
                self._warning("Tormentas"),
            ),
            self.now,
        )

        self.assertEqual(message.count("<b>Сегодня · 03:00–14:59</b>"), 1)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 1)
        self.assertEqual(message.count("<b>Грозы</b>"), 1)
        self.assertEqual(message.count("Вероятность: 40–70%"), 1)
        self.assertIn("60 л/м² за 1 час", message)
        self.assertIn("120 л/м² за 12 часов", message)
        self.assertNotIn("Precipitación acumulada", message)

    def test_different_periods_are_not_merged(self):
        later_start = datetime(2026, 9, 17, 15, 0, tzinfo=MADRID)
        later_end = datetime(2026, 9, 17, 19, 59, tzinfo=MADRID)
        message = build_warning_section(
            (
                self._warning("Lluvias", code="P1", value=60),
                self._warning(
                    "Lluvias",
                    code="P1",
                    value=30,
                    level="yellow",
                    starts_at=later_start,
                    ends_at=later_end,
                ),
            ),
            self.now,
        )

        self.assertIn("🟠 <b>Сегодня · 03:00–14:59</b>", message)
        self.assertIn("🟡 <b>Сегодня · 15:00–19:59</b>", message)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 2)

    def test_different_probabilities_are_not_merged(self):
        message = build_warning_section(
            (
                self._warning("Lluvias", code="P1", value=60),
                self._warning("Tormentas", probability=">70%"),
            ),
            self.now,
        )

        self.assertEqual(message.count("<b>Сегодня · 03:00–14:59</b>"), 2)
        self.assertIn("Вероятность: 40–70%", message)
        self.assertIn("Вероятность: &gt;70%", message)


if __name__ == "__main__":
    unittest.main()
