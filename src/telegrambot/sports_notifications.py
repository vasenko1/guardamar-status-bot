"""Semantic Sporttia change notifications without extra source requests."""

import html
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import FOOTER, with_footer
from .pinned import telegram_message_link
from .sporttia import (
    SPORTTIA_ACTIVITY_KEYS,
    SPORTTIA_CENTER_URL,
    valid_sporttia_snapshot,
)
from .telegram import TelegramError, send_message

STATE_VERSION = 1
TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/sports_notifications.json"
DEADLINE_REMINDER_DAYS = 3
MAX_SENT_DATE_EVENTS = 256

_ACTIVITY_META = {
    "rhythmic_gymnastics": ("🤸", "Художественная гимнастика"),
    "judo": ("🥋", "Дзюдо"),
    "multisport": ("🏃", "Мультиспорт"),
    "inclusive_multisport": ("♿", "Инклюзивный мультиспорт"),
    "senior_gymnastics": ("🧓", "Гимнастика для старшего возраста"),
    "women_gymnastics": ("👩", "Гимнастика Asociación Mujeres"),
    "deporte_plus": ("🏃", "DEPORTE +"),
    "psychomotricity": ("🧒", "Психомоторика"),
}
_CONDITION_FIELDS = (
    "medical_certificate",
    "group_may_change",
    "racket_sports",
    "independent",
    "requires_companion",
    "women_membership",
)
_EVENT_TYPES = frozenset(
    {
        "launch_registration",
        "new_activity",
        "new_season",
        "new_group",
        "registration_open",
        "deadline_reminder",
        "registration_window",
        "schedule",
        "venue",
        "audience",
        "season",
        "conditions",
        "until_full",
    }
)
_MONTHS_RU = (
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


class SportsNotificationError(RuntimeError):
    """Fail-closed sports notification error."""


def _state_path() -> Path:
    return Path(os.environ.get("SPORTS_NOTIFICATION_STATE_PATH", DEFAULT_STATE_PATH))


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "catalog": None,
        "known_keys": [],
        "pending": None,
        "delivery_state": "idle",
        "sent_date_events": [],
        "launch_overview_done": False,
        "last_message_id": None,
    }


def _valid_pending(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    try:
        date.fromisoformat(value.get("created_date", ""))
    except (TypeError, ValueError):
        return False
    if value.get("kind") not in {"launch", "changes"}:
        return False
    events = value.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 128:
        return False
    for event in events:
        if (
            not isinstance(event, dict)
            or event.get("key") not in SPORTTIA_ACTIVITY_KEYS
            or event.get("type") not in _EVENT_TYPES
        ):
            return False
    date_event_ids = value.get("date_event_ids")
    if (
        not isinstance(date_event_ids, list)
        or len(date_event_ids) > 128
        or not all(isinstance(item, str) and item for item in date_event_ids)
    ):
        return False
    return isinstance(value.get("marks_launch"), bool)


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SportsNotificationError(
            "sports notification state is unreadable"
        ) from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise SportsNotificationError("sports notification state is invalid")
    catalog = state.get("catalog")
    if catalog is not None and not valid_sporttia_snapshot(catalog):
        raise SportsNotificationError("sports notification baseline is invalid")
    known_keys = state.get("known_keys")
    sent = state.get("sent_date_events")
    last_message_id = state.get("last_message_id")
    if (
        state.get("delivery_state") not in {"idle", "uncertain"}
        or not isinstance(known_keys, list)
        or len(known_keys) > len(SPORTTIA_ACTIVITY_KEYS)
        or any(key not in SPORTTIA_ACTIVITY_KEYS for key in known_keys)
        or len(set(known_keys)) != len(known_keys)
        or not _valid_pending(state.get("pending"))
        or not isinstance(sent, list)
        or len(sent) > MAX_SENT_DATE_EVENTS
        or not all(isinstance(item, str) and item for item in sent)
        or not isinstance(state.get("launch_overview_done"), bool)
        or (
            last_message_id is not None
            and (
                not isinstance(last_message_id, int)
                or isinstance(last_message_id, bool)
                or last_message_id <= 0
            )
        )
    ):
        raise SportsNotificationError("sports notification state is invalid")
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    if state.get("version") != STATE_VERSION:
        raise SportsNotificationError("sports notification state is invalid")
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


def _snapshot_local_day(catalog: Mapping[str, Any]) -> date:
    try:
        observed = datetime.fromisoformat(str(catalog["observed_at"]))
    except (KeyError, ValueError) as exc:
        raise SportsNotificationError(
            "sports notification catalogue observation is invalid"
        ) from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise SportsNotificationError(
            "sports notification catalogue observation is naive"
        )
    return observed.astimezone(TIMEZONE).date()


def _season(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item["season_start"]), str(item["season_end"])


def _registrations(item: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(entry["start"]), str(entry["end"]))
        for entry in item["registrations"]
    )


