"""Bounded official municipal Wi-Fi source adapter."""

import asyncio
import re
import subprocess
import unicodedata
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional

from ._transport import BoundedFetchError, fetch_bounded

WIFI_SOURCE_PAGE_URL = "https://www.guardamardelsegura.es/wifis-municipales/"
WIFI_VERIFIED_ASSET_URL = (
    "https://www.guardamardelsegura.es/wp-content/uploads/2021/06/"
    "PLANO-WIFIS-GUARDAMAR-PU%CC%81BLICAS.pdf"
)
WIFI_BASELINE_POINTS = (
    ("music_school", (("WiFi4EU", None),)),
    ("culture_house", (("WiFi4EU", None),)),
    ("los_pinos", (("WiFi4EU", None),)),
    ("constitution_square", (("vegafibra_gratis", "vegafibra"),)),
    ("seafront", (("vegafibra_gratis", "vegafibra"),)),
    ("study_room", (("wifi_1EO9C", "vegafibra"),)),
    ("library", (
        ("wifibiblioteca", "biblimar"),
        ("biblioteca infantil", "menjallibres"),
        ("vicenteramos", "menjallibres"),
    )),
)
WIFI_POINT_KEYS = tuple(key for key, _ in WIFI_BASELINE_POINTS)

_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_PDF_HEADERS = {
    "Accept": "application/pdf",
    "User-Agent": "guardamar-status-bot/1.0",
}
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_PDF_TYPES = frozenset({"application/pdf"})
_PDF_LIMIT_BYTES = 2 * 1024 * 1024
_TEXT_LIMIT_BYTES = 128 * 1024
_PDF_PARSE_TIMEOUT_SECONDS = 5.0
_POINT_MARKERS = (
    ("music_school", "ESCOLA DE MUSICA"),
    ("culture_house", "CASA DE CULTURA"),
    ("los_pinos", "AVDA. LOS PINOS"),
    ("constitution_square", "PLAZA DE LA CONSTITUCION"),
    ("seafront", "PASEO MARITIMO"),
    ("study_room", "SALA DE ESTUDIOS 24/365"),
    ("library", "BIBLIOTECA PUBLICA"),
)


class WifiSourceError(RuntimeError):
    """A bounded municipal Wi-Fi source response that is unsafe to use."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


def allowed_wifi_source_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "guardamardelsegura.es",
            "www.guardamardelsegura.es",
        }
        and port in {None, 443}
        and parsed.path in {"/wifis-municipales", "/wifis-municipales/"}
        and parsed.username is None
        and parsed.password is None
    )


def allowed_wifi_asset_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "guardamardelsegura.es",
            "www.guardamardelsegura.es",
        }
        and port in {None, 443}
        and parsed.path.startswith("/wp-content/uploads/")
        and parsed.path.casefold().endswith(".pdf")
        and parsed.username is None
        and parsed.password is None
    )


class _WifiAssetParser(HTMLParser):
    """Collect linked image assets that identify the municipal Wi-Fi map."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_href: Optional[str] = None
        self.candidates = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "a":
            href = attributes.get("href")
            self.current_href = href if isinstance(href, str) else None
            return
        if tag.casefold() != "img" or self.current_href is None:
            return
        marker = " ".join(
            value
            for key in ("src", "data-src", "alt", "title")
            if isinstance((value := attributes.get(key)), str)
        ).casefold()
        if "wifi" in marker and ("guardamar" in marker or "public" in marker):
            self.candidates.add(self.current_href)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a":
            self.current_href = None


