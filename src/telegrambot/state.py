"""Minimal successful-publication state for one-shot digest runs."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional


class StateError(RuntimeError):
    """Raised when publication state cannot be trusted or saved."""


class PublicationState:
    """Store only the last successfully published local date."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def last_successful_date(self) -> Optional[date]:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("publication state is unreadable") from exc
        if not isinstance(value, dict):
            raise StateError("publication state has an invalid structure")

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
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        value = {
            "last_successful_date": local_day.isoformat(),
        }
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
