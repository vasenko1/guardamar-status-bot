"""Deterministic formatting for one concise Telegram message."""

import html
import logging
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import with_footer
from .event_places import (
    canonical_event_place, event_place_is_map_safe, same_event_place,
)
from .event_facts import ROUTE_DIFFICULTY_PREFIX
from .models import (
    AirQualitySummary, BeachNotice, BeachStatus, ColdHealthRisk, HeatHealthRisk,
    MorningDigest, PollenSummary, Warning,
)

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
CAMS_ATTRIBUTION_URL = "https://www.copernicus.eu/en/access-data/copernicus-services-catalogue/atmosphere"

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
WARNING_EVENT_ALIASES = {
    "temperatura maxima": "высокая температура",
    "temperaturas maxima": "высокая температура",
    "altas temperaturas": "высокая температура",
    "temperatura minima": "низкая температура",
    "temperaturas minima": "низкая температура",
    "bajas temperaturas": "низкая температура",
    "lluvia": "сильный дождь",
    "tormenta": "грозы",
    "fenomeno costero": "опасные прибрежные явления",
    "polvo": "пыль в воздухе",
}
LOGGER = logging.getLogger(__name__)
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


def _warning_text(event: str) -> Optional[str]:
    normalized = unicodedata.normalize("NFKD", (event or "").strip().casefold())
    key = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    exact = WARNING_EVENTS.get(key)
    if exact is not None:
        return exact
    alias = WARNING_EVENT_ALIASES.get(key)
    if alias is not None:
        return alias
    for event_name, label in WARNING_EVENTS.items():
        if event_name in key:
            return label
    LOGGER.warning(
        "Omitting AEMET warning with unknown event label: %r", event
    )
    return None


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


def _warning_parameter_line(warning: Warning) -> Optional[str]:
    """Return one compact human-readable structured CAP value."""
    if warning.parameter_code is None or warning.parameter_value is None:
        return None
    value = f"{warning.parameter_value:g}".replace(".", ",")
    code = warning.parameter_code
    if code == "P1" and warning.parameter_unit == "mm":
        return f"{value} л/м² за 1 час"
    if code == "P2" and warning.parameter_unit == "mm":
        return f"{value} л/м² за 12 часов"
    if code == "NV" and warning.parameter_unit == "cm":
        return f"Снег: {value} см за 24 часа"
    if code == "RM" and warning.parameter_unit == "km/h":
        return f"Порывы ветра: {value} км/ч"
    if code == "TA" and warning.parameter_unit == "°C":
        return f"Максимальная температура: {value} °C"
    if code == "TI" and warning.parameter_unit == "°C":
        return f"Минимальная температура: {value} °C"
    return None


