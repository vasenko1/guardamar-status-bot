"""Guardamar blood-donation schedule and next-day alert."""

import asyncio
import html
import json
import os
import re
import tempfile
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .models import Event


SOURCE_URL = (
    "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
    "listaColectas.jsp?provincia=0007"
)
MAP_URL = "https://maps.app.goo.gl/DXW3LqEmCNCjf9JX8"
DEFAULT_STATE_PATH = "state/blood_donation.json"
TIMEZONE = ZoneInfo("Europe/Madrid")

_MAX_BYTES = 300_000
_TIMEOUT = 15
_MAX_SESSIONS = 12
_ALERT_START = time(16, 45)
_ALERT_END = time(18, 0)

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS_ES) + r")\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"^([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*"
    r"([01]?\d|2[0-3]):([0-5]\d)$"
)
_CITY_PREFIX = re.compile(
    r"^\s*GUARDAMAR\s+DEL\s+SEGURA\s*-\s*", re.IGNORECASE
)
_ADDRESS_RE = re.compile(
    r"^(?:c/|calle|carrer|avenida|avda\.?|av\.?|plaza|pla[cç]a|"
    r"carretera|ctra\.?)\b",
    re.IGNORECASE,
)


class BloodDonationError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class BloodDonationDeliveryUncertain(RuntimeError):
    pass


@dataclass(frozen=True)
class BloodDonationSession:
    day: date
    starts_at: time
    ends_at: time
    place: str


class _Parser(HTMLParser):
    """Keep visible text order and table rows; no DOM/browser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.n = 0
        self.tokens: list[tuple[int, str]] = []
        self.rows: list[tuple[int, tuple[str, ...]]] = []
        self.row: Optional[list[str]] = None
        self.cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        self.n += 1
        self.tokens.append((self.n, value))
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append((self.n, tuple(self.row)))
            self.row = None
            self.cell = None


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", " ".join(value.split())).casefold()
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _allowed_url(url: str) -> bool:
    try:
        value = urllib.parse.urlsplit(url)
        port = value.port
        query = urllib.parse.parse_qs(
            value.query, keep_blank_values=True, strict_parsing=True
        )
    except (TypeError, ValueError):
        return False
    return (
        value.scheme == "https"
        and value.hostname == "oficina20.san.gva.es"
        and port in {None, 443}
        and value.username is None
        and value.password is None
        and value.path == "/gportal-ctcvcol-portlet/listaColectas.jsp"
        and value.fragment == ""
        and query == {"provincia": ["0007"]}
    )


def _source_date(value: str, today: date) -> Optional[date]:
    match = _DATE_RE.search(_fold(value))
    if match is None:
        return None
    day = int(match.group(1))
    month = _MONTHS_ES[match.group(2).casefold()]
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if -45 <= (candidate - today).days <= 90:
            candidates.append(candidate)
    if not candidates:
        raise BloodDonationError("schedule date is invalid", code="SCHEMA")
    return min(candidates, key=lambda item: abs((item - today).days))


def _source_time(value: str) -> Optional[tuple[time, time]]:
    match = _TIME_RE.fullmatch(value.strip())
    if match is None:
        return None
    start = time(int(match.group(1)), int(match.group(2)))
    end = time(int(match.group(3)), int(match.group(4)))
    if end <= start:
        raise BloodDonationError("schedule time is invalid", code="SCHEMA")
    return start, end


def _source_place(value: str) -> str:
    value = _CITY_PREFIX.sub("", " ".join(value.split())).strip(" ,-")
    parts = [item.strip(" .") for item in value.split(",") if item.strip(" .")]
    if not parts:
        raise BloodDonationError("Guardamar venue is missing", code="SCHEMA")

    venue = parts[0]
    if venue.isupper():
        venue = venue.title().replace(" De ", " de ").replace(" Del ", " del ")
    if _fold(venue) == "centro sanitario integrado":
        venue = "Centro Sanitario Integrado"

    area = None
    if len(parts) > 1 and not _ADDRESS_RE.search(parts[1]):
        area = parts[1]
        if _fold(area) == "zona de pediatria":
            area = "зона педиатрии"
        elif area.isupper():
            area = area.title().replace(" De ", " de ")

    place = venue if area is None else f"{venue} ({area})"
    if not 1 <= len(place) <= 120:
        raise BloodDonationError("Guardamar venue is invalid", code="SCHEMA")
    return place


def parse_schedule(payload: bytes, today: date) -> tuple[BloodDonationSession, ...]:
    """Extract only today's/future Guardamar rows from the Alicante table."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("iso-8859-1")

    parser = _Parser()
    parser.feed(text)
    parser.close()

    visible = " ".join(_fold(value) for _, value in parser.tokens)
    if not all(word in visible for word in (
        "alicante", "poblacion", "ubicacion", "horario"
    )):
        raise BloodDonationError("schedule markers are missing", code="SCHEMA")

    markers = [
        (n, parsed)
        for n, value in parser.tokens
        if (parsed := _source_date(value, today)) is not None
    ]
    if not markers:
        raise BloodDonationError("schedule dates are missing", code="SCHEMA")

    result = []
    marker = 0
    current_day = None
    for row_n, row in parser.rows:
        while marker < len(markers) and markers[marker][0] <= row_n:
            current_day = markers[marker][1]
            marker += 1

        try:
            city = next(i for i, cell in enumerate(row)
                        if _fold(cell) == "guardamar del segura")
        except StopIteration:
            continue
        if current_day is None:
            raise BloodDonationError("Guardamar row has no date", code="SCHEMA")

        location = next((cell for cell in row[city + 1:] if cell.strip()), "")
        if not location:
            raise BloodDonationError("Guardamar row has no venue", code="SCHEMA")
        if "suspendida" in _fold(location):
            continue

        hours = next(
            (parsed for cell in reversed(row)
             if (parsed := _source_time(cell)) is not None),
            None,
        )
        if hours is None:
            raise BloodDonationError("Guardamar row has no hours", code="SCHEMA")
        if today <= current_day <= today + timedelta(days=60):
            result.append(BloodDonationSession(
                current_day, hours[0], hours[1], _source_place(location)
            ))

    result = sorted(
        set(result),
        key=lambda item: (item.day, item.starts_at, item.place.casefold()),
    )
    if len(result) > _MAX_SESSIONS:
        raise BloodDonationError("too many Guardamar sessions", code="SCHEMA")
    return tuple(result)


def _session_data(value: BloodDonationSession) -> dict:
    return {
        "date": value.day.isoformat(),
        "start": value.starts_at.strftime("%H:%M"),
        "end": value.ends_at.strftime("%H:%M"),
        "place": value.place,
    }


def _session_from_data(value: object) -> BloodDonationSession:
    if not isinstance(value, dict):
        raise BloodDonationError("invalid session state", code="STATE")
    try:
        session = BloodDonationSession(
            date.fromisoformat(value["date"]),
            time.fromisoformat(value["start"]),
            time.fromisoformat(value["end"]),
            value["place"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BloodDonationError("invalid session state", code="STATE") from exc
    if (
        not isinstance(session.place, str)
        or not session.place
        or len(session.place) > 120
        or session.ends_at <= session.starts_at
    ):
        raise BloodDonationError("invalid session state", code="STATE")
    return session


class BloodDonationState:
    """One current-day snapshot plus one duplicate-prevention date."""

    def __init__(self, path: Path = Path(DEFAULT_STATE_PATH)) -> None:
        self.path = path

    def read(self):
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            observed = datetime.fromisoformat(raw["observed_at"])
            sessions = tuple(_session_from_data(item) for item in raw["sessions"])
            alerted_for = (
                None if raw["alerted_for"] is None
                else date.fromisoformat(raw["alerted_for"])
            )
        except (
            OSError, UnicodeDecodeError, json.JSONDecodeError,
            KeyError, TypeError, ValueError,
        ) as exc:
            raise BloodDonationError("invalid blood-donation state", code="STATE") from exc
        if (
            raw.get("version") != 1
            or len(sessions) > _MAX_SESSIONS
            or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            raise BloodDonationError("invalid blood-donation state", code="STATE")
        return observed, sessions, alerted_for

    def write(
        self,
        observed: datetime,
        sessions: Sequence[BloodDonationSession],
        alerted_for: Optional[date],
    ) -> None:
        payload = {
            "version": 1,
            "observed_at": observed.isoformat(),
            "sessions": [_session_data(item) for item in sessions],
            "alerted_for": alerted_for.isoformat() if alerted_for else None,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise BloodDonationError("cannot save blood-donation state", code="STATE") from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def replace_sessions(
        self,
        observed: datetime,
        sessions: Sequence[BloodDonationSession],
    ) -> None:
        current = self.read()
        alerted_for = None if current is None else current[2]
        local_day = observed.astimezone(TIMEZONE).date()
        if alerted_for is not None and alerted_for <= local_day:
            alerted_for = None
        self.write(observed, sessions, alerted_for)

    def fresh_sessions(self, now: datetime) -> tuple[BloodDonationSession, ...]:
        current = self.read()
        if current is None:
            return ()
        observed, sessions, _ = current
        local_now = now.astimezone(TIMEZONE)
        observed = observed.astimezone(TIMEZONE)
        if observed.date() != local_now.date() or observed > local_now + timedelta(minutes=5):
            return ()
        return sessions

    def alerted_for(self) -> Optional[date]:
        current = self.read()
        return None if current is None else current[2]

    def set_alerted_for(self, value: Optional[date]) -> None:
        current = self.read()
        if current is None:
            raise BloodDonationError("alert has no source snapshot", code="STATE")
        self.write(current[0], current[1], value)


async def refresh_blood_donation_catalog(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> tuple[BloodDonationSession, ...]:
    """The feature's only network request: one bounded morning GET."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("blood-donation observation time must be timezone-aware")

    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            SOURCE_URL,
            is_allowed_url=_allowed_url,
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=_MAX_BYTES,
            timeout_seconds=_TIMEOUT,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise BloodDonationError("blood-donation request failed", code=exc.code) from exc

    sessions = parse_schedule(payload, now.astimezone(TIMEZONE).date())
    await asyncio.to_thread(
        BloodDonationState(state_path).replace_sessions, now, sessions
    )
    return sessions


async def fetch_today_blood_donation_events(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> tuple[Event, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("blood-donation event time must be timezone-aware")
    sessions = await asyncio.to_thread(BloodDonationState(state_path).fresh_sessions, now)
    today = now.astimezone(TIMEZONE).date()
    return tuple(
        Event(
            title="Сегодня можно сдать кровь 🩸",
            starts_at=datetime.combine(item.day, item.starts_at, tzinfo=TIMEZONE),
            ends_at=datetime.combine(item.day, item.ends_at, tzinfo=TIMEZONE),
            place=item.place,
        )
        for item in sessions
        if item.day == today
    )


def _date_label(value: date) -> str:
    return f"{value.day} {_MONTHS_RU[value.month]}"


def _place_parts(value: str) -> tuple[str, Optional[str]]:
    match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", value)
    return (
        (value, None)
        if match is None
        else (match.group(1).strip(), match.group(2).strip())
    )


def _place_line(value: str) -> str:
    base, area = _place_parts(value)
    if _fold(base) == "centro sanitario integrado":
        base = f'<a href="{MAP_URL}">{html.escape(base)}</a>'
    else:
        base = html.escape(base)
    return base if area is None else f"{base} ({html.escape(area)})"


def build_alert_message(sessions: Sequence[BloodDonationSession]) -> str:
    if not sessions or len({item.day for item in sessions}) != 1:
        raise BloodDonationError("invalid blood-donation alert", code="MESSAGE")

    day = sessions[0].day
    if len(sessions) == 1:
        item = sessions[0]
        base, _ = _place_parts(item.place)
        lines = [
            "🩸 <b>Завтра в Гуардамаре можно сдать кровь</b>",
            "",
            (
                "Если вы планировали стать донором — завтра, "
                f"<b>{_date_label(day)}</b>, кровь можно сдать в "
                f"{html.escape(base)}."
            ),
            "",
            f"🕒 <b>{item.starts_at:%H:%M}–{item.ends_at:%H:%M}</b>",
            f"📍 {_place_line(item.place)}",
        ]
    else:
        lines = [
            "🩸 <b>Завтра в Гуардамаре можно сдать кровь</b>",
            "",
            (
                "Если вы планировали стать донором — завтра, "
                f"<b>{_date_label(day)}</b>, в городе будет несколько "
                "пунктов сдачи крови."
            ),
        ]
        for item in sessions:
            lines += [
                "",
                f"🕒 <b>{item.starts_at:%H:%M}–{item.ends_at:%H:%M}</b>",
                f"📍 {_place_line(item.place)}",
            ]

    message = "\n".join(lines)
    if len(message) > 4096:
        raise BloodDonationError("blood-donation alert is too long", code="MESSAGE")
    return message


async def monitor_blood_donation_alert(
    state: BloodDonationState,
    now: datetime,
    send: Callable[[str], Awaitable[int]],
) -> str:
    """Send tomorrow's alert once, using only this morning's snapshot."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("blood-donation alert time must be timezone-aware")

    local_now = now.astimezone(TIMEZONE)
    if not (_ALERT_START <= local_now.time() < _ALERT_END):
        return "outside_window"

    tomorrow = local_now.date() + timedelta(days=1)
    sessions = tuple(
        item for item in state.fresh_sessions(now) if item.day == tomorrow
    )
    if not sessions:
        return "no_trigger"
    if state.alerted_for() == tomorrow:
        return "duplicate"

    state.set_alerted_for(tomorrow)
    try:
        await send(build_alert_message(sessions))
    except BloodDonationDeliveryUncertain:
        raise
    except Exception:
        state.set_alerted_for(None)
        raise
    return "published"
