"""Unified user-facing notifications for courses, classes, and sections."""

import asyncio
import html
import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import FOOTER, with_footer
from .chess_school import valid_chess_school_snapshot
from .dinamizacion import valid_dinamizacion_snapshot
from .guide import DEFAULT_GUIDE_STATE_PATH, GuideState
from .literary_group import valid_literary_group_snapshot
from .music_school import valid_music_school_snapshot
from .pinned import (
    DEFAULT_PINNED_STATE_PATH,
    DINAMIZACION_GROUP_TITLES,
    SPORT_ACTIVITY_META,
    PinnedGuideState,
    telegram_message_link,
)
from .sporttia import valid_sporttia_snapshot
from .state import PublicationState
from .telegram import TelegramError, is_ambiguous_send_failure, send_message

STATE_VERSION = 1
TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/course_notifications.json"
MAX_SENT_DATE_EVENTS = 512
MESSAGE_ORDER = (
    "registration_closing",
    "registration_opening",
    "registration_changes",
    "new_courses",
    "course_changes",
)
EVENT_KINDS = {
    "registration_open": "registration_opening",
    "registration_single_day": "registration_opening",
    "registration_close": "registration_closing",
    "registration_changed": "registration_changes",
    "new_course": "new_courses",
    "new_group": "new_courses",
    "new_season": "new_courses",
    "course_changed": "course_changes",
}
CONDITION_FIELDS = (
    "medical_certificate",
    "group_may_change",
    "racket_sports",
    "independent",
    "requires_companion",
    "women_membership",
)
MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


class CourseNotificationError(RuntimeError):
    """Fail-closed course notification error."""


def _state_path() -> Path:
    return Path(
        os.environ.get("COURSE_NOTIFICATION_STATE_PATH", DEFAULT_STATE_PATH)
    )


def _guide_path() -> Path:
    return Path(os.environ.get("GUIDE_STATE_PATH", DEFAULT_GUIDE_STATE_PATH))


def _pinned_path() -> Path:
    return Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH)
    )


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "baseline": {},
        "known_sources": [],
        "known_course_keys": [],
        "known_record_ids": [],
        "sent_date_events": [],
        "pending": None,
    }


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _valid_registrations(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > 16:
        return False
    for item in value:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            return False
        try:
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item["end"])
        except (KeyError, TypeError, ValueError):
            return False
        if end < start:
            return False
    return True


def _valid_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    required = {
        "record_id",
        "source",
        "course_key",
        "card_key",
        "title",
        "emoji",
        "group",
        "observed_day",
        "fresh",
        "schedule",
        "venue",
        "audience",
        "period",
        "season",
        "registrations",
        "until_full",
        "conditions",
    }
    if set(record) != required:
        return False
    for field in ("record_id", "source", "course_key", "card_key", "title", "emoji"):
        if not isinstance(record.get(field), str) or not record[field]:
            return False
    for field in ("group", "schedule", "venue", "audience", "season"):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            return False
    try:
        date.fromisoformat(record["observed_day"])
    except (TypeError, ValueError):
        return False
    if not isinstance(record.get("fresh"), bool):
        return False
    period = record.get("period")
    if period is not None and (
        not isinstance(period, list)
        or len(period) != 2
        or not all(value is None or isinstance(value, str) for value in period)
    ):
        return False
    if not _valid_registrations(record.get("registrations")):
        return False
    if not isinstance(record.get("until_full"), bool):
        return False
    conditions = record.get("conditions")
    return (
        isinstance(conditions, list)
        and len(conditions) <= 32
        and all(isinstance(value, str) and value for value in conditions)
    )


def _valid_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    for field in ("type", "record_id", "course_key", "card_key", "title", "emoji"):
        if not isinstance(event.get(field), str) or not event[field]:
            return False
    event_type = event["type"]
    if event_type not in EVENT_KINDS:
        return False
    group = event.get("group")
    if group is not None and not isinstance(group, str):
        return False

    if event_type in {
        "registration_open",
        "registration_close",
        "registration_single_day",
    }:
        start_raw = event.get("start")
        end_raw = event.get("end")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            return False
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except ValueError:
            return False
        return (
            end >= start
            and isinstance(event.get("until_full"), bool)
            and isinstance(event.get("date_event_id"), str)
            and bool(event["date_event_id"])
        )

    if event_type == "registration_changed":
        return (
            _valid_registrations(event.get("old_registrations"))
            and _valid_registrations(event.get("new_registrations"))
            and isinstance(event.get("old_until_full"), bool)
            and isinstance(event.get("new_until_full"), bool)
        )

    if event_type == "course_changed":
        fields = event.get("changed_fields")
        allowed = {
            "schedule",
            "venue",
            "audience",
            "period",
            "season",
            "conditions",
        }
        return (
            isinstance(fields, list)
            and bool(fields)
            and len(fields) <= len(allowed)
            and len(set(fields)) == len(fields)
            and all(field in allowed for field in fields)
        )

    return True


