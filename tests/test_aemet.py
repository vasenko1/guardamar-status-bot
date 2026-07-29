import io
import json
import tarfile
import unittest
import zipfile
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.aemet import (
    AemetError,
    normalize_beach_forecast,
    normalize_daily_forecast,
    normalize_observation,
    normalize_warnings,
)


class BeachForecastTests(unittest.TestCase):
    def test_selects_today_water_temperature(self):
        payload = json.dumps(
            [
                {
                    "prediccion": {
                        "dia": [
                            {
                                "fecha": 20260727,
                                "tAgua": {"valor1": 29},
                                "oleaje": {
                                    "descripcion1": "Débil",
                                    "descripcion2": "Moderado",
                                },
                            }
                        ]
                    }
                }
            ]
        ).encode("iso-8859-1")

        self.assertEqual(
            normalize_beach_forecast(payload, date(2026, 7, 27)),
            (29, "slight", "moderate"),
        )

    def test_allows_missing_water_temperature(self):
        payload = json.dumps(
            [
                {
                    "prediccion": {
                        "dia": [{"fecha": 20260727}]
                    }
                }
            ]
        ).encode()

        self.assertEqual(
            normalize_beach_forecast(payload, date(2026, 7, 27)),
            (None, None, None),
        )


class DailyForecastTests(unittest.TestCase):
    def test_normalizes_temperature_range_and_strongest_wind(self):
        payload = json.dumps(
            [
                {
                    "prediccion": {
                        "dia": [
                            {
                                "fecha": "2026-07-26T00:00:00",
                                "temperatura": {"minima": 23, "maxima": 31},
                                "estadoCielo": [
                                    {"descripcion": "Poco nuboso"},
                                    {"descripcion": "Lluvia escasa"},
                                ],
                                "probPrecipitacion": [
                                    {"value": 40, "periodo": "00-12"},
                                    {"value": 80, "periodo": "12-18"},
                                    {"value": 65, "periodo": "18-24"},
                                ],
                                "viento": [
                                    {"direccion": "E", "velocidad": 10},
                                    {"direccion": "SE", "velocidad": 20},
                                ],
                            }
                        ]
                    }
                }
            ]
        ).encode()

        self.assertEqual(
            normalize_daily_forecast(
                payload,
                date(2026, 7, 26),
                local_hour=10,
            ),
            (23, 31, "SE", 20, "rain", 80, "12:00–18:00"),
        )

    def test_uses_encompassing_rain_period_when_no_future_period_exists(self):
        payload = json.dumps(
            [
                {
                    "prediccion": {
                        "dia": [
                            {
                                "fecha": "2026-07-26T00:00:00",
                                "temperatura": {"minima": 23, "maxima": 31},
                                "probPrecipitacion": [
                                    {"value": 76, "periodo": "00-24"}
                                ],
                            }
                        ]
                    }
                }
            ]
        ).encode()

        result = normalize_daily_forecast(
            payload,
            date(2026, 7, 26),
            local_hour=10,
        )

        self.assertEqual(result[-2:], (76, "00:00–24:00"))

    def test_rejects_forecast_without_today(self):
        payload = json.dumps(
            [{"prediccion": {"dia": []}}]
        ).encode()

        with self.assertRaises(AemetError):
            normalize_daily_forecast(payload, date(2026, 7, 26))


class ObservationTests(unittest.TestCase):
    def test_uses_newest_fresh_observation_and_converts_wind(self):
        payload = json.dumps(
            [
                {
                    "fint": "2026-07-26T05:00:00+00:00",
                    "ta": 22.1,
                    "vv": 2,
                    "dv": 85,
                },
                {
                    "fint": "2026-07-26T06:00:00+00:00",
                    "ta": 23.4,
                    "vv": 3.2,
                    "dv": 92,
                },
            ]
        ).encode()
        now = datetime(2026, 7, 26, 6, 30, tzinfo=timezone.utc)

        result = normalize_observation(payload, now)

        self.assertIsNotNone(result)
        temperature, direction, speed, observed_at = result
        self.assertEqual(temperature, 23.4)
        self.assertEqual(direction, "E")
        self.assertEqual(speed, 12)
        self.assertEqual(
            observed_at, datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
        )

    def test_omits_stale_observation(self):
        payload = json.dumps(
            [{"fint": "2026-07-26T01:00:00+00:00", "ta": 20}]
        ).encode()
        now = datetime(2026, 7, 26, 6, 30, tzinfo=timezone.utc)

        self.assertIsNone(normalize_observation(payload, now))


