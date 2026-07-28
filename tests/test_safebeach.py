import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import BeachStatus, MorningDigest, Weather
from telegrambot.morning import _safebeach_is_in_season, produce_message
from telegrambot.safebeach import (
    SafeBeachError,
    normalize_beach_status,
)

MADRID = ZoneInfo("Europe/Madrid")


def _page(markers):
    data = json.dumps(markers, separators=(",", ":")).encode()
    return b"<script>window.SB_MARKERS = " + data + b";</script>"


def _marker(
    flag,
    temperature="24º C",
    ended=False,
    beach_name="Platja Centre / Babilònia",
    sea_state="Moderado",
    jellyfish="No",
):
    return {
        "items": [
            {
                "beachName": beach_name,
                "hasActividad": True,
                "serviceEnded": ended,
                "textoBandera": f"Bandera {flag}",
                "waterTemp": temperature,
                "viento": "3 m/s",
                "windDeg": 100.34,
                "oleaje": sea_state,
                "medusas": jellyfish,
            }
        ]
    }


class SafeBeachNormalizationTests(unittest.TestCase):
    def test_conservative_season_boundaries_are_inclusive(self):
        self.assertFalse(
            _safebeach_is_in_season(
                datetime(2026, 6, 19, 23, 59, tzinfo=MADRID)
            )
        )
        self.assertTrue(
            _safebeach_is_in_season(
                datetime(2026, 6, 20, 0, 0, tzinfo=MADRID)
            )
        )
        self.assertTrue(
            _safebeach_is_in_season(
                datetime(2026, 9, 14, 23, 59, tzinfo=MADRID)
            )
        )
        self.assertFalse(
            _safebeach_is_in_season(
                datetime(2026, 9, 15, 0, 0, tzinfo=MADRID)
            )
        )

    def test_selects_centre_conditions_and_three_nearby_flags(self):
        status = normalize_beach_status(
            _page(
                [
                    _marker("verde", "25º C"),
                    _marker(
                        "amarilla",
                        "23º C",
                        beach_name="Platja La Roqueta",
                        jellyfish="Sí",
                    ),
                    _marker(
                        "verde",
                        "24º C",
                        beach_name="Platja dels Vivers",
                    ),
                    _marker(
                        "roja",
                        "23º C",
                        beach_name="Platja del Camp",
                    ),
                ]
            )
        )

        self.assertEqual(status.flag_color, "green")
        self.assertEqual(status.sea_temperature_c, 25)
        self.assertEqual(status.wind_direction, "E")
        self.assertEqual(status.wind_speed_kmh, 11)
        self.assertEqual(status.sea_state, "moderate")
        self.assertEqual(
            status.nearby_flags,
            (
                ("Vivers", "green"),
                ("Centre", "green"),
                ("Roqueta", "yellow"),
            ),
        )
        self.assertEqual(status.jellyfish_beaches, ("Roqueta",))

    def test_ignores_ended_service_and_allows_missing_temperature(self):
        status = normalize_beach_status(
            _page(
                [
                    _marker("roja", "22º C", ended=True),
                    _marker("amarilla", "not available"),
                ]
            )
        )

        self.assertEqual(status.flag_color, "yellow")
        self.assertIsNone(status.sea_temperature_c)


class SafeBeachFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_safebeach_outside_conservative_season(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=18,
                minimum_temperature_c=12,
                maximum_temperature_c=20,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=True,
            forecast_sea_temperature_c=18,
        )
        now = datetime(2026, 12, 15, 10, 0, tzinfo=MADRID)
        with (
            patch(
                "telegrambot.morning.fetch_morning_digest",
                new=AsyncMock(return_value=digest),
            ),
            patch(
                "telegrambot.morning.fetch_beach_status",
                new=AsyncMock(),
            ) as beach_fetch,
            patch(
                "telegrambot.morning.fetch_today_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_today_municipal_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(return_value=()),
            ),
        ):
            message = await produce_message("api-key", now)

        beach_fetch.assert_not_awaited()
        self.assertIn("🌊 Море: 18°", message)
        self.assertNotIn("🏖 Флаги", message)

    async def test_uses_beach_wind_as_current_and_aemet_as_forecast(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=23,
                maximum_temperature_c=31,
                wind_direction="E",
                wind_speed_kmh=15,
                observed_at=None,
                forecast_wind_speed_kmh=15,
            ),
            warnings=(),
            warnings_available=True,
        )
        now = datetime(2026, 7, 27, 8, 0, tzinfo=MADRID)
        with (
            patch(
                "telegrambot.morning.fetch_morning_digest",
                new=AsyncMock(return_value=digest),
            ),
            patch(
                "telegrambot.morning.fetch_beach_status",
                new=AsyncMock(
                    return_value=BeachStatus(
                        flag_color="yellow",
                        sea_temperature_c=27,
                        wind_direction="E",
                        wind_speed_kmh=11,
                    )
                ),
            ),
            patch(
                "telegrambot.morning.fetch_today_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_today_municipal_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(return_value=()),
            ),
        ):
            message = await produce_message("api-key", now)

        self.assertIn("💨 Ветер: В 3 → 4 м/с", message)

    async def test_failure_omits_beach_without_blocking_weather(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=23.0,
                minimum_temperature_c=20,
                maximum_temperature_c=29,
                wind_direction="E",
                wind_speed_kmh=12,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=True,
        )
        now = datetime(2026, 7, 26, 8, 0, tzinfo=MADRID)

        with (
            patch(
                "telegrambot.morning.fetch_morning_digest",
                new=AsyncMock(return_value=digest),
            ),
            patch(
                "telegrambot.morning.fetch_beach_status",
                new=AsyncMock(
                    side_effect=SafeBeachError("temporarily unavailable")
                ),
            ),
            patch(
                "telegrambot.morning.fetch_today_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(return_value=()),
            ),
        ):
            message = await produce_message("api-key", now)

        self.assertIn("🌊 Море: —", message)
        self.assertNotIn("Источник", message)
        self.assertNotIn("Флаг", message)
        self.assertNotIn("SafeBeach", message)


if __name__ == "__main__":
    unittest.main()
