"""Operator-reviewed correction data loaded from one validated file.

`reviewed.json` ships with the package and holds everything a monthly
poster review changes: exact Russian title translations, per-poster
reviewed occurrences with their known-bad OCR title filter, and bounded
day-of schedule rules. The file is validated strictly at load; any
defect rejects the whole file so a bad data commit fails the test suite
instead of silently changing published output.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, time
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from .event_urls import normalize_ticket_url

DATA_PATH = Path(__file__).with_name("reviewed.json")
DATA_VERSION = 1
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MAX_TEXT = 200
# Match and drop terms are substrings, so a very short or blank one selects
# almost every title: a single space in a drop clause empties the whole
# event section, and in a match term it rewrites every event.
_MIN_MATCH_TERM = 3
_SET_FIELDS = {
    "title_es": str,
    "place": str,
    "category": str,
    "start_time": str,
    "end_time": str,
    "ticket_price_cents": int,
    "participation_note": str,
    "registration_contact": str,
    "capacity_limited": bool,
}


class ReviewedDataError(RuntimeError):
    """Raised when the reviewed-data file cannot be trusted."""


@dataclass(frozen=True)
class ReviewedPoster:
    """One poster's reviewed occurrences and its OCR drop filter."""

    upload_path: str
    drop_titles: Tuple[Tuple[str, ...], ...]
    events: Tuple[dict, ...]


@dataclass(frozen=True)
class ScheduleRule:
    """One bounded day-of correction from the official text agenda."""

    match: Tuple[str, ...]
    requires: Dict[str, str]
    weekday_windows: Optional[Dict[str, Optional[Tuple[str, str]]]]
    set_fields: Dict[str, object]


def normalized_title(value: str) -> str:
    """Casefold and unify apostrophes so match terms stay stable."""

    return value.casefold().replace("’", "'")


def _check_keys(
    mapping,
    label: str,
    *,
    required=frozenset(),
    optional=frozenset(),
) -> None:
    """Refuse both a misspelled key and a missing one.

    Every object in this schema goes through here. A typo such as
    `drop_title` would otherwise leave an empty filter, and deleting
    `drop_titles` outright would do the same silently — either way
    republishing OCR rows already judged wrong. An explicit empty list
    stays valid: it states the intent that a typo or deletion cannot.
    """

    present = set(mapping)
    unknown = present - required - optional
    if unknown:
        raise ReviewedDataError(
            f"{label} has unknown fields {sorted(unknown)}"
        )
    missing = required - present
    if missing:
        raise ReviewedDataError(
            f"{label} is missing required fields {sorted(missing)}"
        )


def _reject_duplicate_keys(pairs):
    """Refuse a repeated key, which JSON would resolve to the last one.

    Two `posters` blocks, or one title listed twice, would otherwise load
    quietly with the earlier definition — including its drop filter —
    discarded.
    """

    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r} in reviewed data")
        seen.add(key)
    return dict(pairs)


def _match_term(value, field: str) -> str:
    """Accept only a substring specific enough to select real titles."""

    if (
        not isinstance(value, str)
        or value != value.strip()
        or len(value) < _MIN_MATCH_TERM
        or len(value) > _MAX_TEXT
    ):
        raise ReviewedDataError(
            f"{field} must be a trimmed substring of at least "
            f"{_MIN_MATCH_TERM} characters"
        )
    return value


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_TEXT:
        raise ReviewedDataError(f"{field} must be a bounded string")
    return value


def _time(value, field: str) -> str:
    """Accept only a real wall-clock time, not merely the HH:MM shape."""

    # The pattern rejects impossible values itself because
    # time.fromisoformat accepts "24:00" and silently returns midnight,
    # which would move an end-of-day correction to the start of the day.
    if not isinstance(value, str) or not _TIME_PATTERN.match(value):
        raise ReviewedDataError(f"{field} must be a real zero-padded HH:MM")
    try:
        time.fromisoformat(value)
    except ValueError as exc:
        raise ReviewedDataError(f"{field} is not a real time") from exc
    return value


def _date(value, field: str) -> str:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ReviewedDataError(f"{field} must be an ISO date") from exc
    return value


