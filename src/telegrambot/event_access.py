"""Pure event-access lifecycle model and planner.

This module owns no filesystem, network, source-adapter or Telegram I/O.
It keeps one bounded lifecycle record per real source-owned event and supports
source-proven child access options.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

STATE_VERSION = 2
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
    """Persisted event-access state is invalid or cannot be migrated safely."""


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


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def valid_access_option(option: AccessOption) -> bool:
    if (
        not isinstance(option.option_id, str)
        or not option.option_id
        or option.status not in STATUSES
        or not isinstance(option.until_full, bool)
        or option.opens_time is not None
        and option.opens_on is None
        or option.closes_time is not None
        and option.closes_on is None
        or option.opens_on is not None
        and option.closes_on is not None
        and option.closes_on < option.opens_on
    ):
        return False
    if option.status == "open" and not (
        _clean_optional_text(option.action_url)
        or _clean_optional_text(option.action_text)
    ):
        return False
    for value in (option.label, option.action_url, option.action_text):
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            return False
    return True


def valid_event_access_record(record: EventAccessRecord) -> bool:
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
    option_ids = [option.option_id for option in record.options]
    if len(option_ids) != len(set(option_ids)):
        return False
    if not all(valid_access_option(option) for option in record.options):
        return False
    for value in (record.place, record.route, record.schedule_note):
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            return False
    if (
        not isinstance(record.details, tuple)
        or len(record.details) > 8
        or any(not isinstance(item, str) or not item.strip() for item in record.details)
    ):
        return False
    return True


_OPTION_STATE_FIELDS = frozenset({
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

_RECORD_STATE_FIELDS = frozenset({
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
    if not isinstance(value, dict) or set(value) != _OPTION_STATE_FIELDS:
        return False
    if value.get("status") not in STATUSES:
        return False
    if value.get("last_explicit_status") not in {*EXPLICIT_STATUSES, None}:
        return False
    if not isinstance(value.get("until_full"), bool):
        return False
    try:
        opens_on = _date_or_none(value.get("opens_on"))
        closes_on = _date_or_none(value.get("closes_on"))
        opens_time = _time_or_none(value.get("opens_time"))
        closes_time = _time_or_none(value.get("closes_time"))
    except (TypeError, ValueError):
        return False
    if opens_time is not None and opens_on is None:
        return False
    if closes_time is not None and closes_on is None:
        return False
    if (
        opens_on is not None
        and closes_on is not None
        and closes_on < opens_on
    ):
        return False
    for field in ("action_url", "action_text"):
        item = value.get(field)
        if item is not None and (
            not isinstance(item, str) or not item.strip()
        ):
            return False
    if value["status"] == "open" and not (
        _clean_optional_text(value.get("action_url"))
        or _clean_optional_text(value.get("action_text"))
    ):
        return False
    return True


def _valid_record_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _RECORD_STATE_FIELDS:
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
        end = _date_or_none(value.get("event_end_date"))
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
    ):
        return False
    if root is not None and not value["audience_known"]:
        return False
    triggers = value.get("sent_triggers")
    if (
        not isinstance(triggers, list)
        or len(triggers) > MAX_TRIGGERS_PER_RECORD
        or len(triggers) != len(set(triggers))
        or any(not isinstance(item, str) or not item for item in triggers)
    ):
        return False
    return True


def _valid_uncertain(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {
        "created_at",
        "record_id",
        "operation",
        "message",
        "candidate_record",
    }:
        return False
    try:
        created = datetime.fromisoformat(value["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        created.tzinfo is None
        or not isinstance(value.get("record_id"), str)
        or not value["record_id"]
        or value.get("operation") not in {"root", "reply"}
        or not isinstance(value.get("message"), str)
        or not 1 <= len(value["message"]) <= MAX_MESSAGE_LENGTH
        or not _valid_record_state(value.get("candidate_record"))
    ):
        return False
    candidate = value["candidate_record"]
    if value["operation"] == "root" and candidate["root_message_id"] is not None:
        return False
    if value["operation"] == "reply" and candidate["root_message_id"] is None:
        return False
    return True


def empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "records": {},
        "uncertain": None,
    }


def validate_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "records",
        "uncertain",
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
    if not _valid_uncertain(value.get("uncertain")):
        raise EventAccessStateError("event-access uncertain delivery is invalid")
    uncertain = value.get("uncertain")
    if uncertain is not None:
        record_id = uncertain["record_id"]
        if record_id not in records and uncertain["operation"] == "reply":
            raise EventAccessStateError(
                "event-access uncertain reply has no committed record"
            )
    return value


def _option_state_from_observation(
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
        if current is not None:
            return current
        return previous.get(field)

    opens_on = keep(
        "opens_on",
        option.opens_on.isoformat() if option.opens_on is not None else None,
    )
    opens_time = keep(
        "opens_time",
        option.opens_time.strftime("%H:%M")
        if option.opens_time is not None
        else None,
    )
    closes_on = keep(
        "closes_on",
        option.closes_on.isoformat() if option.closes_on is not None else None,
    )
    closes_time = keep(
        "closes_time",
        option.closes_time.strftime("%H:%M")
        if option.closes_time is not None
        else None,
    )
    action_url = keep("action_url", _clean_optional_text(option.action_url))
    action_text = keep("action_text", _clean_optional_text(option.action_text))

    return {
        "status": option.status,
        "last_explicit_status": last_explicit,
        "opens_on": opens_on,
        "opens_time": opens_time,
        "closes_on": closes_on,
        "closes_time": closes_time,
        "until_full": option.until_full,
        "action_url": action_url,
        "action_text": action_text,
    }


def candidate_record_state(
    record: EventAccessRecord,
    previous: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    if not valid_event_access_record(record):
        raise ValueError("invalid event-access record")
    if previous is not None:
        if previous.get("source") != record.source:
            raise EventAccessStateError("event-access source ownership changed")
        if previous.get("access_kind") != record.access_kind:
            raise EventAccessStateError("event-access kind changed")

    previous_options = (
        previous.get("options", {}) if previous is not None else {}
    )
    options: Dict[str, Any] = {
        key: dict(value) for key, value in previous_options.items()
    }
    for option in record.options:
        options[option.option_id] = _option_state_from_observation(
            option,
            previous_options.get(option.option_id),
        )

    candidate = {
        "source": record.source,
        "access_kind": record.access_kind,
        "event_start_date": record.event_start_date.isoformat(),
        "event_end_date": (
            record.event_end_date.isoformat()
            if record.event_end_date is not None
            else None
        ),
        "options": options,
        "audience_known": bool(
            previous.get("audience_known") if previous is not None else False
        ),
        "root_message_id": (
            previous.get("root_message_id") if previous is not None else None
        ),
        "sent_triggers": list(
            previous.get("sent_triggers", ()) if previous is not None else ()
        ),
    }
    if not _valid_record_state(candidate):
        raise EventAccessStateError("candidate event-access record is invalid")
    return candidate


def _boundary_key(day: date, value: Optional[time]) -> str:
    result = day.isoformat()
    if value is not None:
        result += "T" + value.strftime("%H:%M")
    return result


def _trigger(
    kind: str,
    option_id: str,
    day: date,
    value: Optional[time] = None,
) -> str:
    return f"{kind}:{option_id}:{_boundary_key(day, value)}"


def _local_datetime(day: date, value: time) -> datetime:
    return datetime.combine(day, value, GUARDAMAR_TIMEZONE)


def _opening_notice(
    option: AccessOption,
    now: datetime,
    sent: set[str],
) -> Optional[AccessNotice]:
    opening = option.opens_on
    if opening is None or option.status in {"full", "closed"}:
        return None
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    tomorrow = today + timedelta(days=1)

    if opening == tomorrow:
        kind = (
            "one-day-tomorrow"
            if option.closes_on == opening
            else "opening-tomorrow"
        )
        trigger = _trigger(kind, option.option_id, opening, option.opens_time)
        if trigger not in sent:
            return AccessNotice(kind, option.option_id, trigger)
        return None

    if opening != today or option.status == "open":
        return None

    if option.opens_time is not None:
        boundary = _local_datetime(opening, option.opens_time)
        if local >= boundary:
            return None
    kind = "opening-today"
    trigger = _trigger(kind, option.option_id, opening, option.opens_time)
    if trigger in sent:
        return None
    return AccessNotice(kind, option.option_id, trigger)


def _status_notice(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Optional[AccessNotice]:
    if not audience_known or previous is None:
        return None
    previous_status = previous.get("status")
    previous_explicit = previous.get("last_explicit_status")

    if option.status == "open":
        if previous_status == "open":
            return None
        if previous_explicit in {"full", "closed"}:
            return AccessNotice("reopened", option.option_id)
        if previous_explicit == "open":
            return None
        return AccessNotice("open", option.option_id)

    if option.status in {"full", "closed"}:
        if previous_status == "open":
            return AccessNotice(option.status, option.option_id)
        if (
            previous_status == "unknown"
            and previous_explicit not in {"full", "closed"}
        ):
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
        option.closes_time.strftime("%H:%M")
        if option.closes_time is not None
        else None,
    )
    old = (previous.get("closes_on"), previous.get("closes_time"))
    if old == current:
        return None
    if old[0] is None:
        return AccessNotice("deadline-known", option.option_id)
    return AccessNotice("deadline-changed", option.option_id)


def _action_notice(
    option: AccessOption,
    previous: Optional[Mapping[str, Any]],
    audience_known: bool,
) -> Optional[AccessNotice]:
    if (
        not audience_known
        or previous is None
        or option.status != "open"
    ):
        return None
    current = (
        _clean_optional_text(option.action_url),
        _clean_optional_text(option.action_text),
    )
    old = (
        _clean_optional_text(previous.get("action_url")),
        _clean_optional_text(previous.get("action_text")),
    )
    if old == (None, None) or old == current:
        return None
    return AccessNotice("action-changed", option.option_id)


def _closing_notice(
    option: AccessOption,
    now: datetime,
    sent: set[str],
) -> Optional[AccessNotice]:
    if option.status != "open" or option.closes_on is None:
        return None
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    today = local.date()
    tomorrow = today + timedelta(days=1)
    if option.closes_on == tomorrow:
        kind = "closing-tomorrow"
    elif option.closes_on == today:
        if (
            option.closes_time is not None
            and local >= _local_datetime(option.closes_on, option.closes_time)
        ):
            return None
        kind = "closing-today"
    else:
        return None
    trigger = _trigger(
        kind,
        option.option_id,
        option.closes_on,
        option.closes_time,
    )
    if trigger in sent:
        return None
    return AccessNotice(kind, option.option_id, trigger)


def _root_notice(
    record: EventAccessRecord,
    now: datetime,
    sent: set[str],
) -> Optional[AccessNotice]:
    for option in record.options:
        if option.status == "open":
            return AccessNotice("active", option.option_id)
    for option in record.options:
        notice = _opening_notice(option, now, sent)
        if notice is not None:
            return notice
    return None


def plan_event_access_record(
    record: EventAccessRecord,
    previous: Optional[Mapping[str, Any]],
    now: datetime,
) -> EventAccessDecision:
    if not valid_event_access_record(record):
        raise ValueError("invalid event-access record")

    candidate = candidate_record_state(record, previous)
    audience_known = bool(
        previous.get("audience_known") if previous is not None else False
    )
    root_message_id = (
        previous.get("root_message_id") if previous is not None else None
    )
    sent_order = list(
        previous.get("sent_triggers", ()) if previous is not None else ()
    )
    sent = set(sent_order)
    previous_options = (
        previous.get("options", {}) if previous is not None else {}
    )

    if not audience_known:
        root_notice = _root_notice(record, now, sent)
        if root_notice is None:
            return EventAccessDecision(candidate, (), None, None)
        if root_notice.trigger_id is not None:
            sent.add(root_notice.trigger_id)
            sent_order.append(root_notice.trigger_id)
        for option in record.options:
            reminder = _closing_notice(option, now, sent)
            if reminder is not None and reminder.trigger_id is not None:
                sent.add(reminder.trigger_id)
                sent_order.append(reminder.trigger_id)
        candidate["audience_known"] = True
        candidate["sent_triggers"] = sent_order
        if not _valid_record_state(candidate):
            raise EventAccessStateError("root candidate state is invalid")
        return EventAccessDecision(candidate, (root_notice,), "root", None)

    notices = []
    for option in record.options:
        old = previous_options.get(option.option_id)
        if old is None:
            opening = _opening_notice(option, now, sent)
            if option.status == "open":
                notices.append(AccessNotice("option-added", option.option_id))
            elif opening is not None:
                notices.append(opening)
                if opening.trigger_id is not None:
                    sent.add(opening.trigger_id)
                    sent_order.append(opening.trigger_id)
            continue

        stronger = _status_notice(option, old, audience_known)
        if stronger is not None:
            notices.append(stronger)

        deadline = _deadline_notice(option, old, audience_known)
        action = _action_notice(option, old, audience_known)
        opening = _opening_notice(option, now, sent)
        closing = _closing_notice(option, now, sent)

        if opening is not None and stronger is None:
            notices.append(opening)
        if deadline is not None and stronger is None:
            notices.append(deadline)
        elif action is not None and stronger is None and deadline is None:
            notices.append(action)
        if (
            closing is not None
            and stronger is None
            and deadline is None
        ):
            notices.append(closing)

        for item in (opening, closing):
            if (
                item is not None
                and item.trigger_id is not None
                and item.trigger_id not in sent
            ):
                sent.add(item.trigger_id)
                sent_order.append(item.trigger_id)

    candidate["sent_triggers"] = sent_order
    if len(sent_order) > MAX_TRIGGERS_PER_RECORD:
        raise EventAccessStateError("event-access trigger bound exceeded")

    if not notices:
        if not _valid_record_state(candidate):
            raise EventAccessStateError("silent candidate state is invalid")
        return EventAccessDecision(candidate, (), None, None)

    operation = "reply" if root_message_id is not None else "root"
    reply_to = root_message_id if operation == "reply" else None
    if not _valid_record_state(candidate):
        raise EventAccessStateError("publication candidate state is invalid")
    return EventAccessDecision(
        candidate,
        tuple(notices),
        operation,
        reply_to,
    )


def prune_records(
    records: Mapping[str, Mapping[str, Any]],
    today: date,
) -> Dict[str, Dict[str, Any]]:
    cutoff = today - timedelta(days=RETENTION_DAYS)
    kept: Dict[str, Dict[str, Any]] = {}
    for record_id, value in records.items():
        try:
            event_day = date.fromisoformat(
                value.get("event_end_date") or value["event_start_date"]
            )
        except (KeyError, TypeError, ValueError):
            continue
        if event_day >= cutoff:
            kept[record_id] = dict(value)
    return kept


_LEGACY_BASELINE_FIELDS = frozenset({
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


def _valid_legacy_baseline_record(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _LEGACY_BASELINE_FIELDS:
        return False
    for field in ("record_id", "source", "source_url", "title"):
        if not isinstance(value.get(field), str) or not value[field]:
            return False
    if value.get("status") not in STATUSES:
        return False
    if value.get("last_explicit_status") not in {*EXPLICIT_STATUSES, None}:
        return False
    if not isinstance(value.get("until_full"), bool):
        return False
    try:
        event_start = date.fromisoformat(value["event_start_date"])
        event_end = _date_or_none(value.get("event_end_date"))
        opens_on = _date_or_none(value.get("registration_start_date"))
        closes_on = _date_or_none(value.get("registration_end_date"))
        opens_time = _time_or_none(value.get("registration_start_time"))
        closes_time = _time_or_none(value.get("registration_end_time"))
    except (TypeError, ValueError):
        return False
    if event_end is not None and event_end < event_start:
        return False
    if opens_time is not None and opens_on is None:
        return False
    if closes_time is not None and closes_on is None:
        return False
    if (
        opens_on is not None
        and closes_on is not None
        and closes_on < opens_on
    ):
        return False
    for field in ("registration_url", "registration_contact"):
        item = value.get(field)
        if item is not None and (
            not isinstance(item, str) or not item.strip()
        ):
            return False
    return True


def _valid_legacy_id_list(value: Any, limit: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= limit
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item for item in value)
    )


def _validate_legacy_v1(value: Any) -> Mapping[str, Any]:
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
    baseline = value.get("baseline")
    if (
        not isinstance(baseline, dict)
        or len(baseline) > MAX_RECORDS
        or any(
            not isinstance(key, str)
            or not key
            or not _valid_legacy_baseline_record(item)
            or item.get("record_id") != key
            for key, item in baseline.items()
        )
    ):
        raise EventAccessStateError("legacy registration baseline is invalid")
    if not _valid_legacy_id_list(value.get("announced_record_ids"), MAX_RECORDS):
        raise EventAccessStateError("legacy announced records are invalid")
    if not _valid_legacy_id_list(
        value.get("sent_triggers"),
        MAX_RECORDS * MAX_TRIGGERS_PER_RECORD,
    ):
        raise EventAccessStateError("legacy registration triggers are invalid")
    if value.get("uncertain") is not None:
        raise EventAccessStateError(
            "legacy uncertain delivery must be resolved before migration"
        )
    unknown_announced = set(value["announced_record_ids"]) - set(baseline)
    if unknown_announced:
        raise EventAccessStateError(
            "legacy announced record has no baseline"
        )
    return value


def _map_legacy_trigger(
    trigger: str,
    record_ids: Sequence[str],
) -> Tuple[str, str]:
    matches = []
    for kind in LEGACY_TRIGGER_KINDS:
        prefix = kind + ":"
        if not trigger.startswith(prefix):
            continue
        for record_id in record_ids:
            marker = prefix + record_id + ":"
            if not trigger.startswith(marker):
                continue
            remainder = trigger[len(marker):]
            try:
                date.fromisoformat(remainder)
            except ValueError:
                continue
            matches.append((
                record_id,
                f"{kind}:default:{remainder}",
            ))
    if len(matches) != 1:
        raise EventAccessStateError(
            "legacy trigger cannot be mapped unambiguously"
        )
    return matches[0]


def migrate_v1_state(value: Any) -> Dict[str, Any]:
    legacy = _validate_legacy_v1(value)
    announced = set(legacy["announced_record_ids"])
    records: Dict[str, Dict[str, Any]] = {}
    for record_id, item in legacy["baseline"].items():
        option = {
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
        records[record_id] = {
            "source": item["source"],
            "access_kind": "registration",
            "event_start_date": item["event_start_date"],
            "event_end_date": item["event_end_date"],
            "options": {"default": option},
            "audience_known": record_id in announced,
            "root_message_id": None,
            "sent_triggers": [],
        }

    for trigger in legacy["sent_triggers"]:
        record_id, mapped = _map_legacy_trigger(
            trigger,
            tuple(records),
        )
        records[record_id]["sent_triggers"].append(mapped)

    result = {
        "version": STATE_VERSION,
        "records": records,
        "uncertain": None,
    }
    return validate_state(result)
