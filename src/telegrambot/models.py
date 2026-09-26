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
    uv_index: Optional[int] = None
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None


@dataclass(frozen=True)
class Warning:
    event: str
    level: str
    ends_at: Optional[datetime]
    starts_at: Optional[datetime] = None
    description: Optional[str] = None
    probability: Optional[str] = None
    parameter_code: Optional[str] = None
    parameter_value: Optional[float] = None
    parameter_unit: Optional[str] = None


@dataclass(frozen=True)
class BeachStatus:
    flag_color: Optional[str]
    sea_temperature_c: Optional[int]
    wind_direction: Optional[str] = None
    wind_speed_kmh: Optional[int] = None
    sea_state: Optional[str] = None
    nearby_flags: Tuple[Tuple[str, str], ...] = ()
    jellyfish_beaches: Tuple[str, ...] = ()
    jellyfish_states: Tuple[Tuple[str, bool], ...] = ()
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
    ticket_price_cents: Optional[int] = None
    ticket_price_is_from: bool = False
    ticket_url: Optional[str] = None
    participation_note: Optional[str] = None
    registration_contact: Optional[str] = None
    registration_url: Optional[str] = None
    capacity_limited: bool = False
    teaser: Optional[str] = None
    programme_title: Optional[str] = None
    programme_order: Optional[int] = None
    session_group_key: Optional[str] = None
    duration_minutes: Optional[int] = None
    audience_label: Optional[str] = None
    details: Tuple[str, ...] = ()
    place_query: Optional[str] = None
    meeting_point: Optional[str] = None
    schedule_note: Optional[str] = None
    access_note: Optional[str] = None
    active_from: Optional[date] = None
    route: Optional[str] = None
    admission_evidence: Optional[str] = None
    image_url: Optional[str] = None
    programme_display_title: Optional[str] = None


@dataclass(frozen=True)
class Holiday:
    """One reviewed official non-working holiday applicable in Guardamar."""

    date: date
    name: str
    scope: str


@dataclass(frozen=True)
class Celebration:
    """One reviewed local festive period, separate from legal holidays."""

    name: str
    start_date: date
    end_date: date
    official_holiday_dates: Tuple[date, ...] = ()


@dataclass(frozen=True)
class PharmacyDuty:
    """One on-call pharmacy row from the official provincial rota."""

    name: str
    address: str
    hours: str
    municipality: str = "Guardamar del Segura"


@dataclass(frozen=True)
class HeatHealthRisk:
    """Today's official Meteosalud risk level (never a forecast history)."""

    level: int


@dataclass(frozen=True)
class ColdHealthRisk:
    """Today's official Meteosalud cold-risk level."""

    level: int


@dataclass(frozen=True)
class AirQualitySummary:
    """Compact, display-ready result of today's CAMS forecast."""

    pollutants: Tuple[str, ...]
    period: str
    dust_related: bool = False
    wildfire_possible: bool = False
    category: int = 0


@dataclass(frozen=True)
class PollenSummary:
    """Compact, display-ready result of today's CAMS pollen forecast."""

    allergens: Tuple[str, ...] = ()
    period: Optional[str] = None
    ragweed_present: bool = False
    ragweed_period: Optional[str] = None


@dataclass(frozen=True)
class BeachNotice:
    text: str
    bathing_prohibited: bool
    published_at: datetime


@dataclass(frozen=True)
class MorningDigest:
    weather: Optional[Weather]
    warnings: Tuple[Warning, ...]
    warnings_available: bool
    beach: Optional[BeachStatus] = None
    forecast_sea_temperature_c: Optional[int] = None
    forecast_sea_state: Optional[str] = None
    forecast_later_sea_state: Optional[str] = None
    holidays: Tuple[Holiday, ...] = ()
    celebrations: Tuple[Celebration, ...] = ()
    events: Tuple[Event, ...] = ()
    beach_notice: Optional[BeachNotice] = None
    pharmacies: Tuple[PharmacyDuty, ...] = ()
    heat_health_risk: Optional[HeatHealthRisk] = None
    air_quality: Optional[AirQualitySummary] = None
    pollen: Optional[PollenSummary] = None
    cold_health_risk: Optional[ColdHealthRisk] = None
    fire_risk_level: Optional[int] = None
    dry_thunderstorm_risk_level: Optional[int] = None
    hydrology_state: Optional[str] = None