def _validate_event(entry, index: int) -> dict:
    if not isinstance(entry, dict):
        raise ReviewedDataError(f"poster event {index} must be an object")
    _check_keys(
        entry,
        f"poster event {index}",
        required={"title_es", "start_date", "end_date", "category"},
        optional={
            "start_time", "end_time", "place", "sources",
            "ticket_price_cents", "ticket_url", "participation_note",
            "registration_contact", "capacity_limited",
        },
    )
    _text(entry["title_es"], f"event {index} title_es")
    start = _date(entry["start_date"], f"event {index} start_date")
    end = _date(entry["end_date"], f"event {index} end_date")
    if date.fromisoformat(end) < date.fromisoformat(start):
        # An inverted range matches no day, so the occurrence would simply
        # never appear rather than announcing the mistake.
        raise ReviewedDataError(
            f"event {index} ends before it starts"
        )
    if entry["category"] != "exhibition" and start != end:
        raise ReviewedDataError(
            f"event {index} needs separate dated occurrences"
        )
    for field in ("start_time", "end_time"):
        if entry.get(field) is not None:
            _time(entry[field], f"event {index} {field}")
    if entry.get("place") is not None:
        _text(entry["place"], f"event {index} place")
    _text(entry["category"], f"event {index} category")
    sources = entry.get("sources", [])
    if not isinstance(sources, list) or not all(
        isinstance(source, str) and source for source in sources
    ):
        raise ReviewedDataError(f"event {index} sources must be strings")
    for field in ("participation_note", "registration_contact"):
        if entry.get(field) is not None:
            _text(entry[field], f"event {index} {field}")
    if "capacity_limited" in entry and not isinstance(
        entry["capacity_limited"], bool
    ):
        # A JSON string such as "false" would otherwise render as True.
        raise ReviewedDataError(
            f"event {index} capacity_limited must be a boolean"
        )
    price = entry.get("ticket_price_cents")
    if price is not None and (
        # bool subclasses int, so True would pass a bare isinstance check.
        not isinstance(price, int)
        or isinstance(price, bool)
        or not 0 <= price <= 100_000
    ):
        raise ReviewedDataError(f"event {index} price is implausible")
    ticket_url = entry.get("ticket_url")
    if ticket_url is not None:
        if not isinstance(ticket_url, str):
            raise ReviewedDataError(
                f"event {index} ticket_url is not an approved HTTPS URL"
            )
        if normalize_ticket_url(ticket_url) is None:
            raise ReviewedDataError(
                f"event {index} ticket_url is not an approved HTTPS URL"
            )
    return entry


def _validate_rule(entry, index: int) -> ScheduleRule:
    if not isinstance(entry, dict):
        raise ReviewedDataError(f"schedule rule {index} must be an object")
    _check_keys(
        entry,
        f"schedule rule {index}",
        required={"match", "requires", "set"},
        optional={"weekday_windows"},
    )
    match = entry["match"]
    if not isinstance(match, list) or not match:
        raise ReviewedDataError(f"rule {index} match must list substrings")
    for position, term in enumerate(match):
        _match_term(term, f"rule {index} match[{position}]")

    # An absent guard would let one substring rewrite matching events on
    # every date, so a rule must state what it applies to.
    requires = entry["requires"]
    if not isinstance(requires, dict) or not requires:
        raise ReviewedDataError(
            f"rule {index} requires must name at least one condition"
        )
    for field, value in requires.items():
        if field in {"start_date", "end_date"}:
            if value != "today":
                _date(value, f"rule {index} {field}")
        elif field in {"start_time", "end_time"}:
            _time(value, f"rule {index} {field}")
        else:
            raise ReviewedDataError(f"rule {index} requires unknown {field}")

    windows = entry.get("weekday_windows")
    parsed_windows = None
    if windows is not None:
        if not isinstance(windows, dict) or set(windows) != {
            "weekday", "saturday", "sunday",
        }:
            raise ReviewedDataError(
                f"rule {index} weekday_windows needs weekday/saturday/sunday"
            )
        parsed_windows = {}
        for day, window in windows.items():
            if window is None:
                parsed_windows[day] = None
                continue
            if not isinstance(window, list) or len(window) != 2:
                raise ReviewedDataError(
                    f"rule {index} {day} window must be [start, end]"
                )
            parsed_windows[day] = (
                _time(window[0], f"rule {index} {day} start"),
                _time(window[1], f"rule {index} {day} end"),
            )

    set_fields = entry["set"]
    if not isinstance(set_fields, dict) or not set_fields:
        raise ReviewedDataError(f"rule {index} set must assign fields")
    for field, value in set_fields.items():
        expected = _SET_FIELDS.get(field)
        if expected is None:
            raise ReviewedDataError(f"rule {index} sets unknown {field}")
        if expected is int:
            if not isinstance(value, int) or isinstance(value, bool) or (
                not 0 <= value <= 100_000
            ):
                raise ReviewedDataError(f"rule {index} {field} is invalid")
        elif not isinstance(value, expected):
            raise ReviewedDataError(f"rule {index} {field} has a wrong type")
        if expected is str:
            _text(value, f"rule {index} {field}")
            if field in {"start_time", "end_time"}:
                _time(value, f"rule {index} {field}")

    if parsed_windows is not None and (
        {"start_time", "end_time"} & set(set_fields)
    ):
        # The window is applied after `set`, so keeping both would let the
        # window silently override the hours the rule appears to assign.
        raise ReviewedDataError(
            f"rule {index} cannot set hours and weekday_windows together"
        )

    return ScheduleRule(
        match=tuple(normalized_title(term) for term in match),
        requires=dict(requires),
        weekday_windows=parsed_windows,
        set_fields=dict(set_fields),
    )


