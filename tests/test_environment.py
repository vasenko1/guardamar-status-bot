import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot._transport import BoundedFetchError
from telegrambot.environment import (
    EnvironmentError,
    METEOSALUD_COLD_URL,
    METEOSALUD_URL,
    _required_utc_hours,
    fetch_cams,
    fetch_meteosalud,
    fetch_meteosalud_cold,
    parse_cams_payload,
    parse_meteosalud_level,
    parse_meteosalud_cold_level,
    summarize_cams,
)


MADRID = ZoneInfo("Europe/Madrid")
VARIABLES = (
    "particulate_matter_2.5um",
    "particulate_matter_10um",
    "ozone",
    "nitrogen_dioxide",
    "sulphur_dioxide",
)


def _cams_payload(now, *, base=None, omit=()):
    base = base or datetime(2026, 8, 4, tzinfo=timezone.utc)
    units = {name: "µg/m3" for name in VARIABLES}
    start = _required_utc_hours(now)[0]
    rows = []
    for offset in range(80):
        timestamp = start + timedelta(hours=offset)
        values = {
            "particulate_matter_2.5um": 8.0,
            "particulate_matter_10um": 15.0,
            "ozone": 60.0,
            "nitrogen_dioxide": 20.0,
            "sulphur_dioxide": 20.0,
        }
        for name in omit:
            values.pop(name, None)
        rows.append({
            "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "kind": "analysis" if timestamp < base else "forecast",
            "values": values,
        })
    return json.dumps({
        "schema_version": 1,
        "provider": "Copernicus Atmosphere Monitoring Service (CAMS)",
        "product": "cams-europe-air-quality-forecasts",
        "model": "ensemble",
        "forecast_base_utc": base.isoformat().replace("+00:00", "Z"),
        "units": units,
        "hourly": rows,
    }).encode()


METEOSALUD_HEADER = (
    "Código Provincia         Nombre Provincia                                  "
    "Código Comarca           Nombre Comarca                                    "
    "Nivel de alerta"
)
GUARDAMAR_ROW = (
    "03                       Alicante                                          "
    "770303                   Litoral sur de Alicante                           0"
)


