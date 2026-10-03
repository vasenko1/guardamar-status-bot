"""Lightweight CONVEGA GR-92 source adapter.

The adapter is deliberately narrow: WordPress REST provides campaign discovery,
announcement facts and one current guided-route landing.  It stores one small
source-specific snapshot that can project both normal Event rows and one-off
registration lifecycle records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import tempfile
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .event_translations import cached_title
from .models import Event


LOGGER = logging.getLogger(__name__)

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/convega_events.json"

API_HOSTS = frozenset({"convega.com", "www.convega.com"})
CATEGORY_ID = 338
CATEGORY_LIMIT = 100
MAX_ANNOUNCEMENTS = 3
LANDING_SLUG = "rutasguiadas-senderodelmediterraneo"
REQUEST_TIMEOUT_SECONDS = 12.0
CATEGORY_LIMIT_BYTES = 64 * 1024
DETAIL_LIMIT_BYTES = 256 * 1024
SNAPSHOT_VERSION = 1
MAX_RECORDS = 16
EVENT_HORIZON_DAYS = 370

REGISTRATION_FULL_ACCESS_NOTE = "места закончились"
REGISTRATION_CLOSED_ACCESS_NOTE = "регистрация закрыта"
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
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_DATE_STAGE_PATTERNS = (
    re.compile(
        r"(?P<day>\d{1,2})\s+de\s+(?P<month>[a-záéíóúñ]+)"
        r"(?P<middle>.{0,220}?)\betapa\s+(?P<stage>\d{1,3})\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\betapa\s+(?P<stage>\d{1,3})\b"
        r"(?P<middle>.{0,220}?)(?P<day>\d{1,2})\s+de\s+"
        r"(?P<month>[a-záéíóúñ]+)",
        re.IGNORECASE | re.DOTALL,
    ),
)
_GUIDED_TITLE = re.compile(r"\brutas?\s+guiadas?\b", re.IGNORECASE)
_GR92 = re.compile(r"\bgr\s*[-–]?\s*92\b", re.IGNORECASE)
_STAGE = re.compile(r"\betapa\s+(\d{1,3})\b", re.IGNORECASE)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_SPANISH_FULL_DATE = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)

_OPEN_PHRASES = (
    "inscripcion",
    "inscripciones",
    "inscribete",
    "ir a inscripcion",
    "reserva tu plaza",
    "reservar plaza",
    "formulario de inscripcion",
    "inscripcion aqui",
    "inscripciones aqui",
    "inscribete aqui",
)
_CTA_PATTERNS = tuple(
    re.compile(rf"^(?:{pattern})$", re.IGNORECASE)
    for pattern in (
        r"inscripci[oó]n",
        r"ir\s+a\s+inscripci[oó]n",
        r"inscr[ií]bete",
        r"reserva(?:r)?\s+(?:tu\s+)?plaza",
        r"formulario\s+de\s+inscripci[oó]n",
        r"inscripciones?\s+aqu[ií]",
        r"inscr[ií]bete\s+aqu[ií]",
    )
)


class ConvegaSourceError(RuntimeError):
    """Operator-safe failure from the approved CONVEGA source slice."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


