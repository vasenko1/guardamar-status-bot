"""On-demand category-first supermarket product-award publications.

The runtime deliberately services a reviewed catalogue instead of discovering
new competitions. A due run validates one immutable award fact, refreshes one
exact retailer product, publishes at most one event, and exits.
"""

from __future__ import annotations

import fcntl
import html
import json
import logging
import os
import re
import unicodedata
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator, Optional

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15
HTML_LIMIT_BYTES = 768_000
USER_AGENT = "GuardamarMorningDigest/0.13"
COOLDOWN_DAYS = 3
STATE_SCHEMA_VERSION = 1
MAX_HISTORY = 128


class ProductAwardError(RuntimeError):
    """Fail-closed product-award error with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


@dataclass(frozen=True)
class RetailOffer:
    retailer: str
    package: str
    price: str
    product_url: str


@dataclass(frozen=True)
class ReviewedCandidate:
    category_key: str
    event_id: str
    source_name: str
    source_url: str
    source_hosts: frozenset[str]
    source_markers: tuple[str, ...]
    retailer: str
    retailer_kind: str
    retailer_url: str
    retailer_hosts: frozenset[str]
    retailer_markers: tuple[str, ...]
    retailer_title: str
    package: str
    result_line: str
    detail_line: str
    source_link_label: str
    source_priority: int = 1
    rank: int = 1


@dataclass(frozen=True)
class ReviewedSource:
    name: str
    priority: int
    candidates: tuple[ReviewedCandidate, ...]


@dataclass(frozen=True)
class ReviewedCategory:
    key: str
    sources: tuple[ReviewedSource, ...]


@dataclass(frozen=True)
class ProductAwardPublication:
    candidate: ReviewedCandidate
    offer: RetailOffer
    message: str


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", html.unescape(value))
    return " ".join(
        "".join(ch for ch in normalized if not unicodedata.combining(ch))
        .casefold()
        .split()
    )


def _allowed(hosts: frozenset[str]):
    def check(url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.casefold() in hosts
            and parsed.username is None
            and parsed.password is None
        )
    return check


def _fetch_visible_text(url: str, hosts: frozenset[str]) -> str:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed(hosts),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": USER_AGENT,
            },
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            "product-award source request failed",
            code=exc.code,
        ) from exc
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProductAwardError(
            "product-award source is not UTF-8",
            code="ENCODING",
        ) from exc
    parser = _VisibleTextParser()
    try:
        parser.feed(source)
    except Exception as exc:
        raise ProductAwardError(
            "product-award HTML could not be parsed",
            code="PARSER",
        ) from exc
    text = parser.text()
    if not text:
        raise ProductAwardError("product-award page is empty", code="PARSER")
    return text


def _require_markers(text: str, markers: tuple[str, ...], *, code: str) -> None:
    folded = _fold(text)
    missing = [marker for marker in markers if _fold(marker) not in folded]
    if missing:
        raise ProductAwardError(
            "reviewed product-award contract changed",
            code=code,
        )


def _price_after_title(text: str, title: str) -> Optional[str]:
    folded_text = _fold(text)
    folded_title = _fold(title)
    index = folded_text.find(folded_title)
    if index < 0:
        return None
    # _fold preserves ordinary digits/punctuation well enough for a bounded
    # post-title window; only the first currency-formatted value is accepted.
    window = folded_text[index:index + 3000]
    match = re.search(r"(?<!\d)(\d{1,3}[.,]\d{2})\s*€", window)
    if match is None:
        return None
    return match.group(1).replace(".", ",") + " €"


def _aldi_price(text: str, package_marker: str) -> Optional[str]:
    folded = _fold(text)
    package = re.escape(_fold(package_marker))
    # ALDI's server-rendered card exposes price immediately before the package
    # line and does not consistently include a euro symbol.
    match = re.search(
        rf"(?<!\d)(\d{{1,3}}[.,]\d{{2}})\s+{package}(?:\s|$)",
        folded,
    )
    if match is None:
        return None
    return match.group(1).replace(".", ",") + " €"


def _verify_award(candidate: ReviewedCandidate) -> None:
    text = _fetch_visible_text(candidate.source_url, candidate.source_hosts)
    _require_markers(text, candidate.source_markers, code="AWARD-DRIFT")


def _refresh_offer(candidate: ReviewedCandidate) -> Optional[RetailOffer]:
    text = _fetch_visible_text(candidate.retailer_url, candidate.retailer_hosts)
    try:
        _require_markers(text, candidate.retailer_markers, code="RETAIL-DRIFT")
    except ProductAwardError:
        return None

    if candidate.retailer_kind == "aldi":
        price = _aldi_price(text, candidate.package)
    elif candidate.retailer_kind in {"carrefour", "dia"}:
        if _fold("Añadir") not in _fold(text):
            return None
        price = _price_after_title(text, candidate.retailer_title)
    else:
        raise ProductAwardError("unknown retailer adapter", code="CONFIG")

    if price is None:
        return None
    return RetailOffer(
        retailer=candidate.retailer,
        package=candidate.package,
        price=price,
        product_url=candidate.retailer_url,
    )


def build_message(candidate: ReviewedCandidate, offer: RetailOffer) -> str:
    source_url = html.escape(candidate.source_url, quote=True)
    retail_url = html.escape(offer.product_url, quote=True)
    message = (
        "🏆 <b>"
        + html.escape(candidate.result_line)
        + "</b>\n\n"
        + html.escape(candidate.detail_line)
        + "\n\n"
        + "🛒 <b>Сейчас в "
        + html.escape(offer.retailer)
        + "</b>\n"
        + html.escape(offer.package)
        + " — <b>"
        + html.escape(offer.price)
        + "</b>\n"
        + f'🔗 <a href="{retail_url}">Карточка товара</a>\n\n'
        + f'🏅 <a href="{source_url}">'
        + html.escape(candidate.source_link_label)
        + "</a>"
    )
    rendered = with_footer(message)
    if len(rendered) > 4096:
        raise ProductAwardError(
            "product-award message exceeds Telegram limit",
            code="MESSAGE-LENGTH",
        )
    return rendered


# Empty higher-priority source groups mean that their authoritative podium was
# reviewed and exhausted without a current exact match in the six retailer
# chains. They preserve source precedence without making the phone re-search
# the internet.
CATEGORIES: tuple[ReviewedCategory, ...] = (
    ReviewedCategory(
        "sparkling_cava",
        (
            ReviewedSource("MAPA 2026 sparkling", 1, ()),
            ReviewedSource(
                "OCU cava 2025",
                2,
                (
                    ReviewedCandidate(
                        category_key="sparkling_cava",
                        event_id="sparkling_cava:ocu-2025:naltros-brut",
                        source_name="OCU",
                        source_url="https://www.ocu.org/organizacion/prensa/notas-de-prensa/2025/cavas191225",
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "25 vinos espumosos",
                            "Naltros Brut (Aldi)",
                            "94 puntos sobre 100",
                        ),
                        retailer="ALDI",
                        retailer_kind="aldi",
                        retailer_url="https://www.aldi.es/p/cava-brut-190300.html",
                        retailer_hosts=frozenset({"www.aldi.es"}),
                        retailer_markers=("NALTROS", "Cava brut", "0,75 l"),
                        retailer_title="Cava brut",
                        package="0,75 l",
                        result_line="NALTROS Brut в ALDI — лучший Brut в тесте OCU",
                        detail_line=(
                            "OCU сравнила 25 cava: NALTROS Brut получил 94/100 "
                            "и вошёл в тройку продуктов с максимальной оценкой."
                        ),
                        source_link_label="Исследование OCU",
                        source_priority=2,
                        rank=1,
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "gazpacho",
        (
            ReviewedSource(
                "OCU gazpacho 2025",
                1,
                (
                    ReviewedCandidate(
                        category_key="gazpacho",
                        event_id="gazpacho:ocu-2025:realfooding",
                        source_name="OCU",
                        source_url="https://www.ocu.org/alimentacion/platos-preparados/informe/gazpachos",
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "39 gazpachos",
                            "Mejor del Análisis",
                            "Real Fooding",
                            "90 sobre 100",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url="https://www.carrefour.es/supermercado/gazpacho-fresco-realfooding-sin-gluten-1-l/R-VC4AECOMM-339275/p",
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Gazpacho fresco Realfooding sin gluten 1 l",
                            "CAÑA NATURE",
                            "REALFOODING",
                        ),
                        retailer_title="Gazpacho fresco Realfooding sin gluten 1 l",
                        package="1 l",
                        result_line="Realfooding в Carrefour — лучший gazpacho по версии OCU",
                        detail_line=(
                            "В сравнении 39 gazpacho он получил 90/100, "
                            "Mejor del Análisis и лучший результат дегустации."
                        ),
                        source_link_label="Исследование OCU",
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "aove",
        (
            ReviewedSource("EVOOLEUM 2026 overall", 1, ()),
            ReviewedSource(
                "OCU AOVE 2024",
                2,
                (
                    ReviewedCandidate(
                        category_key="aove",
                        event_id="aove:ocu-2024:oleoestepa-dop-estepa",
                        source_name="OCU",
                        source_url="https://www.ocu.org/alimentacion/aceite-oliva/informe/aceite-oliva-virgen-extra",
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "23 productos",
                            "lista de los mejores",
                            "AOVE Oleoestepa, DOP Estepa",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url="https://www.carrefour.es/supermercado/aceite-de-oliva-virgen-extra-oleoestepa-1-l/R-589802552/p",
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Aceite de oliva virgen extra Oleoestepa 1 l",
                            "D.O. Estepa",
                            "Oleoestepa S.C.A.",
                        ),
                        retailer_title="Aceite de oliva virgen extra Oleoestepa 1 l",
                        package="1 l",
                        result_line="Oleoestepa DOP Estepa в Carrefour — №1 в анализе AOVE OCU",
                        detail_line=(
                            "OCU сравнила 23 массовых AOVE; рейтинг качества "
                            "возглавил Oleoestepa с DOP Estepa."
                        ),
                        source_link_label="Анализ OCU",
                        source_priority=2,
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "coffee_capsules",
        (
            ReviewedSource(
                "OCU coffee capsules 2024",
                1,
                (
                    ReviewedCandidate(
                        category_key="coffee_capsules",
                        event_id="coffee_capsules:ocu-2024:aromarte-intenso",
                        source_name="OCU",
                        source_url="https://www.ocu.org/alimentacion/cafe/comparador/arom-arte-dia-intenso/273/103038",
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "AROM'ARTE (DIA) Intenso",
                            "Analizado en el laboratorio",
                            "20 unidades",
                            "Nespresso original",
                        ),
                        retailer="DIA",
                        retailer_kind="dia",
                        retailer_url="https://www.dia.es/cafe-cacao-e-infusiones/capsulas-compatibles-nespresso/p/273821",
                        retailer_hosts=frozenset({"www.dia.es"}),
                        retailer_markers=(
                            "Cápsulas de café intenso Dia Arom'arte 20 unidades",
                            "Toscaf",
                            "Nespresso",
                        ),
                        retailer_title="Cápsulas de café intenso Dia Arom'arte 20 unidades",
                        package="20 капсул",
                        result_line="AROM’ARTE Intenso в DIA — лидер теста капсул OCU",
                        detail_line=(
                            "В исследовании OCU 2024 продукт получил 85/100; "
                            "точная карточка OCU подтверждает лабораторное тестирование."
                        ),
                        source_link_label="Карточка лабораторного анализа OCU",
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "spirits_anis",
        (
            ReviewedSource(
                "MAPA spirits 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="spirits_anis",
                        event_id="spirits_anis:mapa-2026:chinchon-dulce",
                        source_name="MAPA",
                        source_url="https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados-bebidas-espirituosas",
                        source_hosts=frozenset({"www.mapa.gob.es"}),
                        source_markers=(
                            "Galardonado 2026",
                            "Anís Chinchón de la Alcoholera Dulce",
                            "GONZALEZ BYASS DISTRIBUCION",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url="https://www.carrefour.es/supermercado/anis-chinchon-dulce-1-l/R-538001406/p",
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Anís Chinchón dulce 1 l",
                            "35",
                            "I.G.P. Chinchón",
                            "González Byass",
                        ),
                        retailer_title="Anís Chinchón dulce 1 l",
                        package="1 l",
                        result_line="Anís Chinchón Dulce — лучший напиток своей категории MAPA 2026",
                        detail_line=(
                            "Министерство сельского хозяйства Испании присудило "
                            "ему Premio Alimentos de España 2026 среди спиртных "
                            "напитков с географическим указанием."
                        ),
                        source_link_label="Премия MAPA",
                    ),
                ),
            ),
        ),
    ),
)


def _all_candidates() -> tuple[ReviewedCandidate, ...]:
    return tuple(
        candidate
        for category in CATEGORIES
        for source in sorted(category.sources, key=lambda item: item.priority)
        for candidate in sorted(source.candidates, key=lambda item: item.rank)
    )


class ProductAwardState:
    """Small crash-safe delivery state for the three-day award workflow."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _empty(self) -> dict:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "last_delivery_day": None,
            "published_events": [],
            "category_cursor": 0,
            "uncertain_event": None,
        }

    def _read(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductAwardError("product-award state is unreadable", code="STATE") from exc
        if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ProductAwardError("product-award state schema is invalid", code="STATE")
        published = value.get("published_events")
        cursor = value.get("category_cursor")
        last_day = value.get("last_delivery_day")
        uncertain = value.get("uncertain_event")
        if (
            not isinstance(published, list)
            or len(published) > MAX_HISTORY
            or any(not isinstance(item, str) or not item for item in published)
            or not isinstance(cursor, int)
            or isinstance(cursor, bool)
            or cursor < 0
            or cursor >= len(CATEGORIES)
            or (last_day is not None and not isinstance(last_day, str))
            or (uncertain is not None and not isinstance(uncertain, str))
        ):
            raise ProductAwardError("product-award state structure is invalid", code="STATE")
        if last_day is not None:
            try:
                date.fromisoformat(last_day)
            except ValueError as exc:
                raise ProductAwardError("product-award state date is invalid", code="STATE") from exc
        return value

    def _write(self, value: dict) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ProductAwardError("product-award state could not be saved", code="STATE") from exc

    def due(self, local_day: date) -> bool:
        value = self._read()
        raw = value["last_delivery_day"]
        if raw is None:
            return True
        return (local_day - date.fromisoformat(raw)).days >= COOLDOWN_DAYS

    def uncertain_event(self) -> Optional[str]:
        return self._read()["uncertain_event"]

    def published_events(self) -> frozenset[str]:
        return frozenset(self._read()["published_events"])

    def category_cursor(self) -> int:
        return self._read()["category_cursor"]

    def has_unpublished(self) -> bool:
        published = self.published_events()
        return any(candidate.event_id not in published for candidate in _all_candidates())

    def mark_uncertain(self, event_id: str) -> None:
        value = self._read()
        value["uncertain_event"] = event_id
        self._write(value)

    def clear_uncertain(self, event_id: str) -> None:
        value = self._read()
        if value["uncertain_event"] == event_id:
            value["uncertain_event"] = None
            self._write(value)

    def confirm(self, event_id: str, category_index: int, local_day: date) -> None:
        value = self._read()
        if value["uncertain_event"] != event_id:
            raise ProductAwardError("product-award delivery reservation is missing", code="STATE")
        published = list(value["published_events"])
        if event_id not in published:
            if len(published) >= MAX_HISTORY:
                raise ProductAwardError("product-award history is full", code="STATE")
            published.append(event_id)
        value["published_events"] = published
        value["last_delivery_day"] = local_day.isoformat()
        value["category_cursor"] = (category_index + 1) % len(CATEGORIES)
        value["uncertain_event"] = None
        self._write(value)

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock = None
        try:
            lock = lock_path.open("a", encoding="utf-8")
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if lock is not None:
                lock.close()
            raise ProductAwardError(
                "another product-award run is active",
                code="LOCK",
            ) from exc
        except OSError as exc:
            if lock is not None:
                lock.close()
            raise ProductAwardError(
                "product-award state could not be locked",
                code="STATE",
            ) from exc
        try:
            yield
        finally:
            assert lock is not None
            lock.close()


def _category_order(cursor: int) -> tuple[int, ...]:
    return tuple((cursor + offset) % len(CATEGORIES) for offset in range(len(CATEGORIES)))


def select_publication(
    now: datetime,
    state: ProductAwardState,
    *,
    ignore_cooldown: bool = False,
) -> Optional[tuple[int, ProductAwardPublication]]:
    local_day = now.date()
    if state.uncertain_event() is not None:
        LOGGER.warning("Product-award delivery remains uncertain; automatic resend disabled")
        return None
    if not ignore_cooldown and not state.due(local_day):
        LOGGER.info("SKIP: product-award three-day cooldown is active")
        return None
    if not state.has_unpublished():
        LOGGER.info("SKIP: reviewed product-award registry is exhausted")
        return None

    published = state.published_events()
    for category_index in _category_order(state.category_cursor()):
        category = CATEGORIES[category_index]
        for source in sorted(category.sources, key=lambda item: item.priority):
            for candidate in sorted(source.candidates, key=lambda item: item.rank):
                if candidate.event_id in published:
                    continue
                try:
                    _verify_award(candidate)
                    offer = _refresh_offer(candidate)
                except ProductAwardError as exc:
                    LOGGER.warning(
                        "Product-award candidate %s unavailable [%s]",
                        candidate.event_id,
                        exc.diagnostic_code,
                    )
                    continue
                if offer is None:
                    LOGGER.info("Product-award candidate %s has no current exact offer", candidate.event_id)
                    continue
                publication = ProductAwardPublication(
                    candidate=candidate,
                    offer=offer,
                    message=build_message(candidate, offer),
                )
                return category_index, publication
    return None


def preview_publications(now: datetime) -> tuple[ProductAwardPublication, ...]:
    publications: list[ProductAwardPublication] = []
    for category in CATEGORIES:
        accepted = None
        for source in sorted(category.sources, key=lambda item: item.priority):
            for candidate in sorted(source.candidates, key=lambda item: item.rank):
                try:
                    _verify_award(candidate)
                    offer = _refresh_offer(candidate)
                except ProductAwardError as exc:
                    LOGGER.warning(
                        "Product-award preview candidate %s unavailable [%s]",
                        candidate.event_id,
                        exc.diagnostic_code,
                    )
                    continue
                if offer is not None:
                    accepted = ProductAwardPublication(
                        candidate=candidate,
                        offer=offer,
                        message=build_message(candidate, offer),
                    )
                    break
            if accepted is not None:
                break
        if accepted is not None:
            publications.append(accepted)
    return tuple(publications)
