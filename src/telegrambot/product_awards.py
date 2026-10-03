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


def _fetch_html(url: str, hosts: frozenset[str]) -> str:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_allowed(hosts),
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
                "User-Agent": USER_AGENT,
            },
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


def fetch_product_image(
    candidate: ReviewedCandidate,
    url: str,
) -> tuple[bytes, str]:
    media_hosts = {
        "consum": CONSUM_MEDIA_HOSTS,
        "masymas": MASYMAS_MEDIA_HOSTS,
        "aldi": ALDI_MEDIA_HOSTS,
    }.get(candidate.retailer_kind, frozenset())
    allowed_hosts = candidate.retailer_hosts | media_hosts
    try:
        payload, _, content_type = fetch_bounded(
            url,
            is_allowed_url=_allowed(allowed_hosts),
            accepted_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
            limit_bytes=IMAGE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "image/webp,image/png,image/jpeg,*/*;q=0.8",
                "User-Agent": USER_AGENT,
            },
        )
    except BoundedFetchError as exc:
        raise ProductAwardError(
            "retailer product image could not be downloaded",
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


def _aldi_next_data(source: str) -> dict | list:
    import re

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
    raise ProductAwardError(
        "unknown retailer adapter",
        code="CONFIG",
    )


def _price_sentence(offer: RetailOffer, *, range_member: bool) -> str:
    subject = "Этот вариант" if range_member else "Сейчас этот товар"
    if offer.regular_price is not None and offer.regular_price != offer.price:
        return (
            f"{subject} в {html.escape(offer.retailer)} стоит "
            f"<b>{html.escape(offer.price)}</b> вместо обычных "
            f"{html.escape(offer.regular_price)}."
        )
    return (
        f"{subject} в {html.escape(offer.retailer)} стоит "
        f"<b>{html.escape(offer.price)}</b>."
    )


def _methodology(candidate: ReviewedCandidate) -> str:
    if candidate.source_kind == "producto_del_ano":
        return (
            "<blockquote expandable>"
            "🔬 <b>Как выбирают Producto del Año</b><br><br>"
            "Это испанская потребительская премия за инновации. "
            "По данным организатора, в голосовании участвуют более "
            "10 000 потребителей, а каждый кандидат дополнительно "
            "проходит тест продукта среди 100 представителей своей "
            "целевой аудитории. Победителем становится продукт с "
            "наибольшим результатом в своей категории."
            "</blockquote>"
        )
    if candidate.source_kind == "world_beer_awards":
        return (
            "<blockquote expandable>"
            "🔬 <b>Как проходит World Beer Awards</b><br><br>"
            "Пиво оценивают вслепую международные экспертные панели. "
            "На первых этапах продукты сравниваются внутри своих стилей "
            "и стран, после чего победители могут проходить дальше в "
            "конкурсе."
            "</blockquote>"
        )
    if candidate.source_kind == "ocu":
        return (
            "<blockquote expandable>"
            "🔬 <b>Как проходил тест OCU</b><br><br>"
            "OCU проверяла состав и основные лабораторные показатели cava, "
            "а также проводила отдельную дегустационную оценку. Итоговый "
            "балл объединяет результаты этих проверок."
            "</blockquote>"
        )
    raise ProductAwardError(
        "unknown award methodology",
        code="CONFIG",
    )


def build_message(
    candidate: ReviewedCandidate,
    offer: RetailOffer,
    *,
    image_src: Optional[str] = None,
) -> str:
    name = html.escape(candidate.product_name)
    category = html.escape(candidate.source_category)

    if candidate.source_kind == "producto_del_ano":
        title = f"Producto del Año {candidate.award_year}: {name}"
        if candidate.award_scope == "range":
            first = (
                f"Награда относится к линейке <b>{name}</b> в категории "
                f"{category}. В {html.escape(offer.retailer)} сейчас продается "
                "один из продуктов этой линейки: "
                f"<b>{html.escape(offer.product_name)}</b>."
            )
            price = _price_sentence(offer, range_member=True)
        else:
            first = (
                f"<b>{name}</b> стал победителем Producto del Año "
                f"{candidate.award_year} в категории {category}."
            )
            price = _price_sentence(offer, range_member=False)
    elif candidate.source_kind == "world_beer_awards":
        title = (
            f"Пиво {name} получило золото World Beer Awards "
            f"{candidate.award_year}"
        )
        first = (
            f"На World Beer Awards {candidate.award_year} <b>{name}</b> "
            f"получило золото и стало победителем Испании в стиле {category}."
        )
        price = _price_sentence(offer, range_member=False)
    elif candidate.source_kind == "ocu":
        title = f"{name} получил {html.escape(candidate.award_result)} в тесте OCU"
        sample = (
            f"{candidate.sample_size} cava"
            if candidate.sample_size is not None
            else "cava"
        )
        first = (
            "<b>OCU - испанская Организация потребителей и пользователей</b> "
            f"сравнила {sample}. <b>{name}</b> получил "
            f"{html.escape(candidate.award_result)} и вошел в число лидеров "
            "исследования."
        )
        price = _price_sentence(offer, range_member=False)
    else:
        raise ProductAwardError(
            "unknown award renderer",
            code="CONFIG",
        )

    parts = []
    image_value = image_src if image_src is not None else offer.image_url
    if image_value:
        parts.append(f'<img src="{html.escape(image_value, quote=True)}"/>')
    parts.extend((
        f"<p>🏆 <b>{title}</b></p>",
        f"<p>{first}</p>",
        f"<p>{price}</p>",
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


PRODUCTO_DEL_ANO_URL = (
    "https://granpremioalainnovacion.com/productos-ganadores-pda/"
)
PRODUCTO_DEL_ANO_HOSTS = frozenset({"granpremioalainnovacion.com"})
WORLD_BEER_HOSTS = frozenset({"www.worldbeerawards.com", "worldbeerawards.com"})


CATEGORIES: tuple[ReviewedCategory, ...] = (
    ReviewedCategory(
        "sparkling_cava",
        (
            ReviewedSource(
                "OCU cava 2025",
                1,
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
                        award_result="94/100",
                        product_id=190300,
                        expected_ean=None,
                        sample_size=25,
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "dairy_drinks",
        (
            ReviewedSource(
                "Producto del Año 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="dairy_drinks",
                        selection_key="dairy_drinks:2026",
                        event_id="dairy_drinks:pda-2026:celta-proteina",
                        source_name="Producto del Año",
                        source_kind="producto_del_ano",
                        source_url=PRODUCTO_DEL_ANO_URL,
                        source_hosts=PRODUCTO_DEL_ANO_HOSTS,
                        source_markers=("CELTA + PROTEÍNA", "BEBIDAS LÁCTEAS"),
                        retailer="Consum",
                        retailer_kind="consum",
                        retailer_url=(
                            "https://tienda.consum.es/api/rest/V1.0/"
                            "catalog/product/45721"
                        ),
                        retailer_hosts=frozenset({"tienda.consum.es"}),
                        retailer_markers=("Batido", "Proteina", "Café"),
                        product_name="Celta +Proteína",
                        award_year=2026,
                        source_category="Bebidas Lácteas",
                        award_scope="range",
                        award_result="Producto del Año",
                        product_id=45721,
                        expected_ean="8414044004122",
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "snacks",
        (
            ReviewedSource(
                "Producto del Año 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="snacks",
                        selection_key="snacks:2026",
                        event_id="snacks:pda-2026:takis-blue-heat",
                        source_name="Producto del Año",
                        source_kind="producto_del_ano",
                        source_url=PRODUCTO_DEL_ANO_URL,
                        source_hosts=PRODUCTO_DEL_ANO_HOSTS,
                        source_markers=("TAKIS BLUE HEAT", "SNACKS"),
                        retailer="Consum",
                        retailer_kind="consum",
                        retailer_url=(
                            "https://tienda.consum.es/api/rest/V1.0/"
                            "catalog/product/43051"
                        ),
                        retailer_hosts=frozenset({"tienda.consum.es"}),
                        retailer_markers=("Takis", "Blue Heat"),
                        product_name="Takis Blue Heat",
                        award_year=2026,
                        source_category="Snacks",
                        award_scope="exact_product",
                        award_result="Producto del Año",
                        product_id=43051,
                        expected_ean="8412600047163",
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "meat_prepared",
        (
            ReviewedSource(
                "Producto del Año 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="meat_prepared",
                        selection_key="meat_prepared:2026",
                        event_id="meat_prepared:pda-2026:elpozo-extratiernos",
                        source_name="Producto del Año",
                        source_kind="producto_del_ano",
                        source_url=PRODUCTO_DEL_ANO_URL,
                        source_hosts=PRODUCTO_DEL_ANO_HOSTS,
                        source_markers=(
                            "EXTRATIERNOS",
                            "ESCALOPINES",
                            "SOLOMILLOS",
                            "CÁRNICOS + PLATOS PREPARADOS",
                        ),
                        retailer="Consum",
                        retailer_kind="consum",
                        retailer_url=(
                            "https://tienda.consum.es/api/rest/V1.0/"
                            "catalog/product/23530"
                        ),
                        retailer_hosts=frozenset({"tienda.consum.es"}),
                        retailer_markers=("Escalopín", "Extratierno"),
                        product_name="ELPOZO ExtraTiernos",
                        award_year=2026,
                        source_category="Cárnicos + Platos Preparados",
                        award_scope="range",
                        award_result="Producto del Año",
                        product_id=23530,
                        expected_ean="8410843064220",
                    ),
                ),
            ),
        ),
    ),
    ReviewedCategory(
        "refrigerated_coffee",
        (
            ReviewedSource(
                "Producto del Año 2026",
                1,
                (
                    ReviewedCandidate(
                        category_key="refrigerated_coffee",
                        selection_key="refrigerated_coffee:2026",
                        event_id="refrigerated_coffee:pda-2026:nescafe-latte-baileys",
                        source_name="Producto del Año",
                        source_kind="producto_del_ano",
                        source_url=PRODUCTO_DEL_ANO_URL,
                        source_hosts=PRODUCTO_DEL_ANO_HOSTS,
                        source_markers=("NESCAFÉ LATTE BAILEYS", "CAFÉS REFRIGERADOS"),
                        retailer="Consum",
                        retailer_kind="consum",
                        retailer_url=(
                            "https://tienda.consum.es/api/rest/V1.0/"
                            "catalog/product/44075"
                        ),
                        retailer_hosts=frozenset({"tienda.consum.es"}),
                        retailer_markers=("Nescafé", "Latte", "Baileys"),
                        product_name="Nescafé Latte Baileys",
                        award_year=2026,
                        source_category="Cafés Refrigerados",
                        award_scope="exact_product",
                        award_result="Producto del Año",
                        product_id=44075,
                        expected_ean="8435257073224",
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
                    message=build_message(candidate, offer),
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
