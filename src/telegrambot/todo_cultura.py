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
from datetime import date
from html.parser import HTMLParser
from typing import List, Optional, Tuple


API_HOSTS = {"todoculturavegabaja.es", "www.todoculturavegabaja.es"}
REQUEST_TIMEOUT_SECONDS = 20
RESPONSE_LIMIT_BYTES = 300_000
PROGRAM_TEXT_LIMIT = 12_000
MAX_CANDIDATES = 3
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
    r"^(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"
    r"\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?$",
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


def _daily_section(lines: List[str], target_date: date) -> str:
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        parsed = _header_date(line, target_date.year)
        if start is None:
            if parsed == target_date:
                start = index
            continue
        if parsed is not None:
            end = index
            break
    if start is None:
        raise TodoCulturaError(
            "Todo Cultura did not contain the requested date",
            code="NO-DATE",
            description="в дополнительной программе нет раздела нужной даты",
        )
    return "\n".join(lines[start:end])


def _date_search(target_date: date) -> str:
    month = next(
        name for name, number in _MONTHS.items() if number == target_date.month
    )
    return f"Guardamar {target_date.day} de {month}"


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


def _read_latest_program(target_date: date) -> TodoCulturaProgram:
    query = urllib.parse.urlencode({
        "search": _date_search(target_date),
        "per_page": MAX_CANDIDATES,
        "orderby": "modified",
        "order": "desc",
        "_fields": "id,modified,link,title,content",
    })
    url = f"{API_URL}?{query}"
    try:
        data = json.loads(_read_api_payload(url, RESPONSE_LIMIT_BYTES))
        if (
            not isinstance(data, list)
            or not 1 <= len(data) <= MAX_CANDIDATES
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TodoCulturaError(
            "Todo Cultura JSON was invalid",
            code="INVALID",
            description="источник вернул неполные данные",
        ) from exc
    candidates = []
    failure_code = "INVALID"
    failure_description = "источник вернул неполные данные"
    for item in data:
        try:
            rendered = item["content"]["rendered"]
            source_url = item["link"]
            modified = item.get("modified")
            title = item.get("title", {}).get("rendered", "")
            if not all(
                isinstance(value, str)
                for value in (rendered, source_url, title)
            ):
                continue
            if not _allowed_url(source_url):
                continue
            parser = _TextParser()
            parser.feed(rendered)
            full_text = html.unescape("".join(parser.parts))
            lines = [" ".join(line.split()) for line in full_text.splitlines()]
            lines = [line for line in lines if line]
            attributed = " ".join(lines).casefold()
            if (
                "ayuntamiento de guardamar" not in attributed
                or "agenda municipal" not in attributed
            ):
                failure_code = "NOT-PROGRAMME"
                failure_description = (
                    "запись не является программой Гуардамара"
                )
                continue
            try:
                text = _daily_section(lines, target_date)
            except TodoCulturaError:
                failure_code = "NO-DATE"
                failure_description = (
                    "в дополнительной программе нет раздела нужной даты"
                )
                continue
            if not 100 <= len(text) <= PROGRAM_TEXT_LIMIT:
                failure_code = "DAILY-SIZE"
                failure_description = (
                    "раздел нужной даты имеет недопустимый размер"
                )
                continue
            candidates.append((
                1,
                TodoCulturaProgram(
                    text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    source_url=source_url,
                    modified=modified if isinstance(modified, str) else None,
                    admissions=_admissions(rendered),
                    participation=_participation(text),
                ),
            ))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    if not candidates:
        raise TodoCulturaError(
            "Todo Cultura candidates had no municipal daily programme",
            code=failure_code,
            description=failure_description,
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


async def fetch_latest_program(target_date: date) -> TodoCulturaProgram:
    """Fetch one bounded date-matched programme record."""

    return await asyncio.to_thread(_read_latest_program, target_date)
