"""Small deterministic helpers for verified route facts."""

import re
import unicodedata
from typing import Optional

ROUTE_DIFFICULTY_PREFIX = "Сложность маршрута: "

_LOW = r"(?:baja|baixa|facil)"
_MEDIUM = r"(?:moderada|media|mitjana)"
_HIGH = r"(?:alta|dificil)"
_JOIN = r"(?:\s*[-–/]\s*|\s+a\s+)"


def route_difficulty_detail(value: str) -> Optional[str]:
    """Return one canonical route difficulty from an explicit source label."""

    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    marker = re.search(
        r"\b(?:nivel\s+de\s+)?(?:dificultad|dificultat)\s*:?\s*(.{1,48})",
        normalized,
    )
    if marker is None:
        return None
    candidate = marker.group(1)

    for pattern, label in (
        (rf"^{_LOW}{_JOIN}{_MEDIUM}\b", "низкая–средняя"),
        (rf"^{_MEDIUM}{_JOIN}{_LOW}\b", "низкая–средняя"),
        (rf"^{_MEDIUM}{_JOIN}{_HIGH}\b", "средняя–высокая"),
        (rf"^{_HIGH}{_JOIN}{_MEDIUM}\b", "средняя–высокая"),
        (rf"^{_LOW}\b", "низкая"),
        (rf"^{_MEDIUM}\b", "средняя"),
        (rf"^{_HIGH}\b", "высокая"),
    ):
        if re.match(pattern, candidate):
            return ROUTE_DIFFICULTY_PREFIX + label
    return None
