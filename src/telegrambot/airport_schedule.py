"""Bounded daily Bus Sigüenza airport timetable and fare synchronization."""

import asyncio
import hashlib
import html
import http.client
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .branding import FOOTER, with_footer
from .pinned import PinnedGuideState, build_leaf_message, telegram_message_link
from .state import StateError
from .telegram import TelegramError

SEARCH_URL = "https://www.bus-siguenza.com/wbus/procesa.php"
PLANNER_URL = "https://www.bus-siguenza.com/index.php?page=urbano"
ALLOWED_HOST = "www.bus-siguenza.com"
HTML_LIMIT_BYTES = 160_000
PDF_LIMIT_BYTES = 5_000_000
REQUEST_TIMEOUT_SECONDS = 20
PROCESS_TIMEOUT_SECONDS = 30
TLS_CERT_LIMIT_BYTES = 16_384
TLS_INTERMEDIATE_HOST = re.compile(r"^[a-z0-9-]+\.i\.lencr\.org$")
STATE_VERSION = 1
USER_AGENT = "GuardamarMorningDigest/0.13"
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_ES = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

SendText = Callable[[str], Awaitable[int]]
EditText = Callable[[int, str], Awaitable[None]]


class AirportScheduleError(RuntimeError):
    """Safe bounded failure while reading the official airport service."""


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise AirportScheduleError(
                "airport source redirected outside allowlist"
            )
        return super().redirect_request(
            request, fp, code, msg, headers, newurl
        )


class _IntermediateRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_intermediate_url(newurl):
            raise AirportScheduleError(
                "TLS intermediate redirected outside allowlist"
            )
        return super().redirect_request(
            request, fp, code, msg, headers, newurl
        )


@dataclass(frozen=True)
class Fare:
    cents: int
    effective_date: date
    source_url: str
    etag: Optional[str]
    last_modified: Optional[str]
    pdf_sha256: str


@dataclass(frozen=True)
class AirportSchedule:
    service_date: date
    to_airport: tuple[str, ...]
    from_airport: tuple[str, ...]
    guardamar_coordinates: str
    airport_coordinates: str
    fare: Optional[Fare]


@dataclass(frozen=True)
class _SearchResult:
    schedule: AirportSchedule
    fare_url: Optional[str]


@dataclass(frozen=True)
class _DownloadedPdf:
    payload: bytes
    url: str
    etag: Optional[str]
    last_modified: Optional[str]


_BUS_TLS_CONTEXT: Optional[ssl.SSLContext] = None
_BUS_TLS_LOCK = threading.Lock()


def _allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == ALLOWED_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_fare_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        _allowed_url(url)
        and parsed.path.startswith("/wbus/tarifas/")
        and parsed.path.casefold().endswith(".pdf")
        and not parsed.fragment
    )


def _allowed_intermediate_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and TLS_INTERMEDIATE_HOST.fullmatch(parsed.hostname) is not None
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _missing_issuer(exc: urllib.error.URLError) -> bool:
    reason = exc.reason
    return isinstance(reason, ssl.SSLCertVerificationError) and (
        getattr(reason, "verify_code", None) in (20, 21)
        or "unable to get local issuer certificate" in str(reason).casefold()
        or "unable to verify the first certificate" in str(reason).casefold()
    )


def _leaf_certificate() -> bytes:
    unverified = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(
            (ALLOWED_HOST, 443), timeout=REQUEST_TIMEOUT_SECONDS
        ) as connection:
            with unverified.wrap_socket(
                connection, server_hostname=ALLOWED_HOST
            ) as tls:
                certificate = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError, TimeoutError) as exc:
        raise AirportScheduleError(
            "airport TLS certificate is unavailable"
        ) from exc
    if not certificate or len(certificate) > TLS_CERT_LIMIT_BYTES:
        raise AirportScheduleError("airport TLS certificate is invalid")
    return certificate