def _event(key: str, event_type: str, item: Mapping[str, Any], **extra) -> dict:
    value = {
        "key": key,
        "type": event_type,
        "group_order": int(item["group_order"]),
    }
    value.update(extra)
    return value


def semantic_diff(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    known_keys: Sequence[str],
) -> list[dict]:
    """Return resident-relevant changes only; source-row removal is ignored."""

    if not valid_sporttia_snapshot(previous) or not valid_sporttia_snapshot(current):
        raise SportsNotificationError("sports notification catalogue is invalid")
    old_by_id = {item["source_id"]: item for item in previous["activities"]}
    old_by_key: Dict[str, list[dict]] = {}
    for item in previous["activities"]:
        old_by_key.setdefault(item["key"], []).append(item)

    known = set(known_keys)
    announced_new_keys = set()
    announced_seasons = set()
    events: list[dict] = []

    for item in current["activities"]:
        key = item["key"]
        old = old_by_id.get(item["source_id"])
        if old is None:
            if key not in known:
                if key not in announced_new_keys:
                    events.append(
                        _event(
                            key,
                            "new_activity",
                            item,
                            season_start=item["season_start"],
                            season_end=item["season_end"],
                        )
                    )
                    announced_new_keys.add(key)
                continue
            old_seasons = {_season(value) for value in old_by_key.get(key, [])}
            season = _season(item)
            if season not in old_seasons:
                marker = (key, season)
                if marker not in announced_seasons:
                    events.append(
                        _event(
                            key,
                            "new_season",
                            item,
                            season_start=item["season_start"],
                            season_end=item["season_end"],
                        )
                    )
                    announced_seasons.add(marker)
            else:
                events.append(
                    _event(
                        key,
                        "new_group",
                        item,
                        audience=item.get("audience"),
                        schedule=item["schedule"],
                    )
                )
            continue

        if _registrations(old) != _registrations(item):
            events.append(
                _event(
                    key,
                    "registration_window",
                    item,
                    registrations=list(item["registrations"]),
                )
            )
        if old["schedule"] != item["schedule"]:
            events.append(
                _event(key, "schedule", item, value=item["schedule"])
            )
        if old["venue"] != item["venue"]:
            events.append(_event(key, "venue", item, value=item["venue"]))
        if old.get("audience") != item.get("audience"):
            events.append(
                _event(key, "audience", item, value=item.get("audience"))
            )
        if _season(old) != _season(item):
            events.append(
                _event(
                    key,
                    "season",
                    item,
                    season_start=item["season_start"],
                    season_end=item["season_end"],
                )
            )
        changed_conditions = {
            field: bool(item[field])
            for field in _CONDITION_FIELDS
            if old[field] != item[field]
        }
        if changed_conditions:
            events.append(
                _event(
                    key,
                    "conditions",
                    item,
                    changes=changed_conditions,
                )
            )
        if old["registration_until_full"] != item["registration_until_full"]:
            events.append(
                _event(
                    key,
                    "until_full",
                    item,
                    value=bool(item["registration_until_full"]),
                )
            )
    return events


def _date_event_id(event_type: str, key: str, start: str, end: str) -> str:
    return f"{event_type}:{key}:{start}:{end}"


def date_events(
    catalog: Mapping[str, Any],
    local_day: date,
    sent_ids: Sequence[str],
) -> tuple[list[dict], list[str]]:
    """Return opening and three-day deadline events from a fresh snapshot."""

    if not valid_sporttia_snapshot(catalog):
        raise SportsNotificationError("sports notification catalogue is invalid")
    sent = set(sent_ids)
    events: list[dict] = []
    identifiers: list[str] = []
    seen = set()
    for item in catalog["activities"]:
        key = item["key"]
        for registration in item["registrations"]:
            start = date.fromisoformat(registration["start"])
            end = date.fromisoformat(registration["end"])
            interval = (key, start, end)
            if interval in seen:
                continue
            seen.add(interval)
            if start == local_day:
                identifier = _date_event_id(
                    "open", key, start.isoformat(), end.isoformat()
                )
                if identifier not in sent:
                    events.append(
                        _event(
                            key,
                            "registration_open",
                            item,
                            start=start.isoformat(),
                            end=end.isoformat(),
                        )
                    )
                    identifiers.append(identifier)
                continue
            if end - timedelta(days=DEADLINE_REMINDER_DAYS) == local_day:
                identifier = _date_event_id(
                    "deadline", key, start.isoformat(), end.isoformat()
                )
                if identifier not in sent:
                    events.append(
                        _event(
                            key,
                            "deadline_reminder",
                            item,
                            start=start.isoformat(),
                            end=end.isoformat(),
                        )
                    )
                    identifiers.append(identifier)
    return events, identifiers