def _valid_pending(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    try:
        date.fromisoformat(value.get("created_date", ""))
    except (TypeError, ValueError):
        return False
    baseline = value.get("candidate_baseline")
    if (
        not isinstance(baseline, dict)
        or len(baseline) > 512
        or any(
            not _valid_record(record) or key != record["record_id"]
            for key, record in baseline.items()
        )
    ):
        return False
    for field in (
        "candidate_known_sources",
        "candidate_known_course_keys",
        "candidate_known_record_ids",
    ):
        items = value.get(field)
        if (
            not isinstance(items, list)
            or len(items) > 512
            or len(set(items)) != len(items)
            or not all(isinstance(item, str) and item for item in items)
        ):
            return False
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) > len(MESSAGE_ORDER):
        return False
    seen = set()
    for item in messages:
        if not isinstance(item, dict):
            return False
        if item.get("kind") not in MESSAGE_ORDER or item["kind"] in seen:
            return False
        seen.add(item["kind"])
        if item.get("status") not in {"pending", "uncertain", "sent"}:
            return False
        events = item.get("events")
        if not isinstance(events, list) or not events or len(events) > 256:
            return False
        if not all(
            _valid_event(event) and EVENT_KINDS[event["type"]] == item["kind"]
            for event in events
        ):
            return False
        identifiers = item.get("date_event_ids")
        if (
            not isinstance(identifiers, list)
            or len(identifiers) > 256
            or len(set(identifiers)) != len(identifiers)
            or not all(
                isinstance(identifier, str) and identifier
                for identifier in identifiers
            )
        ):
            return False
        expected_identifiers = [
            event["date_event_id"]
            for event in events
            if event["type"] in {
                "registration_open",
                "registration_close",
                "registration_single_day",
            }
        ]
        if identifiers != expected_identifiers:
            return False

        message_id = item.get("message_id")
        if item["status"] == "sent":
            if (
                not isinstance(message_id, int)
                or isinstance(message_id, bool)
                or message_id <= 0
            ):
                return False
        elif message_id is not None:
            return False
    return True


def _valid_state(state: Any) -> bool:
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return False
    baseline = state.get("baseline")
    if (
        not isinstance(baseline, dict)
        or len(baseline) > 512
        or any(
            not _valid_record(record) or key != record["record_id"]
            for key, record in baseline.items()
        )
    ):
        return False
    for field in ("known_sources", "known_course_keys", "known_record_ids"):
        items = state.get(field)
        if (
            not isinstance(items, list)
            or len(items) > 512
            or len(set(items)) != len(items)
            or not all(isinstance(item, str) and item for item in items)
        ):
            return False
    sent = state.get("sent_date_events")
    if (
        not isinstance(sent, list)
        or len(sent) > MAX_SENT_DATE_EVENTS
        or len(set(sent)) != len(sent)
        or not all(isinstance(item, str) and item for item in sent)
    ):
        return False
    return _valid_pending(state.get("pending"))


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CourseNotificationError(
            "course notification state is unreadable"
        ) from exc
    if not _valid_state(state):
        raise CourseNotificationError("course notification state is invalid")
    return state


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    if not _valid_state(state):
        raise CourseNotificationError("course notification state is invalid")
    _atomic_write(path, state)

