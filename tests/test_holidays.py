import unittest
from datetime import date

from telegrambot.holidays import (
    holidays_for_year,
    is_market_day,
    official_holidays_on,
)


class HolidayCalendarTests(unittest.TestCase):
    def test_returns_reviewed_local_holiday_with_name_and_scope(self):
        holidays = official_holidays_on(date(2026, 10, 7))

        self.assertEqual(len(holidays), 1)
        self.assertEqual(holidays[0].name, "Праздник Девы Марии Розария")
        self.assertEqual(holidays[0].scope, "local")

    def test_unknown_year_is_fail_closed(self):
        self.assertEqual(official_holidays_on(date(2027, 1, 1)), ())
        self.assertIsNone(holidays_for_year(2027))
        self.assertFalse(is_market_day(date(2027, 1, 6)))

    def test_existing_market_holiday_rule_is_preserved(self):
        self.assertTrue(is_market_day(date(2026, 10, 6)))
        self.assertFalse(is_market_day(date(2026, 10, 7)))


if __name__ == "__main__":
    unittest.main()
