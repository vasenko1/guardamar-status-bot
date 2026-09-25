"""Shared state and managed-message lifecycle for exact-date intercity cards."""

import asyncio
import html
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from .pinned import PinnedGuideState, build_leaf_message, telegram_message_link
from .state import StateError
from .telegram import TelegramError

STATE_VERSION = 1
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
WEEKDAYS_RU = (
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
)

SendText = Callable[[str], Awaitable[int]]
EditText = Callable[[int, str], Awaitable[None]]


class IntercityScheduleError(RuntimeError):
    """Bounded source/state error that must fail closed."""


@dataclass(frozen=True)
class IntercityFare:
    cents: int
    from_price: bool = False
    effective_date: Optional[date] = None
    source_url: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    pdf_sha256: Optional[str] = None


@dataclass(frozen=True)
class IntercitySchedule:
    service_date: date
    outbound: tuple[str, ...]
    inbound: tuple[str, ...]
    fare: Optional[IntercityFare] = None


@dataclass(frozen=True)
class IntercityScheduleBundle:
    current: IntercitySchedule
    next: Optional[IntercitySchedule]


FetchBundle = Callable[
    [date, Optional[IntercityScheduleBundle]],
    IntercityScheduleBundle,
]
BuildMessage = Callable[[IntercitySchedule, date, str], str]


def validate_schedule(schedule: IntercitySchedule) -> None:
    for values in (schedule.outbound, schedule.inbound):
        if (
            not 1 <= len(values) <= 64
            or len(set(values)) != len(values)
            or tuple(sorted(values)) != values
            or not all(
                isinstance(value, str) and TIME_PATTERN.fullmatch(value)
                for value in values
            )
        ):
            raise StateError("intercity schedule state is invalid")
    fare = schedule.fare
    if fare is None:
        return
    if (
        not isinstance(fare.cents, int)
        or isinstance(fare.cents, bool)
        or not 100 <= fare.cents <= 2_000
        or not isinstance(fare.from_price, bool)
    ):
        raise StateError("intercity schedule state is invalid")
    for value in (fare.source_url, fare.etag, fare.last_modified):
        if value is not None and (
            not isinstance(value, str) or len(value) > 1_000
        ):
            raise StateError("intercity schedule state is invalid")
    if fare.pdf_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", fare.pdf_sha256
    ):
        raise StateError("intercity schedule state is invalid")


def _encode_fare(fare: Optional[IntercityFare]) -> Optional[dict]:
    if fare is None:
        return None
    return {
        "cents": fare.cents,
        "from_price": fare.from_price,
        "effective_date": (
            None if fare.effective_date is None
            else fare.effective_date.isoformat()
        ),
        "source_url": fare.source_url,
        "etag": fare.etag,
        "last_modified": fare.last_modified,
        "pdf_sha256": fare.pdf_sha256,
    }


def _decode_fare(raw: object) -> Optional[IntercityFare]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise StateError("intercity schedule state is invalid")
    effective_raw = raw.get("effective_date")
    try:
        effective_date = (
            None if effective_raw is None
            else date.fromisoformat(effective_raw)
        )
    except (TypeError, ValueError) as exc:
        raise StateError("intercity schedule state is invalid") from exc
    fare = IntercityFare(
        cents=raw.get("cents"),
        from_price=raw.get("from_price"),
        effective_date=effective_date,
        source_url=raw.get("source_url"),
        etag=raw.get("etag"),
        last_modified=raw.get("last_modified"),
        pdf_sha256=raw.get("pdf_sha256"),
    )
    test = IntercitySchedule(
        service_date=date(2000, 1, 1),
        outbound=("00:00",),
        inbound=("00:00",),
        fare=fare,
    )
    validate_schedule(test)
    return fare


def encode_schedule(schedule: IntercitySchedule) -> dict:
    validate_schedule(schedule)
    return {
        "service_date": schedule.service_date.isoformat(),
        "outbound": list(schedule.outbound),
        "inbound": list(schedule.inbound),
        "fare": _encode_fare(schedule.fare),
    }


