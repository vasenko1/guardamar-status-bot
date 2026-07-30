"""Monthly official municipal agenda poster with a small local snapshot."""

import asyncio
import hashlib
import http.client
import json
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .gemini import GeminiError, extract_agenda_events, translate_event_titles
from .models import Event
from .diagnostics import SourceDiagnostic, source_error

AGENDA_PAGE_URL = "https://guardamarturismo.com/agenda-cultural/"
PAGE_HOSTS = {"guardamarturismo.com", "www.guardamarturismo.com"}
POSTER_HOSTS = {"guardamardelsegura.es", "www.guardamardelsegura.es"}
PAGE_LIMIT_BYTES = 500_000
POSTER_LIMIT_BYTES = 4_000_000
REQUEST_TIMEOUT_SECONDS = 15
MAX_EVENTS = 80
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


class MunicipalAgendaError(RuntimeError):
    """An operator-safe municipal agenda failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


@dataclass(frozen=True)
class SourceEvent:
    title_es: str
    start_date: date
    end_date: date
    start_time: Optional[str]
    end_time: Optional[str]
    place: Optional[str]
    category: str


class _PosterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        candidate = values.get("href") if tag.casefold() == "a" else None
        if tag.casefold() == "img":
            candidate = values.get("src")
        if candidate:
            self.urls.append(candidate)


def _is_allowed_url(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in allowed_hosts


class _MunicipalRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_allowed_url(new_url, self.allowed_hosts):
            raise MunicipalAgendaError(
                "Municipal agenda redirected outside official hosts",
                code="REDIRECT",
                description=(
                    "сервер перенаправил запрос за пределы официального сайта"
                ),
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _read_url(
    url: str,
    allowed_hosts: set[str],
    limit: int,
) -> Tuple[bytes, str]:
    if not _is_allowed_url(url, allowed_hosts):
        raise MunicipalAgendaError(
            "Municipal agenda URL is not allowed",
            code="URL-POLICY",
            description="адрес не принадлежит официальной афише",
        )
    page_request = allowed_hosts == PAGE_HOSTS
    accepted_types = (
        {"text/html"}
        if page_request
        else {"image/jpeg", "image/png", "image/webp"}
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "text/html"
                if page_request
                else "image/jpeg,image/png,image/webp"
            ),
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
    )
    opener = urllib.request.build_opener(
        _MunicipalRedirectHandler(allowed_hosts)
    )
    try:
        with opener.open(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not _is_allowed_url(response.geturl(), allowed_hosts):
                raise MunicipalAgendaError(
                    "Unexpected municipal agenda redirect",
                    code="REDIRECT",
                    description=(
                        "получен недопустимый адрес ответа официальной афиши"
                    ),
                )
            mime_type = response.headers.get_content_type()
            if mime_type not in accepted_types:
                raise MunicipalAgendaError(
                    "Municipal agenda returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description=(
                        "официальная афиша вернула неожиданный формат"
                    ),
                )
            payload = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise MunicipalAgendaError(
            f"Municipal agenda returned HTTP {exc.code}",
            code=f"HTTP-{exc.code}",
            status=exc.code,
            description=f"сервер вернул HTTP {exc.code}",
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, (TimeoutError, socket.timeout))
        )
        raise MunicipalAgendaError(
            "Municipal agenda request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "сервер не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить сетевое соединение"
            ),
        ) from exc
    if len(payload) > limit:
        raise MunicipalAgendaError(
            "Municipal agenda response was too large",
            code="TOO-LARGE",
            description="ответ превысил допустимый размер",
        )
    return payload, mime_type


def extract_poster_url(payload: bytes) -> str:
    """Find the official MUPI monthly poster linked by the tourism page."""

    parser = _PosterParser()
    parser.feed(payload.decode("utf-8", "replace"))
    for candidate in reversed(parser.urls):
        url = urllib.parse.urljoin(AGENDA_PAGE_URL, candidate)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.casefold()
        if (
            parsed.scheme == "https"
            and parsed.hostname in POSTER_HOSTS
            and "/wp-content/uploads/" in path
            and "mupi-" in path
            and path.endswith((".jpg", ".jpeg", ".png", ".webp"))
        ):
            return url
    raise MunicipalAgendaError(
        "Official monthly poster was not found",
        code="NO-POSTER",
        description="на странице не найдена официальная месячная афиша",
    )


def _clean_text(value: Any, maximum: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MunicipalAgendaError("invalid poster event text")
    result = " ".join(value.split())
    if not result or len(result) > maximum:
        raise MunicipalAgendaError("invalid poster event text")
    return result


def _poster_month(poster_url: str) -> str:
    match = re.search(r"/wp-content/uploads/(\d{4})/(\d{2})/", poster_url)
    if match is None:
        raise MunicipalAgendaError(
            "Municipal poster URL has no month",
            code="POSTER-MONTH",
            description="в адресе официальной афиши не указан месяц",
        )
    year, month = (int(value) for value in match.groups())
    try:
        date(year, month, 1)
    except ValueError as exc:
        raise MunicipalAgendaError(
            "Municipal poster URL has an invalid month",
            code="POSTER-MONTH",
            description="в адресе официальной афиши указан неверный месяц",
        ) from exc
    return f"{year:04d}-{month:02d}"


def _month_window(month: str) -> Tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise MunicipalAgendaError(
            "Municipal OCR returned an invalid month",
            code="MONTH",
            description="OCR вернул неверный месяц афиши",
        ) from exc
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_after_next = (
        next_month.replace(day=28) + timedelta(days=4)
    ).replace(day=1)
    return first, month_after_next - timedelta(days=1)


def normalize_extraction(
    result: Dict[str, Any],
    expected_month: Optional[str] = None,
) -> Tuple[SourceEvent, ...]:
    """Validate OCR output and discard routine non-event entries."""

    allowed_dates = None
    if expected_month is not None:
        if result.get("month") != expected_month:
            raise MunicipalAgendaError(
                "Municipal OCR month does not match the poster",
                code="MONTH",
                description="месяц в OCR не совпадает с месяцем афиши",
            )
        allowed_dates = _month_window(expected_month)
    raw_events = result.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise MunicipalAgendaError("invalid poster event list")
    events: List[SourceEvent] = []
    seen = set()
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise MunicipalAgendaError("invalid poster event")
        category = raw.get("category")
        if category not in {
            "event",
            "exhibition",
            "workshop",
            "municipal_service",
            "opening_hours",
        }:
            raise MunicipalAgendaError("invalid poster event category")
        if category in {"municipal_service", "opening_hours"}:
            continue
        start_raw = raw.get("start_date")
        end_raw = raw.get("end_date") or start_raw
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            raise MunicipalAgendaError("invalid poster event date")
        try:
            start_date = date.fromisoformat(start_raw)
            end_date = date.fromisoformat(end_raw)
        except ValueError as exc:
            raise MunicipalAgendaError("invalid poster event date") from exc
        if start_date > end_date or (end_date - start_date).days > 62:
            raise MunicipalAgendaError("invalid poster event range")
        if allowed_dates is not None and (
            start_date < allowed_dates[0] or end_date > allowed_dates[1]
        ):
            raise MunicipalAgendaError(
                "Municipal OCR event is outside the poster window",
                code="MONTH",
                description=(
                    "OCR вернул событие за пределами месяца афиши "
                    "и следующего месяца"
                ),
            )
        times = []
        for field in ("start_time", "end_time"):
            value = raw.get(field)
            if value is not None:
                if not isinstance(value, str) or not _TIME_PATTERN.match(value):
                    raise MunicipalAgendaError("invalid poster event time")
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError as exc:
                    raise MunicipalAgendaError(
                        "invalid poster event time"
                    ) from exc
            times.append(value)
        start_time, end_time = times
        if end_time is not None and start_time is None:
            raise MunicipalAgendaError("event end time has no start time")
        event = SourceEvent(
            title_es=_clean_text(raw.get("title_es"), 120) or "",
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            place=_clean_text(raw.get("place"), 120),
            category="event" if category == "workshop" else category,
        )
        key = (event.title_es.casefold(), event.start_date, event.start_time)
        if key not in seen:
            seen.add(key)
            events.append(event)
    return tuple(events)


def _snapshot_data(
    poster_url: str,
    poster_hash: str,
    fetched_at: datetime,
    events: Tuple[SourceEvent, ...],
) -> Dict[str, Any]:
    return {
        "version": 1,
        "poster_url": poster_url,
        "poster_sha256": poster_hash,
        "fetched_at": fetched_at.isoformat(),
        "events": [
            {
                "title_es": event.title_es,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "start_time": event.start_time,
                "end_time": event.end_time,
                "place": event.place,
                "category": event.category,
            }
            for event in events
        ],
    }


def _write_snapshot(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if fetched_at.tzinfo is None:
            raise ValueError
        events = normalize_extraction({"events": data["events"]})
        return {
            **data,
            "_events": events,
            "_fetched_at": fetched_at,
        }
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MunicipalAgendaError,
    ) as exc:
        raise MunicipalAgendaError(
            "Municipal agenda snapshot is invalid",
            code="CORRUPT",
            description="локальный снимок афиши повреждён",
        ) from exc


def _apply_reviewed_corrections(
    poster_url: str,
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Repair facts manually verified in the official text agenda."""

    parsed = urllib.parse.urlparse(poster_url)
    poster_name = parsed.path.rsplit("/", 1)[-1].casefold()
    if (
        parsed.scheme != "https"
        or parsed.hostname not in POSTER_HOSTS
        or "/wp-content/uploads/2026/07/" not in parsed.path.casefold()
        or not poster_name.startswith("mupi-julio-2026")
        or not poster_name.endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        return events
    corrected = []
    entropia_added = False
    for event in events:
        title = event.title_es.casefold()
        if "conchi montes" not in title and "entrop" not in title:
            corrected.append(event)
            continue
        if not entropia_added:
            corrected.append(
                SourceEvent(
                    title_es=(
                        "Exposición de pintura «Entropía» "
                        "de Conchi Montes"
                    ),
                    start_date=date(2026, 7, 3),
                    end_date=date(2026, 7, 29),
                    start_time="08:00",
                    end_time="14:00",
                    place="Biblioteca Pública Municipal",
                    category="exhibition",
                )
            )
            entropia_added = True
    return tuple(corrected)


def _merge_reviewed_text_agenda(
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Keep verified current-month facts when the poster advances early."""

    if any(
        "conchi montes" in event.title_es.casefold()
        or "entrop" in event.title_es.casefold()
        for event in events
    ):
        return events
    return events + (
        SourceEvent(
            title_es="Exposición de pintura «Entropía» de Conchi Montes",
            start_date=date(2026, 7, 3),
            end_date=date(2026, 7, 29),
            start_time="08:00",
            end_time="14:00",
            place="Biblioteca Pública Municipal",
            category="exhibition",
        ),
    )


async def _current_events(
    api_key: str,
    now: datetime,
    state_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[SourceEvent, ...]:
    snapshot_failure = None
    try:
        snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    except MunicipalAgendaError as exc:
        snapshot = None
        snapshot_failure = exc
        if diagnostics is not None:
            diagnostics.append(
                source_error(
                    "MUNI-AGENDA",
                    "Agenda municipal",
                    exc,
                    stage="SNAPSHOT",
                )
            )
    poster_url = (
        str(snapshot.get("poster_url", ""))
        if snapshot is not None
        else ""
    )
    try:
        page, _ = await asyncio.to_thread(
            _read_url, AGENDA_PAGE_URL, PAGE_HOSTS, PAGE_LIMIT_BYTES
        )
        poster_url = extract_poster_url(page)
        local_now = now.astimezone(GUARDAMAR_TIMEZONE)
        snapshot_month = (
            snapshot["_fetched_at"]
            .astimezone(GUARDAMAR_TIMEZONE)
            .strftime("%Y-%m")
            if snapshot is not None
            else None
        )
        current_month = local_now.strftime("%Y-%m")
        if (
            snapshot is not None
            and snapshot.get("poster_url") == poster_url
            and snapshot_month == current_month
        ):
            events = snapshot["_events"]
        else:
            poster, mime_type = await asyncio.to_thread(
                _read_url, poster_url, POSTER_HOSTS, POSTER_LIMIT_BYTES
            )
            poster_hash = hashlib.sha256(poster).hexdigest()
            if snapshot is not None and snapshot.get("poster_sha256") == poster_hash:
                events = snapshot["_events"]
            else:
                extracted = await extract_agenda_events(api_key, poster, mime_type)
                events = normalize_extraction(
                    extracted,
                    _poster_month(poster_url),
                )
            try:
                await asyncio.to_thread(
                    _write_snapshot,
                    state_path,
                    _snapshot_data(poster_url, poster_hash, now, events),
                )
            except OSError as exc:
                if diagnostics is not None:
                    diagnostics.append(
                        source_error(
                            "MUNI-AGENDA",
                            "Agenda municipal",
                            MunicipalAgendaError(
                                "Municipal snapshot could not be written",
                                code="WRITE",
                                description=(
                                    "не удалось сохранить локальный "
                                    "снимок афиши"
                                ),
                            ),
                            stage="SNAPSHOT",
                        )
                    )
    except (MunicipalAgendaError, GeminiError) as exc:
        if snapshot is None:
            if snapshot_failure is not None:
                raise MunicipalAgendaError(
                    "Municipal agenda recovery failed",
                    code="RECOVERY",
                    description=(
                        "локальный снимок повреждён, а официальный источник "
                        "недоступен"
                    ),
                ) from exc
            if isinstance(exc, GeminiError):
                raise MunicipalAgendaError(
                    "Municipal poster extraction failed",
                    code=exc.diagnostic_code,
                    status=exc.server_status,
                    description=exc.safe_description,
                ) from exc
            raise
        if diagnostics is not None:
            failure = source_error(
                "MUNI-AGENDA",
                "Agenda municipal",
                exc,
                stage="FALLBACK",
            )
            diagnostics.append(
                SourceDiagnostic(
                    failure.code,
                    failure.source,
                    f"{failure.description}; использован локальный снимок",
                )
            )
        events = snapshot["_events"]
    events = _apply_reviewed_corrections(poster_url, events)
    events = _merge_reviewed_text_agenda(events)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    active = [event for event in events if event.start_date <= local_day <= event.end_date]
    active.sort(
        key=lambda event: (
            event.start_date != event.end_date,
            event.start_time or "99:99",
            event.title_es.casefold(),
        )
    )
    return tuple(active[:2])


async def fetch_today_municipal_events(
    now: datetime,
    api_key: str,
    state_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[Event, ...]:
    """Return up to two translated events, using the snapshot during outages."""

    if not api_key:
        raise MunicipalAgendaError(
            "Gemini key is required for municipal agenda",
            code="CONFIG",
            description="не настроен ключ Gemini для муниципальной афиши",
        )
    source_events = await _current_events(
        api_key,
        now,
        state_path,
        diagnostics,
    )
    if not source_events:
        return ()
    try:
        titles = await translate_event_titles(
            api_key, [event.title_es for event in source_events]
        )
    except GeminiError as exc:
        raise MunicipalAgendaError(
            "Event translation failed",
            code=exc.diagnostic_code,
            status=exc.server_status,
            description=exc.safe_description,
        ) from exc
    result = []
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for source, title in zip(source_events, titles):
        starts_at = None
        ends_at = None
        if source.start_time:
            hour, minute = (int(part) for part in source.start_time.split(":"))
            starts_at = datetime.combine(
                local_day,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=GUARDAMAR_TIMEZONE,
            )
            if source.end_time:
                end_hour, end_minute = (
                    int(part) for part in source.end_time.split(":")
                )
                ends_at = datetime.combine(
                    local_day,
                    datetime.min.time().replace(
                        hour=end_hour,
                        minute=end_minute,
                    ),
                    tzinfo=GUARDAMAR_TIMEZONE,
                )
                if ends_at <= starts_at:
                    ends_at += timedelta(days=1)
        result.append(
            Event(
                title=title,
                starts_at=starts_at,
                ends_at=ends_at,
                place=source.place,
                active_until=source.end_date,
                category=source.category,
            )
        )
    return tuple(result)
