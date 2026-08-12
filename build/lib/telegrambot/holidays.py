"""Small, annually reviewed official holiday calendar for Guardamar."""

from datetime import date
from typing import Dict, FrozenSet, Optional, Tuple

from .models import Holiday


# The published annual calendar already contains substitutions and transfers;
# never calculate them here. Sources for 2026:
# - BOE-A-2025-21667 (national and autonomous-community classification)
# - DOGV-C-2025-24690 (Comunitat Valenciana calendar)
# - DOGV 10238, 14-11-2025 (Guardamar local holidays)
_GUARDAMAR_HOLIDAY_RECORDS: Dict[int, Tuple[Holiday, ...]] = {
    2026: (
        Holiday(date(2026, 1, 1), "Новый год", "national"),
        Holiday(date(2026, 1, 6), "Богоявление", "national"),
        Holiday(date(2026, 3, 19), "День святого Иосифа", "national"),
        Holiday(date(2026, 4, 3), "Страстная пятница", "national"),
        Holiday(date(2026, 4, 6), "Пасхальный понедельник", "regional"),
        Holiday(date(2026, 5, 1), "День труда", "national"),
        Holiday(date(2026, 6, 24), "День святого Иоанна", "regional"),
        Holiday(
            date(2026, 7, 24),
            "Канун Дня святого Иакова",
            "local",
        ),
        Holiday(date(2026, 8, 15), "Успение Богородицы", "national"),
        Holiday(
            date(2026, 10, 7),
            "Праздник Девы Марии Розария",
            "local",
        ),
        Holiday(
            date(2026, 10, 9),
            "День Валенсийского сообщества",
            "regional",
        ),
        Holiday(
            date(2026, 10, 12),
            "Национальный день Испании",
            "national",
        ),
        Holiday(
            date(2026, 12, 8),
            "Непорочное зачатие",
            "national",
        ),
        Holiday(date(2026, 12, 25), "Рождество Христово", "national"),
    ),
}

_GUARDAMAR_HOLIDAYS: Dict[int, FrozenSet[date]] = {
    year: frozenset(holiday.date for holiday in holidays)
    for year, holidays in _GUARDAMAR_HOLIDAY_RECORDS.items()
}


def official_holidays_on(local_day: date) -> Tuple[Holiday, ...]:
    """Return reviewed official holidays for one Guardamar local date."""

    holidays = _GUARDAMAR_HOLIDAY_RECORDS.get(local_day.year, ())
    return tuple(holiday for holiday in holidays if holiday.date == local_day)


def holidays_for_year(year: int) -> Optional[FrozenSet[date]]:
    """Return the reviewed Guardamar calendar, or None for unknown years."""

    return _GUARDAMAR_HOLIDAYS.get(year)


def is_market_day(local_day: date) -> bool:
    """Apply the ordinance: Wednesday, or Tuesday before a holiday Wednesday."""

    holidays = holidays_for_year(local_day.year)
    if holidays is None:
        return False
    if local_day.weekday() == 1:
        following_day = date.fromordinal(local_day.toordinal() + 1)
        return following_day in holidays
    return local_day.weekday() == 2 and local_day not in holidays
