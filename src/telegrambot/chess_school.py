"""Cheap unattended snapshot for the Guardamar chess school."""

import asyncio
import re
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from ._transport import BoundedFetchError, fetch_bounded

SOURCE_URL = "https://ajedrezdamadeguardamar.com/cuotas/"
_ALLOWED_HOSTS = frozenset({
    "ajedrezdamadeguardamar.com",
    "www.ajedrezdamadeguardamar.com",
})
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 128 * 1024

_SCHOOL_RE = re.compile(r"\bESCUELA\s+DE\s+AJEDREZ\b", re.IGNORECASE)
_SCHEDULE_RE = re.compile(
    r"(?:todos\s+los\s+)?martes\s+y\s+jueves.*?"
    r"(\d{1,2}:\d{2})\s+a\s+(\d{1,2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)
_LEVELS_RE = re.compile(
    r"niveles?\s*:\s*([A-ZÁÉÍÓÚÜÑ]+)\s*[–—-]\s*([A-ZÁÉÍÓÚÜÑ]+)",
    re.IGNORECASE,
)


class ChessSchoolSourceError(RuntimeError):
    """Operator-safe failure from the chess-school source."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") == "/cuotas"
    )


def _plain(payload: bytes) -> str:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChessSchoolSourceError(
            "chess-school HTML is invalid", code="HTML"
        ) from exc
    parser = _TextParser()
    parser.feed(source)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _extract_snapshot(payload: bytes, now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("chess-school observation time must be timezone-aware")
    text = _plain(payload)
    schedule = _SCHEDULE_RE.search(text)
    levels = _LEVELS_RE.search(text)
    if _SCHOOL_RE.search(text) is None or schedule is None or levels is None:
        raise ChessSchoolSourceError(
            "chess-school schedule markers are missing", code="SCHEMA"
        )
    start_time, end_time = schedule.group(1), schedule.group(2)
    if start_time >= end_time:
        raise ChessSchoolSourceError(
            "chess-school schedule is invalid", code="SCHEMA"
        )
    return {
        "observed_at": now.isoformat(),
        "source_url": SOURCE_URL,
        "days": ["tuesday", "thursday"],
        "start_time": start_time,
        "end_time": end_time,
        "level_from": levels.group(1).upper(),
        "level_to": levels.group(2).upper(),
    }


async def fetch_chess_school_snapshot(now: datetime) -> dict:
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            SOURCE_URL,
            is_allowed_url=_allowed_url,
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "guardamar-status-bot/1.0",
            },
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
        )
    except BoundedFetchError as exc:
        raise ChessSchoolSourceError(
            "chess-school source request failed", code=exc.code
        ) from exc
    return _extract_snapshot(payload, now)


def valid_chess_school_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "observed_at",
        "source_url",
        "days",
        "start_time",
        "end_time",
        "level_from",
        "level_to",
    }:
        return False
    observed = value.get("observed_at")
    if not isinstance(observed, str):
        return False
    try:
        parsed = datetime.fromisoformat(observed)
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return (
        value.get("source_url") == SOURCE_URL
        and value.get("days") == ["tuesday", "thursday"]
        and isinstance(value.get("start_time"), str)
        and isinstance(value.get("end_time"), str)
        and re.fullmatch(r"\d{2}:\d{2}", value["start_time"]) is not None
        and re.fullmatch(r"\d{2}:\d{2}", value["end_time"]) is not None
        and value["start_time"] < value["end_time"]
        and isinstance(value.get("level_from"), str)
        and bool(value["level_from"])
        and isinstance(value.get("level_to"), str)
        and bool(value["level_to"])
    )
