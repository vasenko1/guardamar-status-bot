"""Official CCE/112 and Previfoc risk monitoring for Guardamar."""

import asyncio
import fcntl
import html
import json
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

CCE_EMERGENCIES_URL = (
    "https://www.112cv.com/WebPublica-MapasOnLineV2/"
    "emergencias.jsf?idioma=es_es"
)
CCE_PDF_URL = (
    "https://wpr.112cv.gva.es/external/api/storage/descargar/pdf/"
    "avisosmeteorologicos/avisometeorologico.pdf"
)
PREVIFOC_URL = (
    "https://vaersa.org/arcgis/rest/services/"
    "Nivel_preemergencia_Alerta3_112/MapServer/0/query"
    "?where=ZonaID%3D6"
    "&outFields=ZonaID%2CRiesgoId%2CTormentaID%2CDia%2CAlertaDiaID"
    "&returnGeometry=false&f=json"
)

STATE_VERSION = 2
HTML_LIMIT_BYTES = 64 * 1024
JSON_LIMIT_BYTES = 64 * 1024
PDF_LIMIT_BYTES = 512 * 1024
PDF_TEXT_LIMIT_BYTES = 256 * 1024
REQUEST_TIMEOUT_SECONDS = 15
PDF_PARSE_TIMEOUT_SECONDS = 10
MORNING_FRESHNESS = timedelta(hours=2)

HYDRO_NONE = "none"
HYDRO_PREEMERGENCIA = "preemergencia"
HYDRO_SITUATION_0 = "situation0"
HYDRO_SITUATION_1 = "situation1"
HYDRO_SITUATION_2 = "situation2"

_HYDRO_RANK = {
    HYDRO_NONE: 0,
    HYDRO_PREEMERGENCIA: 1,
    HYDRO_SITUATION_0: 2,
    HYDRO_SITUATION_1: 3,
    HYDRO_SITUATION_2: 4,
}
_HYDRO_VALUES = frozenset(_HYDRO_RANK)


