"""Small, annually reviewed local celebration calendar for Guardamar."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .holidays import official_holidays_on
from .models import Celebration, Holiday


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_ALERT_STATE_PATH = "state/celebration_alert.json"

# Reviewed 2026 local festive periods and traditions. These are presentation
# facts only: they never affect official-holiday or municipal-market logic.
# Sources:
# - Turisme Guardamar: Carnaval de Guardamar del Segura 2026
# - Turisme Guardamar: Semana Santa
# - Turisme Guardamar: Fiestas Patronales
# - Turisme Guardamar: Programa completo Hogueras de San Juan 2026
# - Turisme Guardamar: Programa de Moros y Cristianos 2026
# - Turisme Guardamar: Fiestas del Campo de Guardamar 2026
# - Turisme Guardamar: Fiestas de la Virgen del Rosario 2026
# - Turisme Guardamar: Todos los Santos y Halloween
_CELEBRATIONS: Dict[int, Tuple[Celebration, ...]] = {
    2026: (
        Celebration(
            "Карнавал в Гуардамаре",
            date(2026, 2, 14),
            date(2026, 2, 15),
        ),
        Celebration(
            "Страстная неделя (Semana Santa)",
            date(2026, 3, 29),
            date(2026, 4, 5),
        ),
        Celebration(
            "День Святого Висенте Феррера",
            date(2026, 4, 13),
            date(2026, 4, 13),
        ),
        Celebration(
            "День Девы Марии Фатимской в Campo de Guardamar",
            date(2026, 5, 13),
            date(2026, 5, 13),
        ),
        Celebration(
            "Праздники Сан-Хуан (Hogueras de San Juan)",
            date(2026, 6, 20),
            date(2026, 6, 24),
            official_holiday_dates=(date(2026, 6, 24),),
        ),
        Celebration(
            "Праздники Мавров и Христиан в честь Sant Jaume",
            date(2026, 7, 16),
            date(2026, 7, 26),
            official_holiday_dates=(date(2026, 7, 24),),
        ),
        Celebration(
            "Праздники Campo de Guardamar в честь Девы Марии Фатимской",
            date(2026, 8, 29),
            date(2026, 9, 13),
        ),
        Celebration(
            "Праздники в честь Девы Марии Розария",
            date(2026, 9, 19),
            date(2026, 10, 7),
            official_holiday_dates=(date(2026, 10, 7),),
        ),
        Celebration(
            "День всех святых",
            date(2026, 11, 1),
            date(2026, 11, 1),
        ),
    ),
}

_MONTHS_GENITIVE = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

_SCOPE_LABELS = {
    "national": "национальный праздник",
    "regional": "региональный праздник",
    "local": "официальный городской праздник",
}


def celebrations_for_year(year: int) -> Optional[Tuple[Celebration, ...]]:
    """Return the reviewed local celebration calendar, or None if unknown."""

    return _CELEBRATIONS.get(year)


def celebrations_on(local_day: date) -> Tuple[Celebration, ...]:
    """Return reviewed celebrations active on one Guardamar local date."""

    celebrations = _CELEBRATIONS.get(local_day.year, ())
    return tuple(
        celebration
        for celebration in celebrations
        if celebration.start_date <= local_day <= celebration.end_date
    )


def celebrations_starting_on(local_day: date) -> Tuple[Celebration, ...]:
    """Return reviewed celebrations whose first day is local_day."""

    celebrations = _CELEBRATIONS.get(local_day.year, ())
    return tuple(
        celebration
        for celebration in celebrations
        if celebration.start_date == local_day
    )


def _date_label(value: date) -> str:
    return f"{value.day} {_MONTHS_GENITIVE[value.month]}"


def _range_label(celebration: Celebration) -> str:
    if celebration.start_date == celebration.end_date:
        return _date_label(celebration.start_date)
    if celebration.start_date.month == celebration.end_date.month:
        return (
            f"{celebration.start_date.day}–{celebration.end_date.day} "
            f"{_MONTHS_GENITIVE[celebration.end_date.month]}"
        )
    return (
        f"{_date_label(celebration.start_date)} — "
        f"{_date_label(celebration.end_date)}"
    )


def _linked_single_holiday(
    holidays: Tuple[Holiday, ...],
    celebrations: Tuple[Celebration, ...],
    target_day: date,
) -> Optional[Holiday]:
    if len(holidays) != 1:
        return None
    if not any(
        target_day in celebration.official_holiday_dates
        for celebration in celebrations
    ):
        return None
    return holidays[0]


def _holiday_status_line(holiday: Holiday, target_day: date) -> str:
    if target_day.weekday() < 5:
        return {
            "local": "🏛️ Официальный городской выходной.",
            "regional": "🏛️ Региональный праздник · официальный выходной.",
            "national": "🏛️ Национальный праздник · официальный выходной.",
        }.get(holiday.scope, "🏛️ Официальный выходной день.")
    return {
        "local": "🏛️ Официальный городской праздник.",
        "regional": "🏛️ Официальный региональный праздник.",
        "national": "🏛️ Официальный национальный праздник.",
    }.get(holiday.scope, "🏛️ Официальный праздник.")


@dataclass(frozen=True)
class CelebrationAlertPublication:
    target_date: date
    message: str


def build_celebration_alert(now: datetime) -> Optional[CelebrationAlertPublication]:
    """Build one next-day festive notice from reviewed local data only."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    target_day = local_day + timedelta(days=1)
    active = celebrations_on(target_day)
    starting = celebrations_starting_on(target_day)
    linked = tuple(
        celebration
        for celebration in active
        if target_day in celebration.official_holiday_dates
    )

    relevant = tuple(dict.fromkeys(starting + linked))
    holidays = tuple(
        holiday
        for holiday in official_holidays_on(target_day)
        if holiday.scope in _SCOPE_LABELS
    )
    if not relevant and not holidays:
        return None

    linked_holiday = _linked_single_holiday(holidays, relevant, target_day)
    visible_holidays = () if linked_holiday is not None else holidays

    lines = ["🎉 <b>Завтра в Гуардамаре:</b>"]
    for celebration in relevant:
        if celebration.start_date == target_day:
            if celebration.start_date == celebration.end_date:
                suffix = "завтра"
            else:
                suffix = _range_label(celebration)
        elif celebration.end_date == target_day:
            suffix = "последний день"
        else:
            suffix = f"до {_date_label(celebration.end_date)}"
        lines.append(f"• {celebration.name} · {suffix}")

    for holiday in visible_holidays:
        lines.append(f"• {holiday.name} — {_SCOPE_LABELS[holiday.scope]}")

    if linked_holiday is not None:
        lines.append("")
        lines.append(_holiday_status_line(linked_holiday, target_day))
    elif holidays and target_day.weekday() < 5:
        lines.append("")
        lines.append("🏛️ Официальный выходной день.")

    return CelebrationAlertPublication(
        target_date=target_day,
        message=with_footer("\n".join(lines)),
    )


