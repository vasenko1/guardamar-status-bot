"""Crash-safe resident notices for exceptional Guardamar supermarket closures."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import html
import json
import logging
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .holidays import official_holidays_on
from .supermarket_hours import (
    SOURCE_FETCHERS,
    STORE_NAMES,
    STORE_ORDER,
    StoreScheduleObservation,
    SupermarketSourceError,
)
from .telegram import TelegramError, is_ambiguous_send_failure, send_message


LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = Path("state/supermarket_closures.json")
STATE_VERSION = 1
MAX_SENT_KEYS = 256
MAX_STORE_CLOSURES = 128
MAX_UNCERTAIN_KEYS = 64
MAX_STATE_BYTES = 64 * 1024
SENT_RETENTION_DAYS = 180
MAX_MESSAGE_LENGTH = 4096

_KEY = re.compile(
    r"^(early|tomorrow|today|correction):(\d{4}-\d{2}-\d{2}):"
    r"(mercadona_guardamar|masymas_guardamar|dia_guardamar)$"
)

_RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_RU_WEEKDAYS = ("понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье")
_STORE_RANK = {key: index for index, key in enumerate(STORE_ORDER)}


class SupermarketStateError(RuntimeError):
    """Persistent supermarket lifecycle state is not trustworthy."""


class SupermarketDeliveryUncertain(RuntimeError):
    """Telegram may already contain the reserved supermarket message."""


@dataclass(frozen=True)
class NoticeGroup:
    kind: str
    target_date: date
    stores: Tuple[str, ...]
    keys: Tuple[str, ...]
    open_context: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedBatch:
    local_day: date
    groups: Tuple[NoticeGroup, ...]
    keys: Tuple[str, ...]
    message: str


def _empty_state() -> Dict[str, object]:
    return {
        "version": STATE_VERSION,
        "stores": {},
        "sent": [],
        "confirmed": [],
        "uncertain_batch": None,
        "last_delivery_day": None,
    }


def _key_parts(value: str) -> Tuple[str, date, str]:
    match = _KEY.fullmatch(value)
    if match is None:
        raise SupermarketStateError("supermarket state contains an invalid delivery key")
    try:
        target = date.fromisoformat(match.group(2))
    except ValueError as exc:
        raise SupermarketStateError("supermarket state contains an invalid delivery date") from exc
    return match.group(1), target, match.group(3)


def _prune_sent(
    values: Iterable[str],
    today: date,
    *,
    required: Iterable[str] = (),
) -> List[str]:
    """Bound delivery history without dropping crash-safety reservations."""

    cutoff = today - timedelta(days=SENT_RETENTION_DAYS)
    required_set = set(required)
    if len(required_set) > MAX_SENT_KEYS:
        raise SupermarketStateError("supermarket required delivery keys exceed the state bound")
    for value in required_set:
        _key_parts(value)

    eligible = {
        value
        for value in values
        if value in required_set or _key_parts(value)[1] >= cutoff
    }
    eligible.update(required_set)

    def sort_key(value: str):
        phase, target, store_key = _key_parts(value)
        return target, phase, store_key

    optional = sorted(eligible - required_set, key=sort_key)
    room = MAX_SENT_KEYS - len(required_set)
    kept = set(optional[-room:] if room else ())
    kept.update(required_set)
    return sorted(kept, key=sort_key)


def _prune_delivery_state(value: Dict[str, object], today: date) -> Dict[str, object]:
    uncertain = value.get("uncertain_batch")
    required = ()
    if isinstance(uncertain, dict) and isinstance(uncertain.get("keys"), list):
        required = tuple(uncertain["keys"])
    sent = _prune_sent(value["sent"], today, required=required)
    sent_set = set(sent)
    confirmed = [
        key
        for key in _prune_sent(value["confirmed"], today)
        if key in sent_set
    ]
    value["sent"] = sent
    value["confirmed"] = confirmed
    return value


def _validate_state(value: object) -> Dict[str, object]:
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        raise SupermarketStateError("supermarket state has an invalid version")
    if set(value) != {"version", "stores", "sent", "confirmed", "uncertain_batch", "last_delivery_day"}:
        raise SupermarketStateError("supermarket state has unexpected fields")
    stores = value.get("stores")
    sent = value.get("sent")
    confirmed = value.get("confirmed")
    if (
        not isinstance(stores, dict)
        or len(stores) > len(STORE_NAMES)
        or not isinstance(sent, list)
        or not isinstance(confirmed, list)
        or len(sent) > MAX_SENT_KEYS
        or len(confirmed) > MAX_SENT_KEYS
    ):
        raise SupermarketStateError("supermarket state structure is invalid")
    if any(not isinstance(item, str) for item in sent + confirmed):
        raise SupermarketStateError("supermarket state delivery keys are invalid")
    if len(set(sent)) != len(sent) or len(set(confirmed)) != len(confirmed):
        raise SupermarketStateError("supermarket state delivery keys are duplicated")
    for item in sent + confirmed:
        _key_parts(item)
    if not set(confirmed).issubset(sent):
        raise SupermarketStateError("supermarket confirmed keys are not accounted")
    for store_key, record in stores.items():
        if store_key not in STORE_NAMES or not isinstance(record, dict):
            raise SupermarketStateError("supermarket store state is invalid")
        if set(record) != {"observed_at", "closures"}:
            raise SupermarketStateError("supermarket store state has unexpected fields")
        if (
            not isinstance(record.get("observed_at"), str)
            or not isinstance(record.get("closures"), list)
            or len(record["closures"]) > MAX_STORE_CLOSURES
        ):
            raise SupermarketStateError("supermarket store state is invalid")
        try:
            observed = datetime.fromisoformat(record["observed_at"])
            if observed.tzinfo is None:
                raise ValueError
            for raw_day in record["closures"]:
                if not isinstance(raw_day, str):
                    raise ValueError
                date.fromisoformat(raw_day)
        except ValueError as exc:
            raise SupermarketStateError("supermarket store state contains an invalid date") from exc
    last_day = value.get("last_delivery_day")
    if last_day is not None:
        if not isinstance(last_day, str):
            raise SupermarketStateError("supermarket last delivery day is invalid")
        try:
            date.fromisoformat(last_day)
        except ValueError as exc:
            raise SupermarketStateError("supermarket last delivery day is invalid") from exc
    uncertain = value.get("uncertain_batch")
    if uncertain is not None:
        if not isinstance(uncertain, dict) or set(uncertain) != {"local_day", "keys"}:
            raise SupermarketStateError("supermarket uncertain batch is invalid")
        if not isinstance(uncertain.get("local_day"), str) or not isinstance(uncertain.get("keys"), list):
            raise SupermarketStateError("supermarket uncertain batch is invalid")
        try:
            date.fromisoformat(uncertain["local_day"])
        except ValueError as exc:
            raise SupermarketStateError("supermarket uncertain batch day is invalid") from exc
        if (
            not uncertain["keys"]
            or len(uncertain["keys"]) > MAX_UNCERTAIN_KEYS
            or len(set(uncertain["keys"])) != len(uncertain["keys"])
            or any(not isinstance(key, str) for key in uncertain["keys"])
        ):
            raise SupermarketStateError("supermarket uncertain batch keys are invalid")
        for key in uncertain["keys"]:
            _key_parts(key)
            if key not in sent:
                raise SupermarketStateError("supermarket uncertain key is not reserved")
    return value


class SupermarketState:
    """One small atomic state file for observations and at-most-once delivery."""

    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        self.path = path

    def read(self) -> Dict[str, object]:
        if not self.path.exists():
            return _empty_state()
        try:
            if self.path.stat().st_size > MAX_STATE_BYTES:
                raise SupermarketStateError("supermarket state is too large")
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupermarketStateError("supermarket state is unreadable") from exc
        return _validate_state(value)

    def write(self, value: Mapping[str, object]) -> None:
        checked = _validate_state(dict(value))
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                dir=str(self.path.parent),
            )
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
        except OSError as exc:
            raise SupermarketStateError("supermarket state could not be saved") from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            lock = lock_path.open("a+")
        except OSError as exc:
            raise SupermarketStateError("supermarket state could not be locked") from exc
        with lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SupermarketStateError("another supermarket run is active") from exc
            except OSError as exc:
                raise SupermarketStateError("supermarket state could not be locked") from exc
            yield


def _previous_closures(state: Mapping[str, object], store_key: str) -> frozenset:
    stores = state.get("stores", {})
    record = stores.get(store_key) if isinstance(stores, dict) else None
    if not isinstance(record, dict):
        return frozenset()
    return frozenset(date.fromisoformat(raw) for raw in record.get("closures", []))


def _week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def _delivery_key(phase: str, target: date, store_key: str) -> str:
    return f"{phase}:{target.isoformat()}:{store_key}"


def _phases_due(today: date, target: date, newly_discovered: bool) -> Tuple[str, ...]:
    phases = []
    distance = (target - today).days
    if distance == 0:
        phases.append("today")
    if distance == 1:
        phases.append("tomorrow")
    if target > today and target <= _week_end(today):
        if today.weekday() == 0:
            phases.append("early")
        elif today.weekday() in range(1, 6) and distance >= 2 and newly_discovered:
            phases.append("early")
    return tuple(dict.fromkeys(phases))



def _ordered_store_keys(values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda key: _STORE_RANK[key]))


def plan_batch(
    state: Mapping[str, object],
    observations: Sequence[StoreScheduleObservation],
    now: datetime,
) -> Optional[PlannedBatch]:
    """Plan all fresh due facts into at most one human-facing daily message."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if state.get("last_delivery_day") == today.isoformat():
        return None
    uncertain = state.get("uncertain_batch")
    if isinstance(uncertain, dict) and uncertain.get("local_day") == today.isoformat():
        return None

    sent = set(state.get("sent", []))
    confirmed = set(state.get("confirmed", []))
    fresh = {observation.store_key: observation for observation in observations}
    closure_items: Dict[date, Dict[str, List[str]]] = {}
    correction_items: Dict[date, Dict[str, List[str]]] = {}

    for observation in observations:
        previous = _previous_closures(state, observation.store_key)
        for target in sorted(observation.closures):
            phases = _phases_due(today, target, target not in previous)
            new_keys = [
                _delivery_key(phase, target, observation.store_key)
                for phase in phases
                if _delivery_key(phase, target, observation.store_key) not in sent
            ]
            if new_keys:
                closure_items.setdefault(target, {})[observation.store_key] = new_keys

        for target in sorted(observation.explicit_open_days):
            if target < today:
                continue
            prior_claim = any(
                _delivery_key(phase, target, observation.store_key) in confirmed
                for phase in ("early", "tomorrow", "today")
            )
            correction = _delivery_key("correction", target, observation.store_key)
            if prior_claim and correction not in sent:
                correction_items.setdefault(target, {})[observation.store_key] = [correction]

    groups = []
    for target, stores in closure_items.items():
        closed = _ordered_store_keys(stores)
        open_context = _ordered_store_keys(
            key
            for key, observation in fresh.items()
            if key not in stores
            and (observation.status_on(target) is not None)
            and observation.status_on(target).is_open
        )
        groups.append(NoticeGroup(
            "closure",
            target,
            closed,
            tuple(key for store in closed for key in stores[store]),
            open_context,
        ))
    for target, stores in correction_items.items():
        corrected = _ordered_store_keys(stores)
        groups.append(NoticeGroup(
            "correction",
            target,
            corrected,
            tuple(key for store in corrected for key in stores[store]),
        ))
    if not groups:
        return None

    kind_rank = {"correction": 0, "closure": 1}
    groups.sort(key=lambda group: (
        (group.target_date - today).days,
        kind_rank[group.kind],
        tuple(_STORE_RANK[key] for key in group.stores),
    ))
    keys = tuple(dict.fromkeys(key for group in groups for key in group.keys))
    message = build_message(tuple(groups), today)
    return PlannedBatch(today, tuple(groups), keys, message)


