"""Bounded later-day beach and AEMET change monitoring."""

import fcntl
import html
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .digest import (
    BEACH_NAMES,
    FLAG_DOTS,
    MONTHS_GENITIVE,
    WARNING_DOTS,
    _beach_operational_lines,
    _warning_description,
    _warning_interval,
    _warning_text,
)
from .models import BeachNotice, BeachStatus, Warning
from .safebeach import BEACH_ORDER, KNOWN_BEACHES

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
STATE_VERSION = 1


class OperationalUpdateStateError(RuntimeError):
    """Raised when operational-update state cannot be trusted."""


@dataclass(frozen=True)
class MonitorRun:
    beach_phase: Optional[int]
    check_aemet: bool


def scheduled_run(now: datetime) -> MonitorRun:
    """Return the bounded work assigned to this exact local minute."""
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    day = local.date()
    in_season = (
        (day.month == 6 and day.day >= 20)
        or day.month in {7, 8}
        or (day.month == 9 and day.day <= 15)
    )
    shoulder = in_season and day.month in {6, 9}
    beach_hours = {12, 14, 16, 18} if shoulder else {11, 13, 15, 17, 19}
    aemet_hours = {12, 16, 20} if shoulder else {11, 15, 19}
    beach_phase = None
    if in_season and local.hour in beach_hours:
        beach_phase = {0: 1, 5: 2, 10: 3}.get(local.minute)
    return MonitorRun(
        beach_phase=beach_phase,
        check_aemet=local.minute == 0 and local.hour in aemet_hours,
    )


