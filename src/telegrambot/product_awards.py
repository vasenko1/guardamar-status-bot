"""Reviewed supermarket product-award publications.

The runtime keeps a small reviewed catalogue. A due run validates one award
fact, refreshes one exact retailer object, builds one rich Telegram article,
publishes at most one event, and exits.
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
from .branding import FOOTER

LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15
HTML_LIMIT_BYTES = 768_000
JSON_LIMIT_BYTES = 500_000
IMAGE_LIMIT_BYTES = 700_000
USER_AGENT = "GuardamarMorningDigest/0.14"
RETAIL_NAVIGATION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}
COOLDOWN_DAYS = 3
STATE_SCHEMA_VERSION = 1
MAX_HISTORY = 128
CONSUM_MEDIA_HOSTS = frozenset({"cdn-consum.aktiosdigitalservices.com"})
MASYMAS_MEDIA_HOSTS = frozenset({"cdn-fornes.aktiosdigitalservices.com"})
ALDI_MEDIA_HOSTS = frozenset({"s7g10.scene7.com"})


class ProductAwardError(RuntimeError):
    """Fail-closed product-award error with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


@dataclass(frozen=True)
class RetailOffer:
    retailer: str
    price: str
    image_url: Optional[str]
    product_name: str
    regular_price: Optional[str] = None


@dataclass(frozen=True)
class ReviewedImageSource:
    name: str
    page_url: str
    page_hosts: frozenset[str]
    image_hosts: frozenset[str]
    page_markers: tuple[str, ...]
    image_alt_markers: tuple[str, ...] = ()
    use_navigation_headers: bool = False


@dataclass(frozen=True)
class ResolvedProductImage:
    url: str
    hosts: frozenset[str]
    source_name: str
    referer: Optional[str] = None


@dataclass(frozen=True)
class ReviewedCandidate:
    category_key: str
    selection_key: str
    event_id: str
    source_name: str
    source_kind: str
    source_url: str
    source_hosts: frozenset[str]
    source_markers: tuple[str, ...]
    retailer: str
    retailer_kind: str
    retailer_url: str
    retailer_hosts: frozenset[str]
    retailer_markers: tuple[str, ...]
    product_name: str
    award_year: int
    source_category: str
    award_scope: str
    award_result: str
    product_id: int
    expected_ean: Optional[str]
    sample_size: Optional[int] = None
    rank: int = 1
    retailer_title: Optional[str] = None
    package_label: Optional[str] = None
    country_label: Optional[str] = None
    producer_label: Optional[str] = None
    headline_award: Optional[str] = None
    highlight: Optional[str] = None
    image_sources: tuple[ReviewedImageSource, ...] = ()


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


class _ProductImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_images: list[str] = []
        self.images: list[tuple[str, str, int]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        if tag.casefold() == "meta":
            key = str(
                values.get("property") or values.get("name") or ""
            ).casefold()
            if key in {
                "og:image",
                "og:image:url",
                "twitter:image",
                "twitter:image:src",
            }:
                content = values.get("content")
                if isinstance(content, str) and content.strip():
                    self.meta_images.append(content.strip())
            return
        if tag.casefold() != "img":
            return
        alt = str(values.get("alt") or "").strip()
        image_values: list[tuple[str, int]] = []
        for key, source_priority in (
            ("src", 0),
            ("data-src", 1),
            ("data-lazy-src", 1),
        ):
            value = values.get(key)
            if isinstance(value, str) and value.strip():
                image_values.append((value.strip(), source_priority))
        srcset = values.get("srcset")
        if isinstance(srcset, str) and srcset.strip():
            for item in srcset.split(","):
                raw = item.strip().split(" ", 1)[0]
                if raw:
                    image_values.append((raw, 1))
        for raw, source_priority in image_values:
            self.images.append((alt, raw, source_priority))


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


def _fetch_html(
    url: str,
    hosts: frozenset[str],
    *,
    headers: Optional[dict[str, str]] = None,
) -> str:
    request_headers = headers or {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
        "User-Agent": USER_AGENT,
    }
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed(hosts),
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers=request_headers,
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            "product-award HTML request failed",
            code=exc.code,
        ) from exc
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProductAwardError(
            "product-award source is not UTF-8",
            code="ENCODING",
        ) from exc


def _fetch_json(url: str, hosts: frozenset[str]) -> dict:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed(hosts),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=JSON_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "Accept-Language": "es-ES,es;q=0.9",
                "User-Agent": USER_AGENT,
            },
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            "product-award JSON request failed",
            code=exc.code,
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductAwardError(
            "product-award JSON is invalid",
            code="PARSER",
        ) from exc
    if not isinstance(value, dict):
        raise ProductAwardError(
            "product-award JSON structure is invalid",
            code="PARSER",
        )
    return value


def _visible_text(source: str) -> str:
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
        raise ProductAwardError(
            "product-award page is empty",
            code="PARSER",
        )
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
    folded_add = _fold("Añadir")

    candidates: list[tuple[int, str]] = []
    start = 0
    while True:
        index = folded_text.find(folded_title, start)
        if index < 0:
            break
        window = folded_text[index:index + 1500]
        add_index = window.find(folded_add)
        if add_index >= 0:
            candidates.append((add_index, window[:add_index]))
        start = index + len(folded_title)

    if not candidates:
        return None

    unavailable_markers = (
        "agotado",
        "no disponible",
        "sin stock",
        "temporalmente agotado",
    )
    for _, product_card in sorted(candidates, key=lambda item: item[0]):
        if any(_fold(value) in product_card for value in unavailable_markers):
            continue
        match = re.search(r"(?<!\d)(\d{1,3}[.,]\d{2})\s*€", product_card)
        if match is None:
            continue
        raw_price = match.group(1).replace(",", ".")
        if float(raw_price) <= 0:
            continue
        return match.group(1).replace(".", ",") + " €"
    return None


def _walk_json_dicts(value) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_dicts(child)


def _decimal_price(value) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"{number:.2f}".replace(".", ",") + " €"


def _remote_image(
    value: object,
    hosts: Optional[frozenset[str]] = None,
) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname.casefold() if parsed.hostname else None
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or (hosts is not None and hostname not in hosts)
    ):
        return None
    return value


