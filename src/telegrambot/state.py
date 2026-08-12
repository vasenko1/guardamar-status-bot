"""Minimal successful-publication state for one-shot digest runs."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterator, Optional

from .models import BeachStatus


class StateError(RuntimeError):
    """Raised when publication state cannot be trusted or saved."""


class PublicationState:
    """Store the minimal identifiers needed for safe daily replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("publication state is unreadable") from exc
        if not isinstance(value, dict):
            raise StateError("publication state has an invalid structure")

        return value

    def last_successful_date(self) -> Optional[date]:
        value = self._read()
        if not value:
            return None
        raw_date = value.get("last_successful_date")
        if raw_date is None:
            if set(value) == {"electricity_explanation_message_id"}:
                return None
            raise StateError("publication state has an invalid structure")
        if not isinstance(raw_date, str):
            raise StateError("publication state has an invalid date")
        try:
            return date.fromisoformat(raw_date)
        except ValueError as exc:
            raise StateError("publication state has an invalid date") from exc

    def is_published(self, local_day: date) -> bool:
        return self.last_successful_date() == local_day

    def electricity_explanation_message_id(self) -> Optional[int]:
        value = self._read()
        message_id = value.get("electricity_explanation_message_id")
        if message_id is None:
            return None
        if not isinstance(message_id, int) or message_id <= 0:
            raise StateError(
                "publication state has an invalid electricity anchor"
            )
        return message_id

    def mark_electricity_published(self, local_day: date) -> None:
        value = {
            "last_successful_date": local_day.isoformat(),
        }
        anchor_id = self.electricity_explanation_message_id()
        if anchor_id is not None:
            value["electricity_explanation_message_id"] = anchor_id
        self._write(value)

    def mark_electricity_explanation(self, message_id: int) -> None:
        if not isinstance(message_id, int) or message_id <= 0:
            raise StateError("electricity anchor message ID is invalid")
        value = self._read()
        value["electricity_explanation_message_id"] = message_id
        self._write(value)

    def morning_record(self, local_day: date) -> Optional[dict]:
        value = self._read()
        if value.get("local_date") != local_day.isoformat():
            return None
        message_id = value.get("morning_message_id")
        published_at = value.get("morning_published_at")
        if not isinstance(message_id, int) or not isinstance(
            published_at, str
        ):
            raise StateError("publication state has an invalid morning record")
        try:
            parsed_time = datetime.fromisoformat(published_at)
        except ValueError as exc:
            raise StateError(
                "publication state has an invalid publication time"
            ) from exc
        if parsed_time.tzinfo is None:
            raise StateError(
                "publication state has an invalid publication time"
            )
        return value

    def mark_morning(
        self,
        local_day: date,
        message_id: int,
        published_at: datetime,
    ) -> None:
        self._write({
            "last_successful_date": local_day.isoformat(),
            "local_date": local_day.isoformat(),
            "morning_message_id": message_id,
            "morning_published_at": published_at.isoformat(),
            "update_message_id": None,
            "morning_deleted": False,
        })

    def mark_update_sent(
        self,
        local_day: date,
        message_id: int,
        beach_status: Optional[BeachStatus] = None,
    ) -> None:
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["update_message_id"] = message_id
        value.pop("beach_candidate", None)
        if beach_status is not None:
            jellyfish = dict(beach_status.jellyfish_states)
            value["beach_baseline"] = {
                name: {
                    "flag": color,
                    "jellyfish": jellyfish.get(name),
                }
                for name, color in beach_status.nearby_flags
            }
        self._write(value)

    def remember_beach_candidate(
        self,
        local_day: date,
        status: BeachStatus,
        observed_at: datetime,
    ) -> bool:
        """Keep one whole best SafeBeach response for the final attempt."""

        if (
            observed_at.tzinfo is None
            or observed_at.date() != local_day
            or status.source_date != local_day
            or not status.nearby_flags
        ):
            return False
        with self.exclusive_run():
            value = self.morning_record(local_day)
            if value is None or isinstance(value.get("update_message_id"), int):
                return False
            existing = _decode_beach_candidate(value.get("beach_candidate"))
            if existing is not None:
                existing_time, existing_status = existing
                existing_size = len(existing_status.nearby_flags)
                candidate_size = len(status.nearby_flags)
                if candidate_size < existing_size or (
                    candidate_size == existing_size
                    and observed_at <= existing_time
                ):
                    return False
            value["beach_candidate"] = {
                "observed_at": observed_at.isoformat(),
                "status": _encode_beach_status(status),
            }
            self._write(value)
            return True

    def beach_candidate(
        self,
        local_day: date,
        now: datetime,
        *,
        max_age: timedelta = timedelta(minutes=45),
    ) -> Optional[BeachStatus]:
        """Return a recent same-day candidate without trusting bad state."""

        if now.tzinfo is None or max_age < timedelta(0):
            return None
        value = self.morning_record(local_day)
        if value is None:
            return None
        decoded = _decode_beach_candidate(value.get("beach_candidate"))
        if decoded is None:
            return None
        observed_at, status = decoded
        age = now - observed_at
        if (
            observed_at.date() != local_day
            or status.source_date != local_day
            or age < timedelta(0)
            or age > max_age
        ):
            return None
        return status

    def mark_morning_deleted(self, local_day: date) -> None:
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["morning_deleted"] = True
        self._write(value)

    def event_catalog_sync_attempted(
        self, local_day: date, source: str
    ) -> bool:
        value = self.morning_record(local_day)
        if value is None:
            return False
        completed = value.get("event_catalog_sync", [])
        return (
            isinstance(completed, list)
            and source in completed
        )

    def mark_event_catalog_sync_attempted(
        self, local_day: date, source: str
    ) -> None:
        if not source or len(source) > 40:
            raise StateError("event catalog source is invalid")
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        completed = value.get("event_catalog_sync", [])
        if not isinstance(completed, list) or not all(
            isinstance(item, str) for item in completed
        ):
            raise StateError("event catalog sync state is invalid")
        value["event_catalog_sync"] = list(dict.fromkeys(
            completed + [source]
        ))
        self._write(value)

    def _write(self, value: dict) -> None:
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(value, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise StateError(
                "publication state could not be saved"
            ) from exc

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        """Prevent overlapping one-shot processes without storing run state."""

        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock_file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError(
                "another publication run is already active"
            ) from exc
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError(
                "publication state could not be locked"
            ) from exc

        try:
            yield
        finally:
            assert lock_file is not None
            lock_file.close()


def _encode_beach_status(status: BeachStatus) -> dict:
    return {
        "flag_color": status.flag_color,
        "sea_temperature_c": status.sea_temperature_c,
        "wind_direction": status.wind_direction,
        "wind_speed_kmh": status.wind_speed_kmh,
        "sea_state": status.sea_state,
        "nearby_flags": [list(item) for item in status.nearby_flags],
        "jellyfish_beaches": list(status.jellyfish_beaches),
        "jellyfish_states": [list(item) for item in status.jellyfish_states],
        "flag_meanings": [list(item) for item in status.flag_meanings],
        "updated_times": [
            [name, updated.isoformat()]
            for name, updated in status.updated_times
        ],
        "source_date": (
            status.source_date.isoformat()
            if status.source_date is not None else None
        ),
    }


def _decode_beach_candidate(value) -> Optional[tuple]:
    if not isinstance(value, dict):
        return None
    observed_raw = value.get("observed_at")
    status_raw = value.get("status")
    if not isinstance(observed_raw, str) or not isinstance(status_raw, dict):
        return None
    try:
        observed_at = datetime.fromisoformat(observed_raw)
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        return None
    status = _decode_beach_status(status_raw)
    if status is None:
        return None
    return observed_at, status


def _decode_beach_status(value: dict) -> Optional[BeachStatus]:
    optional_strings = (
        "flag_color", "wind_direction", "sea_state",
    )
    if any(
        value.get(name) is not None
        and not isinstance(value.get(name), str)
        for name in optional_strings
    ):
        return None
    optional_integers = ("sea_temperature_c", "wind_speed_kmh")
    if any(
        value.get(name) is not None
        and (
            not isinstance(value.get(name), int)
            or isinstance(value.get(name), bool)
        )
        for name in optional_integers
    ):
        return None
    nearby_flags = _string_pairs(value.get("nearby_flags"))
    jellyfish_states = _boolean_pairs(value.get("jellyfish_states"))
    flag_meanings = _string_pairs(value.get("flag_meanings"))
    jellyfish_beaches = value.get("jellyfish_beaches")
    updated_raw = value.get("updated_times")
    source_raw = value.get("source_date")
    if (
        nearby_flags is None
        or jellyfish_states is None
        or flag_meanings is None
        or not isinstance(jellyfish_beaches, list)
        or any(not isinstance(name, str) for name in jellyfish_beaches)
        or not isinstance(updated_raw, list)
        or not isinstance(source_raw, str)
    ):
        return None
    updated_times = []
    try:
        for item in updated_raw:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(part, str) for part in item)
            ):
                return None
            updated_times.append((item[0], time.fromisoformat(item[1])))
        source_date = date.fromisoformat(source_raw)
    except ValueError:
        return None
    return BeachStatus(
        flag_color=value.get("flag_color"),
        sea_temperature_c=value.get("sea_temperature_c"),
        wind_direction=value.get("wind_direction"),
        wind_speed_kmh=value.get("wind_speed_kmh"),
        sea_state=value.get("sea_state"),
        nearby_flags=nearby_flags,
        jellyfish_beaches=tuple(jellyfish_beaches),
        jellyfish_states=jellyfish_states,
        flag_meanings=flag_meanings,
        updated_times=tuple(updated_times),
        source_date=source_date,
    )


def _string_pairs(value) -> Optional[tuple]:
    if not isinstance(value, list):
        return None
    pairs = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            return None
        pairs.append((item[0], item[1]))
    return tuple(pairs)


def _boolean_pairs(value) -> Optional[tuple]:
    if not isinstance(value, list):
        return None
    pairs = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], bool)
        ):
            return None
        pairs.append((item[0], item[1]))
    return tuple(pairs)
