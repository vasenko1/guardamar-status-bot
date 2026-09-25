"""Exact-date Guardamar ↔ Orihuela timetable and fare from Bus Sigüenza."""

import hashlib
import html
import logging
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

from . import airport_schedule as bus
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

ORIHUELA_ROUTE_KEY = "inland"
ORIGIN = "GUARDAMAR DEL SEGURA"
DESTINATION = "ORIHUELA"
MAX_TRIPS_PER_DIRECTION = 24
FARE_ROW_DISTANCES = (
    37, 31, 28, 25, 22, 15, 12, 8, 6, 12, 16, 14, 10, 10,
)


def _wrap_source_error(exc: Exception) -> IntercityScheduleError:
    return IntercityScheduleError(f"Orihuela source is unavailable: {exc}")


def _fare_urls(page: str) -> tuple[str, ...]:
    active = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    raw = re.findall(
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        active,
        flags=re.I,
    )
    urls = tuple(dict.fromkeys(
        bus._normalized_url(
            urllib.parse.urljoin(bus.PLANNER_URL, html.unescape(value))
        )
        for value in raw
    ))
    return tuple(value for value in urls if bus._allowed_fare_url(value))


def _parse_schedule_response(
    payload: bytes,
    service_date: date,
    final_url: str,
) -> tuple[IntercitySchedule, Optional[str]]:
    if not bus._allowed_url(final_url):
        raise IntercityScheduleError(
            "Orihuela timetable URL is not allowed"
        )
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntercityScheduleError(
            "Orihuela timetable is not UTF-8"
        ) from exc

    active = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    panels = re.findall(
        r'<h3[^>]*class=["\']panel-title["\'][^>]*>(.*?)</h3>'
        r".*?<table[^>]*>(.*?)</table>",
        active,
        flags=re.I | re.S,
    )
    routes: Dict[str, tuple[str, ...]] = {}
    for raw_title, table in panels:
        title = bus._plain_fragment(raw_title).casefold()
        if "guardamar del segura" not in title or "orihuela" not in title:
            continue
        if title.startswith("guardamar del segura"):
            key = "outbound"
        elif title.startswith("orihuela"):
            key = "inbound"
        else:
            raise IntercityScheduleError(
                "Orihuela timetable direction is invalid"
            )
        times = tuple(re.findall(
            r">\s*((?:[01][0-9]|2[0-3]):[0-5][0-9])\s*</button>",
            table,
            flags=re.I,
        ))
        if (
            not 1 <= len(times) <= MAX_TRIPS_PER_DIRECTION
            or len(set(times)) != len(times)
            or tuple(sorted(times)) != times
            or not all(bus.TIME_PATTERN.fullmatch(value) for value in times)
            or key in routes
        ):
            raise IntercityScheduleError(
                "Orihuela timetable times are invalid"
            )
        routes[key] = times

    if set(routes) != {"outbound", "inbound"}:
        raise IntercityScheduleError(
            "Orihuela timetable directions are incomplete"
        )

    fare_urls = _fare_urls(page)
    fare_url = fare_urls[0] if len(fare_urls) == 1 else None
    if fare_url is None:
        logging.warning(
            "Orihuela fare link is missing or ambiguous; omitting price"
        )

    return (
        IntercitySchedule(
            service_date=service_date,
            outbound=routes["outbound"],
            inbound=routes["inbound"],
            fare=None,
        ),
        fare_url,
    )


def _fetch_schedule(
    service_date: date,
) -> tuple[IntercitySchedule, Optional[str]]:
    body = urllib.parse.urlencode({
        "accion": 3,
        "idioma": "es",
        "FECHASALIDA": service_date.strftime("%d/%m/%Y"),
        "ORIGEN": ORIGIN,
        "DESTINO": DESTINATION,
    }).encode("ascii")
    request = urllib.request.Request(
        bus.SEARCH_URL,
        data=body,
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": bus.USER_AGENT,
        },
        method="POST",
    )
    try:
        payload, final_url, headers, status = bus._open_bounded(
            request,
            bus.HTML_LIMIT_BYTES,
        )
    except bus.AirportScheduleError as exc:
        raise _wrap_source_error(exc) from exc
    if status != 200 or headers.get_content_type() != "text/html":
        raise IntercityScheduleError(
            "Orihuela timetable response is invalid"
        )
    return _parse_schedule_response(payload, service_date, final_url)