def _image_resolution_score(url: str) -> int:
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    except ValueError:
        return 0
    score = 0
    for key in ("width", "w", "sw", "imwidth", "height", "h", "sh"):
        for value in query.get(key, ()):
            if value.isdigit():
                score = max(score, int(value))
    return score


def _resolve_reviewed_image_source(
    source: ReviewedImageSource,
) -> ResolvedProductImage:
    html_source = _fetch_html(
        source.page_url,
        source.page_hosts,
        headers=(
            RETAIL_NAVIGATION_HEADERS
            if source.use_navigation_headers
            else None
        ),
    )
    visible = _visible_text(html_source)
    _require_markers(
        visible,
        source.page_markers,
        code="MEDIA-DRIFT",
    )

    parser = _ProductImageParser()
    try:
        parser.feed(html_source)
    except Exception as exc:
        raise ProductAwardError(
            "reviewed product image page could not be parsed",
            code="MEDIA-PARSER",
        ) from exc

    def resolve(raw_url: str) -> Optional[str]:
        absolute = urllib.parse.urljoin(source.page_url, html.unescape(raw_url))
        return _remote_image(absolute, source.image_hosts)

    if source.image_alt_markers:
        wanted = tuple(_fold(value) for value in source.image_alt_markers)
        matches: list[tuple[str, int]] = []
        for alt, raw_url, source_priority in parser.images:
            folded_alt = _fold(alt)
            if not all(marker in folded_alt for marker in wanted):
                continue
            image_url = resolve(raw_url)
            if image_url is not None:
                matches.append((image_url, source_priority))
        if matches:
            image_url, _ = max(
                matches,
                key=lambda item: (
                    _image_resolution_score(item[0]),
                    item[1],
                ),
            )
            return ResolvedProductImage(
                url=image_url,
                hosts=source.image_hosts,
                source_name=source.name,
                referer=(
                    source.page_url
                    if source.use_navigation_headers
                    else None
                ),
            )
    else:
        for raw_url in parser.meta_images:
            image_url = resolve(raw_url)
            if image_url is not None:
                return ResolvedProductImage(
                    url=image_url,
                    hosts=source.image_hosts,
                    source_name=source.name,
                    referer=(
                        source.page_url
                        if source.use_navigation_headers
                        else None
                    ),
                )

        for _, raw_url, _ in parser.images:
            image_url = resolve(raw_url)
            if image_url is not None:
                return ResolvedProductImage(
                    url=image_url,
                    hosts=source.image_hosts,
                    source_name=source.name,
                    referer=(
                        source.page_url
                        if source.use_navigation_headers
                        else None
                    ),
                )

    raise ProductAwardError(
        "reviewed exact product image missing",
        code="MEDIA-DRIFT",
    )


def _retailer_image(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
) -> Optional[ResolvedProductImage]:
    if offer.image_url is None:
        return None
    media_hosts = {
        "consum": CONSUM_MEDIA_HOSTS,
        "masymas": MASYMAS_MEDIA_HOSTS,
        "aldi": ALDI_MEDIA_HOSTS,
    }.get(candidate.retailer_kind, frozenset())
    hosts = candidate.retailer_hosts | media_hosts
    image_url = _remote_image(offer.image_url, hosts)
    if image_url is None:
        return None
    return ResolvedProductImage(
        url=image_url,
        hosts=hosts,
        source_name=f"{candidate.retailer} exact product",
    )


def iter_product_images(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
) -> Iterator[ResolvedProductImage]:
    seen: set[str] = set()
    for source in candidate.image_sources:
        try:
            image = _resolve_reviewed_image_source(source)
        except ProductAwardError as exc:
            LOGGER.warning(
                "Product-award image source %s unavailable for %s [%s]",
                source.name,
                candidate.event_id,
                exc.diagnostic_code,
            )
            continue
        if image.url in seen:
            continue
        seen.add(image.url)
        yield image

    retailer_image = _retailer_image(candidate, offer)
    if retailer_image is not None and retailer_image.url not in seen:
        yield retailer_image


def first_product_image(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
) -> Optional[ResolvedProductImage]:
    return next(iter_product_images(candidate, offer), None)


def fetch_product_image(
    image: ResolvedProductImage,
) -> tuple[bytes, str]:
    headers = {
        "Accept": "image/webp,image/png,image/jpeg,*/*;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if image.referer is not None:
        headers = {
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            "User-Agent": RETAIL_NAVIGATION_HEADERS["User-Agent"],
            "Referer": image.referer,
        }

    try:
        payload, _, content_type = fetch_bounded(
            image.url,
            is_allowed_url=_allowed(image.hosts),
            accepted_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
            limit_bytes=IMAGE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers=headers,
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            "product image could not be downloaded",
            code=f"MEDIA-{exc.code}",
        ) from exc
    return payload, content_type


def _image_exists(url: str, hosts: frozenset[str]) -> bool:
    try:
        fetch_bounded(
            url,
            is_allowed_url=_allowed(hosts),
            accepted_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
            limit_bytes=IMAGE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                "User-Agent": USER_AGENT,
            },
        )
    except BoundedFetchError:
        return False
    return True


def _upgrade_masymas_image(url: str, hosts: frozenset[str]) -> str:
    if "/135x135/" not in url:
        return url
    candidate = url.replace("/135x135/", "/300x300/")
    return candidate if _image_exists(candidate, hosts) else url


def _price_data(payload: dict) -> tuple[str, Optional[str]]:
    price_data = payload.get("priceData")
    if not isinstance(price_data, dict):
        raise ProductAwardError(
            "retailer priceData missing",
            code="RETAIL-DRIFT",
        )
    prices = price_data.get("prices")
    if not isinstance(prices, list):
        raise ProductAwardError(
            "retailer prices missing",
            code="RETAIL-DRIFT",
        )

    regular = None
    offer = None
    for item in prices:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        price = _decimal_price(value.get("centAmount"))
        if price is None:
            continue
        if item.get("id") == "PRICE":
            regular = price
        elif item.get("id") == "OFFER_PRICE":
            offer = price

    if offer is not None:
        return offer, regular
    if regular is not None:
        return regular, None
    raise ProductAwardError(
        "retailer current price missing",
        code="RETAIL-DRIFT",
    )