def _intermediate_url(certificate: bytes) -> str:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "leaf.der"
        path.write_bytes(certificate)
        try:
            result = subprocess.run(
                [
                    "openssl", "x509", "-inform", "DER", "-in", str(path),
                    "-noout", "-ext", "authorityInfoAccess",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise AirportScheduleError(
                "required TLS tool is missing: openssl"
            ) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise AirportScheduleError(
                "airport TLS certificate could not be inspected"
            ) from exc
    urls = re.findall(
        r"CA Issuers\s*-\s*URI:(https?://[^\s]+)",
        result.stdout.decode("ascii", "replace"),
        flags=re.I,
    )
    if len(urls) != 1:
        raise AirportScheduleError("airport TLS issuer is ambiguous")
    parsed = urllib.parse.urlparse(urls[0])
    secure = urllib.parse.urlunparse(parsed._replace(scheme="https"))
    if not _allowed_intermediate_url(secure):
        raise AirportScheduleError("airport TLS issuer is not allowed")
    return secure


def _download_intermediate(url: str) -> bytes:
    if not _allowed_intermediate_url(url):
        raise AirportScheduleError("TLS intermediate URL is not allowed")
    opener = urllib.request.build_opener(_IntermediateRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/pkix-cert",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise AirportScheduleError(
            "TLS intermediate is unavailable"
        ) from exc
    with response:
        final_url = response.geturl()
        payload = response.read(TLS_CERT_LIMIT_BYTES + 1)
        if (
            response.status != 200
            or not _allowed_intermediate_url(final_url)
            or response.headers.get_content_type()
            != "application/pkix-cert"
            or not 1 <= len(payload) <= TLS_CERT_LIMIT_BYTES
        ):
            raise AirportScheduleError("TLS intermediate is invalid")
        return payload


def _repaired_tls_context() -> ssl.SSLContext:
    global _BUS_TLS_CONTEXT
    with _BUS_TLS_LOCK:
        if _BUS_TLS_CONTEXT is not None:
            return _BUS_TLS_CONTEXT
        certificate = _leaf_certificate()
        intermediate = _download_intermediate(
            _intermediate_url(certificate)
        )
        try:
            pem = ssl.DER_cert_to_PEM_cert(intermediate)
            context = ssl.create_default_context()
            context.load_verify_locations(cadata=pem)
        except (ValueError, ssl.SSLError) as exc:
            raise AirportScheduleError(
                "TLS intermediate could not be loaded"
            ) from exc
        _BUS_TLS_CONTEXT = context
        return context


def _normalized_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(
        path=urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/"),
    ))


def _open_bounded(
    request: urllib.request.Request,
    limit: int,
) -> tuple[bytes, str, object, int]:
    if not _allowed_url(request.full_url):
        raise AirportScheduleError("airport source URL is not allowed")

    def open_with(context: Optional[ssl.SSLContext]):
        handlers = [_AllowedRedirectHandler()]
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        return urllib.request.build_opener(*handlers).open(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        )

    try:
        try:
            response = open_with(_BUS_TLS_CONTEXT)
        except urllib.error.URLError as exc:
            if not _missing_issuer(exc):
                raise
            response = open_with(_repaired_tls_context())
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return b"", request.full_url, exc.headers, 304
        raise AirportScheduleError(
            f"airport source returned HTTP {exc.code}"
        ) from None
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise AirportScheduleError("airport source is unavailable") from exc
    with response:
        final_url = response.geturl()
        if not _allowed_url(final_url):
            raise AirportScheduleError(
                "airport source redirected outside allowlist"
            )
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise AirportScheduleError("airport source response is too large")
        return payload, final_url, response.headers, response.status


def _plain_fragment(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def _coordinates_from_table(table: str) -> str:
    coordinates = []
    for raw_url in re.findall(r'href=["\']([^"\']+)["\']', table, re.I):
        parsed = urllib.parse.urlparse(html.unescape(raw_url))
        if parsed.scheme != "https" or parsed.hostname != "www.google.com":
            continue
        query = urllib.parse.parse_qs(parsed.query).get("query", [])
        if len(query) == 1 and re.fullmatch(
            r"-?[0-9]{1,3}(?:\.[0-9]+)?,-?[0-9]{1,3}(?:\.[0-9]+)?",
            query[0],
        ):
            coordinates.append(query[0])
    unique = tuple(dict.fromkeys(coordinates))
    if len(unique) != 1:
        raise AirportScheduleError("airport timetable has ambiguous stops")
    return unique[0]


def _validate_coordinates(value: str, *, airport: bool) -> None:
    latitude_text, longitude_text = value.split(",", 1)
    latitude = float(latitude_text)
    longitude = float(longitude_text)
    bounds = (
        (38.20, 38.40, -0.70, -0.40)
        if airport
        else (38.00, 38.20, -0.80, -0.50)
    )
    if not (
        bounds[0] <= latitude <= bounds[1]
        and bounds[2] <= longitude <= bounds[3]
    ):
        raise AirportScheduleError("airport timetable stop is out of bounds")


def parse_search_response(
    payload: bytes,
    service_date: date,
    final_url: str = SEARCH_URL,
) -> _SearchResult:
    """Parse two exact directions, their stops, and the current fare link."""

    if not _allowed_url(final_url):
        raise AirportScheduleError("airport timetable URL is not allowed")
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AirportScheduleError("airport timetable is not UTF-8") from exc
    active = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    panels = re.findall(
        r'<h3[^>]*class=["\']panel-title["\'][^>]*>(.*?)</h3>'
        r".*?<table[^>]*>(.*?)</table>",
        active,
        flags=re.I | re.S,
    )
    routes = {}
    for raw_title, table in panels:
        title = _plain_fragment(raw_title).casefold()
        if "guardamar del segura" not in title or "aeropuerto" not in title:
            continue
        if title.startswith("guardamar del segura"):
            key = "to_airport"
        elif title.startswith("aeropuerto"):
            key = "from_airport"
        else:
            raise AirportScheduleError("airport timetable direction is invalid")
        times = tuple(re.findall(
            r">\s*((?:[01][0-9]|2[0-3]):[0-5][0-9])\s*</button>",
            table,
            flags=re.I,
        ))
        if (
            not 1 <= len(times) <= 12
            or len(set(times)) != len(times)
            or tuple(sorted(times)) != times
            or not all(TIME_PATTERN.fullmatch(value) for value in times)
            or key in routes
        ):
            raise AirportScheduleError("airport timetable times are invalid")
        routes[key] = (times, _coordinates_from_table(table))
    if set(routes) != {"to_airport", "from_airport"}:
        raise AirportScheduleError("airport timetable directions are incomplete")
    guardamar_coordinates = routes["to_airport"][1]
    airport_coordinates = routes["from_airport"][1]
    _validate_coordinates(guardamar_coordinates, airport=False)
    _validate_coordinates(airport_coordinates, airport=True)

    raw_pdf_links = re.findall(
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        active,
        flags=re.I,
    )
    fare_urls = tuple(dict.fromkeys(
        _normalized_url(
            urllib.parse.urljoin(PLANNER_URL, html.unescape(value))
        )
        for value in raw_pdf_links
    ))
    fare_urls = tuple(
        value for value in fare_urls
        if _allowed_fare_url(value)
    )
    fare_url = fare_urls[0] if len(fare_urls) == 1 else None
    if fare_url is None:
        logging.warning("Airport fare link is missing or ambiguous; omitting price")
    schedule = AirportSchedule(
        service_date=service_date,
        to_airport=routes["to_airport"][0],
        from_airport=routes["from_airport"][0],
        guardamar_coordinates=guardamar_coordinates,
        airport_coordinates=airport_coordinates,
        fare=None,
    )
    return _SearchResult(schedule=schedule, fare_url=fare_url)


def fetch_schedule(service_date: date) -> _SearchResult:
    body = urllib.parse.urlencode({
        "accion": 3,
        "idioma": "es",
        "FECHASALIDA": service_date.strftime("%d/%m/%Y"),
        "ORIGEN": "GUARDAMAR DEL SEGURA",
        "DESTINO": "AEROPUERTO DE ALICANTE - ELCHE",
    }).encode("ascii")
    request = urllib.request.Request(
        SEARCH_URL,
        data=body,
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    payload, final_url, headers, status = _open_bounded(
        request, HTML_LIMIT_BYTES
    )
    if status != 200 or headers.get_content_type() != "text/html":
        raise AirportScheduleError("airport timetable response is invalid")
    return parse_search_response(payload, service_date, final_url)


def download_fare_pdf(
    url: str,
    etag: Optional[str],
    last_modified: Optional[str],
    *,
    force: bool = False,
) -> Optional[_DownloadedPdf]:
    if not _allowed_fare_url(url):
        raise AirportScheduleError("airport fare URL is not allowed")
    headers = {"Accept": "application/pdf", "User-Agent": USER_AGENT}
    if not force and etag:
        headers["If-None-Match"] = etag
    if not force and last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    payload, final_url, response_headers, status = _open_bounded(
        request, PDF_LIMIT_BYTES
    )
    if status == 304:
        return None
    if (
        status != 200
        or not _allowed_fare_url(final_url)
        or response_headers.get_content_type() != "application/pdf"
        or not payload.startswith(b"%PDF-")
    ):
        raise AirportScheduleError("airport fare PDF is invalid")
    return _DownloadedPdf(
        payload=payload,
        url=final_url,
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
    )


def _run(command: list[str]) -> bytes:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
        ).stdout
    except FileNotFoundError as exc:
        raise AirportScheduleError(
            f"required PDF tool is missing: {command[0]}"
        ) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise AirportScheduleError("airport fare PDF could not be read") from exc


def parse_fare_pdf(payload: bytes, source_url: str, headers: _DownloadedPdf) -> Fare:
    """Extract only the standard Guardamar-airport fare from official line 3."""

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fare.pdf"
        path.write_bytes(payload)
        info = _run(["pdfinfo", str(path)]).decode("utf-8", "replace")
        pages_match = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", info)
        encrypted = re.search(r"(?mi)^Encrypted:\s*no\s*$", info)
        if pages_match is None or encrypted is None:
            raise AirportScheduleError("airport fare PDF metadata is invalid")
        pages = int(pages_match.group(1))
        if not 1 <= pages <= 5:
            raise AirportScheduleError("airport fare PDF page count is invalid")
        text = _run([
            "pdftotext", "-layout", "-f", "1", "-l", str(pages),
            str(path), "-",
        ]).decode("utf-8", "replace")
    required = (
        "Dirección General de Transportes y Logística",
        "CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT",
        "LÍNEA 3: ALMORADÍ - GUARDAMAR - AEROPUERTO",
        "FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO",
    )
    if any(marker not in text for marker in required):
        raise AirportScheduleError("airport fare PDF identity is invalid")
    effective_match = re.search(
        r"FECHA ENTRADA EN VIGOR:\s*(\d{1,2})\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})",
        text,
    )
    if effective_match is None or effective_match.group(2) not in MONTHS_ES:
        raise AirportScheduleError("airport fare effective date is invalid")
    try:
        effective_date = date(
            int(effective_match.group(3)),
            MONTHS_ES[effective_match.group(2)],
            int(effective_match.group(1)),
        )
    except ValueError as exc:
        raise AirportScheduleError(
            "airport fare effective date is invalid"
        ) from exc
    base_start = text.find("TARIFA BASE GENERAL", text.find(required[2]))
    senior_start = text.find("TARIFA MAYORES DE 65 AÑOS", base_start)
    if base_start < 0 or senior_start < 0:
        raise AirportScheduleError("airport base fare section is missing")
    base_section = text[base_start:senior_start]
    expected_stops = (
        "ALMORADÍ", "FORMENTERA DEL SEGURA", "ROJALES",
        "GUARDAMAR DEL SEGURA", "URBANIZACIÓN LA MARINA",
        "LA MARINA", "AEROPUERTO",
    )
    stop_cursor = 0
    for stop in expected_stops:
        position = base_section.find(stop, stop_cursor)
        if position < 0:
            raise AirportScheduleError("airport fare stop order is invalid")
        stop_cursor = position + len(stop)
    airport_lines = []
    for line in base_section.splitlines():
        position = line.find("AEROPUERTO")
        if position >= 0:
            airport_lines.append(line[:position + len("AEROPUERTO")])
    if len(airport_lines) != 1:
        raise AirportScheduleError("airport fare row is ambiguous")
    pairs = re.findall(r"(\d+)\s+(\d+),(\d{2})\s*€", airport_lines[0])
    if len(pairs) != 6:
        raise AirportScheduleError("airport fare row is invalid")
    distance, euros, cents = pairs[3]
    amount = int(euros) * 100 + int(cents)
    if not 20 <= int(distance) <= 50 or not 100 <= amount <= 2_000:
        raise AirportScheduleError("airport fare value is invalid")
    return Fare(
        cents=amount,
        effective_date=effective_date,
        source_url=source_url,
        etag=headers.etag,
        last_modified=headers.last_modified,
        pdf_sha256=hashlib.sha256(payload).hexdigest(),
    )


class AirportScheduleState:
    """One strict atomic normalized snapshot, never a raw source cache."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Optional[AirportSchedule]:
        if not self.path.exists():
            previous = self.path.with_name(
                f"{self.path.stem}.previous.json"
            )
            if not previous.exists():
                return None
            try:
                return self._decode(json.loads(
                    previous.read_text(encoding="utf-8")
                ))
            except (
                OSError, UnicodeDecodeError, json.JSONDecodeError, StateError
            ) as exc:
                raise StateError("airport schedule state is invalid") from exc
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._decode(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, StateError):
            previous = self.path.with_name(
                f"{self.path.stem}.previous.json"
            )
            try:
                raw = json.loads(previous.read_text(encoding="utf-8"))
                return self._decode(raw)
            except (
                OSError, UnicodeDecodeError, json.JSONDecodeError, StateError
            ) as exc:
                raise StateError("airport schedule state is invalid") from exc

    def _decode(self, raw: object) -> AirportSchedule:
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise StateError("airport schedule state is invalid")
        try:
            service_date = date.fromisoformat(raw["service_date"])
            to_airport = tuple(raw["to_airport"])
            from_airport = tuple(raw["from_airport"])
            guardamar = raw["guardamar_coordinates"]
            airport = raw["airport_coordinates"]
            raw_fare = raw.get("fare")
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError("airport schedule state is invalid") from exc
        if (
            not 1 <= len(to_airport) <= 12
            or not 1 <= len(from_airport) <= 12
            or not all(isinstance(value, str) for value in to_airport)
            or not all(isinstance(value, str) for value in from_airport)
            or len(set(to_airport)) != len(to_airport)
            or len(set(from_airport)) != len(from_airport)
            or tuple(sorted(to_airport)) != to_airport
            or tuple(sorted(from_airport)) != from_airport
            or not all(TIME_PATTERN.fullmatch(value) for value in to_airport)
            or not all(TIME_PATTERN.fullmatch(value) for value in from_airport)
            or not isinstance(guardamar, str)
            or not isinstance(airport, str)
        ):
            raise StateError("airport schedule state is invalid")
        try:
            _validate_coordinates(guardamar, airport=False)
            _validate_coordinates(airport, airport=True)
        except (AirportScheduleError, ValueError) as exc:
            raise StateError("airport schedule state is invalid") from exc
        fare = None
        if raw_fare is not None:
            if not isinstance(raw_fare, dict):
                raise StateError("airport schedule state is invalid")
            try:
                fare = Fare(
                    cents=int(raw_fare["cents"]),
                    effective_date=date.fromisoformat(
                        raw_fare["effective_date"]
                    ),
                    source_url=raw_fare["source_url"],
                    etag=raw_fare.get("etag"),
                    last_modified=raw_fare.get("last_modified"),
                    pdf_sha256=raw_fare["pdf_sha256"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise StateError("airport schedule state is invalid") from exc
            if (
                not 100 <= fare.cents <= 2_000
                or not isinstance(fare.source_url, str)
                or not _allowed_fare_url(fare.source_url)
                or not isinstance(fare.pdf_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", fare.pdf_sha256)
                or any(
                    value is not None
                    and (not isinstance(value, str) or len(value) > 200)
                    for value in (fare.etag, fare.last_modified)
                )
            ):
                raise StateError("airport schedule state is invalid")
        return AirportSchedule(
            service_date=service_date,
            to_airport=to_airport,
            from_airport=from_airport,
            guardamar_coordinates=guardamar,
            airport_coordinates=airport,
            fare=fare,
        )

    def write(self, schedule: AirportSchedule) -> None:
        fare = schedule.fare
        payload = {
            "version": STATE_VERSION,
            "service_date": schedule.service_date.isoformat(),
            "to_airport": list(schedule.to_airport),
            "from_airport": list(schedule.from_airport),
            "guardamar_coordinates": schedule.guardamar_coordinates,
            "airport_coordinates": schedule.airport_coordinates,
            "fare": None if fare is None else {
                "cents": fare.cents,
                "effective_date": fare.effective_date.isoformat(),
                "source_url": fare.source_url,
                "etag": fare.etag,
                "last_modified": fare.last_modified,
                "pdf_sha256": fare.pdf_sha256,
            },
        }
        self._decode(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}."
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            previous = self.path.with_name(
                f"{self.path.stem}.previous.json"
            )
            if self.path.exists():
                os.replace(self.path, previous)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _refresh_fare(
    fare_url: str,
    cached: Optional[Fare],
) -> Optional[Fare]:
    same_source = cached is not None and cached.source_url == fare_url
    try:
        downloaded = download_fare_pdf(
            fare_url,
            cached.etag if same_source else None,
            cached.last_modified if same_source else None,
        )
    except AirportScheduleError as exc:
        if same_source:
            logging.warning(
                "Airport fare unavailable; keeping verified fare: %s", exc
            )
            return cached
        logging.warning("Airport fare unavailable; omitting price: %s", exc)
        return None
    if downloaded is None:
        if cached is None:
            raise AirportScheduleError(
                "airport fare returned 304 without accepted state"
            )
        return cached
    digest = hashlib.sha256(downloaded.payload).hexdigest()
    if cached is not None and digest == cached.pdf_sha256:
        return Fare(
            cents=cached.cents,
            effective_date=cached.effective_date,
            source_url=downloaded.url,
            etag=downloaded.etag,
            last_modified=downloaded.last_modified,
            pdf_sha256=digest,
        )
    try:
        confirmation = download_fare_pdf(
            downloaded.url, None, None, force=True
        )
        if confirmation is None or confirmation.payload != downloaded.payload:
            raise AirportScheduleError(
                "changed airport fare PDF is not stable"
            )
        return parse_fare_pdf(
            downloaded.payload, downloaded.url, downloaded
        )
    except AirportScheduleError as exc:
        logging.warning("Changed airport fare rejected; omitting price: %s", exc)
        return None


def build_airport_message(
    schedule: AirportSchedule,
    today: date,
    transport_link: str,
) -> str:
    if schedule.service_date == today:
        date_label = (
            f"Сегодня, {today.day} {MONTHS_RU[today.month - 1]}"
        )
    else:
        date_label = (
            f"Расписание на {schedule.service_date.day} "
            f"{MONTHS_RU[schedule.service_date.month - 1]}"
        )
    guardamar_map = (
        "https://www.google.com/maps/search/?api=1&amp;query="
        + urllib.parse.quote(schedule.guardamar_coordinates, safe="")
    )
    airport_map = (
        "https://www.google.com/maps/search/?api=1&amp;query="
        + urllib.parse.quote(schedule.airport_coordinates, safe="")
    )
    fare_line = ""
    if (
        schedule.fare is not None
        and schedule.service_date >= schedule.fare.effective_date
    ):
        amount = f"{schedule.fare.cents // 100},{schedule.fare.cents % 100:02d}"
        fare_line = (
            "\n💶 <a href=\""
            + html.escape(schedule.fare.source_url, quote=True)
            + f'\">Обычный билет: {amount} €</a>'
        )
    message = with_footer(
        "✈️ <b>Гуардамар ↔ аэропорт Alicante-Elche</b>\n"
        "Прямой автобус · Bus Sigüenza\n\n"
        f"🗓 <b>{date_label}</b>\n\n"
        "<b>Гуардамар → аэропорт</b>\n"
        + " · ".join(schedule.to_airport)
        + "\n\n<b>Аэропорт → Гуардамар</b>\n"
        + " · ".join(schedule.from_airport)
        + "\n\n⏱ Около 35 минут"
        + fare_line
        + "\n📍 <a href=\""
        + guardamar_map
        + "\">Estación de Autobuses</a> ↔ <a href=\""
        + airport_map
        + "\">остановка аэропорта</a>\n\n"
        + f'🔎 <a href="{PLANNER_URL}">Проверить расписание на другую дату</a>'
        + "\n\n⬅️ <a href=\""
        + transport_link
        + "\"><b>К списку транспорта</b></a>"
    )
    if len(message) > 4_096 or message.count(FOOTER) != 1 or "—" in message:
        raise AirportScheduleError("airport message is not Telegram-safe")
    return message


async def sync_airport_schedule(
    now: datetime,
    chat_id: str,
    pinned_state: PinnedGuideState,
    schedule_state: AirportScheduleState,
    send_text: SendText,
    edit_text: EditText,
) -> dict[str, int]:
    """Update one date-specific message and recover a deleted known message."""

    payload = await asyncio.to_thread(pinned_state.read_payload, chat_id)
    messages = payload["messages"]
    if "transport" not in messages or "airport" not in messages:
        raise AirportScheduleError("airport guide message is missing from state")
    cached = None
    try:
        cached = await asyncio.to_thread(schedule_state.read)
    except StateError as exc:
        logging.warning("Airport schedule state rejected: %s", exc)
    schedule = None
    try:
        result = await asyncio.to_thread(fetch_schedule, now.date())
        cached_fare = cached.fare if cached is not None else None
        fare = (
            await asyncio.to_thread(
                _refresh_fare, result.fare_url, cached_fare
            )
            if result.fare_url is not None
            else None
        )
        schedule = AirportSchedule(
            service_date=result.schedule.service_date,
            to_airport=result.schedule.to_airport,
            from_airport=result.schedule.from_airport,
            guardamar_coordinates=result.schedule.guardamar_coordinates,
            airport_coordinates=result.schedule.airport_coordinates,
            fare=fare,
        )
        await asyncio.to_thread(schedule_state.write, schedule)
    except AirportScheduleError as exc:
        logging.warning(
            "Airport timetable unavailable; keeping accepted message: %s", exc
        )
        schedule = cached
    transport_link = telegram_message_link(chat_id, messages["transport"])
    message = (
        build_airport_message(schedule, now.date(), transport_link)
        if schedule is not None
        else build_leaf_message("airport", transport_link)
    )
    message_id = messages["airport"]
    try:
        await edit_text(message_id, message)
        return dict(messages)
    except TelegramError as exc:
        if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
            return dict(messages)
        if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise
    try:
        new_id = await send_text(message)
    except TelegramError as exc:
        if exc.retryable and exc.server_status != 429:
            await asyncio.to_thread(
                pinned_state.mark_uncertain, chat_id, "airport"
            )
        raise
    messages["airport"] = new_id
    payload["messages"] = messages
    await asyncio.to_thread(pinned_state.write_payload, chat_id, payload)
    return dict(messages)