def _fare_effective_date(text: str) -> date:
    match = re.search(
        r"FECHA ENTRADA EN VIGOR:\s*(\d{1,2})\s+"
        r"([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})",
        text,
    )
    if match is None or match.group(2) not in bus.MONTHS_ES:
        raise IntercityScheduleError(
            "Orihuela fare effective date is invalid"
        )
    try:
        return date(
            int(match.group(3)),
            bus.MONTHS_ES[match.group(2)],
            int(match.group(1)),
        )
    except ValueError as exc:
        raise IntercityScheduleError(
            "Orihuela fare effective date is invalid"
        ) from exc


def parse_fare_pdf(
    payload: bytes,
    source_url: str,
    *,
    etag: Optional[str],
    last_modified: Optional[str],
) -> IntercityFare:
    """Extract only the BASE GENERAL Orihuela ↔ Guardamar fare."""

    with TemporaryDirectory() as directory:
        path = Path(directory) / "fare.pdf"
        path.write_bytes(payload)
        try:
            info = bus._run(["pdfinfo", str(path)]).decode(
                "utf-8", "replace"
            )
            pages_match = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", info)
            encrypted = re.search(r"(?mi)^Encrypted:\s*no\s*$", info)
            if pages_match is None or encrypted is None:
                raise IntercityScheduleError(
                    "Orihuela fare PDF metadata is invalid"
                )
            pages = int(pages_match.group(1))
            if not 1 <= pages <= 5:
                raise IntercityScheduleError(
                    "Orihuela fare PDF page count is invalid"
                )
            text = bus._run([
                "pdftotext",
                "-layout",
                "-f",
                "1",
                "-l",
                str(pages),
                str(path),
                "-",
            ]).decode("utf-8", "replace")
        except bus.AirportScheduleError as exc:
            raise _wrap_source_error(exc) from exc

    required = (
        "Dirección General de Transportes y Logística",
        "CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT",
        "LÍNEA 1: ORIHUELA - (LAS DAYAS A LA DEMANDA) - GUARDAMAR DEL SEGURA",
        "FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO",
    )
    if any(marker not in text for marker in required):
        raise IntercityScheduleError(
            "Orihuela fare PDF identity is invalid"
        )

    effective_date = _fare_effective_date(text)
    base_start = text.find("TARIFA BASE GENERAL", text.find(required[2]))
    senior_start = text.find("TARIFA MAYORES DE 65 AÑOS", base_start)
    if base_start < 0 or senior_start < 0:
        raise IntercityScheduleError(
            "Orihuela base fare section is missing"
        )
    base = text[base_start:senior_start]

    candidates: list[int] = []
    for line in base.splitlines():
        pairs = [
            (int(distance), int(euros) * 100 + int(cents))
            for distance, euros, cents in re.findall(
                r"(\d+)\s+(\d+),(\d{2})\s*€",
                line,
            )
        ]
        if len(pairs) < len(FARE_ROW_DISTANCES):
            continue
        distances = tuple(
            distance
            for distance, _ in pairs[:len(FARE_ROW_DISTANCES)]
        )
        if distances == FARE_ROW_DISTANCES:
            candidates.append(pairs[0][1])

    if len(candidates) != 1 or not 100 <= candidates[0] <= 2_000:
        raise IntercityScheduleError(
            "Orihuela base fare row is ambiguous"
        )

    return IntercityFare(
        cents=candidates[0],
        from_price=False,
        effective_date=effective_date,
        source_url=source_url,
        etag=etag,
        last_modified=last_modified,
        pdf_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _refresh_fare(
    fare_url: Optional[str],
    cached: Optional[IntercityFare],
) -> Optional[IntercityFare]:
    if fare_url is None:
        return None
    same_source = (
        cached is not None
        and cached.source_url == fare_url
        and cached.pdf_sha256 is not None
    )
    try:
        downloaded = bus.download_fare_pdf(
            fare_url,
            cached.etag if same_source else None,
            cached.last_modified if same_source else None,
        )
    except bus.AirportScheduleError as exc:
        if same_source:
            logging.warning(
                "Orihuela fare unavailable; keeping verified fare: %s",
                exc,
            )
            return cached
        logging.warning(
            "Orihuela fare unavailable; omitting price: %s",
            exc,
        )
        return None

    if downloaded is None:
        if cached is None:
            raise IntercityScheduleError(
                "Orihuela fare returned 304 without accepted state"
            )
        return cached

    digest = hashlib.sha256(downloaded.payload).hexdigest()
    if cached is not None and digest == cached.pdf_sha256:
        return IntercityFare(
            cents=cached.cents,
            from_price=False,
            effective_date=cached.effective_date,
            source_url=downloaded.url,
            etag=downloaded.etag,
            last_modified=downloaded.last_modified,
            pdf_sha256=digest,
        )

    try:
        confirmation = bus.download_fare_pdf(
            downloaded.url,
            None,
            None,
            force=True,
        )
        if (
            confirmation is None
            or confirmation.payload != downloaded.payload
        ):
            raise IntercityScheduleError(
                "changed Orihuela fare PDF is not stable"
            )
        return parse_fare_pdf(
            downloaded.payload,
            downloaded.url,
            etag=downloaded.etag,
            last_modified=downloaded.last_modified,
        )
    except (bus.AirportScheduleError, IntercityScheduleError) as exc:
        logging.warning(
            "Changed Orihuela fare rejected; omitting price: %s",
            exc,
        )
        return None


def fetch_bundle(
    today: date,
    cached: Optional[IntercityScheduleBundle],
) -> IntercityScheduleBundle:
    tomorrow = today + timedelta(days=1)
    schedules: Dict[date, IntercitySchedule] = {}
    fare_urls: list[str] = []

    for service_date in (today, tomorrow):
        try:
            schedule, fare_url = _fetch_schedule(service_date)
        except IntercityScheduleError as exc:
            logging.warning(
                "Orihuela timetable rejected %s: %s",
                service_date,
                exc,
            )
            continue
        schedules[service_date] = schedule
        if fare_url is not None:
            fare_urls.append(fare_url)

    current = schedules.get(today)
    if current is None:
        raise IntercityScheduleError(
            "Orihuela source has no validated current date"
        )

    unique_fare_urls = tuple(dict.fromkeys(fare_urls))
    fare_url = (
        unique_fare_urls[0]
        if len(unique_fare_urls) == 1
        else None
    )
    cached_fare = (
        cached.current.fare
        if cached is not None
        else None
    )
    fare = _refresh_fare(fare_url, cached_fare)

    def attach(schedule: Optional[IntercitySchedule]):
        if schedule is None:
            return None
        return IntercitySchedule(
            service_date=schedule.service_date,
            outbound=schedule.outbound,
            inbound=schedule.inbound,
            fare=fare,
        )

    return IntercityScheduleBundle(
        current=attach(current),
        next=attach(schedules.get(tomorrow)),
    )


def build_message(
    schedule: IntercitySchedule,
    today: date,
    transport_link: str,
) -> str:
    fare_line = ""
    if (
        schedule.fare is not None
        and (
            schedule.fare.effective_date is None
            or schedule.service_date >= schedule.fare.effective_date
        )
    ):
        amount = fare_amount(schedule.fare)
        if schedule.fare.source_url is not None:
            fare_line = (
                '\n\n🎟 <b>Билет в одну сторону:</b> <a href="'
                + html.escape(schedule.fare.source_url, quote=True)
                + '">'
                + amount
                + "</a>"
            )
        else:
            fare_line = (
                "\n\n🎟 <b>Билет в одну сторону:</b> " + amount
            )

    message = with_footer(
        "🚌 <b>Гуардамар ↔ Orihuela</b>\n"
        "Доехать можно без пересадок на автобусе Bus Sigüenza.\n\n"
        "По дороге автобус заезжает в Daya Vieja, Rojales, "
        "Formentera del Segura, Las Heredades, Daya Nueva, Almoradí, "
        "Hospital Vega Baja, Benejúzar, Jacarilla и Bigastro.\n\n"
        f"🗓 <b>{date_label(schedule.service_date, today)}</b>\n\n"
        "➡️ <b>Гуардамар → Orihuela</b>\n"
        + format_times(schedule.outbound)
        + "\n\n⬅️ <b>Orihuela → Гуардамар</b>\n"
        + format_times(schedule.inbound)
        + fare_line
        + "\n\n📍 <b>Откуда и куда</b>\n"
        '<a href="https://www.google.com/maps/search/?api=1&amp;query='
        'Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">'
        "автовокзал Гуардамара</a>"
        " ↔ "
        '<a href="https://www.google.com/maps/search/?api=1&amp;query='
        'Estaci%C3%B3n+de+Autobuses%2C+Orihuela">'
        "автовокзал в Orihuela</a>"
        + "\n\n"
        + f'🕒 <a href="{bus.PLANNER_URL}">'
        "Найти расписание на другую дату</a>"
        + '\n\n⬅️ <a href="'
        + html.escape(transport_link, quote=True)
        + '"><b>К списку транспорта</b></a>'
    )
    if (
        len(message) > 4096
        or message.count(FOOTER) != 1
        or "—" in message
    ):
        raise IntercityScheduleError(
            "Orihuela message is not Telegram-safe"
        )
    return message
