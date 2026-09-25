"""Collect and publish user-facing transport change notifications."""

import argparse
import asyncio
import html
import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from .airport_schedule import (
    AirportSchedule,
    AirportScheduleError,
    AirportScheduleState,
    fetch_schedule,
)
from .alicante_schedule import (
    AlicanteSchedule,
    AlicanteScheduleState,
)
from .intercity_schedule import (
    IntercitySchedule,
    IntercityScheduleState,
)
from .branding import FOOTER, with_footer
from .pinned import DEFAULT_PINNED_STATE_PATH, PinnedGuideState, telegram_message_link
from .state import PublicationState, StateError
from .telegram import TelegramError, is_ambiguous_send_failure, send_message

STATE_VERSION = 5
TIMEZONE = ZoneInfo("Europe/Madrid")
LINE_NUMBERS = {"line_1": "1", "line_2": "2"}
ROUTE_META = {
    "line_1": ("🚌", "Городской автобус · Линия 1"),
    "line_2": ("🚌", "Городской автобус · Линия 2"),
    "airport": ("✈️", "Аэропорт Alicante-Elche"),
    "alicante": ("🚌", "Гуардамар ↔ Alicante"),
    "elche": ("🚌", "Гуардамар ↔ Elche"),
    "inland": ("🚌", "Гуардамар ↔ Orihuela"),
    "zenia": ("🛍", "Гуардамар - Zenia Boulevard"),
}
MESSAGE_ORDER = ("schedule_changes", "route_changes", "fare_changes")
EVENT_KINDS = {
    "timetable_changed": "schedule_changes",
    "departures_changed": "schedule_changes",
    "period_changed": "schedule_changes",
    "route_changed": "route_changes",
    "fare_changed": "fare_changes",
}
MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class TransportNotificationError(RuntimeError):
    """Fail-closed transport notification error."""


def _pinned_path() -> Path:
    return Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH)
    )


def _state_path() -> Path:
    return Path(
        os.environ.get(
            "TRANSPORT_NOTIFICATION_STATE_PATH",
            str(_pinned_path().with_name("transport_notifications.json")),
        )
    )


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "urban": {},
        "fare": None,
        "airport_next": None,
        "alicante_next": None,
        "elche_next": None,
        "inland_next": None,
        "zenia_next": None,
        "pending": None,
    }


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_urban_state(value: Any) -> bool:
    if not isinstance(value, dict) or any(key not in LINE_NUMBERS for key in value):
        return False
    for item in value.values():
        if not isinstance(item, dict):
            return False
        if not _is_sha256(item.get("pdf_sha256")) or not _is_sha256(
            item.get("image_sha256")
        ):
            return False
        if item.get("period") not in {None, "summer", "regular"}:
            return False
    return True


def _valid_fare_state(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    cents = value.get("cents")
    if not isinstance(cents, int) or isinstance(cents, bool):
        return False
    try:
        date.fromisoformat(value["effective_date"])
    except (KeyError, TypeError, ValueError):
        return False
    return 100 <= cents <= 2_000 and _is_sha256(value.get("pdf_sha256"))


def _valid_airport_state(value: Any) -> bool:
    if value is None:
        return True
    try:
        _decode_airport_snapshot(value)
    except TransportNotificationError:
        return False
    return True


def _valid_alicante_state(value: Any) -> bool:
    if value is None:
        return True
    try:
        _decode_alicante_snapshot(value)
    except TransportNotificationError:
        return False
    return True


def _valid_intercity_state(value: Any) -> bool:
    if value is None:
        return True
    try:
        _decode_intercity_snapshot(value)
    except TransportNotificationError:
        return False
    return True


def _valid_event(event: Any) -> bool:
    if (
        not isinstance(event, dict)
        or event.get("type") not in EVENT_KINDS
        or event.get("route") not in ROUTE_META
    ):
        return False

    event_type = event["type"]
    if event_type == "period_changed":
        if event.get("period") not in {"summer", "regular"}:
            return False
        effective_date = event.get("effective_date")
        if not isinstance(effective_date, str):
            return False
        try:
            date.fromisoformat(effective_date)
        except ValueError:
            return False
    elif event_type == "departures_changed":
        for field in ("added_to", "removed_to", "added_from", "removed_from"):
            values = event.get(field)
            if (
                not isinstance(values, list)
                or len(values) > 64
                or len(set(values)) != len(values)
                or not all(
                    isinstance(value, str)
                    and len(value) == 5
                    and value[2] == ":"
                    and value[:2].isdigit()
                    and value[3:].isdigit()
                    and 0 <= int(value[:2]) <= 23
                    and 0 <= int(value[3:]) <= 59
                    for value in values
                )
            ):
                return False
    elif event_type == "fare_changed":
        old_cents = event.get("old_cents")
        new_cents = event.get("new_cents")
        if (
            not isinstance(old_cents, int)
            or isinstance(old_cents, bool)
            or not isinstance(new_cents, int)
            or isinstance(new_cents, bool)
            or not 100 <= old_cents <= 2_000
            or not 100 <= new_cents <= 2_000
        ):
            return False
        effective_date = event.get("effective_date")
        if not isinstance(effective_date, str):
            return False
        try:
            date.fromisoformat(effective_date)
        except ValueError:
            return False
        for field in ("old_from", "new_from"):
            if field in event and not isinstance(event[field], bool):
                return False
    elif event_type == "route_changed":
        detail = event.get("detail")
        if detail is not None and (
            not isinstance(detail, str) or not detail.strip() or len(detail) > 512
        ):
            return False
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
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) > len(MESSAGE_ORDER):
        return False
    seen = set()
    for item in messages:
        if not isinstance(item, dict):
            return False
        kind = item.get("kind")
        if kind not in MESSAGE_ORDER or kind in seen:
            return False
        seen.add(kind)
        if item.get("status") not in {"pending", "uncertain", "sent"}:
            return False
        events = item.get("events")
        if not isinstance(events, list) or not events or len(events) > 64:
            return False
        if not all(
            _valid_event(event) and EVENT_KINDS[event["type"]] == kind
            for event in events
        ):
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


