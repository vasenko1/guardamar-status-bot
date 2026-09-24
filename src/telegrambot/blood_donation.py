"""Lightweight Guardamar blood-donation schedule and next-day alert."""

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
SOURCE_HOST = "oficina20.san.gva.es"
SOURCE_PATH = "/gportal-ctcvcol-portlet/listaColectas.jsp"
GOOGLE_MAPS_URL = "https://maps.app.goo.gl/DXW3LqEmCNCjf9JX8"
DEFAULT_STATE_PATH = "state/blood_donation.json"
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

_REQUEST_TIMEOUT_SECONDS = 15
_RESPONSE_LIMIT_BYTES = 300_000
_MAX_SESSIONS = 16
_MAX_SENT_ALERTS = 32
_STATE_VERSION = 1
_ALERT_START = time(16, 45)
_ALERT_END = time(18, 0)

_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_MONTHS_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+("
    + "|".join(_MONTHS_ES)
    + r")\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*"
    r"([01]?\d|2[0-3]):([0-5]\d)\s*$"
)
_GUARDAMAR = "guardamar del segura"
_CITY_PREFIX = re.compile(
    r"^\s*GUARDAMAR\s+DEL\s+SEGURA\s*-\s*",
    re.IGNORECASE,
)
_ADDRESS_START = re.compile(
    r"^(?:c/|c\.|calle|carrer|avenida|avda\.?|av\.?|plaza|pla[cç]a|"
    r"carretera|ctra\.?|paseo|passeig)\b",
    re.IGNORECASE,
)
_SENT_KEY = re.compile(r"^alert:(\d{4}-\d{2}-\d{2})$")


class BloodDonationError(RuntimeError):
    """A source, schema or local-state failure that must fail closed."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class BloodDonationDeliveryUncertain(RuntimeError):
    """Telegram may already contain the alert; automatic resend is unsafe."""


@dataclass(frozen=True)
class BloodDonationSession:
    day: date
    starts_at: time
    ends_at: time
    place: str


class _ScheduleParser(HTMLParser):
    """Capture visible text order plus table rows without a DOM dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sequence = 0
        self.tokens: list[tuple[int, str]] = []
        self.rows: list[tuple[int, tuple[str, ...]]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.casefold()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        compact = " ".join(data.split())
        if not compact:
            return
        self.sequence += 1
        self.tokens.append((self.sequence, compact))
        if self._cell is not None:
            self._cell.append(compact)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join(self._cell))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append((self.sequence, tuple(self._row)))
            self._row = None
            self._cell = None


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", " ".join(value.split())).casefold()
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def _is_allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        query = urllib.parse.parse_qs(
            parsed.query, keep_blank_values=True, strict_parsing=True
        )
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == SOURCE_HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == SOURCE_PATH
        and parsed.fragment == ""
        and query == {"provincia": ["0007"]}
    )


