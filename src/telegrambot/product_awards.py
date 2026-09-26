"""Lightweight award feed for verified supermarket-listed products.

The core is intentionally source-agnostic:
- each award adapter discovers stable source items and parses its own format;
- adapters return verified ProductAwardCandidate objects with source-defined
  award identity plus explicit retail evidence;
- the shared core only deduplicates, queues, renders and delivers at most one
  item per day.

No LLM, browser, OCR, fuzzy product matching or catalogue crawl is required.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import unicodedata
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

LOGGER = logging.getLogger(__name__)

OCU_INDEX_URL = "https://www.ocu.org/ocu-salud"
WCCC_2026_TOP20_URL = "https://worldchampioncheese.org/2026-wccc-top-20-finalists/"
VALLE_WCCC_2026_URL = (
    "https://valledesanjuan.com/"
    "ocho-premios-que-saben-a-esfuerzo-origen-y-oficio/"
)
MERCADONA_API_ROOT = "https://tienda.mercadona.es/api/products"
MERCADONA_GUARDAMAR_WAREHOUSE = "alc1"  # reviewed for postal code 03140
REQUEST_TIMEOUT_SECONDS = 20
HTML_LIMIT_BYTES = 900_000
JSON_LIMIT_BYTES = 256_000
MAX_PUBLICATION_CANDIDATES = 4
USER_AGENT = "GuardamarMorningDigest/0.13"

PRIVATE_LABELS: dict[str, tuple[str, ...]] = {
    "Mercadona": ("Hacendado",),
    "Consum": ("Consum", "Consum Eco", "Consum Kids", "Kyrey", "Vitality"),
    "ALDI": ("La Tabla", "Milsani", "Cucina", "Moser Roth", "GutBio"),
    "Lidl": (
        "Roncero",
        "Deluxe",
        "Milbona",
        "Chef Select",
        "Crownfield",
        "Freshona",
        "Gelatelli",
        "Vemondo",
        "J.D. Gross",
        "Favorina",
        "La Cestera",
        "Realvalle",
        "Ocean Sea",
    ),
    "Carrefour": (
        "Carrefour",
        "Carrefour Classic",
        "Carrefour Extra",
        "Carrefour Original",
        "Carrefour Sensation",
        "Carrefour El Mercado",
    ),
    "DIA": ("DIA",),
    "Masymas": ("Alteza", "Deleitum"),
}


class ProductAwardError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.safe_description = description


@dataclass(frozen=True)
class PageDocument:
    url: str
    text: str
    links: tuple[str, ...]


RETAIL_RELATIONSHIPS = frozenset({"private_label", "exclusive", "listed"})


@dataclass(frozen=True)
class RetailEvidence:
    retailer: str
    relationship: str
    label: Optional[str] = None
    product_id: Optional[str] = None
    ean: Optional[str] = None
    product_url: Optional[str] = None
    variant: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.retailer, str) or not self.retailer.strip():
            raise ProductAwardError("retailer evidence needs a retailer", code="INVALID")
        if (
            not isinstance(self.relationship, str)
            or self.relationship not in RETAIL_RELATIONSHIPS
        ):
            raise ProductAwardError(
                "unsupported retailer relationship",
                code="INVALID",
            )
        for name, value in (
            ("label", self.label),
            ("product_id", self.product_id),
            ("ean", self.ean),
            ("product_url", self.product_url),
            ("variant", self.variant),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ProductAwardError(
                    f"invalid retail {name}",
                    code="INVALID",
                )
        if self.relationship == "private_label" and self.label is None:
            raise ProductAwardError(
                "private-label evidence needs the label",
                code="INVALID",
            )
        if self.ean is not None and not re.fullmatch(r"\d{8,14}", self.ean):
            raise ProductAwardError("invalid retail EAN/GTIN", code="INVALID")
        if self.product_url is not None:
            try:
                parsed = urllib.parse.urlsplit(self.product_url)
                port = parsed.port
            except ValueError as exc:
                raise ProductAwardError(
                    "invalid retail product URL",
                    code="INVALID",
                ) from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or port not in {None, 443}
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ProductAwardError("invalid retail product URL", code="INVALID")

    @property
    def has_exact_identity(self) -> bool:
        return bool(self.ean or self.product_id)


@dataclass(frozen=True)
class RetailOfferVariant:
    """Fresh exact-SKU retail offer used only at publication time."""

    package: str
    price: str
    unit_price: Optional[str] = None
    product_id: Optional[str] = None
    ean: Optional[str] = None
    product_url: Optional[str] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("package", self.package),
            ("price", self.price),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProductAwardError(
                    f"retail offer needs {name}",
                    code="INVALID",
                )
        for name, value in (
            ("unit_price", self.unit_price),
            ("product_id", self.product_id),
            ("ean", self.ean),
            ("product_url", self.product_url),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ProductAwardError(
                    f"invalid retail offer {name}",
                    code="INVALID",
                )
        if self.ean is not None and not re.fullmatch(r"\d{8,14}", self.ean):
            raise ProductAwardError("invalid retail offer EAN/GTIN", code="INVALID")
        if self.product_url is not None:
            try:
                parsed = urllib.parse.urlsplit(self.product_url)
                port = parsed.port
            except ValueError as exc:
                raise ProductAwardError(
                    "invalid retail offer product URL",
                    code="INVALID",
                ) from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or port not in {None, 443}
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ProductAwardError(
                    "invalid retail offer product URL",
                    code="INVALID",
                )


@dataclass(frozen=True)
class AwardEditorialFacts:
    comparison_size: Optional[int] = None
    category: Optional[str] = None
    judge_count: Optional[int] = None
    method_flags: tuple[str, ...] = ()
    standout: Optional[str] = None
    quality_label: Optional[str] = None
    producer: Optional[str] = None
    producer_location: Optional[str] = None
    production_country: Optional[str] = None
    headline_claim: Optional[str] = None
    product_summary: Optional[str] = None
    tasting_notes: tuple[str, ...] = ()
    composition_details: tuple[str, ...] = ()
    nutrition_details: tuple[str, ...] = ()
    method_summary: Optional[str] = None
    identity_details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.producer is not None and self.production_country is None:
            raise ProductAwardError(
                "producer facts require production country",
                code="INVALID",
            )


@dataclass(frozen=True)
class ProductAwardCandidate:
    source_kind: str
    event_key: str
    source_url: str
    product_name: str
    result: str
    award_body: str
    result_year: int
    retail: RetailEvidence
    score: Optional[str] = None
    source_price: Optional[str] = None
    editorial: AwardEditorialFacts = AwardEditorialFacts()

    @property
    def event_id(self) -> str:
        canonical = f"{self.source_kind}|{self.event_key}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    @property
    def retailer(self) -> str:
        return self.retail.retailer

    @property
    def private_label(self) -> Optional[str]:
        if self.retail.relationship != "private_label":
            return None
        return self.retail.label

    @property
    def sample_size(self) -> Optional[int]:
        return self.editorial.comparison_size


@dataclass(frozen=True)
class ProductAwardQueueItem:
    event_id: str
    detected_at: str
    candidate: ProductAwardCandidate


@dataclass(frozen=True)
class ProductAwardPublication:
    candidate: ProductAwardCandidate
    message: str


@dataclass(frozen=True)
class AwardSourceItem:
    candidates: tuple[ProductAwardCandidate, ...]


@dataclass(frozen=True)
class AwardSourceAdapter:
    name: str
    discover: Callable[[int], tuple[str, ...]]
    load: Callable[[str, int], AwardSourceItem]


@dataclass(frozen=True)
class _MercadonaProductContract:
    evidence: RetailEvidence
    supplier_names: tuple[str, ...]
    recipe_markers: tuple[str, ...] = ()


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._ignored = 0
        self._anchor_href: Optional[str] = None
        self._text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, Optional[str]]],
    ) -> None:
        tag = tag.casefold()
        values = {key.casefold(): value for key, value in attrs}
        if tag in {"script", "style", "svg", "noscript"}:
            self._ignored += 1
            return
        if self._ignored:
            return
        if tag == "a":
            href = values.get("href")
            self._anchor_href = href if isinstance(href, str) else None
        elif tag == "img":
            alt = values.get("alt")
            if isinstance(alt, str) and alt.strip():
                self._text.append(alt.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "svg", "noscript"}:
            if self._ignored:
                self._ignored -= 1
            return
        if self._ignored:
            return
        if tag == "a" and self._anchor_href is not None:
            self.links.append(urllib.parse.urljoin(self.base_url, self._anchor_href))
            self._anchor_href = None

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        value = " ".join(data.split())
        if value:
            self._text.append(value)

    def document(self) -> PageDocument:
        return PageDocument(
            url=self.base_url,
            text="\n".join(self._text),
            links=tuple(dict.fromkeys(self.links)),
        )


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    asciiish = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", asciiish.casefold()).split()
    )


def _phrase_count(text: str, phrase: str) -> int:
    tokens = _fold(text).split()
    needle = _fold(phrase).split()
    if not needle or len(needle) > len(tokens):
        return 0
    width = len(needle)
    return sum(
        1
        for index in range(len(tokens) - width + 1)
        if tokens[index : index + width] == needle
    )


def _phrase_present(text: str, phrase: str) -> bool:
    return _phrase_count(text, phrase) > 0


def _host_policy(hosts: frozenset[str]):
    normalized = frozenset(host.casefold() for host in hosts)

    def allowed(url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.casefold() in normalized
            and port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )

    return allowed


def _fetch_page(url: str, hosts: frozenset[str]) -> PageDocument:
    try:
        payload, final_url, _ = fetch_bounded(
            url,
            is_allowed_url=_host_policy(hosts),
            accepted_types=frozenset({"text/html"}),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": USER_AGENT,
            },
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            f"product-award source failed: {exc.code}",
            code=exc.code,
            description="источник наград временно недоступен",
        ) from exc
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProductAwardError(
            "product-award source is not UTF-8",
            code="ENCODING",
        ) from exc
    parser = _PageParser(final_url)
    parser.feed(source)
    parser.close()
    return parser.document()


def _fetch_json(url: str, hosts: frozenset[str]) -> Any:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_host_policy(hosts),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=JSON_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            f"product-award JSON source failed: {exc.code}",
            code=exc.code,
            description="источник товара временно недоступен",
        ) from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductAwardError(
            "product-award JSON source is invalid",
            code="PARSER",
        ) from exc


# ---------------------------------------------------------------------------
# OCU adapter
# ---------------------------------------------------------------------------

_OCU_RESULTS = ("Mejor del Análisis", "Compra Maestra")
_OCU_PRODUCT_PREFIX_STOPWORDS = frozenset({
    "que",
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "producto",
    "productos",
    "este",
    "esta",
    "es",
    "son",
    "obtiene",
    "obtenemos",
    "destacamos",
    "tambien",
})


def discover_ocu_documents(year: int) -> tuple[str, ...]:
    del year  # OCU index URLs themselves are not year-scoped.
    page = _fetch_page(
        OCU_INDEX_URL,
        frozenset({"www.ocu.org", "ocu.org"}),
    )
    urls: list[str] = []
    for value in page.links:
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            continue
        if parsed.hostname not in {"www.ocu.org", "ocu.org"}:
            continue
        path = parsed.path.rstrip("/")
        if not path.startswith("/alimentacion/") or "/informe/" not in path:
            continue
        canonical = urllib.parse.urlunsplit((
            "https",
            "www.ocu.org",
            path,
            "",
            "",
        ))
        if canonical not in urls:
            urls.append(canonical)
        if len(urls) >= 40:
            break
    return tuple(urls)


def _resolve_private_label(text: str) -> Optional[tuple[str, str]]:
    matches: list[tuple[int, int, str, str]] = []
    for retailer, labels in PRIVATE_LABELS.items():
        for label in labels:
            if not _phrase_present(text, label):
                continue
            if (
                _fold(label) == _fold(retailer)
                and _phrase_count(text, label) < 2
            ):
                continue
            matches.append(
                (len(_fold(label).split()), len(_fold(label)), retailer, label)
            )
    if not matches:
        return None
    matches.sort(reverse=True)
    specificity = matches[0][:2]
    best = {
        (retailer, label)
        for token_count, length, retailer, label in matches
        if (token_count, length) == specificity
    }
    if len(best) != 1:
        return None
    return next(iter(best))


def _ocu_product_name(
    line: str,
    private_label: str,
) -> Optional[str]:
    matches = list(
        re.finditer(re.escape(private_label), line, flags=re.IGNORECASE)
    )
    if not matches:
        return None
    match = matches[-1]
    prefix = line[: match.end()]
    tokens = re.findall(
        r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+",
        prefix,
    )
    label_tokens = re.findall(
        r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+",
        private_label,
    )
    take = min(len(tokens), len(label_tokens) + 5)
    selected = tokens[-take:]
    while selected and _fold(selected[0]) in _OCU_PRODUCT_PREFIX_STOPWORDS:
        selected.pop(0)
    while selected and _fold(selected[0]) in {"de", "del"}:
        selected.pop(0)
    value = " ".join(selected).strip()
    if not value or not _phrase_present(value, private_label):
        return None
    if _fold(value) == _fold(private_label):
        return None
    return value


_SPANISH_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    "septiembre|octubre|noviembre|diciembre"
)


def _ocu_report_year(text: str) -> Optional[int]:
    match = re.search(
        rf"\b\d{{1,2}}\s+(?:{_SPANISH_MONTHS})\s+(20\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _ocu_sample_size(text: str) -> Optional[int]:
    match = re.search(
        r"\bhemos\s+analizado\s+(\d{1,3})\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 500 else None


def _ocu_score(text: str) -> Optional[str]:
    match = re.search(r"\b(\d{1,3}/100)\b", text)
    return match.group(1) if match else None


def _ocu_source_price(text: str) -> Optional[str]:
    match = re.search(
        r"\bprecio[^0-9]{0,30}(\d+(?:[.,]\d+)?)\s*euros?\s*/\s*"
        r"(litro|kg|kilo)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    amount = match.group(1).replace(".", ",")
    if amount.endswith(",0"):
        amount = amount[:-2]
    unit = "л" if match.group(2).casefold() == "litro" else "кг"
    return f"{amount} €/{unit}"


def _ocu_global_editorial_facts(
    text: str,
    sample_size: Optional[int],
) -> AwardEditorialFacts:
    folded = _fold(text)
    flags: list[str] = []
    for needle, flag in (
        ("etiquet", "labeling"),
        ("composicion", "composition"),
        ("valor nutricional", "nutrition"),
        ("escala saludable", "nutrition"),
        ("cata profesional", "professional_tasting"),
    ):
        if needle in folded and flag not in flags:
            flags.append(flag)
    return AwardEditorialFacts(
        comparison_size=sample_size,
        method_flags=tuple(flags),
    )


def _ocu_local_editorial_facts(
    global_facts: AwardEditorialFacts,
    text: str,
) -> AwardEditorialFacts:
    folded = _fold(text)
    standout = None
    if (
        "mejor valorado en la cata profesional" in folded
        or "mejor valorada en la cata profesional" in folded
    ):
        standout = "best_professional_tasting"
    quality_label = "Buena Elección" if "buena eleccion" in folded else None
    return AwardEditorialFacts(
        comparison_size=global_facts.comparison_size,
        method_flags=global_facts.method_flags,
        standout=standout,
        quality_label=quality_label,
    )


def parse_ocu_awards(
    document: PageDocument,
    year: int,
) -> tuple[ProductAwardCandidate, ...]:
    if _ocu_report_year(document.text) != year:
        return ()

    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    sample_size = _ocu_sample_size(document.text)
    global_editorial = _ocu_global_editorial_facts(document.text, sample_size)
    candidates: list[ProductAwardCandidate] = []

    previous_result_index = -1
    for index, line in enumerate(lines):
        result = next(
            (name for name in _OCU_RESULTS if _phrase_present(line, name)),
            None,
        )
        if result is None:
            continue

        # Prefer the exact result line when it already names the private label.
        # If OCU split a linked product name across text nodes, look backwards
        # only within this result block and never across the previous award.
        direct_owner = _resolve_private_label(line)
        if direct_owner is not None:
            identity_window = line
            owner = direct_owner
        else:
            start = max(previous_result_index + 1, index - 6, 0)
            identity_window = " ".join(lines[start : index + 1])
            owner = _resolve_private_label(identity_window)

        previous_result_index = index
        if owner is None:
            continue
        retailer, private_label = owner
        product_name = _ocu_product_name(identity_window, private_label)
        if product_name is None:
            raise ProductAwardError(
                f"OCU award product could not be parsed: {document.url}",
                code="PARSER",
            )

        # Score/price can also be separate text nodes. Stop at the next
        # result marker so another product's score/price cannot leak in.
        end = min(len(lines), index + 6)
        for next_index in range(index + 1, end):
            if any(
                _phrase_present(lines[next_index], marker)
                for marker in _OCU_RESULTS
            ):
                end = next_index
                break
        window = " ".join(lines[index:end])
        score = _ocu_score(window)
        source_price = _ocu_source_price(window)
        editorial = _ocu_local_editorial_facts(global_editorial, window)
        event_key = "|".join((
            str(year),
            document.url,
            _fold(private_label),
            _fold(product_name),
        ))
        candidates.append(ProductAwardCandidate(
            source_kind="ocu",
            event_key=event_key,
            source_url=document.url,
            product_name=product_name,
            result=result,
            award_body="OCU",
            result_year=year,
            retail=RetailEvidence(
                retailer=retailer,
                relationship="private_label",
                label=private_label,
            ),
            score=score,
            source_price=source_price,
            editorial=editorial,
        ))

    unique: dict[str, ProductAwardCandidate] = {}
    order: list[str] = []
    priority = {"Mejor del Análisis": 2, "Compra Maestra": 1}
    for candidate in candidates:
        event_id = candidate.event_id
        existing = unique.get(event_id)
        if existing is None:
            unique[event_id] = candidate
            order.append(event_id)
            continue
        if priority.get(candidate.result, 0) <= priority.get(existing.result, 0):
            continue
        unique[event_id] = ProductAwardCandidate(
            source_kind=candidate.source_kind,
            event_key=candidate.event_key,
            source_url=candidate.source_url,
            product_name=candidate.product_name,
            result=candidate.result,
            award_body=candidate.award_body,
            result_year=candidate.result_year,
            retail=candidate.retail,
            score=candidate.score or existing.score,
            source_price=candidate.source_price or existing.source_price,
            editorial=candidate.editorial,
        )
    return tuple(unique[event_id] for event_id in order)


def _score_out_of_100(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    match = re.fullmatch(r"(\d{1,3}(?:[.,]\d+)?)/100", value.strip())
    if match is None:
        return None
    score = float(match.group(1).replace(",", "."))
    return score if 0 <= score <= 100 else None


def _ocu_publication_eligible(candidate: ProductAwardCandidate) -> bool:
    """OCU editorial gate: only exceptional overall scores are publishable."""

    score = _score_out_of_100(candidate.score)
    return score is not None and score >= 85.0


def load_ocu_item(url: str, year: int) -> AwardSourceItem:
    document = _fetch_page(
        url,
        frozenset({"www.ocu.org", "ocu.org"}),
    )
    candidates = [
        candidate
        for candidate in parse_ocu_awards(document, year)
        if _ocu_publication_eligible(candidate)
    ]
    candidates.sort(
        key=lambda candidate: _score_out_of_100(candidate.score) or 0.0,
        reverse=True,
    )
    return AwardSourceItem(tuple(candidates))


# ---------------------------------------------------------------------------
# World Championship Cheese Contest 2026 — reviewed Top-20 slice
# ---------------------------------------------------------------------------

_WCCC_2026_CHEESE = "Seleccion Tostado Mixed Milk Cheese Extra Aged"
_WCCC_2026_MAKER = "Queserías Entrepinares S.A.U."
_WCCC_2026_COMPANY = "Queserías Entrepinares"
_WCCC_2026_LOCATION = "Valladolid, Spain"
_WCCC_2026_CLASS = "114"
_WCCC_2026_RETAIL_PRODUCT_ID = "50952"
_WCCC_2026_RETAIL_EAN = "8480000509529"
_WCCC_2026_RETAIL_URL = (
    "https://tienda.mercadona.es/product/50952/"
    "queso-anejo-tostado-mezcla-hacendado-pieza"
)

_WCCC_2026_METHOD_SUMMARY = (
    "В 2026 году 56 профессиональных судей оценивали 3 375 продуктов. "
    "В жюри вошли сырные эксперты, закупщики, преподаватели молочной науки "
    "и исследователи из 22 стран. Каждую заявку осматривают, нюхают и "
    "дегустируют технические судьи. Оценка начинается со 100 баллов, затем "
    "баллы снимаются за недостатки вкуса, структуры и текстуры, соли, цвета, "
    "послевкусия, упаковки и других характеристик."
)


def _mercadona_evidence(
    product_id: str,
    ean: str,
    share_url: str,
    *,
    variant: str = "кусок переменного веса",
) -> RetailEvidence:
    return RetailEvidence(
        retailer="Mercadona",
        relationship="private_label",
        label="Hacendado",
        product_id=product_id,
        ean=ean,
        product_url=share_url,
        variant=variant,
    )


_MERCADONA_CONTRACTS: dict[str, _MercadonaProductContract] = {
    "50952": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "50952",
            "8480000509529",
            _WCCC_2026_RETAIL_URL,
        ),
        supplier_names=("Queserías Entrepinares S.A.U.",),
        recipe_markers=("vaca 50", "oveja 20", "cabra 15"),
    ),
    "4883": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "4883",
            "8480000048837",
            "https://tienda.mercadona.es/product/4883/"
            "queso-curado-mezcla-con-trufa-hacendado-pieza",
        ),
        supplier_names=(
            "Valle de San Juan Palencia S.L.",
            "Valle de San Juan S.L.",
        ),
        recipe_markers=("vaca min 35", "oveja min 25", "cabra min 25", "trufa min 2"),
    ),
    "50975": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "50975",
            "2105600509750",
            "https://tienda.mercadona.es/product/50975/"
            "queso-anejo-fuerte-oveja-hacendado-pieza",
        ),
        supplier_names=(
            "Valle de San Juan Palencia S.L.",
            "Valle de San Juan S.L.",
        ),
        recipe_markers=("leche cruda de oveja",),
    ),
    "11680": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "11680",
            "8402001028878",
            "https://tienda.mercadona.es/product/11680/"
            "queso-anejo-fuerte-oveja-hacendado-cortado-cunitas-pieza",
            variant="нарезка клиньями",
        ),
        supplier_names=(
            "Valle de San Juan Palencia S.L",
            "Distribuciones Juan Luna S.L.U",
        ),
        recipe_markers=("leche cruda de oveja",),
    ),
    "11682": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "11682",
            "8402001028953",
            "https://tienda.mercadona.es/product/11682/"
            "queso-curado-mezcla-afrutado-hacendado-cortado-cunitas-pieza",
            variant="нарезка клиньями",
        ),
        supplier_names=(
            "Valle de San Juan Palencia S.L.",
            "Distribuciones Juan Luna S.L.U",
        ),
        recipe_markers=("vaca min 80", "oveja min 5", "cabra min 5"),
    ),
    "5548": _MercadonaProductContract(
        evidence=_mercadona_evidence(
            "5548",
            "8402001048289",
            "https://tienda.mercadona.es/product/5548/"
            "queso-anejo-iberico-mezcla-hacendado-cortado-cunitas-pieza",
            variant="нарезка клиньями",
        ),
        supplier_names=(
            "Valle de San Juan Palencia S.L.",
            "Distribuciones Juan Luna S.L.U.",
        ),
        recipe_markers=("vaca min 35", "oveja min 25", "cabra min 25"),
    ),
}

_MERCADONA_RELATED_VARIANTS: dict[str, tuple[str, ...]] = {
    "50975": ("11680",),
}


def discover_wccc_documents(year: int) -> tuple[str, ...]:
    # Only the reviewed 2026 publication contract is enabled. A future edition
    # must be revalidated rather than guessed from a URL pattern.
    if year != 2026:
        return ()
    try:
        document = _fetch_page(
            WCCC_2026_TOP20_URL,
            frozenset({"worldchampioncheese.org"}),
        )
    except ProductAwardError as exc:
        if exc.diagnostic_code == "HTTP-404":
            return ()
        raise
    if _fold("2026 WCCC Top 20 Finalists") not in _fold(document.text):
        raise ProductAwardError(
            "WCCC Top-20 page has unexpected shape",
            code="PARSER",
        )
    return (WCCC_2026_TOP20_URL,)


def parse_wccc_top20(
    document: PageDocument,
    year: int,
) -> tuple[ProductAwardCandidate, ...]:
    if year != 2026:
        return ()
    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    target = _fold(f"Cheese: {_WCCC_2026_CHEESE}")
    for index, line in enumerate(lines):
        if _fold(line) != target:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 5)
        block = "\n".join(lines[start:end])
        required = (
            f"Class #: {_WCCC_2026_CLASS}",
            f"Cheese: {_WCCC_2026_CHEESE}",
            f"Maker: {_WCCC_2026_MAKER}",
            f"Company: {_WCCC_2026_COMPANY}",
            f"Location: {_WCCC_2026_LOCATION}",
        )
        if not all(_fold(value) in _fold(block) for value in required):
            raise ProductAwardError(
                "WCCC reviewed finalist block changed",
                code="PARSER",
            )
        return (
            ProductAwardCandidate(
                source_kind="wccc",
                event_key=(
                    f"{year}|top20|class-{_WCCC_2026_CLASS}|"
                    f"{_fold(_WCCC_2026_CHEESE)}"
                ),
                source_url=document.url,
                product_name="Queso añejo tostado mezcla Hacendado",
                result="Top 20 finalist",
                award_body="World Championship Cheese Contest 2026",
                result_year=year,
                retail=_MERCADONA_CONTRACTS["50952"].evidence,
                editorial=AwardEditorialFacts(
                    comparison_size=3375,
                    category="Hard Mixed Milk Cheeses",
                    judge_count=56,
                    producer=_WCCC_2026_MAKER,
                    producer_location="Вальядолид",
                    production_country="Испания",
                    headline_claim="вошёл в мировой Top 20 сыров",
                    product_summary=(
                        "Твёрдый выдержанный сыр из смеси коровьего, "
                        "овечьего и козьего молока."
                    ),
                    composition_details=(
                        "коровье молоко — не менее 50%",
                        "овечье молоко — не менее 20%",
                        "козье молоко — не менее 15%",
                    ),
                    method_summary=_WCCC_2026_METHOD_SUMMARY,
                ),
            ),
        )
    return ()


def load_wccc_item(url: str, year: int) -> AwardSourceItem:
    if url != WCCC_2026_TOP20_URL:
        raise ProductAwardError("unexpected WCCC source URL", code="URL-POLICY")
    document = _fetch_page(
        url,
        frozenset({"worldchampioncheese.org"}),
    )
    return AwardSourceItem(parse_wccc_top20(document, year))


# ---------------------------------------------------------------------------
# Reviewed one-time launch seed
# ---------------------------------------------------------------------------

def _valle_wccc_seed_candidates() -> tuple[ProductAwardCandidate, ...]:
    # Reviewed launch data, verified 26 September 2026 from Valle de San Juan's
    # own WCCC 2026 result announcement and Mercadona portfolio. Those pages are
    # historical evidence and are not runtime dependencies because the producer
    # host is not reliably reachable from the bounded bot transport. Dynamic
    # retail identity, recipe, availability and price are still revalidated
    # against Mercadona before every publication.
    common = dict(
        source_kind="wccc_valle_seed",
        source_url=VALLE_WCCC_2026_URL,
        award_body="World Championship Cheese Contest 2026",
        result_year=2026,
    )
    common_editorial = dict(
        comparison_size=3375,
        judge_count=56,
        producer="Valle de San Juan",
        producer_location="Паленсия",
        production_country="Испания",
        method_summary=_WCCC_2026_METHOD_SUMMARY,
    )

    return (
        ProductAwardCandidate(
            **common,
            event_key="2026|valle|con-trufa|99.30",
            product_name="Queso curado mezcla con trufa Hacendado",
            result="Best of Class",
            retail=_MERCADONA_CONTRACTS["4883"].evidence,
            score="99,30/100",
            editorial=AwardEditorialFacts(
                **common_editorial,
                headline_claim="стал лучшим в своей категории на мировом конкурсе",
                product_summary=(
                    "Выдержанный иберийский сыр из сырого коровьего, овечьего "
                    "и козьего молока с кремом из трюфеля."
                ),
                tasting_notes=(
                    "выраженный аромат трюфеля",
                    "землистые и грибные оттенки",
                    "ноты сливочного масла и лёгкая сладость",
                    "ломкая текстура",
                ),
                composition_details=(
                    "коровье молоко — не менее 35%",
                    "овечье молоко — не менее 25%",
                    "козье молоко — не менее 25%",
                    "крем из трюфеля — не менее 2%",
                ),
                nutrition_details=(
                    "437 ккал",
                    "жиры — 37 г",
                    "белки — 24 г",
                    "соль — 2 г",
                ),
            ),
        ),
        ProductAwardCandidate(
            **common,
            event_key="2026|valle|anejo|99.25",
            product_name="Queso añejo fuerte de oveja Hacendado",
            result="99.25 points",
            retail=_MERCADONA_CONTRACTS["50975"].evidence,
            score="99,25/100",
            editorial=AwardEditorialFacts(
                **common_editorial,
                headline_claim="получил выдающуюся оценку на мировом конкурсе",
                product_summary="Долго выдержанный сыр из сырого овечьего молока.",
                tasting_notes=(
                    "интенсивный и стойкий вкус",
                    "ноты овечьего сливочного масла, кожи, ферментированных трав и злаков",
                    "приятная пикантность в долгом послевкусии",
                    "интенсивность — 6 из 6",
                ),
                composition_details=("сырое овечье молоко",),
                nutrition_details=(
                    "470 ккал",
                    "жиры — 40 г",
                    "белки — 25 г",
                    "соль — 1,7 г",
                ),
            ),
        ),
        ProductAwardCandidate(
            **common,
            event_key="2026|valle|afrutado|97.40",
            product_name="Queso curado mezcla afrutado Hacendado cortado en cuñitas",
            result="97.40 points",
            retail=_MERCADONA_CONTRACTS["11682"].evidence,
            score="97,40/100",
            editorial=AwardEditorialFacts(
                **common_editorial,
                headline_claim="получил выдающуюся оценку на мировом конкурсе",
                product_summary=(
                    "Выдержанный пастеризованный сыр из смеси коровьего, "
                    "овечьего и козьего молока, продающийся уже нарезанным "
                    "на небольшие клинья."
                ),
                composition_details=(
                    "коровье молоко — не менее 80%",
                    "овечье молоко — не менее 5%",
                    "козье молоко — не менее 5%",
                ),
            ),
        ),
        ProductAwardCandidate(
            **common,
            event_key="2026|valle|iberico-anejo|97.20",
            product_name="Queso añejo ibérico mezcla Hacendado cortado en cuñitas",
            result="97.20 points",
            retail=_MERCADONA_CONTRACTS["5548"].evidence,
            score="97,20/100",
            editorial=AwardEditorialFacts(
                **common_editorial,
                headline_claim="получил выдающуюся оценку на мировом конкурсе",
                product_summary=(
                    "Долго выдержанный иберийский сыр из сырого коровьего, "
                    "овечьего и козьего молока."
                ),
                tasting_notes=(
                    "глубокий и стойкий вкус после длительной выдержки",
                    "плотная и ломкая текстура",
                    "интенсивность — 5 из 6",
                ),
                composition_details=(
                    "коровье молоко — не менее 35%",
                    "овечье молоко — не менее 25%",
                    "козье молоко — не менее 25%",
                ),
                nutrition_details=(
                    "437 ккал",
                    "жиры — 37 г",
                    "белки — 24 г",
                    "соль — 2 г",
                ),
            ),
        ),
    )


def reviewed_starter_product_awards(year: int) -> tuple[ProductAwardCandidate, ...]:
    if year != 2026:
        return ()

    valle = _valle_wccc_seed_candidates()
    top20 = load_wccc_item(WCCC_2026_TOP20_URL, 2026).candidates
    if len(top20) != 1:
        raise ProductAwardError(
            "reviewed WCCC Top-20 starter candidate is unavailable",
            code="PARSER",
        )

    # Hand-reviewed launch order: strongest numeric results first, with the
    # organizer-confirmed Top-20 item inserted before the remaining 97-point
    # products. The shared runtime queue itself remains source-agnostic FIFO.
    return (valle[0], valle[1], top20[0], valle[2], valle[3])


# Add future validated adapters here. A new adapter only needs a stable list of
# item IDs and a loader that returns verified ProductAwardCandidate objects.
SOURCE_ADAPTERS: tuple[AwardSourceAdapter, ...] = (
    AwardSourceAdapter("ocu", discover_ocu_documents, load_ocu_item),
    AwardSourceAdapter("wccc", discover_wccc_documents, load_wccc_item),
)


# ---------------------------------------------------------------------------
# Shared renderer
# ---------------------------------------------------------------------------

def _display_product(value: str) -> str:
    value = " ".join(value.split()).strip()
    if not value:
        return value
    return value[0].upper() + value[1:]


def _source_link_label(candidate: ProductAwardCandidate) -> str:
    if candidate.source_kind == "ocu":
        return "Исследование OCU"
    if candidate.source_kind == "wccc":
        return "World Championship Cheese Contest 2026"
    if candidate.source_kind == "wccc_valle_seed":
        return "Результаты Valle de San Juan на WCCC 2026"
    return candidate.award_body


def _retail_phrase(candidate: ProductAwardCandidate) -> str:
    evidence = candidate.retail
    if evidence.relationship == "private_label":
        return (
            f"продукт собственной марки {evidence.label} "
            f"из {evidence.retailer}"
        )
    if evidence.relationship == "exclusive":
        return f"товар, эксклюзивно представленный в {evidence.retailer}"
    return f"товар, который продаётся в {evidence.retailer}"


def _ocu_method_sentence(facts: AwardEditorialFacts) -> Optional[str]:
    flags = set(facts.method_flags)
    parts: list[str] = []
    if "labeling" in flags and "composition" in flags:
        parts.append("проверяли маркировку и состав")
    elif "labeling" in flags:
        parts.append("проверяли маркировку")
    elif "composition" in flags:
        parts.append("проверяли состав")
    if "nutrition" in flags:
        parts.append("оценивали пищевую ценность")
    if "professional_tasting" in flags:
        parts.append("проводили профессиональную дегустацию")
    if not parts:
        return None
    return "В исследовании " + ", ".join(parts) + "."


def _render_offer(offer: RetailOfferVariant) -> str:
    value = f"• <b>{html.escape(offer.package)}</b> — {html.escape(offer.price)}"
    if offer.unit_price is not None:
        value += f" · {html.escape(offer.unit_price)}"
    return value


def _render_method_block(candidate: ProductAwardCandidate) -> Optional[str]:
    facts = candidate.editorial
    lines: list[str] = []

    if facts.method_summary is not None:
        lines.append(facts.method_summary)
    elif candidate.source_kind == "ocu":
        method_sentence = _ocu_method_sentence(facts)
        if candidate.sample_size is not None:
            lines.append(f"OCU сравнила {candidate.sample_size} продуктов.")
        if method_sentence is not None:
            lines.append(method_sentence)
    else:
        if facts.comparison_size is not None:
            lines.append(
                f"В конкурсе участвовало {facts.comparison_size} продуктов."
            )
        if facts.judge_count is not None:
            lines.append(f"Оценивали {facts.judge_count} судей.")

    if not lines:
        return None
    escaped = "\n\n".join(html.escape(line) for line in lines)
    return (
        "<blockquote expandable><b>Как оценивали</b>\n\n"
        + escaped
        + "</blockquote>"
    )


def build_publication(
    candidate: ProductAwardCandidate,
    *,
    current_offers: Sequence[RetailOfferVariant] = (),
) -> ProductAwardPublication:
    product = _display_product(candidate.product_name)
    facts = candidate.editorial
    sections: list[str] = []

    if candidate.source_kind == "ocu":
        if candidate.result == "Mejor del Análisis":
            headline = f"{product} в {candidate.retailer} — лучший в тесте OCU"
            intro = (
                f"{product} получил статус Mejor del Análisis — "
                "лучший результат сравнительного теста OCU."
            )
        elif candidate.result == "Compra Maestra":
            headline = (
                f"{product} в {candidate.retailer} — выбор OCU "
                "по качеству и цене"
            )
            intro = (
                f"{product} получил отметку Compra Maestra — "
                "за удачное соотношение качества и цены."
            )
        else:
            headline = f"{product} в {candidate.retailer} — результат OCU"
            intro = (
                f"{product} получил результат {candidate.result} "
                "в исследовании OCU."
            )
    elif candidate.source_kind == "wccc":
        claim = facts.headline_claim or "вошёл в Top 20 конкурса WCCC"
        headline = f"{product} в {candidate.retailer} — {claim}"
        intro = (
            f"{product}, {_retail_phrase(candidate)}, вошёл в Top 20 "
            "финалистов World Championship Cheese Contest 2026."
        )
    elif candidate.source_kind == "wccc_valle_seed":
        claim = facts.headline_claim or "получил высокую оценку на WCCC 2026"
        headline = f"{product} в {candidate.retailer} — {claim}"
        prefix = (
            "По результатам, опубликованным производителем Valle de San Juan, "
            f"{product}, {_retail_phrase(candidate)}, получил "
        )
        if candidate.result == "Best of Class":
            intro = (
                prefix
                + f"{candidate.score} на World Championship Cheese Contest 2026 "
                "и стал лучшим в своей категории."
            )
        else:
            intro = (
                prefix
                + f"{candidate.score} на World Championship Cheese Contest 2026."
            )
    else:
        claim = facts.headline_claim or (
            f"{candidate.result} на {candidate.award_body}"
        )
        headline = f"{product} в {candidate.retailer} — {claim}"
        intro = (
            f"{product}, {_retail_phrase(candidate)}, получил "
            f"{candidate.result} на {candidate.award_body}."
        )

    if candidate.score is not None and candidate.source_kind != "wccc_valle_seed":
        intro += f" Итоговая оценка — {candidate.score}."
    sections.append(html.escape(intro))

    product_lines: list[str] = []
    if facts.product_summary is not None:
        product_lines.append(html.escape(facts.product_summary))
    if facts.tasting_notes:
        product_lines.append(
            "<b>Вкус и особенности:</b> "
            + html.escape("; ".join(facts.tasting_notes))
            + "."
        )
    if facts.composition_details:
        product_lines.append(
            "<b>Состав:</b>\n"
            + "\n".join(
                "• " + html.escape(item)
                for item in facts.composition_details
            )
        )
    if facts.nutrition_details:
        product_lines.append(
            "<b>На 100 г:</b>\n"
            + "\n".join(
                "• " + html.escape(item)
                for item in facts.nutrition_details
            )
        )
    if product_lines:
        sections.append(
            "🧀 <b>Что это за продукт</b>\n\n"
            + "\n\n".join(product_lines)
        )

    if facts.standout == "best_professional_tasting":
        sections.append(
            "Особенно хорошо продукт показал себя на профессиональной "
            "дегустации: OCU назвала его лучшим по этому этапу."
        )
    if facts.quality_label is not None:
        sections.append(
            "По своей шкале пищевого состава OCU также отнесла продукт "
            f"к категории {html.escape(facts.quality_label)}."
        )

    if facts.production_country is not None:
        producer_bits: list[str] = []
        if facts.producer is not None:
            producer_bits.append(facts.producer)
        if facts.producer_location is not None:
            producer_bits.append(facts.producer_location)
        producer_bits.append(facts.production_country)
        if facts.producer is not None:
            sections.append(
                "<b>Производитель</b> — "
                + html.escape(", ".join(producer_bits))
                + "."
            )
        else:
            sections.append(
                "<b>Страна производства</b> — "
                + html.escape(facts.production_country)
                + "."
            )

    if current_offers:
        unique_offers = tuple(dict.fromkeys(current_offers))
        sections.append(
            f"🛒 <b>Сейчас в {html.escape(candidate.retailer)}</b>\n\n"
            + "\n".join(_render_offer(offer) for offer in unique_offers)
        )
    elif candidate.source_price is not None:
        sections.append(
            "В исследовании указана цена "
            + html.escape(candidate.source_price)
            + "."
        )

    method_block = _render_method_block(candidate)
    if method_block is not None:
        sections.append(method_block)

    source_url = html.escape(candidate.source_url, quote=True)
    link_label = html.escape(_source_link_label(candidate))
    message = with_footer(
        "🏆 <b>"
        + html.escape(headline)
        + "</b>\n\n"
        + "\n\n".join(sections)
        + f'\n\n🔗 <a href="{source_url}">{link_label}</a>'
    )
    if len(message) > 4096:
        raise ProductAwardError(
            "product-award message exceeds Telegram limit",
            code="MESSAGE-LENGTH",
        )
    return ProductAwardPublication(candidate=candidate, message=message)


# ---------------------------------------------------------------------------
# Publication-time exact retail refresh
# ---------------------------------------------------------------------------

def _format_decimal_price(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return f"{number:.2f}".replace(".", ",")


def _mercadona_package_label(payload: dict[str, Any]) -> Optional[str]:
    prices = payload.get("price_instructions")
    if not isinstance(prices, dict):
        return None
    size = prices.get("unit_size")
    unit = prices.get("size_format")
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return None
    if unit == "kg":
        grams = int(round(float(size) * 1000))
        label = f"{grams} г"
    elif unit == "l":
        millilitres = int(round(float(size) * 1000))
        label = f"{millilitres} мл" if millilitres < 1000 else f"{size:g} л"
    else:
        return None
    if payload.get("is_variable_weight") is True or prices.get("approx_size") is True:
        label = "около " + label
    return label


def _refresh_one_mercadona_offer(
    candidate: ProductAwardCandidate,
    evidence: RetailEvidence,
) -> Optional[RetailOfferVariant]:
    if evidence.product_id is None or not re.fullmatch(r"\d{1,12}", evidence.product_id):
        raise ProductAwardError("invalid Mercadona product ID", code="INVALID")

    contract = _MERCADONA_CONTRACTS.get(evidence.product_id)
    if contract is not None and evidence != contract.evidence:
        raise ProductAwardError(
            "Mercadona reviewed identity contract changed",
            code="PARSER",
        )

    url = (
        f"{MERCADONA_API_ROOT}/{evidence.product_id}/"
        f"?lang=es&wh={MERCADONA_GUARDAMAR_WAREHOUSE}"
    )
    payload = _fetch_json(url, frozenset({"tienda.mercadona.es"}))
    if not isinstance(payload, dict):
        raise ProductAwardError("invalid Mercadona product payload", code="PARSER")
    if str(payload.get("id")) != evidence.product_id:
        raise ProductAwardError("Mercadona product ID mismatch", code="PARSER")
    if payload.get("published") is not True:
        return None
    if payload.get("unavailable_from") not in {None, ""}:
        return None
    unavailable_weekdays = payload.get("unavailable_weekdays")
    if not isinstance(unavailable_weekdays, list):
        raise ProductAwardError(
            "Mercadona availability shape changed",
            code="PARSER",
        )
    if unavailable_weekdays:
        return None

    ean = payload.get("ean")
    if evidence.ean is not None and str(ean) != evidence.ean:
        raise ProductAwardError("Mercadona EAN mismatch", code="PARSER")
    brand = payload.get("brand")
    if (
        evidence.relationship == "private_label"
        and evidence.label is not None
        and _fold(str(brand)) != _fold(evidence.label)
    ):
        raise ProductAwardError("Mercadona brand mismatch", code="PARSER")

    details = payload.get("details")
    if not isinstance(details, dict):
        raise ProductAwardError("Mercadona supplier data missing", code="PARSER")
    suppliers = details.get("suppliers")
    if not isinstance(suppliers, list):
        raise ProductAwardError("Mercadona supplier data missing", code="PARSER")
    supplier_names = {
        _fold(str(item.get("name")))
        for item in suppliers
        if isinstance(item, dict) and item.get("name")
    }

    if contract is not None:
        expected_suppliers = {_fold(name) for name in contract.supplier_names}
        if not supplier_names & expected_suppliers:
            raise ProductAwardError("Mercadona supplier mismatch", code="PARSER")
        if contract.recipe_markers:
            nutrition = payload.get("nutrition_information")
            if not isinstance(nutrition, dict):
                raise ProductAwardError(
                    "Mercadona ingredient data missing",
                    code="PARSER",
                )
            ingredients = nutrition.get("ingredients")
            if not isinstance(ingredients, str):
                raise ProductAwardError(
                    "Mercadona ingredient data missing",
                    code="PARSER",
                )
            ingredient_text = html.unescape(
                re.sub(r"<[^>]+>", " ", ingredients)
            )
            if not all(
                _phrase_present(ingredient_text, marker)
                for marker in contract.recipe_markers
            ):
                raise ProductAwardError(
                    "Mercadona awarded recipe changed",
                    code="PARSER",
                )
    elif candidate.editorial.producer is not None:
        if _fold(candidate.editorial.producer) not in supplier_names:
            raise ProductAwardError("Mercadona supplier mismatch", code="PARSER")

    prices = payload.get("price_instructions")
    package = _mercadona_package_label(payload)
    if not isinstance(prices, dict) or package is None:
        raise ProductAwardError("Mercadona offer shape changed", code="PARSER")

    price = _format_decimal_price(prices.get("unit_price"))
    reference = _format_decimal_price(prices.get("reference_price"))
    reference_format = prices.get("reference_format")
    if price is None:
        return None
    unit_price = None
    if reference is not None and reference_format in {"kg", "l"}:
        suffix = "кг" if reference_format == "kg" else "л"
        unit_price = f"{reference} €/{suffix}"

    share_url = payload.get("share_url")
    if not isinstance(share_url, str) or not _host_policy(
        frozenset({"tienda.mercadona.es"})
    )(share_url):
        raise ProductAwardError("Mercadona product URL changed", code="PARSER")
    if evidence.product_url is not None and share_url != evidence.product_url:
        raise ProductAwardError("Mercadona product URL mismatch", code="PARSER")

    if evidence.variant is not None:
        package = f"{package} · {evidence.variant}"

    return RetailOfferVariant(
        package=package,
        price=f"{price} €",
        unit_price=unit_price,
        product_id=evidence.product_id,
        ean=str(ean) if ean is not None else None,
        product_url=share_url,
    )


def refresh_mercadona_offers(
    candidate: ProductAwardCandidate,
) -> tuple[RetailOfferVariant, ...]:
    evidence = candidate.retail
    if evidence.retailer != "Mercadona" or evidence.product_id is None:
        return ()

    identities: list[RetailEvidence] = [evidence]
    for related_id in _MERCADONA_RELATED_VARIANTS.get(evidence.product_id, ()):
        contract = _MERCADONA_CONTRACTS.get(related_id)
        if contract is None:
            raise ProductAwardError(
                "Mercadona related retail contract is missing",
                code="PARSER",
            )
        identities.append(contract.evidence)

    offers: list[RetailOfferVariant] = []
    for identity in identities:
        offer = _refresh_one_mercadona_offer(candidate, identity)
        if offer is not None:
            offers.append(offer)
    return tuple(offers)


def refresh_retail_offers(
    candidate: ProductAwardCandidate,
) -> tuple[RetailOfferVariant, ...]:
    if candidate.retail.retailer == "Mercadona":
        return refresh_mercadona_offers(candidate)
    return ()


def build_current_publication(
    candidate: ProductAwardCandidate,
) -> Optional[ProductAwardPublication]:
    try:
        offers = refresh_retail_offers(candidate)
    except ProductAwardError as exc:
        LOGGER.warning(
            "Product-award retail refresh failed for %s [%s]",
            candidate.event_id,
            exc.diagnostic_code,
        )
        return None
    if not offers:
        LOGGER.info(
            "Product-award candidate %s has no verified current retail offer",
            candidate.event_id,
        )
        return None
    return build_publication(candidate, current_offers=offers)


def preview_starter_product_awards(
    year: int,
) -> tuple[ProductAwardPublication, ...]:
    candidates = reviewed_starter_product_awards(year)
    publications: list[ProductAwardPublication] = []
    for candidate in candidates:
        publication = build_current_publication(candidate)
        if publication is None:
            raise ProductAwardError(
                "reviewed starter pool is not fully available",
                code="SEED-INCOMPLETE",
            )
        publications.append(publication)
    return tuple(publications)


def seed_starter_product_awards(
    now: datetime,
    state: "ProductAwardState",
) -> tuple[ProductAwardCandidate, ...]:
    candidates = reviewed_starter_product_awards(now.year)
    if not candidates:
        raise ProductAwardError(
            "no reviewed starter pool exists for this year",
            code="SEED-UNAVAILABLE",
        )

    # Validate the complete launch set before touching persistent state.
    for candidate in candidates:
        if build_current_publication(candidate) is None:
            raise ProductAwardError(
                "reviewed starter pool is not fully available",
                code="SEED-INCOMPLETE",
            )

    state.enqueue_candidates(candidates, now.date())
    return candidates


# ---------------------------------------------------------------------------
# Queue/state
# ---------------------------------------------------------------------------

def _retail_to_dict(value: RetailEvidence) -> dict[str, Any]:
    return {
        "retailer": value.retailer,
        "relationship": value.relationship,
        "label": value.label,
        "product_id": value.product_id,
        "ean": value.ean,
        "product_url": value.product_url,
        "variant": value.variant,
    }


def _editorial_to_dict(value: AwardEditorialFacts) -> dict[str, Any]:
    return {
        "comparison_size": value.comparison_size,
        "category": value.category,
        "judge_count": value.judge_count,
        "method_flags": list(value.method_flags),
        "standout": value.standout,
        "quality_label": value.quality_label,
        "producer": value.producer,
        "producer_location": value.producer_location,
        "production_country": value.production_country,
        "headline_claim": value.headline_claim,
        "product_summary": value.product_summary,
        "tasting_notes": list(value.tasting_notes),
        "composition_details": list(value.composition_details),
        "nutrition_details": list(value.nutrition_details),
        "method_summary": value.method_summary,
        "identity_details": list(value.identity_details),
    }


def _candidate_to_dict(candidate: ProductAwardCandidate) -> dict[str, Any]:
    return {
        "source_kind": candidate.source_kind,
        "event_key": candidate.event_key,
        "source_url": candidate.source_url,
        "product_name": candidate.product_name,
        "result": candidate.result,
        "award_body": candidate.award_body,
        "result_year": candidate.result_year,
        "retail": _retail_to_dict(candidate.retail),
        "score": candidate.score,
        "source_price": candidate.source_price,
        "editorial": _editorial_to_dict(candidate.editorial),
    }


def _retail_from_dict(value: Any) -> RetailEvidence:
    if not isinstance(value, dict) or set(value) != {
        "retailer",
        "relationship",
        "label",
        "product_id",
        "ean",
        "product_url",
        "variant",
    }:
        raise ProductAwardError("invalid queued retail evidence", code="STATE")
    for key in ("retailer", "relationship"):
        if not isinstance(value[key], str) or not value[key]:
            raise ProductAwardError("invalid queued retail strings", code="STATE")
    for key in ("label", "product_id", "ean", "product_url", "variant"):
        if value[key] is not None and not isinstance(value[key], str):
            raise ProductAwardError("invalid queued retail optional field", code="STATE")
    return RetailEvidence(**value)


def _editorial_from_dict(value: Any) -> AwardEditorialFacts:
    if not isinstance(value, dict) or set(value) != {
        "comparison_size",
        "category",
        "judge_count",
        "method_flags",
        "standout",
        "quality_label",
        "producer",
        "producer_location",
        "production_country",
        "headline_claim",
        "product_summary",
        "tasting_notes",
        "composition_details",
        "nutrition_details",
        "method_summary",
        "identity_details",
    }:
        raise ProductAwardError("invalid queued editorial facts", code="STATE")
    for key in ("comparison_size", "judge_count"):
        if value[key] is not None and not isinstance(value[key], int):
            raise ProductAwardError("invalid queued editorial number", code="STATE")
    for key in (
        "category",
        "standout",
        "quality_label",
        "producer",
        "producer_location",
        "production_country",
        "headline_claim",
        "product_summary",
        "method_summary",
    ):
        if value[key] is not None and not isinstance(value[key], str):
            raise ProductAwardError("invalid queued editorial string", code="STATE")
    for key in (
        "method_flags",
        "tasting_notes",
        "composition_details",
        "nutrition_details",
        "identity_details",
    ):
        if (
            not isinstance(value[key], list)
            or len(value[key]) > 32
            or not all(isinstance(item, str) and item for item in value[key])
        ):
            raise ProductAwardError("invalid queued editorial list", code="STATE")
    return AwardEditorialFacts(
        comparison_size=value["comparison_size"],
        category=value["category"],
        judge_count=value["judge_count"],
        method_flags=tuple(value["method_flags"]),
        standout=value["standout"],
        quality_label=value["quality_label"],
        producer=value["producer"],
        producer_location=value["producer_location"],
        production_country=value["production_country"],
        headline_claim=value["headline_claim"],
        product_summary=value["product_summary"],
        tasting_notes=tuple(value["tasting_notes"]),
        composition_details=tuple(value["composition_details"]),
        nutrition_details=tuple(value["nutrition_details"]),
        method_summary=value["method_summary"],
        identity_details=tuple(value["identity_details"]),
    )


def _candidate_from_dict(value: Any) -> ProductAwardCandidate:
    if not isinstance(value, dict):
        raise ProductAwardError("invalid queued product-award candidate", code="STATE")
    expected = {
        "source_kind",
        "event_key",
        "source_url",
        "product_name",
        "result",
        "award_body",
        "result_year",
        "retail",
        "score",
        "source_price",
        "editorial",
    }
    if set(value) != expected:
        raise ProductAwardError("invalid queued product-award fields", code="STATE")
    for key in (
        "source_kind",
        "event_key",
        "source_url",
        "product_name",
        "result",
        "award_body",
    ):
        if not isinstance(value[key], str) or not value[key]:
            raise ProductAwardError("invalid queued product-award strings", code="STATE")
    if not isinstance(value["result_year"], int):
        raise ProductAwardError("invalid queued product-award year", code="STATE")
    for key in ("score", "source_price"):
        if value[key] is not None and not isinstance(value[key], str):
            raise ProductAwardError("invalid queued product-award optional field", code="STATE")
    return ProductAwardCandidate(
        source_kind=value["source_kind"],
        event_key=value["event_key"],
        source_url=value["source_url"],
        product_name=value["product_name"],
        result=value["result"],
        award_body=value["award_body"],
        result_year=value["result_year"],
        retail=_retail_from_dict(value["retail"]),
        score=value["score"],
        source_price=value["source_price"],
        editorial=_editorial_from_dict(value["editorial"]),
    )


def _queue_item_to_dict(item: ProductAwardQueueItem) -> dict[str, Any]:
    return {
        "event_id": item.event_id,
        "detected_at": item.detected_at,
        "candidate": _candidate_to_dict(item.candidate),
    }


def _queue_item_from_dict(value: Any) -> ProductAwardQueueItem:
    if not isinstance(value, dict) or set(value) != {
        "event_id",
        "detected_at",
        "candidate",
    }:
        raise ProductAwardError("invalid product-award queue item", code="STATE")
    event_id = value["event_id"]
    detected_at = value["detected_at"]
    if (
        not isinstance(event_id, str)
        or not re.fullmatch(r"[0-9a-f]{24}", event_id)
        or not isinstance(detected_at, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", detected_at)
    ):
        raise ProductAwardError("invalid product-award queue metadata", code="STATE")
    candidate = _candidate_from_dict(value["candidate"])
    if candidate.event_id != event_id:
        raise ProductAwardError("product-award queue identity mismatch", code="STATE")
    return ProductAwardQueueItem(event_id, detected_at, candidate)


def _merge_optional(existing: Any, incoming: Any, field: str) -> Any:
    if existing is not None and incoming is not None and existing != incoming:
        raise ProductAwardError(
            f"conflicting product-award {field}",
            code="STATE",
        )
    return incoming if incoming is not None else existing


def _merge_editorial_facts(
    existing: AwardEditorialFacts,
    incoming: AwardEditorialFacts,
) -> AwardEditorialFacts:
    return AwardEditorialFacts(
        comparison_size=_merge_optional(
            existing.comparison_size,
            incoming.comparison_size,
            "comparison size",
        ),
        category=_merge_optional(existing.category, incoming.category, "category"),
        judge_count=_merge_optional(
            existing.judge_count,
            incoming.judge_count,
            "judge count",
        ),
        method_flags=tuple(dict.fromkeys(
            (*existing.method_flags, *incoming.method_flags)
        )),
        standout=_merge_optional(existing.standout, incoming.standout, "standout"),
        quality_label=_merge_optional(
            existing.quality_label,
            incoming.quality_label,
            "quality label",
        ),
        producer=_merge_optional(existing.producer, incoming.producer, "producer"),
        producer_location=_merge_optional(
            existing.producer_location,
            incoming.producer_location,
            "producer location",
        ),
        production_country=_merge_optional(
            existing.production_country,
            incoming.production_country,
            "production country",
        ),
        headline_claim=_merge_optional(
            existing.headline_claim,
            incoming.headline_claim,
            "headline claim",
        ),
        product_summary=_merge_optional(
            existing.product_summary,
            incoming.product_summary,
            "product summary",
        ),
        tasting_notes=tuple(dict.fromkeys(
            (*existing.tasting_notes, *incoming.tasting_notes)
        )),
        composition_details=tuple(dict.fromkeys(
            (*existing.composition_details, *incoming.composition_details)
        )),
        nutrition_details=tuple(dict.fromkeys(
            (*existing.nutrition_details, *incoming.nutrition_details)
        )),
        method_summary=_merge_optional(
            existing.method_summary,
            incoming.method_summary,
            "method summary",
        ),
        identity_details=tuple(dict.fromkeys(
            (*existing.identity_details, *incoming.identity_details)
        )),
    )


def _merge_duplicate_candidate(
    existing: ProductAwardCandidate,
    incoming: ProductAwardCandidate,
) -> ProductAwardCandidate:
    if existing.event_id != incoming.event_id:
        raise ProductAwardError("cannot merge different award events", code="STATE")
    stable_existing = (
        existing.source_kind,
        existing.event_key,
        existing.source_url,
        existing.product_name,
        existing.result,
        existing.award_body,
        existing.result_year,
        existing.retail,
    )
    stable_incoming = (
        incoming.source_kind,
        incoming.event_key,
        incoming.source_url,
        incoming.product_name,
        incoming.result,
        incoming.award_body,
        incoming.result_year,
        incoming.retail,
    )
    if stable_existing != stable_incoming:
        raise ProductAwardError(
            "source adapter returned conflicting identity for one award event",
            code="STATE",
        )
    return ProductAwardCandidate(
        source_kind=existing.source_kind,
        event_key=existing.event_key,
        source_url=existing.source_url,
        product_name=existing.product_name,
        result=existing.result,
        award_body=existing.award_body,
        result_year=existing.result_year,
        retail=existing.retail,
        score=_merge_optional(existing.score, incoming.score, "score"),
        source_price=_merge_optional(
            existing.source_price,
            incoming.source_price,
            "source price",
        ),
        editorial=_merge_editorial_facts(existing.editorial, incoming.editorial),
    )


class ProductAwardState:
    VERSION = 6
    MAX_SEEN = 2_000
    MAX_QUEUE = 128
    MAX_HISTORY = 10_000

    def __init__(self, path: Path) -> None:
        self.path = path

    def _empty(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "initialized_sources": [],
            "seen_items": [],
            "queue": [],
            "published_events": [],
            "uncertain_events": [],
            "last_delivery_day": None,
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductAwardError(
                "product-award state is unreadable",
                code="STATE",
            ) from exc
        if not isinstance(value, dict) or value.get("version") != self.VERSION:
            raise ProductAwardError("invalid product-award state", code="STATE")
        expected = {
            "version",
            "initialized_sources",
            "seen_items",
            "queue",
            "published_events",
            "uncertain_events",
            "last_delivery_day",
        }
        if set(value) != expected:
            raise ProductAwardError("invalid product-award state fields", code="STATE")
        if (
            not isinstance(value["initialized_sources"], list)
            or len(value["initialized_sources"]) > 64
            or not all(
                isinstance(item, str) and item
                for item in value["initialized_sources"]
            )
            or len(value["initialized_sources"])
            != len(set(value["initialized_sources"]))
        ):
            raise ProductAwardError(
                "invalid product-award initialized sources",
                code="STATE",
            )
        if (
            not isinstance(value["seen_items"], list)
            or len(value["seen_items"]) > self.MAX_SEEN
            or not all(isinstance(item, str) for item in value["seen_items"])
        ):
            raise ProductAwardError("invalid product-award seen items", code="STATE")

        queue = value["queue"]
        if not isinstance(queue, list) or len(queue) > self.MAX_QUEUE:
            raise ProductAwardError("invalid product-award queue", code="STATE")
        parsed_queue = [_queue_item_from_dict(item) for item in queue]
        queue_ids = [item.event_id for item in parsed_queue]
        if len(queue_ids) != len(set(queue_ids)):
            raise ProductAwardError("duplicate event in product-award queue", code="STATE")

        for key in ("published_events", "uncertain_events"):
            items = value[key]
            if (
                not isinstance(items, list)
                or len(items) > self.MAX_HISTORY
                or not all(
                    isinstance(item, str) and re.fullmatch(r"[0-9a-f]{24}", item)
                    for item in items
                )
                or len(items) != len(set(items))
            ):
                raise ProductAwardError(f"invalid product-award {key}", code="STATE")
        published = set(value["published_events"])
        uncertain = set(value["uncertain_events"])
        if published & uncertain:
            raise ProductAwardError("overlapping product-award history", code="STATE")
        if (published | uncertain) & set(queue_ids):
            raise ProductAwardError("blocked event remains queued", code="STATE")

        last_day = value["last_delivery_day"]
        if last_day is not None and (
            not isinstance(last_day, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_day)
        ):
            raise ProductAwardError("invalid product-award delivery day", code="STATE")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
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

    def source_initialized(self, source_name: str) -> bool:
        return source_name in self._read()["initialized_sources"]

    def initialize_source(
        self,
        source_name: str,
        item_keys: Sequence[str],
    ) -> None:
        value = self._read()
        if source_name not in value["initialized_sources"]:
            value["initialized_sources"].append(source_name)
        items = list(value["seen_items"])
        items.extend(item_keys)
        value["seen_items"] = list(dict.fromkeys(items))[-self.MAX_SEEN :]
        self._write(value)

    def seen(self, item_key: str) -> bool:
        return item_key in self._read()["seen_items"]

    def mark_seen(self, item_key: str) -> None:
        value = self._read()
        items = [item for item in value["seen_items"] if item != item_key]
        items.append(item_key)
        value["seen_items"] = items[-self.MAX_SEEN :]
        self._write(value)

    def event_known(self, event_id: str) -> bool:
        value = self._read()
        if event_id in value["published_events"] or event_id in value["uncertain_events"]:
            return True
        return any(item.get("event_id") == event_id for item in value["queue"])

    def queue_size(self) -> int:
        return len(self._read()["queue"])

    def enqueue_candidates(
        self,
        candidates: Sequence[ProductAwardCandidate],
        detected_at: date,
    ) -> tuple[int, int, int]:
        value = self._read()
        blocked = set(value["published_events"]) | set(value["uncertain_events"])
        queue = [_queue_item_from_dict(item) for item in value["queue"]]
        positions = {item.event_id: index for index, item in enumerate(queue)}
        added = updated = ignored = 0

        for candidate in candidates:
            event_id = candidate.event_id
            if event_id in blocked:
                ignored += 1
                continue
            if event_id in positions:
                index = positions[event_id]
                merged = _merge_duplicate_candidate(queue[index].candidate, candidate)
                if merged != queue[index].candidate:
                    queue[index] = ProductAwardQueueItem(
                        event_id,
                        queue[index].detected_at,
                        merged,
                    )
                    updated += 1
                else:
                    ignored += 1
                continue
            if len(queue) >= self.MAX_QUEUE:
                raise ProductAwardError("product-award queue is full", code="QUEUE-FULL")
            positions[event_id] = len(queue)
            queue.append(ProductAwardQueueItem(
                event_id,
                detected_at.isoformat(),
                candidate,
            ))
            added += 1

        value["queue"] = [_queue_item_to_dict(item) for item in queue]
        if added or updated:
            self._write(value)
        return added, updated, ignored

    def queue_items(
        self,
        local_day: date,
        *,
        limit: int = MAX_PUBLICATION_CANDIDATES,
    ) -> tuple[ProductAwardQueueItem, ...]:
        if not isinstance(limit, int) or not 1 <= limit <= MAX_PUBLICATION_CANDIDATES:
            raise ProductAwardError("invalid product-award queue read limit", code="INVALID")
        value = self._read()
        if value["last_delivery_day"] == local_day.isoformat():
            return ()
        return tuple(
            _queue_item_from_dict(raw)
            for raw in value["queue"][:limit]
        )

    def next_queue_item(self, local_day: date) -> Optional[ProductAwardQueueItem]:
        items = self.queue_items(local_day, limit=1)
        return items[0] if items else None

    def begin_delivery(
        self,
        item: ProductAwardQueueItem,
        local_day: date,
    ) -> bool:
        value = self._read()
        day = local_day.isoformat()
        if value["last_delivery_day"] == day:
            return False
        queue = [_queue_item_from_dict(raw) for raw in value["queue"]]
        index = next(
            (index for index, queued in enumerate(queue) if queued.event_id == item.event_id),
            None,
        )
        if index is None:
            return False
        queue.pop(index)
        uncertain = list(value["uncertain_events"])
        if item.event_id not in uncertain:
            uncertain.append(item.event_id)
        if len(uncertain) > self.MAX_HISTORY:
            raise ProductAwardError("product-award uncertain history is full", code="STATE")
        value["queue"] = [_queue_item_to_dict(queued) for queued in queue]
        value["uncertain_events"] = uncertain
        value["last_delivery_day"] = day
        self._write(value)
        return True

    def restore_failed_delivery(self, item: ProductAwardQueueItem) -> None:
        value = self._read()
        if item.event_id in value["published_events"]:
            return
        value["uncertain_events"] = [
            event_id
            for event_id in value["uncertain_events"]
            if event_id != item.event_id
        ]
        if not any(raw.get("event_id") == item.event_id for raw in value["queue"]):
            if len(value["queue"]) >= self.MAX_QUEUE:
                raise ProductAwardError("product-award queue is full", code="QUEUE-FULL")
            value["queue"].insert(0, _queue_item_to_dict(item))
        self._write(value)

    def confirm_delivery(self, event_id: str, local_day: date) -> None:
        value = self._read()
        value["uncertain_events"] = [
            item for item in value["uncertain_events"] if item != event_id
        ]
        if event_id not in value["published_events"]:
            if len(value["published_events"]) >= self.MAX_HISTORY:
                raise ProductAwardError("product-award history is full", code="STATE")
            value["published_events"].append(event_id)
        value["last_delivery_day"] = local_day.isoformat()
        self._write(value)

    def published(self, event_id: str) -> bool:
        return event_id in self._read()["published_events"]

    def uncertain_events(self) -> tuple[str, ...]:
        return tuple(self._read()["uncertain_events"])

    def last_delivery_day(self) -> Optional[str]:
        value = self._read()["last_delivery_day"]
        return value if isinstance(value, str) else None

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProductAwardError(
                    "another product-award run is active",
                    code="LOCK",
                ) from exc
            yield


def _source_item_key(
    adapter: AwardSourceAdapter,
    item_id: str,
    year: int,
) -> str:
    return f"{adapter.name}:{year}:{item_id}"


def _merge_candidates(
    candidates: Sequence[ProductAwardCandidate],
) -> tuple[ProductAwardCandidate, ...]:
    merged: dict[str, ProductAwardCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        event_id = candidate.event_id
        if event_id in merged:
            merged[event_id] = _merge_duplicate_candidate(merged[event_id], candidate)
        else:
            merged[event_id] = candidate
            order.append(event_id)
    return tuple(merged[event_id] for event_id in order)


def discover_product_awards(
    now: datetime,
    state: ProductAwardState,
    *,
    preview: bool = False,
) -> tuple[ProductAwardCandidate, ...]:
    discovered: list[ProductAwardCandidate] = []
    for adapter in SOURCE_ADAPTERS:
        try:
            item_ids = adapter.discover(now.year)
        except ProductAwardError as exc:
            LOGGER.warning(
                "Product-award source %s unavailable [%s]",
                adapter.name,
                exc.diagnostic_code,
            )
            continue

        if not preview and not state.source_initialized(adapter.name):
            item_keys = [
                _source_item_key(adapter, item_id, now.year)
                for item_id in item_ids
            ]
            state.initialize_source(adapter.name, item_keys)
            LOGGER.info(
                "Product-award source %s baselined: %d items",
                adapter.name,
                len(item_keys),
            )
            continue

        checked = 0
        for item_id in item_ids:
            item_key = _source_item_key(adapter, item_id, now.year)
            if not preview and state.seen(item_key):
                continue
            if checked >= 8:
                break
            checked += 1
            try:
                item = adapter.load(item_id, now.year)
            except ProductAwardError as exc:
                LOGGER.warning(
                    "Product-award source item %s skipped for retry [%s]",
                    item_key,
                    exc.diagnostic_code,
                )
                continue

            discovered.extend(item.candidates)
            if not preview:
                state.enqueue_candidates(item.candidates, now.date())
                state.mark_seen(item_key)

    return _merge_candidates(discovered)


def scan_next_product_award(
    now: datetime,
    state: ProductAwardState,
    *,
    preview: bool = False,
) -> Optional[ProductAwardPublication]:
    if preview:
        candidates = discover_product_awards(
            now,
            state,
            preview=True,
        )
        for candidate in candidates:
            publication = build_current_publication(candidate)
            if publication is not None:
                return publication
        return None

    for item in state.queue_items(now.date()):
        publication = build_current_publication(item.candidate)
        if publication is not None:
            return publication
    return None
