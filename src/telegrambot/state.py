"""Minimal successful-publication state for one-shot digest runs."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterator, Optional

from .models import AirQualitySummary, BeachNotice, BeachStatus, PollenSummary


class StateError(RuntimeError):
    """Raised when publication state cannot be trusted or saved."""


class PublicationState:
    """Store the minimal identifiers and semantic baselines for one local day."""

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

    def mark_published(self, local_day: date) -> None:
        """Record one confirmed success for a simple single-date workflow."""
        self._write({"last_successful_date": local_day.isoformat()})

    def electricity_explanation_message_id(self) -> Optional[int]:
        value = self._read()
        message_id = value.get("electricity_explanation_message_id")
        if message_id is None:
            return None
        if not isinstance(message_id, int) or message_id <= 0:
            raise StateError("publication state has an invalid electricity anchor")
        return message_id

    def mark_electricity_published(self, local_day: date) -> None:
        value = {"last_successful_date": local_day.isoformat()}
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
        if not isinstance(message_id, int) or not isinstance(published_at, str):
            raise StateError("publication state has an invalid morning record")
        try:
            parsed_time = datetime.fromisoformat(published_at)
        except ValueError as exc:
            raise StateError("publication state has an invalid publication time") from exc
        if parsed_time.tzinfo is None:
            raise StateError("publication state has an invalid publication time")
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

    def beach_message_id(self, local_day: date) -> Optional[int]:
        value = self.morning_record(local_day)
        if value is None:
            return None
        identifier = value.get("beach_message_id")
        if identifier is None:
            return None
        if not isinstance(identifier, int) or identifier <= 0:
            raise StateError("publication state has an invalid beach anchor")
        return identifier

    def mark_beach_message(
        self,
        local_day: date,
        message_id: int,
        status: Optional[BeachStatus] = None,
        notice: Optional[BeachNotice] = None,
    ) -> None:
        """Store the daily beach root and its verified SafeBeach baseline."""
        if not isinstance(message_id, int) or message_id <= 0:
            raise StateError("beach message ID is invalid")
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["beach_message_id"] = message_id
        value.pop("beach_candidate", None)
        if status is not None:
            value["beach_root_status"] = _encode_beach_status(status)
            jellyfish = dict(status.jellyfish_states)
            value["beach_baseline"] = {
                name: {"flag": color, "jellyfish": jellyfish.get(name)}
                for name, color in status.nearby_flags
            }
        if notice is not None:
            value["beach_root_notice"] = _encode_beach_notice(notice)
        self._write(value)

    def beach_root_facts(
        self, local_day: date
    ) -> tuple[Optional[BeachStatus], Optional[BeachNotice]]:
        """Return the last verified root facts so a refresh cannot erase them."""
        value = self.morning_record(local_day)
        if value is None:
            return None, None
        status = _decode_beach_status(value.get("beach_root_status"))
        notice = _decode_beach_notice(value.get("beach_root_notice"))
        return status, notice

    def set_beach_message_id(self, local_day: date, message_id: int) -> None:
        value = self.morning_record(local_day)
        if value is None or not isinstance(message_id, int) or message_id <= 0:
            raise StateError("beach message ID is invalid")
        value["beach_message_id"] = message_id
        self._write(value)

    def mark_update_sent(
        self,
        local_day: date,
        message_id: int,
        beach_status: Optional[BeachStatus] = None,
    ) -> None:
        """Legacy replacement state retained for safe same-day upgrades."""
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        value["update_message_id"] = message_id
        value.pop("beach_candidate", None)
        if beach_status is not None:
            jellyfish = dict(beach_status.jellyfish_states)
            value["beach_baseline"] = {
                name: {"flag": color, "jellyfish": jellyfish.get(name)}
                for name, color in beach_status.nearby_flags
            }
        self._write(value)

    def morning_environment(
        self, local_day: date
    ) -> tuple[Optional[int], Optional[int], Optional[datetime]]:
        value = self.morning_record(local_day)
        if value is None:
            return None, None, None
        heat_level = value.get("heat_health_level")
        if heat_level is not None and (
            not isinstance(heat_level, int)
            or isinstance(heat_level, bool)
            or heat_level not in range(4)
        ):
            raise StateError("publication state has an invalid heat level")
        cold_level = value.get("cold_health_level")
        if cold_level is not None and (
            not isinstance(cold_level, int)
            or isinstance(cold_level, bool)
            or cold_level not in range(4)
        ):
            raise StateError("publication state has an invalid cold level")
        raw_base = value.get("cams_forecast_base")
        if raw_base is None:
            return heat_level, cold_level, None
        if not isinstance(raw_base, str):
            raise StateError("publication state has an invalid CAMS base")
        try:
            forecast_base = datetime.fromisoformat(raw_base)
        except ValueError as exc:
            raise StateError("publication state has an invalid CAMS base") from exc
        if forecast_base.tzinfo is None:
            raise StateError("publication state has an invalid CAMS base")
        return heat_level, cold_level, forecast_base

    def mark_morning_environment(
        self,
        local_day: date,
        heat_level: Optional[int],
        cams_forecast_base: Optional[datetime],
        *,
        cold_level: Optional[int] = None,
        air_quality: Optional[AirQualitySummary] = None,
        pollen: Optional[PollenSummary] = None,
    ) -> None:
        """Store health levels and legacy CAMS fields without source-cache side effects."""
        if heat_level is not None and (
            not isinstance(heat_level, int)
            or isinstance(heat_level, bool)
            or heat_level not in range(4)
        ):
            raise StateError("morning heat level is invalid")
        if cold_level is not None and (
            not isinstance(cold_level, int)
            or isinstance(cold_level, bool)
            or cold_level not in range(4)
        ):
            raise StateError("morning cold level is invalid")
        if cams_forecast_base is not None and cams_forecast_base.tzinfo is None:
            raise StateError("morning CAMS base is invalid")
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        if heat_level is not None:
            value["heat_health_level"] = heat_level
        else:
            value.pop("heat_health_level", None)
        if cold_level is not None:
            value["cold_health_level"] = cold_level
        else:
            value.pop("cold_health_level", None)
        if cams_forecast_base is not None:
            value["cams_forecast_base"] = cams_forecast_base.isoformat()
        else:
            value.pop("cams_forecast_base", None)
        if air_quality is not None:
            value["cams_air"] = _encode_air_quality(air_quality)
        if pollen is not None:
            value["cams_pollen"] = _encode_pollen(pollen)
        self._write(value)

    def mark_cams_environment(
        self,
        local_day: date,
        cams_forecast_base: Optional[datetime],
        air_quality: Optional[AirQualitySummary],
        pollen: Optional[PollenSummary],
    ) -> None:
        """Replace one valid CAMS semantic snapshot, including explicit clears."""
        if cams_forecast_base is not None and cams_forecast_base.tzinfo is None:
            raise StateError("CAMS base is invalid")
        value = self.morning_record(local_day)
        if value is None:
            raise StateError("morning publication record is missing")
        if cams_forecast_base is None:
            value.pop("cams_forecast_base", None)
        else:
            value["cams_forecast_base"] = cams_forecast_base.isoformat()
        if air_quality is None:
            value.pop("cams_air", None)
        else:
            value["cams_air"] = _encode_air_quality(air_quality)
        if pollen is None:
            value.pop("cams_pollen", None)
        else:
            value["cams_pollen"] = _encode_pollen(pollen)
        value["cams_semantic_baseline"] = True
        self._write(value)

    def morning_environment_state(
        self, local_day: date
    ) -> tuple[
        Optional[int], Optional[int], Optional[datetime],
        Optional[AirQualitySummary], Optional[PollenSummary],
    ]:
        """Return health levels plus the compact semantic CAMS baseline."""
        heat, cold, base = self.morning_environment(local_day)
        value = self.morning_record(local_day) or {}
        air = _decode_air_quality(value.get("cams_air"))
        pollen = _decode_pollen(value.get("cams_pollen"))
        return heat, cold, base, air, pollen

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
                    candidate_size == existing_size and observed_at <= existing_time
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

    def event_catalog_sync_attempted(self, local_day: date, source: str) -> bool:
        value = self.morning_record(local_day)
        if value is None:
            return False
        completed = value.get("event_catalog_sync", [])
        return isinstance(completed, list) and source in completed

    def mark_event_catalog_sync_attempted(self, local_day: date, source: str) -> None:
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
        value["event_catalog_sync"] = list(dict.fromkeys(completed + [source]))
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
            raise StateError("publication state could not be saved") from exc

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        """Prevent overlapping one-shot processes without storing run state."""
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock_file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError("another publication run is already active") from exc
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError("publication state could not be locked") from exc
        try:
            yield
        finally:
            assert lock_file is not None
            lock_file.close()


def _encode_air_quality(value: AirQualitySummary) -> dict:
    return {
        "pollutants": list(value.pollutants),
        "period": value.period,
        "dust_related": value.dust_related,
        "wildfire_possible": value.wildfire_possible,
        "category": value.category,
    }


def _decode_air_quality(value) -> Optional[AirQualitySummary]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StateError("publication state has an invalid CAMS air baseline")
    pollutants = value.get("pollutants")
    period = value.get("period")
    category = value.get("category")
    dust_related = value.get("dust_related", False)
    wildfire_possible = value.get("wildfire_possible", False)
    if (
        not isinstance(pollutants, list)
        or not pollutants
        or any(not isinstance(item, str) or not item for item in pollutants)
        or not isinstance(period, str)
        or not period
        or not isinstance(category, int)
        or isinstance(category, bool)
        or category not in range(3, 6)
        or not isinstance(dust_related, bool)
        or not isinstance(wildfire_possible, bool)
    ):
        raise StateError("publication state has an invalid CAMS air baseline")
    return AirQualitySummary(
        tuple(pollutants), period, dust_related, wildfire_possible, category
    )


def _encode_pollen(value: PollenSummary) -> dict:
    return {
        "allergens": list(value.allergens),
        "period": value.period,
        "ragweed_present": value.ragweed_present,
        "ragweed_period": value.ragweed_period,
    }


def _decode_pollen(value) -> Optional[PollenSummary]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StateError("publication state has an invalid CAMS pollen baseline")
    allergens = value.get("allergens")
    period = value.get("period")
    ragweed_present = value.get("ragweed_present")
    ragweed_period = value.get("ragweed_period")
    if (
        not isinstance(allergens, list)
        or any(not isinstance(item, str) or not item for item in allergens)
        or (period is not None and not isinstance(period, str))
        or not isinstance(ragweed_present, bool)
        or (ragweed_period is not None and not isinstance(ragweed_period, str))
        or (not allergens and not ragweed_present)
    ):
        raise StateError("publication state has an invalid CAMS pollen baseline")
    return PollenSummary(
        tuple(allergens), period, ragweed_present, ragweed_period
    )


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
            [name, updated.isoformat()] for name, updated in status.updated_times
        ],
        "source_date": status.source_date.isoformat() if status.source_date else None,
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


def _decode_beach_status(value) -> Optional[BeachStatus]:
    if not isinstance(value, dict):
        return None
    optional_strings = ("flag_color", "wind_direction", "sea_state")
    if any(
        value.get(name) is not None and not isinstance(value.get(name), str)
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


def _encode_beach_notice(notice: BeachNotice) -> dict:
    return {
        "text": notice.text,
        "bathing_prohibited": notice.bathing_prohibited,
        "published_at": notice.published_at.isoformat(),
    }


def _decode_beach_notice(value) -> Optional[BeachNotice]:
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    prohibited = value.get("bathing_prohibited")
    raw_time = value.get("published_at")
    if (
        not isinstance(text, str)
        or not isinstance(prohibited, bool)
        or not isinstance(raw_time, str)
    ):
        return None
    try:
        published_at = datetime.fromisoformat(raw_time)
    except ValueError:
        return None
    if published_at.tzinfo is None:
        return None
    return BeachNotice(text, prohibited, published_at)


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