def _observed_day(snapshot: Mapping[str, Any]) -> str:
    try:
        observed = datetime.fromisoformat(str(snapshot["observed_at"]))
    except (KeyError, ValueError) as exc:
        raise CourseNotificationError("course source observation is invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise CourseNotificationError("course source observation is naive")
    return observed.astimezone(TIMEZONE).date().isoformat()


def _group_label(key: str, order: int) -> str:
    if key in {"women_gymnastics", "deporte_plus"}:
        return "Группа"
    suffix = {1: "1-я", 2: "2-я", 3: "3-я", 4: "4-я"}.get(order, f"{order}-я")
    return f"{suffix} группа"


def _record(
    *,
    record_id: str,
    source: str,
    course_key: str,
    card_key: str,
    title: str,
    emoji: str,
    observed_day: str,
    fresh: bool = True,
    group: Optional[str] = None,
    schedule: Optional[str] = None,
    venue: Optional[str] = None,
    audience: Optional[str] = None,
    period: Optional[Sequence[Optional[str]]] = None,
    season: Optional[str] = None,
    registrations: Sequence[Mapping[str, str]] = (),
    until_full: bool = False,
    conditions: Sequence[str] = (),
) -> dict:
    value = {
        "record_id": record_id,
        "source": source,
        "course_key": course_key,
        "card_key": card_key,
        "title": title,
        "emoji": emoji,
        "group": group,
        "observed_day": observed_day,
        "fresh": fresh,
        "schedule": schedule,
        "venue": venue,
        "audience": audience,
        "period": list(period) if period is not None else None,
        "season": season,
        "registrations": [
            {"start": str(item["start"]), "end": str(item["end"])}
            for item in registrations
        ],
        "until_full": bool(until_full),
        "conditions": sorted(set(str(value) for value in conditions)),
    }
    if not _valid_record(value):
        raise CourseNotificationError("normalized course record is invalid")
    return value


def project_course_records(
    guide_state: Mapping[str, Any],
) -> tuple[Dict[str, dict], set[str]]:
    """Project heterogeneous accepted source snapshots into one small course model."""

    records: Dict[str, dict] = {}
    present_sources: set[str] = set()

    sporttia = guide_state.get("sporttia_catalog")
    if sporttia is not None:
        if not valid_sporttia_snapshot(sporttia):
            raise CourseNotificationError("accepted Sporttia snapshot is invalid")
        present_sources.add("sporttia")
        observed = _observed_day(sporttia)
        observed_ids_raw = sporttia.get("observed_source_ids")
        observed_ids = (
            set(observed_ids_raw)
            if isinstance(observed_ids_raw, list)
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in observed_ids_raw
            )
            else {item["source_id"] for item in sporttia["activities"]}
        )
        for item in sporttia["activities"]:
            key = item["key"]
            emoji, title = SPORT_ACTIVITY_META[key]
            conditions = [
                field for field in CONDITION_FIELDS if bool(item[field])
            ]
            value = _record(
                record_id=f"sporttia:{item['source_id']}",
                source="sporttia",
                course_key=f"sporttia:{key}",
                card_key=key,
                title=title,
                emoji=emoji,
                group=_group_label(key, int(item["group_order"])),
                observed_day=observed,
                fresh=item["source_id"] in observed_ids,
                schedule=str(item["schedule"]),
                venue=str(item["venue"]),
                audience=item.get("audience"),
                season=f"{item['season_start']}|{item['season_end']}",
                registrations=item["registrations"],
                until_full=bool(item["registration_until_full"]),
                conditions=conditions,
            )
            records[value["record_id"]] = value

    music = guide_state.get("music_school_catalog")
    if music is not None:
        if not valid_music_school_snapshot(music):
            raise CourseNotificationError("accepted music-school snapshot is invalid")
        present_sources.add("music_school")
        observed = _observed_day(music)
        registration = music.get("jardin_registration")
        registrations = [] if registration is None else [{
            "start": registration["start"],
            "end": registration["end"],
        }]
        value = _record(
            record_id="music_school:jardin",
            source="music_school",
            course_key="music_school:jardin",
            card_key="music_basics",
            title="Jardín Musical",
            emoji="🎶",
            observed_day=observed,
            season=str(music["season"]),
            registrations=registrations,
        )
        records[value["record_id"]] = value

        school_registration = music.get("school_registration")
        school_registrations = (
            []
            if school_registration is None
            else [{
                "start": school_registration["start"],
                "end": school_registration["end"],
            }]
        )
        school_value = _record(
            record_id="music_school:school_registration",
            source="music_school",
            course_key="music_school:school_registration",
            card_key="music_school",
            title="Escuela de Música",
            emoji="🎼",
            observed_day=observed,
            season=str(music["season"]),
            registrations=school_registrations,
        )
        records[school_value["record_id"]] = school_value

    chess = guide_state.get("chess_school_snapshot")
    if chess is not None:
        if not valid_chess_school_snapshot(chess):
            raise CourseNotificationError("accepted chess snapshot is invalid")
        present_sources.add("chess")
        value = _record(
            record_id="chess:main",
            source="chess",
            course_key="chess:main",
            card_key="chess",
            title="Шахматы",
            emoji="♟️",
            observed_day=_observed_day(chess),
            schedule=f"Вт/Чт · {chess['start_time']}–{chess['end_time']}",
            audience=f"{chess['level_from']}–{chess['level_to']}",
        )
        records[value["record_id"]] = value

    literary = guide_state.get("literary_group_snapshot")
    if literary is not None:
        if not valid_literary_group_snapshot(literary):
            raise CourseNotificationError("accepted literary-group snapshot is invalid")
        present_sources.add("literary_group")
        value = _record(
            record_id="literary_group:main",
            source="literary_group",
            course_key="literary_group:main",
            card_key="literary_group",
            title="Литературное творчество",
            emoji="✍️",
            observed_day=_observed_day(literary),
            schedule=f"Вт · {literary['start_time']}–{literary['end_time']}",
            venue=str(literary["venue"]),
        )
        records[value["record_id"]] = value

    dinamizacion = guide_state.get("dinamizacion_snapshot")
    if dinamizacion is not None:
        if not valid_dinamizacion_snapshot(dinamizacion):
            raise CourseNotificationError("accepted Dinamización snapshot is invalid")
        present_sources.add("dinamizacion")
        observed = _observed_day(dinamizacion)
        program = _record(
            record_id="dinamizacion:program",
            source="dinamizacion",
            course_key="dinamizacion:program",
            card_key="dinamizacion",
            title="Муниципальные занятия и мастерские",
            emoji="🤝",
            observed_day=observed,
            season=str(dinamizacion["season"]),
            registrations=[{
                "start": dinamizacion["registration_start"],
                "end": dinamizacion["registration_end"],
            }],
            until_full=bool(dinamizacion["registration_until_full"]),
            conditions=(
                ("resident_priority",)
                if dinamizacion.get("resident_priority") is True
                else ()
            ),
        )
        records[program["record_id"]] = program

        for group in dinamizacion["groups"]:
            key = str(group["key"])
            title = DINAMIZACION_GROUP_TITLES.get(key, key)
            value = _record(
                record_id=f"dinamizacion:{key}",
                source="dinamizacion",
                course_key=f"dinamizacion:{key}",
                card_key="dinamizacion",
                title=title,
                emoji="🤝",
                observed_day=observed,
                schedule="; ".join(str(item) for item in group["schedules"]),
                period=[group.get("start_date"), group.get("end_date")],
                season=str(dinamizacion["season"]),
            )
            records[value["record_id"]] = value

    return records, present_sources


