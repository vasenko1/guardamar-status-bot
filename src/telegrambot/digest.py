"""Deterministic formatting for one concise Telegram message."""

import html
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import with_footer
from .models import BeachNotice, BeachStatus, MorningDigest, Warning

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
MAX_BEACH_NAMES_PER_LINE = 3
SEA_STATES = {
    "calm": "спокойные",
    "slight": "слабые",
    "moderate": "умеренные",
    "rough": "сильные",
    "very_rough": "очень сильные",
}
WARNING_DOTS = {
    "yellow": "🟡",
    "orange": "🟠",
    "red": "🔴",
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
WARNING_DESCRIPTIONS = {
    (
        "posibles rachas muy fuertes de viento, granizo y chubascos "
        "localmente fuertes."
    ): (
        "Возможны очень сильные порывы ветра, град и местами сильные "
        "ливни."
    ),
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
SKY_LABELS = {
    "clear": "ясно",
    "partly_cloudy": "малооблачно",
    "cloudy": "облачно",
    "fog": "туман",
    "rain": "дождь",
    "snow": "снег",
    "storm": "гроза",
}


MONTHS_GENITIVE = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _uv_label(uv_index: int) -> str:
    """Return the WHO exposure-category name for a high UV index."""

    if uv_index >= 11:
        return "экстремальный"
    if uv_index >= 8:
        return "очень высокий"
    return "высокий"


def _warning_text(event: str) -> str:
    normalized = unicodedata.normalize("NFKD", event.strip().casefold())
    key = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    exact = WARNING_EVENTS.get(key)
    if exact is not None:
        return exact
    for event_name, label in WARNING_EVENTS.items():
        if event_name in key:
            return label
    return "предупреждение AEMET"


def _warning_description(warning: Warning) -> Optional[str]:
    if warning.description:
        source = " ".join(warning.description.split()).casefold()
        return WARNING_DESCRIPTIONS.get(source)
    return None


def _warning_clock(value: datetime) -> str:
    return value.astimezone(GUARDAMAR_TIMEZONE).strftime("%H:%M")


def _warning_day_label(value: date, today: date) -> str:
    if value == today:
        return "Сегодня"
    if value == today + timedelta(days=1):
        return "Завтра"
    return f"{value.day} {MONTHS_GENITIVE[value.month]}"


def _warning_interval(warning: Warning, today: date) -> str:
    start = (
        warning.starts_at.astimezone(GUARDAMAR_TIMEZONE)
        if warning.starts_at
        else None
    )
    end = (
        warning.ends_at.astimezone(GUARDAMAR_TIMEZONE)
        if warning.ends_at
        else None
    )
    if start is None and end is None:
        return ""
    if start is None:
        return (
            f"{_warning_day_label(end.date(), today)} · "
            f"до {_warning_clock(end)}"
        )
    if end is None:
        return (
            f"{_warning_day_label(start.date(), today)} · "
            f"с {_warning_clock(start)}"
        )
    if start.date() == end.date():
        return (
            f"{_warning_day_label(start.date(), today)} · "
            f"{_warning_clock(start)}–{_warning_clock(end)}"
        )
    return (
        f"{_warning_day_label(start.date(), today)}, с "
        f"{_warning_clock(start)} — "
        f"{_warning_day_label(end.date(), today).casefold()}, до "
        f"{_warning_clock(end)}"
    )


def _warning_blocks(
    warnings: Sequence[Warning],
    now: datetime,
) -> list[str]:
    """Render scan-friendly AEMET warnings without merging unlike facts."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    priority = {"red": 0, "orange": 1, "yellow": 2}
    active = [
        warning for warning in warnings
        if warning.ends_at is None
        or warning.ends_at.astimezone(GUARDAMAR_TIMEZONE) > now
    ]
    ordered = sorted(
        active,
        key=lambda warning: (
            priority.get(warning.level, 3),
            warning.starts_at or datetime.min.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            _warning_text(warning.event),
        ),
    )
    grouped = []
    positions = {}
    for warning in ordered:
        description = _warning_description(warning)
        description_identity = (
            " ".join(warning.description.split()).casefold()
            if warning.description
            else None
        )
        key = (
            warning.level,
            _warning_text(warning.event),
            description_identity,
            description,
            warning.probability,
        )
        if key not in positions:
            positions[key] = len(grouped)
            grouped.append([key, []])
        grouped[positions[key]][1].append(warning)

    blocks = []
    for (
        level,
        event,
        _description_identity,
        description,
        probability,
    ), items in grouped:
        dot = WARNING_DOTS.get(level, "⚠️")
        blocks.append(f"{dot} <b>{html.escape(event.capitalize())}</b>")
        intervals = []
        if (
            len(items) == 2
            and items[0].starts_at
            and items[0].ends_at
            and items[1].starts_at
            and items[1].ends_at
        ):
            first_start = items[0].starts_at.astimezone(GUARDAMAR_TIMEZONE)
            first_end = items[0].ends_at.astimezone(GUARDAMAR_TIMEZONE)
            second_start = items[1].starts_at.astimezone(GUARDAMAR_TIMEZONE)
            second_end = items[1].ends_at.astimezone(GUARDAMAR_TIMEZONE)
            if (
                first_start.date() == today
                and second_start.date() == today + timedelta(days=1)
                and first_start.time() == second_start.time()
                and first_end.time() == second_end.time()
                and first_start.date() == first_end.date()
                and second_start.date() == second_end.date()
            ):
                intervals.append(
                    "Сегодня и завтра · "
                    f"{_warning_clock(first_start)}–"
                    f"{_warning_clock(first_end)}"
                )
        if not intervals:
            intervals = [
                interval
                for item in items
                if (interval := _warning_interval(item, today))
            ]
        if probability:
            if intervals:
                intervals = [
                    f"{interval} · вероятность {probability}"
                    for interval in intervals
                ]
            else:
                intervals.append(f"Вероятность: {probability}")
        blocks.extend(f"   {interval}" for interval in intervals)
        if description:
            blocks.append(f"   {description}")
    return blocks


def build_warning_section(
    warnings: Sequence[Warning],
    now: datetime,
) -> str:
    """Render the approved complete AEMET warning section."""

    blocks = _warning_blocks(warnings, now)
    if not blocks:
        return ""
    return "\n".join([
        "⚠️ <b>Предупреждения AEMET:</b>",
        "Зона: южное побережье Аликанте",
        *blocks,
    ])


def _event_title(value: str) -> str:
    return value if len(value) <= 120 else f"{value[:117].rstrip()}…"


def _event_place(value: str) -> str:
    value = " ".join(value.split())
    if value.casefold() in {
        "sala de exposiciones casa de cultura",
        "sala de exposiciones de la casa de cultura",
    }:
        return "Casa de Cultura (Sala de exposiciones)"
    value = re.sub(r"\bC/\s*", "улица ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^parque\s+улица\s+",
        "парк на улице ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^frente(?:\s+a)?(?:\s+la)?\s+piscina,?\s*",
        "у бассейна, ",
        value,
        flags=re.IGNORECASE,
    )
    if value.isupper():
        value = value.title().replace(" Del ", " del ").replace(
            " De ", " de "
        )
    return _event_title(value)


def _event_place_link(value: str) -> str:
    """Render one fixed-host Google Maps search for a verified place."""

    source_place = " ".join(value.split())
    if source_place == "Место старта сообщит инструктор":
        return html.escape(source_place)
    if source_place.casefold() in {
        "plaça dels llauradors",
        "plaça llauradors",
        "plaza labradores",
    }:
        query = "38.0921948,-0.6552320"
    elif "guardamar" not in source_place.casefold():
        query = f"{source_place}, Guardamar del Segura"
    else:
        query = source_place
    map_url = "https://www.google.com/maps/search/?" + urllib.parse.urlencode({
        "api": "1",
        "query": query,
    })
    return (
        '<a href="'
        + html.escape(map_url, quote=True)
        + '">'
        + html.escape(_event_place(source_place))
        + "</a>"
    )


def _pharmacy_address_link(address: str, municipality: str) -> str:
    """Link the compact address while searching in its actual municipality."""

    source_address = " ".join(address.split())
    source_address = re.sub(
        r"^C/\s*", "Calle ", source_address, flags=re.IGNORECASE
    )
    query = f"{source_address}, {' '.join(municipality.split())}"
    map_url = "https://www.google.com/maps/search/?" + urllib.parse.urlencode({
        "api": "1",
        "query": query,
    })
    return (
        '<a href="'
        + html.escape(map_url, quote=True)
        + '">'
        + html.escape(source_address)
        + "</a>"
    )


def _exhibition_title(value: str) -> str:
    """Give an explicitly separated exhibition name Russian typography."""

    if "выстав" not in value.casefold():
        return f"Выставка «{value}»"
    prefix, separator, name = value.partition(":")
    if separator and name.strip() and "выстав" in prefix.casefold():
        prefix = prefix.strip()
        name = name.strip()
        if name.casefold().startswith(prefix.casefold()):
            name = name[len(prefix):].lstrip(" :-—")
        name = re.sub(r'"([^"]+)"', r"«\1»", name)
        if "«" in name:
            return f"{prefix} {name}"
        return f"{prefix} «{name}»"
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
        lines.append("🏖 <b>Флаги на пляжах:</b>")
        all_known_green = (
            len(nearby_flags) == len(BEACH_ORDER)
            and {name for name, _ in nearby_flags} == set(BEACH_ORDER)
            and all(color == "green" for _, color in nearby_flags)
            and not (notice is not None and notice.bathing_prohibited)
        )
        if all_known_green:
            lines.append("   🟢 На всех пляжах")
        for color in ("red", "yellow", "green"):
            if all_known_green:
                break
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
            for offset in range(0, len(matching), MAX_BEACH_NAMES_PER_LINE):
                chunk = matching[offset:offset + MAX_BEACH_NAMES_PER_LINE]
                lines.append(
                    f"   {FLAG_DOTS[color]} "
                    f"{', '.join(BEACH_NAMES.get(name, name) for name in chunk)}"
                )
    if beach is not None and beach.jellyfish_beaches:
        jellyfish = sorted(
            beach.jellyfish_beaches,
            key=lambda name: BEACH_ORDER.get(name, len(BEACH_ORDER)),
        )
        for offset in range(0, len(jellyfish), MAX_BEACH_NAMES_PER_LINE):
            chunk = jellyfish[offset:offset + MAX_BEACH_NAMES_PER_LINE]
            prefix = "🪼 Медузы: " if offset == 0 else "   🪼 "
            lines.append(
                prefix
                + ", ".join(BEACH_NAMES.get(name, name) for name in chunk)
            )
    if notice is not None:
        heading = (
            "⛔ Ограничение купания"
            if notice.bathing_prohibited
            else "🏖 Информация о купании"
        )
        lines.extend(["", f"<b>{heading}:</b>", html.escape(notice.text)])
    return lines


def build_message(
    digest: MorningDigest,
    now: Optional[datetime] = None,
) -> str:
    """Format a Morning Digest without inference or generated prose."""

    weather = digest.weather
    lines = ["🌅 Доброе утро, Гуардамар!"]
    if weather is not None:
        displayed_conditions = weather.sky_conditions
        if not displayed_conditions and weather.sky_condition:
            displayed_conditions = (weather.sky_condition,)
        sky_labels = []
        for condition in displayed_conditions:
            label = SKY_LABELS.get(condition)
            if label is not None and label not in sky_labels:
                sky_labels.append(label)
        sky_suffix = f" • {' → '.join(sky_labels)}" if sky_labels else ""
        weather_icon = (
            "🌤"
            if len(displayed_conditions) > 1
            else WEATHER_ICONS.get(
                displayed_conditions[0] if displayed_conditions else None,
                WEATHER_ICONS.get(weather.sky_condition, "🌤"),
            )
        )
        if (
            weather.rain_probability_percent is not None
            and weather.rain_probability_percent >= 75
        ):
            rain_line = (
                f"<b>Дождь:</b> {weather.rain_probability_percent}%"
            )
            if weather.rain_period:
                rain_line += f" • {weather.rain_period}"
        lines.extend([
            "",
            f"{weather_icon} <b>Погода от AEMET:</b>",
            (
                f"<b>Воздух:</b> {weather.minimum_temperature_c}°"
                f" → {weather.maximum_temperature_c}°{sky_suffix}"
            ),
        ])
        if (
            weather.rain_probability_percent is not None
            and weather.rain_probability_percent >= 75
        ):
            lines.append(rain_line)
        sea_temperature_c = digest.forecast_sea_temperature_c
        if sea_temperature_c is None and digest.beach is not None:
            sea_temperature_c = digest.beach.sea_temperature_c
        sea_temperature = (
            f"{sea_temperature_c}°"
            if sea_temperature_c is not None else "—"
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
            first_sea_label and later_sea_label
            and later_sea_label != first_sea_label
        ):
            sea_state = f"{first_sea_label} → {later_sea_label}"
        else:
            sea_label = first_sea_label or later_sea_label
            sea_state = f"{sea_label} волны" if sea_label else None
        sea_suffix = f" • {sea_state}" if sea_state else ""
        if weather.wind_direction and weather.wind_speed_kmh is not None:
            direction = WIND_DIRECTIONS.get(weather.wind_direction, "—")
            current_wind_mps = _wind_mps(weather.wind_speed_kmh)
            wind_line = f"<b>Ветер:</b> {direction} {current_wind_mps}"
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
            lines.append("<b>Ветер:</b> —")
        lines.append(f"<b>Море:</b> {sea_temperature}{sea_suffix}")
        if weather.uv_index is not None and weather.uv_index >= 6:
            lines.append(
                f"<b>УФ:</b> {weather.uv_index}"
                f" ({_uv_label(weather.uv_index)})"
            )
        if weather.sunrise is not None and weather.sunset is not None:
            sunrise_label = weather.sunrise.astimezone(
                GUARDAMAR_TIMEZONE
            ).strftime("%H:%M")
            sunset_label = weather.sunset.astimezone(
                GUARDAMAR_TIMEZONE
            ).strftime("%H:%M")
            lines.append(
                f"<b>Солнце:</b> {sunrise_label} → {sunset_label}"
            )

    warning_now = now or datetime.now(GUARDAMAR_TIMEZONE)
    warning_section = build_warning_section(digest.warnings, warning_now)
    if warning_section:
        lines.extend(["", *warning_section.splitlines()])

    beach_lines = _beach_operational_lines(
        digest.beach,
        digest.beach_notice,
    )
    if beach_lines:
        lines.extend(["", *beach_lines])

    if digest.traffic_notices:
        lines.extend(["", "🚧 <b>Движение:</b>"])
        visible_traffic = digest.traffic_notices[:2]
        for notice in visible_traffic:
            prefix = "• " if len(visible_traffic) > 1 else ""
            lines.append(prefix + html.escape(notice.text))

    if digest.pharmacies:
        heading = (
            "💊 <b>Дежурная аптека:</b>"
            if len(digest.pharmacies) == 1
            else "💊 <b>Дежурные аптеки:</b>"
        )
        lines.extend(["", heading])
        for index, duty in enumerate(digest.pharmacies[:2]):
            if index:
                lines.append("")
            lines.append(
                f"<b>{html.escape(duty.name)}, "
                f"{html.escape(duty.municipality)}</b>"
            )
            lines.append(html.escape(duty.hours))
            lines.append(
                f"📍 {_pharmacy_address_link(duty.address, duty.municipality)}"
            )

    if digest.holidays:
        scope_labels = {
            "national": "национальный праздник",
            "regional": "региональный праздник",
            "local": "официальный городской праздник",
        }
        ordered_holidays = sorted(
            (
                holiday
                for holiday in digest.holidays
                if holiday.scope in scope_labels
            ),
            key=lambda holiday: {
                "national": 0,
                "regional": 1,
                "local": 2,
            }.get(holiday.scope, 3),
        )
    else:
        ordered_holidays = []

    if ordered_holidays:
        heading = (
            "🎉 <b>Праздник сегодня:</b>"
            if len(ordered_holidays) == 1
            else "🎉 <b>Праздники сегодня:</b>"
        )
        lines.extend(["", heading])
        for holiday in ordered_holidays:
            label = scope_labels.get(holiday.scope)
            if label is None:
                continue
            lines.append(
                f"• {html.escape(holiday.name)} — {label}"
            )
        if ordered_holidays[0].date.weekday() < 5:
            lines.append("  🏛️ Официальный выходной день.")

    if digest.events:
        event_lines = build_event_section(
            digest.events,
            "📅 <b>События дня:</b>",
            prefix_length=len("\n".join(lines)),
        )
        lines.extend(event_lines)
    if len(lines) == 1:
        raise ValueError("No verified digest content is available")
    return with_footer("\n".join(lines))


def build_event_section(
    events: Sequence,
    heading: str,
    *,
    prefix_length: int = 0,
) -> List[str]:
    """Render one bounded event list shared by every digest variant.

    Returns a leading empty line, the heading, and event bullets, or an
    empty list when nothing survives the message-size bound.
    """

    event_lines = ["", heading]
    for index, event in enumerate(events):
        if index:
            event_lines.append("")
        title = event.title
        if event.category == "exhibition":
            title = _exhibition_title(title)
        title = html.escape(_event_title(title))
        if event.participation_note:
            title += " (" + html.escape(event.participation_note) + ")"
        if event.is_final_day:
            title = f"Последний день: {title}"
        time_prefix = ""
        if event.starts_at is not None:
            start_time = event.starts_at.astimezone(
                GUARDAMAR_TIMEZONE
            ).strftime("%H:%M")
            time_prefix = f"<b>{start_time}"
            if event.ends_at is not None:
                end_time = event.ends_at.astimezone(
                    GUARDAMAR_TIMEZONE
                ).strftime("%H:%M")
                time_prefix += f"–{end_time}"
            time_prefix += "</b> — "
        event_lines.append(f"• {time_prefix}{title}")
        if event.place:
            event_lines.append(f"  📍 {_event_place_link(event.place)}")
        has_ticket_row = (
            event.ticket_price_cents is not None
            or event.ticket_url is not None
            or event.registration_contact is not None
            or event.capacity_limited
        )
        if has_ticket_row:
            if event.ticket_price_cents == 0:
                ticket_label = "Бесплатно"
            elif event.ticket_price_cents is not None:
                price = event.ticket_price_cents / 100
                price_label = (
                    f"{int(price)} €"
                    if price.is_integer()
                    else f"{price:.2f} €".replace(".", ",")
                )
                ticket_label = f"Билет {price_label}"
            else:
                ticket_label = "Билеты" if event.ticket_url else ""
            details = []
            if event.ticket_url and ticket_label:
                details.append(
                    '<a href="'
                    + html.escape(event.ticket_url, quote=True)
                    + f'">{ticket_label}</a>'
                )
            elif ticket_label:
                details.append(ticket_label)
            if event.registration_contact:
                details.append(
                    "регистрация: "
                    + html.escape(event.registration_contact)
                )
            if event.capacity_limited:
                details.append("места ограничены")
            if details:
                event_lines.append("  🎟 " + " · ".join(details))
        if prefix_length + 1 + len("\n".join(event_lines)) > 3900:
            rows = 1 + int(bool(event.place)) + int(has_ticket_row)
            event_lines = event_lines[:-rows]
            if event_lines and event_lines[-1] == "":
                event_lines.pop()
            break
    return event_lines if len(event_lines) > 2 else []
