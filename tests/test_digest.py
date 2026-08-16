import unittest
from datetime import date, datetime, time, timedelta, timezone

from telegrambot.digest import (
    GUARDAMAR_TIMEZONE,
    build_message,
)
from telegrambot.models import (
    BeachNotice,
    BeachStatus,
    Event,
    Holiday,
    MorningDigest,
    PharmacyDuty,
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

    def test_renders_high_uv_and_sun_rows_inside_weather_block(self):
        digest = self._routine_digest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=22,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
                uv_index=9,
                sunrise=datetime(2026, 8, 15, 7, 10, tzinfo=GUARDAMAR_TIMEZONE),
                sunset=datetime(2026, 8, 15, 21, 0, tzinfo=GUARDAMAR_TIMEZONE),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "<b>Море:</b> —\n"
            "<b>УФ:</b> 9 (очень высокий)\n"
            "<b>Солнце:</b> 07:10 → 21:00",
            message,
        )

    def test_moderate_uv_is_omitted_and_sun_needs_both_times(self):
        digest = self._routine_digest(
            weather=Weather(
                current_temperature_c=None,
                minimum_temperature_c=22,
                maximum_temperature_c=30,
                wind_direction="E",
                wind_speed_kmh=10,
                observed_at=None,
                uv_index=5,
                sunrise=datetime(2026, 8, 15, 7, 10, tzinfo=GUARDAMAR_TIMEZONE),
                sunset=None,
            ),
        )

        message = build_message(digest)

        self.assertNotIn("УФ:", message)
        self.assertNotIn("Солнце:", message)

    def test_renders_duty_pharmacy_with_maps_link(self):
        digest = self._routine_digest(
            pharmacies=(PharmacyDuty(
                name="Planelles Mas, Asuncion",
                address="Av. Cervantes, 29",
                hours=(
                    "Круглосуточное дежурство с 09:00 16 августа "
                    "до 09:00 17 августа"
                ),
                municipality="Guardamar del Segura",
            ),),
        )

        message = build_message(digest)

        self.assertIn(
            "💊 <b>Дежурная аптека:</b>\n"
            "<b>Planelles Mas, Asuncion, Guardamar del Segura</b>\n"
            "Круглосуточное дежурство с 09:00 16 августа "
            "до 09:00 17 августа",
            message,
        )
        self.assertIn(
            "query=Av.+Cervantes%2C+29%2C+Guardamar+del+Segura",
            message,
        )
        self.assertNotIn("%C2%BA", message)
        self.assertNotIn("🏘", message)
        self.assertNotIn("🕐", message)
        self.assertNotIn("🕘", message)

    def test_renders_two_pharmacies_with_plural_heading_and_real_cities(self):
        digest = self._routine_digest(
            pharmacies=(
                PharmacyDuty(
                    name="Farmacia Ruiz Lozano",
                    address="C/ Amsterdam, 14",
                    hours=(
                        "Круглосуточное дежурство с 09:00 13 августа "
                        "до 09:00 14 августа"
                    ),
                    municipality="San Fulgencio",
                ),
                PharmacyDuty(
                    name="Farmacia Mora",
                    address="Av. Pais Valenciano, 29",
                    hours=(
                        "Дежурит с 09:00 13 августа "
                        "до 00:00 14 августа"
                    ),
                    municipality="Guardamar del Segura",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn("💊 <b>Дежурные аптеки:</b>", message)
        self.assertIn(
            "<b>Farmacia Ruiz Lozano, San Fulgencio</b>", message
        )
        self.assertIn(
            "query=Calle+Amsterdam%2C+14%2C+San+Fulgencio", message
        )
        self.assertIn(">Calle Amsterdam, 14</a>", message)
        self.assertIn(
            "<b>Farmacia Mora, Guardamar del Segura</b>", message
        )
        self.assertNotIn("• Farmacia", message)

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
            "  🏛️ Официальный выходной день.",
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
        self.assertNotIn("Официальный выходной", message)

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
        self.assertIn("⛈️ <b>Погода от AEMET:</b>", message)
        self.assertIn("<b>Воздух:</b> 21° → 30° • гроза", message)
        self.assertIn("<b>Дождь:</b> 80% • 12:00–18:00", message)
        self.assertIn(
            "<b>Море:</b> 29° • слабые → умеренные",
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
        self.assertIn("<b>Ветер:</b> В 3 → 5 м/с", message)
        self.assertLess(
            message.index("<b>Воздух:</b>"),
            message.index("<b>Ветер:</b>"),
        )
        self.assertLess(
            message.index("<b>Ветер:</b>"),
            message.index("<b>Море:</b>"),
        )
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
        self.assertLess(len(rendered), 600)

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

        self.assertNotIn("<b>Дождь:</b>", build_message(digest))

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
            "<b>Дождь:</b> 75% • 18:00–24:00",
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

        self.assertIn("🌤 <b>Погода от AEMET:</b>", message)
        self.assertIn("<b>Воздух:</b> 21° → 30°", message)
        self.assertIn("<b>Море:</b> 28°", message)
        self.assertNotIn("🏖 Флаги", message)
        self.assertNotIn("🪼 Медузы", message)
        self.assertIn("<b>Ветер:</b> —", message)
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
            "<b>Воздух:</b> 21° → 30° • ясно → облачно",
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

        self.assertIn("• Музыка &lt;джаз&gt; &amp; танцы", message)
        self.assertIn(
            'https://www.google.com/maps/search/?api=1&amp;query=',
            message,
        )
        self.assertIn(">Sala &lt;A&gt;</a>", message)

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

        self.assertIn("<b>Море:</b> 29° • умеренные волны", message)
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

        self.assertIn("• Выставка «Средиземноморье, язык воды»", message)
        self.assertIn(">Casa de Cultura</a>", message)
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
        self.assertIn(
            ">Casa de Cultura (Sala de exposiciones)</a>", message
        )
        self.assertNotIn(
            "скульптуры: Средиземноморье",
            message,
        )

    def test_ball_venue_keeps_park_first_in_map_label_and_query(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Летний танцевальный вечер Ball d’Estiu",
                starts_at=datetime(
                    2026, 8, 6, 21, 30, tzinfo=GUARDAMAR_TIMEZONE
                ),
                ends_at=datetime(
                    2026, 8, 6, 23, 30, tzinfo=GUARDAMAR_TIMEZONE
                ),
                place="Parque Reina Sofía (Auditorio Orquesta GÚMAR)",
                ticket_price_cents=0,
            ),),
        )

        message = build_message(digest)

        self.assertIn(
            ">Parque Reina Sofía (Auditorio Orquesta GÚMAR)</a>",
            message,
        )
        self.assertIn("query=Parque+Reina+Sof", message)
        self.assertIn("🎟 Бесплатно", message)

    def test_event_context_is_removed_before_building_map_link(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Занятие по керамике",
                starts_at=None,
                place=(
                    "Feria de comercio Guardamar 2026 de la "
                    "avenida de los Pinos"
                ),
            ),),
        )

        message = build_message(digest)

        self.assertIn(">Avenida de los Pinos</a>", message)
        self.assertIn("query=Avenida+de+los+Pinos%2C+Guardamar", message)
        self.assertNotIn("Feria+de+comercio", message)

    def test_unrecognized_event_prose_is_not_linked_as_a_place(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Городская встреча",
                starts_at=None,
                place="Evento municipal, lugar por confirmar",
            ),),
        )

        message = build_message(digest)

        self.assertIn("📍 Evento municipal, lugar por confirmar", message)
        self.assertNotIn("query=Evento+municipal", message)

    def test_placa_dels_llauradors_uses_coordinates_not_ambiguous_search(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Dixie Project",
                starts_at=None,
                place="Plaça dels Llauradors",
            ),),
        )

        message = build_message(digest)

        self.assertIn(
            "query=38.0921948%2C-0.6552320",
            message,
        )
        self.assertIn(">Plaça dels Llauradors</a>", message)
        self.assertNotIn("query=Plaza+Labradores", message)
        self.assertNotIn("query=Pla%C3%A7a+dels+Llauradors", message)

    def test_ticket_link_without_published_price_has_useful_label(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Благотворительный концерт TRIVOX",
                starts_at=None,
                ticket_url="https://www.giglon.com/",
            ),),
        )

        message = build_message(digest)

        self.assertIn(
            '🎟 <a href="https://www.giglon.com/">Билеты</a>',
            message,
        )

    def test_non_geographic_meeting_instruction_is_not_a_map_link(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Ночной поход (8 км) для молодёжи 12–30 лет",
                starts_at=datetime(
                    2026, 8, 7, 22, 15, tzinfo=GUARDAMAR_TIMEZONE
                ),
                ends_at=datetime(
                    2026, 8, 8, 0, 15, tzinfo=GUARDAMAR_TIMEZONE
                ),
                place="Место старта сообщит инструктор",
                ticket_price_cents=0,
                participation_note=(
                    "с собой: спортивная обувь, вода и фонарик"
                ),
                registration_contact="633 14 57 75",
                capacity_limited=True,
            ),),
        )

        message = build_message(digest)

        self.assertIn("📍 Место старта сообщит инструктор", message)
        self.assertNotIn("query=%D0%9C%D0%B5%D1%81%D1%82%D0%BE", message)
        self.assertIn(
            "Ночной поход (8 км) для молодёжи 12–30 лет "
            "(с собой: спортивная обувь, вода и фонарик)",
            message,
        )
        self.assertIn(
            "🎟 Бесплатно · регистрация: 633 14 57 75 · "
            "места ограничены",
            message,
        )

    def test_never_invents_registration_without_a_contact(self):
        digest = MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=True,
            events=(Event(
                title="Мастер-класс по электронной музыке",
                starts_at=None,
                ticket_price_cents=0,
                capacity_limited=True,
            ),),
        )

        message = build_message(digest)

        self.assertIn("🎟 Бесплатно · места ограничены", message)
        self.assertNotIn("регистрац", message)

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

        self.assertIn("• <b>09:00–15:30</b> — Рынок", message)
        self.assertIn(">парковка La Redonda</a>", message)

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

    def test_renders_named_beaches_without_renaming(self):
        digest = self._routine_digest(
            beach=BeachStatus(
                flag_color=None,
                sea_temperature_c=None,
                nearby_flags=(
                    ("Roqueta", "yellow"),
                    ("Vivers", "green"),
                    ("Montcaio", "red"),
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn("   🔴 Montcaio", message)
        self.assertIn("   🟡 Roqueta", message)
        self.assertIn("   🟢 Vivers", message)
        self.assertNotIn("Centre / Babilònia", message)

    def test_groups_all_beaches_with_at_most_three_names_per_row(self):
        digest = self._routine_digest(
            beach=BeachStatus(
                flag_color="red",
                sea_temperature_c=28,
                nearby_flags=(
                    ("Centre", "red"),
                    ("Roqueta", "red"),
                    ("Vivers", "red"),
                    ("Montcaio", "red"),
                    ("Camp", "green"),
                    ("Ortigues", "green"),
                ),
                jellyfish_beaches=(
                    "Centre",
                    "Roqueta",
                    "Vivers",
                    "Montcaio",
                ),
            ),
        )

        message = build_message(digest)

        self.assertIn(
            "   🔴 Centre / Babilònia, Roqueta, Vivers\n"
            "   🔴 Montcaio\n"
            "   🟢 Camp, Ortigues",
            message,
        )
        self.assertIn(
            "🪼 Медузы: Centre / Babilònia, Roqueta, Vivers\n"
            "   🪼 Montcaio",
            message,
        )

    def test_compacts_only_a_complete_all_green_beach_set(self):
        all_green = BeachStatus(
            flag_color="green",
            sea_temperature_c=28,
            nearby_flags=tuple(
                (name, "green")
                for name in (
                    "Centre",
                    "Roqueta",
                    "Vivers",
                    "Montcaio",
                    "Camp",
                    "Ortigues",
                )
            ),
        )

        compact = build_message(self._routine_digest(beach=all_green))
        partial = build_message(self._routine_digest(
            beach=BeachStatus(
                flag_color="green",
                sea_temperature_c=28,
                nearby_flags=all_green.nearby_flags[:-1],
            ),
        ))

        self.assertIn("   🟢 На всех пляжах", compact)
        self.assertNotIn("На всех пляжах", partial)
        self.assertIn(
            "   🟢 Centre / Babilònia, Roqueta, Vivers\n"
            "   🟢 Montcaio, Camp",
            partial,
        )

    def test_official_prohibition_disables_all_green_compaction(self):
        all_green = BeachStatus(
            flag_color="green",
            sea_temperature_c=28,
            nearby_flags=tuple(
                (name, "green")
                for name in (
                    "Centre",
                    "Roqueta",
                    "Vivers",
                    "Montcaio",
                    "Camp",
                    "Ortigues",
                )
            ),
        )
        notice = BeachNotice(
            text="Купание временно запрещено.",
            bathing_prohibited=True,
            published_at=datetime(2026, 7, 29, 10, 20, tzinfo=timezone.utc),
        )

        message = build_message(self._routine_digest(
            beach=all_green,
            beach_notice=notice,
        ))

        self.assertNotIn("На всех пляжах", message)
        self.assertIn("⛔ Ограничение купания", message)

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
        self.assertIn("• <b>21:00</b> — Событие 1", message)
        self.assertIn(">парк на улице Berlín</a>", message)
        self.assertIn("• <b>22:00</b> — Событие 2", message)
        self.assertIn(">Castell</a>", message)

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