def _decode_html(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return payload.decode("iso-8859-1")
        except UnicodeDecodeError as exc:
            raise BloodDonationError(
                "blood-donation HTML encoding is invalid", code="HTML"
            ) from exc


def _date_from_label(day: int, month: int, observed_day: date) -> date:
    candidates = []
    for year in range(observed_day.year - 1, observed_day.year + 2):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = (candidate - observed_day).days
        if -45 <= distance <= 90:
            candidates.append(candidate)
    if not candidates:
        raise BloodDonationError(
            "blood-donation date is outside the expected window", code="SCHEMA"
        )
    return min(candidates, key=lambda candidate: abs((candidate - observed_day).days))


def _parse_date_marker(value: str, observed_day: date) -> Optional[date]:
    match = _DATE_RE.search(_fold(value))
    if match is None:
        return None
    return _date_from_label(
        int(match.group(1)),
        _MONTHS_ES[match.group(2).casefold()],
        observed_day,
    )


def _parse_time_range(value: str) -> Optional[tuple[time, time]]:
    match = _TIME_RE.fullmatch(value)
    if match is None:
        return None
    start = time(int(match.group(1)), int(match.group(2)))
    end = time(int(match.group(3)), int(match.group(4)))
    if end <= start:
        raise BloodDonationError(
            "blood-donation time range is invalid", code="SCHEMA"
        )
    return start, end


def _pretty_label(value: str) -> str:
    compact = " ".join(value.split()).strip(" ,.;")
    if not compact:
        return compact
    if compact.isupper():
        compact = compact.title()
        for token in (" De ", " Del ", " La ", " El "):
            compact = compact.replace(token, token.lower())
    return compact


def _display_place(raw: str) -> str:
    value = _CITY_PREFIX.sub("", " ".join(raw.split())).strip(" ,-")
    parts = [part.strip(" .") for part in value.split(",") if part.strip(" .")]
    if not parts:
        raise BloodDonationError(
            "blood-donation Guardamar venue is missing", code="SCHEMA"
        )

    venue = _pretty_label(parts[0])
    if _fold(venue) == "centro sanitario integrado":
        venue = "Centro Sanitario Integrado"

    area = None
    if len(parts) > 1 and not _ADDRESS_START.search(parts[1]):
        area = _pretty_label(parts[1])
    if area is not None and _fold(area) == "zona de pediatria":
        area = "зона педиатрии"

    place = venue if not area else f"{venue} ({area})"
    if not 1 <= len(place) <= 120:
        raise BloodDonationError(
            "blood-donation Guardamar venue is invalid", code="SCHEMA"
        )
    return place


def parse_schedule(payload: bytes, observed_day: date) -> tuple[BloodDonationSession, ...]:
    """Extract only current/future Guardamar rows from the Alicante schedule."""

    parser = _ScheduleParser()
    try:
        parser.feed(_decode_html(payload))
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise BloodDonationError(
            "blood-donation HTML is malformed", code="HTML"
        ) from exc

    visible = " ".join(_fold(text) for _, text in parser.tokens)
    if not all(marker in visible for marker in (
        "alicante", "poblacion", "ubicacion", "horario"
    )):
        raise BloodDonationError(
            "blood-donation page markers are missing", code="SCHEMA"
        )

    date_markers: list[tuple[int, date]] = []
    for sequence, token in parser.tokens:
        parsed = _parse_date_marker(token, observed_day)
        if parsed is not None:
            date_markers.append((sequence, parsed))
    if len({value for _, value in date_markers}) < 3:
        raise BloodDonationError(
            "blood-donation schedule dates are missing", code="SCHEMA"
        )

    sessions: list[BloodDonationSession] = []
    marker_index = 0
    current_day = None
    for row_sequence, row in parser.rows:
        while (
            marker_index < len(date_markers)
            and date_markers[marker_index][0] <= row_sequence
        ):
            current_day = date_markers[marker_index][1]
            marker_index += 1

        city_index = next(
            (index for index, cell in enumerate(row) if _fold(cell) == _GUARDAMAR),
            None,
        )
        if city_index is None:
            continue
        if current_day is None:
            raise BloodDonationError(
                "Guardamar donation row has no date", code="SCHEMA"
            )

        location = next(
            (cell for cell in row[city_index + 1:] if cell.strip()),
            "",
        )
        if not location:
            raise BloodDonationError(
                "Guardamar donation row has no venue", code="SCHEMA"
            )
        if "suspendida" in _fold(location):
            continue

        parsed_time = next(
            (
                parsed
                for cell in reversed(row)
                if (parsed := _parse_time_range(cell)) is not None
            ),
            None,
        )
        if parsed_time is None:
            raise BloodDonationError(
                "Guardamar donation row has no valid time", code="SCHEMA"
            )
        if not observed_day <= current_day <= observed_day + timedelta(days=60):
            continue

        sessions.append(BloodDonationSession(
            current_day,
            parsed_time[0],
            parsed_time[1],
            _display_place(location),
        ))

    unique = {
        (item.day, item.starts_at, item.ends_at, item.place): item
        for item in sessions
    }
    result = tuple(sorted(
        unique.values(),
        key=lambda item: (item.day, item.starts_at, item.place.casefold()),
    ))
    if len(result) > _MAX_SESSIONS:
        raise BloodDonationError(
            "Guardamar blood-donation schedule is unexpectedly large",
            code="SCHEMA",
        )
    return result


def _session_to_data(session: BloodDonationSession) -> dict:
    return {
        "date": session.day.isoformat(),
        "start": session.starts_at.strftime("%H:%M"),
        "end": session.ends_at.strftime("%H:%M"),
        "place": session.place,
    }


def _session_from_data(raw: object) -> BloodDonationSession:
    if not isinstance(raw, dict) or set(raw) != {"date", "start", "end", "place"}:
        raise BloodDonationError(
            "blood-donation state contains an invalid session", code="STATE"
        )
    try:
        day = date.fromisoformat(raw["date"])
        start = time.fromisoformat(raw["start"])
        end = time.fromisoformat(raw["end"])
    except (TypeError, ValueError) as exc:
        raise BloodDonationError(
            "blood-donation state contains an invalid session", code="STATE"
        ) from exc
    place = raw["place"]
    if (
        not isinstance(place, str)
        or not 1 <= len(place) <= 120
        or start.second
        or end.second
        or end <= start
    ):
        raise BloodDonationError(
            "blood-donation state contains an invalid session", code="STATE"
        )
    return BloodDonationSession(day, start, end, place)


def _sent_date(value: str) -> date:
    match = _SENT_KEY.fullmatch(value)
    if match is None:
        raise BloodDonationError(
            "blood-donation state contains an invalid alert key", code="STATE"
        )
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise BloodDonationError(
            "blood-donation state contains an invalid alert date", code="STATE"
        ) from exc


class BloodDonationState:
    """One tiny atomic snapshot shared by the digest and 16:45 alert."""

    def __init__(self, path: Path = Path(DEFAULT_STATE_PATH)) -> None:
        self.path = path

    def read(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BloodDonationError(
                "blood-donation state is unreadable", code="STATE"
            ) from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "observed_at", "sessions", "sent_alerts"}
            or value.get("version") != _STATE_VERSION
            or not isinstance(value.get("observed_at"), str)
            or not isinstance(value.get("sessions"), list)
            or len(value["sessions"]) > _MAX_SESSIONS
            or not isinstance(value.get("sent_alerts"), list)
            or len(value["sent_alerts"]) > _MAX_SENT_ALERTS
        ):
            raise BloodDonationError(
                "blood-donation state is invalid", code="STATE"
            )
        try:
            observed_at = datetime.fromisoformat(value["observed_at"])
        except ValueError as exc:
            raise BloodDonationError(
                "blood-donation observation time is invalid", code="STATE"
            ) from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise BloodDonationError(
                "blood-donation observation time is naive", code="STATE"
            )
        sessions = [_session_from_data(item) for item in value["sessions"]]
        alerts = value["sent_alerts"]
        if any(not isinstance(item, str) for item in alerts):
            raise BloodDonationError(
                "blood-donation alert state is invalid", code="STATE"
            )
        for item in alerts:
            _sent_date(item)
        return {
            "version": _STATE_VERSION,
            "observed_at": observed_at,
            "sessions": sessions,
            "sent_alerts": list(dict.fromkeys(alerts)),
        }

    def _write(self, value: dict) -> None:
        payload = {
            "version": _STATE_VERSION,
            "observed_at": value["observed_at"].isoformat(),
            "sessions": [_session_to_data(item) for item in value["sessions"]],
            "sent_alerts": value["sent_alerts"],
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(
                    payload,
                    output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise BloodDonationError(
                "blood-donation state could not be saved", code="STATE"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def replace_sessions(
        self,
        observed_at: datetime,
        sessions: Sequence[BloodDonationSession],
    ) -> None:
        current = self.read()
        sent = [] if current is None else current["sent_alerts"]
        cutoff = observed_at.astimezone(GUARDAMAR_TIMEZONE).date() - timedelta(days=370)
        sent = [
            item for item in sent
            if _sent_date(item) >= cutoff
        ][-_MAX_SENT_ALERTS:]
        self._write({
            "observed_at": observed_at,
            "sessions": list(sessions),
            "sent_alerts": sent,
        })

    def fresh_sessions(self, now: datetime) -> tuple[BloodDonationSession, ...]:
        current = self.read()
        if current is None:
            return ()
        local_now = now.astimezone(GUARDAMAR_TIMEZONE)
        observed = current["observed_at"].astimezone(GUARDAMAR_TIMEZONE)
        if observed.date() != local_now.date() or observed > local_now + timedelta(minutes=5):
            return ()
        return tuple(current["sessions"])

    def sent_alerts(self) -> set[str]:
        current = self.read()
        return set() if current is None else set(current["sent_alerts"])

    def set_alert(self, key: str, sent: bool) -> None:
        _sent_date(key)
        current = self.read()
        if current is None:
            raise BloodDonationError(
                "blood-donation alert has no source snapshot", code="STATE"
            )
        values = set(current["sent_alerts"])
        if sent:
            values.add(key)
        else:
            values.discard(key)
        ordered = sorted(values, key=_sent_date)[-_MAX_SENT_ALERTS:]
        self._write({
            "observed_at": current["observed_at"],
            "sessions": current["sessions"],
            "sent_alerts": ordered,
        })


async def refresh_blood_donation_catalog(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> tuple[BloodDonationSession, ...]:
    """Perform the only daily network request and persist Guardamar rows."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("blood-donation observation time must be timezone-aware")
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            SOURCE_URL,
            is_allowed_url=_is_allowed_url,
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=_RESPONSE_LIMIT_BYTES,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise BloodDonationError(
            "blood-donation request failed", code=exc.code
        ) from exc

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    sessions = parse_schedule(payload, local_day)
    await asyncio.to_thread(
        BloodDonationState(state_path).replace_sessions,
        now,
        sessions,
    )
    return sessions


async def fetch_today_blood_donation_events(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> tuple[Event, ...]:
    """Return today's donation sessions from the fresh morning snapshot only."""

    sessions = await asyncio.to_thread(
        BloodDonationState(state_path).fresh_sessions, now
    )
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    result = []
    for session in sessions:
        if session.day != local_day:
            continue
        result.append(Event(
            title="Сегодня можно сдать кровь 🩸",
            starts_at=datetime.combine(
                session.day, session.starts_at, tzinfo=GUARDAMAR_TIMEZONE
            ),
            ends_at=datetime.combine(
                session.day, session.ends_at, tzinfo=GUARDAMAR_TIMEZONE
            ),
            place=session.place,
        ))
    return tuple(result)


def _date_label(value: date) -> str:
    return f"{value.day} {_MONTHS_RU[value.month]}"


def _place_parts(value: str) -> tuple[str, Optional[str]]:
    match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", value)
    if match is None:
        return value, None
    return match.group(1).strip(), match.group(2).strip()


def _place_line(value: str) -> str:
    base, area = _place_parts(value)
    if _fold(base) == "centro sanitario integrado":
        rendered = (
            f'<a href="{html.escape(GOOGLE_MAPS_URL, quote=True)}">'
            f"{html.escape(base)}</a>"
        )
    else:
        rendered = html.escape(base)
    if area:
        rendered += f" ({html.escape(area)})"
    return rendered


def build_alert_message(
    sessions: Sequence[BloodDonationSession],
) -> str:
    """Render the reviewed human-style next-day message."""

    if not sessions:
        raise BloodDonationError("blood-donation alert is empty", code="MESSAGE")
    days = {item.day for item in sessions}
    if len(days) != 1:
        raise BloodDonationError(
            "blood-donation alert spans multiple dates", code="MESSAGE"
        )
    day = next(iter(days))

    if len(sessions) == 1:
        session = sessions[0]
        base, _ = _place_parts(session.place)
        lines = [
            "🩸 <b>Завтра в Гуардамаре можно сдать кровь</b>",
            "",
            (
                "Если вы планировали стать донором — завтра, "
                f"<b>{_date_label(day)}</b>, кровь можно сдать в "
                f"{html.escape(base)}."
            ),
            "",
            (
                f"🕒 <b>{session.starts_at.strftime('%H:%M')}–"
                f"{session.ends_at.strftime('%H:%M')}</b>"
            ),
            f"📍 {_place_line(session.place)}",
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
        for session in sessions:
            lines.extend([
                "",
                (
                    f"🕒 <b>{session.starts_at.strftime('%H:%M')}–"
                    f"{session.ends_at.strftime('%H:%M')}</b>"
                ),
                f"📍 {_place_line(session.place)}",
            ])

    message = "\n".join(lines)
    if len(message) > 4096:
        raise BloodDonationError(
            "blood-donation alert is too long", code="MESSAGE"
        )
    return message


async def monitor_blood_donation_alert(
    state: BloodDonationState,
    now: datetime,
    send: Callable[[str], Awaitable[int]],
) -> str:
    """Publish one next-day alert from the same-day morning snapshot."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("blood-donation alert time must be timezone-aware")
    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    if not (_ALERT_START <= local_now.time() < _ALERT_END):
        return "outside_window"

    tomorrow = local_now.date() + timedelta(days=1)
    sessions = tuple(
        item for item in state.fresh_sessions(now)
        if item.day == tomorrow
    )
    if not sessions:
        return "no_trigger"

    key = f"alert:{tomorrow.isoformat()}"
    if key in state.sent_alerts():
        return "duplicate"

    state.set_alert(key, True)
    try:
        await send(build_alert_message(sessions))
    except BloodDonationDeliveryUncertain:
        raise
    except Exception:
        state.set_alert(key, False)
        raise
    return "published"
