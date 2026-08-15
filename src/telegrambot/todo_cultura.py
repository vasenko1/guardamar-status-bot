"""Bounded supplemental text from Todo Cultura Vega Baja."""

import asyncio
import hashlib
import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from ._transport import BoundedFetchError, fetch_bounded
from .event_urls import normalize_ticket_url


API_HOSTS = {"todoculturavegabaja.es", "www.todoculturavegabaja.es"}
REQUEST_TIMEOUT_SECONDS = 20
RESPONSE_LIMIT_BYTES = 300_000
PROGRAM_TEXT_LIMIT = 12_000
MAX_CANDIDATES = 3
MAX_INDEX_CANDIDATES = 100
METADATA_PAGE_SIZE = 100
METADATA_LIMIT_BYTES = 150_000
ROLLING_WINDOW_DAYS = 7
CURSOR_OVERLAP_MINUTES = 5
PARSER_VERSION = 7
API_URL = "https://todoculturavegabaja.es/wp-json/wp/v2/mec-events"


class TodoCulturaError(RuntimeError):
    """A safe failure from the optional supplemental source."""

    def __init__(self, message: str, *, code: str, description: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.safe_description = description
        self.server_status = None


@dataclass(frozen=True)
class TodoCulturaAdmission:
    title_hint: str
    price_cents: Optional[int]
    ticket_url: Optional[str] = None
    evidence: str = ""
    event_date: Optional[date] = None
    start_time: Optional[str] = None
    event_dates: Tuple[date, ...] = ()


@dataclass(frozen=True)
class TodoCulturaParticipation:
    """Explicit event-local participation facts from the dated programme."""

    title_hint: str
    registration_contact: str
    participation_note: Optional[str] = None
    capacity_limited: bool = False
    evidence: str = ""


@dataclass(frozen=True)
class TodoCulturaProgram:
    text: str
    sha256: str
    source_url: str
    modified: Optional[str]
    admissions: Tuple[TodoCulturaAdmission, ...] = ()
    participation: Tuple[TodoCulturaParticipation, ...] = ()
    dates: Tuple[date, ...] = ()


@dataclass(frozen=True)
class TodoCulturaWindow:
    """New date sections plus the bounded state needed by the next run."""

    programs: Tuple[TodoCulturaProgram, ...]
    source_state: Dict[str, Any]


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")


_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_DATE_HEADER = re.compile(
    r"^\s*[–—•-]?\s*"
    r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"
    r"\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?"
    r"(?:\s*[,.:;–—-]\s*(.*))?$",
    re.IGNORECASE,
)
_DATE_MENTION = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?\b",
    re.IGNORECASE,
)


def _header_date(line: str, default_year: int) -> Optional[date]:
    match = _DATE_HEADER.fullmatch(line.strip())
    if match is None:
        return None
    month = _MONTHS.get(match.group(2).casefold())
    if month is None:
        return None
    try:
        return date(int(match.group(3) or default_year), month, int(match.group(1)))
    except ValueError:
        return None


def _date_sections(
    lines: List[str],
    default_year: int,
    reference_date: Optional[date] = None,
) -> Dict[date, str]:
    """Split standalone and inline Spanish date headings deterministically."""

    sections: Dict[date, List[str]] = {}
    current: Optional[date] = None
    for line in lines:
        match = _DATE_HEADER.fullmatch(line.strip())
        parsed = _header_date(line, default_year)
        if parsed is not None:
            if match is not None and match.group(3) is None:
                anchor = current or reference_date
                if anchor is not None:
                    alternatives = []
                    for year in (
                        default_year - 1, default_year, default_year + 1
                    ):
                        try:
                            alternatives.append(parsed.replace(year=year))
                        except ValueError:
                            continue
                    parsed = min(
                        alternatives,
                        key=lambda candidate: abs((candidate - anchor).days),
                    )
            current = parsed
            sections.setdefault(parsed, []).append(
                f"{parsed.isoformat()}"
            )
            trailing = match.group(4).strip() if match and match.group(4) else ""
            if trailing:
                sections[parsed].append(trailing)
            continue
        if current is not None:
            sections[current].append(line)
    return {
        day: "\n".join(section)
        for day, section in sections.items()
        if section
    }


