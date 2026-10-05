import unittest
from datetime import date, time

from telegrambot.clock_change import (
    clock_change_notice_lines,
    clock_change_on,
)
from telegrambot.digest import build_message
from telegrambot.models import ClockChange, MorningDigest


class ClockChangeFactsTests(unittest.TestCase):
    def test_ordinary_day_has_no_transition(self):
        self.assertIsNone(clock_change_on(date(2026, 10, 24)))

    def test_2026_spring_transition_comes_from_europe_madrid(self):
        change = clock_change_on(date(2026, 3, 29))

        self.assertEqual(
            change,
            ClockChange(
                date=date(2026, 3, 29),
                from_time=time(2, 0),
                to_time=time(3, 0),
                delta_minutes=60,
            ),
        )

    def test_2026_autumn_transition_comes_from_europe_madrid(self):
        change = clock_change_on(date(2026, 10, 25))

        self.assertEqual(
            change,
            ClockChange(
                date=date(2026, 10, 25),
                from_time=time(3, 0),
                to_time=time(2, 0),
                delta_minutes=-60,
            ),
        )

    def test_future_tzdata_transition_is_not_hardcoded_to_2026(self):
        spring = clock_change_on(date(2031, 3, 30))
        autumn = clock_change_on(date(2031, 10, 26))

        self.assertEqual(spring.delta_minutes, 60)
        self.assertEqual(autumn.delta_minutes, -60)

    def test_previous_day_notice_has_exact_wall_clock_jump(self):
        change = clock_change_on(date(2026, 10, 25))

        lines = clock_change_notice_lines(change, tomorrow=True)

        self.assertIn("переход на зимнее время", lines[0])
        self.assertIn("<b>03:00</b>", lines[1])
        self.assertIn("<b>02:00</b>", lines[1])
        self.assertIn("час дольше", lines[1])


class ClockChangeDigestTests(unittest.TestCase):
    def test_day_of_transition_renders_one_compact_block(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            clock_change=clock_change_on(date(2026, 10, 25)),
        )

        message = build_message(digest)

        self.assertIn("⏰ <b>Сегодня перешли на зимнее время</b>", message)
        self.assertIn(
            "Ночью в <b>03:00</b> стало <b>02:00</b>.",
            message,
        )
        self.assertEqual(message.count("⏰"), 1)


if __name__ == "__main__":
    unittest.main()
