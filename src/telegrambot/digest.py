"""Deterministic formatting for one concise Telegram message."""

import unicodedata
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .models import BeachNotice, BeachStatus, MorningDigest

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
BEACH_ORDER = {
    "Centre": 0,
    "Roqueta": 1,
    "Vivers": 2,
    "Montcaio": 3,
    "Camp": 4,
    "Ortigues": 5,
}
BEACH_NAMES = {
    "Centre": "Centre / Babilònia",
    "Roqueta": "Roqueta",
    "Vivers": "Vivers",
    "Montcaio": "Montcaio",
    "Camp": "Camp",
    "Ortigues": "Ortigues",
}
SEA_STATES = {
    "calm": "спокойные",
    "slight": "слабые",
    "moderate": "умеренные",
    "rough": "сильные",
    "very_rough": "очень сильные",
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


def _exhibition_title(value: str) -> str:
    """Give an explicitly separated exhibition name Russian typography."""

    if "выстав" not in value.casefold():
        return f"Выставка «{value}»"
    prefix, separator, name = value.partition(":")
    if (
        separator
        and name.strip()
        and "«" not in value
        and '"' not in value
        and "выстав" in prefix.casefold()
    ):
        return f"{prefix.strip()} «{name.strip()}»"
    return value


def _wind_mps(value_kmh: int) -> int:
    return round(value_kmh / 3.6)


def _beach_operational_lines(
    beach: Optional[BeachStatus],
    notice: Optional[BeachNotice],
) -> list:
    lines = []
    nearby_flags = beach.nearby_flags if beach is not None else ()
    if (
        not nearby_flags
        and beach is not None
        and beach.flag_color in FLAG_DOTS
    ):
        nearby_flags = (("Centre", beach.flag_color),)
    if nearby_flags:
        lines.append("🏖 Флаги на пляжах:")
        for color in ("red", "yellow", "green"):
            matching = [
                name
                for name, flag_color in nearby_flags
                if flag_color == color
            ]
            matching.sort(
                key=lambda name: BEACH_ORDER.get(name, len(BEACH_ORDER))
            )
            if not matching:
                continue
            lines.append(
                f"   {FLAG_DOTS[color]} "
                f"{', '.join(BEACH_NAMES.get(name, name) for name in matching)}"
            )
    if beach is not None and beach.jellyfish_beaches:
        jellyfish = sorted(
            beach.jellyfish_beaches,
            key=lambda name: BEACH_ORDER.get(name, len(BEACH_ORDER)),
        )
        lines.append(
            "🪼 Медузы: "
            + ", ".join(BEACH_NAMES.get(name, name) for name in jellyfish)
        )
    if notice is not None:
        heading = (
            "⛔ Ограничение купания"
            if notice.bathing_prohibited
            else "🏖 Информация о купании"
        )
        lines.extend(["", heading, notice.text])
    return lines


def build_fallback_update(
    morning_message: str,
    beach: Optional[BeachStatus],
    notice: Optional[BeachNotice],
) -> str:
    """Add verified beach updates to the already published morning copy."""

    additions = _beach_operational_lines(beach, notice)
    if not additions:
        return morning_message
    lines = morning_message.splitlines()
    insert_at = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if line.startswith("💨 Ветер:")
        ),
        len(lines),
    )
    lines[insert_at:insert_at] = additions
    return "\n".join(lines)


def build_message(digest: MorningDigest) -> str:
    """Format a Morning Digest without inference or generated prose."""

    weather = digest.weather
    weather_icon = WEATHER_ICONS.get(weather.sky_condition, "🌤")
    lines = [
        "🌅 Доброе утро, Гуардамар!",
        "",
        (
            f"{weather_icon} Погода: {weather.minimum_temperature_c}°"
            f" → {weather.maximum_temperature_c}°"
        ),
    ]
    if (
        weather.rain_probability_percent is not None
        and weather.rain_probability_percent >= 75
    ):
        rain_line = f"🌧 Дождь: {weather.rain_probability_percent}%"
        if weather.rain_period:
            rain_line += f" • {weather.rain_period}"
        lines.append(rain_line)

    sea_temperature_c = digest.forecast_sea_temperature_c
    if (
        sea_temperature_c is None
        and digest.beach is not None
    ):
        sea_temperature_c = digest.beach.sea_temperature_c
    sea_temperature = (
        f"{sea_temperature_c}°"
        if sea_temperature_c is not None
        else "—"
    )
    first_sea_state = digest.forecast_sea_state
    later_sea_state = digest.forecast_later_sea_state
    if (
        first_sea_state is None
        and later_sea_state is None
        and digest.beach is not None
    ):
        first_sea_state = digest.beach.sea_state
    first_sea_label = SEA_STATES.get(first_sea_state)
    later_sea_label = SEA_STATES.get(later_sea_state)
    if (
        first_sea_label
        and later_sea_label
        and later_sea_label != first_sea_label
    ):
        sea_state = f"{first_sea_label} → {later_sea_label}"
    else:
        sea_label = first_sea_label or later_sea_label
        sea_state = f"{sea_label} волны" if sea_label else None
    sea_suffix = f" • {sea_state}" if sea_state else ""
    lines.append(f"🌊 Море: {sea_temperature}{sea_suffix}")

    if weather.wind_direction and weather.wind_speed_kmh is not None:
        direction = WIND_DIRECTIONS.get(
            weather.wind_direction,
            "—",
        )
        current_wind_mps = _wind_mps(weather.wind_speed_kmh)
        wind_line = f"💨 Ветер: {direction} {current_wind_mps}"
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
        lines.append("💨 Ветер: —")

    lines.extend(
        _beach_operational_lines(digest.beach, digest.beach_notice)
    )

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
        lines.extend(
            notice.text for notice in digest.traffic_notices[:2]
        )

    if digest.events:
        lines.extend(["", "📅 События дня:"])
        for event in digest.events[:2]:
            title = _event_title(event.title)
            if event.category == "exhibition":
                title = _exhibition_title(title)
            if event.is_final_day:
                title = f"Последний день: {title}"
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
