"""Lightweight next-day event announcement from fresh local catalogs."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Optional, Sequence
from zoneinfo import ZoneInfo

from .agenda import AgendaError, fetch_today_events
from .am_guardamar import AmGuardamarError, fetch_today_am_guardamar_events
from .branding import with_footer
from .digest import build_event_section
from .facv import FacvSourceError, fetch_today_facv_events
from .library_agenda import LibraryAgendaError, fetch_today_library_events
from .models import Event
from .morning import _merge_events, _prefer_agenda_guardamar_venues
from .municipal_agenda import MunicipalAgendaError, fetch_today_municipal_events
from .pesca_cv import PescaCvSourceError, fetch_today_pesca_cv_events

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_DUE_WEEKDAYS = frozenset({0, 1, 2, 3, 6})  # Sunday through Thursday.
_IMAGE_HOSTS = frozenset({
    "amguardamar.es",
    "www.amguardamar.es",
    "guardamarturismo.com",
    "www.guardamarturismo.com",
})


class TomorrowEventStateError(RuntimeError):
    """Raised when next-day publication state cannot be trusted."""


class TomorrowEventState:
    """Minimal crash-safe at-most-once state for one target date."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": self.VERSION}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TomorrowEventStateError(
                "tomorrow-event state is unreadable"
            ) from exc
        if not isinstance(value, dict) or value.get("version") != self.VERSION:
            raise TomorrowEventStateError(
                "tomorrow-event state has an invalid structure"
            )
        raw_date = value.get("target_date")
        status = value.get("status")
        if raw_date is None and status is None:
            if set(value) != {"version"}:
                raise TomorrowEventStateError(
                    "tomorrow-event empty state has unexpected fields"
                )
            return value
        if not isinstance(raw_date, str) or status not in {"uncertain", "sent"}:
            raise TomorrowEventStateError(
                "tomorrow-event state has an invalid publication marker"
            )
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise TomorrowEventStateError(
                "tomorrow-event state has an invalid target date"
            ) from exc
        expected_fields = (
            {"version", "target_date", "status", "message_id"}
            if status == "sent"
            else {"version", "target_date", "status"}
        )
        if set(value) != expected_fields:
            raise TomorrowEventStateError(
                "tomorrow-event state has unexpected fields"
            )
        message_id = value.get("message_id")
        if status == "sent":
            if (
                not isinstance(message_id, int)
                or isinstance(message_id, bool)
                or message_id <= 0
            ):
                raise TomorrowEventStateError(
                    "tomorrow-event state has an invalid message ID"
                )
        elif message_id is not None:
            raise TomorrowEventStateError(
                "uncertain tomorrow-event state cannot have a message ID"
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

    def clear(self, target_day: date) -> None:
        value = self._read()
        if value.get("target_date") == target_day.isoformat():
            self._write({"version": self.VERSION})

    def mark_sent(self, target_day: date, message_id: int) -> None:
        if (
            not isinstance(message_id, int)
            or isinstance(message_id, bool)
            or message_id <= 0
        ):
            raise TomorrowEventStateError("invalid tomorrow-event message ID")
        self._write({
            "version": self.VERSION,
            "target_date": target_day.isoformat(),
            "status": "sent",
            "message_id": message_id,
        })

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

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TomorrowEventStateError(
                    "another tomorrow-event run is active"
                ) from exc
            yield


@dataclass(frozen=True)
class TomorrowEventPublication:
    target_date: date
    message: str
    events: tuple[Event, ...]
    unit_count: int
    image_url: Optional[str] = None


def tomorrow_notice_due(now: datetime) -> bool:
    """Avoid Friday/Saturday duplication of the Friday weekend digest."""

    local = now.astimezone(GUARDAMAR_TIMEZONE)
    return local.weekday() in _DUE_WEEKDAYS


def _fresh_snapshot(path: Path, field: str, local_day: date) -> bool:
    """Accept proactive claims only from a snapshot observed today."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        raw = value.get(field)
        if not isinstance(raw, str):
            return False
        observed = datetime.fromisoformat(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, AttributeError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    return observed.astimezone(GUARDAMAR_TIMEZONE).date() == local_day


async def _load_if_fresh(
    *,
    name: str,
    path: Path,
    timestamp_field: str,
    local_day: date,
    load: Callable[[], Awaitable[tuple[Event, ...]]],
    errors: tuple[type[Exception], ...],
) -> tuple[Event, ...]:
    if not _fresh_snapshot(path, timestamp_field, local_day):
        LOGGER.info("Tomorrow events omit stale/missing %s snapshot", name)
        return ()
    try:
        return await load()
    except errors as exc:
        LOGGER.warning("Tomorrow events omit invalid %s snapshot: %s", name, exc)
        return ()


def _eligible_tomorrow_event(event: Event, target_day: date) -> bool:
    """Keep discrete occurrences plus only the first/final day of ranges."""

    if event.active_from is None and event.active_until is None:
        return True
    if event.active_from == target_day:
        return True
    return bool(event.is_final_day)


def _editorial_units(events: Sequence[Event]) -> tuple[tuple[Event, ...], ...]:
    """Collapse one named programme into one resident-facing unit."""

    units: list[tuple[Event, ...]] = []
    seen_programmes: set[str] = set()
    for event in events:
        programme = event.programme_title
        if programme:
            if programme in seen_programmes:
                continue
            seen_programmes.add(programme)
            members = tuple(
                sorted(
                    (
                        candidate
                        for candidate in events
                        if candidate.programme_title == programme
                    ),
                    key=lambda candidate: (
                        candidate.programme_order is None,
                        candidate.programme_order or 0,
                        candidate.starts_at is None,
                        candidate.starts_at
                        or datetime.max.replace(tzinfo=GUARDAMAR_TIMEZONE),
                    ),
                )
            )
            units.append(members)
        else:
            units.append((event,))
    return tuple(units)


def _approved_image_url(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    path = parsed.path.casefold()
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _IMAGE_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not path.startswith("/wp-content/uploads/")
        or not path.endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        return None
    return urllib.parse.urlunsplit(parsed._replace(query="", fragment=""))


def _unit_image_url(unit: Sequence[Event]) -> Optional[str]:
    values = {
        normalized
        for event in unit
        if (normalized := _approved_image_url(event.image_url)) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _render_message(events: Sequence[Event], unit_count: int) -> str:
    render_events = tuple(events)
    if unit_count > 1:
        # A multi-event planning post is scan-first; full prose stays for a
        # standalone event and in the next morning digest.
        render_events = tuple(
            replace(event, teaser=None)
            for event in render_events
        )
    section = build_event_section(
        render_events,
        "📅 <b>Завтра в Гуардамаре</b>",
    )
    if not section:
        raise ValueError("tomorrow event section is empty")
    message = with_footer("\n".join(section[1:]))
    if len(message) > 4096:
        raise ValueError("tomorrow event message exceeds Telegram limit")
    return message


async def produce_tomorrow_event_publication(
    now: datetime,
    *,
    municipal_agenda_state_path: Path,
    agenda_state_path: Path,
    library_agenda_state_path: Path,
    am_guardamar_state_path: Path,
    facv_state_path: Path,
    pesca_cv_state_path: Path,
    translation_cache_path: Path,
) -> Optional[TomorrowEventPublication]:
    """Build tomorrow's proactive announcement with no source network I/O."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    target_day = local_day + timedelta(days=1)
    target = datetime.combine(target_day, time(12, 0), GUARDAMAR_TIMEZONE)

    municipal = await _load_if_fresh(
        name="municipal agenda",
        path=municipal_agenda_state_path,
        timestamp_field="fetched_at",
        local_day=local_day,
        load=lambda: fetch_today_municipal_events(
            target,
            "",
            municipal_agenda_state_path,
            translation_cache_path=translation_cache_path,
        ),
        errors=(MunicipalAgendaError,),
    )
    agenda = await _load_if_fresh(
        name="Agenda Guardamar",
        path=agenda_state_path,
        timestamp_field="fetched_at",
        local_day=local_day,
        load=lambda: fetch_today_events(
            target,
            "",
            agenda_state_path,
            translation_cache_path,
        ),
        errors=(AgendaError,),
    )
    library = await _load_if_fresh(
        name="library agenda",
        path=library_agenda_state_path,
        timestamp_field="fetched_at",
        local_day=local_day,
        load=lambda: fetch_today_library_events(
            target,
            library_agenda_state_path,
            translation_cache_path,
        ),
        errors=(LibraryAgendaError,),
    )
    music = await _load_if_fresh(
        name="AM Guardamar",
        path=am_guardamar_state_path,
        timestamp_field="fetched_at",
        local_day=local_day,
        load=lambda: fetch_today_am_guardamar_events(
            target,
            am_guardamar_state_path,
            translation_cache_path,
        ),
        errors=(AmGuardamarError,),
    )
    chess = await _load_if_fresh(
        name="FACV",
        path=facv_state_path,
        timestamp_field="observed_at",
        local_day=local_day,
        load=lambda: fetch_today_facv_events(
            target,
            facv_state_path,
            translation_cache_path,
        ),
        errors=(FacvSourceError,),
    )
    fishing = await _load_if_fresh(
        name="Pesca CV",
        path=pesca_cv_state_path,
        timestamp_field="observed_at",
        local_day=local_day,
        load=lambda: fetch_today_pesca_cv_events(
            target,
            pesca_cv_state_path,
            translation_cache_path,
        ),
        errors=(PescaCvSourceError,),
    )

    municipal = _prefer_agenda_guardamar_venues(municipal, agenda)
    merged = _merge_events(
        municipal,
        agenda,
        library,
        music,
        chess,
        fishing,
    )
    eligible = tuple(
        event
        for event in merged
        if _eligible_tomorrow_event(event, target_day)
    )
    if not eligible:
        return None

    units = _editorial_units(eligible)
    if not units:
        return None
    image_url = _unit_image_url(units[0]) if len(units) == 1 else None
    return TomorrowEventPublication(
        target_date=target_day,
        message=_render_message(eligible, len(units)),
        events=eligible,
        unit_count=len(units),
        image_url=image_url,
    )