class OperationalUpdateState:
    """Store one small daily monitor state with atomic replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, now: datetime) -> dict:
        local_day = now.astimezone(GUARDAMAR_TIMEZONE).date().isoformat()
        if not self.path.exists():
            return self.empty(local_day)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OperationalUpdateStateError(
                "operational update state is unreadable"
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("version") != STATE_VERSION
            or not isinstance(value.get("local_date"), str)
        ):
            raise OperationalUpdateStateError(
                "operational update state has an invalid structure"
            )
        if value["local_date"] != local_day:
            return self.empty(local_day)
        for key in ("beaches", "latest_beaches"):
            if not isinstance(value.get(key), dict):
                raise OperationalUpdateStateError(
                    "operational beach state has an invalid structure"
                )
        beach_pending = value.get("beach_pending")
        warning_ready = value.get("warning_ready")
        if (
            not isinstance(value.get("beach_ready"), list)
            or (beach_pending is not None and not isinstance(beach_pending, dict))
            or not isinstance(value.get("warnings_initialized"), bool)
            or not isinstance(value.get("warnings"), list)
            or (warning_ready is not None and not isinstance(warning_ready, dict))
        ):
            raise OperationalUpdateStateError(
                "operational update state has invalid pending data"
            )
        if isinstance(beach_pending, dict) and (
            beach_pending.get("stage") not in {1, 2}
            or not isinstance(beach_pending.get("candidates"), list)
            or not isinstance(beach_pending.get("held"), list)
        ):
            raise OperationalUpdateStateError(
                "operational beach confirmation has an invalid structure"
            )
        if isinstance(warning_ready, dict) and (
            not isinstance(warning_ready.get("current"), list)
            or not isinstance(warning_ready.get("cancelled"), list)
            or (
                warning_ready.get("previous") is not None
                and not isinstance(warning_ready.get("previous"), list)
            )
        ):
            raise OperationalUpdateStateError(
                "operational warning update has an invalid structure"
            )
        return value

    @staticmethod
    def empty(local_day: str) -> dict:
        return {
            "version": STATE_VERSION,
            "local_date": local_day,
            "beaches": {},
            "latest_beaches": {},
            "beach_pending": None,
            "beach_ready": [],
            "warnings_initialized": False,
            "warnings": [],
            "warning_ready": None,
        }

    def write(self, value: dict) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise OperationalUpdateStateError(
                "operational update state could not be saved"
            ) from exc

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a", encoding="utf-8") as lock:
                os.chmod(lock_path, 0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError as exc:
            raise OperationalUpdateStateError(
                "another operational update run is active"
            ) from exc
        except OSError as exc:
            raise OperationalUpdateStateError(
                "operational update state could not be locked"
            ) from exc


def _beach_values(status: BeachStatus) -> Dict[str, dict]:
    jellyfish = dict(status.jellyfish_states)
    times = dict(status.updated_times)
    values = {}
    for name, flag in status.nearby_flags:
        if name not in BEACH_ORDER or name not in times:
            continue
        values[name] = {
            "flag": flag,
            "jellyfish": jellyfish.get(name),
            "updated": times[name].strftime("%H:%M"),
        }
    return values


def _field_changes(baseline: dict, current: dict) -> list[dict]:
    changes = []
    for name in KNOWN_BEACHES:
        new = current.get(name)
        if new is None:
            continue
        old = baseline.get(name)
        if old is None:
            continue
        if new.get("flag") != old.get("flag"):
            changes.append({
                "beach": name,
                "field": "flag",
                "old": old.get("flag"),
                "new": new.get("flag"),
            })
        old_jellyfish = old.get("jellyfish")
        new_jellyfish = new.get("jellyfish")
        if new_jellyfish is True and old_jellyfish is None:
            changes.append({
                "beach": name,
                "field": "jellyfish",
                "old": None,
                "new": True,
            })
        elif (
            old_jellyfish is not None
            and new_jellyfish is not None
            and old_jellyfish != new_jellyfish
        ):
            changes.append({
                "beach": name,
                "field": "jellyfish",
                "old": old_jellyfish,
                "new": new_jellyfish,
            })
    return changes


def _initial_flag_changes(current: dict) -> list[dict]:
    """Represent the first usable flag status as a public initial snapshot."""
    return [
        {
            "beach": name,
            "field": "flag",
            "old": None,
            "new": values["flag"],
            "initial": True,
        }
        for name, values in current.items()
        if values.get("flag") is not None
    ]


def _change_key(change: dict) -> Tuple[str, str]:
    return change["beach"], change["field"]


def observe_beaches(state: dict, status: BeachStatus, phase: int) -> None:
    """Advance one bounded three-sample beach confirmation window."""
    current = _beach_values(status)
    if not current:
        return
    baseline = state["beaches"]
    latest = state["latest_beaches"]
    accepted = {}
    for name, values in current.items():
        previous = latest.get(name)
        if previous is not None:
            old_time = previous.get("updated")
            new_time = values.get("updated")
            if old_time and new_time and new_time < old_time:
                continue
            if old_time and new_time == old_time and any(
                values.get(field) != previous.get(field)
                for field in ("flag", "jellyfish")
            ):
                continue
            merged = dict(previous)
            merged["flag"] = values["flag"]
            merged["updated"] = values["updated"]
            if values.get("jellyfish") is not None:
                merged["jellyfish"] = values["jellyfish"]
            latest[name] = merged
            accepted[name] = values
        else:
            latest[name] = dict(values)
            accepted[name] = values
    current = accepted
    if not current:
        return

    initial_status = not baseline
    if not initial_status:
        for name, values in current.items():
            if name not in baseline:
                baseline[name] = {
                    "flag": values["flag"],
                    "jellyfish": False if values.get("jellyfish") is False else None,
                }
            elif (
                baseline[name].get("jellyfish") is None
                and values.get("jellyfish") is False
            ):
                baseline[name]["jellyfish"] = False

    pending = state.get("beach_pending")
    if phase == 1:
        if pending is not None or state.get("beach_ready"):
            return
        candidates = (
            _initial_flag_changes(current)
            if initial_status else _field_changes(baseline, current)
        )
        if candidates:
            state["beach_pending"] = {
                "stage": 1,
                "candidates": candidates,
                "held": [],
                "initial": initial_status,
            }
        return

    if not isinstance(pending, dict):
        return
    stage = pending.get("stage")
    if stage not in {1, 2} or phase != stage + 1:
        return

    changes = (
        _initial_flag_changes(current)
        if pending.get("initial") else _field_changes(baseline, current)
    )
    observed = {_change_key(item): item for item in changes}
    held = list(pending.get("held", ()))
    rolled = []
    handled = set()
    for candidate in pending.get("candidates", ()):
        key = _change_key(candidate)
        handled.add(key)
        live = observed.get(key)
        if live is None:
            continue
        if live.get("new") == candidate.get("new"):
            held.append(live)
        elif stage == 1:
            rolled.append(live)

    if stage == 1:
        rolled.extend(
            change for key, change in observed.items() if key not in handled
        )
        if rolled:
            state["beach_pending"] = {
                "stage": 2,
                "candidates": rolled,
                "held": held,
            }
            return

    state["beach_pending"] = None
    state["beach_ready"] = held


def miss_beach_sample(state: dict, phase: int) -> None:
    """Close a bounded confirmation safely after a missing valid sample."""
    pending = state.get("beach_pending")
    if not isinstance(pending, dict):
        return
    stage = pending.get("stage")
    if phase == 2 and stage == 1:
        state["beach_pending"] = None
    elif phase == 3:
        if stage == 2:
            state["beach_ready"] = list(pending.get("held", ()))
        state["beach_pending"] = None


def _warning_dict(warning: Warning) -> dict:
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


def seed_warnings(state: dict, warnings: Sequence[Warning]) -> None:
    if state.get("warnings_initialized"):
        return
    state["warnings"] = [_warning_dict(item) for item in warnings]
    state["warnings_initialized"] = True


def seed_beaches(state: dict, baseline: object) -> None:
    """Reuse verified beach values stored with the daily beach root."""
    if state["beaches"] or not isinstance(baseline, dict):
        return
    for name in KNOWN_BEACHES:
        value = baseline.get(name)
        if not isinstance(value, dict):
            continue
        flag = value.get("flag")
        jellyfish = value.get("jellyfish")
        if flag not in FLAG_DOTS or (
            jellyfish is not None and not isinstance(jellyfish, bool)
        ):
            continue
        state["beaches"][name] = {"flag": flag, "jellyfish": jellyfish}
        state["latest_beaches"][name] = {"flag": flag, "jellyfish": jellyfish}


def confirmed_beach_status(state: dict, now: datetime) -> Optional[BeachStatus]:
    """Build the full confirmed snapshot without erasing temporarily missing beaches."""
    confirmed = {
        name: dict(value)
        for name, value in state.get("beaches", {}).items()
        if name in BEACH_ORDER and isinstance(value, dict)
    }
    for change in state.get("beach_ready") or ():
        if not isinstance(change, dict) or change.get("beach") not in BEACH_ORDER:
            continue
        field = change.get("field")
        if field not in {"flag", "jellyfish"}:
            continue
        confirmed.setdefault(change["beach"], {})[field] = change.get("new")

    flags = tuple(
        (name, confirmed[name]["flag"])
        for name in KNOWN_BEACHES
        if confirmed.get(name, {}).get("flag") in FLAG_DOTS
    )
    if not flags:
        return None
    jellyfish_states = tuple(
        (name, confirmed[name]["jellyfish"])
        for name in KNOWN_BEACHES
        if isinstance(confirmed.get(name, {}).get("jellyfish"), bool)
    )
    return BeachStatus(
        flag_color=None,
        sea_temperature_c=None,
        nearby_flags=flags,
        jellyfish_beaches=tuple(
            name for name, present in jellyfish_states if present
        ),
        jellyfish_states=jellyfish_states,
        source_date=now.astimezone(GUARDAMAR_TIMEZONE).date(),
    )


def observe_warnings(
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
    changed_events = {
        identity[0] for identity in added_or_changed
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
        event_key = item.get("event", "").casefold()
        same_context_other_parameter = (
            item.get("parameter_code") is not None
            and any(
                candidate.get("event", "").casefold() == event_key
                and candidate.get("starts_at") == item.get("starts_at")
                and candidate.get("ends_at") == item.get("ends_at")
                and candidate.get("parameter_code") != item.get("parameter_code")
                for candidate in current
            )
        )
        if event_key in changed_events or same_context_other_parameter:
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


def _warning_from_dict(value: dict) -> Warning:
    def parsed(name: str):
        raw = value.get(name)
        return datetime.fromisoformat(raw) if raw else None

    return Warning(
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


def _beach_change_lines(changes: Sequence[dict]) -> list[str]:
    initial = bool(changes) and all(change.get("initial") for change in changes)
    lines = [
        "🏖 <b>Пляжи Guardamar:</b>"
        if initial else "🏖 <b>Изменения на пляжах:</b>"
    ]
    for change in changes:
        name = html.escape(BEACH_NAMES.get(change["beach"], change["beach"]))
        if change["field"] == "flag":
            old = FLAG_DOTS.get(change.get("old"), "?")
            new = FLAG_DOTS.get(change.get("new"), "?")
            lines.append(
                f"• {name}: {new}"
                if initial else f"• {name}: {old} → {new}"
            )
        elif change.get("new") is True:
            lines.append(f"• 🪼 Медузы: {name}")
        else:
            lines.append(f"• 🪼 На {name} отметка о медузах снята")
    return lines


def _beach_name_lines(names: Sequence[str]) -> list[str]:
    """Render narrow-screen beach-name rows with at most three names."""
    escaped = [
        f"<b>{html.escape(BEACH_NAMES.get(name, name))}</b>"
        for name in names
    ]
    return [
        ", ".join(escaped[offset:offset + 3])
        for offset in range(0, len(escaped), 3)
    ]


def _show_flag_meaning(color: str, notice: Optional[BeachNotice]) -> bool:
    if color == "red" or notice is None:
        return True
    if notice.bathing_prohibited:
        return False
    return color == "yellow"

def _beach_root_flag_lines(
    status: Optional[BeachStatus],
    notice: Optional[BeachNotice],
) -> list[str]:
    if status is None or not status.nearby_flags:
        return []
    flags = {
        name: color
        for name, color in status.nearby_flags
        if name in BEACH_ORDER and color in FLAG_DOTS
    }
    if not flags:
        return []
    labels = {
        "red": ("Красный", "Красные", "⛔ Купание запрещено"),
        "yellow": ("Жёлтый", "Жёлтые", "⚠️ Купаться с осторожностью"),
        "green": ("Зелёный", "Зелёные", "✅ Купание разрешено"),
    }

    if set(flags) == set(BEACH_ORDER) and len(set(flags.values())) == 1:
        color = next(iter(flags.values()))
        _, plural, meaning = labels[color]
        lines = [f"{FLAG_DOTS[color]} На всех пляжах {plural.lower()} флаги"]
        if _show_flag_meaning(color, notice):
            lines.append(meaning)
        return lines

    blocks = []
    for color in ("red", "yellow", "green"):
        names = [name for name in KNOWN_BEACHES if flags.get(name) == color]
        if not names:
            continue
        singular, plural, meaning = labels[color]
        heading = (
            f"{FLAG_DOTS[color]} {singular} флаг"
            if len(names) == 1
            else f"{FLAG_DOTS[color]} {plural} флаги"
        )
        block = [heading, *_beach_name_lines(names)]
        if _show_flag_meaning(color, notice):
            block.append(meaning)
        blocks.append(block)

    lines = []
    for block in blocks:
        if lines:
            lines.append("")
        lines.extend(block)
    return lines

def build_beach_root_message(
    status: Optional[BeachStatus],
    notice: Optional[BeachNotice],
) -> Optional[str]:
    """Render one self-explanatory daily beach root from verified facts."""
    displayed_notice = notice
    if (
        notice is not None
        and not notice.bathing_prohibited
        and status is not None
        and any(color == "red" for _, color in status.nearby_flags)
    ):
        # Mayor parsing intentionally keeps no beach scope. Keep the caution as
        # a constraint on green wording, but do not render a weaker generic
        # statement beside a stricter confirmed beach-specific red flag.
        displayed_notice = None
    context = _beach_root_flag_lines(status, notice)
    if status is not None and status.jellyfish_beaches:
        jellyfish = sorted(
            status.jellyfish_beaches,
            key=lambda name: BEACH_ORDER.get(name, len(BEACH_ORDER)),
        )
        for offset in range(0, len(jellyfish), 3):
            chunk = jellyfish[offset:offset + 3]
            prefix = "🪼 Медузы: " if offset == 0 else "   🪼 "
            context.append(
                prefix
                + ", ".join(
                    html.escape(BEACH_NAMES.get(name, name)) for name in chunk
                )
            )
    if displayed_notice is not None:
        heading = (
            "⛔ Ограничение купания"
            if displayed_notice.bathing_prohibited
            else "🏖 Информация о купании"
        )
        if context:
            context.append("")
        context.extend([f"<b>{heading}:</b>", html.escape(displayed_notice.text)])
    if not context:
        return None
    return with_footer("\n".join([
        "🏖 <b>Пляжи Гуардамара сегодня</b>",
        "",
        *context,
    ]))


def _cancelled_warning_period(warning: Warning, now: datetime) -> str:
    """Return a compact Russian target period for a cancelled warning."""
    if warning.starts_at is None:
        return ""
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    warning_day = warning.starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
    if warning_day == local_day:
        return "На сегодня"
    if warning_day == local_day + timedelta(days=1):
        return "На завтра"
    return f"На {warning_day.day} {MONTHS_GENITIVE[warning_day.month]}"


def _joined_warning_labels(labels: Sequence[str]) -> str:
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


def build_update_message(state: dict, now: datetime) -> Optional[str]:
    """Render only the AEMET portion; beaches use their own reply thread."""
    warning_ready = state.get("warning_ready")
    if not isinstance(warning_ready, dict):
        return None
    warning_lines = _warning_update_lines(warning_ready, now)
    return with_footer("\n".join(warning_lines)) if warning_lines else None


def build_beach_message(state: dict, now: datetime) -> Optional[str]:
    """Render only confirmed beach changes for the daily beach thread."""
    changes = state.get("beach_ready") or []
    if not changes:
        return None
    lines = _beach_change_lines(changes)
    confirmed = {
        name: dict(value)
        for name, value in state.get("beaches", {}).items()
    }
    for change in changes:
        confirmed.setdefault(change["beach"], {})[change["field"]] = change["new"]
    if not all(change.get("initial") for change in changes):
        status = BeachStatus(
            flag_color=None,
            sea_temperature_c=None,
            nearby_flags=tuple(
                (name, confirmed[name]["flag"])
                for name in KNOWN_BEACHES
                if confirmed.get(name, {}).get("flag") in FLAG_DOTS
            ),
            jellyfish_beaches=tuple(
                name for name in KNOWN_BEACHES
                if confirmed.get(name, {}).get("jellyfish") is True
            ),
        )
        context = _beach_operational_lines(status, None)
        if context:
            context[0] = "<b>Последние подтверждённые флаги:</b>"
            lines.extend(["", *context])
    return with_footer("\n".join(lines))


def clear_beach_ready(state: dict) -> None:
    for change in state.get("beach_ready", ()):
        beach = state["beaches"].setdefault(change["beach"], {})
        beach[change["field"]] = change["new"]
    state["beach_ready"] = []


def finalize_delivery(state: dict) -> None:
    """Commit a successfully delivered AEMET update."""
    clear_beach_ready(state)
    ready = state.get("warning_ready")
    if isinstance(ready, dict):
        state["warnings"] = list(ready.get("current", ()))
        state["warnings_initialized"] = True
        state["warning_ready"] = None