def _mentioned_dates(text: str, reference_date: date) -> set[date]:
    """Read bounded date hints from a title or REST excerpt."""

    result = set()
    for match in _DATE_MENTION.finditer(text):
        month = _MONTHS.get(match.group(2).casefold())
        if month is None:
            continue
        years = (
            [int(match.group(3))]
            if match.group(3)
            else [reference_date.year - 1, reference_date.year, reference_date.year + 1]
        )
        candidates = []
        for year in years:
            try:
                candidates.append(date(year, month, int(match.group(1))))
            except ValueError:
                continue
        if candidates:
            result.add(min(
                candidates,
                key=lambda candidate: abs((candidate - reference_date).days),
            ))
    return result


def _participation(text: str) -> Tuple[TodoCulturaParticipation, ...]:
    """Bind only explicit registration rows to their preceding event row."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = []
    seen = set()
    for index, line in enumerate(lines):
        match = re.match(
            r"^(?:inscripci(?:ón|on|ones)|reservas?)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if match is None:
            continue
        contact = " ".join(match.group(1).split())
        phone = re.search(r"(?:\+34\s*)?(?:\d[\s.-]*){9}", contact)
        email = re.search(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            contact,
            re.IGNORECASE,
        )
        if (phone is None and email is None) or len(contact) > 180:
            continue
        anchors = []
        for candidate in lines[max(0, index - 4):index]:
            normalized = candidate.casefold()
            if (
                any(word in normalized for word in (
                    "taller", "ruta", "visita", "concierto", "curso",
                    "actividad", "sesión", "sesion",
                ))
                and "actividades del centro social juvenil" not in normalized
            ):
                anchors.append(candidate)
        if not anchors:
            continue
        anchor = next((
            candidate
            for candidate in reversed(anchors)
            if re.search(r"\b\d{1,2}\s*(?:a|:)\s*\d{1,2}\b", candidate)
        ), anchors[-1])
        contact = re.sub(r"\bwasap\b", "WhatsApp", contact, flags=re.IGNORECASE)
        contact = re.sub(
            r"\bwhatsapp\b", "WhatsApp", contact, flags=re.IGNORECASE
        )
        contact = re.sub(r"\s+y\s+WhatsApp\b", " или WhatsApp", contact)
        age = re.search(
            r"(?:jóvenes|jovenes|personas|niños|niñas)"
            r"(?:\s+de|\s+entre)?\s+(\d{1,2})\s+(?:a|y)\s+"
            r"(\d{1,2})\s+años",
            anchor,
            re.IGNORECASE,
        )
        minimum_age = re.search(
            r"(?:edades?\s+)?a\s+partir\s+de\s+(\d{1,2})\s+años",
            anchor,
            re.IGNORECASE,
        )
        if age is not None:
            audience = (
                "молодёжи"
                if re.search(r"\bjóvenes\b|\bjovenes\b", anchor, re.I)
                else "участников"
            )
            participation_note = (
                f"для {audience} {age.group(1)}–{age.group(2)} лет"
            )
        elif minimum_age is not None:
            participation_note = (
                f"для участников от {minimum_age.group(1)} лет"
            )
        else:
            participation_note = None
        evidence_lines = lines[max(0, index - 2):index + 1]
        evidence = " ".join(evidence_lines)[:600]
        key = (anchor.casefold(), contact.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(TodoCulturaParticipation(
            title_hint=anchor,
            registration_contact=contact,
            participation_note=participation_note,
            capacity_limited=bool(re.search(
                r"\b(?:plazas|aforo)\b.{0,24}\blimitad[oa]s?\b",
                evidence,
                re.IGNORECASE,
            )),
            evidence=evidence,
        ))
        if len(result) == 12:
            break
    return tuple(result)


def _allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in API_HOSTS


_EVENT_ROW = re.compile(
    r"^\s*[–—•-]?\s*(?:\d{1,2}(?:[.,:]\d{1,2})?\s*"
    r"(?:a\s*\d{1,2}(?:[.,:]\d{1,2})?\s*)?(?:h(?:oras?)?\.?)?\s*:\s*)",
    re.IGNORECASE,
)
_INLINE_EVENT_ROW = re.compile(
    r"\b\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?.{0,80}"
    r"\b\d{1,2}(?:[.,:]\d{1,2})?\s*(?:h(?:oras?)?\.?)?\s*:\s*",
    re.IGNORECASE,
)
def _paragraphs(rendered: str) -> List[Tuple[str, str]]:
    """Return bounded paragraph HTML and normalized visible text."""

    result = []
    for fragment in re.findall(
        r"<p\b[^>]*>(.*?)</p>", rendered, flags=re.IGNORECASE | re.DOTALL
    ):
        plain = " ".join(
            html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split()
        )
        if plain:
            result.append((fragment, plain))
    return result


def _ticket_url(fragment: str) -> Optional[str]:
    """Keep only explicit purchase links on reviewed ticketing hosts."""

    for raw_url in re.findall(
        r"href\s*=\s*['\"]([^'\"]+)['\"]", fragment, re.IGNORECASE
    ):
        normalized = normalize_ticket_url(html.unescape(raw_url))
        if normalized is not None:
            return normalized
    return None


def _event_time(value: str) -> Optional[str]:
    """Read the explicit leading or inline time that introduces an event."""

    patterns = (
        r"(?<!\d)(\d{1,2})(?:[.,:](\d{2}))?\s*"
        r"(?:h(?:oras?)?\.?)?\s+a\s+\d{1,2}"
        r"(?:[.,:]\d{2})?\s*h",
        r"\ba\s+las\s+(\d{1,2})(?:[.,:](\d{2}))?"
        r"\s*(?:h(?:oras?)?\.?)?",
        r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)",
        r"(?<!\d)(\d{1,2})[.,](\d{2})\s*h(?:oras?)?\.?(?!\d)",
        r"(?<!\d)(\d{1,2})\s*h(?:oras?)?\.?(?!\d)",
    )
    for raw_pattern in patterns:
        match = re.search(raw_pattern, value, re.IGNORECASE)
        if match is None:
            continue
        hour = int(match.group(1))
        minute = int(
            match.group(2) if match.lastindex and match.lastindex >= 2
            and match.group(2) else 0
        )
        if hour <= 23 and minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def _all_mentioned_dates(text: str, reference_date: date) -> Tuple[date, ...]:
    """Expand explicit Spanish date lists as occurrence-level facts."""

    result = set(_mentioned_dates(text, reference_date))
    list_pattern = re.compile(
        r"\b((?:\d{1,2}\s*(?:,|y)\s*)+\d{1,2})\s+de\s+"
        r"([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?\b",
        re.IGNORECASE,
    )
    for match in list_pattern.finditer(text):
        month = _MONTHS.get(match.group(2).casefold())
        if month is None:
            continue
        year = int(match.group(3) or reference_date.year)
        for raw_day in re.findall(r"\d{1,2}", match.group(1)):
            try:
                candidates = [date(year, month, int(raw_day))]
                if match.group(3) is None:
                    candidates = [
                        date(candidate_year, month, int(raw_day))
                        for candidate_year in (
                            reference_date.year - 1,
                            reference_date.year,
                            reference_date.year + 1,
                        )
                    ]
                result.add(min(
                    candidates,
                    key=lambda candidate: abs((candidate - reference_date).days),
                ))
            except ValueError:
                continue
    range_pattern = re.compile(
        r"\b(?:del\s+)?(\d{1,2})\s+(?:al|a)\s+(\d{1,2})\s+de\s+"
        r"([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?\b",
        re.IGNORECASE,
    )
    for match in range_pattern.finditer(text):
        month = _MONTHS.get(match.group(3).casefold())
        if month is None:
            continue
        year = int(match.group(4) or reference_date.year)
        for raw_day in match.group(1), match.group(2):
            try:
                result.add(date(year, month, int(raw_day)))
            except ValueError:
                continue
    return tuple(sorted(result))


def _admissions(
    rendered: str,
    reference_date: Optional[date] = None,
) -> Tuple[TodoCulturaAdmission, ...]:
    """Bind explicit admission facts to the preceding event row.

    Municipal programmes put admission facts in the event paragraph or the
    paragraph immediately after it, so the event row itself is retained as
    deterministic matching evidence.
    """

    result = []
    seen = set()
    title_hint = None
    title_dates: Tuple[date, ...] = ()
    title_time = None
    current_date = None
    anchor = reference_date or date.today()
    for paragraph, plain in _paragraphs(rendered):
        admission_marker = re.search(
            r"\b(?:precio\s*:|el\s+precio\b|venta\s+de\s+entradas\b|"
            r"(?:(?:la|las)\s+)?entradas?\s+(?:(?:es|son)\s+)?"
            r"(?:libres?|gratuitas?)\b|"
            r"(?:(?:el|los)\s+)?accesos?\s+(?:(?:es|son)\s+)?"
            r"(?:libres?|gratuitos?)\b|"
            r"entradas?\s+en\b)",
            plain,
            re.IGNORECASE,
        )
        event_context = (
            plain[:admission_marker.start()].strip(" .,:;–—-")
            if admission_marker is not None
            else plain
        )
        header_date = _header_date(event_context, anchor.year)
        if header_date is not None:
            current_date = header_date
        mentioned = _all_mentioned_dates(event_context, anchor)
        mentioned_date = min(
            mentioned,
            key=lambda candidate: abs((candidate - anchor).days),
        ) if mentioned else None
        if mentioned_date is not None:
            current_date = mentioned_date
        explicit_time = _event_time(event_context)
        is_event_row = bool(
            _EVENT_ROW.match(event_context)
            or _INLINE_EVENT_ROW.search(event_context)
            or re.match(
                r"^\s*[–—•-]?\s*a\s+las\s+\d",
                event_context,
                re.IGNORECASE,
            )
        )
        if is_event_row:
            title_hint = event_context[:300]
            title_dates = mentioned or (
                (current_date,) if current_date is not None else ()
            )
            title_time = explicit_time
        price_match = re.search(
            r"(?:\bprecio\s+de\s+(?:(?:la|las)\s+)?(?:entrada|entradas)"
            r"\s+es\s+de\s+(\d{1,4})(?:[,.](\d{1,2}))?\s+euros?\b|"
            r"\bprecio\s*:\s*(\d{1,4})(?:[,.](\d{1,2}))?\s*(?:€|euros?)"
            r")",
            plain,
            re.IGNORECASE,
        )
        free = re.search(
            r"\b(?:(?:(?:la|las)\s+)?entradas?|"
            r"(?:(?:el|los)\s+)?accesos?)"
            r"(?:\s+(?:es|son))?\s+(?:libres?|gratuit[oa]s?)\b",
            plain,
            re.IGNORECASE,
        )
        ticket_url = _ticket_url(paragraph)
        ticket_only = bool(
            (is_event_row or bool(mentioned and event_context))
            and ticket_url
            and re.search(
                r"\b(?:entradas?|tickets?|venta|compra)\b",
                plain,
                re.IGNORECASE,
            )
        )
        if price_match is None and free is None and not ticket_only:
            continue
        if mentioned and event_context:
            # A dated paragraph carrying its own admission fact is a complete
            # event block even when it does not use the usual leading-time
            # punctuation. It must not borrow the preceding row's identity.
            title_hint = event_context[:300]
            title_dates = mentioned
            title_time = explicit_time
        if title_hint is None:
            # Some short articles put the event name and price in one
            # paragraph. It remains event-local evidence, not a guessed link.
            title_hint = plain[:300]
            title_dates = mentioned or (
                (current_date,) if current_date is not None else ()
            )
            title_time = explicit_time
        if price_match is not None:
            euros = int(price_match.group(1) or price_match.group(3))
            cents = int(
                (price_match.group(2) or price_match.group(4) or "0")
                .ljust(2, "0")
            )
            price_cents = euros * 100 + cents
        elif free is not None:
            price_cents = 0
        else:
            price_cents = None
        if price_cents is not None and not 0 <= price_cents <= 100_000:
            continue
        evidence = (
            plain if plain == title_hint else f"{title_hint} {plain}"
        )[:600]
        key = (
            title_hint.casefold(), title_dates, title_time,
            price_cents, ticket_url,
        )
        if key not in seen:
            seen.add(key)
            result.append(TodoCulturaAdmission(
                title_hint=title_hint,
                price_cents=price_cents,
                ticket_url=ticket_url,
                evidence=evidence,
                event_date=title_dates[0] if len(title_dates) == 1 else None,
                start_time=title_time,
                event_dates=title_dates,
            ))
        if len(result) == 20:
            break
    return tuple(result)


_TRANSPORT_DESCRIPTIONS = {
    "REDIRECT": "получен недопустимый адрес ответа",
    "CONTENT-TYPE": "источник вернул данные не в формате JSON",
    "NETWORK": "не удалось получить дополнительную программу",
    "TOO-LARGE": "ответ превысил допустимый размер",
}


def _read_api_payload(url: str, limit: int) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=limit,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        # This optional supplement keeps one coarse NETWORK code for
        # timeouts as well; finer classification adds no operator value.
        code = "NETWORK" if exc.code == "TIMEOUT" else exc.code
        raise TodoCulturaError(
            f"Todo Cultura request failed: {code}",
            code=code,
            description=(
                f"сервер вернул HTTP {exc.status}"
                if exc.status is not None
                else _TRANSPORT_DESCRIPTIONS.get(code)
            ),
        ) from exc
    return payload


def _plain_lines(rendered: str) -> List[str]:
    parser = _TextParser()
    parser.feed(rendered)
    full_text = html.unescape("".join(parser.parts))
    return [
        " ".join(line.split())
        for line in full_text.splitlines()
        if line.strip()
    ]


def _parse_modified(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _metadata_query(cursor: Optional[str]) -> str:
    parameters: Dict[str, Any] = {
        "search": "Guardamar",
        "per_page": METADATA_PAGE_SIZE,
        "orderby": "modified",
        "order": "asc" if cursor else "desc",
        "_fields": "id,modified_gmt,link,title,excerpt",
    }
    parsed_cursor = _parse_modified(cursor)
    if parsed_cursor is not None:
        parameters["modified_after"] = (
            parsed_cursor - timedelta(minutes=CURSOR_OVERLAP_MINUTES)
        ).isoformat(timespec="seconds")
    return f"{API_URL}?{urllib.parse.urlencode(parameters)}"


def _read_metadata(cursor: Optional[str]) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(_read_api_payload(
            _metadata_query(cursor), METADATA_LIMIT_BYTES
        ))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TodoCulturaError(
            "Todo Cultura metadata was invalid",
            code="INVALID",
            description="источник вернул неполный индекс мероприятий",
        ) from exc
    if not isinstance(payload, list) or len(payload) > METADATA_PAGE_SIZE:
        raise TodoCulturaError(
            "Todo Cultura metadata was invalid",
            code="INVALID",
            description="источник вернул неполный индекс мероприятий",
        )
    return [item for item in payload if isinstance(item, dict)]


def _metadata_candidate(
    item: Dict[str, Any], reference_date: date
) -> Dict[str, Any]:
    identifier = item.get("id")
    modified = item.get("modified_gmt")
    link = item.get("link")
    title_value = item.get("title")
    excerpt_value = item.get("excerpt")
    if not isinstance(title_value, dict) or not isinstance(
        excerpt_value, dict
    ):
        raise ValueError
    title = title_value.get("rendered", "")
    excerpt = excerpt_value.get("rendered", "")
    if (
        not isinstance(identifier, int)
        or identifier <= 0
        or _parse_modified(modified) is None
        or not isinstance(link, str)
        or not _allowed_url(link)
        or not isinstance(title, str)
        or not isinstance(excerpt, str)
    ):
        raise ValueError
    metadata_lines = _plain_lines(f"{title}\n{excerpt}")
    metadata_text = " ".join(metadata_lines).casefold()
    hinted = _date_sections(
        metadata_lines,
        reference_date.year,
        reference_date,
    )
    mentioned = _mentioned_dates(
        " ".join(_plain_lines(f"{title}\n{excerpt}")), reference_date
    )
    hinted_dates = set(hinted) | mentioned
    detail_priority = 0
    if any(word in metadata_text for word in (
        "taller", "curso", "ruta", "visita", "escape room",
        "actividad juvenil",
    )):
        detail_priority += 1
    if re.search(
        r"\b(?:para\s+(?:jóvenes|jovenes|niños|ninas|niñas)|"
        r"edades?|años?)\b",
        metadata_text,
    ):
        detail_priority += 1
    if any(word in metadata_text for word in (
        "inscrip", "reserv", "aforo", "plazas", "entrada", "precio",
    )):
        detail_priority += 1
    return {
        "id": identifier,
        "modified_gmt": modified,
        "link": link,
        "dates": sorted(day.isoformat() for day in hinted_dates),
        "processed_dates": [],
        "detail_checked": not hinted_dates,
        "detail_priority": detail_priority,
    }


def _candidate_dates(candidate: Dict[str, Any], field: str) -> set[date]:
    result = set()
    values = candidate.get(field, [])
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            result.add(date.fromisoformat(value))
        except ValueError:
            continue
    return result


def _candidate_priority(
    candidate: Dict[str, Any],
    start: date,
    end: date,
    horizon: date,
) -> Tuple[int, int, int, float]:
    dates = _candidate_dates(candidate, "dates")
    processed = _candidate_dates(candidate, "processed_dates")
    pending_window = sorted(
        day for day in dates
        if start <= day <= end and day not in processed
    )
    pending_horizon = sorted(
        day for day in dates
        if start <= day <= horizon and day not in processed
    )
    if pending_window:
        rank = 0
        day_distance = (pending_window[0] - start).days
    elif not candidate.get("detail_checked") and any(
        start <= day <= horizon for day in dates
    ):
        rank = 1
        day_distance = (
            (pending_horizon[0] - start).days if pending_horizon else 999
        )
    elif not candidate.get("detail_checked"):
        rank = 2
        day_distance = 999
    else:
        rank = 3
        day_distance = 999
    detail_priority = candidate.get("detail_priority", 0)
    if not isinstance(detail_priority, int) or not 0 <= detail_priority <= 3:
        detail_priority = 0
    modified = _parse_modified(candidate.get("modified_gmt"))
    return (
        rank,
        day_distance,
        -detail_priority,
        -(modified.timestamp() if modified is not None else 0.0),
    )


def _read_documents(identifiers: List[int]) -> List[Dict[str, Any]]:
    if not identifiers:
        return []
    query = urllib.parse.urlencode({
        "include": ",".join(str(value) for value in identifiers),
        "per_page": len(identifiers),
        "orderby": "include",
        "_fields": "id,modified_gmt,link,title,content",
    })
    try:
        payload = json.loads(_read_api_payload(
            f"{API_URL}?{query}", RESPONSE_LIMIT_BYTES
        ))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TodoCulturaError(
            "Todo Cultura detail JSON was invalid",
            code="INVALID",
            description="источник вернул неполные тексты мероприятий",
        ) from exc
    if not isinstance(payload, list) or len(payload) != len(identifiers):
        raise TodoCulturaError(
            "Todo Cultura detail JSON was invalid",
            code="INVALID",
            description="источник вернул неполные тексты мероприятий",
        )
    documents = [item for item in payload if isinstance(item, dict)]
    returned_ids = [item.get("id") for item in documents]
    if (
        not all(isinstance(value, int) for value in returned_ids)
        or len(set(returned_ids)) != len(identifiers)
        or set(returned_ids) != set(identifiers)
    ):
        raise TodoCulturaError(
            "Todo Cultura detail JSON was invalid",
            code="INVALID",
            description="источник вернул неполные тексты мероприятий",
        )
    return documents


def _bounded_candidates(
    candidates: List[Dict[str, Any]], local_day: date
) -> List[Dict[str, Any]]:
    unique = {candidate["id"]: candidate for candidate in candidates}
    for candidate in unique.values():
        candidate["processed_dates"] = sorted(
            day.isoformat()
            for day in _candidate_dates(candidate, "processed_dates")
            if day >= local_day
        )
    ordered = sorted(
        unique.values(),
        key=lambda candidate: (
            not any(
                day >= local_day
                for day in _candidate_dates(candidate, "dates")
            ),
            bool(candidate.get("detail_checked")),
            str(candidate.get("modified_gmt", "")),
        ),
    )
    return ordered[:MAX_INDEX_CANDIDATES]


def _read_program_window(
    local_day: date,
    prior_state: Optional[Dict[str, Any]] = None,
) -> TodoCulturaWindow:
    """Incrementally collect only sections entering the rolling week."""

    prior = prior_state if isinstance(prior_state, dict) else {}
    if prior.get("parser_version") != PARSER_VERSION:
        # Re-open the rolling window once when extraction capabilities change.
        # The metadata cursor remains useful, but old coverage must not prevent
        # richer event-local facts from being collected.
        prior = {
            **prior,
            "cursor_modified_gmt": None,
            "covered_dates": [],
            "candidates": [
                {
                    **candidate,
                    "processed_dates": [],
                    "detail_checked": False,
                }
                for candidate in prior.get("candidates", [])
                if isinstance(candidate, dict)
            ],
        }
    cursor = prior.get("cursor_modified_gmt")
    if not isinstance(cursor, str):
        cursor = None
    covered_dates = _candidate_dates(
        {"covered_dates": prior.get("covered_dates", [])},
        "covered_dates",
    )
    covered_dates = {
        day for day in covered_dates
        if local_day <= day <= local_day + timedelta(days=44)
    }
    candidates = []
    raw_candidates = prior.get("candidates", [])
    if isinstance(raw_candidates, list):
        candidates = [
            dict(candidate)
            for candidate in raw_candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("id"), int)
        ]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    metadata = _read_metadata(cursor)
    newest_cursor = _parse_modified(cursor)
    for item in metadata:
        try:
            incoming = _metadata_candidate(item, local_day)
        except ValueError:
            continue
        existing = by_id.get(incoming["id"])
        if (
            existing is not None
            and existing.get("modified_gmt") == incoming["modified_gmt"]
        ):
            # Keep full-page progress and discovered dates, but always refresh
            # metadata-derived selection fields. Parser migrations deliberately
            # reopen progress while the upstream modified timestamp may stay
            # unchanged.
            incoming["dates"] = existing.get("dates", incoming["dates"])
            incoming["processed_dates"] = existing.get(
                "processed_dates", []
            )
            incoming["detail_checked"] = existing.get(
                "detail_checked", False
            )
        else:
            covered_dates.difference_update(
                _candidate_dates(incoming, "dates")
            )
        by_id[incoming["id"]] = incoming
        modified = _parse_modified(incoming.get("modified_gmt"))
        if modified is not None and (
            newest_cursor is None or modified > newest_cursor
        ):
            newest_cursor = modified

    candidates = _bounded_candidates(list(by_id.values()), local_day)
    start = local_day
    end = local_day + timedelta(days=ROLLING_WINDOW_DAYS - 1)
    horizon = local_day + timedelta(days=44)
    selected = sorted(
        candidates,
        key=lambda candidate: _candidate_priority(
            candidate, start, end, horizon
        ),
    )[:MAX_CANDIDATES]
    selected = [
        candidate
        for candidate in selected
        if _candidate_priority(candidate, start, end, horizon)[0] < 3
    ]
    documents = _read_documents([candidate["id"] for candidate in selected])
    documents_by_id = {
        item.get("id"): item
        for item in documents
        if isinstance(item.get("id"), int)
    }
    sections_by_month: Dict[str, List[Tuple[date, str]]] = {}
    section_lengths: Dict[str, int] = {}
    seen_sections = set()
    admissions_by_month: Dict[str, List[TodoCulturaAdmission]] = {}
    sources_by_month: Dict[str, List[Tuple[str, str]]] = {}
    for candidate in selected:
        item = documents_by_id.get(candidate["id"])
        if item is None:
            raise TodoCulturaError(
                "Todo Cultura detail JSON was invalid",
                code="INVALID",
                description="источник вернул неполные тексты мероприятий",
            )
        content_value = item.get("content")
        if not isinstance(content_value, dict):
            raise TodoCulturaError(
                "Todo Cultura detail JSON was invalid",
                code="INVALID",
                description="источник вернул неполные тексты мероприятий",
            )
        rendered = content_value.get("rendered", "")
        link = item.get("link", "")
        modified = item.get("modified_gmt")
        if (
            not isinstance(rendered, str)
            or not isinstance(link, str)
            or not _allowed_url(link)
            or _parse_modified(modified) is None
        ):
            raise TodoCulturaError(
                "Todo Cultura detail JSON was invalid",
                code="INVALID",
                description="источник вернул неполные тексты мероприятий",
            )
        lines = _plain_lines(rendered)
        attributed = " ".join(lines).casefold()
        candidate["detail_checked"] = True
        if (
            "ayuntamiento de guardamar" not in attributed
            or "agenda municipal" not in attributed
        ):
            continue
        sections = _date_sections(lines, local_day.year, local_day)
        document_admissions = _admissions(rendered, local_day)
        candidate["dates"] = sorted(day.isoformat() for day in sections)
        processed = _candidate_dates(candidate, "processed_dates")
        included = []
        for day, section in sorted(sections.items()):
            if not start <= day <= end or day in processed:
                continue
            month = day.strftime("%Y-%m")
            section_key = (day, hashlib.sha256(
                section.encode("utf-8")
            ).digest())
            if section_key in seen_sections:
                admissions_by_month.setdefault(month, []).extend(
                    document_admissions
                )
                sources_by_month.setdefault(month, []).append((link, modified))
                included.append(day)
                continue
            addition = len(section) + (
                1 if sections_by_month.get(month) else 0
            )
            if section_lengths.get(month, 0) + addition > PROGRAM_TEXT_LIMIT:
                raise TodoCulturaError(
                    "Todo Cultura rolling section was too large",
                    code="DAILY-SIZE",
                    description=(
                        "разделы скользящего окна превысили допустимый размер"
                    ),
                )
            sections_by_month.setdefault(month, []).append((day, section))
            seen_sections.add(section_key)
            section_lengths[month] = section_lengths.get(month, 0) + addition
            admissions_by_month.setdefault(month, []).extend(
                document_admissions
            )
            sources_by_month.setdefault(month, []).append((link, modified))
            included.append(day)
            covered_dates.add(day)
        processed.update(included)
        candidate["processed_dates"] = sorted(day.isoformat() for day in processed)

    programs = []
    for month, dated_sections in sorted(sections_by_month.items()):
        dated_sections = sorted(dated_sections, key=lambda item: item[0])
        text = "\n".join(section for _, section in dated_sections)
        source_values = sources_by_month[month]
        programs.append(TodoCulturaProgram(
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            source_url=source_values[0][0],
            modified=max(value[1] for value in source_values),
            admissions=tuple(dict.fromkeys(admissions_by_month[month])),
            participation=_participation(text),
            dates=tuple(dict.fromkeys(day for day, _ in dated_sections)),
        ))
    state = {
        "parser_version": PARSER_VERSION,
        "cursor_modified_gmt": (
            newest_cursor.isoformat(timespec="seconds")
            if newest_cursor is not None
            else cursor
        ),
        "covered_dates": sorted(day.isoformat() for day in covered_dates),
        "candidates": _bounded_candidates(candidates, local_day),
    }
    return TodoCulturaWindow(tuple(programs), state)


async def fetch_program_window(
    local_day: date,
    prior_state: Optional[Dict[str, Any]] = None,
) -> TodoCulturaWindow:
    """Fetch a bounded incremental rolling window without resident work."""

    return await asyncio.to_thread(_read_program_window, local_day, prior_state)