def _launch_events(catalog: Mapping[str, Any], local_day: date) -> list[dict]:
    by_key: Dict[str, set[tuple[str, str]]] = {}
    sample: Dict[str, Mapping[str, Any]] = {}
    for item in catalog["activities"]:
        for registration in item["registrations"]:
            start = date.fromisoformat(registration["start"])
            end = date.fromisoformat(registration["end"])
            if start <= local_day <= end:
                by_key.setdefault(item["key"], set()).add(
                    (start.isoformat(), end.isoformat())
                )
                sample.setdefault(item["key"], item)
    events = []
    for key in SPORTTIA_ACTIVITY_KEYS:
        if key not in by_key:
            continue
        events.append(
            _event(
                key,
                "launch_registration",
                sample[key],
                registrations=[
                    {"start": start, "end": end}
                    for start, end in sorted(by_key[key])
                ],
            )
        )
    return events


def collect_changes(
    catalog: Mapping[str, Any],
    state: Dict[str, Any],
    local_day: date,
) -> Dict[str, Any]:
    """Advance baseline and queue at most one current-day sports message."""

    if state.get("delivery_state") == "uncertain":
        raise SportsNotificationError(
            "previous sports notification delivery is uncertain"
        )
    if not valid_sporttia_snapshot(catalog):
        raise SportsNotificationError("sports notification catalogue is invalid")

    updated = dict(state)
    pending = state.get("pending")
    if pending is not None and pending.get("created_date") != local_day.isoformat():
        updated["pending"] = None
        pending = None
    if pending is not None:
        return updated

    previous = state.get("catalog")
    current_keys = {item["key"] for item in catalog["activities"]}
    known_keys = set(state.get("known_keys", []))
    fresh = _snapshot_local_day(catalog) == local_day

    updated["catalog"] = catalog
    updated["known_keys"] = sorted(known_keys | current_keys)

    if previous is None:
        if fresh:
            launch = _launch_events(catalog, local_day)
            if launch:
                updated["pending"] = {
                    "created_date": local_day.isoformat(),
                    "kind": "launch",
                    "events": launch,
                    "date_event_ids": [],
                    "marks_launch": True,
                }
            else:
                updated["launch_overview_done"] = True
        return updated

    if not state.get("launch_overview_done", False):
        if fresh:
            launch = _launch_events(catalog, local_day)
            if launch:
                updated["pending"] = {
                    "created_date": local_day.isoformat(),
                    "kind": "launch",
                    "events": launch,
                    "date_event_ids": [],
                    "marks_launch": True,
                }
            else:
                updated["launch_overview_done"] = True
        return updated

    events = semantic_diff(previous, catalog, state.get("known_keys", []))
    date_event_ids: list[str] = []
    if fresh:
        dated, date_event_ids = date_events(
            catalog,
            local_day,
            state.get("sent_date_events", []),
        )
        events.extend(dated)
    if events:
        updated["pending"] = {
            "created_date": local_day.isoformat(),
            "kind": "changes",
            "events": events,
            "date_event_ids": date_event_ids,
            "marks_launch": False,
        }
    return updated


def _date_label(value: str, include_year: bool = False) -> str:
    parsed = date.fromisoformat(value)
    suffix = f" {parsed.year}" if include_year else ""
    return f"{parsed.day} {_MONTHS_RU[parsed.month - 1]}{suffix}"


def _season_label(start: str, end: str) -> str:
    return f"{_date_label(start, True)} — {_date_label(end, True)}"


