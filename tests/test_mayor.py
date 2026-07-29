import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import MorningDigest, Weather
from telegrambot.morning import produce_message
from telegrambot.mayor import (
    extract_recent_posts,
    latest_beach_notice,
    market_is_cancelled,
    validate_market_status,
)

TZ = ZoneInfo("Europe/Madrid")


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