def _meteosalud_payload(*, date="04/08/2026", rows=(GUARDAMAR_ROW,)):
    text = (
        "Nivel de alerta en zonas de meteosalud del día: " + date + "\n\n"
        + METEOSALUD_HEADER + "\n" + "\n".join(rows) + "\n"
    )
    return text.encode("utf-8")


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)

    def test_meteosalud_today_selects_guardamar_among_other_zones(self):
        other = (
            "01                       Alava                                             "
            "750101                   Cuenca del Nervión                                3"
        )
        result = parse_meteosalud_level(
            _meteosalud_payload(rows=(other, GUARDAMAR_ROW)), self.now
        )
        self.assertEqual(result.level, 0)

    def test_meteosalud_levels_one_to_three(self):
        for level in (1, 2, 3):
            with self.subTest(level=level):
                row = GUARDAMAR_ROW[:-1] + str(level)
                result = parse_meteosalud_level(
                    _meteosalud_payload(rows=(row,)), self.now
                )
                self.assertEqual(result.level, level)

    def test_meteosalud_stale_file_is_silent(self):
        self.assertIsNone(parse_meteosalud_level(
            _meteosalud_payload(date="03/08/2026"), self.now
        ))

    def test_meteosalud_cold_levels_and_stale_date(self):
        for level in range(4):
            with self.subTest(level=level):
                row = GUARDAMAR_ROW[:-1] + str(level)
                self.assertEqual(
                    parse_meteosalud_cold_level(
                        _meteosalud_payload(rows=(row,)), self.now
                    ).level, level,
                )
        self.assertIsNone(parse_meteosalud_cold_level(
            _meteosalud_payload(date="03/08/2026"), self.now
        ))

    def test_meteosalud_cold_rejects_invalid_zone_and_level(self):
        for rows in (
            (GUARDAMAR_ROW[:-1] + "4",),
            (GUARDAMAR_ROW, GUARDAMAR_ROW),
            (GUARDAMAR_ROW.replace("770303", "770304"),),
        ):
            with self.subTest(rows=rows), self.assertRaises(EnvironmentError):
                parse_meteosalud_cold_level(_meteosalud_payload(rows=rows), self.now)

    def test_meteosalud_rejects_missing_or_malformed_date(self):
        for payload in (
            _meteosalud_payload(date=""),
            _meteosalud_payload(date="32/08/2026"),
            _meteosalud_payload(date="04/8/2026"),
        ):
            with self.subTest(payload=payload[:30]), self.assertRaises(EnvironmentError):
                parse_meteosalud_level(payload, self.now)

    def test_meteosalud_rejects_missing_duplicate_or_wrong_zone(self):
        other = (
            "01                       Alava                                             "
            "750101                   Cuenca del Nervión                                1"
        )
        for rows in (
            (other,),
            (GUARDAMAR_ROW, GUARDAMAR_ROW),
            (GUARDAMAR_ROW.replace("Litoral sur de Alicante", "Otra comarca"),),
            (GUARDAMAR_ROW.replace("Alicante", "Murcia", 1),),
        ):
            with self.subTest(rows=rows), self.assertRaises(EnvironmentError):
                parse_meteosalud_level(_meteosalud_payload(rows=rows), self.now)

    def test_meteosalud_rejects_invalid_levels_header_and_rows(self):
        for payload in (
            _meteosalud_payload(rows=(GUARDAMAR_ROW[:-1] + "4",)),
            _meteosalud_payload(rows=(GUARDAMAR_ROW[:-1] + "alto",)),
            _meteosalud_payload().replace(b"Nivel de alerta\n", b"Estado\n"),
            _meteosalud_payload(rows=(GUARDAMAR_ROW, "01 Alava 750101 Cuenca 1")),
            b"\xff" + _meteosalud_payload(),
        ):
            with self.subTest(payload=payload[-50:]), self.assertRaises(EnvironmentError):
                parse_meteosalud_level(payload, self.now)

    def test_uses_official_trailing_windows_and_local_day(self):
        now = self.now.replace(hour=23, minute=30)
        start = datetime(2026, 8, 3, 0, tzinfo=timezone.utc)
        rows = []
        for hour in range(48):
            moment = start + timedelta(hours=hour)
            rows.append((moment, {
                "particulate_matter_10um": 101.0 if hour >= 22 else 20.0,
                "particulate_matter_2.5um": 10.0,
                "ozone": 60.0, "nitrogen_dioxide": 20.0,
                "sulphur_dioxide": 20.0,
            }))
        air, pollen = summarize_cams(rows, now)
        self.assertIsNotNone(air)
        self.assertEqual(air.pollutants, ("PM10",))
        self.assertIsNone(pollen)

    def test_pollen_thresholds_and_ragweed_presence(self):
        rows = []
        for hour in range(24):
            rows.append((datetime(2026, 8, 4, hour, tzinfo=MADRID), {
                "olive_pollen": 201.0 if hour >= 15 else 200.0,
                "grass_pollen": 51.0 if hour == 13 else 0.0,
                "ragweed_pollen": 3.0 if hour == 19 else 2.9,
            }))
        air, pollen = summarize_cams(rows, self.now)
        self.assertIsNone(air)
        self.assertEqual(pollen.allergens, ("злаковых трав", "оливы"))
        self.assertTrue(pollen.ragweed_present)

    def test_parses_covering_public_contract(self):
        rows, base = parse_cams_payload(_cams_payload(self.now), self.now)
        self.assertEqual(base, datetime(2026, 8, 4, tzinfo=timezone.utc))
        self.assertGreaterEqual(len(rows), len(_required_utc_hours(self.now)))

    def test_missing_optional_variables_are_allowed(self):
        rows, _ = parse_cams_payload(_cams_payload(self.now), self.now)
        self.assertNotIn("olive_pollen", rows[0][1])

    def test_rejects_stale_non_covering_or_corrupt_contract(self):
        stale = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaises(EnvironmentError):
            parse_cams_payload(_cams_payload(self.now, base=stale), self.now)
        with self.assertRaises(EnvironmentError):
            parse_cams_payload(
                _cams_payload(self.now, omit=("particulate_matter_10um",)),
                self.now,
            )
        with self.assertRaises(EnvironmentError):
            parse_cams_payload(b"not json", self.now)

    def test_dst_target_day_has_correct_hour_count(self):
        spring = datetime(2026, 3, 29, 7, tzinfo=MADRID)
        autumn = datetime(2026, 10, 25, 7, tzinfo=MADRID)
        self.assertEqual(len(_required_utc_hours(spring)), 46)
        self.assertEqual(len(_required_utc_hours(autumn)), 48)

    def test_display_starts_above_regular_boundary(self):
        hours = []
        for hour in range(24):
            hours.append((datetime(2026, 8, 4, hour, tzinfo=MADRID), {
                "nitrogen_dioxide": 120.0,
                "sulphur_dioxide": 20.0,
            }))
        self.assertIsNone(summarize_cams(hours, self.now)[0])
        hours[-1][1]["nitrogen_dioxide"] = 120.001
        air = summarize_cams(hours, self.now)[0]
        self.assertIsNotNone(air)
        self.assertEqual(air.pollutants, ("NO₂",))


class MeteosaludFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_fetch_uses_official_bounded_txt(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        with patch(
            "telegrambot.environment.fetch_bounded",
            return_value=(_meteosalud_payload(), METEOSALUD_COLD_URL, "application/txt"),
        ) as fetch:
            result = await fetch_meteosalud_cold(now)
        self.assertEqual(result.level, 0)
        self.assertEqual(fetch.call_args.args, (METEOSALUD_COLD_URL,))
        self.assertEqual(fetch.call_args.kwargs["limit_bytes"], 64_000)
        self.assertEqual(fetch.call_args.kwargs["timeout_seconds"], 12)
        self.assertEqual(fetch.call_args.kwargs["accepted_types"], frozenset({"application/txt"}))
        self.assertIn("SANIDAD_NIVELES_ZONAS_ISO_I.txt", METEOSALUD_COLD_URL)
        allowed = fetch.call_args.kwargs["is_allowed_url"]
        self.assertTrue(allowed(METEOSALUD_COLD_URL))
        self.assertFalse(allowed(METEOSALUD_COLD_URL.replace(
            "www.sanidad.gob.es", "example.com"
        )))

    async def test_cold_fetch_transport_failure_has_safe_diagnostics(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        with patch(
            "telegrambot.environment.fetch_bounded",
            side_effect=BoundedFetchError("offline", code="HTTP-503", status=503),
        ):
            with self.assertRaises(EnvironmentError) as raised:
                await fetch_meteosalud_cold(now)
        self.assertEqual(raised.exception.diagnostic_code, "HTTP-503")
        self.assertEqual(raised.exception.server_status, 503)
    async def test_fetches_official_txt_with_bounded_mime_and_returns_level(self):
        with patch(
            "telegrambot.environment.fetch_bounded",
            return_value=(
                _meteosalud_payload(rows=(GUARDAMAR_ROW[:-1] + "2",)),
                METEOSALUD_URL,
                "application/txt",
            ),
        ) as fetch:
            result = await fetch_meteosalud(datetime(2026, 8, 4, 7, 30, tzinfo=MADRID))
        self.assertEqual(result.level, 2)
        self.assertEqual(fetch.call_args.args, (METEOSALUD_URL,))
        self.assertEqual(
            fetch.call_args.kwargs["accepted_types"], frozenset({"application/txt"})
        )
        self.assertEqual(fetch.call_args.kwargs["limit_bytes"], 64_000)
        self.assertIn("SANIDAD_NIVELES_ZONAS_ISO_V.txt", METEOSALUD_URL)

    async def test_transport_and_parse_failures_keep_safe_diagnostics(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        with patch(
            "telegrambot.environment.fetch_bounded",
            side_effect=BoundedFetchError("offline", code="HTTP-503", status=503),
        ):
            with self.assertRaises(EnvironmentError) as raised:
                await fetch_meteosalud(now)
        self.assertEqual(raised.exception.diagnostic_code, "HTTP-503")
        self.assertEqual(raised.exception.server_status, 503)
        self.assertIsNotNone(raised.exception.safe_description)
        with patch(
            "telegrambot.environment.fetch_bounded",
            return_value=(b"bad TXT", METEOSALUD_URL, "application/txt"),
        ):
            with self.assertRaises(EnvironmentError) as raised:
                await fetch_meteosalud(now)
        self.assertEqual(raised.exception.diagnostic_code, "PARSE")
        self.assertIsNone(raised.exception.server_status)


class CamsCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_previous_covering_cycle_is_logged_as_fallback(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        previous = _cams_payload(
            now, base=datetime(2026, 8, 3, tzinfo=timezone.utc)
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cams.json"
            with (
                patch(
                    "telegrambot.environment.fetch_bounded",
                    return_value=(previous, "url", "text/plain"),
                ),
                self.assertLogs("telegrambot.environment", level="INFO") as logs,
            ):
                await fetch_cams(
                    "https://raw.githubusercontent.com/vasenko1/guardamar-cams-data/main/data/latest.json",
                    cache,
                    now,
                )
        self.assertIn("previous forecast cycle", "\n".join(logs.output))

    async def test_newer_remote_replaces_older_covering_cache(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        old = _cams_payload(
            now, base=datetime(2026, 8, 3, tzinfo=timezone.utc)
        )
        new = _cams_payload(now)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cams.json"
            cache.write_bytes(old)
            with patch(
                "telegrambot.environment.fetch_bounded",
                return_value=(new, "url", "text/plain"),
            ):
                _, _, base = await fetch_cams(
                    "https://raw.githubusercontent.com/vasenko1/guardamar-cams-data/main/data/latest.json",
                    cache,
                    now,
                )
            cached_rows, cached_base = parse_cams_payload(
                cache.read_bytes(), now
            )
        self.assertTrue(cached_rows)
        self.assertEqual(base, datetime(2026, 8, 4, tzinfo=timezone.utc))
        self.assertEqual(cached_base, base)

    async def test_remote_failure_uses_covering_last_good_cache(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cams.json"
            cache.write_bytes(_cams_payload(now))
            with patch(
                "telegrambot.environment.fetch_bounded",
                side_effect=BoundedFetchError("offline", code="TEST"),
            ):
                diagnostics = []
                air, pollen, base = await fetch_cams(
                    "https://raw.githubusercontent.com/vasenko1/guardamar-cams-data/main/data/latest.json",
                    cache,
                    now,
                    diagnostics=diagnostics,
                )
        self.assertIsNone(air)
        self.assertIsNone(pollen)
        self.assertEqual(base, datetime(2026, 8, 4, tzinfo=timezone.utc))
        self.assertEqual(diagnostics[0].code, "CAMS-REMOTE-TEST")
        self.assertIn("локальный снимок", diagnostics[0].description)

    async def test_invalid_cache_and_remote_fail_closed(self):
        now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cams.json"
            cache.write_text("broken")
            with patch(
                "telegrambot.environment.fetch_bounded",
                side_effect=BoundedFetchError("offline", code="TEST"),
            ):
                with self.assertRaises(EnvironmentError):
                    await fetch_cams(
                        "https://raw.githubusercontent.com/vasenko1/guardamar-cams-data/main/data/latest.json",
                        cache,
                        now,
                    )


if __name__ == "__main__":
    unittest.main()