def _registration_label(registrations: Sequence[Mapping[str, str]]) -> str:
    ranges = []
    for interval in registrations:
        start = date.fromisoformat(interval["start"])
        end = date.fromisoformat(interval["end"])
        if start.year == end.year and start.month == end.month:
            ranges.append(
                f"{start.day}–{end.day} {_MONTHS_RU[end.month - 1]}"
            )
        else:
            ranges.append(
                f"{_date_label(start.isoformat())} — {_date_label(end.isoformat())}"
            )
    return "; ".join(ranges)


def _activity_link(chat_id: str, messages: Mapping[str, int], key: str) -> str:
    message_id = messages.get(key)
    if isinstance(message_id, int) and message_id > 0:
        return telegram_message_link(chat_id, message_id)
    return SPORTTIA_CENTER_URL


def _group_prefix(key: str, order: int) -> str:
    if key in {"women_gymnastics", "deporte_plus"}:
        return "Группа"
    suffix = {1: "1-я", 2: "2-я", 3: "3-я", 4: "4-я"}.get(
        order, f"{order}-я"
    )
    return f"{suffix} группа"


def _condition_lines(changes: Mapping[str, bool]) -> list[str]:
    labels = {
        "medical_certificate": (
            "Теперь требуется спортивная медсправка.",
            "Требование спортивной медсправки убрано.",
        ),
        "group_may_change": (
            "Организатор указал, что группы или смены могут корректироваться.",
            "Уточнение о возможной корректировке групп или смен убрано.",
        ),
        "racket_sports": (
            "В условиях теперь указаны ракеточные виды спорта.",
            "Уточнение о ракеточных видах спорта убрано.",
        ),
        "independent": (
            "Теперь указано самостоятельное участие.",
            "Условие самостоятельного участия убрано.",
        ),
        "requires_companion": (
            "Теперь требуется сопровождающий взрослый.",
            "Требование сопровождающего взрослого убрано.",
        ),
        "women_membership": (
            "Теперь требуется подтверждение членства Asociación Mujeres.",
            "Требование подтверждения членства Asociación Mujeres убрано.",
        ),
    }
    return [labels[field][0 if value else 1] for field, value in changes.items()]


def _render_event(event: Mapping[str, Any]) -> list[str]:
    event_type = event["type"]
    key = event["key"]
    group = _group_prefix(key, int(event.get("group_order", 1)))
    if event_type == "new_activity":
        return [
            "• Опубликована новая муниципальная секция · сезон "
            f"<b>{html.escape(_season_label(event['season_start'], event['season_end']))}</b>."
        ]
    if event_type == "new_season":
        return [
            "• Опубликован новый сезон: "
            f"<b>{html.escape(_season_label(event['season_start'], event['season_end']))}</b>."
        ]
    if event_type == "new_group":
        details = [value for value in (event.get("audience"), event.get("schedule")) if value]
        suffix = " · ".join(html.escape(str(value)) for value in details)
        return [f"• Добавлена {group.lower()}" + (f" — {suffix}." if suffix else ".")]
    if event_type == "registration_open":
        return [
            "• Открылась запись — до "
            f"<b>{html.escape(_date_label(event['end']))}</b>."
        ]
    if event_type == "deadline_reminder":
        return [
            "• До окончания записи осталось "
            f"{DEADLINE_REMINDER_DAYS} дня — до "
            f"<b>{html.escape(_date_label(event['end']))}</b>."
        ]
    if event_type == "registration_window":
        label = _registration_label(event.get("registrations", []))
        return [
            f"• {group}: изменились сроки записи"
            + (f" — <b>{html.escape(label)}</b>." if label else ".")
        ]
    if event_type == "schedule":
        return [
            f"• {group}: новое расписание — <b>{html.escape(str(event['value']))}</b>."
        ]
    if event_type == "venue":
        return [
            f"• {group}: новое место — <b>{html.escape(str(event['value']))}</b>."
        ]
    if event_type == "audience":
        value = event.get("value")
        if value:
            return [
                f"• {group}: возрастная группа теперь <b>{html.escape(str(value))}</b>."
            ]
        return [f"• {group}: возрастная группа больше не указана."]
    if event_type == "season":
        return [
            f"• {group}: сезон теперь "
            f"<b>{html.escape(_season_label(event['season_start'], event['season_end']))}</b>."
        ]
    if event_type == "conditions":
        return [f"• {group}: {html.escape(line)}" for line in _condition_lines(event["changes"])]
    if event_type == "until_full":
        return [
            f"• {group}: "
            + (
                "запись теперь указана до заполнения мест."
                if event.get("value")
                else "уточнение «до заполнения мест» убрано."
            )
        ]
    raise SportsNotificationError("unknown sports notification event")


