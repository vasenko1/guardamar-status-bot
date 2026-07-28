"""Deterministic formatting for one concise Telegram message."""

import unicodedata
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .models import MorningDigest

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

WIND_DIRECTIONS = {
    "N": "С",
    "NNE": "ССВ",
    "NE": "СВ",
    "ENE": "ВСВ",
    "E": "В",
    "ESE": "ВЮВ",
    "SE": "ЮВ",
    "SSE": "ЮЮВ",
    "S": "Ю",
    "SSW": "ЮЮЗ",
    "SW": "ЮЗ",
    "WSW": "ЗЮЗ",
    "W": "З",
    "WNW": "ЗСЗ",
    "NW": "СЗ",
    "NNW": "ССЗ",
    "C": "штиль",
}
FLAG_DOTS = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
}
SEA_STATES = {
    "calm": "волнение слабое",
    "slight": "волнение небольшое",
    "moderate": "волнение умеренное",
    "rough": "волнение сильное",
    "very_rough": "волнение очень сильное",
}
WARNING_LEVELS = {
    "yellow": "Жёлтое предупреждение",
    "orange": "Оранжевое предупреждение",
    "red": "Красное предупреждение",
}
WARNING_EVENTS = {
    "temperaturas maximas": "высокая температура",
    "temperaturas minimas": "низкая температура",
    "viento": "сильный ветер",
    "lluvias": "сильный дождь",
    "tormentas": "грозы",
    "fenomenos costeros": "опасные прибрежные явления",
    "niebla": "туман",
    "polvo en suspension": "пыль в воздухе",
}
WEATHER_ICONS = {
    "clear": "☀️",
    "partly_cloudy": "🌤",
    "cloudy": "☁️",
    "fog": "🌫️",
    "rain": "🌧️",
    "snow": "🌨️",
    "storm": "⛈️",
}


def _warning_end(value: Optional[datetime]) -> str:
    if value is None:
        return "."
    return f" до {value.astimezone(GUARDAMAR_TIMEZONE).strftime('%H:%M')}."


def _warning_text(event: str) -> str:
    normalized = unicodedata.normalize("NFKD", event.strip().casefold())
    key = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return WARNING_EVENTS.get(key, "предупреждение AEMET")


def _event_title(value: str) -> str:
    return value if len(value) <= 64 else f"{value[:61].rstrip()}…"


def _wind_mps(value_kmh: int) -> int:
    return round(value_kmh / 3.6)


def build_message(digest: MorningDigest) -> str:
    """Format a Morning Digest without inference or generated prose."""

    weather = digest.weather
    weather_icon = WEATHER_ICONS.get(weather.sky_condition, "🌤")
    lines = [
        "🌅 Доброе утро, Гуардамар!",
        "",
        (
            f"{weather_icon} Погода      {weather.minimum_temperature_c}°"
            f" → {weather.maximum_temperature_c}°"
        ),
    ]

    sea_temperature_c = (
        digest.beach.sea_temperature_c
        if digest.beach is not None
        and digest.beach.sea_temperature_c is not None
        else digest.forecast_sea_temperature_c
    )
    sea_temperature = (
        f"{sea_temperature_c}°"
        if sea_temperature_c is not None
        else "—"
    )
    sea_state = (
        SEA_STATES.get(digest.beach.sea_state)
        if digest.beach is not None
        else None
    )
    sea_suffix = f" • {sea_state}" if sea_state else ""
    lines.append(f"🌊 Море        {sea_temperature}{sea_suffix}")

    nearby_flags = (
        digest.beach.nearby_flags
        if digest.beach is not None
        else ()
    )
    if (
        not nearby_flags
        and digest.beach is not None
        and digest.beach.flag_color in FLAG_DOTS
    ):
        nearby_flags = (("Centre", digest.beach.flag_color),)
    rendered_flags = [
        f"{name} {FLAG_DOTS[color]}"
        for name, color in nearby_flags
        if color in FLAG_DOTS
    ]
    if rendered_flags:
        lines.append(f"🏖 Флаги       {' • '.join(rendered_flags)}")

    if weather.wind_direction and weather.wind_speed_kmh is not None:
        direction = WIND_DIRECTIONS.get(
            weather.wind_direction,
            "—",
        )
        current_wind_mps = _wind_mps(weather.wind_speed_kmh)
        wind_line = f"💨 Ветер       {direction} {current_wind_mps}"
        if (
            weather.forecast_wind_speed_kmh is not None
            and _wind_mps(weather.forecast_wind_speed_kmh)
            != current_wind_mps
        ):
            wind_line += (
                f" → {_wind_mps(weather.forecast_wind_speed_kmh)}"
            )
        wind_line += " м/с"
        lines.append(wind_line)
    else:
        lines.append("💨 Ветер       —")

    if digest.warnings:
        lines.extend(["", "⚠️ Внимание"])
    for warning in digest.warnings[:2]:
        level = WARNING_LEVELS.get(
            warning.level, "Предупреждение"
        )
        lines.append(
            f"{level}: {_warning_text(warning.event)}"
            f"{_warning_end(warning.ends_at)}"
        )
    if len(digest.warnings) > 2:
        additional = len(digest.warnings) - 2
        lines.append(f"Ещё предупреждений: {additional}.")

    if digest.traffic_notices:
        lines.extend(["", "🚧 Движение ограничено"])
        lines.append(digest.traffic_notices[0].text)

    if digest.events:
        lines.extend(["", "📅 События"])
        for event in digest.events[:2]:
            title = _event_title(event.title)
            if (
                event.category == "exhibition"
                and "выстав" not in title.casefold()
            ):
                title = f"Выставка «{title}»"
            time_prefix = ""
            if event.starts_at is not None:
                start_time = event.starts_at.astimezone(
                    GUARDAMAR_TIMEZONE
                ).strftime("%H:%M")
                time_prefix = start_time
                if event.ends_at is not None:
                    end_time = event.ends_at.astimezone(
                        GUARDAMAR_TIMEZONE
                    ).strftime("%H:%M")
                    time_prefix += f"–{end_time}"
                time_prefix += " — "
            place_separator = ", " if time_prefix else " — "
            place = (
                f"{place_separator}{_event_title(event.place)}"
                if event.place
                else ""
            )
            lines.append(f"• {time_prefix}{title}{place}")
    return "\n".join(lines)