def _first_product_image(
    payload: dict,
    hosts: frozenset[str],
    *,
    prefer_media: bool = False,
) -> Optional[str]:
    def media_image() -> Optional[str]:
        media = payload.get("media")
        if not isinstance(media, list):
            return None
        for item in media:
            if not isinstance(item, dict):
                continue
            for key in ("url", "imageURL"):
                image = _remote_image(item.get(key), hosts)
                if image is not None:
                    return image
        return None

    def product_data_image() -> Optional[str]:
        product_data = payload.get("productData")
        if not isinstance(product_data, dict):
            return None
        return _remote_image(product_data.get("imageURL"), hosts)

    if prefer_media:
        return media_image() or product_data_image()
    return product_data_image() or media_image()


def _tol_offer(candidate: ReviewedCandidate) -> RetailOffer:
    payload = _fetch_json(candidate.retailer_url, candidate.retailer_hosts)
    actual_ean = str(payload.get("ean") or "")
    if candidate.expected_ean is None or actual_ean != candidate.expected_ean:
        raise ProductAwardError(
            "retailer EAN changed",
            code="RETAIL-DRIFT",
        )

    product_data = payload.get("productData")
    product_name = ""
    if isinstance(product_data, dict) and isinstance(product_data.get("name"), str):
        product_name = product_data["name"].strip()
    if not product_name and isinstance(payload.get("name"), str):
        product_name = payload["name"].strip()
    if not product_name:
        raise ProductAwardError(
            "retailer product name missing",
            code="RETAIL-DRIFT",
        )

    if candidate.retailer_markers:
        _require_markers(
            product_name,
            candidate.retailer_markers,
            code="RETAIL-DRIFT",
        )

    price, regular_price = _price_data(payload)
    media_hosts = {
        "consum": CONSUM_MEDIA_HOSTS,
        "masymas": MASYMAS_MEDIA_HOSTS,
    }.get(candidate.retailer_kind, frozenset())
    image_url = _first_product_image(
        payload,
        media_hosts,
        prefer_media=(candidate.retailer_kind == "consum"),
    )
    if candidate.retailer_kind == "masymas" and image_url is not None:
        image_url = _upgrade_masymas_image(image_url, media_hosts)

    return RetailOffer(
        retailer=candidate.retailer,
        price=price,
        regular_price=regular_price,
        image_url=image_url,
        product_name=product_name,
    )


def _html_retail_offer(candidate: ReviewedCandidate) -> RetailOffer:
    if candidate.retailer_title is None:
        raise ProductAwardError(
            "retailer exact product title is not configured",
            code="CONFIG",
        )

    source = _fetch_html(
        candidate.retailer_url,
        candidate.retailer_hosts,
        headers=RETAIL_NAVIGATION_HEADERS,
    )
    text = _visible_text(source)
    _require_markers(
        text,
        candidate.retailer_markers,
        code="RETAIL-DRIFT",
    )
    price = _price_after_title(text, candidate.retailer_title)
    if price is None:
        raise ProductAwardError(
            "retailer exact product price unavailable",
            code="RETAIL-UNAVAILABLE",
        )
    return RetailOffer(
        retailer=candidate.retailer,
        price=price,
        image_url=None,
        product_name=candidate.retailer_title,
    )


def _aldi_next_data(source: str):
    match = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise ProductAwardError(
            "ALDI Next.js data missing",
            code="RETAIL-DRIFT",
        )
    try:
        next_data = json.loads(match.group(1))
        page_props = next_data["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProductAwardError(
            "ALDI page payload invalid",
            code="RETAIL-DRIFT",
        ) from exc
    if not isinstance(page_props, dict):
        raise ProductAwardError(
            "ALDI page payload changed",
            code="RETAIL-DRIFT",
        )
    if page_props.get("hasError") is True:
        raise ProductAwardError(
            "ALDI exact product page reports an error",
            code="RETAIL-PAGE-ERROR",
        )

    api_data = page_props.get("apiData")
    if isinstance(api_data, str):
        try:
            payload = json.loads(api_data)
        except json.JSONDecodeError as exc:
            raise ProductAwardError(
                "ALDI product payload invalid",
                code="RETAIL-DRIFT",
            ) from exc
    elif isinstance(api_data, (dict, list)):
        payload = api_data
    else:
        raise ProductAwardError(
            "ALDI product payload missing",
            code="RETAIL-DRIFT",
        )
    if not isinstance(payload, (dict, list)):
        raise ProductAwardError(
            "ALDI product payload changed",
            code="RETAIL-DRIFT",
        )
    return payload


def _aldi_offer(candidate: ReviewedCandidate, source: str) -> RetailOffer:
    payload = _aldi_next_data(source)
    matches: list[dict] = []
    for item in _walk_json_dicts(payload):
        if str(item.get("objectID") or "") != str(candidate.product_id):
            continue
        identity_text = json.dumps(item, ensure_ascii=False, sort_keys=True)
        try:
            _require_markers(
                identity_text,
                candidate.retailer_markers,
                code="RETAIL-DRIFT",
            )
        except ProductAwardError:
            continue
        matches.append(item)

    if not matches:
        raise ProductAwardError(
            "ALDI exact product missing",
            code="RETAIL-DRIFT",
        )

    signatures = {
        (
            item.get("isAvailable"),
            item.get("isComingSoon"),
            item.get("isRecall"),
            json.dumps(item.get("currentPrice"), sort_keys=True),
        )
        for item in matches
    }
    if len(signatures) != 1:
        raise ProductAwardError(
            "ALDI product data is ambiguous",
            code="RETAIL-DRIFT",
        )

    product = matches[0]
    if product.get("isAvailable") is not True:
        raise ProductAwardError(
            "ALDI exact product unavailable",
            code="RETAIL-UNAVAILABLE",
        )
    if product.get("isComingSoon") is True or product.get("isRecall") is True:
        raise ProductAwardError(
            "ALDI exact product unavailable",
            code="RETAIL-UNAVAILABLE",
        )

    price_data = product.get("currentPrice")
    if not isinstance(price_data, dict):
        raise ProductAwardError(
            "ALDI current price missing",
            code="RETAIL-DRIFT",
        )
    price = _decimal_price(price_data.get("priceValue"))
    if price is None:
        raise ProductAwardError(
            "ALDI current price invalid",
            code="RETAIL-DRIFT",
        )

    image_url = None
    assets = product.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("type") != "primary":
                continue
            image_url = _remote_image(asset.get("url"), ALDI_MEDIA_HOSTS)
            if image_url is not None:
                break

    name = product.get("name")
    brand = product.get("brandName")
    product_name = " ".join(
        part.strip()
        for part in (brand, name)
        if isinstance(part, str) and part.strip()
    )
    if not product_name:
        product_name = candidate.product_name

    return RetailOffer(
        retailer=candidate.retailer,
        price=price,
        image_url=image_url,
        product_name=product_name,
    )


