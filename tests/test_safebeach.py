import email.message
import json
import unittest
import urllib.error
from datetime import date, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import BeachStatus, MorningDigest, Weather
from telegrambot.morning import _safebeach_is_in_season, produce_message
from telegrambot.safebeach import (
    SafeBeachError,
    _read_page,
    fetch_beach_status,
    is_complete_current_status,
    is_current_status,
    normalize_beach_status,
)

MADRID = ZoneInfo("Europe/Madrid")
TEST_DAY = date(2026, 7, 29)


def _page(markers, page_date=TEST_DAY):
    data = json.dumps(markers, separators=(",", ":")).encode()
    displayed = page_date.strftime("%d/%m/%Y").encode()
    return (
        b'<div class="sub">Mi\xc3\xa9rcoles - '
        + displayed
        + b"</div><script>window.SB_MARKERS = "
        + data
        + b";</script>"
    )


def _normalize(markers, page_date=TEST_DAY):
    return normalize_beach_status(
        _page(markers, page_date),
        TEST_DAY,
    )


def _marker(
    flag,
    temperature="24º C",
    ended=False,
    beach_name="Platja Centre / Babilònia",
    sea_state="Moderado",
    jellyfish="No",
    updated="10:05",
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
                "hora": updated,
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

    def test_normalizes_centre_conditions_and_recognized_beach_flags(self):
        status = _normalize(
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

        self.assertEqual(status.flag_color, "green")
        self.assertEqual(status.sea_temperature_c, 25)
        self.assertEqual(status.wind_direction, "E")
        self.assertEqual(status.wind_speed_kmh, 11)
        self.assertEqual(status.sea_state, "moderate")
        self.assertEqual(
            status.nearby_flags,
            (
                ("Centre", "green"),
                ("Roqueta", "yellow"),
                ("Vivers", "green"),
                ("Camp", "red"),
            ),
        )
        self.assertEqual(status.jellyfish_beaches, ("Roqueta",))
        self.assertEqual(status.source_date, TEST_DAY)

    def test_rejects_page_from_another_local_date(self):
        with self.assertRaises(SafeBeachError) as raised:
            _normalize(
                [_marker("verde")],
                date(2026, 7, 28),
            )

        self.assertEqual(raised.exception.diagnostic_code, "STALE-DATE")

    def test_omits_conflicting_flag_but_keeps_other_valid_beach(self):
        centre = _marker("verde")
        centre["items"][0]["colorBandera"] = "#FF0000"

        status = _normalize(
            [
                centre,
                _marker(
                    "amarilla",
                    beach_name="Platja La Roqueta",
                ),
            ]
        )

        self.assertEqual(status.nearby_flags, (("Roqueta", "yellow"),))
        self.assertIsNone(status.flag_color)

    def test_omits_conflicting_duplicate_beach_records(self):
        status = _normalize(
            [
                _marker("verde"),
                _marker("roja"),
                _marker(
                    "amarilla",
                    beach_name="Platja La Roqueta",
                ),
            ]
        )

        self.assertEqual(status.nearby_flags, (("Roqueta", "yellow"),))

    def test_same_flag_duplicate_uses_the_newer_record(self):
        older = _marker("verde", "23º C", updated="10:00")
        newer = _marker("verde", "25º C", updated="10:05")

        status = _normalize([older, newer])

        self.assertEqual(status.nearby_flags, (("Centre", "green"),))
        self.assertEqual(status.sea_temperature_c, 25)
        self.assertEqual(status.updated_times, (("Centre", time(10, 5)),))

    def test_json_extraction_is_not_broken_by_script_text_in_a_value(self):
        marker = _marker("verde")
        marker["note"] = "literal ]; inside JSON"

        status = _normalize([marker])

        self.assertEqual(status.nearby_flags, (("Centre", "green"),))

    def test_requires_an_exact_markers_assignment(self):
        payload = (
            b'<div class="sub">29/07/2026</div>'
            b"<script>window.SB_MARKERS note = [];</script>"
        )

        with self.assertRaises(SafeBeachError) as raised:
            normalize_beach_status(payload, TEST_DAY)

        self.assertEqual(raised.exception.diagnostic_code, "NO-DATA")

    def test_completeness_requires_all_three_preferred_beaches(self):
        status = _normalize(
            [
                _marker("verde", updated="10:05"),
                _marker(
                    "amarilla",
                    beach_name="Platja La Roqueta",
                    updated="10:04",
                ),
                _marker(
                    "verde",
                    beach_name="Platja dels Vivers",
                    updated="10:03",
                ),
            ]
        )
        now = datetime(2026, 7, 29, 10, 10, tzinfo=MADRID)

        self.assertTrue(is_complete_current_status(status, now))
        partial = _normalize([_marker("verde")])
        self.assertFalse(
            is_complete_current_status(
                partial,
                now,
            )
        )
        self.assertTrue(is_current_status(partial, now))
        self.assertFalse(
            is_complete_current_status(
                _normalize([_marker("verde", updated="")]),
                now,
            )
        )
        self.assertFalse(
            is_complete_current_status(
                _normalize([_marker("verde", updated="10:16")]),
                now,
            )
        )
        self.assertFalse(
            is_complete_current_status(
                BeachStatus(
                    flag_color="green",
                    sea_temperature_c=24,
                    source_date=date(2026, 7, 28),
                    nearby_flags=(("Centre", "green"),),
                    updated_times=(("Centre", time(10, 5)),),
                ),
                now,
            )
        )

    def test_ignores_ended_service_and_allows_missing_temperature(self):
        status = _normalize(
            [
                _marker("roja", "22º C", ended=True),
                _marker("amarilla", "not available"),
            ]
        )

        self.assertEqual(status.flag_color, "yellow")
        self.assertIsNone(status.sea_temperature_c)


class SafeBeachTransportTests(unittest.IsolatedAsyncioTestCase):
    def _response(self, payload, content_type="text/html; charset=UTF-8"):
        headers = email.message.Message()
        headers["Content-Type"] = content_type
        response = MagicMock()
        response.geturl.return_value = (
            "https://info.safebeach.es/guardamar-del-segura"
        )
        response.headers = headers
        response.read.return_value = payload
        response.__enter__.return_value = response
        return response

    def test_accepts_one_bounded_html_response(self):
        response = self._response(b"<html></html>")
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "telegrambot.safebeach.urllib.request.build_opener",
            return_value=opener,
        ):
            self.assertEqual(_read_page(), b"<html></html>")

        opener.open.assert_called_once()
        self.assertEqual(
            response.read.call_args.args[0],
            512 * 1024 + 1,
        )

    def test_rejects_non_html_response(self):
        response = self._response(b"{}", "application/json")
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "telegrambot.safebeach.urllib.request.build_opener",
            return_value=opener,
        ), self.assertRaises(SafeBeachError) as raised:
            _read_page()

        self.assertEqual(raised.exception.diagnostic_code, "CONTENT-TYPE")

    def test_rejects_unexpected_final_host(self):
        response = self._response(b"<html></html>")
        response.geturl.return_value = "https://example.com/guardamar"
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "telegrambot.safebeach.urllib.request.build_opener",
            return_value=opener,
        ), self.assertRaises(SafeBeachError) as raised:
            _read_page()

        self.assertEqual(raised.exception.diagnostic_code, "REDIRECT")

    def test_rejects_oversized_response(self):
        response = self._response(b"x" * (512 * 1024 + 1))
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "telegrambot.safebeach.urllib.request.build_opener",
            return_value=opener,
        ), self.assertRaises(SafeBeachError) as raised:
            _read_page()

        self.assertEqual(raised.exception.diagnostic_code, "TOO-LARGE")

    def test_exposes_server_http_status_without_retry(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://info.safebeach.es/guardamar-del-segura",
            503,
            "unavailable",
            {},
            None,
        )

        with patch(
            "telegrambot.safebeach.urllib.request.build_opener",
            return_value=opener,
        ), self.assertRaises(SafeBeachError) as raised:
            _read_page()

        self.assertEqual(raised.exception.diagnostic_code, "HTTP-503")
        self.assertEqual(raised.exception.server_status, 503)
        opener.open.assert_called_once()

    async def test_fetch_validates_against_supplied_local_date(self):
        with patch(
            "telegrambot.safebeach._read_page",
            return_value=_page([_marker("verde")]),
        ):
            status = await fetch_beach_status(
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID)
            )

        self.assertEqual(status.source_date, TEST_DAY)

    async def test_fills_three_slots_from_lower_priority_active_beaches(self):
        markers = [
            _marker("verde", updated=""),
            _marker(
                "amarilla",
                beach_name="Platja La Roqueta",
                updated="10:04",
            ),
            _marker(
                "verde",
                beach_name="Platja dels Vivers",
                updated="10:03",
            ),
            _marker(
                "roja",
                beach_name="Platja del Montcaio",
                updated="10:02",
            ),
            _marker(
                "verde",
                beach_name="Platja del Camp",
                updated="10:01",
            ),
        ]
        with patch(
            "telegrambot.safebeach._read_page",
            return_value=_page(markers),
        ):
            status = await fetch_beach_status(
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID)
            )

        self.assertEqual(
            status.nearby_flags,
            (
                ("Roqueta", "yellow"),
                ("Vivers", "green"),
                ("Montcaio", "red"),
            ),
        )
        self.assertFalse(
            is_complete_current_status(
                status,
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID),
            )
        )
        self.assertTrue(
            is_current_status(
                status,
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID),
            )
        )

    async def test_one_missing_time_does_not_block_other_valid_beach(self):
        markers = [
            _marker("verde", updated=""),
            _marker(
                "amarilla",
                beach_name="Platja La Roqueta",
                updated="10:04",
            ),
        ]
        with patch(
            "telegrambot.safebeach._read_page",
            return_value=_page(markers),
        ):
            status = await fetch_beach_status(
                datetime(2026, 7, 29, 10, 10, tzinfo=MADRID)
            )

        self.assertEqual(status.nearby_flags, (("Roqueta", "yellow"),))


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
                "telegrambot.morning.fetch_today_mayor_events",
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
                "telegrambot.morning.fetch_today_mayor_events",
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

        diagnostics = []
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
                "telegrambot.morning.fetch_today_mayor_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(return_value=()),
            ),
        ):
            message = await produce_message(
                "api-key",
                now,
                diagnostics=diagnostics,
            )

        self.assertIn("🌊 Море: —", message)
        self.assertNotIn("Источник", message)
        self.assertNotIn("Флаг", message)
        self.assertNotIn("SafeBeach", message)
        safe_beach = [
            item for item in diagnostics if item.source == "SafeBeach"
        ]
        self.assertEqual(len(safe_beach), 1)
        self.assertEqual(safe_beach[0].code, "SB-INVALID")


if __name__ == "__main__":
    unittest.main()
