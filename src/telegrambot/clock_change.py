"""Local Europe/Madrid clock-change facts and compact resident notices."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from .models import ClockChange


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
UTC = timezone.utc


def clock_change_on(local_day: date) -> Optional[ClockChange]:
    """Return the actual Europe/Madrid wall-clock transition on local_day."""

    start = datetime.combine(local_day, time.min, tzinfo=GUARDAMAR_TIMEZONE)
    end = datetime.combine(
        local_day + timedelta(days=1),
        time.min,
        tzinfo=GUARDAMAR_TIMEZONE,
    )
    if start.utcoffset() == end.utcoffset():
        return None

    cursor = start.astimezone(UTC)
    limit = end.astimezone(UTC)
    previous_offset = cursor.astimezone(GUARDAMAR_TIMEZONE).utcoffset()

    while cursor <= limit:
        current = cursor.astimezone(GUARDAMAR_TIMEZONE)
        current_offset = current.utcoffset()
        if current_offset != previous_offset:
            delta = current_offset - previous_offset
            delta_minutes = int(delta.total_seconds() // 60)
            after_time = time(current.hour, current.minute)
            before_time = (
                datetime.combine(local_day, after_time) - delta
            ).time()
            return ClockChange(
                date=local_day,
                from_time=before_time,
                to_time=after_time,
                delta_minutes=delta_minutes,
            )
        previous_offset = current_offset
        cursor += timedelta(minutes=1)

    # A differing midnight offset must imply one transition inside this day.
    # Fail quiet rather than inventing a wall-clock jump if tzdata is corrupt.
    return None


def clock_change_notice_lines(
    change: ClockChange,
    *,
    tomorrow: bool,
) -> Tuple[str, ...]:
    """Render the same verified transition fact for evening and morning."""

    forward = change.delta_minutes > 0
    season = "летнее" if forward else "зимнее"
    from_label = change.from_time.strftime("%H:%M")
    to_label = change.to_time.strftime("%H:%M")

    if tomorrow:
        heading = f"⏰ <b>Завтра — переход на {season} время</b>"
        if abs(change.delta_minutes) == 60:
            effect = (
                "ночь будет на час короче"
                if forward else "спим на час дольше"
            )
        else:
            direction = "вперёд" if forward else "назад"
            effect = (
                f"часы сдвинутся {direction} на "
                f"{abs(change.delta_minutes)} мин."
            )
        detail = (
            f"Этой ночью в <b>{from_label}</b> станет "
            f"<b>{to_label}</b> — {effect}."
        )
    else:
        heading = f"⏰ <b>Сегодня перешли на {season} время</b>"
        detail = (
            f"Ночью в <b>{from_label}</b> стало <b>{to_label}</b>."
        )

    return (
        heading,
        detail,
        "Проверьте часы и будильники без автосинхронизации.",
    )
