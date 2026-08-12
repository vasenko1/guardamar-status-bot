"""Deterministic Guardamar sunrise and sunset times without any source.

Implements the standard NOAA/Almanac sunrise equation with the official
zenith of 90.833 degrees. Accuracy is within a couple of minutes at this
latitude, which is sufficient for one compact informational row.
"""

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
GUARDAMAR_LATITUDE = 38.0896
GUARDAMAR_LONGITUDE = -0.6553
_ZENITH_DEGREES = 90.833


def _event_utc_hour(day: date, rising: bool) -> Optional[float]:
    day_of_year = day.timetuple().tm_yday
    longitude_hour = GUARDAMAR_LONGITUDE / 15.0
    base = 6.0 if rising else 18.0
    approx = day_of_year + ((base - longitude_hour) / 24.0)

    mean_anomaly = (0.9856 * approx) - 3.289
    true_longitude = (
        mean_anomaly
        + (1.916 * math.sin(math.radians(mean_anomaly)))
        + (0.020 * math.sin(math.radians(2 * mean_anomaly)))
        + 282.634
    ) % 360.0

    right_ascension = math.degrees(
        math.atan(0.91764 * math.tan(math.radians(true_longitude)))
    ) % 360.0
    # Keep the right ascension in the same quadrant as the true longitude.
    right_ascension += (
        math.floor(true_longitude / 90.0) * 90.0
        - math.floor(right_ascension / 90.0) * 90.0
    )
    right_ascension /= 15.0

    sin_declination = 0.39782 * math.sin(math.radians(true_longitude))
    cos_declination = math.cos(math.asin(sin_declination))
    latitude = math.radians(GUARDAMAR_LATITUDE)
    cos_hour_angle = (
        math.cos(math.radians(_ZENITH_DEGREES))
        - (sin_declination * math.sin(latitude))
    ) / (cos_declination * math.cos(latitude))
    if not -1.0 <= cos_hour_angle <= 1.0:
        return None

    hour_angle = math.degrees(math.acos(cos_hour_angle))
    if rising:
        hour_angle = 360.0 - hour_angle
    hour_angle /= 15.0

    mean_time = (
        hour_angle
        + right_ascension
        - (0.06571 * approx)
        - 6.622
    )
    return (mean_time - longitude_hour) % 24.0


def sun_times(
    now: datetime,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Return local sunrise and sunset for the current Guardamar date."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    events = []
    for rising in (True, False):
        utc_hour = _event_utc_hour(local_day, rising)
        if utc_hour is None:
            events.append(None)
            continue
        moment = datetime.combine(
            local_day, time.min, timezone.utc
        ) + timedelta(hours=utc_hour)
        events.append(moment.astimezone(GUARDAMAR_TIMEZONE))
    return events[0], events[1]