def _event(event_type: str, record: Mapping[str, Any], **extra: Any) -> dict:
    value = {
        "type": event_type,
        "record_id": record["record_id"],
        "course_key": record["course_key"],
        "card_key": record["card_key"],
        "title": record["title"],
        "emoji": record["emoji"],
        "group": record.get("group"),
    }
    value.update(extra)
    return value


def _fresh_on(record: Mapping[str, Any], local_day: date) -> bool:
    return (
        record.get("fresh") is True
        and record.get("observed_day") == local_day.isoformat()
    )


def _semantic_events(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    known_sources: set[str],
    known_course_keys: set[str],
    known_record_ids: set[str],
    local_day: date,
) -> list[dict]:
    events: list[dict] = []
    for record in current.values():
        if not _fresh_on(record, local_day):
            continue
        previous = baseline.get(record["record_id"])
        if previous is None:
            if record["source"] not in known_sources:
                continue
            if record["course_key"] not in known_course_keys:
                events.append(_event("new_course", record))
            elif record["record_id"] not in known_record_ids:
                previous_seasons = {
                    item.get("season")
                    for item in baseline.values()
                    if item.get("course_key") == record["course_key"]
                    and item.get("season") is not None
                }
                if (
                    record.get("season") is not None
                    and previous_seasons
                    and record["season"] not in previous_seasons
                ):
                    events.append(_event("new_season", record))
                else:
                    events.append(_event("new_group", record))
            continue

        registration_changed = (
            previous["registrations"] != record["registrations"]
            or previous["until_full"] != record["until_full"]
        )
        if registration_changed:
            events.append(_event(
                "registration_changed",
                record,
                old_registrations=previous["registrations"],
                new_registrations=record["registrations"],
                old_until_full=previous["until_full"],
                new_until_full=record["until_full"],
            ))

        changed_fields = [
            field
            for field in (
                "schedule",
                "venue",
                "audience",
                "period",
                "season",
                "conditions",
            )
            if previous[field] != record[field]
        ]
        if changed_fields:
            events.append(_event(
                "course_changed",
                record,
                changed_fields=changed_fields,
            ))
    return events