def _format_date(target: date, today: date) -> str:
    suffix = f"{target.day} {_RU_MONTHS[target.month]}"
    if target == today:
        return f"Сегодня, {suffix}"
    if target == today + timedelta(days=1):
        return f"Завтра, {suffix}"
    return f"В {_RU_WEEKDAYS[target.weekday()]}, {suffix}"


def _join_names(store_keys: Sequence[str]) -> str:
    names = [STORE_NAMES[key] for key in store_keys]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} и {names[1]}"
    return f"{', '.join(names[:-1])} и {names[-1]}"


def _holiday_context(target: date) -> Optional[str]:
    holidays = official_holidays_on(target)
    if not holidays:
        return None
    if len(holidays) != 1:
        return None
    return f"В Гуардамаре это официальный выходной — {html.escape(holidays[0].name)}."


def _render_group(group: NoticeGroup, today: date) -> str:
    lead = _format_date(group.target_date, today)
    names = html.escape(_join_names(group.stores))
    if group.kind == "correction":
        if len(group.stores) == 1:
            body = f"{lead}, <b>{names} работает</b>."
            follow = (
                "Ранее мы писали, что магазин будет закрыт. "
                "Теперь официальный график сети показывает, что он открыт."
            )
        else:
            body = f"{lead}, <b>{names} работают</b>."
            follow = (
                "Ранее мы писали, что эти магазины будут закрыты. "
                "Теперь их официальные графики показывают, что они открыты."
            )
        return f"{body} {follow}"

    if len(group.stores) == 1:
        body = f"{lead}, <b>{names} не работает</b> — магазин закрыт на весь день."
    elif len(group.stores) == 2:
        body = f"{lead}, <b>{names} не работают</b> — оба магазина закрыты на весь день."
    else:
        body = f"{lead}, <b>{names} не работают</b> — все три магазина закрыты на весь день."
    if group.open_context:
        open_names = html.escape(_join_names(group.open_context))
        verb = "работает" if len(group.open_context) == 1 else "работают"
        body += f" При этом <b>{open_names} {verb}</b>."
    holiday = _holiday_context(group.target_date)
    if holiday:
        body += f" {holiday}"
    elif len(group.stores) == 1:
        body += " По обычному графику в этот день магазин работает."
    else:
        body += " По обычному графику в этот день эти магазины работают."
    return body


