import unittest
from datetime import date, datetime
from email.message import Message
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import MorningDigest, Weather
from telegrambot.morning import produce_message
from telegrambot.mayor import (
    MayorChannelError,
    _fiestas_de_barrio_events,
    _read_page,
    extract_recent_posts,
    latest_beach_notice,
    market_is_cancelled,
    validate_market_status,
)

TZ = ZoneInfo("Europe/Madrid")


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
        return "https://t.me/s/AlcaldeGuardamar"


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class _TimeoutOpener:
    def open(self, request, timeout):
        raise TimeoutError("timed out")


def page(text, timestamp="2026-07-28T18:00:00+00:00"):
    return f"""
    <div class="tgme_widget_message_wrap js-widget_message_wrap">
      <div class="tgme_widget_message_text js-message_text">
        {text}
      </div>
      <time datetime="{timestamp}" class="time">20:00</time>
    </div>
    """.encode()


class MayorChannelTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_html_without_channel_message_structure(self):
        with self.assertRaises(MayorChannelError) as raised:
            extract_recent_posts(
                b"<html><body>Temporary page</body></html>",
                datetime(2026, 7, 29, 7, 30, tzinfo=TZ),
            )

        self.assertEqual(
            raised.exception.diagnostic_code,
            "INVALID-STRUCTURE",
        )

    def test_rejects_non_html_channel_response(self):
        with patch(
            "telegrambot.mayor.urllib.request.build_opener",
            return_value=_Opener(_Response("application/json")),
        ):
            with self.assertRaises(MayorChannelError) as raised:
                _read_page()

        self.assertEqual(
            raised.exception.diagnostic_code,
            "CONTENT-TYPE",
        )

    def test_describes_public_page_network_timeout_precisely(self):
        with patch(
            "telegrambot.mayor.urllib.request.build_opener",
            return_value=_TimeoutOpener(),
        ):
            with self.assertRaises(MayorChannelError) as raised:
                _read_page()

        self.assertEqual(raised.exception.diagnostic_code, "TIMEOUT")
        self.assertEqual(
            raised.exception.safe_description,
            "сетевой тайм-аут при загрузке публичной страницы "
            "канала t.me (лимит сетевой операции — 10 с)",
        )

    def test_extracts_only_recent_timestamped_text(self):
        now = datetime(2026, 7, 29, 7, 30, tzinfo=TZ)

        posts = extract_recent_posts(
            page(
                "El mercadillo no se celebrará mañana.<br>Información municipal"
            ),
            now,
        )

        self.assertEqual(len(posts), 1)
        self.assertIn("mercadillo", posts[0][1])
        self.assertIn("Información municipal", posts[0][1])

    def test_requires_exact_dated_cancellation_evidence(self):
        source = (
            "El mercadillo del miércoles 29 de julio queda suspendido."
        )
        candidate = {
            "cancelled": True,
            "evidence_es": source,
            "event_date": "2026-07-29",
        }

        self.assertTrue(
            validate_market_status(candidate, source, date(2026, 7, 29))
        )
        candidate["evidence_es"] = (
            "El mercado del miércoles queda suspendido."
        )
        self.assertFalse(
            validate_market_status(candidate, source, date(2026, 7, 29))
        )

    def test_extracts_today_fiestas_de_barrio_with_full_location(self):
        text = (
            "Este fin de semana llegan las FIESTAS DE BARRIO. "
            "Viernes 31 de julio, desde las 19:00 h., Urbanizaciones "
            "Moncayo, Pórtico Mediterráneo, Larrosa y La Laguna. "
            "Ubicación parque C/ Berlín. "
            "Sábado 1 de agosto, desde de las 18:00 h., Urbanización "
            "Pinomar Lomas del Polo. Ubicación: Frente piscina."
        )

        events = _fiestas_de_barrio_events(
            text,
            date(2026, 7, 31),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].title,
            "Праздник районов Moncayo, Pórtico Mediterráneo, "
            "Larrosa и La Laguna",
        )
        self.assertEqual(events[0].starts_at.hour, 19)
        self.assertEqual(events[0].place, "parque C/ Berlín")

    def test_extracts_singular_tourism_agenda_wording(self):
        events = _fiestas_de_barrio_events(
            (
                "FIESTA DE BARRIO Viernes 31 de julio, a partir de "
                "las 19:00 h. Parque C/ Berlín. URBANIZACIONES MONCAYO."
            ),
            date(2026, 7, 31),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].place, "Parque C/ Berlín")

    async def test_skips_gemini_when_no_market_post_exists(self):
        now = datetime(2026, 7, 29, 7, 30, tzinfo=TZ)
        with (
            patch(
                "telegrambot.mayor._read_page",
                return_value=page("Concierto esta noche."),
            ),
            patch(
                "telegrambot.mayor.extract_market_status",
                new=AsyncMock(),
            ) as extract,
        ):
            cancelled = await market_is_cancelled(now, "key")

        self.assertFalse(cancelled)
        extract.assert_not_awaited()

    async def test_checks_a_market_moved_to_tuesday(self):
        now = datetime(2026, 6, 23, 7, 30, tzinfo=TZ)
        with (
            patch(
                "telegrambot.mayor._read_page",
                return_value=page(
                    "El mercadillo del martes 23 de junio queda suspendido.",
                    "2026-06-22T18:00:00+00:00",
                ),
            ),
            patch(
                "telegrambot.mayor.extract_market_status",
                new=AsyncMock(
                    return_value={
                        "cancelled": True,
                        "evidence_es": (
                            "El mercadillo del martes 23 de junio "
                            "queda suspendido."
                        ),
                        "event_date": "2026-06-23",
                    }
                ),
            ),
        ):
            cancelled = await market_is_cancelled(now, "key")

        self.assertTrue(cancelled)

    async def test_extracts_new_explicit_bathing_restriction(self):
        now = datetime(2026, 7, 29, 10, 40, tzinfo=TZ)
        since = datetime(2026, 7, 29, 7, 30, tzinfo=TZ)
        with patch(
            "telegrambot.mayor._read_page",
            return_value=page(
                "BANDERA ROJA. PROHIBIDO EL BAÑO por fuertes "
                "corrientes y oleaje.",
                "2026-07-29T08:15:00+00:00",
            ),
        ):
            notice = await latest_beach_notice(now, since)

        self.assertTrue(notice.bathing_prohibited)
        self.assertEqual(
            notice.text,
            "Купание запрещено: течения, волны.",
        )

    async def test_explicit_cancellation_hides_recurring_market(self):
        now = datetime(2026, 7, 29, 7, 30, tzinfo=TZ)
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=23,
                maximum_temperature_c=31,
                wind_direction="E",
                wind_speed_kmh=11,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=True,
        )
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
                "telegrambot.morning.fetch_today_municipal_events",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.fetch_traffic_notices",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "telegrambot.morning.market_is_cancelled",
                new=AsyncMock(return_value=True),
            ),
        ):
            message = await produce_message(
                "aemet-key", now, "gemini-key"
            )

        self.assertNotIn("Рынок", message)


if __name__ == "__main__":
    unittest.main()