def extract_wifi_asset_url(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WifiSourceError(
            "Wi-Fi source HTML is invalid", code="WIFI-HTML"
        ) from exc
    parser = _WifiAssetParser()
    parser.feed(text)
    urls = set()
    for href in parser.candidates:
        candidate = urllib.parse.urljoin(WIFI_SOURCE_PAGE_URL, href)
        try:
            parsed = urllib.parse.urlsplit(candidate)
        except ValueError:
            continue
        canonical_path = urllib.parse.quote(
            urllib.parse.unquote(parsed.path),
            safe="/:@!$&'()*+,;=-._~",
        )
        canonical = urllib.parse.urlunsplit(
            parsed._replace(path=canonical_path, fragment="")
        )
        if allowed_wifi_asset_url(canonical):
            urls.add(canonical)
    if len(urls) != 1:
        raise WifiSourceError(
            "Wi-Fi source asset is missing or ambiguous",
            code="WIFI-LINK" if not urls else "WIFI-AMBIGUOUS",
        )
    return urls.pop()


async def fetch_current_wifi_asset() -> str:
    """Return the one municipal PDF currently linked from the Wi-Fi page."""

    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            WIFI_SOURCE_PAGE_URL,
            is_allowed_url=allowed_wifi_source_url,
            limit_bytes=512 * 1024,
            timeout_seconds=15.0,
            headers=_REQUEST_HEADERS,
            accepted_types=_HTML_TYPES,
        )
    except BoundedFetchError as exc:
        raise WifiSourceError(
            "Wi-Fi source request failed", code=f"WIFI-{exc.code}"
        ) from exc
    return extract_wifi_asset_url(payload)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.upper().split())


