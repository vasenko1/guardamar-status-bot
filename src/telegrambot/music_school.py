"""Bounded programme snapshot for Agrupación Musical de Guardamar.

The linked guide needs only a few seasonal facts from the school's public
WordPress posts.  Keep this deliberately separate from ``am_guardamar.py``:
that module discovers public events and intentionally rejects enrolment/course
posts, while this module does deterministic programme extraction with no LLM.
"""

import asyncio
import json
import re
import urllib.parse
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ._transport import BoundedFetchError, fetch_bounded
from .todo_cultura import _plain_lines

API_URL = "https://amguardamar.es/wp-json/wp/v2/posts"
API_HOST = "amguardamar.es"
POST_LIMIT = 12
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 300_000

SCHOOL_INFO_URL = "https://amguardamar.es/escuela/escuela-musica/"
SCHOOL_SITE_URL = "https://amguardamar.es/"
SCHOOL_MAP_URL = (
    "https://www.google.com/maps/search/?api=1&query="
    "Escuela+de+M%C3%BAsica%2C+C%2F+Mercat+2%2C+Guardamar+del+Segura"
)
SCHOOL_ADDRESS = "C/ Mercat, 2"
SCHOOL_PHONE = "966726044"
SCHOOL_EMAIL = "escuela@amguardamar.es"

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
_SEASON_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b")
_WINDOW_RE = re.compile(
    r"\bdel\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
    r"octubre|noviembre|diciembre)(?:\s+de)?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_UNTIL_RE = re.compile(
    r"\bhasta\s+(?:el\s+)?(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
    r"octubre|noviembre|diciembre)(?:\s+de\s+(20\d{2}))?\b",
    re.IGNORECASE,
)


