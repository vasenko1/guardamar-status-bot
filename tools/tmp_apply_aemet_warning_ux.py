from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# 1. Warning model: retain structured CAP parameter data without changing callers.
replace_once(
    "src/telegrambot/models.py",
'''    description: Optional[str] = None
    probability: Optional[str] = None
''',
'''    description: Optional[str] = None
    probability: Optional[str] = None
    parameter_code: Optional[str] = None
    parameter_value: Optional[float] = None
    parameter_unit: Optional[str] = None
''',
)

# 2. AEMET CAP parser: parse only the bounded, documented numeric parameter subset.
replace_once(
    "src/telegrambot/aemet.py",
'''def _elements(element: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    return (item for item in element.iter() if _local_name(item) == name)


def _cap_documents(payload: bytes) -> Iterable[bytes]:
''',
'''def _elements(element: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    return (item for item in element.iter() if _local_name(item) == name)


_WARNING_PARAMETER_UNITS = {
    "P1": "mm",
    "P2": "mm",
    "NV": "cm",
    "RM": "km/h",
    "TA": "°C",
    "TI": "°C",
}


def _normalize_warning_probability(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold().replace("–", "-")
    match = re.fullmatch(r"(\\d{1,3})%\\s*-\\s*(\\d{1,3})%", normalized)
    if match is not None:
        lower, upper = (int(part) for part in match.groups())
        if 0 <= lower <= upper <= 100:
            return f"{lower}–{upper}%"
    if re.fullmatch(r"mayor\\s+70%", normalized):
        return ">70%"
    return None


def _normalize_warning_parameter(
    value: Optional[str],
) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    if not isinstance(value, str):
        return None, None, None
    parts = [part.strip() for part in value.split(";", 2)]
    if len(parts) != 3:
        return None, None, None
    code = parts[0].upper()
    expected_unit = _WARNING_PARAMETER_UNITS.get(code)
    if expected_unit is None:
        return None, None, None
    match = re.fullmatch(
        r"([+-]?\\d+(?:[.,]\\d+)?)\\s*(mm|cm|km/h|ºC|°C)",
        parts[2],
        flags=re.IGNORECASE,
    )
    if match is None:
        return None, None, None
    raw_unit = match.group(2)
    if expected_unit == "°C":
        if raw_unit not in {"ºC", "°C"}:
            return None, None, None
        unit = "°C"
    else:
        if raw_unit.casefold() != expected_unit.casefold():
            return None, None, None
        unit = expected_unit
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return None, None, None
    if not math.isfinite(number):
        return None, None, None
    if code in {"P1", "P2", "NV", "RM"} and number < 0:
        return None, None, None
    return code, number, unit


def _cap_documents(payload: bytes) -> Iterable[bytes]:
''',
)

replace_once(
    "src/telegrambot/aemet.py",
'''            description = _child_text(info, "description")
            probability = None
            for parameter in _elements(info, "parameter"):
                name = _child_text(parameter, "valueName")
                value = _child_text(parameter, "value")
                if (
                    name
                    and value
                    and name.casefold() == "aemet-meteoalerta probabilidad"
                    and re.fullmatch(r"\\d{1,3}%\\s*-\\s*\\d{1,3}%", value)
                ):
                    lower, upper = (
                        int(part.strip().rstrip("%"))
                        for part in value.split("-", 1)
                    )
                    if 0 <= lower <= upper <= 100:
                        probability = f"{lower}–{upper}%"
            key = (event.casefold(), level, starts_at, ends_at)
''',
'''            description = _child_text(info, "description")
            probability = None
            parameter_code = None
            parameter_value = None
            parameter_unit = None
            for parameter in _elements(info, "parameter"):
                name = _child_text(parameter, "valueName")
                value = _child_text(parameter, "value")
                if not name or not value:
                    continue
                normalized_name = name.casefold()
                if normalized_name == "aemet-meteoalerta probabilidad":
                    candidate = _normalize_warning_probability(value)
                    if candidate is not None:
                        probability = candidate
                elif (
                    normalized_name == "aemet-meteoalerta parametro"
                    and parameter_code is None
                ):
                    (
                        candidate_code,
                        candidate_value,
                        candidate_unit,
                    ) = _normalize_warning_parameter(value)
                    if candidate_code is not None:
                        parameter_code = candidate_code
                        parameter_value = candidate_value
                        parameter_unit = candidate_unit
            key = (
                event.casefold(),
                parameter_code,
                level,
                starts_at,
                ends_at,
            )
''',
)