class EmergencyRiskError(RuntimeError):
    """Raised when an official risk source or local state is not trustworthy."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


class EmergencyRiskDeliveryUncertain(RuntimeError):
    """Raised when Telegram may have accepted a message without a response."""


@dataclass(frozen=True)
class PrevifocRisk:
    fire_level: int
    dry_thunderstorm_level: int
    alert_id: int


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag) -> None:
        if tag.casefold() in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data) -> None:
        if not self.hidden_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    ).upper()


def _allowed_exact_url(
    url: str,
    *,
    host: str,
    path: str,
    query: Optional[str] = None,
) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == host
        and parsed.path == path
        and not parsed.params
        and not parsed.fragment
        and (query is None or parsed.query == query)
    )


def _is_cce_emergencies_url(url: str) -> bool:
    return _allowed_exact_url(
        url,
        host="www.112cv.com",
        path="/WebPublica-MapasOnLineV2/emergencias.jsf",
        query="idioma=es_es",
    )


def _is_cce_pdf_url(url: str) -> bool:
    return _allowed_exact_url(
        url,
        host="wpr.112cv.gva.es",
        path=(
            "/external/api/storage/descargar/pdf/"
            "avisosmeteorologicos/avisometeorologico.pdf"
        ),
        query="",
    )


def _is_previfoc_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "vaersa.org"
        or parsed.path != (
            "/arcgis/rest/services/Nivel_preemergencia_Alerta3_112/"
            "MapServer/0/query"
        )
        or parsed.params
        or parsed.fragment
    ):
        return False
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return query == {
        "where": ["ZonaID=6"],
        "outFields": [
            "ZonaID,RiesgoId,TormentaID,Dia,AlertaDiaID"
        ],
        "returnGeometry": ["false"],
        "f": ["json"],
    }


def parse_previfoc(payload: bytes) -> PrevifocRisk:
    """Parse the one Guardamar zone-6 row returned by the official ArcGIS layer."""

    if len(payload) > JSON_LIMIT_BYTES:
        raise EmergencyRiskError("Previfoc response is too large")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmergencyRiskError("Previfoc response is invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("features"), list):
        raise EmergencyRiskError("Previfoc response has an invalid root")
    if len(value["features"]) != 1:
        raise EmergencyRiskError("Previfoc zone 6 is missing or ambiguous")
    feature = value["features"][0]
    if not isinstance(feature, dict) or not isinstance(
        feature.get("attributes"), dict
    ):
        raise EmergencyRiskError("Previfoc feature is invalid")
    attrs = feature["attributes"]
    required = ("ZonaID", "RiesgoId", "TormentaID", "Dia", "AlertaDiaID")
    if any(name not in attrs for name in required):
        raise EmergencyRiskError("Previfoc feature is incomplete")

    def integer(name: str) -> int:
        item = attrs[name]
        if not isinstance(item, int) or isinstance(item, bool):
            raise EmergencyRiskError("Previfoc field is not an integer")
        return item

    zone = integer("ZonaID")
    fire = integer("RiesgoId")
    dry = integer("TormentaID")
    day = integer("Dia")
    alert_id = integer("AlertaDiaID")
    if (
        zone != 6
        or day != 1
        or fire not in {1, 2, 3}
        or dry not in {1, 2, 3}
        or alert_id <= 0
    ):
        raise EmergencyRiskError("Previfoc feature values are out of contract")
    return PrevifocRisk(fire, dry, alert_id)


def _status_from_segura_context(lines) -> Optional[str]:
    """Return the strongest recognized active Segura hydrological state."""

    relevant = []
    for index, line in enumerate(lines):
        if "SEGURA" not in line:
            continue
        relevant.extend(lines[max(0, index - 7): index + 8])
    if not relevant:
        return None
    text = " | ".join(relevant)
    # Remove explicit end statements before looking for still-active states.
    active = re.sub(
        r"FIN(?:ALIZACION)?[^|]{0,100}SITUACION\s*[012]",
        " ",
        text,
    )
    active = re.sub(
        r"FIN(?:ALIZACION)?[^|]{0,100}PREEMERGENCIA\s+HIDROLOGICA",
        " ",
        active,
    )
    hydrological_context = "INUND" in active or "HIDROLOG" in active
    for number, status in (
        ("2", HYDRO_SITUATION_2),
        ("1", HYDRO_SITUATION_1),
        ("0", HYDRO_SITUATION_0),
    ):
        if (
            hydrological_context
            and re.search(rf"SITUACION\s*{number}\b", active)
        ):
            return status
    if "PREEMERGENCIA HIDROLOGICA" in active:
        return HYDRO_PREEMERGENCIA
    if re.search(
        r"FIN(?:ALIZACION)?[^|]{0,100}"
        r"(?:PREEMERGENCIA\s+HIDROLOGICA|SITUACION\s*[012])",
        text,
    ):
        return HYDRO_NONE
    return None


def parse_cce_text(text: str, *, bulletin: bool) -> str:
    """Parse one official CCE surface into a Segura hydrological state."""

    folded_lines = [
        " ".join(_fold(line).split())
        for line in text.splitlines()
        if line.strip()
    ]
    folded = " ".join(folded_lines)
    if not folded:
        raise EmergencyRiskError("CCE response has no visible text")
    if not bulletin and "SIN EMERGENCIAS VIGENTES" in folded:
        return HYDRO_NONE

    status = _status_from_segura_context(folded_lines)
    if status is not None:
        return status

    hydro_words = (
        "HIDROLOG",
        "INUND",
        "SITUACION 0",
        "SITUACION 1",
        "SITUACION 2",
    )
    if bulletin:
        if not (
            "FECHA" in folded
            and "HORA" in folded
            and "PLANES DE EMERGENCIA ACTIVADOS" in folded
        ):
            raise EmergencyRiskError(
                "CCE PDF does not match the expected bulletin"
            )
        if "SEGURA" in folded and any(word in folded for word in hydro_words):
            raise EmergencyRiskError(
                "CCE PDF contains ambiguous Segura hydrological text"
            )
        return HYDRO_NONE

    if "EMERGEN" not in folded:
        raise EmergencyRiskError(
            "CCE emergencies page does not match the expected page"
        )
    if "SEGURA" in folded and any(word in folded for word in hydro_words):
        raise EmergencyRiskError(
            "CCE emergencies page contains ambiguous hydrological text"
        )
    raise EmergencyRiskError(
        "CCE emergencies page has no explicit Segura state", code="UNKNOWN"
    )


def parse_cce_emergencies_html(payload: bytes) -> str:
    if len(payload) > HTML_LIMIT_BYTES:
        raise EmergencyRiskError("CCE emergencies page is too large")
    text = payload.decode("utf-8", errors="replace")
    if "�" in text:
        raise EmergencyRiskError("CCE emergencies page encoding is invalid")
    parser = _VisibleTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise EmergencyRiskError("CCE emergencies page is invalid HTML") from exc
    return parse_cce_text("\n".join(parser.parts), bulletin=False)


def extract_pdf_text(payload: bytes) -> str:
    if not payload.startswith(b"%PDF-") or len(payload) > PDF_LIMIT_BYTES:
        raise EmergencyRiskError("CCE bulletin is not a bounded PDF")
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PDF_PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EmergencyRiskError(
            "pdftotext is unavailable", code="PDF-TO-TEXT"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EmergencyRiskError(
            "pdftotext timed out", code="PDF-TIMEOUT"
        ) from exc
    except OSError as exc:
        raise EmergencyRiskError(
            "pdftotext failed", code="PDF-TO-TEXT"
        ) from exc
    if completed.returncode != 0:
        raise EmergencyRiskError(
            "pdftotext rejected the CCE bulletin", code="PDF-PARSE"
        )
    if not completed.stdout or len(completed.stdout) > PDF_TEXT_LIMIT_BYTES:
        raise EmergencyRiskError(
            "CCE bulletin text is empty or too large", code="PDF-PARSE"
        )
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EmergencyRiskError(
            "CCE bulletin text encoding is invalid", code="PDF-PARSE"
        ) from exc
    return text


def parse_cce_bulletin(text: str, now: datetime) -> str:
    """Validate bulletin date/time before accepting its hydrological state."""

    folded = _fold(text)
    date_match = re.search(
        r"\bFECHA\s*[:\-]?\s*(\d{1,2})\D{1,3}(\d{1,2})\D{1,3}(\d{4})",
        folded,
    )
    time_match = re.search(r"\bHORA\s*[:\-]?\s*(\d{1,2}:\d{2})", folded)
    if date_match is None or time_match is None:
        raise EmergencyRiskError(
            "CCE bulletin timestamp is missing", code="STALE"
        )
    try:
        issued = datetime.strptime(
            (
                f"{date_match.group(1)}/{date_match.group(2)}/"
                f"{date_match.group(3)} {time_match.group(1)}"
            ),
            "%d/%m/%Y %H:%M",
        ).replace(tzinfo=GUARDAMAR_TIMEZONE)
    except ValueError as exc:
        raise EmergencyRiskError(
            "CCE bulletin timestamp is invalid", code="STALE"
        ) from exc
    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    if issued.date() != local_now.date() or issued > local_now + timedelta(minutes=15):
        raise EmergencyRiskError(
            "CCE bulletin is not current for today", code="STALE"
        )
    return parse_cce_text(text, bulletin=True)


def parse_cce_pdf(payload: bytes, now: datetime) -> str:
    return parse_cce_bulletin(extract_pdf_text(payload), now)


def _fetch_previfoc_sync() -> PrevifocRisk:
    try:
        payload, _, _ = fetch_bounded(
            PREVIFOC_URL,
            is_allowed_url=_is_previfoc_url,
            accepted_types=frozenset({
                "application/json",
                "text/json",
                "text/plain",
            }),
            limit_bytes=JSON_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json,text/plain",
                "User-Agent": "GuardamarMorningDigest/0.14",
            },
        )
    except BoundedFetchError as exc:
        raise EmergencyRiskError(
            "Previfoc source is unavailable", code=exc.code
        ) from exc
    return parse_previfoc(payload)


async def fetch_previfoc() -> PrevifocRisk:
    return await asyncio.to_thread(_fetch_previfoc_sync)


def _fetch_cce_emergencies_sync() -> str:
    try:
        payload, _, _ = fetch_bounded(
            CCE_EMERGENCIES_URL,
            is_allowed_url=_is_cce_emergencies_url,
            accepted_types=frozenset({
                "text/html",
                "application/xhtml+xml",
            }),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.14",
            },
        )
    except BoundedFetchError as exc:
        raise EmergencyRiskError(
            "CCE emergencies source is unavailable", code=exc.code
        ) from exc
    return parse_cce_emergencies_html(payload)


async def fetch_cce_emergencies() -> str:
    return await asyncio.to_thread(_fetch_cce_emergencies_sync)


def _fetch_cce_pdf_sync(now: datetime) -> str:
    try:
        payload, _, _ = fetch_bounded(
            CCE_PDF_URL,
            is_allowed_url=_is_cce_pdf_url,
            accepted_types=frozenset({"application/pdf"}),
            limit_bytes=PDF_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/pdf",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.14",
            },
        )
    except BoundedFetchError as exc:
        raise EmergencyRiskError(
            "CCE bulletin is unavailable", code=exc.code
        ) from exc
    return parse_cce_pdf(payload, now)


async def fetch_cce_pdf(now: datetime) -> str:
    return await asyncio.to_thread(_fetch_cce_pdf_sync, now)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EmergencyRiskError(
            "risk state is corrupt", code="STATE-CORRUPT"
        ) from exc
    if parsed.tzinfo is None:
        raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
    return parsed


class EmergencyRiskState:
    """Small atomic state for independent official observations and publications."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def empty() -> dict:
        return {
            "version": STATE_VERSION,
            "previfoc": None,
            "cce_html": None,
            "cce_pdf": None,
            "published": {
                "fire_level": None,
                "dry_level": None,
                "hydrology": None,
            },
        }

    def _validate_observation(self, value: object) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
        if set(value) != {"hydrology", "observed_at"}:
            raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
        if value["hydrology"] not in _HYDRO_VALUES:
            raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
        _parse_datetime(value["observed_at"])

    def read(self) -> dict:
        if not self.path.exists():
            return self.empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise EmergencyRiskError(
                "risk state is unreadable", code="STATE-IO"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EmergencyRiskError(
                "risk state is corrupt", code="STATE-CORRUPT"
            ) from exc

        if (
            not isinstance(value, dict)
            or set(value) != {
                "version", "previfoc", "cce_html", "cce_pdf", "published",
            }
            or value.get("version") not in {1, STATE_VERSION}
            or isinstance(value["version"], bool)
        ):
            raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")

        previfoc = value["previfoc"]
        if previfoc is not None:
            if (
                not isinstance(previfoc, dict)
                or set(previfoc) != {
                    "fire_level", "dry_thunderstorm_level",
                    "alert_id", "observed_at",
                }
                or previfoc["fire_level"] not in {1, 2, 3}
                or isinstance(previfoc["fire_level"], bool)
                or previfoc["dry_thunderstorm_level"] not in {1, 2, 3}
                or isinstance(previfoc["dry_thunderstorm_level"], bool)
                or not isinstance(previfoc["alert_id"], int)
                or isinstance(previfoc["alert_id"], bool)
                or previfoc["alert_id"] <= 0
            ):
                raise EmergencyRiskError(
                    "risk state is corrupt", code="STATE-CORRUPT"
                )
            _parse_datetime(previfoc["observed_at"])

        self._validate_observation(value["cce_html"])
        self._validate_observation(value["cce_pdf"])

        published = value["published"]
        if value["version"] == 1:
            if (
                not isinstance(published, dict)
                or set(published) != {
                    "fire_level", "dry_high", "hydrology",
                }
                or not isinstance(published["dry_high"], bool)
                or (
                    not published["dry_high"]
                    and previfoc is not None
                    and previfoc["dry_thunderstorm_level"] == 3
                )
            ):
                raise EmergencyRiskError(
                    "risk state is corrupt", code="STATE-CORRUPT"
                )
            dry_level = None
            if published["dry_high"]:
                dry_level = 3
            elif previfoc is not None:
                # Preserve the already observed low/probable state as the
                # migration baseline; deployment must not invent a transition.
                dry_level = previfoc["dry_thunderstorm_level"]
            value = {
                **value,
                "version": STATE_VERSION,
                "published": {
                    "fire_level": published["fire_level"],
                    "dry_level": dry_level,
                    "hydrology": published["hydrology"],
                },
            }
            published = value["published"]

        if (
            not isinstance(published, dict)
            or set(published) != {
                "fire_level", "dry_level", "hydrology",
            }
            or (
                published["fire_level"] is not None
                and (
                    not isinstance(published["fire_level"], int)
                    or isinstance(published["fire_level"], bool)
                    or published["fire_level"] not in {1, 2, 3}
                )
            )
            or (
                published["dry_level"] is not None
                and (
                    not isinstance(published["dry_level"], int)
                    or isinstance(published["dry_level"], bool)
                    or published["dry_level"] not in {1, 2, 3}
                )
            )
            or (
                published["hydrology"] is not None
                and published["hydrology"] not in _HYDRO_VALUES - {HYDRO_NONE}
            )
        ):
            raise EmergencyRiskError("risk state is corrupt", code="STATE-CORRUPT")
        return value

    def write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    @staticmethod
    def current_hydrology(value: dict) -> Optional[str]:
        observations = [
            item for item in (value["cce_html"], value["cce_pdf"])
            if item is not None
        ]
        if not observations:
            return None
        newest = max(_parse_datetime(item["observed_at"]) for item in observations)
        current = [
            item["hydrology"]
            for item in observations
            if _parse_datetime(item["observed_at"]) == newest
        ]
        active = [status for status in current if status != HYDRO_NONE]
        if active:
            return max(active, key=lambda status: _HYDRO_RANK[status])
        return HYDRO_NONE

    def morning_values(
        self, now: datetime
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        value = self.read()
        local_now = now.astimezone(GUARDAMAR_TIMEZONE)
        fire = dry = None
        previfoc = value["previfoc"]
        if previfoc is not None:
            observed = _parse_datetime(previfoc["observed_at"]).astimezone(
                GUARDAMAR_TIMEZONE
            )
            age = local_now - observed
            if (
                observed.date() == local_now.date()
                and timedelta(0) <= age <= MORNING_FRESHNESS
            ):
                fire = previfoc["fire_level"]
                dry = previfoc["dry_thunderstorm_level"]

        hydro = self.current_hydrology(value)
        if hydro not in (None, HYDRO_NONE):
            fresh_active = False
            for item in (value["cce_html"], value["cce_pdf"]):
                if item is None or item["hydrology"] == HYDRO_NONE:
                    continue
                observed = _parse_datetime(item["observed_at"]).astimezone(
                    GUARDAMAR_TIMEZONE
                )
                age = local_now - observed
                if (
                    item["hydrology"] == hydro
                    and timedelta(0) <= age <= MORNING_FRESHNESS
                ):
                    fresh_active = True
                    break
            if not fresh_active:
                hydro = None
        else:
            hydro = None
        return fire, dry, hydro


def _hydrology_label(status: str) -> str:
    return {
        HYDRO_PREEMERGENCIA: "гидрологическая preemergencia",
        HYDRO_SITUATION_0: "Situación 0 по риску наводнений",
        HYDRO_SITUATION_1: "Situación 1 по риску наводнений",
        HYDRO_SITUATION_2: "Situación 2 по риску наводнений",
    }[status]


def _current_previfoc(value: dict) -> tuple[Optional[int], Optional[int]]:
    item = value["previfoc"]
    if item is None:
        return None, None
    return item["fire_level"], item["dry_thunderstorm_level"]


def _transition(value: dict) -> Optional[str]:
    published = value["published"]
    fire, dry = _current_previfoc(value)
    hydro = EmergencyRiskState.current_hydrology(value)

    sections = []
    sources = []

    previous_fire = published["fire_level"]
    if fire is not None and fire != previous_fire:
        if fire == 3:
            sections.append([
                "🔥 <b>Экстремальный риск лесных пожаров</b>",
                "",
                "Для зоны Гуардамара установлен <b>максимальный уровень — 3 из 3</b>.",
                "",
                "🚫 Действуют наиболее строгие ограничения на использование огня "
                "и отдельные пожароопасные работы в лесной зоне и рядом с ней.",
                "",
                "Это профилактический уровень риска, а не сообщение "
                "о возникшем пожаре.",
            ])
        elif fire == 2 and previous_fire is not None:
            if previous_fire == 3:
                sections.append([
                    "🔥 <b>Риск лесных пожаров снижен</b>",
                    "",
                    "Для зоны Гуардамара уровень снижен с <b>экстремального "
                    "до высокого — 2 из 3</b>.",
                    "",
                    "Ограничения максимального уровня сняты, однако высокий "
                    "риск сохраняется.",
                    "",
                    "🚫 Сжигание сельскохозяйственных растительных остатков "
                    "в лесной зоне и в пределах <b>500 м от неё по-прежнему "
                    "запрещено</b>.",
                ])
            else:
                sections.append([
                    "🔥 <b>Повышен риск лесных пожаров</b>",
                    "",
                    "Для зоны Гуардамара сегодня действует высокий уровень "
                    "риска — 2 из 3.",
                    "",
                    "Если планируете прогулку, пикник или барбекю в природной "
                    "зоне, будьте особенно осторожны с огнём и не бросайте "
                    "тлеющие окурки.",
                    "",
                    "Это профилактическая информация — пожара или "
                    "непосредственной угрозы городу нет.",
                ])
        elif fire == 1 and previous_fire is not None:
            sections.append([
                "🔥 <b>Риск лесных пожаров снижен</b>",
                "",
                "Для зоны Гуардамара установлен <b>уровень 1 из 3 — "
                "низкий/средний риск лесных пожаров</b>.",
                "",
                "Ограничения, связанные с высоким уровнем риска лесных "
                "пожаров, сняты. При этом продолжают действовать обычные "
                "сезонные правила и местные ограничения на использование огня.",
            ])
        if sections:
            sources.append("Generalitat Valenciana / Previfoc")

    previous_dry = published["dry_level"]
    dry_section_count = len(sections)
    if dry is not None and dry != previous_dry:
        if dry == 3:
            sections.append([
                "⚡ <b>Высокий риск сухих гроз</b>",
                "",
                "Для зоны Гуардамара установлен <b>высокий риск сухих гроз</b>.",
                "",
                "Это профилактическая информация о погодном риске, "
                "а не сообщение о произошедшем пожаре или чрезвычайной ситуации.",
            ])
        elif dry == 2 and previous_dry is not None:
            if previous_dry == 3:
                sections.append([
                    "⚡ <b>Риск сухих гроз снижен</b>",
                    "",
                    "Высокий риск снят, но для зоны Гуардамара "
                    "<b>сухие грозы остаются возможны</b>.",
                ])
            else:
                sections.append([
                    "⚡ <b>Сухие грозы возможны</b>",
                    "",
                    "Для зоны Гуардамара отмечена <b>вероятность сухих гроз</b>.",
                    "",
                    "Это профилактическая информация о погодном риске, "
                    "а не сообщение о произошедшем пожаре или чрезвычайной ситуации.",
                ])
        elif dry == 1 and previous_dry is not None:
            sections.append([
                "✅ <b>Риск сухих гроз снят</b>",
                "",
                "Повышенный риск сухих гроз для зоны Гуардамара "
                "<b>больше не действует</b>.",
            ])
        if len(sections) > dry_section_count:
            sources.append("Generalitat Valenciana / Previfoc")

    published_hydro = published["hydrology"]
    if hydro not in (None, HYDRO_NONE) and hydro != published_hydro:
        if published_hydro is None:
            sections.append([
                "🌊 CCE сообщает: для территории Сегуры действует "
                f"<b>{html.escape(_hydrology_label(hydro))}</b>."
            ])
        elif _HYDRO_RANK[hydro] > _HYDRO_RANK[published_hydro]:
            sections.append([
                "🌊 Гидрологический статус CCE повышен до "
                f"<b>{html.escape(_hydrology_label(hydro))}</b>."
            ])
        else:
            sections.append([
                "🌊 Гидрологический статус CCE снижен до "
                f"<b>{html.escape(_hydrology_label(hydro))}</b>."
            ])
        sources.append("CCE — 112 Comunitat Valenciana")
    elif hydro == HYDRO_NONE and published_hydro is not None:
        sections.append(["🌊 Гидрологическое предупреждение CCE снято."])
        sources.append("CCE — 112 Comunitat Valenciana")

    if not sections:
        return None

    body = []
    for section in sections:
        if body:
            body.append("")
        body.extend(section)
    body.extend(["", "Источник: " + "; ".join(dict.fromkeys(sources))])
    return with_footer("\n".join(body))


def _acknowledge(value: dict) -> None:
    fire, dry = _current_previfoc(value)
    hydro = EmergencyRiskState.current_hydrology(value)
    published = value["published"]
    if fire is not None:
        published["fire_level"] = fire
    if dry is not None:
        published["dry_level"] = dry
    if hydro is not None:
        published["hydrology"] = None if hydro == HYDRO_NONE else hydro


async def monitor_emergency_risks(
    now: datetime,
    state: EmergencyRiskState,
    publish: Callable[[str], Awaitable[int]],
    *,
    fetch_previfoc_fn: Callable[[], Awaitable[PrevifocRisk]] = fetch_previfoc,
    fetch_cce_html_fn: Callable[[], Awaitable[str]] = fetch_cce_emergencies,
    fetch_cce_pdf_fn: Optional[Callable[[], Awaitable[str]]] = None,
) -> str:
    """Run one bounded collection/normalization/delivery cycle."""

    with state.exclusive_run():
        value = state.read()
        successes = 0

        try:
            previfoc = await fetch_previfoc_fn()
        except EmergencyRiskError as exc:
            logging.warning(
                "Previfoc check failed: RISK-%s", exc.diagnostic_code
            )
        else:
            successes += 1
            value["previfoc"] = {
                "fire_level": previfoc.fire_level,
                "dry_thunderstorm_level": previfoc.dry_thunderstorm_level,
                "alert_id": previfoc.alert_id,
                "observed_at": now.isoformat(),
            }

        try:
            hydrology = await fetch_cce_html_fn()
        except EmergencyRiskError as exc:
            logging.warning(
                "CCE emergencies check failed: RISK-%s", exc.diagnostic_code
            )
        else:
            successes += 1
            value["cce_html"] = {
                "hydrology": hydrology,
                "observed_at": now.isoformat(),
            }

        try:
            hydrology = await (
                fetch_cce_pdf_fn() if fetch_cce_pdf_fn is not None
                else fetch_cce_pdf(now)
            )
        except EmergencyRiskError as exc:
            logging.warning(
                "CCE bulletin check failed: RISK-%s", exc.diagnostic_code
            )
        else:
            successes += 1
            value["cce_pdf"] = {
                "hydrology": hydrology,
                "observed_at": now.isoformat(),
            }

        if successes == 0:
            logging.warning("RISK: all official sources unavailable")
            return "unavailable"

        fire, dry = _current_previfoc(value)
        if (
            value["published"]["fire_level"] is None
            and fire in {1, 2}
        ):
            # First low/high observation is a silent baseline. Extreme risk is
            # urgent enough to publish even on the first successful run.
            value["published"]["fire_level"] = fire
        if (
            value["published"]["dry_level"] is None
            and dry in {1, 2}
        ):
            # A first no-risk/probable observation establishes a baseline.
            # High dry-thunderstorm risk remains urgent enough to publish.
            value["published"]["dry_level"] = dry

        message = _transition(value)
        if message is None:
            state.write(value)
            return "no_update"

        try:
            await publish(message)
        except EmergencyRiskDeliveryUncertain:
            # Treat the target state as possibly visible. This avoids an
            # automatic duplicate on the next identical run while still
            # allowing a later downgrade/clearance to correct a message that
            # Telegram may in fact have accepted.
            _acknowledge(value)
            state.write(value)
            return "uncertain"

        _acknowledge(value)
        state.write(value)
        return "published"