def build_message(
    pending: Mapping[str, Any],
    chat_id: str,
    messages: Mapping[str, int],
) -> str:
    """Render one calm, batched sports notification."""

    events = pending.get("events")
    if not isinstance(events, list) or not events:
        raise SportsNotificationError("pending sports notification is empty")
    if pending.get("kind") == "launch":
        blocks = ["🏃 <b>Спорт · сейчас открыта запись</b>"]
        lines = ["Сейчас идёт запись в муниципальные секции:"]
        for event in events:
            if event.get("type") != "launch_registration":
                raise SportsNotificationError("invalid sports launch event")
            key = event["key"]
            emoji, title = _ACTIVITY_META[key]
            link = html.escape(_activity_link(chat_id, messages, key), quote=True)
            registrations = event.get("registrations", [])
            end_dates = sorted({item["end"] for item in registrations})
            if len(end_dates) == 1:
                timing = f"до <b>{html.escape(_date_label(end_dates[0]))}</b>"
            else:
                timing = "срок зависит от группы"
            lines.append(
                f'• {emoji} <a href="{link}"><b>{html.escape(title)}</b></a> — {timing}'
            )
        blocks.append("\n".join(lines))
        blocks.append(
            "Актуальные группы, возраст, расписание и условия — в карточках занятий."
        )
    else:
        blocks = ["🏃 <b>Спорт · изменения</b>"]
        grouped: Dict[str, list[dict]] = {}
        for event in events:
            grouped.setdefault(event["key"], []).append(event)
        for key in SPORTTIA_ACTIVITY_KEYS:
            if key not in grouped:
                continue
            emoji, title = _ACTIVITY_META[key]
            link = html.escape(_activity_link(chat_id, messages, key), quote=True)
            lines = [
                f'{emoji} <a href="{link}"><b>{html.escape(title)}</b></a>'
            ]
            rendered = []
            for event in grouped[key]:
                for line in _render_event(event):
                    if line not in rendered:
                        rendered.append(line)
            lines.extend(rendered)
            blocks.append("\n".join(lines))
        blocks.append(
            "Актуальная информация уже обновлена в карточках занятий."
        )

    message = with_footer("\n\n".join(blocks))
    if len(message) > 4096 or message.count(FOOTER) != 1:
        raise SportsNotificationError(
            "sports notification is not Telegram-safe"
        )
    return message


def _remember_date_events(state: Dict[str, Any], pending: Mapping[str, Any]) -> None:
    sent = list(state.get("sent_date_events", []))
    sent.extend(str(item) for item in pending.get("date_event_ids", []))
    state["sent_date_events"] = list(dict.fromkeys(sent))[-MAX_SENT_DATE_EVENTS:]


async def sync_sports_notifications(
    bot_token: str,
    chat_id: str,
    catalog: Optional[Mapping[str, Any]],
    messages: Mapping[str, int],
    now: datetime,
) -> str:
    """Collect from the accepted snapshot and publish at most one message."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("sports notification time must be timezone-aware")
    local_day = now.astimezone(TIMEZONE).date()
    path = _state_path()
    state = load_state(path)
    if state["delivery_state"] == "uncertain":
        raise SportsNotificationError(
            "sports notification delivery is uncertain; inspect Telegram before retrying"
        )

    pending = state.get("pending")
    if pending is not None and pending.get("created_date") != local_day.isoformat():
        state["pending"] = None
        save_state(path, state)
        pending = None

    if pending is None:
        if catalog is None:
            return "no-catalog"
        if not valid_sporttia_snapshot(catalog):
            raise SportsNotificationError("sports notification catalogue is invalid")
        state = collect_changes(catalog, state, local_day)
        save_state(path, state)
        pending = state.get("pending")
        if pending is None:
            return "baseline"

    message = build_message(pending, chat_id, messages)

    # Telegram sendMessage has no idempotency key. Persist uncertainty first so
    # a crash after acceptance cannot create an automatic duplicate.
    state["delivery_state"] = "uncertain"
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
        if exc.server_status == 429:
            state["delivery_state"] = "idle"
            save_state(path, state)
        raise

    _remember_date_events(state, pending)
    if pending.get("marks_launch"):
        state["launch_overview_done"] = True
    state["pending"] = None
    state["delivery_state"] = "idle"
    state["last_message_id"] = message_id
    save_state(path, state)
    return "published"