replace_once(
    "src/telegrambot/aemet.py",
'''                        description=description,
                        probability=probability,
                    )
                )

    priority = {"red": 0, "orange": 1, "yellow": 2}
    warnings.sort(key=lambda item: (priority.get(item.level, 3), item.event))
''',
'''                        description=description,
                        probability=probability,
                        parameter_code=parameter_code,
                        parameter_value=parameter_value,
                        parameter_unit=parameter_unit,
                    )
                )

    priority = {"red": 0, "orange": 1, "yellow": 2}
    warnings.sort(
        key=lambda item: (
            priority.get(item.level, 3),
            item.event.casefold(),
            item.parameter_code or "",
            item.starts_at or datetime.min.replace(tzinfo=timezone.utc),
            item.ends_at or datetime.max.replace(tzinfo=timezone.utc),
        )
    )
''',
)

# 3. Operational state: preserve legacy state quietly, but detect real value changes.
replace_once(
    "src/telegrambot/operational_updates.py",
'''from .digest import (
    BEACH_NAMES,
    FLAG_DOTS,
    MONTHS_GENITIVE,
    _beach_operational_lines,
    _warning_blocks,
    _warning_text,
)
''',
'''from .digest import (
    BEACH_NAMES,
    FLAG_DOTS,
    MONTHS_GENITIVE,
    WARNING_DOTS,
    _beach_operational_lines,
    _warning_description,
    _warning_interval,
    _warning_text,
)
''',
)

replace_once(
    "src/telegrambot/operational_updates.py",
'''        if isinstance(warning_ready, dict) and (
            not isinstance(warning_ready.get("current"), list)
            or not isinstance(warning_ready.get("cancelled"), list)
        ):
''',
'''        if isinstance(warning_ready, dict) and (
            not isinstance(warning_ready.get("current"), list)
            or not isinstance(warning_ready.get("cancelled"), list)
            or (
                warning_ready.get("previous") is not None
                and not isinstance(warning_ready.get("previous"), list)
            )
        ):
''',
)

replace_once(
    "src/telegrambot/operational_updates.py",
'''def _warning_dict(warning: Warning) -> dict:
    return {
        "event": " ".join(warning.event.split()),
        "level": warning.level.strip().casefold(),
        "starts_at": warning.starts_at.isoformat() if warning.starts_at else None,
        "ends_at": warning.ends_at.isoformat() if warning.ends_at else None,
        "description": (
            " ".join(warning.description.split()) if warning.description else None
        ),
        "probability": warning.probability,
    }


def _warning_identity(value: dict) -> Tuple[object, ...]:
    return (
        value.get("event", "").casefold(),
        value.get("level"),
        value.get("starts_at"),
        value.get("ends_at"),
        (value.get("description") or "").casefold(),
        value.get("probability"),
    )
''',
'''def _warning_dict(warning: Warning) -> dict:
    return {
        "event": " ".join(warning.event.split()),
        "level": warning.level.strip().casefold(),
        "starts_at": warning.starts_at.isoformat() if warning.starts_at else None,
        "ends_at": warning.ends_at.isoformat() if warning.ends_at else None,
        "description": (
            " ".join(warning.description.split()) if warning.description else None
        ),
        "probability": warning.probability,
        "parameter_code": warning.parameter_code,
        "parameter_value": warning.parameter_value,
        "parameter_unit": warning.parameter_unit,
    }


def _warning_legacy_identity(value: dict) -> Tuple[object, ...]:
    return (
        value.get("event", "").casefold(),
        value.get("level"),
        value.get("starts_at"),
        value.get("ends_at"),
        (value.get("description") or "").casefold(),
        value.get("probability"),
    )


def _warning_identity(value: dict) -> Tuple[object, ...]:
    return (
        *_warning_legacy_identity(value),
        value.get("parameter_code"),
        value.get("parameter_value"),
        value.get("parameter_unit"),
    )
''',
)

