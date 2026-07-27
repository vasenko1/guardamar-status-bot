"""Small normalized models used by the Morning Digest."""

from dataclasses import dataclass
from datetime import date, datetime
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


@dataclass(frozen=True)
class Warning:
    event: str
    level: str
    ends_at: Optional[datetime]


@dataclass(frozen=True)
class BeachStatus:
    flag_color: str
    sea_temperature_c: Optional[int]
    wind_direction: Optional[str] = None
    wind_speed_kmh: Optional[int] = None


@dataclass(frozen=True)
class Event:
    title: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime] = None
    place: Optional[str] = None
    active_until: Optional[date] = None
    category: str = "event"


@dataclass(frozen=True)
class TrafficNotice:
    text: str


@dataclass(frozen=True)
class MorningDigest:
    weather: Weather
    warnings: Tuple[Warning, ...]
    warnings_available: bool
    beach: Optional[BeachStatus] = None
    forecast_sea_temperature_c: Optional[int] = None
    traffic_notices: Tuple[TrafficNotice, ...] = ()
    events: Tuple[Event, ...] = ()
