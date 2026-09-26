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
REQUEST_TIMEOUT_SECONDS = 20
HTML_LIMIT_BYTES = 900_000
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
class AwardEditorialFacts:
    comparison_size: Optional[int] = None
    category: Optional[str] = None
    judge_count: Optional[int] = None
    method_flags: tuple[str, ...] = ()
    standout: Optional[str] = None
    quality_label: Optional[str] = None
    producer: Optional[str] = None
    identity_details: tuple[str, ...] = ()


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


def load_ocu_item(url: str, year: int) -> AwardSourceItem:
    document = _fetch_page(
        url,
        frozenset({"www.ocu.org", "ocu.org"}),
    )
    return AwardSourceItem(parse_ocu_awards(document, year))


# Add future validated adapters here. A new adapter only needs a stable list of
# item IDs and a loader that returns verified ProductAwardCandidate objects.
SOURCE_ADAPTERS: tuple[AwardSourceAdapter, ...] = (
    AwardSourceAdapter("ocu", discover_ocu_documents, load_ocu_item),
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


def build_publication(
    candidate: ProductAwardCandidate,
    *,
    current_price: Optional[str] = None,
) -> ProductAwardPublication:
    product = _display_product(candidate.product_name)
    body_parts: list[str] = []

    if candidate.source_kind == "ocu":
        if candidate.result == "Mejor del Análisis":
            headline = f"{product} — лучший в тесте OCU"
            if candidate.sample_size is not None:
                body_parts.append(
                    f"OCU сравнила {candidate.sample_size} продуктов. "
                    f"{product} из {candidate.retailer} получил статус "
                    "Mejor del Análisis — лучший результат сравнительного теста."
                )
            else:
                body_parts.append(
                    f"{product} из {candidate.retailer} получил статус "
                    "Mejor del Análisis — лучший результат сравнительного теста OCU."
                )
        elif candidate.result == "Compra Maestra":
            headline = f"{product} — Compra Maestra в тесте OCU"
            if candidate.sample_size is not None:
                body_parts.append(
                    f"OCU сравнила {candidate.sample_size} продуктов. "
                    f"{product} из {candidate.retailer} получил отметку "
                    "Compra Maestra — за удачное соотношение качества и цены."
                )
            else:
                body_parts.append(
                    f"{product} из {candidate.retailer} получил отметку "
                    "Compra Maestra — за удачное соотношение качества и цены."
                )
        else:
            headline = f"{product} — результат OCU"
            body_parts.append(
                f"{product} из {candidate.retailer} получил результат "
                f"{candidate.result} в исследовании OCU."
            )

        method_sentence = _ocu_method_sentence(candidate.editorial)
        if method_sentence is not None:
            body_parts.append(method_sentence)
        if candidate.editorial.standout == "best_professional_tasting":
            body_parts.append(
                "Особенно хорошо продукт показал себя на профессиональной "
                "дегустации: OCU назвала его лучшим по этому этапу."
            )
        if candidate.editorial.quality_label is not None:
            body_parts.append(
                f"По своей шкале пищевого состава OCU также отнесла продукт "
                f"к категории {candidate.editorial.quality_label}."
            )
    else:
        headline = f"{product} — {candidate.result} на {candidate.award_body}"
        body_parts.append(
            f"{product}, {_retail_phrase(candidate)}, получил "
            f"{candidate.result} на {candidate.award_body}."
        )

    details: list[str] = []
    if candidate.score is not None:
        details.append(f"Итоговая оценка — {candidate.score}.")
    if current_price is not None:
        details.append(
            f"Сейчас в {candidate.retailer} указана цена {current_price}."
        )
    elif candidate.source_price is not None:
        details.append(
            f"В исследовании указана цена {candidate.source_price}."
        )
    if details:
        body_parts.append(" ".join(details))

    source_url = html.escape(candidate.source_url, quote=True)
    link_label = html.escape(_source_link_label(candidate))
    message = with_footer(
        "🏆 <b>"
        + html.escape(headline)
        + "</b>\n\n"
        + "\n\n".join(html.escape(part) for part in body_parts)
        + f'\n\n🔗 <a href="{source_url}">{link_label}</a>'
    )
    if len(message) > 4096:
        raise ProductAwardError(
            "product-award message exceeds Telegram limit",
            code="MESSAGE-LENGTH",
        )
    return ProductAwardPublication(candidate=candidate, message=message)


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
        "identity_details",
    }:
        raise ProductAwardError("invalid queued editorial facts", code="STATE")
    for key in ("comparison_size", "judge_count"):
        if value[key] is not None and not isinstance(value[key], int):
            raise ProductAwardError("invalid queued editorial number", code="STATE")
    for key in ("category", "standout", "quality_label", "producer"):
        if value[key] is not None and not isinstance(value[key], str):
            raise ProductAwardError("invalid queued editorial string", code="STATE")
    for key in ("method_flags", "identity_details"):
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
    VERSION = 5
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

    def next_queue_item(self, local_day: date) -> Optional[ProductAwardQueueItem]:
        value = self._read()
        if value["last_delivery_day"] == local_day.isoformat() or not value["queue"]:
            return None
        return _queue_item_from_dict(value["queue"][0])

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
        if not candidates:
            return None
        return build_publication(candidates[0])

    item = state.next_queue_item(now.date())
    if item is None:
        return None
    return build_publication(item.candidate)
