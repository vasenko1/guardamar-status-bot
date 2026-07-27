import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import MorningDigest, Weather
from telegrambot.morning import produce_message
from telegrambot.police import (
    PoliceTrafficError,
    normalize_traffic_page,
    validate_ai_notice,
)

MADRID = ZoneInfo("Europe/Madrid")
NOTICE_PAGE = """
<html><body>
<p>
TENGA EN CUENTA QUE PARA ACCEDER AL CENTRO DE SALUD Y TERMINAL DE
AUTOBUSES DEBE ACCEDER DESDE LA C/SAN FRANCISCO, YA QUE EL RESTO DE
ACCESOS ESTARÁN CERRADOS AL TRÁFICO, DURANTE EL PERÍODO DE FIESTAS,
ESTO ES, DESDE EL 15 AL 29 DE JULIO.
</p>
</body></html>
""".encode()


class PoliceTrafficNormalizationTests(unittest.TestCase):
    def test_includes_explicit_notice_during_validity_window(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 27, 7, 30, tzinfo=MADRID),
        )

        self.assertEqual(len(notices), 1)
        self.assertEqual(
            notices[0].text,
            (
                "До 29 июля: проезд к поликлинике и автовокзалу — "
                "только через C/ San Francisco."
            ),
        )

    def test_keeps_full_range_on_first_day(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 15, 7, 30, tzinfo=MADRID),
        )

        self.assertTrue(notices[0].text.startswith("15–29 июля:"))

    def test_omits_notice_outside_validity_window(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 30, 7, 30, tzinfo=MADRID),
        )

        self.assertEqual(notices, ())

    def test_accepts_grounded_ai_translation(self):
        source = (
            "Corte de tráfico. Del 5 al 7 de agosto estará cerrada "
            "C/ Mayor por obras."
        )
        candidate = {
            "publish": True,
            "evidence_es": source,
            "message_ru": (
                "5–7 августа: C/ Mayor перекрыта из-за дорожных работ."
            ),
            "streets": ["C/ Mayor"],
            "start_day": 5,
            "start_month": 8,
            "end_day": 7,
            "end_month": 8,
        }

        notices = validate_ai_notice(
            candidate,
            source,
            datetime(2026, 8, 6, 7, 30, tzinfo=MADRID),
        )

        self.assertEqual(len(notices), 1)
        self.assertEqual(
            notices[0].text,
            "До 7 августа: C/ Mayor перекрыта из-за дорожных работ.",
        )

    def test_rejects_ai_invented_street_and_inactive_date(self):
        source = (
            "Corte de tráfico. Del 5 al 7 de agosto estará cerrada "
            "C/ Mayor por obras."
        )
        candidate = {
            "publish": True,
            "evidence_es": source,
            "message_ru": "5–7 августа: C/ Alicante перекрыта.",
            "streets": ["C/ Alicante"],
            "start_day": 5,
            "start_month": 8,
            "end_day": 7,
            "end_month": 8,
        }

        self.assertEqual(
            validate_ai_notice(
                candidate,
                source,
                datetime(2026, 8, 6, 7, 30, tzinfo=MADRID),
            ),
            (),
        )
        candidate["streets"] = ["C/ Mayor"]
        candidate["message_ru"] = "5–7 августа: C/ Mayor перекрыта."
        self.assertEqual(
            validate_ai_notice(
                candidate,
                source,
                datetime(2026, 8, 8, 7, 30, tzinfo=MADRID),
            ),
            (),
        )

    def test_omits_page_without_explicit_access_and_dates(self):
        notices = normalize_traffic_page(
            b"<html><body>Eventos y cortes de trafico.</body></html>",
            datetime(2026, 7, 27, 7, 30, tzinfo=MADRID),
        )

        self.assertEqual(notices, ())


class PoliceTrafficFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_inactive_notice_does_not_consume_gemini(self):
        with (
            patch(
                "telegrambot.police._read_page",
                return_value=NOTICE_PAGE,
            ),
            patch(
                "telegrambot.police.translate_traffic_notice",
                new=AsyncMock(),
            ) as translate,
        ):
            from telegrambot.police import fetch_traffic_notices

            notices = await fetch_traffic_notices(
                datetime(2026, 7, 30, 7, 30, tzinfo=MADRID),
                "gemini-key",
            )

        self.assertEqual(notices, ())
        translate.assert_not_awaited()

    async def test_failure_omits_traffic_without_blocking_weather(self):
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
        now = datetime(2026, 7, 27, 7, 30, tzinfo=MADRID)

        with (
            patch(
                "telegrambot.morning.fetch_morning_digest",
                new=AsyncMock(return_value=digest),
            ),
            patch(
                "telegrambot.morning.fetch_beach_status",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "telegrambot.morning.fetch_today_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(
                    side_effect=PoliceTrafficError("temporarily unavailable")
                ),
            ),
        ):
            message = await produce_message("api-key", now)

        self.assertNotIn("🚧 Движение ограничено", message)
        self.assertIn("🌤 Погода", message)


if __name__ == "__main__":
    unittest.main()