def decode_schedule(raw: object) -> IntercitySchedule:
    if not isinstance(raw, dict):
        raise StateError("intercity schedule state is invalid")
    try:
        schedule = IntercitySchedule(
            service_date=date.fromisoformat(raw["service_date"]),
            outbound=tuple(raw["outbound"]),
            inbound=tuple(raw["inbound"]),
            fare=_decode_fare(raw.get("fare")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StateError("intercity schedule state is invalid") from exc
    validate_schedule(schedule)
    return schedule


class IntercityScheduleState:
    """Strict atomic current+next snapshot; no raw HTML/PDF is persisted."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Optional[IntercityScheduleBundle]:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("intercity schedule state is invalid") from exc
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise StateError("intercity schedule state is invalid")
        current = decode_schedule(raw.get("current"))
        next_raw = raw.get("next")
        next_schedule = (
            None if next_raw is None else decode_schedule(next_raw)
        )
        if (
            next_schedule is not None
            and next_schedule.service_date
            != current.service_date + timedelta(days=1)
        ):
            raise StateError("intercity schedule state is invalid")
        return IntercityScheduleBundle(current=current, next=next_schedule)

    def write(self, bundle: IntercityScheduleBundle) -> None:
        if (
            bundle.next is not None
            and bundle.next.service_date
            != bundle.current.service_date + timedelta(days=1)
        ):
            raise StateError("intercity schedule state is invalid")
        payload = {
            "version": STATE_VERSION,
            "current": encode_schedule(bundle.current),
            "next": (
                None if bundle.next is None else encode_schedule(bundle.next)
            ),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
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


def date_label(service_date: date, today: date) -> str:
    prefix = "Сегодня" if service_date == today else "Расписание на"
    if service_date == today:
        return (
            f"{prefix}, {service_date.day} "
            f"{MONTHS_RU[service_date.month - 1]}, "
            f"{WEEKDAYS_RU[service_date.weekday()]}"
        )
    return (
        f"{prefix} {service_date.day} "
        f"{MONTHS_RU[service_date.month - 1]}, "
        f"{WEEKDAYS_RU[service_date.weekday()]}"
    )


def format_times(values: Sequence[str]) -> str:
    return "\n".join(
        " · ".join(values[index:index + 5])
        for index in range(0, len(values), 5)
    )


def fare_amount(fare: IntercityFare) -> str:
    prefix = "от " if fare.from_price else ""
    return (
        f"{prefix}{fare.cents // 100},"
        f"{fare.cents % 100:02d} €"
    )


async def sync_intercity_schedule(
    now: datetime,
    chat_id: str,
    route_key: str,
    pinned_state: PinnedGuideState,
    schedule_state: IntercityScheduleState,
    fetch_bundle: FetchBundle,
    build_message: BuildMessage,
    send_text: SendText,
    edit_text: EditText,
) -> dict[str, int]:
    """Refresh one managed route card inside the existing transport cycle."""

    payload = await asyncio.to_thread(pinned_state.read_payload, chat_id)
    messages = payload["messages"]
    if "transport" not in messages or route_key not in messages:
        raise IntercityScheduleError(
            f"{route_key} guide message is missing from state"
        )

    cached = None
    try:
        cached = await asyncio.to_thread(schedule_state.read)
    except StateError:
        cached = None

    bundle = cached
    try:
        fresh = await asyncio.to_thread(
            fetch_bundle,
            now.date(),
            cached,
        )
        if fresh.current.service_date != now.date():
            raise IntercityScheduleError(
                f"{route_key} source has no validated current date"
            )
        await asyncio.to_thread(schedule_state.write, fresh)
        bundle = fresh
    except IntercityScheduleError:
        bundle = cached

    transport_link = telegram_message_link(
        chat_id,
        messages["transport"],
    )
    message = (
        build_message(bundle.current, now.date(), transport_link)
        if bundle is not None
        else build_leaf_message(route_key, transport_link)
    )
    message_id = messages[route_key]
    try:
        await edit_text(message_id, message)
        return dict(messages)
    except TelegramError as exc:
        if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
            return dict(messages)
        if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise

    try:
        new_id = await send_text(message)
    except TelegramError as exc:
        if exc.retryable and exc.server_status != 429:
            await asyncio.to_thread(
                pinned_state.mark_uncertain,
                chat_id,
                route_key,
            )
        raise

    messages[route_key] = new_id
    payload["messages"] = messages
    await asyncio.to_thread(
        pinned_state.write_payload,
        chat_id,
        payload,
    )
    return dict(messages)
