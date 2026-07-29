"""Minimal successful-publication state for one-shot digest runs."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional


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
            # Read the previous schema once so an existing confirmed success
            # does not cause a duplicate after this upgrade.
            if value.get("status") == "success":
                raw_date = value.get("local_date")
            elif value.get("status") in {"started", "failed", "skipped"}:
                return None
            else:
                raise StateError("publication state has an invalid structure")
        if not isinstance(raw_date, str):
            raise StateError("publication state has an invalid date")
        try:
            return date.fromisoformat(raw_date)
        except ValueError as exc:
            raise StateError("publication state has an invalid date") from exc

    def is_published(self, local_day: date) -> bool:
        return self.last_successful_date() == local_day

    def mark_published(self, local_day: date) -> None:
        self._write({
            "last_successful_date": local_day.isoformat(),
        })

    def morning_record(self, local_day: date) -> Optional[dict]:
        value = self._read()
        if value.get("local_date") != local_day.isoformat():
            return None
        message_id = value.get("morning_message_id")
        published_at = value.get("morning_published_at")
        message = value.get("morning_message")
        if not isinstance(message_id, int) or not isinstance(
            published_at, str
        ) or (
            message is not None
            and (not isinstance(message, str) or not message)
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
        message: str,
    ) -> None:
        self._write({
            "last_successful_date": local_day.isoformat(),
            "local_date": local_day.isoformat(),
            "morning_message_id": message_id,
            "morning_published_at": published_at.isoformat(),
            "morning_message": message,
            "update_message_id": None,
            "morning_deleted": False,
        })

    def mark_update_sent(
        self,
        local_day: date,
        message_id: int,
    ) -> None:
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["update_message_id"] = message_id
        self._write(value)

    def mark_morning_deleted(self, local_day: date) -> None:
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["morning_deleted"] = True
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