replace_once(
    "src/telegrambot/operational_updates.py",
'''def observe_warnings(
    state: dict,
    warnings: Sequence[Warning],
    now: datetime,
) -> None:
    """Store a ready AEMET update only after one valid complete response."""
    current = [_warning_dict(item) for item in warnings]
    if not state.get("warnings_initialized"):
        state["warnings_initialized"] = True
        state["warnings"] = []
    previous = state.get("warnings", [])
    previous_by_id = {_warning_identity(item): item for item in previous}
    current_ids = {_warning_identity(item) for item in current}
    added_or_changed = current_ids - set(previous_by_id)
    changed_events = {identity[0] for identity in added_or_changed}
    removed = [
        item for identity, item in previous_by_id.items()
        if identity not in current_ids
    ]
    early_cancelled = []
    for item in removed:
        if item.get("event", "").casefold() in changed_events:
            continue
        raw_end = item.get("ends_at")
        if raw_end is None:
            early_cancelled.append(item)
            continue
        try:
            end = datetime.fromisoformat(raw_end)
        except ValueError:
            continue
        if end > now.astimezone(end.tzinfo):
            early_cancelled.append(item)
    if added_or_changed or early_cancelled:
        state["warning_ready"] = {
            "current": current,
            "cancelled": early_cancelled,
        }
    else:
        state["warnings"] = current
''',
'''def observe_warnings(
    state: dict,
    warnings: Sequence[Warning],
    now: datetime,
) -> None:
    """Store a ready AEMET update only after one valid complete response."""
    current = [_warning_dict(item) for item in warnings]
    if not state.get("warnings_initialized"):
        state["warnings_initialized"] = True
        state["warnings"] = []
    previous = state.get("warnings", [])

    # One-time compatibility bridge: old state has no CAP parameter fields.
    # If every legacy-visible fact is unchanged, enrich the baseline silently.
    legacy_previous = bool(previous) and all(
        "parameter_code" not in item
        and "parameter_value" not in item
        and "parameter_unit" not in item
        for item in previous
    )
    if legacy_previous and (
        {_warning_legacy_identity(item) for item in previous}
        == {_warning_legacy_identity(item) for item in current}
    ):
        state["warnings"] = current
        state["warning_ready"] = None
        return

    previous_by_id = {_warning_identity(item): item for item in previous}
    current_ids = {_warning_identity(item) for item in current}
    added_or_changed = current_ids - set(previous_by_id)
    removed = [
        item for identity, item in previous_by_id.items()
        if identity not in current_ids
    ]
    current_events = {
        item.get("event", "").casefold() for item in current
    }
    early_cancelled = []
    removed_relevant = False
    for item in removed:
        raw_end = item.get("ends_at")
        if raw_end is not None:
            try:
                end = datetime.fromisoformat(raw_end)
            except ValueError:
                continue
            if end <= now.astimezone(end.tzinfo):
                continue
        if item.get("event", "").casefold() in current_events:
            removed_relevant = True
        else:
            early_cancelled.append(item)

    if added_or_changed or removed_relevant or early_cancelled:
        state["warning_ready"] = {
            "previous": list(previous),
            "current": current,
            "cancelled": early_cancelled,
        }
    else:
        state["warnings"] = current
''',
)

replace_once(
    "src/telegrambot/operational_updates.py",
'''    return Warning(
        event=value["event"],
        level=value["level"],
        starts_at=parsed("starts_at"),
        ends_at=parsed("ends_at"),
        description=value.get("description"),
        probability=value.get("probability"),
    )
''',
'''    return Warning(
        event=value["event"],
        level=value["level"],
        starts_at=parsed("starts_at"),
        ends_at=parsed("ends_at"),
        description=value.get("description"),
        probability=value.get("probability"),
        parameter_code=value.get("parameter_code"),
        parameter_value=value.get("parameter_value"),
        parameter_unit=value.get("parameter_unit"),
    )
''',
)