def _validate_translations(data) -> Dict[str, str]:
    translations = data.get("translations", {})
    if not isinstance(translations, dict):
        raise ReviewedDataError("translations must be an object")
    for source, translated in translations.items():
        _text(source, "translation key")
        _text(translated, "translation value")
        if source != " ".join(source.split()).strip().casefold():
            raise ReviewedDataError(
                f"translation key is not normalized: {source!r}"
            )
    return dict(translations)


def _validate_posters(data) -> Dict[str, ReviewedPoster]:
    posters = {}
    raw_posters = data.get("posters", {})
    if not isinstance(raw_posters, dict):
        raise ReviewedDataError("posters must be an object")
    for name, poster in raw_posters.items():
        _text(name, "poster name")
        if name != name.casefold():
            raise ReviewedDataError(f"poster name must be casefolded: {name}")
        if not isinstance(poster, dict):
            raise ReviewedDataError(f"poster {name} must be an object")
        _check_keys(
            poster,
            f"poster {name}",
            required={"upload_path", "drop_titles", "events"},
        )
        drop_titles = poster["drop_titles"]
        if not isinstance(drop_titles, list) or not all(
            isinstance(clause, list) and clause for clause in drop_titles
        ):
            raise ReviewedDataError(
                f"poster {name} drop_titles must be substring clauses"
            )
        for clause_index, clause in enumerate(drop_titles):
            for position, term in enumerate(clause):
                _match_term(
                    term,
                    f"poster {name} drop_titles[{clause_index}][{position}]",
                )
        events = poster["events"]
        if not isinstance(events, list):
            raise ReviewedDataError(f"poster {name} events must be a list")
        posters[name] = ReviewedPoster(
            upload_path=_text(
                poster["upload_path"], f"poster {name} upload_path"
            ).casefold(),
            drop_titles=tuple(
                tuple(normalized_title(term) for term in clause)
                for clause in drop_titles
            ),
            events=tuple(
                _validate_event(event, index)
                for index, event in enumerate(events)
            ),
        )
    return posters


def _validate_schedules(data) -> Tuple[ScheduleRule, ...]:
    raw_rules = data.get("schedules", [])
    if not isinstance(raw_rules, list):
        raise ReviewedDataError("schedules must be a list")
    return tuple(
        _validate_rule(rule, index) for index, rule in enumerate(raw_rules)
    )


_SECTIONS = {
    "translations": _validate_translations,
    "posters": _validate_posters,
    "schedules": _validate_schedules,
}


@lru_cache(maxsize=4)
def _load(path: Path):
    """Validate each section independently so one defect stays contained.

    A structural failure still rejects everything, but a defect confined to
    one section must not disable the others — in particular a translation
    typo must never switch off a poster's known-bad-OCR filter.
    """

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, ValueError) as exc:
        raise ReviewedDataError("reviewed data is unreadable") from exc
    if not isinstance(data, dict) or data.get("version") != DATA_VERSION:
        raise ReviewedDataError("reviewed data has an unsupported version")
    # A misspelled or deleted section would otherwise be ignored, silently
    # dropping every correction it was meant to carry.
    _check_keys(
        data,
        "reviewed data",
        required={"version", *_SECTIONS},
    )

    sections = {}
    for name, validate in _SECTIONS.items():
        try:
            sections[name] = validate(data)
        except ReviewedDataError as exc:
            sections[name] = exc
    return sections


def _section(name: str, path: Path):
    value = _load(path)[name]
    if isinstance(value, ReviewedDataError):
        raise value
    return value


def reviewed_translations(path: Path = DATA_PATH) -> Dict[str, str]:
    return _section("translations", path)


def reviewed_poster(
    poster_name: str,
    path: Path = DATA_PATH,
) -> Optional[ReviewedPoster]:
    return _section("posters", path).get(poster_name.casefold())


def schedule_rules(path: Path = DATA_PATH) -> Tuple[ScheduleRule, ...]:
    return _section("schedules", path)
