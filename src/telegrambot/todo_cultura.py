"""Bounded supplemental text from Todo Cultura Vega Baja."""

import asyncio
import hashlib
import html
import http.client
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple


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
    event_url: str
    price_cents: int


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
        if phone is None or len(contact) > 180:
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
            r"(?:jóvenes|personas)\s+de\s+(\d{1,2})\s+a\s+"
            r"(\d{1,2})\s+años",
            anchor,
            re.IGNORECASE,
        )
        participation_note = (
            f"для молодёжи {age.group(1)}–{age.group(2)} лет"
            if age is not None
            else None
        )
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
            capacity_limited=any(
                phrase in evidence.casefold()
                for phrase in ("plazas limitadas", "aforo limitado")
            ),
            evidence=evidence,
        ))
        if len(result) == 12:
            break
    return tuple(result)


def _allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in API_HOSTS


def _admissions(rendered: str) -> Tuple[TodoCulturaAdmission, ...]:
    """Read explicit prices linked to official Agenda Guardamar events."""

    result = []
    seen = set()
    for paragraph in re.findall(
        r"<p\b[^>]*>(.*?)</p>", rendered, flags=re.IGNORECASE | re.DOTALL
    ):
        plain = " ".join(
            html.unescape(re.sub(r"<[^>]+>", " ", paragraph)).split()
        )
        price_match = re.search(
            r"\bprecio\s+de\s+la\s+entrada\s+es\s+de\s+"
            r"(\d{1,4})(?:[,.](\d{1,2}))?\s+euros?\b",
            plain,
            re.IGNORECASE,
        )
        if price_match is None:
            continue
        euros = int(price_match.group(1))
        cents = int((price_match.group(2) or "0").ljust(2, "0"))
        price_cents = euros * 100 + cents
        if not 0 <= price_cents <= 100_000:
            continue
        for raw_url in re.findall(
            r"href\s*=\s*['\"]([^'\"]+)['\"]", paragraph, re.IGNORECASE
        ):
            event_url = html.unescape(raw_url)
            parsed = urllib.parse.urlparse(event_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {
                    "agendaguardamar.com",
                    "www.agendaguardamar.com",
                }
                or "/espectaculo/" not in parsed.path
                or not parsed.path.endswith(".html")
            ):
                continue
            normalized = urllib.parse.urlunparse(
                parsed._replace(query="", fragment="")
            )
            if normalized not in seen:
                seen.add(normalized)
                result.append(TodoCulturaAdmission(normalized, price_cents))
            break
        if len(result) == 20:
            break
    return tuple(result)


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):
        if not _allowed_url(new_url):
            raise TodoCulturaError(
                "Todo Cultura redirected outside its hosts",
                code="REDIRECT",
                description="источник перенаправил запрос на другой сайт",
            )
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _read_api_payload(url: str, limit: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
    )
    opener = urllib.request.build_opener(_RedirectHandler())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if not _allowed_url(response.geturl()):
                raise TodoCulturaError(
                    "Todo Cultura returned an unexpected redirect",
                    code="REDIRECT",
                    description="получен недопустимый адрес ответа",
                )
            if response.headers.get_content_type() != "application/json":
                raise TodoCulturaError(
                    "Todo Cultura returned non-JSON content",
                    code="CONTENT-TYPE",
                    description="источник вернул данные не в формате JSON",
                )
            payload = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise TodoCulturaError(
            f"Todo Cultura returned HTTP {exc.code}",
            code=f"HTTP-{exc.code}",
            description=f"сервер вернул HTTP {exc.code}",
        ) from exc
    except TodoCulturaError:
        raise
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise TodoCulturaError(
            "Todo Cultura request failed",
            code="NETWORK",
            description="не удалось получить дополнительную программу",
        ) from exc
    if len(payload) > limit:
        raise TodoCulturaError(
            "Todo Cultura response was too large",
            code="TOO-LARGE",
            description="ответ превысил допустимый размер",
        )
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
    hinted = _date_sections(
        _plain_lines(f"{title}\n{excerpt}"),
        reference_date.year,
        reference_date,
    )
    mentioned = _mentioned_dates(
        " ".join(_plain_lines(f"{title}\n{excerpt}")), reference_date
    )
    hinted_dates = set(hinted) | mentioned
    return {
        "id": identifier,
        "modified_gmt": modified,
        "link": link,
        "dates": sorted(day.isoformat() for day in hinted_dates),
        "processed_dates": [],
        "detail_checked": not hinted_dates,
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
) -> Tuple[int, float]:
    dates = _candidate_dates(candidate, "dates")
    processed = _candidate_dates(candidate, "processed_dates")
    if any(start <= day <= end and day not in processed for day in dates):
        rank = 0
    elif not candidate.get("detail_checked") and any(
        start <= day <= horizon for day in dates
    ):
        rank = 1
    elif not candidate.get("detail_checked"):
        rank = 2
    else:
        rank = 3
    modified = _parse_modified(candidate.get("modified_gmt"))
    return rank, -(modified.timestamp() if modified is not None else 0.0)


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
            incoming = existing
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

    for candidate in by_id.values():
        shared = _candidate_dates(candidate, "dates") & covered_dates
        if shared:
            processed = (
                _candidate_dates(candidate, "processed_dates") | shared
            )
            candidate["processed_dates"] = sorted(
                day.isoformat() for day in processed
            )
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
        document_admissions = _admissions(rendered)
        candidate["dates"] = sorted(day.isoformat() for day in sections)
        processed = _candidate_dates(candidate, "processed_dates")
        included = []
        for day, section in sorted(sections.items()):
            if not start <= day <= end or day in processed:
                continue
            month = day.strftime("%Y-%m")
            if day in covered_dates:
                admissions_by_month.setdefault(month, []).extend(
                    document_admissions
                )
                sources_by_month.setdefault(month, []).append((link, modified))
                included.append(day)
                continue
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

    # A newer candidate is processed first. Mark the same covered dates on
    # older candidates as well, so the next run does not download duplicate
    # programme reproductions. A later modified_gmt resets the incoming
    # candidate and intentionally reopens its dates.
    for candidate in candidates:
        shared = _candidate_dates(candidate, "dates") & covered_dates
        if not shared:
            continue
        processed = _candidate_dates(candidate, "processed_dates") | shared
        candidate["processed_dates"] = sorted(
            day.isoformat() for day in processed
        )

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
        "parser_version": 4,
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