# 4. Human update renderer. Keep cancellation behavior, add a bounded editorial lead.
replace_once(
    "src/telegrambot/operational_updates.py",
'''def _joined_warning_labels(labels: Sequence[str]) -> str:
    unique = tuple(dict.fromkeys(labels))
    if len(unique) <= 1:
        return unique[0] if unique else ""
    return ", ".join(unique[:-1]) + " и " + unique[-1]


def _warning_update_lines(warning_ready: dict, now: datetime) -> list[str]:
    """Render one self-contained current AEMET status update."""
    current = tuple(
        _warning_from_dict(item)
        for item in warning_ready.get("current", ())
    )
    cancelled_by_period: Dict[str, list[str]] = {}
    for item in warning_ready.get("cancelled", ()):
        warning = _warning_from_dict(item)
        warning_label = _warning_text(warning.event)
        if warning_label is None:
            continue
        period = _cancelled_warning_period(warning, now)
        cancelled_by_period.setdefault(period, []).append(warning_label)

    current_blocks, _, _, _ = _warning_blocks(current, now)
    if not cancelled_by_period and not current_blocks:
        return []

    lines = [
        "⚠️ <b>Обновление AEMET:</b>",
        "Зона: южное побережье Аликанте",
    ]
    for period, labels in cancelled_by_period.items():
        joined = html.escape(_joined_warning_labels(labels))
        status = (
            "отменено предупреждение"
            if len(tuple(dict.fromkeys(labels))) == 1
            else "отменены предупреждения"
        )
        prefix = f"{period} " if period else ""
        lines.append(f"✅ {prefix}{status}: {joined}.")

    if current_blocks:
        lines.extend(["", "<b>Сейчас действует:</b>", *current_blocks])
    elif not current:
        lines.extend(["", "Других действующих предупреждений сейчас нет."])
    return lines
''',
'''def _joined_warning_labels(labels: Sequence[str]) -> str:
    unique = tuple(dict.fromkeys(labels))
    if len(unique) <= 1:
        return unique[0] if unique else ""
    return ", ".join(unique[:-1]) + " и " + unique[-1]


def _warning_parameter_line(warning: Warning) -> Optional[str]:
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


def _warning_probability_text(value: Optional[str]) -> Optional[str]:
    if value == ">70%":
        return "более 70%"
    return value


def _warning_update_blocks(
    warnings: Sequence[Warning], now: datetime
) -> list[str]:
    """Render compact current/future warnings, merging only identical contexts."""
    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    priority = {"red": 0, "orange": 1, "yellow": 2}
    usable = [
        warning for warning in warnings
        if (
            warning.ends_at is None
            or warning.ends_at.astimezone(GUARDAMAR_TIMEZONE) > now
        )
        and _warning_text(warning.event) is not None
    ]
    usable.sort(
        key=lambda warning: (
            warning.starts_at or datetime.min.replace(tzinfo=GUARDAMAR_TIMEZONE),
            priority.get(warning.level, 3),
            _warning_text(warning.event) or "",
            warning.parameter_code or "",
        )
    )

    grouped = []
    positions = {}
    for warning in usable:
        label = _warning_text(warning.event) or ""
        description = _warning_description(warning)
        description_identity = (
            " ".join(warning.description.split()).casefold()
            if warning.description else None
        )
        key = (
            warning.level,
            label,
            warning.starts_at,
            warning.ends_at,
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
        _starts_at,
        _ends_at,
        _description_identity,
        description,
        probability,
    ), items in grouped:
        if blocks:
            blocks.append("")
        dot = WARNING_DOTS.get(level, "⚠️")
        blocks.append(f"{dot} <b>{html.escape(event.capitalize())}</b>")
        interval = _warning_interval(items[0], today)
        if interval:
            blocks.append(f"   {interval}")
        parameter_lines = tuple(dict.fromkeys(
            line for item in items
            if (line := _warning_parameter_line(item)) is not None
        ))
        blocks.extend(f"   • {html.escape(line)}" for line in parameter_lines)
        probability_text = _warning_probability_text(probability)
        if probability_text:
            blocks.append(
                f"   Вероятность: {html.escape(probability_text)}"
            )
        if description:
            blocks.append(f"   {html.escape(description)}")
    return blocks


def _warning_day_phrase(warnings: Sequence[Warning], now: datetime) -> str:
    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    days = {
        warning.starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
        for warning in warnings
        if warning.starts_at is not None
    }
    if len(days) != 1:
        return ""
    day = next(iter(days))
    if day == today:
        return " на сегодня"
    if day == today + timedelta(days=1):
        return " на завтра"
    return f" на {day.day} {MONTHS_GENITIVE[day.month]}"


def _warning_levels_by_day(
    warnings: Sequence[Warning], now: datetime
) -> Dict[object, int]:
    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    weights = {"yellow": 1, "orange": 2, "red": 3}
    result: Dict[object, int] = {}
    for warning in warnings:
        if _warning_text(warning.event) is None:
            continue
        day = (
            warning.starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
            if warning.starts_at is not None else today
        )
        result[day] = max(result.get(day, 0), weights.get(warning.level, 0))
    return result


def _warning_update_lead(
    warning_ready: dict,
    current: Sequence[Warning],
    now: datetime,
) -> str:
    visible_current = tuple(
        item for item in current if _warning_text(item.event) is not None
    )
    previous_known = "previous" in warning_ready
    previous = tuple(
        _warning_from_dict(item)
        for item in warning_ready.get("previous", ())
    ) if previous_known else ()
    visible_previous = tuple(
        item for item in previous if _warning_text(item.event) is not None
    )
    day_phrase = _warning_day_phrase(visible_current, now)

    if previous_known and not visible_previous and visible_current:
        noun = (
            "предупреждение"
            if len({_warning_text(item.event) for item in visible_current}) == 1
            else "предупреждения"
        )
        return f"⚠️ <b>AEMET объявила {noun}{day_phrase}</b>"

    if previous_known and visible_previous and visible_current:
        before = _warning_levels_by_day(visible_previous, now)
        after = _warning_levels_by_day(visible_current, now)
        increased = [
            day for day, level in after.items()
            if day in before and level > before[day]
        ]
        if increased:
            day = min(increased)
            level = after[day]
            level_key = {1: "yellow", 2: "orange", 3: "red"}[level]
            level_word = {
                "yellow": "жёлтого",
                "orange": "оранжевого",
                "red": "красного",
            }[level_key]
            target = _warning_day_phrase(
                tuple(
                    item for item in visible_current
                    if (
                        item.starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
                        if item.starts_at is not None
                        else now.astimezone(GUARDAMAR_TIMEZONE).date()
                    ) == day
                ),
                now,
            )
            dot = WARNING_DOTS.get(level_key, "")
            return (
                f"⚠️{dot} <b>AEMET повысила уровень предупреждения"
                f"{target} до {level_word}</b>"
            )

    return f"⚠️ <b>AEMET обновила предупреждения{day_phrase}</b>"


def _warning_update_lines(warning_ready: dict, now: datetime) -> list[str]:
    """Render one self-contained current AEMET status update."""
    current = tuple(
        _warning_from_dict(item)
        for item in warning_ready.get("current", ())
    )
    cancelled_by_period: Dict[str, list[str]] = {}
    for item in warning_ready.get("cancelled", ()):
        warning = _warning_from_dict(item)
        warning_label = _warning_text(warning.event)
        if warning_label is None:
            continue
        period = _cancelled_warning_period(warning, now)
        cancelled_by_period.setdefault(period, []).append(warning_label)

    current_blocks = _warning_update_blocks(current, now)
    if not cancelled_by_period and not current_blocks:
        return []

    lines = [
        _warning_update_lead(warning_ready, current, now),
        "Зона: южное побережье Аликанте",
    ]
    for period, labels in cancelled_by_period.items():
        joined = html.escape(_joined_warning_labels(labels))
        status = (
            "отменено предупреждение"
            if len(tuple(dict.fromkeys(labels))) == 1
            else "отменены предупреждения"
        )
        prefix = f"{period} " if period else ""
        lines.append(f"✅ {prefix}{status}: {joined}.")

    if current_blocks:
        future = any(
            item.starts_at is not None
            and item.starts_at.astimezone(GUARDAMAR_TIMEZONE) > now
            for item in current
            if _warning_text(item.event) is not None
        )
        heading = (
            "<b>Актуальные предупреждения:</b>"
            if future else "<b>Сейчас действует:</b>"
        )
        lines.extend(["", heading, *current_blocks])
    elif not current:
        lines.extend(["", "Других действующих предупреждений сейчас нет."])
    return lines
''',
)