class CelebrationAlertStateError(RuntimeError):
    """Raised when festive-alert publication state cannot be trusted."""


class CelebrationAlertState:
    """Minimal crash-safe at-most-once state for one target date."""

    VERSION = 1

    def __init__(self, path: Path = Path(DEFAULT_ALERT_STATE_PATH)) -> None:
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": self.VERSION}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CelebrationAlertStateError(
                "celebration-alert state is unreadable"
            ) from exc
        if not isinstance(value, dict) or value.get("version") != self.VERSION:
            raise CelebrationAlertStateError(
                "celebration-alert state has an invalid structure"
            )
        raw_date = value.get("target_date")
        status = value.get("status")
        if raw_date is None and status is None:
            if set(value) != {"version"}:
                raise CelebrationAlertStateError(
                    "celebration-alert empty state has unexpected fields"
                )
            return value
        if not isinstance(raw_date, str) or status not in {"uncertain", "sent"}:
            raise CelebrationAlertStateError(
                "celebration-alert state has an invalid publication marker"
            )
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise CelebrationAlertStateError(
                "celebration-alert state has an invalid target date"
            ) from exc
        if set(value) != {"version", "target_date", "status"}:
            raise CelebrationAlertStateError(
                "celebration-alert state has unexpected fields"
            )
        return value

    def status(self, target_day: date) -> Optional[str]:
        value = self._read()
        if value.get("target_date") != target_day.isoformat():
            return None
        return value.get("status")

    def mark_uncertain(self, target_day: date) -> None:
        self._write({
            "version": self.VERSION,
            "target_date": target_day.isoformat(),
            "status": "uncertain",
        })

    def mark_sent(self, target_day: date) -> None:
        self._write({
            "version": self.VERSION,
            "target_date": target_day.isoformat(),
            "status": "sent",
        })

    def clear(self, target_day: date) -> None:
        value = self._read()
        if value.get("target_date") == target_day.isoformat():
            self._write({"version": self.VERSION})

    def _write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CelebrationAlertStateError(
                    "another celebration-alert run is active"
                ) from exc
            yield
