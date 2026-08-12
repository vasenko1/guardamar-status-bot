"""Atomic same-day cache for one normalized AEMET digest."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import MorningDigest, Warning, Weather

VERSION = 1


def _datetime(value):
    return value.isoformat() if value is not None else None


def _serialize(digest: MorningDigest, fetched_at: datetime) -> dict:
    if digest.weather is None:
        raise ValueError("AEMET snapshot requires normalized weather")
    weather = asdict(digest.weather)
    weather["observed_at"] = _datetime(digest.weather.observed_at)
    weather["sunrise"] = _datetime(digest.weather.sunrise)
    weather["sunset"] = _datetime(digest.weather.sunset)
    return {
        "version": VERSION,
        "fetched_at": fetched_at.isoformat(),
        "weather": weather,
        "warnings": [
            {
                **asdict(warning),
                "starts_at": _datetime(warning.starts_at),
                "ends_at": _datetime(warning.ends_at),
            }
            for warning in digest.warnings
        ],
        "warnings_available": digest.warnings_available,
        "forecast_sea_temperature_c": digest.forecast_sea_temperature_c,
        "forecast_sea_state": digest.forecast_sea_state,
        "forecast_later_sea_state": digest.forecast_later_sea_state,
    }


def _parse_datetime(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError
    return parsed


def load_snapshot(
    path: Path,
    now: datetime,
    *,
    max_age: Optional[timedelta] = None,
) -> Optional[MorningDigest]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != VERSION:
            return None
        fetched_at = _parse_datetime(data["fetched_at"])
        if fetched_at.date() != now.astimezone(fetched_at.tzinfo).date():
            return None
        age = now.astimezone(fetched_at.tzinfo) - fetched_at
        if age < timedelta(minutes=-5) or (
            max_age is not None and age > max_age
        ):
            return None
        raw_weather = data["weather"]
        weather = Weather(
            **{
                **raw_weather,
                "observed_at": _parse_datetime(raw_weather["observed_at"]),
                "sunrise": _parse_datetime(raw_weather.get("sunrise")),
                "sunset": _parse_datetime(raw_weather.get("sunset")),
                "sky_conditions": tuple(raw_weather.get("sky_conditions", ())),
            }
        )
        warnings = tuple(
            Warning(
                **{
                    **raw,
                    "starts_at": _parse_datetime(raw.get("starts_at")),
                    "ends_at": _parse_datetime(raw.get("ends_at")),
                }
            )
            for raw in data.get("warnings", ())
        )
        return MorningDigest(
            weather=weather,
            warnings=warnings,
            warnings_available=bool(data.get("warnings_available")),
            forecast_sea_temperature_c=data.get(
                "forecast_sea_temperature_c"
            ),
            forecast_sea_state=data.get("forecast_sea_state"),
            forecast_later_sea_state=data.get("forecast_later_sea_state"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def write_snapshot(
    path: Path,
    digest: MorningDigest,
    fetched_at: datetime,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _serialize(digest, fetched_at)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def preparation_lock(path: Path, *, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(lock.fileno(), operation)
        except BlockingIOError:
            yield False
            return
        yield True


def preparation_busy(path: Path) -> bool:
    with preparation_lock(path, blocking=False) as acquired:
        return not acquired