def _warning_blocks(
    warnings: Sequence[Warning],
    now: datetime,
    heat_health_risk: Optional[HeatHealthRisk] = None,
    air_quality: Optional[AirQualitySummary] = None,
    cold_health_risk: Optional[ColdHealthRisk] = None,
) -> list[str]:
    """Render scan-friendly AEMET warnings, grouping one visible period once."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    priority = {"red": 0, "orange": 1, "yellow": 2}
    active = [
        warning for warning in warnings
        if (
            warning.ends_at is None
            or warning.ends_at.astimezone(GUARDAMAR_TIMEZONE) > now
        )
        and _warning_text(warning.event) is not None
    ]

    def display_day(warning: Warning) -> date:
        if warning.starts_at is None:
            return today
        start_day = warning.starts_at.astimezone(
            GUARDAMAR_TIMEZONE
        ).date()
        return max(start_day, today)

    ordered = sorted(
        active,
        key=lambda warning: (
            display_day(warning),
            priority.get(warning.level, 3),
            warning.starts_at or datetime.min.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            warning.ends_at or datetime.max.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            _warning_text(warning.event) or "",
            warning.parameter_code or "",
        ),
    )

    # Presentation grouping is intentionally separate from CAP identity.
    # P1/P2 remain distinct facts in the model/state, but one shared visible
    # period should not repeat the same event, interval, or probability.
    grouped = []
    positions = {}
    for warning in ordered:
        key = (
            display_day(warning),
            warning.level,
            warning.starts_at,
            warning.ends_at,
            warning.probability,
        )
        if key not in positions:
            positions[key] = len(grouped)
            grouped.append([key, []])
        grouped[positions[key]][1].append(warning)

    blocks = []
    heat_nested = False
    cold_nested = False
    air_nested = False

    for (
        _display_day,
        level,
        _starts_at,
        _ends_at,
        probability,
    ), items in grouped:
        dot = WARNING_DOTS.get(level, "⚠️")
        interval = _warning_interval(items[0], today)

        # CAP normally supplies a period. Preserve the established event-first
        # fallback for malformed/partial warnings with no usable interval.
        period_first = bool(interval)
        if period_first:
            blocks.append(f"{dot} <b>{html.escape(interval)}</b>")
            if probability:
                blocks.append(
                    f"   Вероятность: {html.escape(probability)}"
                )

        event_groups = []
        event_positions = {}
        for warning in items:
            label = _warning_text(warning.event) or ""
            if label not in event_positions:
                event_positions[label] = len(event_groups)
                event_groups.append([label, []])
            event_groups[event_positions[label]][1].append(warning)

        for event, event_items in event_groups:
            if period_first:
                blocks.append(f"   • <b>{html.escape(event.capitalize())}</b>")
            else:
                blocks.append(
                    f"{dot} <b>{html.escape(event.capitalize())}</b>"
                )
                if probability:
                    blocks.append(
                        f"   Вероятность: {html.escape(probability)}"
                    )

            parameter_lines = tuple(dict.fromkeys(
                line
                for item in event_items
                if (line := _warning_parameter_line(item)) is not None
            ))
            parameter_indent = "      " if period_first else "   "
            blocks.extend(
                f"{parameter_indent}{html.escape(line)}"
                for line in parameter_lines
            )

            descriptions = tuple(dict.fromkeys(
                description
                for item in event_items
                if (description := _warning_description(item)) is not None
            ))
            blocks.extend(
                f"{parameter_indent}{html.escape(description)}"
                for description in descriptions
            )

            today_block = _display_day == today
            health_indent = "   "
            if (
                today_block and event == "высокая температура"
                and heat_health_risk is not None
                and heat_health_risk.level > 0
                and not heat_nested
            ):
                lines = _health_lines(
                    _heat_health_line(heat_health_risk),
                    _HEAT_HEALTH_ADVICE.get(heat_health_risk.level),
                    nested=True,
                )
                blocks.extend(lines)
                heat_nested = True
            if (
                today_block and event == "низкая температура"
                and cold_health_risk is not None
                and cold_health_risk.level > 0
                and not cold_nested
            ):
                lines = _health_lines(
                    _cold_health_line(cold_health_risk),
                    _COLD_HEALTH_ADVICE.get(cold_health_risk.level),
                    nested=True,
                )
                blocks.extend(lines)
                cold_nested = True
            if (
                today_block and event == "пыль в воздухе"
                and air_quality is not None and any(
                    pollutant in {"PM10", "PM2.5"}
                    for pollutant in air_quality.pollutants
                )
            ):
                blocks.append(
                    health_indent
                    + _air_quality_line(air_quality, dust_warning=True)
                )
                air_nested = True

    return blocks, heat_nested, cold_nested, air_nested


def _join_ru(values: Sequence[str]) -> str:
    if len(values) < 2:
        return values[0]
    if len(values) == 2:
        return " и ".join(values)
    return ", ".join(values[:-1]) + " и " + values[-1]


def _heat_health_line(value: HeatHealthRisk) -> str:
    labels = {1: "низкий", 2: "средний", 3: "высокий"}
    return f"❤️‍🩹 Риск жары для здоровья: {labels[value.level]}"


def _cold_health_line(value: ColdHealthRisk) -> str:
    labels = {1: "низкий", 2: "средний", 3: "высокий"}
    return f"❤️‍🩹 Риск холода для здоровья: {labels[value.level]}"


_HEAT_HEALTH_ADVICE = {
    2: "💧 Пейте больше воды и избегайте жары в середине дня.",
    3: "💧 Избегайте жары и нагрузок; особое внимание детям и пожилым.",
}
_COLD_HEALTH_ADVICE = {
    2: "🧥 Одевайтесь теплее и избегайте длительного пребывания на холоде.",
    3: "🧥 Сократите время на холоде; особое внимание детям и пожилым.",
}


def _health_lines(
    risk_line: str, advice: Optional[str], *, nested: bool = False,
) -> list[str]:
    indent = "   " if nested else ""
    lines = [indent + risk_line]
    if advice is not None:
        lines.append(indent + "   " + advice)
    return lines


def _air_quality_line(value: AirQualitySummary, *, dust_warning: bool = False) -> str:
    text = (
        f"😷 <b>Качество воздуха:</b> {value.period} ожидается ухудшение"
        f": повышен{'ы' if len(value.pollutants) > 1 else ''} "
        f"{_join_ru(value.pollutants)}."
    )
    if dust_warning and value.dust_related:
        text += " Возможно влияние переносимой пыли."
    if value.wildfire_possible:
        text += " Возможно влияние дыма от пожаров."
    return text


def _pollen_line(value: PollenSummary) -> str:
    if value.allergens:
        text = (
            "🌿 <b>Пыльца:</b> высокий уровень "
            f"{_join_ru(value.allergens)} ожидается {value.period}"
        )
        if value.ragweed_present:
            if value.ragweed_period == value.period:
                return text + "; также присутствует амброзия."
            return text + f"; амброзия ожидается {value.ragweed_period}."
        return text + "."
    if value.ragweed_period == "в течение дня":
        return "🌿 <b>Пыльца:</b> в воздухе присутствует амброзия."
    return f"🌿 <b>Пыльца:</b> {value.ragweed_period} в воздухе ожидается амброзия."


def _cams_attribution(year: int) -> str:
    return (
        f'Источник: <a href="{CAMS_ATTRIBUTION_URL}">данные CAMS (Copernicus), '
        f'обработанные для Гуардамара, {year}</a>. '
        'ЕС и ECMWF не несут ответственности за их использование.'
    )


def build_warning_section(
    warnings: Sequence[Warning],
    now: datetime,
    heat_health_risk: Optional[HeatHealthRisk] = None,
    air_quality: Optional[AirQualitySummary] = None,
    cold_health_risk: Optional[ColdHealthRisk] = None,
) -> str:
    """Render the approved complete AEMET warning section."""

    blocks, _, _, _ = _warning_blocks(
        warnings, now, heat_health_risk, air_quality, cold_health_risk
    )
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
    value = canonical_event_place(value)
    if value.casefold() in {
        "sala de exposiciones casa de cultura",
        "sala de exposiciones de la casa de cultura",
        "sala de exposiciones de casa de cultura",
    }:
        return "Casa de Cultura (Sala de Exposiciones)"
    if value.casefold() in {
        "hall biblioteca municipal",
        "hall de la biblioteca municipal",
        "hall de la biblioteca pública municipal",
        "hall biblioteca pública municipal",
    }:
        return "Biblioteca Municipal (Hall)"
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


_EVENT_PLACE_MAP_URLS = {
    "camino del raso, 15": "https://maps.app.goo.gl/JhZBna2cqRixy69o8",
    "centro sanitario integrado (зона педиатрии)": (
        "https://maps.app.goo.gl/DXW3LqEmCNCjf9JX8"
    ),
}


def _event_place_link(value: str, place_query: Optional[str] = None) -> str:
    """Render a reviewed exact map URL, otherwise a Google Maps search."""

    source_place = canonical_event_place(value)
    if not event_place_is_map_safe(source_place) or (
        place_query is not None and not event_place_is_map_safe(place_query)
    ):
        return html.escape(_event_place(source_place))

    exact_url = _EVENT_PLACE_MAP_URLS.get(source_place.casefold())
    if exact_url is not None and place_query is None:
        return (
            '<a href="'
            + html.escape(exact_url, quote=True)
            + '">'
            + html.escape(_event_place(source_place))
            + "</a>"
        )

    if place_query is not None:
        query = place_query
        if "guardamar" not in query.casefold():
            query += ", Guardamar del Segura"
    elif source_place.casefold() in {
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


def _event_active_until_label(value: date) -> str:
    return f"До {value.day} {MONTHS_GENITIVE[value.month]}"


def _event_teaser_is_redundant(title: str, teaser: str) -> bool:
    """Reject only a teaser which repeats the displayed event title verbatim.

    This is deliberately conservative: facts are never rewritten or inferred
    during rendering.  Less obvious repetition is handled in the reviewed
    source translation where the compact wording can be checked by a person.
    """

    normalized_title = re.sub(r"\W+", "", title.casefold())
    normalized_teaser = re.sub(r"\W+", "", teaser.casefold())
    return bool(normalized_teaser) and normalized_teaser in normalized_title


_PHARMACY_MAP_POINTS = {
    ("martinez perello, pedro luis", "calle madrid, 1 b", "guardamar del segura"): "38.0942352,-0.6566556",
    ("escudero ortiz, maria dolores", "av. de londres, 1 ed.marina centro l-13", "san fulgencio"): "38.1382065,-0.6752966",
    ("planelles mas, asuncion", "av. cervantes, 29", "guardamar del segura"): "38.0857693,-0.6491500",
    ("rodriguez nieto, julian", "plaza de la figuera, 5 local 19", "guardamar del segura"): "38.0612823,-0.6839423",
    ("farmacia mora", "av. pais valenciano, 29", "guardamar del segura"): "38.0884644,-0.6541501",
    ("farmacia ruiz lozano", "calle amsterdam, 14", "san fulgencio"): "38.1339172,-0.6842980",
    ("rodriguez macia, raquel", "av. pais valenciano, 123", "guardamar del segura"): "38.0832455,-0.6546076",
    ("quiles martinez, farmacia", "calle jose antonio, 8", "san fulgencio"): "38.1132766,-0.7184098",
    ("funes esquinas, maria teresa", "calle mayor, 9", "guardamar del segura"): "38.0907585,-0.6548401",
    ("perez garcia, maria mercedes", "calle plaza sierra de castilla,2 l.9 urb. la marina", "san fulgencio"): "38.1415131,-0.6751306",
}


def _pharmacy_address_link(name: str, address: str, municipality: str) -> str:
    """Link only a reviewed exact pharmacy point; never guess a map result."""

    source_address = " ".join(address.split())
    source_address = re.sub(
        r"^C/\s*", "Calle ", source_address, flags=re.IGNORECASE
    )
    key = (name.casefold(), source_address.casefold(), municipality.casefold())
    query = _PHARMACY_MAP_POINTS.get(key)
    if query is None:
        return html.escape(source_address)
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
    warning_blocks, heat_nested, cold_nested, air_nested = _warning_blocks(
        digest.warnings,
        warning_now,
        digest.heat_health_risk,
        digest.air_quality,
        digest.cold_health_risk,
    )
    if warning_blocks:
        lines.extend([
            "", "⚠️ <b>Предупреждения AEMET:</b>",
            "Зона: южное побережье Аликанте", *warning_blocks,
        ])

    if digest.hydrology_state:
        lines.extend([
            "",
            "🌊 CCE: действует гидрологическое предупреждение.",
        ])

    standalone_environment = []
    if (
        digest.heat_health_risk is not None
        and digest.heat_health_risk.level > 0
        and not heat_nested
    ):
        standalone_environment.extend(_health_lines(
            _heat_health_line(digest.heat_health_risk),
            _HEAT_HEALTH_ADVICE.get(digest.heat_health_risk.level),
        ))
    if (
        digest.cold_health_risk is not None
        and digest.cold_health_risk.level > 0
        and not cold_nested
    ):
        standalone_environment.extend(_health_lines(
            _cold_health_line(digest.cold_health_risk),
            _COLD_HEALTH_ADVICE.get(digest.cold_health_risk.level),
        ))
    if digest.air_quality is not None and not air_nested:
        standalone_environment.append(_air_quality_line(digest.air_quality))
    if digest.pollen is not None:
        standalone_environment.append(_pollen_line(digest.pollen))
    if standalone_environment:
        lines.extend(["", *standalone_environment])
    if digest.air_quality is not None or digest.pollen is not None:
        lines.append(_cams_attribution(warning_now.year))

    beach_lines = _beach_operational_lines(
        digest.beach,
        digest.beach_notice,
    )
    if beach_lines:
        lines.extend(["", *beach_lines])

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
                f"📍 {_pharmacy_address_link(duty.name, duty.address, duty.municipality)}"
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
    rendered_programmes = set()
    for event in events:
        programme = getattr(event, "programme_title", None)
        if programme:
            if programme in rendered_programmes:
                continue
            rendered_programmes.add(programme)
            members = sorted(
                (candidate for candidate in events
                 if getattr(candidate, "programme_title", None) == programme),
                key=lambda candidate: (
                    getattr(candidate, "programme_order", None) is None,
                    getattr(candidate, "programme_order", None) or 0,
                ),
            )
            block = [f"• 🎉 {html.escape(programme)}"]
            for member in members:
                block.append(_event_heading(member, "  ", bullet=False))
                block.extend(_render_event_details(member, "    "))
        else:
            block = [_event_heading(event, "", bullet=True)]
            block.extend(_render_event_details(event, "  "))
        separator = [""] if len(event_lines) > 2 else []
        if prefix_length + 1 + len("\n".join(
            event_lines + separator + block
        )) > 3900:
            break
        event_lines.extend(separator + block)
    return event_lines if len(event_lines) > 2 else []


def _event_heading(event, indent: str, *, bullet: bool) -> str:
    title = event.title
    if event.category == "exhibition":
        title = _exhibition_title(title)
    title = html.escape(_event_title(title))
    if event.is_final_day:
        title = f"Последний день: {title}"
    when = ""
    if event.starts_at is not None:
        when = event.starts_at.astimezone(GUARDAMAR_TIMEZONE).strftime("%H:%M")
        if event.ends_at is not None and event.duration_minutes is None:
            when += "–" + event.ends_at.astimezone(
                GUARDAMAR_TIMEZONE
            ).strftime("%H:%M")
        when = f"<b>{when}</b> — "
    return f"{indent}{'• ' if bullet else ''}{when}{title}"


def _format_distance_detail(value: int, approximate: bool) -> str:
    whole, hundredths = divmod(value, 100)
    if hundredths == 0:
        amount = str(whole)
    elif hundredths % 10 == 0:
        amount = f"{whole},{hundredths // 10}"
    else:
        amount = f"{whole},{hundredths:02d}"
    return ("≈ " if approximate else "") + amount + " км"


def _normalized_event_details(
    details: Sequence[str],
) -> tuple[List[str], Optional[str]]:
    """Normalize only canonical distance/difficulty route facts."""

    classified = []
    distance_values = set()
    difficulty_values = set()
    for detail in details:
        distance_match = re.fullmatch(
            r"\s*(\d{1,3})(?:[,.](\d{1,2}))?\s*км\s*",
            detail,
            re.IGNORECASE,
        )
        if distance_match is not None:
            value = (
                int(distance_match.group(1)) * 100
                + int((distance_match.group(2) or "0").ljust(2, "0"))
            )
            if 0 < value <= 10_000:
                distance_values.add(value)
                classified.append(("distance", detail))
                continue

        if detail.casefold().startswith(ROUTE_DIFFICULTY_PREFIX.casefold()):
            level = detail[len(ROUTE_DIFFICULTY_PREFIX):].strip().casefold()
            level = level.replace("-", "–")
            if level in {
                "низкая",
                "низкая–средняя",
                "средняя",
                "средняя–высокая",
                "высокая",
            }:
                difficulty_values.add(level)
            classified.append(("difficulty", detail))
            continue
        classified.append(("other", detail))

    distance_label = None
    if distance_values:
        distance_label = _format_distance_detail(
            max(distance_values),
            approximate=len(distance_values) > 1,
        )
    difficulty_label = (
        next(iter(difficulty_values))
        if len(difficulty_values) == 1
        else None
    )

    result = []
    distance_added = False
    for kind, detail in classified:
        if kind == "distance":
            if distance_label is not None and not distance_added:
                result.append(distance_label)
                distance_added = True
        elif kind == "other":
            result.append(detail)
    return result, difficulty_label


def _render_event_details(event, indent: str) -> List[str]:
    """One optional detail contract for standalone and programme events."""

    rows = []
    if event.route:
        rows.append(indent + "Маршрут: " + html.escape(event.route))
    facts, route_difficulty = _normalized_event_details(event.details)
    if event.duration_minutes is not None:
        facts.append(f"{event.duration_minutes} мин")
    if event.audience_label:
        facts.append(event.audience_label)
    if facts:
        rows.append(indent + html.escape(" • ".join(facts)))
    if route_difficulty:
        rows.append(
            indent + "Сложность маршрута: " + html.escape(route_difficulty)
        )
    if event.teaser and not _event_teaser_is_redundant(event.title, event.teaser):
        rows.append(indent + html.escape(event.teaser))
    if (
        event.active_until is not None
        and event.starts_at is None
        and not event.is_final_day
    ):
        rows.append(indent + _event_active_until_label(event.active_until))
    if event.schedule_note:
        rows.append(indent + "🕐 " + html.escape(event.schedule_note))
    if event.place:
        rows.append(indent + "📍 " + _event_place_link(
            event.place, event.place_query
        ))
    if event.meeting_point and (
        not event.place or not same_event_place(event.place, event.meeting_point)
    ):
        label = event.meeting_point
        prefix = "" if label.casefold().startswith("место ") else "Место сбора: "
        rows.append(indent + "👥 " + prefix + _event_place_link(label))
    if event.participation_note:
        rows.append(indent + "ℹ️ " + html.escape(event.participation_note))
    access = []
    if event.ticket_price_cents == 0:
        ticket_label = (
            "Бесплатно · Получить билет"
            if event.ticket_url else "Бесплатно"
        )
    elif event.ticket_price_cents is not None:
        price = event.ticket_price_cents / 100
        amount = f"{int(price)}" if price.is_integer() else (
            f"{price:.2f}".replace(".", ",")
        )
        ticket_label = (
            f"Билеты от {amount} €"
            if event.ticket_price_is_from
            else f"Билет {amount} €"
        )
    else:
        ticket_label = "Билеты" if event.ticket_url else ""
    if ticket_label:
        access.append(
            '<a href="' + html.escape(event.ticket_url, quote=True)
            + f'">{ticket_label}</a>' if event.ticket_url else ticket_label
        )
    if event.access_note:
        access.append(html.escape(event.access_note))
    if event.registration_contact:
        label = (
            "" if event.access_note and "регистрац" in event.access_note.casefold()
            else "регистрация: "
        )
        access.append(label + html.escape(event.registration_contact))
    if not event.access_note and event.capacity_limited:
        access.append("места ограничены")
    if access:
        rows.append(indent + "🎟 " + " · ".join(access))
    return rows