def _verify_award(candidate: ReviewedCandidate) -> None:
    text = _visible_text(_fetch_html(candidate.source_url, candidate.source_hosts))
    _require_markers(text, candidate.source_markers, code="AWARD-DRIFT")


def _refresh_offer(candidate: ReviewedCandidate) -> RetailOffer:
    if candidate.retailer_kind in {"consum", "masymas"}:
        return _tol_offer(candidate)
    if candidate.retailer_kind == "aldi":
        source = _fetch_html(candidate.retailer_url, candidate.retailer_hosts)
        return _aldi_offer(candidate, source)
    if candidate.retailer_kind in {"carrefour", "dia"}:
        return _html_retail_offer(candidate)
    raise ProductAwardError(
        "unknown retailer adapter",
        code="CONFIG",
    )


def _ru_product_count(value: int) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        noun = "продуктов"
    else:
        last = value % 10
        if last == 1:
            noun = "продукт"
        elif 2 <= last <= 4:
            noun = "продукта"
        else:
            noun = "продуктов"
    return f"{value} {noun}"


def _price_sentence(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
    *,
    range_member: bool,
) -> str:
    retailer = html.escape(offer.retailer)
    current = html.escape(offer.price)
    regular = (
        html.escape(offer.regular_price)
        if offer.regular_price is not None
        else None
    )

    if candidate.retailer_kind == "carrefour":
        subject = (
            "Для этого варианта на сайте Carrefour"
            if range_member
            else "На сайте Carrefour"
        )
        if regular is not None and regular != current:
            return (
                f"{subject} сейчас указана цена <b>{current}</b> "
                f"вместо обычных {regular}."
            )
        return f"{subject} сейчас указана цена <b>{current}</b>."

    subject = "Этот вариант" if range_member else "Сейчас этот товар"
    if regular is not None and regular != current:
        return (
            f"{subject} в {retailer} стоит <b>{current}</b> "
            f"вместо обычных {regular}."
        )
    return f"{subject} в {retailer} стоит <b>{current}</b>."


_METHODOLOGIES: dict[
    tuple[str, Optional[str]],
    tuple[str, tuple[str, ...]],
] = {
    ("world_beer_awards", None): (
        "Как проходит World Beer Awards",
        (
            "Пиво оценивают вслепую международные эксперты. В части Taste "
            "судьи сосредоточены на вкусе, качестве и характере пива, а "
            "оформление и дизайн оцениваются конкурсом отдельно.",
            "Конкурс проходит в три этапа. Сначала пиво сравнивают с другими "
            "образцами того же стиля из той же страны: судьи присуждают "
            "медали и выбирают Country Winner. Затем победителей стран снова "
            "дегустируют вслепую и сравнивают с пивом того же стиля со всего "
            "мира. Победители стилей проходят в финальную дегустацию внутри "
            "более широкой категории.",
        ),
    ),
    ("ocu", "sparkling_cava"): (
        "Как проходит сравнительный тест OCU",
        (
            "Часть каждого образца отправляют в специализированную "
            "независимую лабораторию. Там проверяют содержание алкоголя и "
            "сахара, общую и летучую кислотность, а также консерванты и другие "
            "добавки, включая сульфиты, сорбиновую и аскорбиновую кислоты.",
            "Другую часть образцов анонимно дегустирует группа опытных "
            "винных экспертов. Вина сравнивают с образцами похожего типа и "
            "оценивают по дегустационным листам на основе валидированной "
            "методики OIV; для этого исследования дегустация является "
            "главным критерием качества.",
        ),
    ),
    ("ocu", "gazpacho"): (
        "Как проходит сравнительный тест OCU",
        (
            "OCU покупает охлаждённые gazpacho и проверяет все образцы по "
            "одинаковой методике. 10% итоговой оценки приходится на "
            "маркировку, 40% — на оценку пищевой ценности по информации "
            "на этикетке, а 50% — на профессиональную дегустацию.",
            "Перед дегустацией эксперты оценивают запах, цвет и текстуру, а "
            "затем вкус и ощущения во рту. Отдельно проверяют список "
            "ингредиентов и обращают внимание на добавки и технологические "
            "компоненты.",
        ),
    ),
    ("ocu", "aove"): (
        "Как проходит сравнительный тест OCU",
        (
            "Масла исследуют в независимой лаборатории: проверяют их "
            "подлинность, чтобы исключить примесь других масел, измеряют "
            "кислотность и показатели, по которым видно качество плодов, "
            "окисление и состояние продукта при хранении.",
            "Кроме лабораторных анализов проводится профессиональная "
            "сенсорная оценка. Дегустаторы проверяют аромат и вкус и ищут "
            "дефекты: именно эта дегустация нужна, чтобы подтвердить, что "
            "масло действительно соответствует категории virgen extra.",
        ),
    ),
    ("ocu", "coffee_capsules"): (
        "Как проходит сравнительный тест OCU",
        (
            "Сначала проверяют маркировку, а в лаборатории измеряют "
            "влажность, количество растворимых веществ и кофеина. Также "
            "ищут нежелательные загрязнители, в том числе акриламид и "
            "охратоксин A.",
            "Затем все образцы готовят на одной и той же кофемашине в "
            "одинаковых условиях и передают экспертной панели на дегустацию. "
            "Эксперты оценивают "
            "равномерность цвета, плотность и устойчивость пенки, аромат, "
            "горечь, терпкость, тело кофе и наличие вкусовых дефектов.",
        ),
    ),
    ("mapa", "spirits_anis"): (
        "Как выбирают победителя премии MAPA",
        (
            "Отбор сочетает профессиональную дегустацию и оценку документов "
            "производителя. Для сенсорной части формируют панель как минимум "
            "из пяти опытных дегустаторов под руководством руководителя "
            "панели.",
            "Каждый образец оценивают по цвету и внешнему виду, аромату, "
            "вкусу и общему впечатлению — с разным весом этих критериев. "
            "Пять образцов с лучшими результатами проходят в финальную "
            "дегустацию. После неё жюри отдельно оценивает деятельность "
            "компаний по поданным документам; победителя определяют по "
            "совокупности обеих оценок.",
        ),
    ),
}


