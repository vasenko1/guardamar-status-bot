import unittest
from datetime import datetime
from email.message import Message
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import MorningDigest, Weather
from telegrambot.morning import produce_message
from telegrambot.police import (
    FESTIVAL_PDF_SHA256,
    PoliceTrafficError,
    _read_official,
    normalize_traffic_page,
    validate_ai_notice,
)

MADRID = ZoneInfo("Europe/Madrid")
NOTICE_PAGE = """
<html><body>
<a href="pdf/cortecalle_fiestas13.pdf">Cortes de tráfico</a>
</body></html>
""".encode()


class _Response:
    status = 200

    def __init__(self, content_type):
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return b"<html></html>"

    def geturl(self):
        return "https://policiaguardamar.com/page.html"


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class PoliceTrafficNormalizationTests(unittest.TestCase):
    def test_rejects_unexpected_official_content_type(self):
        with patch(
            "telegrambot.police.urllib.request.build_opener",
            return_value=_Opener(_Response("text/html")),
        ):
            with self.assertRaises(PoliceTrafficError) as raised:
                _read_official(
                    "https://policiaguardamar.com/file.pdf",
                    "application/pdf",
                    100_000,
                    "PDF",
                )

        self.assertEqual(
            raised.exception.diagnostic_code,
            "CONTENT-TYPE",
        )

    def test_includes_explicit_notice_during_validity_window(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 27, 7, 30, tzinfo=MADRID),
            FESTIVAL_PDF_SHA256,
        )

        self.assertEqual(len(notices), 1)
        self.assertEqual(
            notices[0].text,
            (
                "До 29 июля перекрыта улица Molivent. К поликлинике и "
                "автовокзалу — через La Redonda; легковым авто также "
                "через San Francisco до 23:30."
            ),
        )
        self.assertEqual(notices[0].measures[0].action, "road_closed")
        self.assertEqual(notices[0].measures[0].location, "Molivent")

    def test_keeps_full_range_on_first_day(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 22, 7, 30, tzinfo=MADRID),
            FESTIVAL_PDF_SHA256,
        )

        self.assertTrue(notices[0].text.startswith("22–29 июля"))

    def test_omits_notice_outside_validity_window(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 30, 7, 30, tzinfo=MADRID),
            FESTIVAL_PDF_SHA256,
        )

        self.assertEqual(notices, ())

    def test_rejects_changed_or_unreviewed_document(self):
        notices = normalize_traffic_page(
            NOTICE_PAGE,
            datetime(2026, 7, 27, 7, 30, tzinfo=MADRID),
            "changed",
        )

        self.assertEqual(notices, ())

    def test_accepts_grounded_ai_translation(self):
        source = (
            "Corte de tráfico. Del 5 al 7 de agosto estará cerrada "
            "C/ Mayor por obras."
        )
        candidate = {
            "publish": True,
            "measures": [{
                "action": "road_closed",
                "evidence_es": source,
                "message_ru": (
                    "5–7 августа: C/ Mayor перекрыта из-за дорожных работ."
                ),
                "location": "C/ Mayor",
                "streets": ["C/ Mayor"],
                "start_day": 5,
                "start_month": 8,
                "end_day": 7,
                "end_month": 8,
                "daily_hours": None,
                "affected": None,
                "exceptions": None,
                "alternative": None,
                "destinations": [],
            }],
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
            "measures": [{
                "action": "road_closed",
                "evidence_es": source,
                "message_ru": "5–7 августа: C/ Alicante перекрыта.",
                "location": "C/ Alicante",
                "streets": ["C/ Alicante"],
                "start_day": 5,
                "start_month": 8,
                "end_day": 7,
                "end_month": 8,
                "daily_hours": None,
                "affected": None,
                "exceptions": None,
                "alternative": None,
                "destinations": [],
            }],
        }

        self.assertEqual(
            validate_ai_notice(
                candidate,
                source,
                datetime(2026, 8, 6, 7, 30, tzinfo=MADRID),
            ),
            (),
        )
        candidate["measures"][0]["streets"] = ["C/ Mayor"]
        candidate["measures"][0]["location"] = "C/ Mayor"
        candidate["measures"][0]["message_ru"] = (
            "5–7 августа: C/ Mayor перекрыта."
        )
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
                "telegrambot.police._read_festival_pdf",
                return_value=b"changed",
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
                "telegrambot.morning.fetch_today_mayor_events",
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

        self.assertNotIn("🚧 <b>Движение:</b>", message)
        self.assertIn("🌤 Воздух", message)


if __name__ == "__main__":
    unittest.main()