class _RenderedContentParser(HTMLParser):
    """Keep only structure needed for deterministic text/form/action checks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: List[str] = []
        self.links: List[Dict[str, str]] = []
        self.forms: List[Dict[str, Any]] = []
        self._link: Optional[Dict[str, str]] = None
        self._form: Optional[Dict[str, Any]] = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        values = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "a":
            self._link = {
                "href": values.get("href", ""),
                "text": "",
            }
            self.links.append(self._link)
        elif tag == "form":
            self._form = {
                "has_submit": False,
                "user_fields": 0,
                "text_parts": [],
            }
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            input_type = values.get("type", "text").casefold()
            if input_type == "submit":
                self._form["has_submit"] = True
            elif input_type not in {"hidden", "button", "reset"}:
                self._form["user_fields"] += 1
        elif tag in {"select", "textarea"} and self._form is not None:
            self._form["user_fields"] += 1
        elif tag == "button" and self._form is not None:
            button_type = values.get("type", "").casefold()
            if button_type in {"", "submit"}:
                self._form["has_submit"] = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a":
            self._link = None
        elif tag == "form":
            self._form = None
        elif tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._form is not None:
            self._form["text_parts"].append(value)
        if self._link is not None:
            self._link["text"] = (
                f"{self._link['text']} {value}".strip()
            )

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def _parse_rendered(value: Any) -> _RenderedContentParser:
    if not isinstance(value, str):
        raise ConvegaSourceError("CONVEGA rendered content is missing")
    parser = _RenderedContentParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise ConvegaSourceError("CONVEGA rendered content is invalid") from exc
    return parser


def _allowed_api_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in API_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path.startswith("/wp-json/wp/v2/")
    )


def _valid_public_url(candidate: Any) -> Optional[str]:
    if not isinstance(candidate, str) or candidate != candidate.strip():
        return None
    if any(ord(character) < 32 for character in candidate):
        return None
    try:
        parsed = urllib.parse.urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in API_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path
    ):
        return None
    return urllib.parse.urlunsplit(parsed._replace(fragment=""))


def _valid_registration_action_url(candidate: Any) -> Optional[str]:
    if not isinstance(candidate, str) or candidate != candidate.strip():
        return None
    if any(ord(character) < 32 for character in candidate):
        return None
    try:
        parsed = urllib.parse.urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {
            "convega.com",
            "www.convega.com",
            "convega.empleactiva.com",
        }
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path
        or parsed.path == "/"
    ):
        return None
    return urllib.parse.urlunsplit(parsed._replace(fragment=""))


def _read_json(url: str, *, limit_bytes: int) -> Any:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed_api_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=limit_bytes,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
        return json.loads(payload.decode("utf-8"))
    except BoundedFetchError as exc:
        raise ConvegaSourceError(
            "CONVEGA REST request failed",
            code=exc.code,
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConvegaSourceError(
            "CONVEGA REST returned invalid JSON",
            code="JSON",
        ) from exc


def _category_url() -> str:
    query = urllib.parse.urlencode({
        "categories": CATEGORY_ID,
        "per_page": CATEGORY_LIMIT,
        "order": "desc",
        "orderby": "date",
        "_fields": "id,date,modified,slug,link,title",
    })
    return f"https://convega.com/wp-json/wp/v2/posts?{query}"


def _post_url(identifier: int) -> str:
    query = urllib.parse.urlencode({
        "_fields": "id,date,modified,slug,link,title,content",
    })
    return f"https://convega.com/wp-json/wp/v2/posts/{identifier}?{query}"


def _landing_url() -> str:
    query = urllib.parse.urlencode({
        "slug": LANDING_SLUG,
        "_fields": "id,date,modified,slug,link,title,content",
    })
    return f"https://convega.com/wp-json/wp/v2/pages?{query}"


def _title_text(raw: Mapping[str, Any]) -> str:
    title = raw.get("title")
    if not isinstance(title, Mapping):
        return ""
    rendered = title.get("rendered")
    if not isinstance(rendered, str):
        return ""
    parser = _parse_rendered(rendered)
    return " ".join(parser.text.split())


def _guided_metadata(value: Any) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) > CATEGORY_LIMIT:
        raise ConvegaSourceError("CONVEGA Senderismo index is invalid")
    candidates = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("id")
        title = _title_text(raw)
        slug = raw.get("slug")
        link = _valid_public_url(raw.get("link"))
        if (
            not isinstance(identifier, int)
            or identifier <= 0
            or not isinstance(slug, str)
            or link is None
            or not title
        ):
            continue
        haystack = f"{title} {slug}"
        if _GUIDED_TITLE.search(haystack) and _GR92.search(haystack):
            candidates.append({
                "id": identifier,
                "date": raw.get("date"),
                "modified": raw.get("modified"),
                "slug": slug,
                "link": link,
                "title": title,
            })
    return tuple(candidates[:MAX_ANNOUNCEMENTS])


def _infer_event_date(day: int, month: int, published: date) -> Optional[date]:
    for year in (published.year, published.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if published - timedelta(days=30) <= candidate <= published + timedelta(days=370):
            return candidate
    return None


def _sentence_occurrences(text: str, published: date) -> Tuple[Dict[str, Any], ...]:
    sentences = [
        " ".join(value.split())
        for value in re.split(r"(?<=[.!?])\s+|\n+", text)
        if value.strip()
    ]
    found: Dict[Tuple[int, date], Dict[str, Any]] = {}
    for sentence in sentences:
        folded_sentence = _fold(sentence)
        for pattern in _DATE_STAGE_PATTERNS:
            for match in pattern.finditer(sentence):
                month = _MONTHS.get(_fold(match.group("month")))
                if month is None:
                    continue
                event_day = _infer_event_date(
                    int(match.group("day")),
                    month,
                    published,
                )
                stage = int(match.group("stage"))
                if event_day is None or stage <= 0:
                    continue
                key = (stage, event_day)
                relevant = "guardamar" in folded_sentence
                existing = found.get(key)
                if existing is None or (relevant and not existing["guardamar_relevant"]):
                    found[key] = {
                        "stage": stage,
                        "event_start_date": event_day,
                        "guardamar_relevant": relevant,
                        "sentence": sentence,
                    }
    return tuple(found[key] for key in sorted(found, key=lambda item: (item[1], item[0])))


def _parse_post(raw: Any, now: datetime) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(raw, dict):
        raise ConvegaSourceError("CONVEGA announcement is invalid")
    identifier = raw.get("id")
    if not isinstance(identifier, int) or identifier <= 0:
        raise ConvegaSourceError("CONVEGA announcement ID is invalid")
    source_url = _valid_public_url(raw.get("link"))
    published_raw = raw.get("date")
    content = raw.get("content")
    if (
        source_url is None
        or not isinstance(published_raw, str)
        or not isinstance(content, Mapping)
    ):
        raise ConvegaSourceError("CONVEGA announcement fields are invalid")
    try:
        published = datetime.fromisoformat(published_raw).date()
    except ValueError as exc:
        raise ConvegaSourceError("CONVEGA announcement date is invalid") from exc
    parser = _parse_rendered(content.get("rendered"))
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    occurrences = _sentence_occurrences(parser.text, published)
    if not occurrences:
        raise ConvegaSourceError("CONVEGA announcement has no usable GR-92 occurrences")
    records = []
    for occurrence in occurrences:
        event_day = occurrence["event_start_date"]
        if not (
            local_day - timedelta(days=30)
            <= event_day
            <= local_day + timedelta(days=EVENT_HORIZON_DAYS)
        ):
            continue
        stage = occurrence["stage"]
        relevant = occurrence["guardamar_relevant"]
        route = None
        records.append({
            "record_id": f"convega:post-{identifier}:stage-{stage}",
            "source": "convega",
            "source_post_id": identifier,
            "source_url": source_url,
            "landing_url": None,
            "title": f"Ruta guiada GR-92 · Etapa {stage}",
            "stage": stage,
            "event_start_date": event_day.isoformat(),
            "event_end_date": None,
            "place": "Guardamar del Segura" if relevant else None,
            "route": route,
            "guardamar_relevant": relevant,
            "registration_start_date": None,
            "registration_start_time": None,
            "registration_end_date": None,
            "registration_end_time": None,
            "observed_status": "unknown",
            "until_full": False,
            "registration_url": None,
            "registration_contact": None,
        })
    return tuple(records)


def _landing_identity(parser: _RenderedContentParser) -> Optional[Tuple[int, date]]:
    stages = {int(value) for value in _STAGE.findall(parser.text)}
    dates = {
        candidate
        for day, month, year in _NUMERIC_DATE.findall(parser.text)
        if (candidate := _safe_date(int(year), int(month), int(day))) is not None
    }
    for day, month_name, year in _SPANISH_FULL_DATE.findall(parser.text):
        month = _MONTHS.get(_fold(month_name))
        if month is None:
            continue
        candidate = _safe_date(int(year), month, int(day))
        if candidate is not None:
            dates.add(candidate)
    if len(stages) != 1 or len(dates) != 1:
        return None
    return next(iter(stages)), next(iter(dates))


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _explicit_registration_cta(
    parser: _RenderedContentParser,
    canonical_url: str,
) -> Optional[str]:
    for link in parser.links:
        label = " ".join(link.get("text", "").split())
        if not label:
            continue
        if not any(pattern.fullmatch(label) for pattern in _CTA_PATTERNS):
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        action = _valid_registration_action_url(
            urllib.parse.urljoin(canonical_url, href)
        )
        if action is not None:
            return action
    return None


def _form_has_registration_semantics(form: Mapping[str, Any]) -> bool:
    parts = form.get("text_parts")
    if not isinstance(parts, list):
        return False
    accepted = frozenset(_OPEN_PHRASES)
    return any(
        isinstance(part, str) and _fold(" ".join(part.split())) in accepted
        for part in parts
    )


def _landing_state(
    parser: _RenderedContentParser,
    canonical_url: str,
) -> Tuple[str, Optional[str], bool]:
    folded = _fold(parser.text)
    if re.search(r"\bplazas\s+agotadas\b", folded):
        return "full", None, True

    cta = _explicit_registration_cta(parser, canonical_url)
    if cta is not None:
        return "open", cta, False

    if any(
        bool(form.get("has_submit"))
        and int(form.get("user_fields", 0)) >= 2
        and _form_has_registration_semantics(form)
        for form in parser.forms
    ):
        return "open", canonical_url, False

    return "unknown", None, False


def _apply_landing(
    records: Sequence[Dict[str, Any]],
    value: Any,
) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) != 1:
        return tuple(dict(record) for record in records)
    page = value[0]
    if not isinstance(page, dict) or page.get("slug") != LANDING_SLUG:
        return tuple(dict(record) for record in records)
    canonical_url = _valid_public_url(page.get("link"))
    content = page.get("content")
    if canonical_url is None or not isinstance(content, Mapping):
        return tuple(dict(record) for record in records)
    try:
        parser = _parse_rendered(content.get("rendered"))
    except ConvegaSourceError:
        return tuple(dict(record) for record in records)
    identity = _landing_identity(parser)
    if identity is None:
        return tuple(dict(record) for record in records)
    stage, event_day = identity
    matches = [
        index
        for index, record in enumerate(records)
        if record.get("stage") == stage
        and record.get("event_start_date") == event_day.isoformat()
    ]
    if len(matches) != 1:
        return tuple(dict(record) for record in records)
    status, action_url, until_full = _landing_state(parser, canonical_url)
    result = [dict(record) for record in records]
    index = matches[0]
    result[index] = {
        **result[index],
        "landing_url": canonical_url,
        "observed_status": status,
        "until_full": until_full or bool(result[index].get("until_full")),
        "registration_url": action_url,
    }
    return tuple(result)


def parse_convega_payloads(
    category_value: Any,
    details_by_id: Mapping[int, Any],
    landing_value: Any,
    now: datetime,
) -> Dict[str, Any]:
    """Build one normalized snapshot from already fetched REST payloads."""

    metadata = _guided_metadata(category_value)
    if not metadata:
        raise ConvegaSourceError("CONVEGA has no guided GR-92 announcement candidate")
    records: List[Dict[str, Any]] = []
    for item in metadata:
        detail = details_by_id.get(item["id"])
        if detail is None:
            raise ConvegaSourceError("CONVEGA guided announcement detail is missing")
        records.extend(_parse_post(detail, now))
    if len(records) > MAX_RECORDS:
        raise ConvegaSourceError("CONVEGA produced an invalid occurrence count")

    unique = {}
    for record in records:
        identifier = record["record_id"]
        if identifier in unique and unique[identifier] != record:
            raise ConvegaSourceError("CONVEGA occurrence identity is ambiguous")
        unique[identifier] = record
    normalized = _apply_landing(
        tuple(unique[key] for key in sorted(unique)),
        landing_value,
    )
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "observed_at": now.astimezone(GUARDAMAR_TIMEZONE).isoformat(),
        "records": list(normalized),
    }
    if not valid_convega_snapshot(snapshot):
        raise ConvegaSourceError("CONVEGA normalized snapshot is invalid")
    return snapshot


def valid_convega_snapshot(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "version", "observed_at", "records"
    }:
        return False
    if value.get("version") != SNAPSHOT_VERSION:
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
    except (TypeError, ValueError, KeyError):
        return False
    if observed.tzinfo is None:
        return False
    records = value.get("records")
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        return False
    required = {
        "record_id", "source", "source_post_id", "source_url", "landing_url",
        "title", "stage", "event_start_date", "event_end_date", "place",
        "route", "guardamar_relevant", "registration_start_date",
        "registration_start_time", "registration_end_date",
        "registration_end_time", "observed_status", "until_full",
        "registration_url", "registration_contact",
    }
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != required:
            return False
        if (
            not isinstance(record["record_id"], str)
            or not record["record_id"]
            or record["record_id"] in seen
            or record["source"] != "convega"
            or not isinstance(record["source_post_id"], int)
            or record["source_post_id"] <= 0
            or _valid_public_url(record["source_url"]) is None
            or not isinstance(record["title"], str)
            or not record["title"]
            or not isinstance(record["stage"], int)
            or record["stage"] <= 0
            or not isinstance(record["guardamar_relevant"], bool)
            or record["observed_status"] not in {
                "unknown", "open", "full", "closed"
            }
            or not isinstance(record["until_full"], bool)
        ):
            return False
        seen.add(record["record_id"])
        try:
            start = date.fromisoformat(record["event_start_date"])
        except (TypeError, ValueError):
            return False
        end_raw = record["event_end_date"]
        if end_raw is not None:
            try:
                end = date.fromisoformat(end_raw)
            except (TypeError, ValueError):
                return False
            if end < start:
                return False
        for field in (
            "landing_url", "place", "route", "registration_start_date",
            "registration_start_time", "registration_end_date",
            "registration_end_time", "registration_url",
            "registration_contact",
        ):
            if record[field] is not None and not isinstance(record[field], str):
                return False
        if (
            record["landing_url"] is not None
            and _valid_public_url(record["landing_url"]) is None
        ):
            return False
        if (
            record["registration_url"] is not None
            and _valid_registration_action_url(record["registration_url"]) is None
            and _valid_public_url(record["registration_url"]) is None
        ):
            return False
        for field in ("registration_start_date", "registration_end_date"):
            if record[field] is not None:
                try:
                    date.fromisoformat(record[field])
                except ValueError:
                    return False
    return True


def _load_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConvegaSourceError("CONVEGA local snapshot is invalid") from exc
    if not valid_convega_snapshot(value):
        raise ConvegaSourceError("CONVEGA local snapshot is invalid")
    return value


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


async def fetch_convega_snapshot(now: datetime) -> Dict[str, Any]:
    category = await asyncio.to_thread(
        _read_json, _category_url(), limit_bytes=CATEGORY_LIMIT_BYTES
    )
    metadata = _guided_metadata(category)
    if not metadata:
        raise ConvegaSourceError("CONVEGA has no guided GR-92 announcement candidate")
    details: Dict[int, Any] = {}
    for item in metadata:
        details[item["id"]] = await asyncio.to_thread(
            _read_json,
            _post_url(item["id"]),
            limit_bytes=DETAIL_LIMIT_BYTES,
        )
    landing = await asyncio.to_thread(
        _read_json,
        _landing_url(),
        limit_bytes=DETAIL_LIMIT_BYTES,
    )
    return parse_convega_payloads(category, details, landing, now)


async def refresh_convega_catalog(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> Tuple[Dict[str, Any], ...]:
    """Refresh CONVEGA once and preserve the last-good snapshot on failure."""

    previous = None
    try:
        previous = await asyncio.to_thread(_load_snapshot, state_path)
    except ConvegaSourceError as exc:
        LOGGER.warning("CONVEGA local snapshot ignored: %s", exc)

    try:
        current = await fetch_convega_snapshot(now)
    except ConvegaSourceError:
        if previous is None:
            raise
        LOGGER.warning("CONVEGA source unavailable; preserving last-good snapshot")
        return tuple(previous["records"])

    await asyncio.to_thread(_atomic_write, state_path, current)
    return tuple(current["records"])


async def load_convega_records(
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> Tuple[Dict[str, Any], ...]:
    snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    return tuple(snapshot["records"]) if snapshot is not None else ()


async def convega_snapshot_observed_at(
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> Optional[datetime]:
    snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    if snapshot is None:
        return None
    return datetime.fromisoformat(snapshot["observed_at"])


def _event_for_day(
    raw: Mapping[str, Any],
    local_day: date,
    translation_cache_path: Path,
) -> Optional[Event]:
    if not raw.get("guardamar_relevant"):
        return None
    try:
        start = date.fromisoformat(raw["event_start_date"])
    except (KeyError, TypeError, ValueError):
        return None
    end = start
    if raw.get("event_end_date") is not None:
        try:
            end = date.fromisoformat(raw["event_end_date"])
        except (TypeError, ValueError):
            return None
    if not start <= local_day <= end:
        return None
    status = raw.get("observed_status")
    access_note = (
        REGISTRATION_FULL_ACCESS_NOTE
        if status == "full"
        else REGISTRATION_CLOSED_ACCESS_NOTE
        if status == "closed"
        else None
    )
    registration_url = (
        raw.get("registration_url") if status == "open" else None
    )
    return Event(
        title=cached_title(
            translation_cache_path,
            "convega",
            raw["title"],
        ),
        starts_at=None,
        place=raw.get("place"),
        route=raw.get("route"),
        access_note=access_note,
        registration_url=registration_url,
        capacity_limited=bool(raw.get("until_full")),
        active_from=start if end != start else None,
        active_until=end if end != start else None,
        is_final_day=end != start and local_day == end,
    )


async def fetch_today_convega_events(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
    translation_cache_path: Path = Path("state/event_translations.json"),
) -> Tuple[Event, ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    result = []
    for raw in await load_convega_records(state_path):
        event = _event_for_day(raw, local_day, translation_cache_path)
        if event is not None:
            result.append(event)
    return tuple(result)


async def convega_translation_items(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> Tuple[Tuple[str, str], ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    result = []
    for raw in await load_convega_records(state_path):
        if not raw.get("guardamar_relevant"):
            continue
        try:
            event_day = date.fromisoformat(raw["event_start_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if event_day >= local_day:
            result.append(("convega", raw["title"]))
    return tuple(result)


def convega_snapshot_is_fresh_today(
    now: datetime,
    state_path: Path = Path(DEFAULT_STATE_PATH),
) -> bool:
    try:
        snapshot = _load_snapshot(state_path)
    except ConvegaSourceError:
        return False
    if snapshot is None:
        return False
    observed = datetime.fromisoformat(snapshot["observed_at"])
    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    local_observed = observed.astimezone(GUARDAMAR_TIMEZONE)
    return (
        local_observed.date() == local_now.date()
        and local_observed <= local_now
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CONVEGA GR-92 source sync")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("sync", "fresh-today"),
        default="sync",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    state_path = Path(os.environ.get("CONVEGA_STATE_PATH", DEFAULT_STATE_PATH))
    now = datetime.now(GUARDAMAR_TIMEZONE)
    if args.command == "fresh-today":
        raise SystemExit(
            0 if convega_snapshot_is_fresh_today(now, state_path) else 1
        )
    try:
        records = asyncio.run(refresh_convega_catalog(now, state_path))
    except ConvegaSourceError as exc:
        print(
            f"Command failed [CONVEGA-{exc.diagnostic_code}]: {exc}",
            file=os.sys.stderr,
        )
        raise SystemExit(2) from exc
    logging.info("CONVEGA catalog synchronized: %d records", len(records))


if __name__ == "__main__":
    main()
