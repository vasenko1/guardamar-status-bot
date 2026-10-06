"""Pure event-access lifecycle model and planner.

No filesystem, network, source adapter or Telegram I/O belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
STATE_VERSION = 3
MAX_RECORDS = 64
MAX_OPTIONS_PER_RECORD = 16
MAX_TRIGGERS_PER_RECORD = 128
MAX_MESSAGE_LENGTH = 4096
RETENTION_DAYS = 30

ACCESS_KINDS = frozenset({"registration", "reservation", "ticket"})
STATUSES = frozenset({"unknown", "open", "full", "closed"})
EXPLICIT_STATUSES = frozenset({"open", "full", "closed"})
LEGACY_TRIGGER_KINDS = (
    "opening-tomorrow",
    "opening-today",
    "one-day-tomorrow",
    "one-day-today",
    "closing-tomorrow",
    "closing-today",
)


class EventAccessStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccessOption:
    option_id: str
    status: str = "unknown"
    label: Optional[str] = None
    opens_on: Optional[date] = None
    opens_time: Optional[time] = None
    closes_on: Optional[date] = None
    closes_time: Optional[time] = None
    until_full: bool = False
    action_url: Optional[str] = None
    action_text: Optional[str] = None


@dataclass(frozen=True)
class EventAccessRecord:
    record_id: str
    source: str
    source_url: str
    access_kind: str
    title: str
    event_start_date: date
    event_end_date: Optional[date] = None
    place: Optional[str] = None
    route: Optional[str] = None
    details: Tuple[str, ...] = ()
    schedule_note: Optional[str] = None
    occurrence_status: Optional[str] = None
    options: Tuple[AccessOption, ...] = ()


@dataclass(frozen=True)
class AccessNotice:
    kind: str
    option_id: str
    trigger_id: Optional[str] = None


@dataclass(frozen=True)
class EventAccessDecision:
    candidate_record: Mapping[str, Any]
    notices: Tuple[AccessNotice, ...]
    operation: Optional[str]
    reply_to_message_id: Optional[int]


def _text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _time(value: Any) -> Optional[time]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    parsed = time.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError
    return parsed.replace(second=0, microsecond=0)


def _valid_option(option: AccessOption) -> bool:
    if (
        not option.option_id
        or option.status not in STATUSES
        or option.opens_time is not None
        and option.opens_on is None
        or option.closes_time is not None
        and option.closes_on is None
        or option.opens_on is not None
        and option.closes_on is not None
        and option.closes_on < option.opens_on
        or option.status == "open"
        and not (_text(option.action_url) or _text(option.action_text))
    ):
        return False
    return all(
        value is None or isinstance(value, str) and bool(value.strip())
        for value in (option.label, option.action_url, option.action_text)
    )


def _valid_record(record: EventAccessRecord) -> bool:
    if (
        not record.record_id
        or not record.source
        or not record.source_url
        or record.access_kind not in ACCESS_KINDS
        or not record.title
        or record.event_end_date is not None
        and record.event_end_date < record.event_start_date
        or not 1 <= len(record.options) <= MAX_OPTIONS_PER_RECORD
    ):
        return False
    option_ids = [item.option_id for item in record.options]
    if len(option_ids) != len(set(option_ids)):
        return False
    if not all(_valid_option(item) for item in record.options):
        return False
    event_last_day = record.event_end_date or record.event_start_date
    if any(
        boundary is not None and boundary > event_last_day
        for option in record.options
        for boundary in (option.opens_on, option.closes_on)
    ):
        return False
    if record.occurrence_status not in {None, "cancelled", "postponed"}:
        return False
    if any(
        value is not None
        and (not isinstance(value, str) or not value.strip())
        for value in (record.place, record.route, record.schedule_note)
    ):
        return False
    return (
        isinstance(record.details, tuple)
        and len(record.details) <= 8
        and all(isinstance(item, str) and item.strip() for item in record.details)
    )


_OPTION_FIELDS = frozenset({
    "status",
    "last_explicit_status",
    "opens_on",
    "opens_time",
    "closes_on",
    "closes_time",
    "until_full",
    "action_url",
    "action_text",
})
_RECORD_FIELDS = frozenset({
    "source",
    "access_kind",
    "event_start_date",
    "event_end_date",
    "title",
    "place",
    "route",
    "schedule_note",
    "context_known",
    "occurrence_status",
    "options",
    "audience_known",
    "root_message_id",
    "sent_triggers",
})

_V2_RECORD_FIELDS = frozenset({
    "source",
    "access_kind",
    "event_start_date",
    "event_end_date",
    "options",
    "audience_known",
    "root_message_id",
    "sent_triggers",
})


def _valid_option_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _OPTION_FIELDS:
        return False
    if (
        value.get("status") not in STATUSES
        or value.get("last_explicit_status") not in {*EXPLICIT_STATUSES, None}
        or not isinstance(value.get("until_full"), bool)
    ):
        return False
    try:
        opens_on = _date(value.get("opens_on"))
        opens_time = _time(value.get("opens_time"))
        closes_on = _date(value.get("closes_on"))
        closes_time = _time(value.get("closes_time"))
    except (TypeError, ValueError):
        return False
    if (
        opens_time is not None
        and opens_on is None
        or closes_time is not None
        and closes_on is None
        or opens_on is not None
        and closes_on is not None
        and closes_on < opens_on
    ):
        return False
    if any(
        value.get(field) is not None
        and (
            not isinstance(value[field], str)
            or not value[field].strip()
        )
        for field in ("action_url", "action_text")
    ):
        return False
    if value["status"] == "open" and not (
        _text(value.get("action_url")) or _text(value.get("action_text"))
    ):
        return False
    return True


def _valid_record_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        return False
    if (
        not isinstance(value.get("source"), str)
        or not value["source"]
        or value.get("access_kind") not in ACCESS_KINDS
        or not isinstance(value.get("title"), str)
        or not value["title"].strip()
        or not isinstance(value.get("context_known"), bool)
        or value.get("occurrence_status") not in {None, "cancelled", "postponed"}
        or not isinstance(value.get("audience_known"), bool)
    ):
        return False
    try:
        start = date.fromisoformat(value["event_start_date"])
        end = _date(value.get("event_end_date"))
    except (KeyError, TypeError, ValueError):
        return False
    if end is not None and end < start:
        return False
    if any(
        value.get(field) is not None
        and (
            not isinstance(value[field], str)
            or not value[field].strip()
        )
        for field in ("place", "route", "schedule_note")
    ):
        return False
    options = value.get("options")
    if (
        not isinstance(options, dict)
        or not 1 <= len(options) <= MAX_OPTIONS_PER_RECORD
        or any(
            not isinstance(key, str)
            or not key
            or not _valid_option_state(item)
            for key, item in options.items()
        )
    ):
        return False
    root = value.get("root_message_id")
    if root is not None and (
        not isinstance(root, int)
        or isinstance(root, bool)
        or root <= 0
        or not value["audience_known"]
    ):
        return False
    triggers = value.get("sent_triggers")
    return (
        isinstance(triggers, list)
        and len(triggers) <= MAX_TRIGGERS_PER_RECORD
        and len(triggers) == len(set(triggers))
        and all(isinstance(item, str) and item for item in triggers)
    )



def _valid_v2_record_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _V2_RECORD_FIELDS:
        return False
    if (
        not isinstance(value.get("source"), str)
        or not value["source"]
        or value.get("access_kind") not in ACCESS_KINDS
        or not isinstance(value.get("audience_known"), bool)
    ):
        return False
    try:
        start = date.fromisoformat(value["event_start_date"])
        end = _date(value.get("event_end_date"))
    except (KeyError, TypeError, ValueError):
        return False
    if end is not None and end < start:
        return False
    options = value.get("options")
    if (
        not isinstance(options, dict)
        or not 1 <= len(options) <= MAX_OPTIONS_PER_RECORD
        or any(
            not isinstance(key, str)
            or not key
            or not _valid_option_state(item)
            for key, item in options.items()
        )
    ):
        return False
    root = value.get("root_message_id")
    if root is not None and (
        not isinstance(root, int)
        or isinstance(root, bool)
        or root <= 0
        or not value["audience_known"]
    ):
        return False
    triggers = value.get("sent_triggers")
    return (
        isinstance(triggers, list)
        and len(triggers) <= MAX_TRIGGERS_PER_RECORD
        and len(triggers) == len(set(triggers))
        and all(isinstance(item, str) and item for item in triggers)
    )


def empty_state() -> Dict[str, Any]:
    return {"version": STATE_VERSION, "records": {}, "uncertain": None}


def validate_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version", "records", "uncertain"
    }:
        raise EventAccessStateError("event-access state has unexpected fields")
    if value.get("version") != STATE_VERSION:
        raise EventAccessStateError("event-access state version is unsupported")
    records = value.get("records")
    if (
        not isinstance(records, dict)
        or len(records) > MAX_RECORDS
        or any(
            not isinstance(key, str)
            or not key
            or not _valid_record_state(item)
            for key, item in records.items()
        )
    ):
        raise EventAccessStateError("event-access records are invalid")

    uncertain = value.get("uncertain")
    if uncertain is None:
        return value
    if not isinstance(uncertain, dict) or set(uncertain) != {
        "created_at",
        "record_id",
        "operation",
        "message",
        "candidate_record",
    }:
        raise EventAccessStateError("event-access uncertain delivery is invalid")
    try:
        created = datetime.fromisoformat(uncertain["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventAccessStateError(
            "event-access uncertain timestamp is invalid"
        ) from exc
    if (
        created.tzinfo is None
        or not isinstance(uncertain.get("record_id"), str)
        or not uncertain["record_id"]
        or uncertain.get("operation") not in {"root", "reply"}
        or not isinstance(uncertain.get("message"), str)
        or not 1 <= len(uncertain["message"]) <= MAX_MESSAGE_LENGTH
        or not _valid_record_state(uncertain.get("candidate_record"))
    ):
        raise EventAccessStateError("event-access uncertain delivery is invalid")
    candidate = uncertain["candidate_record"]
    if uncertain["operation"] == "root" and candidate["root_message_id"] is not None:
        raise EventAccessStateError("uncertain root already has a root ID")
    if uncertain["operation"] == "reply":
        if candidate["root_message_id"] is None:
            raise EventAccessStateError("uncertain reply has no root ID")
        if uncertain["record_id"] not in records:
            raise EventAccessStateError("uncertain reply has no committed record")
    return value


def _state_option(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    previous = previous or {}
    last_explicit = previous.get("last_explicit_status")
    if last_explicit not in EXPLICIT_STATUSES:
        last_explicit = None
    if option.status in EXPLICIT_STATUSES:
        last_explicit = option.status

    def keep(field: str, current: Any) -> Any:
        return current if current is not None else previous.get(field)

    return {
        "status": option.status,
        "last_explicit_status": last_explicit,
        "opens_on": keep(
            "opens_on",
            option.opens_on.isoformat() if option.opens_on else None,
        ),
        "opens_time": keep(
            "opens_time",
            option.opens_time.strftime("%H:%M") if option.opens_time else None,
        ),
        "closes_on": keep(
            "closes_on",
            option.closes_on.isoformat() if option.closes_on else None,
        ),
        "closes_time": keep(
            "closes_time",
            option.closes_time.strftime("%H:%M") if option.closes_time else None,
        ),
        "until_full": option.until_full,
        "action_url": keep("action_url", _text(option.action_url)),
        "action_text": keep("action_text", _text(option.action_text)),
    }


def candidate_record_state(
    record: EventAccessRecord,
    previous: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    if not _valid_record(record):
        raise ValueError("invalid event-access record")
    if previous is not None:
        if previous.get("source") != record.source:
            raise EventAccessStateError("event-access source ownership changed")
        if previous.get("access_kind") != record.access_kind:
            raise EventAccessStateError("event-access kind changed")

    prior_options = previous.get("options", {}) if previous else {}
    options = {key: dict(item) for key, item in prior_options.items()}
    for option in record.options:
        options[option.option_id] = _state_option(
            option,
            prior_options.get(option.option_id),
        )
    def keep_context(field: str, current: Optional[str]) -> Optional[str]:
        current = _text(current)
        if current is not None:
            return current
        return _text(previous.get(field)) if previous else None

    candidate = {
        "source": record.source,
        "access_kind": record.access_kind,
        "event_start_date": record.event_start_date.isoformat(),
        "event_end_date": (
            record.event_end_date.isoformat() if record.event_end_date else None
        ),
        "title": record.title.strip(),
        "place": keep_context("place", record.place),
        "route": keep_context("route", record.route),
        "schedule_note": keep_context("schedule_note", record.schedule_note),
        "context_known": True,
        "occurrence_status": (
            record.occurrence_status
            if record.occurrence_status is not None
            else previous.get("occurrence_status") if previous else None
        ),
        "options": options,
        "audience_known": bool(previous and previous.get("audience_known")),
        "root_message_id": previous.get("root_message_id") if previous else None,
        "sent_triggers": list(previous.get("sent_triggers", ())) if previous else [],
    }
    if not _valid_record_state(candidate):
        raise EventAccessStateError("candidate event-access record is invalid")
    return candidate


def _trigger(
    kind: str,
    option: AccessOption,
    boundary: date,
    boundary_time: Optional[time] = None,
) -> str:
    suffix = boundary.isoformat()
    if boundary_time is not None:
        suffix += "T" + boundary_time.strftime("%H:%M")
    return f"{kind}:{option.option_id}:{suffix}"


def _opening_notice(
    option: AccessOption,
    now: datetime,
    sent: set[str],
) -> Optional[AccessNotice]:
    if option.opens_on is None or option.status in {"open", "full", "closed"}:
        return None
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    if option.opens_on == today + timedelta(days=1):
        kind = (
            "one-day-tomorrow"
            if option.closes_on == option.opens_on
            else "opening-tomorrow"
        )
    elif option.opens_on == today:
        if (
            option.opens_time is not None
            and local >= datetime.combine(
                option.opens_on,
                option.opens_time,
                GUARDAMAR_TIMEZONE,
            )
        ):
            return None
        kind = "opening-today"
    else:
        return None
    key = _trigger(kind, option, option.opens_on, option.opens_time)
    return None if key in sent else AccessNotice(kind, option.option_id, key)


def _closing_notice(
    option: AccessOption,
    now: datetime,
    sent: set[str],
) -> Optional[AccessNotice]:
    if option.status != "open" or option.closes_on is None:
        return None
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    if option.closes_on == today + timedelta(days=1):
        kind = "closing-tomorrow"
    elif option.closes_on == today:
        if (
            option.closes_time is not None
            and local >= datetime.combine(
                option.closes_on,
                option.closes_time,
                GUARDAMAR_TIMEZONE,
            )
        ):
            return None
        kind = "closing-today"
    else:
        return None
    key = _trigger(kind, option, option.closes_on, option.closes_time)
    return None if key in sent else AccessNotice(kind, option.option_id, key)


def _status_notice(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Optional[AccessNotice]:
    if not audience_known or previous is None:
        return None
    old_status = previous.get("status")
    old_explicit = previous.get("last_explicit_status")
    if option.status == "open":
        if old_status == "open":
            return None
        if old_explicit in {"full", "closed"}:
            return AccessNotice("reopened", option.option_id)
        if old_explicit == "open":
            return None
        return AccessNotice("open", option.option_id)
    if option.status in {"full", "closed"}:
        if old_status == "open":
            return AccessNotice(option.status, option.option_id)
        if old_status == "unknown" and old_explicit not in {"full", "closed"}:
            return AccessNotice(option.status, option.option_id)
    return None


def _deadline_notice(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Optional[AccessNotice]:
    if not audience_known or previous is None or option.closes_on is None:
        return None
    current = (
        option.closes_on.isoformat(),
        option.closes_time.strftime("%H:%M") if option.closes_time else None,
    )
    old = (previous.get("closes_on"), previous.get("closes_time"))
    if current == old:
        return None
    return AccessNotice(
        "deadline-known" if old[0] is None else "deadline-changed",
        option.option_id,
    )


def _action_notice(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Optional[AccessNotice]:
    if not audience_known or previous is None or option.status != "open":
        return None
    old = (_text(previous.get("action_url")), _text(previous.get("action_text")))
    current = (_text(option.action_url), _text(option.action_text))
    if old == (None, None) or old == current:
        return None
    return AccessNotice("action-changed", option.option_id)


def temporally_consistent(
    record: EventAccessRecord,
    now: datetime,
) -> bool:
    """Reject explicit open states impossible at the current local time."""

    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    event_last_day = record.event_end_date or record.event_start_date
    if any(option.status == "open" for option in record.options):
        if today > event_last_day:
            return False
    local_time = local.time().replace(tzinfo=None)
    for option in record.options:
        if option.status != "open":
            continue
        if option.opens_on is not None:
            if option.opens_on > today:
                return False
            if (
                option.opens_on == today
                and option.opens_time is not None
                and local_time < option.opens_time
            ):
                return False
        if option.closes_on is not None:
            if option.closes_on < today:
                return False
            if (
                option.closes_on == today
                and option.closes_time is not None
                and local_time >= option.closes_time
            ):
                return False
    return True


def _event_notices(
    record: EventAccessRecord,
    candidate: Mapping[str, Any],
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Tuple[AccessNotice, ...]:
    if not audience_known or previous is None:
        return ()

    notices = []
    current_dates = (
        candidate["event_start_date"],
        candidate["event_end_date"],
    )
    previous_dates = (
        previous.get("event_start_date"),
        previous.get("event_end_date"),
    )
    if current_dates != previous_dates:
        notices.append(AccessNotice("event-date-changed"))

    if previous.get("context_known"):
        fields = ("title", "place", "route", "schedule_note")
        if any(candidate.get(field) != previous.get(field) for field in fields):
            notices.append(AccessNotice("event-details-changed"))

    old_status = previous.get("occurrence_status")
    new_status = candidate.get("occurrence_status")
    if new_status in {"cancelled", "postponed"} and new_status != old_status:
        notices.append(AccessNotice("event-" + new_status))

    return tuple(notices)


def plan_event_access_record(
    record: EventAccessRecord,
    previous: Optional[Mapping[str, Any]],
    now: datetime,
) -> EventAccessDecision:
    candidate = candidate_record_state(record, previous)
    audience_known = bool(previous and previous.get("audience_known"))
    root_id = previous.get("root_message_id") if previous else None
    prior_options = previous.get("options", {}) if previous else {}
    sent_order = list(previous.get("sent_triggers", ())) if previous else []
    sent = set(sent_order)

    if not audience_known:
        root_notice = next(
            (
                AccessNotice("active", option.option_id)
                for option in record.options
                if option.status == "open"
            ),
            None,
        )
        if root_notice is None:
            for option in record.options:
                root_notice = _opening_notice(option, now, sent)
                if root_notice is not None:
                    break
        if root_notice is None:
            return EventAccessDecision(candidate, (), None, None)
        if root_notice.trigger_id:
            sent.add(root_notice.trigger_id)
            sent_order.append(root_notice.trigger_id)
        for option in record.options:
            reminder = _closing_notice(option, now, sent)
            if reminder is not None and reminder.trigger_id not in sent:
                sent.add(reminder.trigger_id)
                sent_order.append(reminder.trigger_id)
        candidate["audience_known"] = True
        candidate["sent_triggers"] = sent_order
        return EventAccessDecision(candidate, (root_notice,), "root", None)

    notices = list(_event_notices(
        record,
        candidate,
        previous,
        audience_known,
    ))
    for option in record.options:
        old = prior_options.get(option.option_id)
        if old is None:
            opening = _opening_notice(option, now, sent)
            if option.status == "open":
                notices.append(AccessNotice("option-added", option.option_id))
            elif opening is not None:
                notices.append(opening)
                if opening.trigger_id:
                    sent.add(opening.trigger_id)
                    sent_order.append(opening.trigger_id)
            continue

        status = _status_notice(option, old, audience_known)
        deadline = _deadline_notice(option, old, audience_known)
        action = _action_notice(option, old, audience_known)
        opening = _opening_notice(option, now, sent)
        closing = _closing_notice(option, now, sent)

        if status is not None:
            notices.append(status)
        if opening is not None and status is None:
            notices.append(opening)
        if deadline is not None and status is None:
            notices.append(deadline)
        if action is not None and status is None:
            notices.append(action)
        if closing is not None and status is None and deadline is None:
            notices.append(closing)

        for item in (opening, closing):
            if item is not None and item.trigger_id and item.trigger_id not in sent:
                sent.add(item.trigger_id)
                sent_order.append(item.trigger_id)

    candidate["sent_triggers"] = sent_order
    if len(sent_order) > MAX_TRIGGERS_PER_RECORD:
        raise EventAccessStateError("event-access trigger bound exceeded")
    if not notices:
        return EventAccessDecision(candidate, (), None, None)
    operation = "reply" if root_id is not None else "root"
    return EventAccessDecision(
        candidate,
        tuple(notices),
        operation,
        root_id if operation == "reply" else None,
    )


def prune_records(
    records: Mapping[str, Mapping[str, Any]],
    today: date,
) -> Dict[str, Dict[str, Any]]:
    cutoff = today - timedelta(days=RETENTION_DAYS)
    result: Dict[str, Dict[str, Any]] = {}
    for record_id, value in records.items():
        try:
            event_day = date.fromisoformat(
                value.get("event_end_date") or value["event_start_date"]
            )
        except (KeyError, TypeError, ValueError):
            continue
        if event_day >= cutoff:
            result[record_id] = dict(value)
    return result


_LEGACY_FIELDS = frozenset({
    "record_id",
    "source",
    "source_url",
    "title",
    "event_start_date",
    "event_end_date",
    "registration_start_date",
    "registration_start_time",
    "registration_end_date",
    "registration_end_time",
    "status",
    "last_explicit_status",
    "until_full",
    "registration_url",
    "registration_contact",
})


def _legacy_record(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _LEGACY_FIELDS:
        return False
    if (
        not all(
            isinstance(value.get(field), str) and value[field]
            for field in ("record_id", "source", "source_url", "title")
        )
        or value.get("status") not in STATUSES
        or value.get("last_explicit_status") not in {*EXPLICIT_STATUSES, None}
        or not isinstance(value.get("until_full"), bool)
    ):
        return False
    try:
        start = date.fromisoformat(value["event_start_date"])
        end = _date(value.get("event_end_date"))
        opens = _date(value.get("registration_start_date"))
        closes = _date(value.get("registration_end_date"))
        opens_time = _time(value.get("registration_start_time"))
        closes_time = _time(value.get("registration_end_time"))
    except (TypeError, ValueError):
        return False
    if (
        end is not None
        and end < start
        or opens_time is not None
        and opens is None
        or closes_time is not None
        and closes is None
        or opens is not None
        and closes is not None
        and closes < opens
    ):
        return False
    return all(
        value.get(field) is None
        or isinstance(value[field], str) and bool(value[field].strip())
        for field in ("registration_url", "registration_contact")
    )


def _legacy_trigger(trigger: str, record_ids: Sequence[str]) -> Tuple[str, str]:
    matches = []
    for kind in LEGACY_TRIGGER_KINDS:
        for record_id in record_ids:
            prefix = f"{kind}:{record_id}:"
            if not trigger.startswith(prefix):
                continue
            boundary = trigger[len(prefix):]
            try:
                date.fromisoformat(boundary)
            except ValueError:
                continue
            matches.append((record_id, f"{kind}:default:{boundary}"))
    if len(matches) != 1:
        raise EventAccessStateError(
            "legacy trigger cannot be mapped unambiguously"
        )
    return matches[0]


def migrate_v2_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version", "records", "uncertain"
    }:
        raise EventAccessStateError("event-access v2 state has unexpected fields")
    if value.get("version") != 2:
        raise EventAccessStateError("event-access v2 state version is unsupported")
    if value.get("uncertain") is not None:
        raise EventAccessStateError(
            "event-access v2 uncertain delivery must be resolved before migration"
        )

    records = value.get("records")
    if (
        not isinstance(records, dict)
        or len(records) > MAX_RECORDS
        or any(
            not isinstance(key, str)
            or not key
            or not _valid_v2_record_state(item)
            for key, item in records.items()
        )
    ):
        raise EventAccessStateError("event-access v2 records are invalid")

    migrated = {}
    for record_id, item in records.items():
        migrated[record_id] = {
            **dict(item),
            "title": record_id,
            "place": None,
            "route": None,
            "schedule_note": None,
            "context_known": False,
            "occurrence_status": None,
        }

    return validate_state({
        "version": STATE_VERSION,
        "records": migrated,
        "uncertain": None,
    })


def migrate_v1_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "baseline",
        "announced_record_ids",
        "sent_triggers",
        "uncertain",
    }:
        raise EventAccessStateError("legacy registration state has unexpected fields")
    if value.get("version") != 1:
        raise EventAccessStateError("legacy registration state version is unsupported")
    if value.get("uncertain") is not None:
        raise EventAccessStateError(
            "legacy uncertain delivery must be resolved before migration"
        )

    baseline = value.get("baseline")
    announced = value.get("announced_record_ids")
    triggers = value.get("sent_triggers")
    if (
        not isinstance(baseline, dict)
        or len(baseline) > MAX_RECORDS
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(item, dict)
            or item.get("record_id") != key
            or not _legacy_record(item)
            for key, item in baseline.items()
        )
        or not isinstance(announced, list)
        or len(announced) != len(set(announced))
        or any(item not in baseline for item in announced)
        or not isinstance(triggers, list)
        or len(triggers) != len(set(triggers))
        or any(not isinstance(item, str) or not item for item in triggers)
    ):
        raise EventAccessStateError("legacy registration state is invalid")

    announced_set = set(announced)
    records: Dict[str, Dict[str, Any]] = {}
    for record_id, item in baseline.items():
        records[record_id] = {
            "source": item["source"],
            "access_kind": "registration",
            "event_start_date": item["event_start_date"],
            "event_end_date": item["event_end_date"],
            "title": item["title"],
            "place": None,
            "route": None,
            "schedule_note": None,
            "context_known": False,
            "occurrence_status": None,
            "options": {
                "default": {
                    "status": item["status"],
                    "last_explicit_status": item["last_explicit_status"],
                    "opens_on": item["registration_start_date"],
                    "opens_time": item["registration_start_time"],
                    "closes_on": item["registration_end_date"],
                    "closes_time": item["registration_end_time"],
                    "until_full": item["until_full"],
                    "action_url": item["registration_url"],
                    "action_text": item["registration_contact"],
                }
            },
            "audience_known": record_id in announced_set,
            "root_message_id": None,
            "sent_triggers": [],
        }

    for trigger in triggers:
        record_id, mapped = _legacy_trigger(trigger, tuple(records))
        records[record_id]["sent_triggers"].append(mapped)

    return validate_state({
        "version": STATE_VERSION,
        "records": records,
        "uncertain": None,
    })