def _methodology(candidate: ReviewedCandidate) -> str:
    reviewed = _METHODOLOGIES.get(
        (candidate.source_kind, candidate.category_key)
    )
    if reviewed is None:
        reviewed = _METHODOLOGIES.get((candidate.source_kind, None))
    if reviewed is None:
        raise ProductAwardError(
            "unknown award methodology",
            code="CONFIG",
        )
    title, paragraphs = reviewed
    body = "<br><br>".join(paragraphs)
    return (
        "<blockquote expandable>"
        f"🔬 <b>{title}</b><br><br>"
        f"{body}"
        "</blockquote>"
    )


def build_message(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
    *,
    image_src: Optional[str] = None,
    include_image: bool = True,
) -> str:
    name = html.escape(candidate.product_name)
    category = html.escape(candidate.source_category)
    retailer = html.escape(candidate.retailer)
    default_headline_awards = {
        "world_beer_awards": f"World Beer Awards {candidate.award_year}",
        "ocu": f"OCU {candidate.award_year}",
        "mapa": f"Premio Alimentos de España {candidate.award_year}",
    }
    headline_award = html.escape(
        candidate.headline_award
        or default_headline_awards.get(candidate.source_kind, candidate.source_name)
    )
    title = f"{name} — {headline_award} · {retailer}"

    if candidate.source_kind == "world_beer_awards":
        first = (
            f"На World Beer Awards {candidate.award_year} <b>{name}</b> "
            f"получило золото и стало победителем Испании в стиле {category}."
        )
    elif candidate.source_kind == "ocu":
        result = html.escape(candidate.award_result)
        sample = (
            _ru_product_count(candidate.sample_size)
            if candidate.sample_size is not None
            else "продукты"
        )
        first = (
            "<b>OCU — испанская Организация потребителей и пользователей</b> "
            f"сравнила {sample} в категории {category}. "
            f"Результат <b>{name}</b> — <b>{result}</b>."
        )
    elif candidate.source_kind == "mapa":
        first = (
            "Министерство сельского хозяйства Испании назвало "
            f"<b>{name}</b> победителем в категории {category}."
        )
    else:
        raise ProductAwardError(
            "unknown award renderer",
            code="CONFIG",
        )

    facts = []
    if candidate.package_label:
        facts.append(f"📦 {html.escape(candidate.package_label)}")
    if candidate.country_label:
        facts.append(f"🌍 {html.escape(candidate.country_label)}")
    if candidate.producer_label:
        facts.append(f"🏭 {html.escape(candidate.producer_label)}")

    parts = []
    image_value = (
        image_src if image_src is not None else offer.image_url
    ) if include_image else None
    if image_value:
        parts.append(f'<img src="{html.escape(image_value, quote=True)}"/>')
    parts.extend((
        f"<p>🏆 <b>{title}</b></p>",
        f"<p>{first}</p>",
    ))
    if candidate.highlight:
        parts.append(
            "<p>⭐ <b>Почему выделился:</b> "
            f"{html.escape(candidate.highlight)}</p>"
        )
    if facts:
        parts.append(f"<p>{'<br>'.join(facts)}</p>")
    parts.extend((
        f"<p>{_price_sentence(candidate, offer, range_member=False)}</p>",
        _methodology(candidate),
        f"<p>{FOOTER}</p>",
    ))
    rendered = "\n".join(parts)
    if not 1 <= len(rendered) <= 32768:
        raise ProductAwardError(
            "product-award rich message exceeds Telegram limit",
            code="MESSAGE-LENGTH",
        )
    return rendered

WORLD_BEER_HOSTS = frozenset({"www.worldbeerawards.com", "worldbeerawards.com"})