def _bucket_events(events: List[dict]) -> List[dict]:
    buckets: Dict[str, list[dict]] = {kind: [] for kind in MESSAGE_ORDER}
    for event in events:
        if event["type"] in {
            "timetable_changed",
            "departures_changed",
            "period_changed",
        }:
            buckets["schedule_changes"].append(event)
        elif event["type"] == "route_changed":
            buckets["route_changes"].append(event)
        elif event["type"] == "fare_changed":
            buckets["fare_changes"].append(event)
        else:
            raise TransportNotificationError(
                f"unsupported transport event: {event['type']}"
            )
    return [
        {
            "kind": kind,
            "status": "pending",
            "events": buckets[kind],
            "message_id": None,
        }
        for kind in MESSAGE_ORDER
        if buckets[kind]
    ]


def _migrate_v1(state: Mapping[str, Any]) -> Dict[str, Any]:
    if state.get("delivery_state") == "uncertain":
        raise TransportNotificationError(
            "legacy transport notification delivery is uncertain; "
            "inspect Telegram before migration"
        )
    urban = state.get("urban", {})
    if not isinstance(urban, dict):
        raise TransportNotificationError("legacy transport notification state is invalid")
    migrated = _empty_state()
    migrated["urban"] = {}
    for key, value in urban.items():
        if key not in LINE_NUMBERS or not isinstance(value, dict):
            raise TransportNotificationError(
                "legacy transport notification state is invalid"
            )
        migrated["urban"][key] = {
            "pdf_sha256": value.get("pdf_sha256"),
            "image_sha256": value.get("image_sha256"),
            "period": value.get("period"),
        }
    migrated["fare"] = state.get("fare")
    migrated["airport_next"] = state.get("airport_next")

    old_pending = state.get("pending")
    if old_pending is not None:
        if not isinstance(old_pending, dict):
            raise TransportNotificationError(
                "legacy transport pending notification is invalid"
            )
        try:
            created_date = date.fromisoformat(old_pending["created_date"]).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportNotificationError(
                "legacy transport pending notification is invalid"
            ) from exc
        events: List[dict] = []
        for key in old_pending.get("urban_lines", []):
            if key in LINE_NUMBERS:
                events.append({"type": "timetable_changed", "route": key})
        airport = old_pending.get("airport")
        if isinstance(airport, dict):
            events.append({
                "type": "departures_changed",
                "route": "airport",
                **airport,
            })
        fare = old_pending.get("fare")
        if isinstance(fare, dict):
            events.append({
                "type": "fare_changed",
                "route": "airport",
                **fare,
            })
        if events:
            migrated["pending"] = {
                "created_date": created_date,
                "messages": _bucket_events(events),
            }
    return migrated


def _migrate_v2(state: Mapping[str, Any]) -> Dict[str, Any]:
    migrated = dict(state)
    migrated["version"] = STATE_VERSION
    migrated["alicante_next"] = None
    migrated["elche_next"] = None
    migrated["inland_next"] = None
    return migrated


def _migrate_v3(state: Mapping[str, Any]) -> Dict[str, Any]:
    migrated = dict(state)
    migrated["version"] = STATE_VERSION
    migrated["elche_next"] = None
    migrated["inland_next"] = None
    return migrated


