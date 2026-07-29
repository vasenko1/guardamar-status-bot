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
BEACH_ORDER = {"Centre": 0, "Roqueta": 1, "Vivers": 2}
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
        meanings = dict(beach.flag_meanings)
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
            shared = {meanings.get(name) for name in matching}
            suffix = ""
            if len(shared) == 1 and None not in shared:
                suffix = f" — {shared.pop()}"
            lines.append(
                f"   {FLAG_DOTS[color]} {', '.join(matching)}{suffix}"
            )
    if beach is not None and beach.jellyfish_beaches:
        jellyfish = sorted(
            beach.jellyfish_beaches,
            key=lambda name: BEACH_ORDER.get(name, len(BEACH_ORDER)),
        )
        lines.append("🪼 Медузы: " + ", ".join(jellyfish))
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
