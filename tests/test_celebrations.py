import unittest
from datetime import date, datetime
from telegrambot.celebrations import (
    build_celebration_alert,
    celebrations_for_year,
    celebrations_on,
)
from telegrambot.digest import GUARDAMAR_TIMEZONE, build_message
from telegrambot.holidays import is_market_day, official_holidays_on
from telegrambot.models import Celebration, Holiday, MorningDigest


class CelebrationCalendarTests(unittest.TestCase):
    @staticmethod
    def _digest(**changes):
        values = {
            "weather": None,
            "warnings": (),
            "warnings_available": True,
        }
        values.update(changes)
        return MorningDigest(**values)

    def test_reviewed_2026_calendar_contains_major_local_periods(self):
        celebrations = celebrations_for_year(2026)

        self.assertIsNotNone(celebrations)
        names = {item.name for item in celebrations}
        self.assertIn("Страстная неделя (Semana Santa)", names)
        self.assertIn("Праздники Мавров и Христиан", names)
        self.assertIn(
            "День Sant Jaume — покровителя Гуардамара",
            names,
        )
        self.assertIn(
            "Праздники в честь Девы Марии Розария",
            names,
        )
        self.assertIn("День всех святых", names)

    def test_unknown_year_fails_closed(self):
        self.assertIsNone(celebrations_for_year(2027))
        self.assertEqual(celebrations_on(date(2027, 10, 7)), ())

    def test_cultural_celebration_never_changes_market_rule(self):
        day = date(2026, 9, 23)

        self.assertTrue(celebrations_on(day))
        self.assertTrue(is_market_day(day))

    def test_linked_official_holiday_is_rendered_once_in_morning_digest(self):
        day = date(2026, 10, 7)
        now = datetime(2026, 10, 7, 7, 0, tzinfo=GUARDAMAR_TIMEZONE)
        message = build_message(
            self._digest(
                holidays=official_holidays_on(day),
                celebrations=celebrations_on(day),
            ),
            now=now,
        )

        self.assertIn("🎉 <b>Сегодня в Гуардамаре:</b>", message)
        self.assertIn(
            "• Праздники в честь Девы Марии Розария · "
            "сегодня последний день",
            message,
        )
        self.assertEqual(message.count("Девы Марии Розария"), 1)
        self.assertNotIn("Праздник Девы Марии Розария —", message)
        self.assertIn("🏛️ Официальный городской выходной.", message)

    def test_official_only_holiday_keeps_existing_presentation(self):
        day = date(2026, 10, 9)
        now = datetime(2026, 10, 9, 7, 0, tzinfo=GUARDAMAR_TIMEZONE)
        message = build_message(
            self._digest(holidays=official_holidays_on(day)),
            now=now,
        )

        self.assertIn(
            "🎉 <b>Праздник сегодня:</b>\n"
            "• День Валенсийского сообщества — региональный праздник\n"
            "  🏛️ Официальный выходной день.",
            message,
        )

    def test_two_overlapping_celebrations_render_as_two_human_rows(self):
        day = date(2026, 9, 25)
        now = datetime(2026, 9, 25, 7, 0, tzinfo=GUARDAMAR_TIMEZONE)
        message = build_message(
            self._digest(
                celebrations=(
                    Celebration(
                        "Праздник A",
                        date(2026, 9, 20),
                        date(2026, 9, 30),
                    ),
                    Celebration(
                        "Праздник B",
                        date(2026, 9, 25),
                        date(2026, 9, 26),
                    ),
                ),
            ),
            now=now,
        )

        self.assertIn("🎉 <b>В городе праздники:</b>", message)
        self.assertIn("• Праздник A · до 30 сентября", message)
        self.assertIn(
            "• Праздник B · сегодня первый день · до 26 сентября",
            message,
        )

    def test_sant_jaume_is_visible_inside_moros_y_cristianos_period(self):
        day = date(2026, 7, 25)
        now = datetime(2026, 7, 25, 7, 0, tzinfo=GUARDAMAR_TIMEZONE)
        message = build_message(
            self._digest(celebrations=celebrations_on(day)),
            now=now,
        )

        self.assertIn("🎉 <b>В городе праздники:</b>", message)
        self.assertIn(
            "• Праздники Мавров и Христиан · до 26 июля",
            message,
        )
        self.assertIn(
            "• День Sant Jaume — покровителя Гуардамара · сегодня",
            message,
        )

    def test_sant_jaume_gets_next_day_alert(self):
        now = datetime(2026, 7, 24, 18, 0, tzinfo=GUARDAMAR_TIMEZONE)

        publication = build_celebration_alert(now)

        self.assertIsNotNone(publication)
        self.assertEqual(publication.target_date, date(2026, 7, 25))
        self.assertIn(
            "День Sant Jaume — покровителя Гуардамара · завтра",
            publication.message,
        )
        self.assertNotIn(
            "Праздники Мавров и Христиан · до 26 июля",
            publication.message,
        )

    def test_unrelated_official_holiday_is_not_hidden_by_celebration(self):
        day = date(2026, 10, 12)
        now = datetime(2026, 10, 12, 7, 0, tzinfo=GUARDAMAR_TIMEZONE)
        message = build_message(
            self._digest(
                holidays=(
                    Holiday(day, "Национальный день Испании", "national"),
                ),
                celebrations=(
                    Celebration(
                        "Отдельный городской праздник",
                        date(2026, 10, 10),
                        date(2026, 10, 13),
                    ),
                ),
            ),
            now=now,
        )

        self.assertIn("Отдельный городской праздник", message)
        self.assertIn("Национальный день Испании — национальный праздник", message)


class CelebrationAlertTests(unittest.TestCase):
    def test_alerts_once_before_celebration_start(self):
        now = datetime(2026, 9, 18, 18, 0, tzinfo=GUARDAMAR_TIMEZONE)

        publication = build_celebration_alert(now)

        self.assertIsNotNone(publication)
        self.assertEqual(publication.target_date, date(2026, 9, 19))
        self.assertIn("🎉 <b>Завтра в Гуардамаре:</b>", publication.message)
        self.assertIn(
            "Праздники в честь Девы Марии Розария · "
            "19 сентября — 7 октября",
            publication.message,
        )

    def test_linked_official_day_alert_does_not_repeat_same_festival_name(self):
        now = datetime(2026, 10, 6, 18, 0, tzinfo=GUARDAMAR_TIMEZONE)

        publication = build_celebration_alert(now)

        self.assertIsNotNone(publication)
        self.assertEqual(publication.message.count("Девы Марии Розария"), 1)
        self.assertIn(
            "Праздники в честь Девы Марии Розария · последний день",
            publication.message,
        )
        self.assertNotIn("Праздник Девы Марии Розария —", publication.message)
        self.assertIn("🏛️ Официальный городской выходной.", publication.message)

    def test_official_only_day_still_gets_next_day_alert(self):
        now = datetime(2026, 10, 8, 18, 0, tzinfo=GUARDAMAR_TIMEZONE)

        publication = build_celebration_alert(now)

        self.assertIsNotNone(publication)
        self.assertIn(
            "День Валенсийского сообщества — региональный праздник",
            publication.message,
        )
        self.assertIn("🏛️ Официальный выходной день.", publication.message)

    def test_day_without_start_or_official_holiday_has_no_alert(self):
        now = datetime(2026, 9, 24, 18, 0, tzinfo=GUARDAMAR_TIMEZONE)

        self.assertIsNone(build_celebration_alert(now))


if __name__ == "__main__":
    unittest.main()
