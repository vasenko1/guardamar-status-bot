"""Cheap unattended snapshot for Tertulia Literaria de Guardamar."""

import asyncio
import re
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from ._transport import BoundedFetchError, fetch_bounded

SOURCE_URL = (
    "https://www.bibliotecaspublicas.es/guardamardelsegura/"
    "actividades-programas/Tertulia-Literaria-de-Guardamar.html"
)
HOST = "www.bibliotecaspublicas.es"
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 64 * 1024

_SCHEDULE_RE = re.compile(
    r"todos\s+los\s+martes.*?(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)


class LiteraryGroupSourceError(RuntimeError):
    """Operator-safe failure from the library programme source."""

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
        and parsed.hostname == HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.endswith(
            "/actividades-programas/Tertulia-Literaria-de-Guardamar.html"
        )
    )


def _extract_snapshot(payload: bytes, now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("literary-group observation time must be timezone-aware")
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiteraryGroupSourceError(
            "literary-group HTML is invalid", code="HTML"
        ) from exc
    parser = _TextParser()
    parser.feed(source)
    parser.close()
    text = " ".join(" ".join(parser.parts).split())
    match = _SCHEDULE_RE.search(text)
    if match is None:
        raise LiteraryGroupSourceError(
            "literary-group schedule markers are missing", code="SCHEMA"
        )
    start_time, end_time = match.group(1), match.group(2)
    if start_time >= end_time:
        raise LiteraryGroupSourceError(
            "literary-group schedule is invalid", code="SCHEMA"
        )
    return {
        "observed_at": now.isoformat(),
        "source_url": SOURCE_URL,
        "day": "tuesday",
        "start_time": start_time,
        "end_time": end_time,
    }


async def fetch_literary_group_snapshot(now: datetime) -> dict:
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
        raise LiteraryGroupSourceError(
            "literary-group source request failed", code=exc.code
        ) from exc
    return _extract_snapshot(payload, now)


def valid_literary_group_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "observed_at",
        "source_url",
        "day",
        "start_time",
        "end_time",
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
        and value.get("day") == "tuesday"
        and isinstance(value.get("start_time"), str)
        and isinstance(value.get("end_time"), str)
        and re.fullmatch(r"\d{2}:\d{2}", value["start_time"]) is not None
        and re.fullmatch(r"\d{2}:\d{2}", value["end_time"]) is not None
        and value["start_time"] < value["end_time"]
    )