def _extract_pdf_text(payload: bytes) -> str:
    if not payload.startswith(b"%PDF-") or len(payload) > _PDF_LIMIT_BYTES:
        raise WifiSourceError(
            "Wi-Fi document is not a bounded PDF", code="WIFI-PDF"
        )
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_PDF_PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise WifiSourceError(
            "pdftotext is unavailable", code="WIFI-PDF-TO-TEXT"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WifiSourceError(
            "Wi-Fi PDF parsing timed out", code="WIFI-PDF-TIMEOUT"
        ) from exc
    except OSError as exc:
        raise WifiSourceError(
            "Wi-Fi PDF parsing failed", code="WIFI-PDF-TO-TEXT"
        ) from exc
    if completed.returncode != 0:
        raise WifiSourceError(
            "pdftotext rejected Wi-Fi PDF", code="WIFI-PDF-PARSE"
        )
    if not completed.stdout or len(completed.stdout) > _TEXT_LIMIT_BYTES:
        raise WifiSourceError(
            "Wi-Fi PDF text is empty or too large", code="WIFI-PDF-PARSE"
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WifiSourceError(
            "Wi-Fi PDF text encoding is invalid", code="WIFI-PDF-PARSE"
        ) from exc


def parse_wifi_pdf_text(
    text: str,
    asset_url: str,
    observed_at: datetime,
) -> dict:
    """Normalize the complete reviewed seven-point Wi-Fi topology."""

    if not allowed_wifi_asset_url(asset_url):
        raise WifiSourceError(
            "Wi-Fi asset URL is outside policy", code="WIFI-URL"
        )
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Wi-Fi observation time must be timezone-aware")
    folded = _fold(text)
    if "WIFIS PUBLICAS" not in folded or "GUARDAMAR DEL SEGURA" not in folded:
        raise WifiSourceError(
            "Wi-Fi PDF heading is invalid", code="WIFI-SCHEMA"
        )

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    folded_lines = [_fold(line) for line in lines]
    positions = {}
    for key, marker in _POINT_MARKERS:
        matches = [
            index for index, line in enumerate(folded_lines)
            if marker in line
        ]
        if len(matches) != 1:
            raise WifiSourceError(
                f"Wi-Fi point {key} is missing or ambiguous",
                code="WIFI-SCHEMA",
            )
        positions[key] = matches[0]

    ordered = sorted(positions.items(), key=lambda item: item[1])
    points = []
    parsed_networks = 0
    for offset, (key, start_index) in enumerate(ordered):
        end_index = (
            ordered[offset + 1][1]
            if offset + 1 < len(ordered)
            else len(lines)
        )
        segment = "\n".join(lines[start_index:end_index])
        networks = []
        if re.search(
            r"wifi\s+gratuita\s+wifi4eu",
            segment,
            re.IGNORECASE,
        ):
            networks.append({"ssid": "WiFi4EU", "password": None})
        for match in re.finditer(
            r"Red:\s*(.*?)\s*(?:-\s*)?Contrase(?:ña|na):\s*([^\s]+)",
            segment,
            re.IGNORECASE | re.DOTALL,
        ):
            ssid = " ".join(match.group(1).split())
            password = match.group(2).strip()
            if not ssid or len(ssid) > 80 or len(password) > 80:
                raise WifiSourceError(
                    "Wi-Fi credentials are invalid", code="WIFI-SCHEMA"
                )
            networks.append({"ssid": ssid, "password": password})
        if len(networks) != (3 if key == "library" else 1):
            raise WifiSourceError(
                f"Wi-Fi networks for {key} are incomplete",
                code="WIFI-SCHEMA",
            )
        if len({item["ssid"] for item in networks}) != len(networks):
            raise WifiSourceError(
                "Wi-Fi networks are duplicated", code="WIFI-SCHEMA"
            )
        parsed_networks += len(networks)
        points.append({"key": key, "networks": networks})

    source_networks = len(re.findall(r"\bRED\s*:", folded)) + len(
        re.findall(r"WIFI\s+GRATUITA\s+WIFI4EU", folded)
    )
    if source_networks != parsed_networks:
        raise WifiSourceError(
            "Wi-Fi PDF contains an unrecognized network entry",
            code="WIFI-SCHEMA",
        )
    by_key = {item["key"]: item for item in points}
    snapshot = {
        "observed_at": observed_at.isoformat(),
        "asset_url": asset_url,
        "points": [by_key[key] for key in WIFI_POINT_KEYS],
    }
    if not valid_wifi_snapshot(snapshot):
        raise WifiSourceError(
            "Wi-Fi snapshot is invalid", code="WIFI-SCHEMA"
        )
    return snapshot


def valid_wifi_snapshot(value) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        observed_at = datetime.fromisoformat(value["observed_at"])
        asset_url = value["asset_url"]
        points = value["points"]
    except (KeyError, TypeError, ValueError):
        return False
    if (
        observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or not isinstance(asset_url, str)
        or not allowed_wifi_asset_url(asset_url)
        or not isinstance(points, list)
        or len(points) != len(WIFI_POINT_KEYS)
    ):
        return False
    keys = []
    for point in points:
        if not isinstance(point, dict) or set(point) != {"key", "networks"}:
            return False
        key = point["key"]
        networks = point["networks"]
        if (
            key not in WIFI_POINT_KEYS
            or not isinstance(networks, list)
            or not networks
            or len(networks) != (3 if key == "library" else 1)
        ):
            return False
        seen_ssids = set()
        for network in networks:
            if (
                not isinstance(network, dict)
                or set(network) != {"ssid", "password"}
            ):
                return False
            ssid = network["ssid"]
            password = network["password"]
            if (
                not isinstance(ssid, str)
                or not ssid.strip()
                or len(ssid) > 80
                or ssid in seen_ssids
                or (
                    password is not None
                    and (
                        not isinstance(password, str)
                        or not password.strip()
                        or len(password) > 80
                    )
                )
            ):
                return False
            seen_ssids.add(ssid)
        keys.append(key)
    return tuple(keys) == WIFI_POINT_KEYS


def wifi_snapshot_fingerprint(value: dict) -> tuple:
    """Return semantic Wi-Fi facts, excluding URL and observation time."""

    return tuple(
        (
            point["key"],
            tuple(
                sorted(
                    (network["ssid"], network["password"])
                    for network in point["networks"]
                )
            ),
        )
        for point in value["points"]
    )


def wifi_baseline_snapshot(now: datetime) -> dict:
    """Return the reviewed baseline using the normalized snapshot schema."""

    return {
        "observed_at": now.isoformat(),
        "asset_url": WIFI_VERIFIED_ASSET_URL,
        "points": [
            {
                "key": key,
                "networks": [
                    {"ssid": ssid, "password": password}
                    for ssid, password in networks
                ],
            }
            for key, networks in WIFI_BASELINE_POINTS
        ],
    }


async def fetch_wifi_snapshot(asset_url: str, now: datetime) -> dict:
    """Fetch and parse one new municipal Wi-Fi PDF deterministically."""

    if not allowed_wifi_asset_url(asset_url):
        raise WifiSourceError(
            "Wi-Fi asset URL is outside policy", code="WIFI-URL"
        )
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            asset_url,
            is_allowed_url=allowed_wifi_asset_url,
            limit_bytes=_PDF_LIMIT_BYTES,
            timeout_seconds=15.0,
            headers=_PDF_HEADERS,
            accepted_types=_PDF_TYPES,
        )
    except BoundedFetchError as exc:
        raise WifiSourceError(
            "Wi-Fi PDF request failed", code=f"WIFI-{exc.code}"
        ) from exc
    text = await asyncio.to_thread(_extract_pdf_text, payload)
    return parse_wifi_pdf_text(text, asset_url, now)
