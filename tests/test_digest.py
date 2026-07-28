import unittest
from datetime import datetime, timezone

from telegrambot.digest import build_message
from telegrambot.models import (
    BeachStatus,
    Event,
    MorningDigest,
    TrafficNotice,
    Warning,
    Weather,
)


class DigestMessageTests(unittest.TestCase):
    def test_builds_short_message_with_warning(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=23.4,
                minimum_temperature_c=21,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=12,
                observed_at=datetime(
                    2026, 7, 26, 6, 0, tzinfo=timezone.utc
                ),
                forecast_wind_speed_kmh=18,
                sky_condition="storm",
            ),
            warnings=(
                Warning(
                    event="Temperaturas maximas",
                    level="orange",
                    ends_at=None,
                ),
            ),
            warnings_available=True,
            beach=BeachStatus(
                flag_color="green",
                sea_temperature_c=24,
                sea_state="moderate",
                nearby_flags=(
                    ("Vivers", "green"),
                    ("Centre", "green"),
                    ("Roqueta", "yellow"),
                ),
                jellyfish_beaches=("Roqueta",),
            ),
            forecast_sea_temperature_c=29,
            traffic_notices=(
                TrafficNotice(
                    text=(
                        "15–29 июля: проезд к поликлинике и "
                        "автовокзалу — только через C/ San Francisco."
                    )
                ),
            ),
            events=(
                Event(
                    title="Концерт в замке",
                    starts_at=datetime(
                        2026,
                        7,
                        26,
                        21,
                        0,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )

        message = build_message(digest)

        self.assertTrue(
            message.startswith("🌅 Доброе утро, Гуардамар!\n\n")
        )
        self.assertNotIn("Rojales", message)
        self.assertNotIn("дайджест", message.casefold())
        self.assertIn("⛈️ Погода   21° → 30°", message)
        self.assertIn(
            "🌊 Centre    24° • волнение умеренное",
            message,
        )
        self.assertIn(
            "🏖 Флаги    🟡 Roqueta • 🟢 Vivers, Centre",
            message,
        )
        self.assertIn("🪼 Медузы    Roqueta", message)
        self.assertIn("💨 Ветер    В 3 → 5 м/с", message)
        self.assertIn("\n\n⚠️ Внимание\n", message)
        self.assertIn(
            (
                "Оранжевое предупреждение: "
                "высокая температура."
            ),
            message,
        )
        self.assertNotIn("AEMET", message)
        self.assertNotIn("Источник", message)
        self.assertIn(
            (
                "\n\n🚧 Движение ограничено\n15–29 июля: проезд к "
                "поликлинике и автовокзалу — только через "
                "C/ San Francisco."
            ),
            message,
        )
        self.assertIn(
            "\n\n📅 События\n• 23:00 — Концерт в замке",
            message,
        )
        self.assertLess(len(message), 380)

    def test_uses_mandatory_rows_and_omits_unavailable_optional_section(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=21,
                maximum_temperature_c=30,
                wind_direction=None,
                wind_speed_kmh=None,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=False,
            forecast_sea_temperature_c=28,
        )

        message = build_message(digest)

        self.assertIn("🌤 Погода   21° → 30°", message)
        self.assertIn("🌊 Centre    28°", message)
        self.assertNotIn("🏖 Флаги", message)
        self.assertNotIn("🪼 Медузы", message)
        self.assertIn("💨 Ветер    —", message)
        self.assertNotIn("⚠️ Внимание", message)
        self.assertNotIn("Предупреждений нет", message)

    def test_labels_all_day_exhibition_without_inventing_time(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=22,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=True,
            events=(
                Event(
                    title="Средиземноморье, язык воды",
                    starts_at=None,
                    place="Casa de Cultura",
                    category="exhibition",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "• Выставка «Средиземноморье, язык воды»"
            " — Casa de Cultura",
            message,
        )
        self.assertNotIn("00:00", message)

    def test_formats_market_time_range_and_place(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=22,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=11,
                observed_at=None,
            ),
            warnings=(),
            warnings_available=True,
            events=(
                Event(
                    title="Рынок",
                    starts_at=datetime(
                        2026, 7, 29, 7, 0, tzinfo=timezone.utc
                    ),
                    ends_at=datetime(
                        2026, 7, 29, 13, 30, tzinfo=timezone.utc
                    ),
                    place="парковка La Redonda",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "• 09:00–15:30 — Рынок, парковка La Redonda",
            message,
        )


if __name__ == "__main__":
    unittest.main()