def _date_events(
    current: Mapping[str, Mapping[str, Any]],
    local_day: date,
    sent_ids: Sequence[str],
) -> list[dict]:
    sent = set(sent_ids)
    events: list[dict] = []
    for record in current.values():
        if not _fresh_on(record, local_day):
            continue
        for interval in record["registrations"]:
            start = date.fromisoformat(interval["start"])
            end = date.fromisoformat(interval["end"])
            if start == local_day and end == local_day:
                event_type = "registration_single_day"
            elif start == local_day:
                event_type = "registration_open"
            elif end == local_day:
                event_type = "registration_close"
            else:
                continue
            identifier = (
                f"{event_type}:{record['record_id']}:"
                f"{start.isoformat()}:{end.isoformat()}"
            )
            if identifier in sent:
                continue
            events.append(_event(
                event_type,
                record,
                start=start.isoformat(),
                end=end.isoformat(),
                until_full=record["until_full"],
                date_event_id=identifier,
            ))
    return events


def _bucket_events(
    semantic: Sequence[Mapping[str, Any]],
    dated: Sequence[Mapping[str, Any]],
) -> Dict[str, list[dict]]:
    buckets = {kind: [] for kind in MESSAGE_ORDER}
    dated_records = {
        event["record_id"]
        for event in dated
        if event["type"] in {
            "registration_open",
            "registration_close",
            "registration_single_day",
        }
    }
    opening_courses = {
        event["course_key"]
        for event in dated
        if event["type"] in {"registration_open", "registration_single_day"}
    }

    for event in dated:
        if event["type"] == "registration_close":
            buckets["registration_closing"].append(dict(event))
        else:
            buckets["registration_opening"].append(dict(event))

    for event in semantic:
        event_type = event["type"]
        if event_type == "registration_changed":
            if event["record_id"] not in dated_records:
                buckets["registration_changes"].append(dict(event))
        elif event_type in {"new_course", "new_group", "new_season"}:
            if event["course_key"] not in opening_courses:
                buckets["new_courses"].append(dict(event))
        elif event_type == "course_changed":
            buckets["course_changes"].append(dict(event))
    return {kind: values for kind, values in buckets.items() if values}


