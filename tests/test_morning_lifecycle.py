import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import BeachStatus, MorningDigest, Weather
from telegrambot.morning import produce_message


class MorningLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_morning_without_safebeach_does_not_render_snapshot_flags(self):
        now = datetime(2026, 9, 14, 7, 30, tzinfo=ZoneInfo("Europe/Madrid"))
        fallback = MorningDigest(
            weather=Weather(None, 20, 29, None, None, None, sky_condition="ясно"), warnings=(),
            warnings_available=True,
            beach=BeachStatus(
                flag_color="green", sea_temperature_c=28,
                nearby_flags=(("Montcaio", "green"),),
            ),
        )
        with patch("telegrambot.morning.fetch_today_events", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.fetch_today_mayor_events", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.recurring_events", return_value=()), \
             patch("telegrambot.morning.fetch_traffic_notices", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.fetch_today_municipal_events", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.fetch_today_library_events", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.fetch_today_am_guardamar_events", new=AsyncMock(return_value=())), \
             patch("telegrambot.morning.fetch_meteosalud", new=AsyncMock(return_value=None)), \
             patch("telegrambot.morning.fetch_meteosalud_cold", new=AsyncMock(return_value=None)):
            message = await produce_message(
                "key", now, "", "/tmp/none.json", collect_beach=False,
                aemet_digest=fallback, fetch_aemet=False,
                fetch_environment=False,
            )
        self.assertNotIn("Флаги на пляжах", message)
        self.assertNotIn("Montcaio", message)


if __name__ == "__main__":
    unittest.main()
