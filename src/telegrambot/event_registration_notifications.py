"""Crash-safe one-off event registration lifecycle.

Source adapters own evidence and stable identity.  This module owns only the
small source-independent semantic diff, one-message rendering and delivery
transaction.  The first source is CONVEGA.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import html
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .convega import (
    ConvegaSourceError,
    convega_snapshot_observed_at,
    load_convega_records,
)
from .event_translations import cached_title
from .telegram import TelegramError, is_ambiguous_send_failure, send_message


LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

DEFAULT_SOURCE_STATE_PATH = Path("state/convega_events.json")
DEFAULT_STATE_PATH = Path("state/event_registration_notifications.json")
DEFAULT_TRANSLATION_PATH = Path("state/event_translations.json")

STATE_VERSION = 1
MAX_BASELINE_RECORDS = 128
MAX_ANNOUNCED_RECORDS = 128
MAX_SENT_TRIGGERS = 512
MAX_MESSAGE_LENGTH = 4096
RETENTION_DAYS = 30

_EXPLICIT_STATUSES = frozenset({"open", "full", "closed"})
_STATUSES = frozenset({"unknown", *_EXPLICIT_STATUSES})


class RegistrationStateError(RuntimeError):
    """Lifecycle state is unreadable or violates its strict contract."""


class RegistrationDeliveryUncertain(RuntimeError):
    """Telegram may already contain the reserved publication."""


@dataclass(frozen=True)
class RegistrationRecord:
    record_id: str
    source: str
    source_url: str
    title: str
    event_start_date: date
    event_end_date: Optional[date] = None
    registration_start_date: Optional[date] = None
    registration_start_time: Optional[time] = None
    registration_end_date: Optional[date] = None
    registration_end_time: Optional[time] = None
    status: str = "unknown"
    until_full: bool = False
    registration_url: Optional[str] = None
    registration_contact: Optional[str] = None


@dataclass(frozen=True)
class RegistrationPublication:
    message: str
    record_ids: Tuple[str, ...]
    trigger_ids: Tuple[str, ...]
    candidate_baseline: Mapping[str, Mapping[str, Any]]
    candidate_announced_record_ids: Tuple[str, ...]
    candidate_sent_triggers: Tuple[str, ...]


@dataclass(frozen=True)
class RegistrationPlan:
    candidate_baseline: Mapping[str, Mapping[str, Any]]
    candidate_announced_record_ids: Tuple[str, ...]
    candidate_sent_triggers: Tuple[str, ...]
    publication: Optional[RegistrationPublication]


@dataclass(frozen=True)
class _Notice:
    kind: str
    record: RegistrationRecord
    trigger_id: Optional[str] = None
    old_event_date: Optional[date] = None
    old_end_date: Optional[date] = None


def _date_or_none(value: Any) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _time_or_none(value: Any) -> Optional[time]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    parsed = time.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError
    return parsed.replace(second=0, microsecond=0)


def _record_from_convega(raw: Any) -> Optional[RegistrationRecord]:
    if not isinstance(raw, Mapping) or not raw.get("guardamar_relevant"):
        return None
    try:
        record = RegistrationRecord(
            record_id=raw["record_id"],
            source=raw["source"],
            source_url=raw["source_url"],
            title=raw["title"],
            event_start_date=date.fromisoformat(raw["event_start_date"]),
            event_end_date=_date_or_none(raw.get("event_end_date")),
            registration_start_date=_date_or_none(
                raw.get("registration_start_date")
            ),
            registration_start_time=_time_or_none(
                raw.get("registration_start_time")
            ),
            registration_end_date=_date_or_none(
                raw.get("registration_end_date")
            ),
            registration_end_time=_time_or_none(
                raw.get("registration_end_time")
            ),
            status=raw["observed_status"],
            until_full=raw["until_full"],
            registration_url=raw.get("registration_url"),
            registration_contact=raw.get("registration_contact"),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not valid_registration_record(record):
        return None
    return record


def valid_registration_record(record: RegistrationRecord) -> bool:
    if (
        not record.record_id
        or not record.source
        or not record.source_url
        or not record.title
        or record.status not in _STATUSES
        or record.event_end_date is not None
        and record.event_end_date < record.event_start_date
        or record.registration_start_date is not None
        and record.registration_end_date is not None
        and record.registration_end_date < record.registration_start_date
        or record.registration_start_time is not None
        and record.registration_start_date is None
        or record.registration_end_time is not None
        and record.registration_end_date is None
    ):
        return False
    for value in (
        record.registration_url,
        record.registration_contact,
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return False
    return True


def _temporally_consistent(record: RegistrationRecord, now: datetime) -> bool:
    """Reject only source states that make an explicit open claim impossible."""

    if record.status != "open":
        return True
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    if record.registration_start_date is not None:
        if record.registration_start_date > today:
            return False
        if (
            record.registration_start_date == today
            and record.registration_start_time is not None
            and local.time().replace(tzinfo=None)
            < record.registration_start_time
        ):
            return False
    if record.registration_end_date is not None:
        if record.registration_end_date < today:
            return False
        if (
            record.registration_end_date == today
            and record.registration_end_time is not None
            and local.time().replace(tzinfo=None)
            >= record.registration_end_time
        ):
            return False
    return True


async def load_registration_records(
    source_state_path: Path = DEFAULT_SOURCE_STATE_PATH,
) -> Tuple[RegistrationRecord, ...]:
    result = []
    for raw in await load_convega_records(source_state_path):
        record = _record_from_convega(raw)
        if record is not None:
            result.append(record)
    result.sort(key=lambda item: (item.event_start_date, item.record_id))
    return tuple(result)


def _baseline_record(record: RegistrationRecord, previous: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    last_explicit = None
    if previous is not None:
        value = previous.get("last_explicit_status")
        if value in _EXPLICIT_STATUSES:
            last_explicit = value
    if record.status in _EXPLICIT_STATUSES:
        last_explicit = record.status
    return {
        "record_id": record.record_id,
        "source": record.source,
        "source_url": record.source_url,
        "title": record.title,
        "event_start_date": record.event_start_date.isoformat(),
        "event_end_date": (
            record.event_end_date.isoformat()
            if record.event_end_date is not None else None
        ),
        "registration_start_date": (
            record.registration_start_date.isoformat()
            if record.registration_start_date is not None else None
        ),
        "registration_start_time": (
            record.registration_start_time.strftime("%H:%M")
            if record.registration_start_time is not None else None
        ),
        "registration_end_date": (
            record.registration_end_date.isoformat()
            if record.registration_end_date is not None else None
        ),
        "registration_end_time": (
            record.registration_end_time.strftime("%H:%M")
            if record.registration_end_time is not None else None
        ),
        "status": record.status,
        "last_explicit_status": last_explicit,
        "until_full": record.until_full,
        "registration_url": record.registration_url,
        "registration_contact": record.registration_contact,
    }


_BASELINE_FIELDS = frozenset({
    "record_id", "source", "source_url", "title", "event_start_date",
    "event_end_date", "registration_start_date", "registration_start_time",
    "registration_end_date", "registration_end_time", "status",
    "last_explicit_status", "until_full", "registration_url",
    "registration_contact",
})


def _valid_baseline_record(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _BASELINE_FIELDS:
        return False
    for field in ("record_id", "source", "source_url", "title"):
        if not isinstance(value.get(field), str) or not value[field]:
            return False
    if value.get("status") not in _STATUSES:
        return False
    if value.get("last_explicit_status") not in {*_EXPLICIT_STATUSES, None}:
        return False
    if not isinstance(value.get("until_full"), bool):
        return False
    try:
        start = date.fromisoformat(value["event_start_date"])
        end = _date_or_none(value["event_end_date"])
        reg_start = _date_or_none(value["registration_start_date"])
        reg_end = _date_or_none(value["registration_end_date"])
        _time_or_none(value["registration_start_time"])
        _time_or_none(value["registration_end_time"])
    except (TypeError, ValueError):
        return False
    if end is not None and end < start:
        return False
    if reg_start is not None and reg_end is not None and reg_end < reg_start:
        return False
    for field in ("registration_url", "registration_contact"):
        if value[field] is not None and not isinstance(value[field], str):
            return False
    return True


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "baseline": {},
        "announced_record_ids": [],
        "sent_triggers": [],
        "uncertain": None,
    }


def _valid_id_list(value: Any, *, limit: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= limit
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item for item in value)
    )


def _valid_baseline(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and len(value) <= MAX_BASELINE_RECORDS
        and all(
            isinstance(key, str)
            and key
            and isinstance(item, dict)
            and item.get("record_id") == key
            and _valid_baseline_record(item)
            for key, item in value.items()
        )
    )


def _valid_uncertain(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {
        "created_at", "message", "record_ids", "trigger_ids",
        "candidate_baseline", "candidate_announced_record_ids",
        "candidate_sent_triggers",
    }:
        return False
    try:
        created = datetime.fromisoformat(value["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        created.tzinfo is not None
        and isinstance(value["message"], str)
        and 0 < len(value["message"]) <= MAX_MESSAGE_LENGTH
        and _valid_id_list(value["record_ids"], limit=MAX_ANNOUNCED_RECORDS)
        and _valid_id_list(value["trigger_ids"], limit=MAX_SENT_TRIGGERS)
        and _valid_baseline(value["candidate_baseline"])
        and _valid_id_list(
            value["candidate_announced_record_ids"],
            limit=MAX_ANNOUNCED_RECORDS,
        )
        and _valid_id_list(
            value["candidate_sent_triggers"],
            limit=MAX_SENT_TRIGGERS,
        )
    )


def _validate_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version", "baseline", "announced_record_ids",
        "sent_triggers", "uncertain",
    }:
        raise RegistrationStateError("registration state has unexpected fields")
    if value.get("version") != STATE_VERSION:
        raise RegistrationStateError("registration state version is unsupported")
    if not _valid_baseline(value.get("baseline")):
        raise RegistrationStateError("registration baseline is invalid")
    if not _valid_id_list(
        value.get("announced_record_ids"), limit=MAX_ANNOUNCED_RECORDS
    ):
        raise RegistrationStateError("registration announced set is invalid")
    if not _valid_id_list(
        value.get("sent_triggers"), limit=MAX_SENT_TRIGGERS
    ):
        raise RegistrationStateError("registration trigger set is invalid")
    if not _valid_uncertain(value.get("uncertain")):
        raise RegistrationStateError("registration uncertain delivery is invalid")
    return value


class RegistrationNotificationState:
    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        self.path = path

    def read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistrationStateError("registration state is unreadable") from exc
        return _validate_state(value)

    def _write(self, value: Mapping[str, Any]) -> None:
        checked = _validate_state(dict(value))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(checked, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RegistrationStateError(
                    "another event-registration run is active"
                ) from exc
            yield

    def commit_plan(self, plan: RegistrationPlan) -> None:
        value = self.read()
        self._write({
            "version": STATE_VERSION,
            "baseline": dict(plan.candidate_baseline),
            "announced_record_ids": list(plan.candidate_announced_record_ids),
            "sent_triggers": list(plan.candidate_sent_triggers),
            "uncertain": None,
        })

    def mark_uncertain(
        self,
        publication: RegistrationPublication,
        now: datetime,
    ) -> None:
        value = self.read()
        if value["uncertain"] is not None:
            raise RegistrationStateError(
                "registration delivery is already uncertain"
            )
        value["uncertain"] = {
            "created_at": now.isoformat(),
            "message": publication.message,
            "record_ids": list(publication.record_ids),
            "trigger_ids": list(publication.trigger_ids),
            "candidate_baseline": dict(publication.candidate_baseline),
            "candidate_announced_record_ids": list(
                publication.candidate_announced_record_ids
            ),
            "candidate_sent_triggers": list(
                publication.candidate_sent_triggers
            ),
        }
        self._write(value)

    def clear_uncertain(self) -> None:
        value = self.read()
        value["uncertain"] = None
        self._write(value)

    def confirm_uncertain(self) -> None:
        value = self.read()
        pending = value["uncertain"]
        if pending is None:
            raise RegistrationStateError("no uncertain registration delivery")
        self._write({
            "version": STATE_VERSION,
            "baseline": pending["candidate_baseline"],
            "announced_record_ids": pending["candidate_announced_record_ids"],
            "sent_triggers": pending["candidate_sent_triggers"],
            "uncertain": None,
        })


def _local_datetime(day: date, value: time) -> datetime:
    return datetime.combine(day, value, GUARDAMAR_TIMEZONE)


def _trigger(kind: str, record: RegistrationRecord, boundary: date) -> str:
    return f"{kind}:{record.record_id}:{boundary.isoformat()}"


def _boundary_notices(
    record: RegistrationRecord,
    now: datetime,
    sent_triggers: set[str],
) -> Tuple[_Notice, ...]:
    if record.status in {"full", "closed"}:
        return ()
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    tomorrow = today + timedelta(days=1)
    notices = []

    opening = record.registration_start_date
    closing = record.registration_end_date
    if opening is not None and opening == closing:
        tomorrow_key = _trigger("one-day-tomorrow", record, opening)
        today_key = _trigger("one-day-today", record, opening)
        if opening == tomorrow and tomorrow_key not in sent_triggers:
            return (_Notice("one-day-tomorrow", record, tomorrow_key),)
        if (
            opening == today
            and tomorrow_key not in sent_triggers
            and today_key not in sent_triggers
        ):
            if record.registration_start_time is None:
                return (_Notice("one-day-today", record, today_key),)
            boundary = _local_datetime(opening, record.registration_start_time)
            if local < boundary:
                return (_Notice("one-day-today", record, today_key),)
            if record.status == "open":
                return (_Notice("active", record, today_key),)
        return ()

    if opening is not None:
        tomorrow_key = _trigger("opening-tomorrow", record, opening)
        today_key = _trigger("opening-today", record, opening)
        if opening == tomorrow and tomorrow_key not in sent_triggers:
            notices.append(_Notice("opening-tomorrow", record, tomorrow_key))
        elif opening == today and tomorrow_key not in sent_triggers and today_key not in sent_triggers:
            if record.registration_start_time is None:
                notices.append(_Notice("opening-today", record, today_key))
            else:
                boundary = _local_datetime(opening, record.registration_start_time)
                if local < boundary:
                    notices.append(_Notice("opening-today", record, today_key))
                elif record.status == "open":
                    notices.append(_Notice("active", record, today_key))

    if closing is not None:
        tomorrow_key = _trigger("closing-tomorrow", record, closing)
        today_key = _trigger("closing-today", record, closing)
        if closing == tomorrow and tomorrow_key not in sent_triggers:
            notices.append(_Notice("closing-tomorrow", record, tomorrow_key))
        elif closing == today and tomorrow_key not in sent_triggers and today_key not in sent_triggers:
            if record.registration_end_time is None:
                notices.append(_Notice("closing-today", record, today_key))
            else:
                boundary = _local_datetime(closing, record.registration_end_time)
                if local < boundary:
                    notices.append(_Notice("closing-today", record, today_key))
    return tuple(notices)


def _status_notice(
    record: RegistrationRecord,
    previous: Optional[Mapping[str, Any]],
    announced: bool,
    sent_triggers: set[str],
) -> Optional[_Notice]:
    previous_explicit = (
        previous.get("last_explicit_status")
        if previous is not None else None
    )
    if record.status == "full":
        if announced and previous_explicit != "full":
            return _Notice("full", record)
        return None
    if record.status == "closed":
        if not announced or previous_explicit == "closed":
            return None
        closing = record.registration_end_date
        if closing is not None:
            expected_keys = {
                _trigger("closing-tomorrow", record, closing),
                _trigger("closing-today", record, closing),
            }
            if expected_keys & sent_triggers:
                return None
        return _Notice("closed", record)
    if record.status == "open":
        if announced and previous_explicit in {"full", "closed"}:
            return _Notice("reopened", record)
        if not announced:
            return _Notice("active", record)
    return None


def _change_notices(
    record: RegistrationRecord,
    previous: Optional[Mapping[str, Any]],
    announced: bool,
) -> Tuple[_Notice, ...]:
    if previous is None or not announced:
        return ()
    result = []
    try:
        previous_event = date.fromisoformat(previous["event_start_date"])
    except (KeyError, TypeError, ValueError):
        previous_event = record.event_start_date
    if previous_event != record.event_start_date:
        result.append(_Notice(
            "event-date-changed",
            record,
            old_event_date=previous_event,
        ))

    previous_end = None
    try:
        previous_end = _date_or_none(previous.get("registration_end_date"))
    except ValueError:
        previous_end = None
    if (
        previous_end != record.registration_end_date
        and record.registration_end_date is not None
        and record.status not in {"full", "closed"}
    ):
        result.append(_Notice(
            "deadline-changed",
            record,
            old_end_date=previous_end,
        ))
    return tuple(result)


_NOTICE_PRIORITY = {
    "full": 10,
    "closed": 20,
    "reopened": 30,
    "event-date-changed": 40,
    "deadline-changed": 50,
    "opening-tomorrow": 60,
    "opening-today": 70,
    "active": 80,
    "closing-tomorrow": 90,
    "closing-today": 100,
    "one-day-tomorrow": 65,
    "one-day-today": 75,
}


def _select_notices(
    records: Sequence[RegistrationRecord],
    previous_baseline: Mapping[str, Mapping[str, Any]],
    announced_ids: set[str],
    sent_triggers: set[str],
    now: datetime,
) -> Tuple[_Notice, ...]:
    notices = []
    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for record in records:
        if record.event_start_date < today:
            continue
        previous = previous_baseline.get(record.record_id)
        announced = record.record_id in announced_ids

        status = _status_notice(record, previous, announced, sent_triggers)
        if status is not None:
            notices.append(status)

        notices.extend(_change_notices(record, previous, announced))

        if status is None or status.kind not in {"full", "closed"}:
            notices.extend(_boundary_notices(record, now, sent_triggers))

    # One semantic kind per record when multiple rules collapse to the same
    # resident meaning.  Preserve independent correction + terminal sections.
    unique = {}
    for notice in notices:
        key = (notice.kind, notice.record.record_id, notice.trigger_id)
        unique[key] = notice
    return tuple(sorted(
        unique.values(),
        key=lambda item: (
            _NOTICE_PRIORITY[item.kind],
            item.record.event_start_date,
            item.record.record_id,
        ),
    ))


def _format_date(value: date) -> str:
    months = (
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    return f"{value.day} {months[value.month]}"


def _record_line(record: RegistrationRecord, *, include_action: bool = False) -> str:
    title = html.escape(record.title)
    line = f"• <b>{title}</b> — {_format_date(record.event_start_date)}"
    if include_action and record.registration_url and record.status == "open":
        line += (
            ' · <a href="'
            + html.escape(record.registration_url, quote=True)
            + '">Записаться</a>'
        )
    return line


def _section_title(kind: str, record: RegistrationRecord) -> str:
    if kind == "full":
        return "🎟 <b>Места закончились</b>"
    if kind == "closed":
        return "🔒 <b>Запись закрыта</b>"
    if kind == "reopened":
        return "📝 <b>Регистрация снова открыта</b>"
    if kind == "active":
        return "📝 <b>Идёт запись</b>"
    if kind == "opening-tomorrow":
        return "📝 <b>Завтра открывается регистрация</b>"
    if kind == "opening-today":
        if record.registration_start_time is not None:
            return (
                "📝 <b>Сегодня в "
                f"{record.registration_start_time.strftime('%H:%M')} "
                "откроется регистрация</b>"
            )
        return "📝 <b>Сегодня открывается регистрация</b>"
    if kind == "one-day-tomorrow":
        return "📝 <b>Регистрация только завтра</b>"
    if kind == "one-day-today":
        return "📝 <b>Регистрация только сегодня</b>"
    if kind == "closing-tomorrow":
        return "⏳ <b>Завтра заканчивается запись</b>"
    if kind == "closing-today":
        if record.registration_end_time is not None:
            return (
                "⏳ <b>Сегодня в "
                f"{record.registration_end_time.strftime('%H:%M')} "
                "заканчивается запись</b>"
            )
        return "⏳ <b>Сегодня заканчивается запись</b>"
    if kind == "event-date-changed":
        return "🗓 <b>Изменилась дата мероприятия</b>"
    if kind == "deadline-changed":
        return "⏳ <b>Изменился срок регистрации</b>"
    raise ValueError(kind)


def _notice_line(notice: _Notice) -> str:
    record = notice.record
    if notice.kind == "event-date-changed":
        old = (
            f" (было {_format_date(notice.old_event_date)})"
            if notice.old_event_date is not None else ""
        )
        return _record_line(record) + old
    if notice.kind == "deadline-changed":
        deadline = _format_date(record.registration_end_date)
        if record.registration_end_time is not None:
            deadline += f", {record.registration_end_time.strftime('%H:%M')}"
        suffix = (
            ", если места не закончатся раньше"
            if record.until_full else ""
        )
        return _record_line(record) + f" · теперь до {deadline}{suffix}"
    include_action = notice.kind in {
        "active", "reopened", "opening-today", "opening-tomorrow",
        "closing-today", "closing-tomorrow", "one-day-today",
        "one-day-tomorrow",
    }
    line = _record_line(record, include_action=include_action)
    if notice.kind in {"closing-today", "closing-tomorrow"}:
        deadline = _format_date(record.registration_end_date)
        if record.registration_end_time is not None:
            deadline += f", {record.registration_end_time.strftime('%H:%M')}"
        if record.until_full:
            deadline += ", если места не закончатся раньше"
        line += f" · до {deadline}"
    return line


def _render_notices(notices: Sequence[_Notice], translation_path: Path) -> str:
    groups: Dict[str, list[_Notice]] = {}
    order = []
    for notice in notices:
        translated = RegistrationRecord(
            **{
                **asdict(notice.record),
                "title": cached_title(
                    translation_path,
                    notice.record.source,
                    notice.record.title,
                ),
            }
        )
        notice = _Notice(
            notice.kind,
            translated,
            notice.trigger_id,
            notice.old_event_date,
            notice.old_end_date,
        )
        if notice.kind not in groups:
            order.append(notice.kind)
            groups[notice.kind] = []
        groups[notice.kind].append(notice)

    # Keep section heading and lines compact without special renderer state.
    lines = []
    for kind in order:
        group = groups[kind]
        if lines:
            lines.append("")
        lines.append(_section_title(kind, group[0].record))
        lines.extend(_notice_line(notice) for notice in group)
    message = with_footer("\n".join(lines))
    if not message or len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError("event-registration message exceeds Telegram limit")
    return message


def _prune_baseline(
    baseline: Dict[str, Dict[str, Any]],
    announced: set[str],
    today: date,
) -> Tuple[Dict[str, Dict[str, Any]], set[str]]:
    cutoff = today - timedelta(days=RETENTION_DAYS)
    kept = {}
    for key, value in baseline.items():
        try:
            event_day = date.fromisoformat(value["event_end_date"] or value["event_start_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if event_day >= cutoff:
            kept[key] = value
        else:
            announced.discard(key)
    return kept, announced


def plan_registration_run(
    records: Sequence[RegistrationRecord],
    state_value: Mapping[str, Any],
    now: datetime,
    translation_path: Path = DEFAULT_TRANSLATION_PATH,
) -> RegistrationPlan:
    """Build the next semantic state and at most one current publication."""

    _validate_state(dict(state_value))
    unique: Dict[str, RegistrationRecord] = {}
    for record in records:
        if (
            not valid_registration_record(record)
            or not _temporally_consistent(record, now)
        ):
            continue
        existing = unique.get(record.record_id)
        if existing is not None and existing != record:
            raise ValueError("conflicting registration record identity")
        unique[record.record_id] = record

    previous_baseline = state_value["baseline"]
    announced = set(state_value["announced_record_ids"])
    sent_order = list(state_value["sent_triggers"])
    sent = set(sent_order)
    notices = _select_notices(
        tuple(unique[key] for key in sorted(unique)),
        previous_baseline,
        announced,
        sent,
        now,
    )

    candidate_baseline = {
        key: dict(value)
        for key, value in previous_baseline.items()
    }
    for record in unique.values():
        candidate_baseline[record.record_id] = _baseline_record(
            record,
            previous_baseline.get(record.record_id),
        )

    for notice in notices:
        announced.add(notice.record.record_id)
        if notice.trigger_id is not None and notice.trigger_id not in sent:
            sent.add(notice.trigger_id)
            sent_order.append(notice.trigger_id)

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    candidate_baseline, announced = _prune_baseline(
        candidate_baseline,
        announced,
        today,
    )
    ordered_announced = tuple(sorted(announced))[-MAX_ANNOUNCED_RECORDS:]
    ordered_triggers = tuple(sent_order[-MAX_SENT_TRIGGERS:])

    if not notices:
        return RegistrationPlan(
            candidate_baseline,
            ordered_announced,
            ordered_triggers,
            None,
        )

    message = _render_notices(notices, translation_path)
    record_ids = tuple(dict.fromkeys(
        notice.record.record_id for notice in notices
    ))
    trigger_ids = tuple(dict.fromkeys(
        notice.trigger_id for notice in notices
        if notice.trigger_id is not None
    ))
    publication = RegistrationPublication(
        message=message,
        record_ids=record_ids,
        trigger_ids=trigger_ids,
        candidate_baseline=candidate_baseline,
        candidate_announced_record_ids=ordered_announced,
        candidate_sent_triggers=ordered_triggers,
    )
    return RegistrationPlan(
        candidate_baseline,
        ordered_announced,
        ordered_triggers,
        publication,
    )


async def run_registration_notifications(
    now: datetime,
    state: RegistrationNotificationState,
    publish: Callable[[str], Awaitable[int]],
    *,
    source_state_path: Path = DEFAULT_SOURCE_STATE_PATH,
    translation_path: Path = DEFAULT_TRANSLATION_PATH,
) -> str:
    observed = await convega_snapshot_observed_at(source_state_path)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if (
        observed is None
        or observed.astimezone(GUARDAMAR_TIMEZONE).date() != local_day
    ):
        return "stale_source"

    records = await load_registration_records(source_state_path)
    with state.exclusive_run():
        current = state.read()
        if current["uncertain"] is not None:
            return "uncertain"

        plan = plan_registration_run(
            records,
            current,
            now,
            translation_path,
        )
        if plan.publication is None:
            state.commit_plan(plan)
            return "no_message"

        state.mark_uncertain(plan.publication, now)
        try:
            await publish(plan.publication.message)
        except TelegramError as exc:
            if is_ambiguous_send_failure(exc):
                raise RegistrationDeliveryUncertain() from exc
            state.clear_uncertain()
            raise
        except Exception:
            # Unknown publisher exceptions are deliberately ambiguous: the
            # outbound side effect cannot be proven absent.
            raise RegistrationDeliveryUncertain()

        state.confirm_uncertain()
        return "sent"


def _status_summary(value: Mapping[str, Any]) -> str:
    uncertain = value["uncertain"]
    return json.dumps({
        "version": value["version"],
        "baseline_records": len(value["baseline"]),
        "announced_records": len(value["announced_record_ids"]),
        "sent_triggers": len(value["sent_triggers"]),
        "uncertain": uncertain is not None,
        "uncertain_created_at": (
            uncertain["created_at"] if uncertain is not None else None
        ),
        "uncertain_record_ids": (
            uncertain["record_ids"] if uncertain is not None else []
        ),
    }, ensure_ascii=False, sort_keys=True)


async def _run_cli(command: str) -> int:
    now = datetime.now(GUARDAMAR_TIMEZONE)
    source_path = Path(os.environ.get(
        "CONVEGA_STATE_PATH", str(DEFAULT_SOURCE_STATE_PATH)
    ))
    state = RegistrationNotificationState(Path(os.environ.get(
        "EVENT_REGISTRATION_STATE_PATH", str(DEFAULT_STATE_PATH)
    )))
    translation_path = Path(os.environ.get(
        "EVENT_TRANSLATIONS_PATH", str(DEFAULT_TRANSLATION_PATH)
    ))

    if command == "status":
        print(_status_summary(state.read()))
        return 0
    if command == "resolve-sent":
        with state.exclusive_run():
            state.confirm_uncertain()
        print("uncertain registration delivery committed as sent")
        return 0
    if command == "resolve-unsent":
        with state.exclusive_run():
            state.clear_uncertain()
        print("uncertain registration delivery cleared for recomputation")
        return 0

    observed = await convega_snapshot_observed_at(source_path)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if (
        observed is None
        or observed.astimezone(GUARDAMAR_TIMEZONE).date() != local_day
    ):
        if command == "preview":
            print("No fresh CONVEGA registration snapshot")
        return 0

    if command == "preview":
        records = await load_registration_records(source_path)
        current = state.read()
        if current["uncertain"] is not None:
            print("Registration delivery is uncertain; automatic publication blocked")
            return 0
        plan = plan_registration_run(records, current, now, translation_path)
        print(plan.publication.message if plan.publication else "No registration notification due")
        return 0

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    async def publish(message: str) -> int:
        return await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            retry_only_rate_limits=True,
        )

    try:
        result = await run_registration_notifications(
            now,
            state,
            publish,
            source_state_path=source_path,
            translation_path=translation_path,
        )
    except RegistrationDeliveryUncertain:
        LOGGER.warning(
            "Event-registration delivery uncertain; automatic resend disabled"
        )
        return 0
    LOGGER.info("Event-registration run complete: %s", result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-off event registration lifecycle"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "preview", "status", "resolve-sent", "resolve-unsent"),
        default="run",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        code = asyncio.run(_run_cli(args.command))
    except (
        ConvegaSourceError,
        RegistrationStateError,
        TelegramError,
        ValueError,
    ) as exc:
        print(f"Command failed: {exc}", file=os.sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
