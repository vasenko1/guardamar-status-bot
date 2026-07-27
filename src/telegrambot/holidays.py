"""Small, reviewed holiday calendar used by local recurring rules."""

from datetime import date
from typing import Dict, FrozenSet, Optional


# Official 2026 national and Comunitat Valenciana holidays (BOE-A-2025-21667)
# plus Guardamar local holidays (DOGV 14-11-2025).
_GUARDAMAR_HOLIDAYS: Dict[int, FrozenSet[date]] = {
    2026: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 1, 6),
            date(2026, 3, 19),
            date(2026, 4, 3),
            date(2026, 4, 6),
            date(2026, 5, 1),
            date(2026, 6, 24),
            date(2026, 7, 24),
            date(2026, 8, 15),
            date(2026, 10, 7),
            date(2026, 10, 9),
            date(2026, 10, 12),
            date(2026, 12, 8),
            date(2026, 12, 25),
        }
    ),
}


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
