"""Small normalized models used by the Morning Digest."""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional, Tuple


@dataclass(frozen=True)
class Weather:
    current_temperature_c: Optional[float]
    minimum_temperature_c: int
    maximum_temperature_c: int
    wind_direction: Optional[str]
    wind_speed_kmh: Optional[int]
    observed_at: Optional[datetime]
    forecast_wind_speed_kmh: Optional[int] = None
    sky_condition: Optional[str] = None
    sky_conditions: Tuple[str, ...] = ()
    rain_probability_percent: Optional[int] = None
    rain_period: Optional[str] = None


@dataclass(frozen=True)
class Warning:
    event: str
    level: str
    ends_at: Optional[datetime]
    starts_at: Optional[datetime] = None
    description: Optional[str] = None
    probability: Optional[str] = None


@dataclass(frozen=True)
class BeachStatus:
    flag_color: Optional[str]
    sea_temperature_c: Optional[int]
    wind_direction: Optional[str] = None
    wind_speed_kmh: Optional[int] = None
    sea_state: Optional[str] = None
    nearby_flags: Tuple[Tuple[str, str], ...] = ()
    jellyfish_beaches: Tuple[str, ...] = ()
    flag_meanings: Tuple[Tuple[str, str], ...] = ()
    updated_times: Tuple[Tuple[str, time], ...] = ()
    source_date: Optional[date] = None


@dataclass(frozen=True)
class Event:
    title: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime] = None
    place: Optional[str] = None
    active_until: Optional[date] = None
    category: str = "event"
    is_final_day: bool = False


@dataclass(frozen=True)
class TrafficMeasure:
    """One independently active mobility restriction from an official notice."""

    action: str
    location: str
    valid_from: date
    valid_until: date
    daily_hours: Optional[str] = None
    affected: Optional[str] = None
    exceptions: Optional[str] = None
    alternative: Optional[str] = None
    destinations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TrafficNotice:
    text: str
    measures: Tuple[TrafficMeasure, ...] = ()
    source_url: Optional[str] = None


@dataclass(frozen=True)
class BeachNotice:
    text: str
    bathing_prohibited: bool
    published_at: datetime


@dataclass(frozen=True)
class MorningDigest:
    weather: Weather
    warnings: Tuple[Warning, ...]
    warnings_available: bool
    beach: Optional[BeachStatus] = None
    forecast_sea_temperature_c: Optional[int] = None
    forecast_sea_state: Optional[str] = None
    forecast_later_sea_state: Optional[str] = None
    traffic_notices: Tuple[TrafficNotice, ...] = ()
    events: Tuple[Event, ...] = ()
    beach_notice: Optional[BeachNotice] = None