def build_message(groups: Sequence[NoticeGroup], today: date) -> str:
    if not groups:
        raise ValueError("supermarket message needs at least one group")
    message = with_footer(
        "🛒 <b>График супермаркетов в Гуардамаре</b>\n\n"
        + "\n\n".join(_render_group(group, today) for group in groups)
    )
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError("supermarket message exceeds Telegram limit")
    return message


def _apply_observations(
    state: Mapping[str, object],
    observations: Sequence[StoreScheduleObservation],
    today: date,
) -> Dict[str, object]:
    value = json.loads(json.dumps(state))
    stores = value["stores"]
    for observation in observations:
        stores[observation.store_key] = {
            "observed_at": observation.observed_at.isoformat(),
            "closures": sorted(day.isoformat() for day in observation.closures if day >= today),
        }
    _prune_delivery_state(value, today)
    return _validate_state(value)


async def monitor_supermarkets(
    state: SupermarketState,
    now: datetime,
    observations: Sequence[StoreScheduleObservation],
    send: Callable[[str], Awaitable[int]],
) -> str:
    """Persist fresh observations and publish at most one crash-safe daily batch."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    with state.exclusive_run():
        current = state.read()
        plan = plan_batch(current, observations, now)
        value = _apply_observations(current, observations, today)
        if plan is None:
            state.write(value)
            return "no_notice"

        reserved = set(value["sent"])
        reserved.update(plan.keys)
        value["sent"] = list(reserved)
        value["uncertain_batch"] = {
            "local_day": today.isoformat(),
            "keys": list(plan.keys),
        }
        _prune_delivery_state(value, today)
        state.write(value)
        try:
            await send(plan.message)
        except SupermarketDeliveryUncertain:
            raise
        except Exception:
            state.write(current)
            raise

        delivered = state.read()
        confirmed = set(delivered["confirmed"])
        confirmed.update(plan.keys)
        delivered["confirmed"] = list(confirmed)
        delivered["uncertain_batch"] = None
        delivered["last_delivery_day"] = today.isoformat()
        _prune_delivery_state(delivered, today)
        state.write(delivered)
        return "published"


async def collect_observations(now: datetime) -> Tuple[Tuple[StoreScheduleObservation, ...], Tuple[str, ...]]:
    observations = []
    failures = []
    for fetcher in SOURCE_FETCHERS:
        try:
            observations.append(await fetcher(now))
        except SupermarketSourceError as exc:
            label = fetcher.__name__.replace("fetch_", "")
            failures.append(f"{label}:{exc.diagnostic_code}")
            LOGGER.warning("Supermarket source %s failed: %s", label, exc.diagnostic_code)
        except Exception:
            label = fetcher.__name__.replace("fetch_", "")
            failures.append(f"{label}:UNEXPECTED")
            LOGGER.exception("Unexpected supermarket source %s failure", label)
    return tuple(observations), tuple(failures)


async def run(*, preview: bool = False) -> int:
    now = datetime.now(GUARDAMAR_TIMEZONE)
    observations, failures = await collect_observations(now)
    if not observations:
        LOGGER.warning("No supermarket source produced a fresh observation: %s", ", ".join(failures))
        return 1

    state = SupermarketState(Path(os.environ.get("SUPERMARKET_CLOSURE_STATE_PATH", DEFAULT_STATE_PATH)))
    if preview:
        with state.exclusive_run():
            plan = plan_batch(state.read(), observations, now)
        print(plan.message if plan is not None else "SKIP: no supermarket notice is due")
        return 0

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        raise SupermarketStateError("Telegram configuration is missing")

    async def publish(message: str) -> int:
        try:
            return await send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
                retry_only_rate_limits=True,
            )
        except TelegramError as exc:
            if is_ambiguous_send_failure(exc):
                raise SupermarketDeliveryUncertain() from exc
            raise

    try:
        result = await monitor_supermarkets(state, now, observations, publish)
    except SupermarketDeliveryUncertain:
        LOGGER.warning("Supermarket delivery uncertain; automatic resend disabled")
        return 0
    LOGGER.info("Supermarket closure sync complete: %s", result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Guardamar supermarket closure notices")
    parser.add_argument("--preview", action="store_true", help="render due message without state changes or Telegram delivery")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        code = asyncio.run(run(preview=arguments.preview))
    except (SupermarketSourceError, SupermarketStateError, TelegramError, ValueError) as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        return
    raise SystemExit(code)


if __name__ == "__main__":
    main()