def _migrate_v4(state: Mapping[str, Any]) -> Dict[str, Any]:
    migrated = dict(state)
    migrated["version"] = STATE_VERSION
    migrated["zenia_next"] = None
    return migrated


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportNotificationError(
            "transport notification state is unreadable"
        ) from exc
    if not isinstance(state, dict):
        raise TransportNotificationError("transport notification state is invalid")
    if state.get("version") == 1:
        state = _migrate_v1(state)
    elif state.get("version") == 2:
        state = _migrate_v2(state)
    elif state.get("version") == 3:
        state = _migrate_v3(state)
    elif state.get("version") == 4:
        state = _migrate_v4(state)
    if (
        state.get("version") != STATE_VERSION
        or not _valid_urban_state(state.get("urban"))
        or not _valid_fare_state(state.get("fare"))
        or not _valid_airport_state(state.get("airport_next"))
        or not _valid_alicante_state(state.get("alicante_next"))
        or not _valid_intercity_state(state.get("elche_next"))
        or not _valid_intercity_state(state.get("inland_next"))
        or not _valid_intercity_state(state.get("zenia_next"))
        or not _valid_pending(state.get("pending"))
    ):
        raise TransportNotificationError(
            "transport notification state is invalid"
        )
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    if (
        state.get("version") != STATE_VERSION
        or not _valid_urban_state(state.get("urban"))
        or not _valid_fare_state(state.get("fare"))
        or not _valid_airport_state(state.get("airport_next"))
        or not _valid_alicante_state(state.get("alicante_next"))
        or not _valid_intercity_state(state.get("elche_next"))
        or not _valid_intercity_state(state.get("inland_next"))
        or not _valid_intercity_state(state.get("zenia_next"))
        or not _valid_pending(state.get("pending"))
    ):
        raise TransportNotificationError(
            "transport notification state is invalid"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
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


def _airport_snapshot(schedule: AirportSchedule) -> Dict[str, Any]:
    return {
        "service_date": schedule.service_date.isoformat(),
        "to_airport": list(schedule.to_airport),
        "from_airport": list(schedule.from_airport),
    }


def _decode_airport_snapshot(
    raw: Any,
) -> Tuple[date, Tuple[str, ...], Tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        )
    try:
        service_date = date.fromisoformat(raw["service_date"])
        to_airport = tuple(raw["to_airport"])
        from_airport = tuple(raw["from_airport"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        ) from exc
    if (
        not all(isinstance(value, str) for value in to_airport)
        or not all(isinstance(value, str) for value in from_airport)
    ):
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        )
    return service_date, to_airport, from_airport


def _airport_diff(
    baseline: Any,
    current: Optional[AirportSchedule],
    today: date,
) -> Optional[Dict[str, Any]]:
    if baseline is None or current is None or current.service_date != today:
        return None
    baseline_date, old_to, old_from = _decode_airport_snapshot(baseline)
    if baseline_date != today:
        return None
    added_to = [value for value in current.to_airport if value not in old_to]
    removed_to = [value for value in old_to if value not in current.to_airport]
    added_from = [
        value for value in current.from_airport if value not in old_from
    ]
    removed_from = [
        value for value in old_from if value not in current.from_airport
    ]
    if not any((added_to, removed_to, added_from, removed_from)):
        return None
    return {
        "added_to": added_to,
        "removed_to": removed_to,
        "added_from": added_from,
        "removed_from": removed_from,
    }


def _alicante_snapshot(schedule: AlicanteSchedule) -> Dict[str, Any]:
    return {
        "service_date": schedule.service_date.isoformat(),
        "to_alicante": list(schedule.to_alicante),
        "from_alicante": list(schedule.from_alicante),
        "fare": (
            None
            if schedule.fare is None
            else {
                "cents": schedule.fare.cents,
                "from_price": schedule.fare.from_price,
            }
        ),
    }


def _decode_alicante_snapshot(
    raw: Any,
) -> Tuple[date, Tuple[str, ...], Tuple[str, ...], Optional[Tuple[int, bool]]]:
    if not isinstance(raw, dict):
        raise TransportNotificationError(
            "Alicante notification baseline is invalid"
        )
    try:
        service_date = date.fromisoformat(raw["service_date"])
        to_alicante = tuple(raw["to_alicante"])
        from_alicante = tuple(raw["from_alicante"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportNotificationError(
            "Alicante notification baseline is invalid"
        ) from exc
    for values in (to_alicante, from_alicante):
        if (
            not 1 <= len(values) <= 64
            or len(set(values)) != len(values)
            or tuple(sorted(values)) != values
            or not all(
                isinstance(value, str)
                and len(value) == 5
                and value[2] == ":"
                and value[:2].isdigit()
                and value[3:].isdigit()
                and 0 <= int(value[:2]) <= 23
                and 0 <= int(value[3:]) <= 59
                for value in values
            )
        ):
            raise TransportNotificationError(
                "Alicante notification baseline is invalid"
            )
    fare = raw.get("fare")
    decoded_fare = None
    if fare is not None:
        if (
            not isinstance(fare, dict)
            or not isinstance(fare.get("cents"), int)
            or isinstance(fare.get("cents"), bool)
            or not 100 <= fare["cents"] <= 2_000
            or not isinstance(fare.get("from_price"), bool)
        ):
            raise TransportNotificationError(
                "Alicante notification baseline is invalid"
            )
        decoded_fare = (fare["cents"], fare["from_price"])
    return service_date, to_alicante, from_alicante, decoded_fare


def _alicante_diff(
    baseline: Any,
    current: Optional[AlicanteSchedule],
    today: date,
) -> Optional[Dict[str, Any]]:
    if baseline is None or current is None or current.service_date != today:
        return None
    baseline_date, old_to, old_from, _ = _decode_alicante_snapshot(baseline)
    if baseline_date != today:
        return None
    added_to = [value for value in current.to_alicante if value not in old_to]
    removed_to = [value for value in old_to if value not in current.to_alicante]
    added_from = [
        value for value in current.from_alicante if value not in old_from
    ]
    removed_from = [
        value for value in old_from if value not in current.from_alicante
    ]
    if not any((added_to, removed_to, added_from, removed_from)):
        return None
    return {
        "added_to": added_to,
        "removed_to": removed_to,
        "added_from": added_from,
        "removed_from": removed_from,
    }


def _intercity_snapshot(
    schedule: IntercitySchedule,
) -> Dict[str, Any]:
    return {
        "service_date": schedule.service_date.isoformat(),
        "outbound": list(schedule.outbound),
        "inbound": list(schedule.inbound),
        "fare": (
            None
            if schedule.fare is None
            else {
                "cents": schedule.fare.cents,
                "from_price": schedule.fare.from_price,
                "effective_date": (
                    None
                    if schedule.fare.effective_date is None
                    else schedule.fare.effective_date.isoformat()
                ),
            }
        ),
    }


def _decode_intercity_snapshot(
    raw: Any,
) -> Tuple[
    date,
    Tuple[str, ...],
    Tuple[str, ...],
    Optional[Tuple[int, bool, Optional[date]]],
]:
    if not isinstance(raw, dict):
        raise TransportNotificationError(
            "intercity notification baseline is invalid"
        )
    try:
        service_date = date.fromisoformat(raw["service_date"])
        outbound = tuple(raw["outbound"])
        inbound = tuple(raw["inbound"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportNotificationError(
            "intercity notification baseline is invalid"
        ) from exc

    for values in (outbound, inbound):
        if (
            not 1 <= len(values) <= 64
            or len(set(values)) != len(values)
            or tuple(sorted(values)) != values
            or not all(
                isinstance(value, str)
                and len(value) == 5
                and value[2] == ":"
                and value[:2].isdigit()
                and value[3:].isdigit()
                and 0 <= int(value[:2]) <= 23
                and 0 <= int(value[3:]) <= 59
                for value in values
            )
        ):
            raise TransportNotificationError(
                "intercity notification baseline is invalid"
            )

    fare = raw.get("fare")
    decoded_fare = None
    if fare is not None:
        if (
            not isinstance(fare, dict)
            or not isinstance(fare.get("cents"), int)
            or isinstance(fare.get("cents"), bool)
            or not 100 <= fare["cents"] <= 2_000
            or not isinstance(fare.get("from_price"), bool)
        ):
            raise TransportNotificationError(
                "intercity notification baseline is invalid"
            )
        effective_raw = fare.get("effective_date")
        try:
            effective = (
                None
                if effective_raw is None
                else date.fromisoformat(effective_raw)
            )
        except (TypeError, ValueError) as exc:
            raise TransportNotificationError(
                "intercity notification baseline is invalid"
            ) from exc
        decoded_fare = (
            fare["cents"],
            fare["from_price"],
            effective,
        )
    return service_date, outbound, inbound, decoded_fare


def _intercity_diff(
    baseline: Any,
    current: Optional[IntercitySchedule],
    today: date,
) -> Optional[Dict[str, Any]]:
    if baseline is None or current is None or current.service_date != today:
        return None
    baseline_date, old_to, old_from, _ = _decode_intercity_snapshot(
        baseline
    )
    if baseline_date != today:
        return None
    added_to = [value for value in current.outbound if value not in old_to]
    removed_to = [value for value in old_to if value not in current.outbound]
    added_from = [value for value in current.inbound if value not in old_from]
    removed_from = [value for value in old_from if value not in current.inbound]
    if not any((added_to, removed_to, added_from, removed_from)):
        return None
    return {
        "added_to": added_to,
        "removed_to": removed_to,
        "added_from": added_from,
        "removed_from": removed_from,
    }


def _append_intercity_events(
    events: List[dict],
    route: str,
    baseline: Any,
    current: Optional[IntercitySchedule],
    today: date,
) -> None:
    change = _intercity_diff(baseline, current, today)
    if change is not None:
        events.append({
            "type": "departures_changed",
            "route": route,
            **change,
        })

    if (
        baseline is None
        or current is None
        or current.service_date != today
        or current.fare is None
    ):
        return
    baseline_date, _, _, baseline_fare = _decode_intercity_snapshot(
        baseline
    )
    if baseline_date != today or baseline_fare is None:
        return
    current_value = (
        current.fare.cents,
        current.fare.from_price,
    )
    previous_value = (
        baseline_fare[0],
        baseline_fare[1],
    )
    if current_value == previous_value:
        return
    effective = current.fare.effective_date or today
    events.append({
        "type": "fare_changed",
        "route": route,
        "old_cents": baseline_fare[0],
        "new_cents": current.fare.cents,
        "old_from": baseline_fare[1],
        "new_from": current.fare.from_price,
        "effective_date": effective.isoformat(),
    })


def _fare_snapshot(
    schedule: Optional[AirportSchedule],
) -> Optional[Dict[str, Any]]:
    if schedule is None or schedule.fare is None:
        return None
    return {
        "cents": schedule.fare.cents,
        "effective_date": schedule.fare.effective_date.isoformat(),
        "pdf_sha256": schedule.fare.pdf_sha256,
    }


def _urban_period(current: Mapping[str, Any], today: date) -> Optional[str]:
    if current.get("reviewed") is not True:
        return None
    return "summer" if today.month in {7, 8} else "regular"


def _has_uncertain(pending: Optional[Mapping[str, Any]]) -> bool:
    return (
        isinstance(pending, Mapping)
        and any(item.get("status") == "uncertain" for item in pending["messages"])
    )


def collect_changes(
    now: datetime,
    pinned_payload: Dict[str, Any],
    airport_schedule: Optional[AirportSchedule],
    state: Dict[str, Any],
    tomorrow_schedule: Optional[AirportSchedule],
    alicante_schedule: Optional[AlicanteSchedule] = None,
    tomorrow_alicante: Optional[AlicanteSchedule] = None,
    elche_schedule: Optional[IntercitySchedule] = None,
    tomorrow_elche: Optional[IntercitySchedule] = None,
    inland_schedule: Optional[IntercitySchedule] = None,
    tomorrow_inland: Optional[IntercitySchedule] = None,
    zenia_schedule: Optional[IntercitySchedule] = None,
    tomorrow_zenia: Optional[IntercitySchedule] = None,
) -> Dict[str, Any]:
    """Collect only changes supported by accepted source data."""

    today = now.date()
    pending = state.get("pending")
    if _has_uncertain(pending):
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )
    if pending is not None:
        if pending.get("created_date") == today.isoformat():
            return state
        logging.warning(
            "Expired an unpublished transport notification from %s",
            pending.get("created_date"),
        )

    events: List[dict] = []
    urban_state = dict(state.get("urban", {}))
    lines = pinned_payload.get("lines", {})
    if not isinstance(lines, dict):
        raise TransportNotificationError(
            "pinned transport line state is invalid"
        )

    for key in LINE_NUMBERS:
        current = lines.get(key)
        if not isinstance(current, dict):
            continue
        pdf_sha = current.get("pdf_sha256")
        image_sha = current.get("image_sha256")
        if not _is_sha256(pdf_sha) or not _is_sha256(image_sha):
            continue
        previous = urban_state.get(key)
        if (
            isinstance(previous, dict)
            and _is_sha256(previous.get("image_sha256"))
            and previous.get("image_sha256") != image_sha
        ):
            events.append({"type": "timetable_changed", "route": key})

        period = _urban_period(current, today)
        previous_period = (
            previous.get("period") if isinstance(previous, dict) else None
        )
        if (
            previous_period in {"summer", "regular"}
            and period in {"summer", "regular"}
            and previous_period != period
        ):
            effective_date = (
                date(today.year, 7, 1)
                if period == "summer"
                else date(today.year, 9, 1)
            )
            events.append({
                "type": "period_changed",
                "route": key,
                "period": period,
                "effective_date": effective_date.isoformat(),
            })

        urban_state[key] = {
            "pdf_sha256": pdf_sha,
            "image_sha256": image_sha,
            "period": period,
        }

    airport_event = _airport_diff(
        state.get("airport_next"), airport_schedule, today
    )
    if airport_event is not None:
        events.append({
            "type": "departures_changed",
            "route": "airport",
            **airport_event,
        })

    current_fare = _fare_snapshot(airport_schedule)
    previous_fare = state.get("fare")
    if (
        current_fare is not None
        and isinstance(previous_fare, dict)
        and previous_fare.get("cents") != current_fare["cents"]
    ):
        events.append({
            "type": "fare_changed",
            "route": "airport",
            "old_cents": previous_fare["cents"],
            "new_cents": current_fare["cents"],
            "effective_date": current_fare["effective_date"],
        })

    alicante_event = _alicante_diff(
        state.get("alicante_next"), alicante_schedule, today
    )
    if alicante_event is not None:
        events.append({
            "type": "departures_changed",
            "route": "alicante",
            **alicante_event,
        })

    if (
        alicante_schedule is not None
        and alicante_schedule.service_date == today
        and alicante_schedule.fare is not None
        and state.get("alicante_next") is not None
    ):
        baseline_date, _, _, baseline_fare = _decode_alicante_snapshot(
            state["alicante_next"]
        )
        current_fare_value = (
            alicante_schedule.fare.cents,
            alicante_schedule.fare.from_price,
        )
        if (
            baseline_date == today
            and baseline_fare is not None
            and baseline_fare != current_fare_value
        ):
            events.append({
                "type": "fare_changed",
                "route": "alicante",
                "old_cents": baseline_fare[0],
                "new_cents": current_fare_value[0],
                "old_from": baseline_fare[1],
                "new_from": current_fare_value[1],
                "effective_date": today.isoformat(),
            })

    _append_intercity_events(
        events,
        "elche",
        state.get("elche_next"),
        elche_schedule,
        today,
    )
    _append_intercity_events(
        events,
        "inland",
        state.get("inland_next"),
        inland_schedule,
        today,
    )
    _append_intercity_events(
        events,
        "zenia",
        state.get("zenia_next"),
        zenia_schedule,
        today,
    )

    airport_next = None
    if (
        tomorrow_schedule is not None
        and tomorrow_schedule.service_date == today + timedelta(days=1)
    ):
        airport_next = _airport_snapshot(tomorrow_schedule)

    updated = dict(state)
    updated["urban"] = urban_state
    if current_fare is not None:
        updated["fare"] = current_fare
    updated["airport_next"] = airport_next
    updated["alicante_next"] = (
        _alicante_snapshot(tomorrow_alicante)
        if (
            tomorrow_alicante is not None
            and tomorrow_alicante.service_date == today + timedelta(days=1)
        )
        else None
    )
    updated["elche_next"] = (
        _intercity_snapshot(tomorrow_elche)
        if (
            tomorrow_elche is not None
            and tomorrow_elche.service_date == today + timedelta(days=1)
        )
        else None
    )
    updated["inland_next"] = (
        _intercity_snapshot(tomorrow_inland)
        if (
            tomorrow_inland is not None
            and tomorrow_inland.service_date == today + timedelta(days=1)
        )
        else None
    )
    updated["zenia_next"] = (
        _intercity_snapshot(tomorrow_zenia)
        if (
            tomorrow_zenia is not None
            and tomorrow_zenia.service_date == today + timedelta(days=1)
        )
        else None
    )
    updated["pending"] = (
        {
            "created_date": today.isoformat(),
            "messages": _bucket_events(events),
        }
        if events
        else None
    )
    return updated


def _amount(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def _date_label(value: date) -> str:
    return f"{value.day} {MONTHS_RU[value.month - 1]}"


def _times(values: List[str]) -> str:
    rendered = [f"<b>{html.escape(value)}</b>" for value in values]
    if len(rendered) < 2:
        return "".join(rendered)
    if len(rendered) == 2:
        return f"{rendered[0]} и {rendered[1]}"
    return ", ".join(rendered[:-1]) + f" и {rendered[-1]}"


def _departure_lines(route: str, event: Mapping[str, Any]) -> List[str]:
    if route == "airport":
        outbound = "из Гуардамара в аэропорт"
        inbound = "из аэропорта в Гуардамар"
    elif route == "alicante":
        outbound = "из Гуардамара в Alicante"
        inbound = "из Alicante в Гуардамар"
    elif route == "elche":
        outbound = "из Гуардамара в Elche"
        inbound = "из Elche в Гуардамар"
    elif route == "inland":
        outbound = "из Гуардамара в Orihuela"
        inbound = "из Orihuela в Гуардамар"
    elif route == "zenia":
        outbound = "из Гуардамара в Zenia Boulevard"
        inbound = "из Zenia Boulevard в Гуардамар"
    else:
        raise TransportNotificationError(
            f"departure details are unsupported for route: {route}"
        )
    result = []
    added_to = list(event.get("added_to", []))
    removed_to = list(event.get("removed_to", []))
    added_from = list(event.get("added_from", []))
    removed_from = list(event.get("removed_from", []))

    if added_to:
        prefix = "Добавлен рейс" if len(added_to) == 1 else "Добавлены рейсы"
        result.append(
            f"{prefix} {outbound} в {_times(added_to)}."
        )
    if removed_to:
        prefix = "Рейса" if len(removed_to) == 1 else "Рейсов"
        result.append(
            f"{prefix} {outbound} в {_times(removed_to)} больше нет."
        )
    if added_from:
        prefix = "Добавлен рейс" if len(added_from) == 1 else "Добавлены рейсы"
        result.append(
            f"{prefix} {inbound} в {_times(added_from)}."
        )
    if removed_from:
        prefix = "Рейса" if len(removed_from) == 1 else "Рейсов"
        result.append(
            f"{prefix} {inbound} в {_times(removed_from)} больше нет."
        )
    return result


def _route_link(
    chat_id: str,
    messages: Mapping[str, int],
    route: str,
) -> str:
    message_id = messages.get(route)
    if not isinstance(message_id, int) or message_id <= 0:
        raise TransportNotificationError(
            f"transport route card is unavailable: {route}"
        )
    return telegram_message_link(chat_id, message_id)


def _linked_route(
    route: str,
    chat_id: str,
    messages: Mapping[str, int],
) -> str:
    if route not in ROUTE_META:
        raise TransportNotificationError(f"unknown transport route: {route}")
    emoji, title = ROUTE_META[route]
    link = html.escape(_route_link(chat_id, messages, route), quote=True)
    return f'{emoji} <a href="{link}"><b>{html.escape(title)}</b></a>'


def build_message(
    kind: str,
    events: List[Mapping[str, Any]],
    chat_id: str,
    messages: Mapping[str, int],
    today: date,
) -> str:
    """Render one semantic transport message with direct route-card links."""

    if kind not in MESSAGE_ORDER or not events:
        raise TransportNotificationError("transport notification message is empty")

    lines: List[str] = []
    if kind == "schedule_changes":
        lines.extend(["🕒 <b>Обновилось расписание транспорта</b>", ""])
        grouped: Dict[str, list[Mapping[str, Any]]] = {}
        for event in events:
            grouped.setdefault(str(event["route"]), []).append(event)
        for route in ROUTE_META:
            route_events = grouped.get(route)
            if not route_events:
                continue
            target = _linked_route(route, chat_id, messages)
            details: List[str] = []
            for event in route_events:
                if event["type"] == "timetable_changed":
                    details.append("опубликовано новое расписание")
                elif event["type"] == "period_changed":
                    effective = date.fromisoformat(
                        str(event["effective_date"])
                    )
                    prefix = (
                        "с сегодняшнего дня"
                        if effective == today
                        else f"с {_date_label(effective)}"
                    )
                    if event.get("period") == "summer":
                        details.append(
                            f"{prefix} действует летний режим: автобус ходит ежедневно"
                        )
                    else:
                        details.append(
                            f"{prefix} действует обычный режим: "
                            "с понедельника по субботу, по воскресеньям отдельное расписание"
                        )
                elif event["type"] == "departures_changed":
                    details.extend(_departure_lines(route, event))
            if route in {"airport", "alicante", "elche", "inland", "zenia"}:
                lines.append(f"• {target}")
                lines.extend(f"  {detail}" for detail in details)
            else:
                text = "; ".join(detail.rstrip(".") for detail in details) + "."
                lines.append(f"• {target}: {text}")
        lines.extend([
            "",
            "Нажмите на маршрут, чтобы открыть его актуальную карточку.",
        ])
    elif kind == "route_changes":
        lines.extend(["📍 <b>Изменился маршрут транспорта</b>", ""])
        for event in events:
            target = _linked_route(str(event["route"]), chat_id, messages)
            detail = str(event.get("detail") or "изменился маршрут или список остановок")
            lines.append(f"• {target}: {html.escape(detail)}.")
        lines.extend([
            "",
            "Нажмите на маршрут, чтобы открыть актуальную карточку.",
        ])
    else:
        lines.extend(["💶 <b>Изменилась стоимость проезда</b>", ""])
        for event in events:
            route = str(event["route"])
            target = _linked_route(route, chat_id, messages)
            effective = date.fromisoformat(str(event["effective_date"]))
            old = _amount(int(event["old_cents"]))
            new = _amount(int(event["new_cents"]))

            if "old_from" in event or "new_from" in event:
                old_from = event.get("old_from") is True
                new_from = event.get("new_from") is True
                if old == new and old_from != new_from:
                    if new_from:
                        detail = (
                            f"цена теперь зависит от рейса: "
                            f"<b>от {new}</b>"
                        )
                    else:
                        detail = (
                            f"для найденных рейсов теперь единая цена: "
                            f"<b>{new}</b>"
                        )
                else:
                    old_prefix = "от " if old_from else ""
                    new_prefix = "от " if new_from else ""
                    if effective > today:
                        detail = (
                            f"с {_date_label(effective)} билет будет стоить "
                            f"<b>{new_prefix}{new}</b> "
                            f"вместо {old_prefix}{old}"
                        )
                    else:
                        detail = (
                            f"билет теперь стоит <b>{new_prefix}{new}</b> "
                            f"вместо {old_prefix}{old}"
                        )
            elif effective > today:
                detail = (
                    f"с {_date_label(effective)} обычный билет будет стоить "
                    f"<b>{new}</b> вместо {old}"
                )
            else:
                detail = (
                    f"обычный билет теперь стоит <b>{new}</b> вместо {old}"
                )
            lines.append(f"• {target}: {detail}.")
        lines.extend([
            "",
            "Нажмите на маршрут, чтобы открыть актуальную карточку.",
        ])

    message = with_footer("\n".join(lines))
    if len(message) > 4096 or message.count(FOOTER) != 1:
        raise TransportNotificationError(
            "transport notification message exceeds Telegram limit"
        )
    return message


async def collect() -> None:
    state_path = _state_path()
    state = load_state(state_path)
    if _has_uncertain(state.get("pending")):
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TransportNotificationError("TELEGRAM_CHAT_ID is required")

    pinned_path = _pinned_path()
    pinned_payload = PinnedGuideState(pinned_path).read_payload(chat_id)
    airport_state = AirportScheduleState(
        pinned_path.with_name("airport_schedule.json")
    )
    try:
        airport_schedule = airport_state.read()
    except StateError as exc:
        raise TransportNotificationError(
            "accepted airport schedule state is invalid"
        ) from exc

    alicante_state = AlicanteScheduleState(
        pinned_path.with_name("alicante_schedule.json")
    )
    try:
        alicante_bundle = alicante_state.read()
    except StateError as exc:
        raise TransportNotificationError(
            "accepted Alicante schedule state is invalid"
        ) from exc

    elche_state = IntercityScheduleState(
        pinned_path.with_name("elche_schedule.json")
    )
    inland_state = IntercityScheduleState(
        pinned_path.with_name("orihuela_schedule.json")
    )
    zenia_state = IntercityScheduleState(
        pinned_path.with_name("zenia_schedule.json")
    )
    try:
        elche_bundle = elche_state.read()
        inland_bundle = inland_state.read()
        zenia_bundle = zenia_state.read()
    except StateError as exc:
        raise TransportNotificationError(
            "accepted intercity schedule state is invalid"
        ) from exc

    now = datetime.now(TIMEZONE)
    tomorrow_schedule = None
    try:
        tomorrow_schedule = (
            await asyncio.to_thread(
                fetch_schedule, now.date() + timedelta(days=1)
            )
        ).schedule
    except AirportScheduleError as exc:
        logging.warning(
            "Tomorrow airport timetable unavailable; exact airport change "
            "detection will skip the next day rather than guess: %s",
            exc,
        )

    updated = collect_changes(
        now,
        pinned_payload,
        airport_schedule,
        state,
        tomorrow_schedule,
        (
            alicante_bundle.current
            if alicante_bundle is not None
            else None
        ),
        (
            alicante_bundle.next
            if alicante_bundle is not None
            else None
        ),
        (
            elche_bundle.current
            if elche_bundle is not None
            else None
        ),
        (
            elche_bundle.next
            if elche_bundle is not None
            else None
        ),
        (
            inland_bundle.current
            if inland_bundle is not None
            else None
        ),
        (
            inland_bundle.next
            if inland_bundle is not None
            else None
        ),
        (
            zenia_bundle.current
            if zenia_bundle is not None
            else None
        ),
        (
            zenia_bundle.next
            if zenia_bundle is not None
            else None
        ),
    )
    save_state(state_path, updated)
    logging.info(
        "Transport notification collection complete: %s",
        "pending" if updated["pending"] is not None else "no changes",
    )


async def publish() -> None:
    state_path = _state_path()
    state = load_state(state_path)
    pending = state.get("pending")
    if pending is None:
        logging.info("No pending transport notification")
        return
    if _has_uncertain(pending):
        raise TransportNotificationError(
            "transport notification delivery is uncertain; "
            "inspect Telegram before retrying"
        )

    today = datetime.now(TIMEZONE).date()
    if pending.get("created_date") != today.isoformat():
        state["pending"] = None
        save_state(state_path, state)
        logging.warning("Expired stale transport notification without sending")
        return

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise TransportNotificationError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )

    pinned = PinnedGuideState(_pinned_path()).read_payload(chat_id)
    if pinned["uncertain_messages"]:
        raise TransportNotificationError(
            "pinned transport guide delivery is uncertain"
        )
    messages = pinned["messages"]

    for kind in MESSAGE_ORDER:
        item = next(
            (
                candidate
                for candidate in pending["messages"]
                if candidate["kind"] == kind
            ),
            None,
        )
        if item is None or item["status"] == "sent":
            continue
        message = build_message(
            kind,
            item["events"],
            chat_id,
            messages,
            today,
        )
        item["status"] = "uncertain"
        save_state(state_path, state)
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
                save_state(state_path, state)
            else:
                logging.exception(
                    "Transport notification delivery is uncertain; "
                    "automatic resend disabled"
                )
            raise
        item["status"] = "sent"
        item["message_id"] = message_id
        save_state(state_path, state)

    if all(item["status"] == "sent" for item in pending["messages"]):
        state["pending"] = None
        save_state(state_path, state)
    logging.info("Transport notification publication complete")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "publish"))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    with PublicationState(_state_path()).exclusive_run():
        if args.command == "collect":
            await collect()
        else:
            await publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