# 5. Focused regression coverage for parser, migration, change detection and UX.
Path("tests/test_aemet_warning_updates.py").write_text(r'''import io
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.aemet import normalize_warnings
from telegrambot.models import Warning
from telegrambot.operational_updates import (
    OperationalUpdateState,
    build_update_message,
    observe_warnings,
)

MADRID = ZoneInfo("Europe/Madrid")


def _cap(
    *,
    event="Lluvias",
    severity="Severe",
    onset="2026-09-17T03:00:00+02:00",
    expires="2026-09-17T14:59:59+02:00",
    parameter=None,
    probability="40%-70%",
    description=None,
):
    extra = ""
    if parameter is not None:
        extra += (
            "<parameter><valueName>AEMET-Meteoalerta parametro</valueName>"
            f"<value>{parameter}</value></parameter>"
        )
    if probability is not None:
        extra += (
            "<parameter><valueName>AEMET-Meteoalerta probabilidad</valueName>"
            f"<value>{probability}</value></parameter>"
        )
    description_xml = (
        f"<description>{description}</description>" if description else ""
    )
    return f'''<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <status>Actual</status><info><language>es-ES</language>
      <event>{event}</event><severity>{severity}</severity>
      <onset>{onset}</onset><expires>{expires}</expires>
      {description_xml}{extra}
      <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
      </info></alert>'''.encode()


def _archive(*documents):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for index, document in enumerate(documents):
            archive.writestr(f"warning-{index}.xml", document)
    return result.getvalue()


class AemetWarningParameterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 20, 0, tzinfo=MADRID)

    def test_p1_and_p2_survive_dedup_and_archive_order(self):
        p1 = _cap(parameter="P1;Precipitación acumulada en una hora;60 mm")
        p2 = _cap(parameter="P2;Precipitación acumulada en 12 horas;120 mm")

        forward = normalize_warnings(_archive(p1, p2), self.now)
        reverse = normalize_warnings(_archive(p2, p1), self.now)

        self.assertEqual(forward, reverse)
        self.assertEqual([item.parameter_code for item in forward], ["P1", "P2"])
        self.assertEqual([item.parameter_value for item in forward], [60.0, 120.0])
        self.assertEqual([item.parameter_unit for item in forward], ["mm", "mm"])

    def test_invalid_parameter_is_ignored_without_dropping_warning(self):
        warnings = normalize_warnings(
            _cap(parameter="P1;Precipitación acumulada en una hora;60 km/h"),
            self.now,
        )
        self.assertEqual(len(warnings), 1)
        self.assertIsNone(warnings[0].parameter_code)
        self.assertIsNone(warnings[0].parameter_value)

    def test_probability_above_seventy_is_retained(self):
        warning = normalize_warnings(
            _cap(parameter="P1;Precipitación acumulada en una hora;60 mm", probability="mayor 70%"),
            self.now,
        )[0]
        self.assertEqual(warning.probability, ">70%")


class AemetWarningUpdateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 20, 0, tzinfo=MADRID)
        self.start = datetime(2026, 9, 17, 3, 0, tzinfo=MADRID)
        self.end = datetime(2026, 9, 17, 14, 59, tzinfo=MADRID)

    def _warning(self, *, code="P1", value=60, level="orange", end=None):
        return Warning(
            event="Lluvias",
            level=level,
            starts_at=self.start,
            ends_at=end or self.end,
            probability="40–70%",
            parameter_code=code,
            parameter_value=value,
            parameter_unit="mm",
        )

    def test_legacy_state_is_enriched_silently_even_when_p1_p2_expand(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warnings_initialized"] = True
        state["warnings"] = [{
            "event": "Lluvias",
            "level": "orange",
            "starts_at": self.start.isoformat(),
            "ends_at": self.end.isoformat(),
            "description": None,
            "probability": "40–70%",
        }]

        observe_warnings(
            state,
            (self._warning(code="P1", value=60), self._warning(code="P2", value=120)),
            self.now,
        )

        self.assertIsNone(state["warning_ready"])
        self.assertEqual(len(state["warnings"]), 2)
        self.assertEqual(
            {item["parameter_code"] for item in state["warnings"]},
            {"P1", "P2"},
        )

    def test_parameter_value_change_creates_neutral_update(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warnings_initialized"] = True
        old = self._warning(value=40)
        state["warnings"] = [{
            "event": old.event,
            "level": old.level,
            "starts_at": old.starts_at.isoformat(),
            "ends_at": old.ends_at.isoformat(),
            "description": None,
            "probability": old.probability,
            "parameter_code": old.parameter_code,
            "parameter_value": old.parameter_value,
            "parameter_unit": old.parameter_unit,
        }]

        observe_warnings(state, (self._warning(value=60),), self.now)
        message = build_update_message(state, self.now)

        self.assertIsNotNone(state["warning_ready"])
        self.assertIn("AEMET обновила предупреждения на завтра", message)
        self.assertIn("60 л/м² за 1 час", message)

    def test_level_increase_gets_editorial_lead_and_future_heading(self):
        state = OperationalUpdateState.empty("2026-09-16")
        old = self._warning(level="yellow")
        state["warnings_initialized"] = True
        state["warnings"] = [{
            "event": old.event,
            "level": old.level,
            "starts_at": old.starts_at.isoformat(),
            "ends_at": old.ends_at.isoformat(),
            "description": None,
            "probability": old.probability,
            "parameter_code": old.parameter_code,
            "parameter_value": old.parameter_value,
            "parameter_unit": old.parameter_unit,
        }]

        observe_warnings(state, (self._warning(level="orange"),), self.now)
        message = build_update_message(state, self.now)

        self.assertIn(
            "AEMET повысила уровень предупреждения на завтра до оранжевого",
            message,
        )
        self.assertIn("<b>Актуальные предупреждения:</b>", message)
        self.assertNotIn("<b>Сейчас действует:</b>", message)

    def test_matching_p1_p2_are_one_visual_block(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warning_ready"] = {
            "previous": [],
            "current": [],
            "cancelled": [],
        }
        for warning in (self._warning(code="P1", value=60), self._warning(code="P2", value=120)):
            state["warning_ready"]["current"].append({
                "event": warning.event,
                "level": warning.level,
                "starts_at": warning.starts_at.isoformat(),
                "ends_at": warning.ends_at.isoformat(),
                "description": None,
                "probability": warning.probability,
                "parameter_code": warning.parameter_code,
                "parameter_value": warning.parameter_value,
                "parameter_unit": warning.parameter_unit,
            })

        message = build_update_message(state, self.now)

        self.assertEqual(message.count("<b>Сильный дождь</b>"), 1)
        self.assertEqual(message.count("Вероятность: 40–70%"), 1)
        self.assertIn("60 л/м² за 1 час", message)
        self.assertIn("120 л/м² за 12 часов", message)

    def test_different_intervals_do_not_merge(self):
        state = OperationalUpdateState.empty("2026-09-16")
        first = self._warning(code="P1", value=60)
        second = self._warning(
            code="P2",
            value=120,
            end=self.end + timedelta(hours=5),
        )
        state["warning_ready"] = {
            "previous": [],
            "current": [
                {
                    "event": item.event,
                    "level": item.level,
                    "starts_at": item.starts_at.isoformat(),
                    "ends_at": item.ends_at.isoformat(),
                    "description": None,
                    "probability": item.probability,
                    "parameter_code": item.parameter_code,
                    "parameter_value": item.parameter_value,
                    "parameter_unit": item.parameter_unit,
                }
                for item in (first, second)
            ],
            "cancelled": [],
        }

        message = build_update_message(state, self.now)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 2)

    def test_above_seventy_probability_is_human_readable(self):
        warning = self._warning()
        state = OperationalUpdateState.empty("2026-09-16")
        state["warning_ready"] = {
            "previous": [],
            "current": [{
                "event": warning.event,
                "level": warning.level,
                "starts_at": warning.starts_at.isoformat(),
                "ends_at": warning.ends_at.isoformat(),
                "description": None,
                "probability": ">70%",
                "parameter_code": warning.parameter_code,
                "parameter_value": warning.parameter_value,
                "parameter_unit": warning.parameter_unit,
            }],
            "cancelled": [],
        }

        message = build_update_message(state, self.now)
        self.assertIn("Вероятность: более 70%", message)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")
