"""Bounded later-day beach and AEMET change monitoring."""

import fcntl
import html
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .digest import (
    BEACH_NAMES,
    FLAG_DOTS,
    _beach_operational_lines,
    _warning_text,
    build_warning_section,
)
from .models import BeachStatus, Warning
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
        or (day.month == 9 and day.day <= 14)
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
            or (
                beach_pending is not None
                and not isinstance(beach_pending, dict)
            )
            or not isinstance(value.get("warnings_initialized"), bool)
            or not isinstance(value.get("warnings"), list)
            or (
                warning_ready is not None
                and not isinstance(warning_ready, dict)
            )
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


def _change_key(change: dict) -> Tuple[str, str]:
    return change["beach"], change["field"]


def observe_beaches(
    state: dict,
    status: BeachStatus,
    phase: int,
) -> None:
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

    # A newly seen flag is availability, not a transition. An explicit
    # negative jellyfish value is also a safe baseline; first positive remains
    # a candidate so a newly reported hazard is not silently swallowed.
    for name, values in current.items():
        if name not in baseline:
            baseline[name] = {
                "flag": values["flag"],
                "jellyfish": (
                    False if values.get("jellyfish") is False else None
                ),
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
        candidates = _field_changes(baseline, current)
        if candidates:
            state["beach_pending"] = {
                "stage": 1,
                "candidates": candidates,
                "held": [],
            }
        return

    if not isinstance(pending, dict):
        return
    stage = pending.get("stage")
    if stage not in {1, 2} or phase != stage + 1:
        return

    observed = {
        _change_key(item): item
        for item in _field_changes(baseline, current)
    }
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
        "starts_at": (
            warning.starts_at.isoformat() if warning.starts_at else None
        ),
        "ends_at": warning.ends_at.isoformat() if warning.ends_at else None,
        "description": (
            " ".join(warning.description.split())
            if warning.description else None
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


def seed_warnings(state: dict, warnings: Sequence[Warning]) -> None:
    if state.get("warnings_initialized"):
        return
    state["warnings"] = [_warning_dict(item) for item in warnings]
    state["warnings_initialized"] = True


def seed_beaches(state: dict, baseline: object) -> None:
    """Reuse the verified beach values stored with the full daily digest."""

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
        state["beaches"][name] = {
            "flag": flag,
            "jellyfish": jellyfish,
        }
        state["latest_beaches"][name] = {
            "flag": flag,
            "jellyfish": jellyfish,
        }


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
    previous_by_id = {_warning_identity(item): item for item in previous}
    current_ids = {_warning_identity(item) for item in current}
    added_or_changed = current_ids - set(previous_by_id)
    changed_events = {
        identity[0] for identity in added_or_changed
    }
    removed = [
        item for identity, item in previous_by_id.items()
        if identity not in current_ids
    ]
    early_cancelled = []
    for item in removed:
        # A replacement interval/content for the same event is an update, not
        # a simultaneous cancellation. Another unchanged interval with the
        # same event name must not hide a genuinely removed warning.
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
        # Natural expiry and unchanged valid responses advance silently.
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
    )


def _beach_change_lines(changes: Sequence[dict]) -> list[str]:
    lines = ["🏖 <b>Изменения на пляжах:</b>"]
    for change in changes:
        name = html.escape(BEACH_NAMES.get(change["beach"], change["beach"]))
        if change["field"] == "flag":
            old = FLAG_DOTS.get(change.get("old"), "—")
            new = FLAG_DOTS.get(change.get("new"), "—")
            lines.append(f"• {name}: {old} → {new}")
        elif change.get("new") is True:
            lines.append(f"• 🪼 Медузы: {name}")
        else:
            lines.append(f"• 🪼 На {name} отметка о медузах снята")
    return lines


def build_update_message(state: dict, now: datetime) -> Optional[str]:
    sections = []
    beach_ready = state.get("beach_ready") or []
    if beach_ready:
        beach_lines = _beach_change_lines(beach_ready)
        confirmed = {
            name: dict(value)
            for name, value in state.get("beaches", {}).items()
        }
        for change in beach_ready:
            confirmed.setdefault(change["beach"], {})[
                change["field"]
            ] = change["new"]
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
            beach_lines.extend(["", *context])
        sections.append("\n".join(beach_lines))

    warning_ready = state.get("warning_ready")
    if isinstance(warning_ready, dict):
        warning_lines = []
        current = tuple(
            _warning_from_dict(item)
            for item in warning_ready.get("current", ())
        )
        if current:
            warning_lines.append(build_warning_section(current, now))
        for item in warning_ready.get("cancelled", ()):
            warning = _warning_from_dict(item)
            warning_lines.extend([
                "⚠️ <b>Обновление AEMET:</b>",
                "Зона: южное побережье Аликанте",
                "✅ Досрочно отменено: "
                f"{html.escape(_warning_text(warning.event))}",
            ])
        if warning_lines:
            sections.append("\n".join(warning_lines))

    if not sections:
        return None
    return with_footer("\n\n".join(sections))


def finalize_delivery(state: dict) -> None:
    for change in state.get("beach_ready", ()):
        beach = state["beaches"].setdefault(change["beach"], {})
        beach[change["field"]] = change["new"]
    state["beach_ready"] = []
    ready = state.get("warning_ready")
    if isinstance(ready, dict):
        state["warnings"] = list(ready.get("current", ()))
        state["warnings_initialized"] = True
        state["warning_ready"] = None
