"""Small aggregate sports-event catalogue for the linked Guardamar guide.

This module is deliberately not a generic provider framework. It combines the
two currently approved source-specific snapshots, preserves last-good data per
source when one source fails, and formats one aggregate resident-facing card.
"""

import html
import logging
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence

from .branding import with_footer
from .facv import FacvSourceError, fetch_facv_snapshot, valid_facv_snapshot
from .pesca_cv import (
    PescaCvSourceError,
    fetch_pesca_cv_snapshot,
    valid_pesca_cv_snapshot,
)

_MAX_VISIBLE_EVENTS = 12


class SportsEventsSourceError(RuntimeError):
    """No usable current or last-good sports-event source remains."""


def valid_sports_events_catalog(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not set(value).issubset({"observed_at", "facv", "pesca_cv"}):
        return False
    if "observed_at" not in value:
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
    except (TypeError, ValueError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    if "facv" in value and not valid_facv_snapshot(value["facv"]):
        return False
    if "pesca_cv" in value and not valid_pesca_cv_snapshot(value["pesca_cv"]):
        return False
    return "facv" in value or "pesca_cv" in value


async def refresh_sports_events_catalog(
    previous: Optional[Mapping[str, Any]], now: datetime
) -> dict:
    """Read both approved sources once, retaining each source independently."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("sports-event observation time must be timezone-aware")
    prior = (
        dict(previous)
        if previous is not None and valid_sports_events_catalog(previous)
        else {}
    )
    result: dict[str, Any] = {"observed_at": now.isoformat()}
    successful = False

    try:
        result["facv"] = await fetch_facv_snapshot(now)
        successful = True
    except FacvSourceError as exc:
        logging.warning("FACV sports events deferred [FACV-%s]", exc.diagnostic_code)
        if "facv" in prior:
            result["facv"] = prior["facv"]

    try:
        result["pesca_cv"] = await fetch_pesca_cv_snapshot(now)
        successful = True
    except PescaCvSourceError as exc:
        logging.warning("Pesca CV sports events deferred [PESCA-%s]", exc.diagnostic_code)
        if "pesca_cv" in prior:
            result["pesca_cv"] = prior["pesca_cv"]

    if not successful:
        if prior:
            # Do not pretend stale last-good data was freshly observed today.
            return prior
        raise SportsEventsSourceError("sports-event sources are unavailable")
    if not valid_sports_events_catalog(result):
        raise SportsEventsSourceError("sports-event catalogue is invalid")
    return result


def current_sports_events(
    catalog: Optional[Mapping[str, Any]], local_day: date
) -> tuple[dict, ...]:
    """Return the compact current/future event set used by the guide card."""

    if catalog is None or not valid_sports_events_catalog(catalog):
        return ()
    result = []
    seen = set()
    for source_name in ("facv", "pesca_cv"):
        snapshot = catalog.get(source_name)
        if not isinstance(snapshot, dict):
            continue
        for raw in snapshot.get("events", ()):
            try:
                start = date.fromisoformat(raw["start"])
                end = date.fromisoformat(raw["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end < local_day:
                continue
            identity = (
                raw.get("sport"),
                raw.get("title"),
                start,
                end,
                raw.get("place"),
            )
            if identity in seen:
                continue
            seen.add(identity)
            event = {
                "sport": raw["sport"],
                "title": raw["title"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "place": raw["place"],
                "source_url": raw["source_url"],
            }
            level = raw.get("level")
            if isinstance(level, str) and level:
                event["level"] = level
            result.append(event)
    result.sort(key=lambda item: (item["start"], item["title"].casefold()))
    return tuple(result[:_MAX_VISIBLE_EVENTS])


_RU_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _date_label(value: date, *, include_year: bool = True) -> str:
    suffix = f" {value.year}" if include_year else ""
    return f"{value.day} {_RU_MONTHS[value.month]}{suffix}"


def _period_label(start_value: str, end_value: str) -> str:
    start = date.fromisoformat(start_value)
    end = date.fromisoformat(end_value)
    if start == end:
        return _date_label(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {_RU_MONTHS[start.month]} {start.year}"
    if start.year == end.year:
        return f"{_date_label(start, include_year=False)} — {_date_label(end)}"
    return f"{_date_label(start)} — {_date_label(end)}"


def build_sports_events_card(
    events: Sequence[Mapping[str, Any]] = (),
    root_link: Optional[str] = None,
) -> str:
    """Render one durable aggregate card; clubs remain provenance, not navigation."""

    lines = ["🏆 <b>Спортивные мероприятия</b>"]
    if not events:
        lines.extend(
            [
                "",
                "Сейчас ближайшие мероприятия из подключённых официальных "
                "источников не опубликованы.",
            ]
        )
    else:
        for event in events:
            emoji = "♟" if event.get("sport") == "chess" else "🎣"
            lines.extend(
                [
                    "",
                    f"{emoji} <b>{html.escape(str(event['title']))}</b>",
                    f"🗓 {_period_label(str(event['start']), str(event['end']))}",
                    f"📍 {html.escape(str(event['place']))}",
                ]
            )
            level = event.get("level")
            if isinstance(level, str) and level:
                lines.append(f"🏅 {html.escape(level.capitalize())}")
            source_url = html.escape(str(event["source_url"]), quote=True)
            lines.append(f'🔎 <a href="{source_url}">Источник и подробности</a>')
    target = "<b>Полезное о Гуардамаре</b>"
    if root_link is not None:
        target = (
            f'<a href="{html.escape(root_link, quote=True)}">'
            "<b>Полезное о Гуардамаре</b></a>"
        )
    return with_footer("\n".join(lines) + f"\n\n⬅️ {target}")
