"""Exact-date Guardamar ↔ Elche timetable from the Avanza public planner."""

import html
import http.cookiejar
import logging
import urllib.request
from datetime import date, timedelta
from typing import Dict, Optional

from . import alicante_schedule as avanza
from .branding import FOOTER, with_footer
from .intercity_schedule import (
    IntercityFare,
    IntercitySchedule,
    IntercityScheduleBundle,
    IntercityScheduleError,
    date_label,
    fare_amount,
    format_times,
)
from .pinned import GUARDAMAR_BUS_STATION_MAP_URL

ELCHE_ROUTE_KEY = "elche"


def fetch_schedules(
    service_dates: tuple[date, ...],
) -> Dict[date, IntercitySchedule]:
    """Fetch Guardamar ↔ Elche for exact dates using the proven Avanza form."""

    wanted_dates = tuple(dict.fromkeys(service_dates))
    if not wanted_dates or len(wanted_dates) > 3:
        raise IntercityScheduleError("Elche planner date request is invalid")

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        avanza._PlannerRedirectHandler(),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    initial = urllib.request.Request(
        avanza.PLANNER_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": avanza.USER_AGENT,
        },
    )
    try:
        payload, final_url = avanza._planner_open(opener, initial)
        action, base_fields = avanza._search_form(payload, final_url)
    except avanza.AlicanteScheduleError as exc:
        raise IntercityScheduleError(
            f"Elche planner is unavailable: {exc}"
        ) from exc

    result: Dict[date, IntercitySchedule] = {}
    for service_date in wanted_dates:
        try:
            outbound = avanza._fetch_direction(
                opener,
                action,
                final_url,
                base_fields,
                service_date,
                "GUARDAMAR",
                "ELCHE",
            )
            inbound = avanza._fetch_direction(
                opener,
                action,
                final_url,
                base_fields,
                service_date,
                "ELCHE",
                "GUARDAMAR",
            )
        except avanza.AlicanteScheduleError as exc:
            logging.warning(
                "Elche planner rejected %s: %s",
                service_date,
                exc,
            )
            continue

        fares = [
            item.fare
            for item in (outbound, inbound)
            if item.fare is not None
        ]
        fare = None
        if len(fares) == 2:
            cents = min(item.cents for item in fares)
            fare = IntercityFare(
                cents=cents,
                from_price=(
                    any(item.from_price for item in fares)
                    or len({item.cents for item in fares}) > 1
                ),
            )

        result[service_date] = IntercitySchedule(
            service_date=service_date,
            outbound=outbound.departures,
            inbound=inbound.departures,
            fare=fare,
        )

    if not result:
        raise IntercityScheduleError(
            "Elche planner has no validated requested dates"
        )
    return result


def fetch_bundle(
    today: date,
    cached: Optional[IntercityScheduleBundle],
) -> IntercityScheduleBundle:
    del cached
    tomorrow = today + timedelta(days=1)
    schedules = fetch_schedules((today, tomorrow))
    current = schedules.get(today)
    if current is None:
        raise IntercityScheduleError(
            "Elche planner has no validated current date"
        )
    return IntercityScheduleBundle(
        current=current,
        next=schedules.get(tomorrow),
    )


def build_message(
    schedule: IntercitySchedule,
    today: date,
    transport_link: str,
) -> str:
    fare_line = ""
    if schedule.fare is not None:
        fare_line = (
            "\n\n🎟 <b>Билет в одну сторону:</b> "
            + fare_amount(schedule.fare)
        )
    message = with_footer(
        "🚌 <b>Гуардамар ↔ Elche</b>\n"
        "Доехать можно без пересадок на автобусе Avanza.\n\n"
        "По дороге автобус заезжает в San Fulgencio, Dolores, "
        "Catral и Crevillente.\n\n"
        f"🗓 <b>{date_label(schedule.service_date, today)}</b>\n\n"
        "➡️ <b>Гуардамар → Elche</b>\n"
        + format_times(schedule.outbound)
        + "\n\n⬅️ <b>Elche → Гуардамар</b>\n"
        + format_times(schedule.inbound)
        + fare_line
        + "\n\n📍 <b>Откуда и куда</b>\n"
        '<a href="'
        + html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)
        + '">'
        "автовокзал Гуардамара</a>"
        " ↔ "
        '<a href="https://www.google.com/maps/search/?api=1&amp;query='
        'Av.+Vicente+Quiles%2C+Elche">'
        "остановка на проспекте Vicente Quiles в Elche</a>"
        + "\n\n"
        + f'🕒 <a href="{avanza.PLANNER_URL}">'
        "Найти расписание на другую дату</a>"
        + '\n\n⬅️ <a href="'
        + transport_link
        + '"><b>К списку транспорта</b></a>'
    )
    if (
        len(message) > 4096
        or message.count(FOOTER) != 1
        or "—" in message
    ):
        raise IntercityScheduleError("Elche message is not Telegram-safe")
    return message
