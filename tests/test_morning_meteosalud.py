import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.environment import EnvironmentError
from telegrambot.models import ColdHealthRisk, HeatHealthRisk, MorningDigest, Weather
from telegrambot.morning import produce_message


class MorningMeteosaludTests(unittest.IsolatedAsyncioTestCase):
    async def _produce(self, heat, cold, *, cams=None):
        now = datetime(2026, 9, 14, 7, 30, tzinfo=ZoneInfo("Europe/Madrid"))
        observed = []
        heat_mock = AsyncMock(side_effect=heat) if isinstance(heat, Exception) else AsyncMock(return_value=heat)
        cold_mock = AsyncMock(side_effect=cold) if isinstance(cold, Exception) else AsyncMock(return_value=cold)
        with (
            patch("telegrambot.morning.fetch_today_events", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_today_mayor_events", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_today_municipal_events", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_today_library_events", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_today_am_guardamar_events", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_traffic_notices", new=AsyncMock(return_value=())),
            patch("telegrambot.morning.fetch_meteosalud", new=heat_mock),
            patch("telegrambot.morning.fetch_meteosalud_cold", new=cold_mock),
            patch("telegrambot.morning.fetch_cams", new=AsyncMock(return_value=cams)) as cams_fetch,
        ):
            message = await produce_message(
                "unused", now, fetch_aemet=False, collect_beach=False,
                aemet_digest=MorningDigest(
                    weather=Weather(None, 12, 20, None, None, None),
                    warnings=(), warnings_available=True,
                ),
                cams_data_url="https://example.test/cams" if cams is not None else "",
                environment_observer=lambda h, c, base: observed.append((h, c, base)),
            )
        return message, observed, cams_fetch.await_count

    async def test_cold_source_failure_does_not_hide_heat(self):
        message, observed, _ = await self._produce(
            HeatHealthRisk(2), EnvironmentError("cold unavailable")
        )
        self.assertIn("Риск жары для здоровья: средний", message)
        self.assertNotIn("Риск холода", message)
        self.assertEqual(observed, [(HeatHealthRisk(2), None, None)])

    async def test_heat_source_failure_does_not_hide_cold(self):
        message, observed, _ = await self._produce(
            EnvironmentError("heat unavailable"), ColdHealthRisk(1)
        )
        self.assertIn("Риск холода для здоровья: низкий", message)
        self.assertNotIn("Риск жары", message)
        self.assertEqual(observed, [(None, ColdHealthRisk(1), None)])

    async def test_both_successful_and_zero_cold_is_silent(self):
        message, observed, _ = await self._produce(HeatHealthRisk(1), ColdHealthRisk(2))
        self.assertIn("Риск жары для здоровья: низкий", message)
        self.assertIn("Риск холода для здоровья: средний", message)
        self.assertEqual(observed, [(HeatHealthRisk(1), ColdHealthRisk(2), None)])
        silent, _, _ = await self._produce(HeatHealthRisk(0), ColdHealthRisk(0))
        self.assertNotIn("Риск жары", silent)
        self.assertNotIn("Риск холода", silent)

    async def test_cold_failure_does_not_skip_cams(self):
        base = datetime.fromisoformat("2026-09-14T00:00:00+00:00")
        message, observed, calls = await self._produce(
            HeatHealthRisk(1), EnvironmentError("cold unavailable"),
            cams=(None, None, base),
        )
        self.assertIn("Риск жары для здоровья: низкий", message)
        self.assertEqual(calls, 1)
        self.assertEqual(observed, [(HeatHealthRisk(1), None, base)])
