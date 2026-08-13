import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegrambot.sun import sun_times

TZ = ZoneInfo("Europe/Madrid")


class SunTimesTests(unittest.TestCase):
    def _times(self, day):
        return sun_times(datetime.fromisoformat(f"{day}T07:00").replace(
            tzinfo=TZ
        ))

    def assertNear(self, moment, expected_hhmm, tolerance_minutes=4):
        expected = datetime.combine(
            moment.date(),
            datetime.strptime(expected_hhmm, "%H:%M").time(),
            TZ,
        )
        delta = abs(moment - expected)
        self.assertLessEqual(
            delta,
            timedelta(minutes=tolerance_minutes),
            f"{moment:%H:%M} is not within {tolerance_minutes} minutes "
            f"of {expected_hhmm}",
        )

    def test_summer_solstice_matches_published_ephemeris(self):
        sunrise, sunset = self._times("2026-06-21")
        self.assertNear(sunrise, "06:39")
        self.assertNear(sunset, "21:28")

    def test_winter_solstice_matches_published_ephemeris(self):
        sunrise, sunset = self._times("2026-12-21")
        self.assertNear(sunrise, "08:15")
        self.assertNear(sunset, "17:46")

    def test_returns_local_timezone_aware_daylight_ordering(self):
        sunrise, sunset = self._times("2026-08-15")
        self.assertEqual(sunrise.tzinfo, TZ)
        self.assertEqual(sunset.tzinfo, TZ)
        self.assertLess(sunrise, sunset)
        # CEST in August: sunrise after 06:00, sunset before 22:00.
        self.assertGreaterEqual(sunrise.hour, 6)
        self.assertLessEqual(sunset.hour, 21)


if __name__ == "__main__":
    unittest.main()