class WarningTests(unittest.TestCase):
    def _archive(self, *documents):
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as archive:
            for index, document in enumerate(documents):
                archive.writestr(f"warning-{index}.xml", document)
        return result.getvalue()

    def _tar_archive(self, *documents):
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w") as archive:
            for index, document in enumerate(documents):
                item = tarfile.TarInfo(f"warning-{index}.xml")
                item.size = len(document)
                archive.addfile(item, io.BytesIO(document))
        return result.getvalue()

    def test_keeps_only_active_guardamar_zone_warning(self):
        active = b"""<?xml version="1.0" encoding="UTF-8"?>
        <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <status>Actual</status>
          <info>
            <language>es-ES</language>
            <event>Temperaturas maximas</event>
            <severity>Severe</severity>
            <onset>2026-07-26T10:00:00+02:00</onset>
            <expires>2026-07-26T20:00:00+02:00</expires>
            <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
          </info>
        </alert>"""
        other_zone = active.replace(
            b"Litoral sur de Alicante", b"Interior de Alicante"
        )
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

        warnings = normalize_warnings(
            self._archive(active, other_zone), now
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].level, "orange")
        self.assertEqual(warnings[0].event, "Temperaturas maximas")

    def test_reads_current_aemet_tar_archive_format(self):
        active = b"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <status>Actual</status><info><language>es-ES</language>
          <event>Viento</event><severity>Moderate</severity>
          <expires>2026-07-26T20:00:00+02:00</expires>
          <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
          </info></alert>"""
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

        warnings = normalize_warnings(
            self._tar_archive(active),
            now,
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].level, "yellow")

    def test_omits_expired_warning(self):
        expired = b"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <status>Actual</status><info><language>es-ES</language>
          <event>Viento</event><severity>Moderate</severity>
          <expires>2026-07-26T08:00:00+00:00</expires>
          <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
          </info></alert>"""
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(normalize_warnings(expired, now), ())

    def test_includes_warning_starting_later_today(self):
        upcoming = b"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <status>Actual</status><info><language>es-ES</language>
          <event>Viento</event><severity>Moderate</severity>
          <onset>2026-07-26T18:00:00+02:00</onset>
          <expires>2026-07-26T23:00:00+02:00</expires>
          <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
          </info></alert>"""
        now = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)

        warnings = normalize_warnings(upcoming, now)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event, "Viento")

    def test_omits_minor_cap_status_because_aemet_defines_it_as_no_warning(self):
        no_warning = b"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <status>Actual</status><info><language>es-ES</language>
          <event>Sin aviso</event><severity>Minor</severity>
          <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
          </info></alert>"""
        now = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)

        self.assertEqual(normalize_warnings(no_warning, now), ())


class AemetCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_policy_retries_twice_after_two_minutes(self):
        from telegrambot.aemet import fetch_morning_digest

        with patch(
            "telegrambot.aemet._fetch_product",
            new=AsyncMock(side_effect=AemetError("temporary")),
        ) as fetch_mock, patch(
            "telegrambot.aemet.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep_mock:
            with self.assertRaises(AemetError):
                await fetch_morning_digest(
                    "key",
                    datetime(
                        2026,
                        7,
                        29,
                        10,
                        10,
                        tzinfo=ZoneInfo("Europe/Madrid"),
                    ),
                )

        self.assertEqual(fetch_mock.await_count, 3)
        self.assertEqual(
            [call.args for call in sleep_mock.await_args_list],
            [(120,), (120,)],
        )

    async def test_retries_required_daily_forecast_once(self):
        from telegrambot.aemet import fetch_morning_digest

        daily = (
            b'[{"prediccion":{"dia":[{"fecha":"2026-07-27",'
            b'"temperatura":{"minima":23,"maxima":30},'
            b'"viento":[{"direccion":"E","velocidad":15}]}]}}]'
        )
        products = [
            AemetError("temporary"),
            daily,
            b"[]",
            b"<alerts></alerts>",
            (
                b'[{"prediccion":{"dia":['
                b'{"fecha":20260727,"tAgua":{"valor1":29}}]}}]'
            ),
        ]

        async def fetch_product(*_args):
            result = products.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch(
            "telegrambot.aemet._fetch_product",
            new=AsyncMock(side_effect=fetch_product),
        ) as fetch_mock, patch(
            "telegrambot.aemet.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep_mock:
            digest = await fetch_morning_digest(
                "key",
                datetime(
                    2026,
                    7,
                    27,
                    8,
                    tzinfo=ZoneInfo("Europe/Madrid"),
                ),
            )

        self.assertEqual(digest.weather.maximum_temperature_c, 30)
        self.assertEqual(fetch_mock.await_count, 5)
        self.assertEqual(digest.forecast_sea_temperature_c, 29)
        self.assertIsNone(digest.forecast_sea_state)
        sleep_mock.assert_awaited_once_with(120)

    async def test_fetches_products_sequentially(self):
        from telegrambot.aemet import fetch_morning_digest

        daily = json.dumps(
            [
                {
                    "prediccion": {
                        "dia": [
                            {
                                "fecha": "2026-07-26T00:00:00",
                                "temperatura": {
                                    "minima": 22,
                                    "maxima": 31,
                                },
                                "viento": [
                                    {
                                        "direccion": "E",
                                        "velocidad": 20,
                                    }
                                ],
                            }
                        ]
                    }
                }
            ]
        ).encode()
        observation = json.dumps(
            [
                {
                    "fint": "2026-07-26T06:00:00+00:00",
                    "ta": 23,
                    "dv": 90,
                    "vv": 10 / 3.6,
                }
            ]
        ).encode()
        warnings = b"<alerts></alerts>"
        beach = (
            b'[{"prediccion":{"dia":['
            b'{"fecha":20260726,"tAgua":{"valor1":28}}]}}]'
        )
        active = 0
        peak = 0
        payloads = iter((daily, observation, warnings, beach))

        async def fetch_product(path, api_key, limit):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await __import__("asyncio").sleep(0)
            active -= 1
            return next(payloads)

        now = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
        with patch(
            "telegrambot.aemet._fetch_product",
            new=AsyncMock(side_effect=fetch_product),
        ) as fetch:
            digest = await fetch_morning_digest("key", now)

        self.assertEqual(fetch.await_count, 4)
        self.assertEqual(peak, 1)
        self.assertEqual(digest.weather.maximum_temperature_c, 31)
        self.assertEqual(digest.weather.wind_speed_kmh, 10)
        self.assertEqual(digest.weather.forecast_wind_speed_kmh, 20)
        self.assertEqual(digest.forecast_sea_temperature_c, 28)


if __name__ == "__main__":
    unittest.main()
