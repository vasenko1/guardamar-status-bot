"""Crash-safe at-most-once delivery state for one target date."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional, Type


class DatedPublicationStateError(RuntimeError):
    """Raised when dated publication state cannot be trusted."""


class DatedPublicationState:
    """Minimal crash-safe at-most-once state for one target date."""

    VERSION = 1

    def __init__(
        self,
        path: Path,
        *,
        label: str = "dated-publication",
        error_type: Type[RuntimeError] = DatedPublicationStateError,
    ) -> None:
        if not label:
            raise ValueError("dated publication label must not be empty")
        self.path = path
        self.label = label
        self.error_type = error_type

    def _error(self, message: str) -> RuntimeError:
        return self.error_type(f"{self.label} {message}")

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": self.VERSION}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._error("state is unreadable") from exc
        if not isinstance(value, dict) or value.get("version") != self.VERSION:
            raise self._error("state has an invalid structure")
        raw_date = value.get("target_date")
        status = value.get("status")
        if raw_date is None and status is None:
            if set(value) != {"version"}:
                raise self._error("empty state has unexpected fields")
            return value
        if not isinstance(raw_date, str) or status not in {"uncertain", "sent"}:
            raise self._error("state has an invalid publication marker")
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise self._error("state has an invalid target date") from exc
        expected_fields = (
            {"version", "target_date", "status", "message_id"}
            if status == "sent"
            else {"version", "target_date", "status"}
        )
        if set(value) != expected_fields:
            raise self._error("state has unexpected fields")
        message_id = value.get("message_id")
        if status == "sent":
            if (
                not isinstance(message_id, int)
                or isinstance(message_id, bool)
                or message_id <= 0
            ):
                raise self._error("state has an invalid message ID")
        elif message_id is not None:
            raise self._error("uncertain state cannot have a message ID")
        return value

    def status(self, target_day: date) -> Optional[str]:
        value = self._read()
        if value.get("target_date") != target_day.isoformat():
            return None
        return value.get("status")

    def mark_uncertain(self, target_day: date) -> None:
        self._write({
            "version": self.VERSION,
            "target_date": target_day.isoformat(),
            "status": "uncertain",
        })

    def clear(self, target_day: date) -> None:
        value = self._read()
        if value.get("target_date") == target_day.isoformat():
            self._write({"version": self.VERSION})

    def mark_sent(self, target_day: date, message_id: int) -> None:
        if (
            not isinstance(message_id, int)
            or isinstance(message_id, bool)
            or message_id <= 0
        ):
            raise self._error("invalid message ID")
        self._write({
            "version": self.VERSION,
            "target_date": target_day.isoformat(),
            "status": "sent",
            "message_id": message_id,
        })

    def _write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise self._error("another run is active") from exc
            yield