CATEGORIES: tuple[ReviewedCategory, ...] = (
    ReviewedCategory(
        "sparkling_cava",
        (
            ReviewedSource(
                "MAPA 2026 sparkling",
                1,
                (),
            ),
            ReviewedSource(
                "OCU cava 2025",
                2,
                (
                    ReviewedCandidate(
                        category_key="sparkling_cava",
                        selection_key="sparkling_cava:2025",
                        event_id="sparkling_cava:ocu-2025:naltros-brut",
                        source_name="OCU",
                        source_kind="ocu",
                        source_url=(
                            "https://www.ocu.org/organizacion/prensa/"
                            "notas-de-prensa/2025/cavas191225"
                        ),
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "25 vinos espumosos",
                            "Naltros Brut (Aldi)",
                            "94 puntos sobre 100",
                        ),
                        retailer="ALDI",
                        retailer_kind="aldi",
                        retailer_url="https://www.aldi.es/p/cava-brut-190300.html",
                        retailer_hosts=frozenset({"www.aldi.es", "aldi.es"}),
                        retailer_markers=("NALTROS", "Cava brut", "0,75 l"),
                        product_name="NALTROS Brut",
                        award_year=2025,
                        source_category="cava",
                        award_scope="exact_product",
                        award_result="94/100, один из лидеров",
                        product_id=190300,
                        expected_ean=None,
                        sample_size=25,
                        package_label="0,75 л",
                        country_label="Испания",
                        producer_label="Jaume Serra",
                        headline_award="один из лидеров OCU",
                        highlight=(
                            "94/100 — один из трёх лидирующих результатов OCU; "
                            "в дегустации отмечены тонкая пузырьковая структура, "
                            "хлебные и фруктовые ноты."
                        ),
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
                        selection_key="gazpacho:2025",
                        event_id="gazpacho:ocu-2025:realfooding",
                        source_name="OCU",
                        source_kind="ocu",
                        source_url=(
                            "https://www.ocu.org/alimentacion/"
                            "platos-preparados/informe/gazpachos"
                        ),
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "39 gazpachos",
                            "Mejor del Análisis",
                            "Real Fooding",
                            "90 sobre 100",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url=(
                            "https://www.carrefour.es/supermercado/"
                            "gazpacho-fresco-realfooding-sin-gluten-1-l/"
                            "R-VC4AECOMM-339275/p"
                        ),
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Gazpacho fresco Realfooding sin gluten 1 l",
                            "CAÑA NATURE",
                            "REALFOODING",
                        ),
                        product_name="Realfooding Gazpacho",
                        award_year=2025,
                        source_category="gazpachos",
                        award_scope="exact_product",
                        award_result="Mejor del Análisis, 90/100",
                        product_id=339275,
                        expected_ean=None,
                        sample_size=39,
                        retailer_title="Gazpacho fresco Realfooding sin gluten 1 l",
                        package_label="1 л, PET",
                        country_label="Испания",
                        producer_label="CAÑA NATURE, S.L.U.",
                        headline_award="Mejor del Análisis OCU",
                        highlight=(
                            "90/100: лучший результат среди 39 газпачо; "
                            "OCU поставила его первым и по дегустации, "
                            "и по Escala Saludable."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="Realfooding official product",
                                page_url="https://realfooding.com/products/gazpacho",
                                page_hosts=frozenset({"realfooding.com"}),
                                image_hosts=frozenset({"realfooding.com"}),
                                page_markers=("Gazpacho Fresco", "Peso envase: 1L"),
                                image_alt_markers=("Gazpacho Fresco",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "aove",
        (
            ReviewedSource(
                "EVOOLEUM 2026 overall",
                1,
                (),
            ),
            ReviewedSource(
                "OCU AOVE 2024",
                2,
                (
                    ReviewedCandidate(
                        category_key="aove",
                        selection_key="aove:2024",
                        event_id="aove:ocu-2024:oleoestepa-dop-estepa",
                        source_name="OCU",
                        source_kind="ocu",
                        source_url=(
                            "https://www.ocu.org/alimentacion/aceite-oliva/"
                            "informe/aceite-oliva-virgen-extra"
                        ),
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "23 productos",
                            "AOVE Oleoestepa, DOP Estepa",
                            "liderada",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url=(
                            "https://www.carrefour.es/supermercado/"
                            "aceite-de-oliva-virgen-extra-oleoestepa-1-l/"
                            "R-589802552/p"
                        ),
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Aceite de oliva virgen extra Oleoestepa 1 l",
                            "D.O. Estepa",
                            "Oleoestepa S.C.A.",
                        ),
                        product_name="Oleoestepa DOP Estepa",
                        award_year=2024,
                        source_category="AOVE",
                        award_scope="exact_product",
                        award_result="Mejor del Análisis",
                        product_id=589802552,
                        expected_ean=None,
                        sample_size=23,
                        retailer_title="Aceite de oliva virgen extra Oleoestepa 1 l",
                        package_label="1 л, PET",
                        country_label="Испания",
                        producer_label="Oleoestepa S.C.A.",
                        headline_award="Mejor del Análisis OCU",
                        highlight=(
                            "Возглавляет рейтинг 23 AOVE OCU; лабораторные "
                            "проверки подтвердили категорию extra, а "
                            "профессиональная дегустация — отсутствие дефектов."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="Oleoestepa official product",
                                page_url=(
                                    "https://tienda.oleoestepa.com/es/"
                                    "aceite-de-oliva-virgen-extra-oleoestepa/"
                                    "29-aceite-de-oliva-virgen-extra-oleoestepa-1-l.html"
                                ),
                                page_hosts=frozenset({"tienda.oleoestepa.com"}),
                                image_hosts=frozenset({"tienda.oleoestepa.com"}),
                                page_markers=(
                                    "Aceite de Oliva Virgen Extra Oleoestepa 1 L",
                                    "8422975000069",
                                ),
                                image_alt_markers=(
                                    "Aceite de Oliva Virgen Extra Oleoestepa 1 L",
                                ),
                            ),
                        ),
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
                        selection_key="coffee_capsules:2024",
                        event_id="coffee_capsules:ocu-2024:aromarte-intenso",
                        source_name="OCU",
                        source_kind="ocu",
                        source_url=(
                            "https://www.ocu.org/alimentacion/cafe/comparador/"
                            "arom-arte-dia-intenso/273/103038"
                        ),
                        source_hosts=frozenset({"www.ocu.org"}),
                        source_markers=(
                            "AROM'ARTE (DIA) Intenso",
                            "Analizado en el laboratorio",
                            "20 unidades",
                            "Nespresso original",
                        ),
                        retailer="DIA",
                        retailer_kind="dia",
                        retailer_url=(
                            "https://www.dia.es/cafe-cacao-e-infusiones/"
                            "capsulas-compatibles-nespresso/p/273821"
                        ),
                        retailer_hosts=frozenset({"www.dia.es"}),
                        retailer_markers=(
                            "Cápsulas de café intenso Dia Arom'arte 20 unidades",
                            "Toscaf",
                            "Nespresso",
                        ),
                        product_name="AROM'ARTE Intenso",
                        award_year=2024,
                        source_category="кофейные капсулы Nespresso/Dolce Gusto",
                        award_scope="exact_product",
                        award_result=(
                            "85/100, лучший результат среди Nespresso с кофеином"
                        ),
                        product_id=273821,
                        expected_ean=None,
                        sample_size=29,
                        retailer_title="Cápsulas de café intenso Dia Arom'arte 20 unidades",
                        package_label="20 капсул, 108 г",
                        producer_label="Toscaf, S.A.",
                        headline_award="лучший результат в группе OCU",
                        highlight=(
                            "85/100 — лучший результат среди капсул Nespresso "
                            "с кофеином в физическом сравнении OCU."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="DIA exact product",
                                page_url=(
                                    "https://www.dia.es/cafe-cacao-e-infusiones/"
                                    "capsulas-compatibles-nespresso/p/273821"
                                ),
                                page_hosts=frozenset({"www.dia.es"}),
                                image_hosts=frozenset({"www.dia.es"}),
                                page_markers=(
                                    "Cápsulas de café intenso Dia Arom'arte 20 unidades",
                                    "Toscaf",
                                ),
                                image_alt_markers=(
                                    "Cápsulas de café intenso Dia Arom'arte 20 unidades",
                                ),
                                use_navigation_headers=True,
                            ),
                        ),
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
                        selection_key="spirits_anis:2026",
                        event_id="spirits_anis:mapa-2026:chinchon-dulce",
                        source_name="MAPA",
                        source_kind="mapa",
                        source_url=(
                            "https://www.mapa.gob.es/es/alimentacion/temas/"
                            "promo-alimentos/premios-alimentos/"
                            "galardonados-bebidas-espirituosas"
                        ),
                        source_hosts=frozenset({"www.mapa.gob.es"}),
                        source_markers=(
                            "Galardonado 2026",
                            "Anís Chinchón de la Alcoholera Dulce",
                            "GONZALEZ BYASS DISTRIBUCION",
                        ),
                        retailer="Carrefour",
                        retailer_kind="carrefour",
                        retailer_url=(
                            "https://www.carrefour.es/supermercado/"
                            "anis-chinchon-dulce-1-l/R-538001406/p"
                        ),
                        retailer_hosts=frozenset({"www.carrefour.es"}),
                        retailer_markers=(
                            "Anís Chinchón dulce 1 l",
                            "35",
                            "I.G.P. Chinchón",
                            "González Byass",
                        ),
                        product_name="Anís Chinchón Dulce",
                        award_year=2026,
                        source_category=(
                            "Mejor Bebida Espirituosa con Indicación Geográfica"
                        ),
                        award_scope="exact_product",
                        award_result="Galardonado 2026",
                        product_id=538001406,
                        expected_ean=None,
                        retailer_title="Anís Chinchón dulce 1 l",
                        package_label="1 л, 35% об.",
                        country_label="Испания",
                        producer_label="González Byass S.A.",
                        headline_award="Premio Alimentos de España 2026",
                        highlight=(
                            "Официальный национальный победитель MAPA в "
                            "категории спиртных напитков с географическим указанием."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="González Byass Chinchón official product",
                                page_url=(
                                    "https://www.gonzalezbyass.com/es/"
                                    "bodegas-marcas/chinchon"
                                ),
                                page_hosts=frozenset({
                                    "www.gonzalezbyass.com",
                                    "gonzalezbyass.com",
                                }),
                                image_hosts=frozenset({
                                    "www.gonzalezbyass.com",
                                    "gonzalezbyass.com",
                                }),
                                page_markers=("Anís dulce", "Chinchón"),
                                image_alt_markers=("Botella Chinchón Anís Dulce",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "international_lager",
        (
            ReviewedSource(
                "World Beer Awards 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="international_lager",
                        selection_key="international_lager:2026",
                        event_id="international_lager:wba-2026:ambar-especial",
                        source_name="World Beer Awards",
                        source_kind="world_beer_awards",
                        source_url=(
                            "https://www.worldbeerawards.com/winner-beer/beer/2026/"
                            "worlds-best-international-lager-68769-world-beer-awards-2026"
                        ),
                        source_hosts=WORLD_BEER_HOSTS,
                        source_markers=(
                            "Ambar",
                            "Especial",
                            "Spain",
                            "GOLD",
                            "Country Winner",
                        ),
                        retailer="Consum",
                        retailer_kind="consum",
                        retailer_url=(
                            "https://tienda.consum.es/api/rest/V1.0/"
                            "catalog/product/22554"
                        ),
                        retailer_hosts=frozenset({"tienda.consum.es"}),
                        retailer_markers=("Cerveza", "Especial"),
                        product_name="Ambar Especial",
                        award_year=2026,
                        source_category="International Lager",
                        award_scope="exact_product",
                        award_result="gold_country_winner",
                        product_id=22554,
                        expected_ean="84107015",
                        package_label="0,33 л, банка",
                        country_label="Испания",
                        producer_label="La Zaragozana, S.A.",
                        headline_award="World Beer Awards 2026",
                        highlight=(
                            "Золото и Spain Country Winner в стиле "
                            "International Lager."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="Ambar official product",
                                page_url="https://ambar.com/cervezas/especial/",
                                page_hosts=frozenset({"ambar.com", "www.ambar.com"}),
                                image_hosts=frozenset({"ambar.com", "www.ambar.com"}),
                                page_markers=("Ambar Especial", "5,2"),
                                image_alt_markers=("especial nueva",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "classic_pilsener",
        (
            ReviewedSource(
                "World Beer Awards 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="classic_pilsener",
                        selection_key="classic_pilsener:2026",
                        event_id="classic_pilsener:wba-2026:mahou-sin-filtrar",
                        source_name="World Beer Awards",
                        source_kind="world_beer_awards",
                        source_url=(
                            "https://www.worldbeerawards.com/winner-beer/beer/2026/"
                            "worlds-best-classic-pilsener-68763-world-beer-awards-2026"
                        ),
                        source_hosts=WORLD_BEER_HOSTS,
                        source_markers=(
                            "Mahou",
                            "Sin Filtrar",
                            "Spain",
                            "GOLD",
                            "Country Winner",
                        ),
                        retailer="Masymas",
                        retailer_kind="masymas",
                        retailer_url=(
                            "https://tienda.masymas.com/api/rest/V1.0/"
                            "catalog/product/10067"
                        ),
                        retailer_hosts=frozenset({
                            "tienda.masymas.com",
                            "cdn-fornes.aktiosdigitalservices.com",
                        }),
                        retailer_markers=("Cerveza", "Sin Filtrar"),
                        product_name="Mahou Sin Filtrar",
                        award_year=2026,
                        source_category="Classic Pilsener",
                        award_scope="exact_product",
                        award_result="gold_country_winner",
                        product_id=10067,
                        expected_ean="8411327010153",
                        package_label="0,33 л, банка",
                        country_label="Испания",
                        producer_label="Mahou, S.A.",
                        headline_award="World Beer Awards 2026",
                        highlight=(
                            "Золото и Spain Country Winner в стиле "
                            "Classic Pilsener."
                        ),
                        image_sources=(
                            ReviewedImageSource(
                                name="Mahou official product",
                                page_url=(
                                    "https://www.mahou-sanmiguel.com/tienda/p/"
                                    "mahou-cinco-estrellas-sin-filtrar.html"
                                ),
                                page_hosts=frozenset({"www.mahou-sanmiguel.com"}),
                                image_hosts=frozenset({"www.mahou-sanmiguel.com"}),
                                page_markers=(
                                    "Mahou Cinco Estrellas Sin Filtrar",
                                    "5.50 % vol.",
                                ),
                                image_alt_markers=(
                                    "Mahou Cinco Estrellas Sin Filtrar",
                                ),
                            ),
                        ),
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
            "published_selections": [],
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
        selections = value.get("published_selections")
        cursor = value.get("category_cursor")
        last_day = value.get("last_delivery_day")
        uncertain = value.get("uncertain_event")
        if (
            not isinstance(published, list)
            or len(published) > MAX_HISTORY
            or any(not isinstance(item, str) or not item for item in published)
            or not isinstance(selections, list)
            or len(selections) > MAX_HISTORY
            or any(not isinstance(item, str) or not item for item in selections)
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

    def last_delivery_day(self) -> Optional[date]:
        raw = self._read()["last_delivery_day"]
        return date.fromisoformat(raw) if raw is not None else None

    def due(self, local_day: date) -> bool:
        last_day = self.last_delivery_day()
        if last_day is None:
            return True
        return (local_day - last_day).days >= COOLDOWN_DAYS

    def uncertain_event(self) -> Optional[str]:
        return self._read()["uncertain_event"]

    def published_events(self) -> frozenset[str]:
        return frozenset(self._read()["published_events"])

    def last_published_event_id(self) -> Optional[str]:
        published = self._read()["published_events"]
        return published[-1] if published else None

    def published_selections(self) -> frozenset[str]:
        return frozenset(self._read()["published_selections"])

    def category_cursor(self) -> int:
        return self._read()["category_cursor"]

    def has_unpublished(self) -> bool:
        published = self.published_events()
        selections = self.published_selections()
        return any(
            candidate.event_id not in published
            and candidate.selection_key not in selections
            for candidate in _all_candidates()
        )

    def mark_uncertain(self, event_id: str) -> None:
        value = self._read()
        value["uncertain_event"] = event_id
        self._write(value)

    def clear_uncertain(self, event_id: str) -> None:
        value = self._read()
        if value["uncertain_event"] == event_id:
            value["uncertain_event"] = None
            self._write(value)

    def confirm(
        self,
        event_id: str,
        selection_key: str,
        category_index: int,
        local_day: date,
    ) -> None:
        value = self._read()
        if value["uncertain_event"] != event_id:
            raise ProductAwardError("product-award delivery reservation is missing", code="STATE")
        published = list(value["published_events"])
        if event_id not in published:
            if len(published) >= MAX_HISTORY:
                raise ProductAwardError("product-award history is full", code="STATE")
            published.append(event_id)
        value["published_events"] = published
        selections = list(value["published_selections"])
        if selection_key not in selections:
            if len(selections) >= MAX_HISTORY:
                raise ProductAwardError("product-award selection history is full", code="STATE")
            selections.append(selection_key)
        value["published_selections"] = selections
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


def _retailer_for_event(event_id: Optional[str]) -> Optional[str]:
    if event_id is None:
        return None
    for candidate in _all_candidates():
        if candidate.event_id == event_id:
            return candidate.retailer_kind
    return None


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
    last_delivery_day = state.last_delivery_day()
    if ignore_cooldown:
        if last_delivery_day == local_day:
            LOGGER.info("SKIP: product-award already delivered today")
            return None
    elif not state.due(local_day):
        LOGGER.info("SKIP: product-award three-day cooldown is active")
        return None
    if not state.has_unpublished():
        LOGGER.info("SKIP: reviewed product-award registry is exhausted")
        return None

    published = state.published_events()
    published_selections = state.published_selections()
    previous_retailer = _retailer_for_event(state.last_published_event_id())
    same_retailer_fallback: Optional[tuple[int, ProductAwardPublication]] = None

    for category_index in _category_order(state.category_cursor()):
        category = CATEGORIES[category_index]
        accepted: Optional[ProductAwardPublication] = None
        for source in sorted(category.sources, key=lambda item: item.priority):
            for candidate in sorted(source.candidates, key=lambda item: item.rank):
                if (
                    candidate.event_id in published
                    or candidate.selection_key in published_selections
                ):
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
                accepted = ProductAwardPublication(
                    candidate=candidate,
                    offer=offer,
                    message=build_message(
                        candidate,
                        offer,
                        include_image=False,
                    ),
                )
                break
            if accepted is not None:
                break

        if accepted is None:
            continue
        if previous_retailer is None or accepted.candidate.retailer_kind != previous_retailer:
            return category_index, accepted
        if same_retailer_fallback is None:
            same_retailer_fallback = (category_index, accepted)

    if same_retailer_fallback is not None:
        return same_retailer_fallback

    LOGGER.info("SKIP: all reviewed product-award candidates are unavailable")
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
                    image = first_product_image(candidate, offer)
                    accepted = ProductAwardPublication(
                        candidate=candidate,
                        offer=offer,
                        message=build_message(
                            candidate,
                            offer,
                            image_src=(image.url if image is not None else None),
                            include_image=(image is not None),
                        ),
                    )
                    break
            if accepted is not None:
                break
        if accepted is not None:
            publications.append(accepted)
    return tuple(publications)