class MusicSchoolSourceError(RuntimeError):
    """Operator-safe failure from the music-school WordPress source."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if isinstance(href, str):
            self.hrefs.append(href)


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == API_HOST
        and port in {None, 443}
        and parsed.path == "/wp-json/wp/v2/posts"
        and parsed.username is None
        and parsed.password is None
    )


def _request_url() -> str:
    fields = "id,date,modified,link,title,content"
    return API_URL + "?" + urllib.parse.urlencode({
        "per_page": POST_LIMIT,
        "orderby": "modified",
        "order": "desc",
        "_fields": fields,
    })


def _read_posts() -> List[Dict[str, Any]]:
    try:
        payload, _, _ = fetch_bounded(
            _request_url(),
            is_allowed_url=_allowed_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "guardamar-status-bot/1.0",
            },
        )
        value = json.loads(payload.decode("utf-8"))
    except (BoundedFetchError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, BoundedFetchError) else "JSON"
        raise MusicSchoolSourceError(
            "music-school WordPress source is unavailable or invalid",
            code=code,
        ) from exc
    if not isinstance(value, list) or len(value) > POST_LIMIT:
        raise MusicSchoolSourceError(
            "music-school WordPress source returned an invalid post list",
            code="SCHEMA",
        )
    return [item for item in value if isinstance(item, dict)]


def _plain(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "\n".join(_plain_lines(value))


def _post(raw: Mapping[str, Any]) -> Optional[dict]:
    identifier = raw.get("id")
    published = raw.get("date")
    modified = raw.get("modified")
    link = raw.get("link")
    title_value = raw.get("title")
    content_value = raw.get("content")
    if not (
        isinstance(identifier, int)
        and identifier > 0
        and isinstance(published, str)
        and isinstance(modified, str)
        and isinstance(link, str)
        and isinstance(title_value, dict)
        and isinstance(content_value, dict)
    ):
        return None
    try:
        published_day = date.fromisoformat(published[:10])
        parsed_link = urllib.parse.urlsplit(link)
        link_port = parsed_link.port
    except (ValueError, TypeError):
        return None
    if (
        parsed_link.scheme != "https"
        or parsed_link.hostname != API_HOST
        or link_port not in {None, 443}
        or parsed_link.username is not None
        or parsed_link.password is not None
    ):
        return None
    title = _plain(title_value.get("rendered"))
    rendered = content_value.get("rendered")
    text = _plain(rendered)
    if not title or not text:
        return None
    parser = _HrefParser()
    if isinstance(rendered, str):
        parser.feed(rendered)
    return {
        "id": identifier,
        "date": published_day,
        "modified": modified,
        "link": link,
        "title": title,
        "text": f"{title}\n{text}",
        "hrefs": tuple(parser.hrefs),
    }


def _season(text: str) -> Optional[Tuple[int, str]]:
    values = []
    for match in _SEASON_RE.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2))
        if end == start + 1:
            values.append((start, f"{start}/{str(end)[2:]}"))
    return max(values) if values else None


def _windows(text: str) -> Tuple[Tuple[date, date], ...]:
    result = []
    for match in _WINDOW_RE.finditer(text):
        start_day = int(match.group(1))
        end_day = int(match.group(2))
        month = _MONTHS[match.group(3).casefold()]
        year = int(match.group(4))
        try:
            start = date(year, month, start_day)
            end = date(year, month, end_day)
        except ValueError:
            continue
        if start <= end:
            result.append((start, end))
    return tuple(result)


def _extension_end(text: str, default_year: int) -> Optional[date]:
    candidates = []
    for match in _UNTIL_RE.finditer(text):
        day = int(match.group(1))
        month = _MONTHS[match.group(2).casefold()]
        year = int(match.group(3)) if match.group(3) else default_year
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    return max(candidates) if candidates else None


def _forms(hrefs: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    jardin = None
    school = None
    for href in hrefs:
        if not href.startswith("https://cutt.ly/"):
            continue
        marker = href.casefold()
        if "matricula_jm_" in marker:
            jardin = href
        elif "matricula_em_" in marker:
            school = href
    return jardin, school


def _registration(start: date, end: date, url: str) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat(), "url": url}


def _latest_registration(current: Optional[dict], candidate: dict) -> dict:
    if current is None:
        return candidate
    current_end = date.fromisoformat(current["end"])
    candidate_end = date.fromisoformat(candidate["end"])
    return candidate if candidate_end >= current_end else current


def _normalize_posts(raw_posts: List[Dict[str, Any]], now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("music-school observation time must be timezone-aware")
    posts = [item for item in (_post(raw) for raw in raw_posts) if item is not None]
    seasons: Dict[int, dict] = {}
    for post in sorted(posts, key=lambda item: item["date"]):
        season = _season(post["text"])
        if season is None:
            continue
        start_year, label = season
        folded = post["text"].casefold()
        if not any(marker in folded for marker in (
            "matrícula",
            "matricula",
            "jardín musical",
            "jardin musical",
            "lenguaje musical",
            "asignaturas conjuntas",
        )):
            continue
        bucket = seasons.setdefault(start_year, {
            "season": label,
            "schedule_url": None,
            "jardin_registration": None,
            "school_registration": None,
        })
        jardin_form, school_form = _forms(post["hrefs"])
        intervals = _windows(post["text"])

        if "horarios" in folded and "lenguaje musical" in folded:
            if "coro" in folded or "técnica vocal" in folded:
                bucket["schedule_url"] = post["link"]

        if intervals:
            start, end = max(intervals, key=lambda item: item[1])
            if jardin_form is not None:
                bucket["jardin_registration"] = _latest_registration(
                    bucket["jardin_registration"],
                    _registration(start, end, jardin_form),
                )
            if school_form is not None:
                bucket["school_registration"] = _latest_registration(
                    bucket["school_registration"],
                    _registration(start, end, school_form),
                )

        if "jardín musical" in folded and jardin_form is not None:
            extended_end = _extension_end(post["text"], start_year)
            if extended_end is not None:
                previous = bucket["jardin_registration"]
                start = post["date"]
                if previous is not None:
                    previous_start = date.fromisoformat(previous["start"])
                    if previous_start <= extended_end:
                        start = previous_start
                candidate = _registration(start, extended_end, jardin_form)
                bucket["jardin_registration"] = _latest_registration(
                    previous, candidate
                )

    if not seasons:
        raise MusicSchoolSourceError(
            "no current music-school season found in recent posts",
            code="NO-SEASON",
        )
    latest_year = max(seasons)
    current = seasons[latest_year]
    return {
        "observed_at": now.isoformat(),
        "season": current["season"],
        "schedule_url": current["schedule_url"],
        "jardin_registration": current["jardin_registration"],
        "school_registration": current["school_registration"],
    }


async def fetch_music_school_catalog(now: datetime) -> dict:
    """Fetch one bounded recent-post page and normalize the newest school season."""

    raw_posts = await asyncio.to_thread(_read_posts)
    return _normalize_posts(raw_posts, now)


def _https_url(value: Any, *, hosts: Optional[frozenset[str]] = None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    return hosts is None or parsed.hostname in hosts


def _valid_registration(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"start", "end", "url"}:
        return False
    try:
        start = date.fromisoformat(value["start"])
        end = date.fromisoformat(value["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        start <= end
        and _https_url(value.get("url"), hosts=frozenset({"cutt.ly"}))
    )


def valid_music_school_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "observed_at",
        "season",
        "schedule_url",
        "jardin_registration",
        "school_registration",
    }:
        return False
    observed = value.get("observed_at")
    season = value.get("season")
    if not isinstance(observed, str) or not isinstance(season, str):
        return False
    try:
        parsed = datetime.fromisoformat(observed)
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    if not re.fullmatch(r"20\d{2}/\d{2}", season):
        return False
    schedule_url = value.get("schedule_url")
    if schedule_url is not None and not _https_url(
        schedule_url, hosts=frozenset({API_HOST})
    ):
        return False
    return _valid_registration(value.get("jardin_registration")) and _valid_registration(
        value.get("school_registration")
    )


def merge_music_school_catalog(
    previous: Optional[Mapping[str, Any]], current: Mapping[str, Any]
) -> dict:
    """Keep same-season last-good fields when an old post leaves the small window."""

    merged = dict(current)
    if (
        previous is None
        or not valid_music_school_snapshot(previous)
        or previous.get("season") != current.get("season")
    ):
        return merged
    for key in ("schedule_url", "jardin_registration", "school_registration"):
        if merged.get(key) is None and previous.get(key) is not None:
            merged[key] = previous[key]
    return merged


def registration_is_open(
    snapshot: Mapping[str, Any], key: str, local_day: date
) -> bool:
    registration = snapshot.get(key)
    if not isinstance(registration, dict):
        return False
    try:
        start = date.fromisoformat(registration["start"])
        end = date.fromisoformat(registration["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= local_day <= end
