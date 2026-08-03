import unittest
from datetime import date, datetime, time, timedelta, timezone

from telegrambot.digest import build_fallback_update, build_message
from telegrambot.models import (
    BeachStatus,
    Event,
    Holiday,
    MorningDigest,
    TrafficNotice,
    Warning,
    Weather,
)


class DigestMessageTests(unittest.TestCase):
    @staticmethod
    def _routine_digest(**changes):
        values = {
            "weather": Weather(
                current_temperature_c=None,
                minimum_temperature_c=22,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
            ),
            "warnings": (),
            "warnings_available": True,
        }
        values.update(changes)
        return MorningDigest(**values)

    def test_renders_weekday_holiday_before_events(self):
        digest = self._routine_digest(
            holidays=(
                Holiday(
                    date(2026, 7, 24),
                    "Канун Дня святого Иакова",
                    "local",
                ),
            ),
            events=(
                Event(
                    title="Концерт",
                    starts_at=None,
                    place="Castillo",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "🎉 <b>Праздник сегодня:</b>\n"
            "• Канун Дня святого Иакова — "
            "официальный городской праздник\n"
            "  🏛️ Официальный праздничный выходной.",
            message,
        )
        self.assertLess(
            message.index("🎉 <b>Праздник сегодня:</b>"),
            message.index("📅 <b>События дня:</b>"),
        )

    def test_weekend_holiday_omits_extra_day_off_line(self):
        digest = self._routine_digest(
            holidays=(
                Holiday(
                    date(2026, 8, 15),
                    "Успение Богородицы",
                    "national",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "• Успение Богородицы — национальный праздник",
            message,
        )
        self.assertNotIn("Официальный праздничный выходной", message)

    def test_orders_coincident_holidays_by_scope(self):
        holiday_date = date(2026, 10, 12)
        digest = self._routine_digest(
            holidays=(
                Holiday(holiday_date, "Местный день", "local"),
                Holiday(holiday_date, "Региональный день", "regional"),
                Holiday(holiday_date, "Национальный день", "national"),
            ),
        )

        message = build_message(digest)

        self.assertIn("🎉 <b>Праздники сегодня:</b>", message)
        self.assertLess(
            message.index("Национальный день"),
            message.index("Региональный день"),
        )
        self.assertLess(
            message.index("Региональный день"),
            message.index("Местный день"),
        )

    def test_unknown_holiday_scope_does_not_render_empty_section(self):
        digest = self._routine_digest(
            holidays=(
                Holiday(date(2026, 1, 1), "Неизвестный", "province"),
            ),
        )

        message = build_message(digest)

        self.assertNotIn("🎉", message)

    def test_collapses_equal_rendered_sky_conditions(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=24,
                maximum_temperature_c=31,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
                sky_conditions=("partly_cloudy", "partly_cloudy"),
            ),
            warnings=(),
            warnings_available=True,
        )

        message = build_message(digest)

        self.assertIn("малооблачно", message)
        self.assertNotIn("малооблачно → малооблачно", message)

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
                rain_probability_percent=80,
                rain_period="12:00–18:00",
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
                updated_times=(
                    ("Vivers", time(15, 54)),
                    ("Centre", time(15, 56)),
                    ("Roqueta", time(15, 55)),
                ),
            ),
            forecast_sea_temperature_c=29,
            forecast_sea_state="slight",
            forecast_later_sea_state="moderate",
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
        self.assertIn("☀️ <b>Погода от AEMET:</b>", message)
        self.assertIn("⛈️ Воздух: 21° → 30° • гроза", message)
        self.assertIn("🌧 Дождь: 80% • 12:00–18:00", message)
        self.assertIn(
            "🌊 Море: 29° • слабые → умеренные",
            message,
        )
        self.assertIn(
            "🏖 <b>Флаги на пляжах:</b>\n"
            "   🟡 Roqueta\n"
            "   🟢 Centre / Babilònia, Vivers",
            message,
        )
        self.assertIn("🪼 Медузы: Roqueta", message)
        self.assertNotIn("15:56", message)
        self.assertIn("💨 Ветер: В 3 → 5 м/с", message)
        self.assertLess(message.index("⛈️ Воздух:"), message.index("💨 Ветер:"))
        self.assertLess(message.index("💨 Ветер:"), message.index("🌊 Море:"))
        self.assertIn(
            "\n\n⚠️ <b>Предупреждения AEMET:</b>\n"
            "Зона: южное побережье Аликанте\n",
            message,
        )
        self.assertIn(
            "🟠 <b>Высокая температура</b>",
            message,
        )
        self.assertIn("AEMET", message)
        self.assertIn(
            (
                "\n\n🚧 <b>Движение:</b>\n15–29 июля: проезд к "
                "поликлинике и автовокзалу — только через "
                "C/ San Francisco."
            ),
            message,
        )
        self.assertIn(
            "\n\n📅 <b>События дня:</b>\n"
            "• <b>23:00</b> — Концерт в замке",
            message,
        )
        rendered = message.replace("<b>", "").replace("</b>", "")
        self.assertLess(len(rendered), 500)

    def test_omits_rain_below_threshold(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=21,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
                rain_probability_percent=74,
                rain_period="12:00–18:00",
            ),
            warnings=(),
            warnings_available=True,
        )

        self.assertNotIn("🌧 Дождь", build_message(digest))

    def test_includes_rain_at_threshold(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=21,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
                rain_probability_percent=75,
                rain_period="18:00–24:00",
            ),
            warnings=(),
            warnings_available=True,
        )

        self.assertIn(
            "🌧 Дождь: 75% • 18:00–24:00",
            build_message(digest),
        )

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

        self.assertIn("🌤 Воздух: 21° → 30°", message)
        self.assertIn("🌊 Море: 28°", message)
        self.assertNotIn("🏖 Флаги", message)
        self.assertNotIn("🪼 Медузы", message)
        self.assertIn("💨 Ветер: —", message)
        self.assertNotIn("⚠️ <b>Предупреждения AEMET:</b>", message)
        self.assertNotIn("Предупреждений нет", message)

    def test_marks_multiple_warnings_and_traffic_items(self):
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=21,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=12,
                observed_at=None,
                sky_conditions=("clear", "cloudy"),
            ),
            warnings=(
                Warning("Viento", "yellow", None),
                Warning("Lluvias", "orange", None),
            ),
            warnings_available=True,
            traffic_notices=(
                TrafficNotice(text="Перекрыта улица A."),
                TrafficNotice(text="Изменён маршрут автобуса B."),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "🌤 Воздух: 21° → 30° • ясно → облачно",
            message,
        )
        self.assertIn(
            "⚠️ <b>Предупреждения AEMET:</b>\n"
            "Зона: южное побережье Аликанте\n"
            "🟠 <b>Сильный дождь</b>\n"
            "🟡 <b>Сильный ветер</b>",
            message,
        )
        self.assertIn(
            "🚧 <b>Движение:</b>\n"
            "• Перекрыта улица A.\n"
            "• Изменён маршрут автобуса B.",
            message,
        )

    def test_future_warning_shows_exact_start_and_end(self):
        madrid = timezone(timedelta(hours=2))
        digest = MorningDigest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=23,
                maximum_temperature_c=31,
                wind_direction=None,
                wind_speed_kmh=None,
                observed_at=None,
            ),
            warnings=(
                Warning(
                    "Aviso de tormentas de nivel amarillo",
                    "yellow",
                    datetime(2026, 8, 1, 21, 59, 59, tzinfo=madrid),
                    starts_at=datetime(2026, 8, 1, 16, 0, tzinfo=madrid),
                    description=(
                        "Posibles rachas muy fuertes de viento, granizo y "
                        "chubascos localmente fuertes."
                    ),
                    probability="40–70%",
                ),
            ),
            warnings_available=True,
        )

        message = build_message(
            digest,
            now=datetime(2026, 8, 1, 7, 30, tzinfo=madrid),
        )

        self.assertIn(
            "🟡 <b>Грозы</b>\n"
            "   Сегодня · 16:00–21:59 · вероятность 40–70%",
            message,
        )
        self.assertIn(
            "Возможны очень сильные порывы ветра, град и местами сильные "
            "ливни.",
            message,
        )

    def test_groups_identical_warning_for_today_and_tomorrow(self):
        madrid = timezone(timedelta(hours=2))
        warnings = tuple(
            Warning(
                "Temperaturas maximas",
                "yellow",
                datetime(2026, 8, day, 20, 59, tzinfo=madrid),
                starts_at=datetime(2026, 8, day, 13, 0, tzinfo=madrid),
                probability="40–70%",
            )
            for day in (3, 4)
        )
        digest = MorningDigest(
            weather=Weather(None, 24, 32, None, None, None),
            warnings=warnings,
            warnings_available=True,
        )

        message = build_message(
            digest,
            now=datetime(2026, 8, 3, 7, 30, tzinfo=madrid),
        )

        self.assertEqual(message.count("<b>Высокая температура</b>"), 1)
        self.assertIn(
            "   Сегодня и завтра · 13:00–20:59 · вероятность 40–70%",
            message,
        )

    def test_keeps_different_warning_intervals_separate(self):
        madrid = timezone(timedelta(hours=2))
        digest = MorningDigest(
            weather=Weather(None, 24, 32, None, None, None),
            warnings=(
                Warning(
                    "Temperaturas maximas",
                    "yellow",
                    datetime(2026, 8, 3, 20, 59, tzinfo=madrid),
                    starts_at=datetime(2026, 8, 3, 13, 0, tzinfo=madrid),
                    probability="40–70%",
                ),
                Warning(
                    "Temperaturas maximas",
                    "yellow",
                    datetime(2026, 8, 4, 20, 59, tzinfo=madrid),
                    starts_at=datetime(2026, 8, 4, 14, 0, tzinfo=madrid),
                    probability="40–70%",
                ),
            ),
            warnings_available=True,
        )

        message = build_message(
            digest,
            now=datetime(2026, 8, 3, 7, 30, tzinfo=madrid),
        )

        self.assertIn(
            "   Сегодня · 13:00–20:59 · вероятность 40–70%\n"
            "   Завтра · 14:00–20:59 · вероятность 40–70%",
            message,
        )
        self.assertNotIn("Сегодня и завтра", message)

    def test_does_not_limit_hazardous_warnings_to_two(self):
        digest = MorningDigest(
            weather=Weather(None, 20, 30, None, None, None),
            warnings=(
                Warning("Viento", "yellow", None),
                Warning("Lluvias", "orange", None),
                Warning("Tormentas", "red", None),
            ),
            warnings_available=True,
        )

        message = build_message(digest)

        self.assertIn("<b>Сильный ветер</b>", message)
        self.assertIn("<b>Сильный дождь</b>", message)
        self.assertIn("<b>Грозы</b>", message)
        self.assertNotIn("Ещё предупреждений", message)

    def test_escapes_source_text_for_telegram_html(self):
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
            warnings_available=True,
            events=(
                Event(
                    title="Музыка <джаз> & танцы",
                    starts_at=None,
                    place="Sala <A>",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "• Музыка &lt;джаз&gt; &amp; танцы\n"
            "  📍 Sala &lt;A&gt;",
            message,
        )

    def test_uses_one_label_when_sea_state_does_not_change(self):
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
            beach=BeachStatus(
                flag_color=None,
                sea_temperature_c=27,
            ),
            forecast_sea_temperature_c=29,
            forecast_sea_state="moderate",
            forecast_later_sea_state="moderate",
        )

        message = build_message(digest)

        self.assertIn("🌊 Море: 29° • умеренные волны", message)
        self.assertNotIn("умеренные → умеренные", message)

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
            "• Выставка «Средиземноморье, язык воды»\n"
            "  📍 Casa de Cultura",
            message,
        )
        self.assertNotIn("00:00", message)

    def test_marks_confirmed_final_day(self):
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
                    title=(
                        "Выставка «Средиземноморье, язык воды»"
                    ),
                    starts_at=datetime(
                        2026, 8, 14, 7, 0, tzinfo=timezone.utc
                    ),
                    ends_at=datetime(
                        2026, 8, 14, 18, 0, tzinfo=timezone.utc
                    ),
                    place="Casa de Cultura",
                    category="exhibition",
                    is_final_day=True,
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "• <b>09:00–20:00</b> — Последний день: "
            "Выставка «Средиземноморье, язык воды»",
            message,
        )

    def test_quotes_explicit_exhibition_name_after_category(self):
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
                    title=(
                        "Выставка живописи и скульптуры: "
                        "Средиземноморье, язык воды"
                    ),
                    starts_at=datetime(
                        2026, 7, 30, 7, 0, tzinfo=timezone.utc
                    ),
                    ends_at=datetime(
                        2026, 7, 30, 18, 0, tzinfo=timezone.utc
                    ),
                    place="Sala de exposiciones Casa de Cultura",
                    category="exhibition",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "Выставка живописи и скульптуры "
            "«Средиземноморье, язык воды»",
            message,
        )
        self.assertNotIn(
            "скульптуры: Средиземноморье",
            message,
        )

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
            "• <b>09:00–15:30</b> — Рынок\n"
            "  📍 парковка La Redonda",
            message,
        )

    def test_fallback_preserves_morning_copy_and_adds_beach_update(self):
        morning = (
            "🌅 Доброе утро, Гуардамар!\n\n"
            "☀️ <b>Погода от AEMET:</b>\n"
            "🌤 Воздух: 22° → 30°\n"
            "💨 Ветер: В 3 → 5 м/с\n"
            "🌊 Море: 27° • умеренные волны\n\n"
            "📅 <b>События дня:</b>\n• Выставка"
        )
        beach = BeachStatus(
            flag_color="yellow",
            sea_temperature_c=28,
            nearby_flags=(
                ("Vivers", "green"),
                ("Centre", "yellow"),
                ("Roqueta", "red"),
            ),
            jellyfish_beaches=("Roqueta",),
        )

        updated = build_fallback_update(morning, beach, None)

        self.assertIn("🌤 Воздух: 22° → 30°", updated)
        self.assertIn("🌊 Море: 27° • умеренные волны", updated)
        self.assertIn(
            "🌊 Море: 27° • умеренные волны\n\n"
            "🏖 <b>Флаги на пляжах:</b>\n"
            "   🔴 Roqueta\n"
            "   🟡 Centre / Babilònia\n"
            "   🟢 Vivers\n"
            "🪼 Медузы: Roqueta",
            updated,
        )
        self.assertTrue(
            updated.endswith("📅 <b>События дня:</b>\n• Выставка")
        )

    def test_omits_missing_beaches_and_flag_descriptions(self):
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
            beach=BeachStatus(
                flag_color="red",
                sea_temperature_c=27,
                nearby_flags=(("Centre", "red"),),
                flag_meanings=(("Centre", "купание запрещено"),),
            ),
        )

        message = build_message(digest)

        self.assertIn("   🔴 Centre / Babilònia", message)
        self.assertNotIn("Нет данных", message)
        self.assertNotIn("Roqueta", message)
        self.assertNotIn("Vivers", message)
        self.assertNotIn("купание запрещено", message)

    def test_renders_named_fallback_beaches_without_renaming(self):
        morning = (
            "🌅 Доброе утро, Гуардамар!\n\n"
            "☀️ <b>Погода от AEMET:</b>\n"
            "🌤 Воздух: 22° → 30°\n"
            "💨 Ветер: В 3 → 5 м/с\n"
            "🌊 Море: 27° • умеренные волны"
        )
        beach = BeachStatus(
            flag_color=None,
            sea_temperature_c=None,
            nearby_flags=(
                ("Roqueta", "yellow"),
                ("Vivers", "green"),
                ("Montcaio", "red"),
            ),
        )

        updated = build_fallback_update(morning, beach, None)

        self.assertIn("   🔴 Montcaio", updated)
        self.assertIn("   🟡 Roqueta", updated)
        self.assertIn("   🟢 Vivers", updated)
        self.assertNotIn("Centre / Babilònia", updated)

    def test_renders_all_events_and_expands_street_abbreviation(self):
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
            events=tuple(
                Event(
                    title=f"Событие {number}",
                    starts_at=datetime(
                        2026,
                        7,
                        31,
                        18 + number,
                        tzinfo=timezone.utc,
                    ),
                    place=(
                        "parque C/ Berlín"
                        if number == 1
                        else "Castell"
                    ),
                )
                for number in range(1, 4)
            ),
        )

        message = build_message(digest)

        self.assertEqual(message.count("\n• "), 3)
        self.assertIn("парк на улице Berlín", message)
        self.assertIn(
            "• <b>21:00</b> — Событие 1\n"
            "  📍 парк на улице Berlín\n\n"
            "• <b>22:00</b> — Событие 2\n"
            "  📍 Castell",
            message,
        )

    def test_removes_duplicate_exhibition_type_and_keeps_author(self):
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
            events=(
                Event(
                    title=(
                        'Выставка живописи: Выставка живописи '
                        '"Свет вопреки боли" — Вира Дегляренко'
                    ),
                    starts_at=None,
                    place="BIBLIOTECA MUNICIPAL GUARDAMAR DEL SEGURA",
                    category="exhibition",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "Выставка живописи «Свет вопреки боли» — Вира Дегляренко",
            message,
        )
        self.assertNotIn(
            "Выставка живописи: Выставка живописи",
            message,
        )


if __name__ == "__main__":
    unittest.main()