def _candidate_baseline(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> Dict[str, dict]:
    merged = {key: dict(value) for key, value in baseline.items()}
    for key, value in current.items():
        merged[key] = dict(value)
    return merged


def _event_card_keys(buckets: Mapping[str, Sequence[Mapping[str, Any]]]) -> set[str]:
    return {
        str(event["card_key"])
        for values in buckets.values()
        for event in values
    }


def _validate_card_keys(
    buckets: Mapping[str, Sequence[Mapping[str, Any]]],
    messages: Mapping[str, int],
) -> None:
    missing = [
        key
        for key in sorted(_event_card_keys(buckets))
        if not isinstance(messages.get(key), int) or messages[key] <= 0
    ]
    if missing:
        raise CourseNotificationError(
            "course notification card is unavailable: " + ", ".join(missing)
        )


def _expire_stale_pending(state: Dict[str, Any], local_day: date) -> Dict[str, Any]:
    pending = state.get("pending")
    if pending is None or pending.get("created_date") == local_day.isoformat():
        return state
    if any(item["status"] == "uncertain" for item in pending["messages"]):
        raise CourseNotificationError(
            "previous course notification delivery is uncertain"
        )
    updated = dict(state)
    updated["baseline"] = pending["candidate_baseline"]
    updated["known_sources"] = pending["candidate_known_sources"]
    updated["known_course_keys"] = pending["candidate_known_course_keys"]
    updated["known_record_ids"] = pending["candidate_known_record_ids"]
    sent = list(updated.get("sent_date_events", []))
    for item in pending["messages"]:
        sent.extend(item["date_event_ids"])
    updated["sent_date_events"] = list(dict.fromkeys(sent))[-MAX_SENT_DATE_EVENTS:]
    updated["pending"] = None
    return updated


def collect_changes(
    current: Mapping[str, Mapping[str, Any]],
    present_sources: set[str],
    state: Dict[str, Any],
    local_day: date,
    messages: Mapping[str, int],
) -> Dict[str, Any]:
    """Build one immutable same-day batch from accepted course state."""

    updated = _expire_stale_pending(dict(state), local_day)
    pending = updated.get("pending")
    if pending is not None:
        if any(item["status"] == "uncertain" for item in pending["messages"]):
            raise CourseNotificationError(
                "course notification delivery is uncertain"
            )
        return updated

    baseline = updated["baseline"]
    known_sources = set(updated["known_sources"])
    known_course_keys = set(updated["known_course_keys"])
    known_record_ids = set(updated["known_record_ids"])
    next_baseline = _candidate_baseline(baseline, current)
    next_sources = sorted(known_sources | present_sources)
    next_course_keys = sorted(
        known_course_keys | {record["course_key"] for record in current.values()}
    )
    next_record_ids = sorted(known_record_ids | set(current))

    # The first run after deployment is intentionally baseline-only.
    if not baseline and not known_sources and not known_record_ids:
        updated["baseline"] = next_baseline
        updated["known_sources"] = next_sources
        updated["known_course_keys"] = next_course_keys
        updated["known_record_ids"] = next_record_ids
        return updated

    semantic = _semantic_events(
        baseline,
        current,
        known_sources,
        known_course_keys,
        known_record_ids,
        local_day,
    )
    dated = _date_events(
        current,
        local_day,
        updated.get("sent_date_events", []),
    )
    buckets = _bucket_events(semantic, dated)
    if not buckets:
        updated["baseline"] = next_baseline
        updated["known_sources"] = next_sources
        updated["known_course_keys"] = next_course_keys
        updated["known_record_ids"] = next_record_ids
        return updated

    _validate_card_keys(buckets, messages)
    pending_messages = []
    for kind in MESSAGE_ORDER:
        events = buckets.get(kind)
        if not events:
            continue
        pending_messages.append({
            "kind": kind,
            "status": "pending",
            "events": events,
            "date_event_ids": [
                event["date_event_id"]
                for event in events
                if isinstance(event.get("date_event_id"), str)
            ],
            "message_id": None,
        })
    updated["pending"] = {
        "created_date": local_day.isoformat(),
        "candidate_baseline": next_baseline,
        "candidate_known_sources": next_sources,
        "candidate_known_course_keys": next_course_keys,
        "candidate_known_record_ids": next_record_ids,
        "messages": pending_messages,
    }
    return updated


def _date_label(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {MONTHS_RU[parsed.month]}"


def _range_label(intervals: Sequence[Mapping[str, str]]) -> str:
    if not intervals:
        return "срок записи не указан"
    if len(intervals) != 1:
        return "срок зависит от группы"
    start = date.fromisoformat(intervals[0]["start"])
    end = date.fromisoformat(intervals[0]["end"])
    if start == end:
        return f"только {_date_label(start.isoformat())}"
    return f"{_date_label(start.isoformat())} — {_date_label(end.isoformat())}"


def _card_link(
    chat_id: str,
    messages: Mapping[str, int],
    card_key: str,
) -> str:
    message_id = messages.get(card_key)
    if not isinstance(message_id, int) or message_id <= 0:
        raise CourseNotificationError(
            f"course notification card is unavailable: {card_key}"
        )
    return telegram_message_link(chat_id, message_id)


def _linked_title(
    event: Mapping[str, Any],
    chat_id: str,
    messages: Mapping[str, int],
) -> str:
    link = html.escape(
        _card_link(chat_id, messages, str(event["card_key"])),
        quote=True,
    )
    return (
        f"{html.escape(str(event['emoji']))} "
        f'<a href="{link}"><b>{html.escape(str(event["title"]))}</b></a>'
    )


def _collapse_date_events(
    events: Sequence[Mapping[str, Any]],
) -> list[dict]:
    grouped: Dict[tuple, list[Mapping[str, Any]]] = {}
    for event in events:
        signature = (
            event["course_key"],
            event["card_key"],
            event["title"],
            event["emoji"],
            event["type"],
            event.get("start"),
            event.get("end"),
            bool(event.get("until_full")),
        )
        grouped.setdefault(signature, []).append(event)
    result = []
    for values in grouped.values():
        sample = dict(values[0])
        groups = sorted({
            str(value["group"])
            for value in values
            if isinstance(value.get("group"), str) and value["group"]
        })
        sample["group"] = groups[0] if len(groups) == 1 else None
        result.append(sample)
    result.sort(key=lambda item: (str(item["title"]).casefold(), str(item.get("group") or "")))
    return result


def _registration_change_text(event: Mapping[str, Any]) -> str:
    old = list(event.get("old_registrations", []))
    new = list(event.get("new_registrations", []))
    old_until = bool(event.get("old_until_full"))
    new_until = bool(event.get("new_until_full"))
    if len(old) == 1 and len(new) == 1:
        old_start = date.fromisoformat(old[0]["start"])
        old_end = date.fromisoformat(old[0]["end"])
        new_start = date.fromisoformat(new[0]["start"])
        new_end = date.fromisoformat(new[0]["end"])
        if old_start == new_start and new_end > old_end:
            return f"запись продлили до {_date_label(new_end.isoformat())}"
        if old_start == new_start and new_end < old_end:
            return f"последний день записи перенесли на {_date_label(new_end.isoformat())}"
        if old_end == new_end and new_start != old_start:
            return f"начало записи перенесли на {_date_label(new_start.isoformat())}"
    if old == new and old_until != new_until:
        if new_until:
            return "после основного срока запись может продолжаться при наличии мест"
        return "запись теперь ограничена основным сроком"
    return f"новый срок записи: {_range_label(new)}"


def _join_ru(items: Sequence[str]) -> str:
    values = [value for value in items if value]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + " и " + values[-1]


def _course_change_text(events: Sequence[Mapping[str, Any]]) -> str:
    fields = set()
    groups = set()
    for event in events:
        fields.update(str(value) for value in event.get("changed_fields", []))
        group = event.get("group")
        if isinstance(group, str) and group:
            groups.add(group)
    labels = {
        "schedule": "расписание",
        "venue": "место занятий",
        "audience": "возраст или уровень участников",
        "period": "даты занятий",
        "season": "сезон",
        "conditions": "условия участия",
    }
    changed = [labels[field] for field in labels if field in fields]
    if not changed:
        return "обновилась информация"
    prefix = ""
    if len(groups) == 1:
        prefix = f"у {next(iter(groups)).casefold()} "
    elif len(groups) > 1:
        prefix = "у нескольких групп "
    verb = "изменилось" if len(changed) == 1 else "обновились"
    return f"{prefix}{verb} {_join_ru(changed)}"


def _collapse_new_events(
    events: Sequence[Mapping[str, Any]],
) -> list[dict]:
    """Render one resident-facing row per course, even if several groups appear."""

    grouped: Dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for event in events:
        grouped.setdefault(
            (str(event["course_key"]), str(event["type"])),
            [],
        ).append(event)

    result: list[dict] = []
    for values in grouped.values():
        sample = dict(values[0])
        groups = sorted({
            str(value["group"])
            for value in values
            if isinstance(value.get("group"), str) and value["group"]
        })
        if sample["type"] == "new_group":
            if len(groups) == 1:
                sample["group"] = groups[0]
            elif len(groups) > 1:
                sample["group"] = "несколько новых групп"
            else:
                sample["group"] = None
        else:
            sample["group"] = None
        result.append(sample)

    result.sort(
        key=lambda item: (
            str(item["title"]).casefold(),
            str(item.get("group") or ""),
        )
    )
    return result


def build_message(
    kind: str,
    events: Sequence[Mapping[str, Any]],
    chat_id: str,
    messages: Mapping[str, int],
) -> str:
    """Render one semantic, card-linked user message."""

    if kind not in MESSAGE_ORDER or not events:
        raise CourseNotificationError("course notification message is empty")

    lines: list[str] = []
    if kind == "registration_opening":
        lines.append("📝 <b>Открылась запись на занятия</b>")
        lines.append("")
        rendered = _collapse_date_events(events)
        for event in rendered:
            target = _linked_title(event, chat_id, messages)
            group = f" · {html.escape(str(event['group']))}" if event.get("group") else ""
            if event["type"] == "registration_single_day":
                detail = "запись проходит только сегодня"
            else:
                detail = f"запись до {_date_label(str(event['end']))}"
            lines.append(f"• {target}{group} — {detail}")
        lines.extend([
            "",
            "Нажмите на название занятия — откроется карточка с актуальной информацией и записью.",
        ])
    elif kind == "registration_closing":
        lines.append("⏳ <b>Сегодня заканчивается запись</b>")
        lines.append("")
        for event in _collapse_date_events(events):
            target = _linked_title(event, chat_id, messages)
            group = f" · {html.escape(str(event['group']))}" if event.get("group") else ""
            if event.get("until_full"):
                detail = (
                    "заканчивается основной период записи; после него заявки "
                    "могут продолжать принимать при наличии мест"
                )
            else:
                detail = "сегодня последний день подачи заявки"
            lines.append(f"• {target}{group} — {detail}")
        lines.extend([
            "",
            "Нажмите на название занятия, чтобы открыть его актуальную карточку.",
        ])
    elif kind == "registration_changes":
        lines.append("🗓 <b>Изменились сроки записи</b>")
        lines.append("")
        for event in sorted(events, key=lambda item: str(item["title"]).casefold()):
            target = _linked_title(event, chat_id, messages)
            group = f" · {html.escape(str(event['group']))}" if event.get("group") else ""
            lines.append(
                f"• {target}{group} — "
                f"{html.escape(_registration_change_text(event))}"
            )
        lines.extend([
            "",
            "Актуальные условия и ссылка на запись находятся в карточке занятия.",
        ])
    elif kind == "new_courses":
        lines.append("🎓 <b>Новые занятия</b>")
        lines.append("")
        for event in _collapse_new_events(events):
            target = _linked_title(event, chat_id, messages)
            if event["type"] == "new_season":
                lines.append(f"• {target} — опубликован новый сезон")
            elif event["type"] == "new_group" and event.get("group"):
                group = str(event["group"])
                if group == "несколько новых групп":
                    lines.append(f"• {target} — появились новые группы")
                else:
                    lines.append(
                        f"• {target} — появилась {html.escape(group.casefold())}"
                    )
            else:
                lines.append(f"• {target}")
        lines.extend([
            "",
            "Нажмите на название — откроется карточка с расписанием и условиями.",
        ])
    else:
        lines.append("🔄 <b>Изменения в занятиях и секциях</b>")
        grouped: Dict[str, list[Mapping[str, Any]]] = {}
        for event in events:
            grouped.setdefault(str(event["course_key"]), []).append(event)
        lines.append("")
        for values in sorted(
            grouped.values(),
            key=lambda items: str(items[0]["title"]).casefold(),
        ):
            sample = values[0]
            target = _linked_title(sample, chat_id, messages)
            lines.append(
                f"• {target} — "
                f"{html.escape(_course_change_text(values))}"
            )
        lines.extend([
            "",
            "Нажмите на название занятия, чтобы открыть актуальную карточку.",
        ])

    message = with_footer("\n".join(lines))
    if len(message) > 4096 or message.count(FOOTER) != 1:
        raise CourseNotificationError(
            "course notification message exceeds Telegram limit"
        )
    return message


def _commit_pending(state: Dict[str, Any]) -> Dict[str, Any]:
    pending = state.get("pending")
    if pending is None:
        return state
    if any(item["status"] != "sent" for item in pending["messages"]):
        raise CourseNotificationError("course notification batch is incomplete")
    updated = dict(state)
    updated["baseline"] = pending["candidate_baseline"]
    updated["known_sources"] = pending["candidate_known_sources"]
    updated["known_course_keys"] = pending["candidate_known_course_keys"]
    updated["known_record_ids"] = pending["candidate_known_record_ids"]
    sent = list(updated.get("sent_date_events", []))
    for item in pending["messages"]:
        sent.extend(item["date_event_ids"])
    updated["sent_date_events"] = list(dict.fromkeys(sent))[-MAX_SENT_DATE_EVENTS:]
    updated["pending"] = None
    return updated


async def sync_course_notifications() -> str:
    """Collect accepted course changes and publish each semantic bucket once."""

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        raise CourseNotificationError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )

    now = datetime.now(TIMEZONE)
    local_day = now.date()
    guide = GuideState(_guide_path()).read()
    if guide.get("last_successful_sync_day") != local_day.isoformat():
        logging.info("Course notifications deferred: today's guide sync is not complete")
        return "guide-not-ready"

    records, sources = project_course_records(guide)
    pinned = PinnedGuideState(_pinned_path()).read_payload(chat_id)
    if pinned["uncertain_messages"]:
        raise CourseNotificationError(
            "pinned guide delivery is uncertain"
        )
    messages = pinned["messages"]

    path = _state_path()
    state = load_state(path)
    state = collect_changes(records, sources, state, local_day, messages)
    save_state(path, state)
    pending = state.get("pending")
    if pending is None:
        return "no-changes"

    if any(item["status"] == "uncertain" for item in pending["messages"]):
        raise CourseNotificationError(
            "course notification delivery is uncertain; inspect Telegram before retrying"
        )

    for kind in MESSAGE_ORDER:
        item = next(
            (candidate for candidate in pending["messages"] if candidate["kind"] == kind),
            None,
        )
        if item is None or item["status"] == "sent":
            continue
        message = build_message(kind, item["events"], chat_id, messages)
        item["status"] = "uncertain"
        save_state(path, state)
        try:
            message_id = await send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
                max_attempts=3,
                retry_only_rate_limits=True,
            )
        except TelegramError as exc:
            if not is_ambiguous_send_failure(exc):
                item["status"] = "pending"
                save_state(path, state)
            else:
                logging.exception(
                    "Course notification delivery is uncertain; "
                    "automatic resend disabled"
                )
            raise
        item["status"] = "sent"
        item["message_id"] = message_id
        save_state(path, state)

    completed = _commit_pending(state)
    save_state(path, completed)
    return "published"


async def _main() -> int:
    with PublicationState(_state_path()).exclusive_run():
        result = await sync_course_notifications()
    logging.info("Course notification run: %s", result)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    raise SystemExit(asyncio.run(_main()))
