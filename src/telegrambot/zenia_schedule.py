"""Exact-date Guardamar ↔ Zenia Boulevard timetable from the Avanza public planner."""

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

ZENIA_ROUTE_KEY = "zenia"
ORIGIN = "GUARDAMAR"
DESTINATION = "C.C. BOULEVAR ZENIA"
ZENIA_MAP_URL = (
    "https://www.google.com/maps/search/?api=1&"
    "query=37.9292298333%2C-0.7346398333"
)


def fetch_schedules(
    service_dates: tuple[date, ...],
) -> Dict[date, IntercitySchedule]:
    """Fetch Guardamar ↔ Zenia Boulevard for exact dates via Avanza."""

    wanted_dates = tuple(dict.fromkeys(service_dates))
    if not wanted_dates or len(wanted_dates) > 3:
        raise IntercityScheduleError("Zenia planner date request is invalid")

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
            f"Zenia planner is unavailable: {exc}"
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
                ORIGIN,
                DESTINATION,
            )
            inbound = avanza._fetch_direction(
                opener,
                action,
                final_url,
                base_fields,
                service_date,
                DESTINATION,
                ORIGIN,
            )
        except avanza.AlicanteScheduleError as exc:
            logging.warning(
                "Zenia planner rejected %s: %s",
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
            "Zenia planner has no validated requested dates"
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
            "Zenia planner has no validated current date"
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
        "🛍 <b>Гуардамар ↔ Zenia Boulevard</b>\n"
        "До торгового центра можно доехать без пересадок "
        "на автобусе Avanza.\n\n"
        "🚌 <b>Маршрут:</b> Alicante ↔ Pilar de la Horadada\n"
        "Из Гуардамара садитесь в сторону <b>Pilar de la Horadada</b>. "
        "Обратно от Zenia Boulevard садитесь в сторону <b>Alicante</b>.\n\n"
        f"🗓 <b>{date_label(schedule.service_date, today)}</b>\n\n"
        "➡️ <b>Гуардамар → Zenia Boulevard</b>\n"
        + format_times(schedule.outbound)
        + "\n\n⬅️ <b>Zenia Boulevard → Гуардамар</b>\n"
        + format_times(schedule.inbound)
        + fare_line
        + "\n\n📍 <b>Откуда и куда</b>\n"
        '<a href="'
        + html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)
        + '">автовокзал Гуардамара</a>'
        " ↔ "
        '<a href="'
        + html.escape(ZENIA_MAP_URL, quote=True)
        + '">ТЦ Zenia Boulevard</a>'
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
        raise IntercityScheduleError("Zenia message is not Telegram-safe")
    return message
