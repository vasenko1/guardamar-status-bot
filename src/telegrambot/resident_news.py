"""First-party-grounded practical news discovered through Euro Weekly News."""

import fcntl
import html
import json
import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Optional, Sequence

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer
from .gemini import classify_resident_news, compose_resident_news


LOGGER = logging.getLogger(__name__)
EWN_FEED_URL = "https://euroweeklynews.com/news/spain/feed/"
EWN_HOST = "euroweeklynews.com"
STATE_SCHEMA_VERSION = 1
MAX_FEED_BYTES = 256 * 1024
MAX_ARTICLE_BYTES = 768 * 1024
MAX_PRIMARY_BYTES = 768 * 1024
MAX_BATCH_ITEMS = 8
MAX_DESCRIPTION_CHARS = 500
MAX_PRIMARY_TEXT_CHARS = 8_000
MAX_STATE_ITEMS = 128
MAX_PENDING_AGE = timedelta(hours=48)
REQUEST_TIMEOUT_SECONDS = 15


class ResidentNewsError(RuntimeError):
    """Bounded resident-news failure with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


class ResidentNewsDeliveryUncertain(RuntimeError):
    """Telegram may have accepted the message; automatic resend is unsafe."""


@dataclass(frozen=True)
class DiscoveryItem:
    item_id: str
    title: str
    description: str
    url: str
    published_at: datetime


@dataclass(frozen=True)
class ResidentNewsPost:
    headline_ru: str
    paragraphs_ru: tuple[str, ...]
    emoji: str
    status: str


class _TextOnlyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.capture_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "header", "footer", "form", "aside"}:
            self.skip_depth += 1
        if tag in {"title", "h1", "h2", "h3", "p", "li"}:
            self.capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "header", "footer", "form", "aside"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag in {"title", "h1", "h2", "h3", "p", "li"}:
            self.capture_depth = max(0, self.capture_depth - 1)
            if self.parts and self.parts[-1] != "\n":
                self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.capture_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)
            self.parts.append(" ")


class _ArticleLinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.saw_article = False
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "article":
            self.article_depth += 1
            self.saw_article = True
        if tag == "a" and self.article_depth:
            href = dict(attrs).get("href")
            if isinstance(href, str) and href.strip():
                self.links.append(href.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "article" and self.article_depth:
            self.article_depth -= 1


class _AllTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"}:
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def _strip_html(value: str) -> str:
    parser = _AllTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise ResidentNewsError("RSS description HTML is invalid", code="RSS") from exc
    return " ".join(parser.parts)


def _is_ewn_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {EWN_HOST, f"www.{EWN_HOST}"}
    )


def _approved_primary_host(host: Optional[str]) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host == "boe.es" or host.endswith(".boe.es"):
        return True
    if host == "dgt.es" or host.endswith(".dgt.es"):
        return True
    if host == "renfe.com" or host.endswith(".renfe.com"):
        return True
    if host == "gva.es" or host.endswith(".gva.es"):
        return True
    if host.endswith(".gob.es"):
        return True
    for family in (
        "sepe.es",
        "seg-social.es",
        "aemet.es",
        "congreso.es",
        "senado.es",
        "ccoo.es",
        "ugt.es",
        "cgt.es",
    ):
        if host == family or host.endswith(f".{family}"):
            return True
    return False


def is_approved_primary_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and _approved_primary_host(parsed.hostname)


def source_label(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "boe.es" or host.endswith(".boe.es"):
        return "BOE"
    if host == "dgt.es" or host.endswith(".dgt.es"):
        return "DGT"
    if host == "renfe.com" or host.endswith(".renfe.com"):
        return "Renfe"
    if host == "gva.es" or host.endswith(".gva.es"):
        return "Generalitat Valenciana"
    if host == "sepe.es" or host.endswith(".sepe.es"):
        return "SEPE"
    if host == "seg-social.es" or host.endswith(".seg-social.es"):
        return "Seguridad Social"
    if host == "aemet.es" or host.endswith(".aemet.es"):
        return "AEMET"
    if host == "lamoncloa.gob.es" or host.endswith(".lamoncloa.gob.es"):
        return "La Moncloa"
    if (
        host == "agenciatributaria.gob.es"
        or host.endswith(".agenciatributaria.gob.es")
    ):
        return "Agencia Tributaria"
    if host == "congreso.es" or host.endswith(".congreso.es"):
        return "Congreso de los Diputados"
    if host == "senado.es" or host.endswith(".senado.es"):
        return "Senado"
    if host == "ccoo.es" or host.endswith(".ccoo.es"):
        return "CCOO"
    if host == "ugt.es" or host.endswith(".ugt.es"):
        return "UGT"
    if host == "cgt.es" or host.endswith(".cgt.es"):
        return "CGT"
    if host.endswith(".gob.es"):
        return "Gobierno de España"
    raise ResidentNewsError("primary source label is unknown", code="SOURCE")


def parse_feed(payload: bytes) -> tuple[DiscoveryItem, ...]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ResidentNewsError("EWN RSS is invalid XML", code="RSS") from exc
    items: list[DiscoveryItem] = []
    for element in root.findall(".//item")[:32]:
        title = (element.findtext("title") or "").strip()
        url = (element.findtext("link") or "").strip()
        guid = (element.findtext("guid") or "").strip()
        published = (element.findtext("pubDate") or "").strip()
        description_raw = element.findtext("description") or ""
        if not title or not _is_ewn_url(url) or not published:
            continue
        try:
            published_at = parsedate_to_datetime(published)
        except (TypeError, ValueError, OverflowError):
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        item_id = guid if guid and len(guid) <= 500 else url
        description = _strip_html(description_raw)[:MAX_DESCRIPTION_CHARS]
        items.append(DiscoveryItem(
            item_id=item_id,
            title=" ".join(html.unescape(title).split())[:300],
            description=description,
            url=url,
            published_at=published_at.astimezone(timezone.utc),
        ))
    items.sort(key=lambda item: item.published_at)
    return tuple(items)


def _fetch_feed() -> tuple[DiscoveryItem, ...]:
    try:
        payload, _, _ = fetch_bounded(
            EWN_FEED_URL,
            is_allowed_url=_is_ewn_url,
            accepted_types=frozenset({
                "application/rss+xml",
                "application/xml",
                "text/xml",
            }),
            limit_bytes=MAX_FEED_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise ResidentNewsError("EWN RSS fetch failed", code=exc.code) from exc
    return parse_feed(payload)


async def fetch_feed() -> tuple[DiscoveryItem, ...]:
    import asyncio
    return await asyncio.to_thread(_fetch_feed)


def _fetch_ewn_article(url: str) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_is_ewn_url,
            accepted_types=frozenset({"text/html"}),
            limit_bytes=MAX_ARTICLE_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise ResidentNewsError("EWN article fetch failed", code=exc.code) from exc
    return payload


def first_primary_link(article_url: str, payload: bytes) -> Optional[str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResidentNewsError("EWN article encoding is invalid", code="ARTICLE") from exc
    parser = _ArticleLinksParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise ResidentNewsError("EWN article HTML is invalid", code="ARTICLE") from exc
    if not parser.saw_article:
        raise ResidentNewsError("EWN article body was not found", code="ARTICLE")
    for href in parser.links:
        candidate = urllib.parse.urljoin(article_url, href)
        if is_approved_primary_url(candidate):
            return candidate
    return None


async def fetch_primary_link(article_url: str) -> Optional[str]:
    import asyncio
    payload = await asyncio.to_thread(_fetch_ewn_article, article_url)
    return first_primary_link(article_url, payload)


def _fetch_primary_text(url: str) -> tuple[str, str]:
    if not is_approved_primary_url(url):
        raise ResidentNewsError("primary URL is outside the allowlist", code="SOURCE")
    try:
        payload, final_url, _ = fetch_bounded(
            url,
            is_allowed_url=is_approved_primary_url,
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=MAX_PRIMARY_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html, application/xhtml+xml",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise ResidentNewsError("primary source fetch failed", code=exc.code) from exc
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResidentNewsError("primary source encoding is invalid", code="SOURCE") from exc
    parser = _TextOnlyParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as exc:
        raise ResidentNewsError("primary source HTML is invalid", code="SOURCE") from exc
    normalized = "\n".join(
        line.strip()
        for line in "".join(parser.parts).splitlines()
        if line.strip()
    )
    normalized = normalized[:MAX_PRIMARY_TEXT_CHARS].strip()
    if len(normalized) < 80:
        raise ResidentNewsError("primary source text is too short", code="SOURCE")
    return normalized, final_url


async def fetch_primary_text(url: str) -> tuple[str, str]:
    import asyncio
    return await asyncio.to_thread(_fetch_primary_text, url)


class ResidentNewsState:
    """Small atomic state for discovery, deduplication and delivery safety."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _empty(self) -> dict:
        return {"schema_version": STATE_SCHEMA_VERSION, "seeded": False, "items": {}}

    def _read(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResidentNewsError("resident-news state is unreadable", code="STATE") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != STATE_SCHEMA_VERSION
            or not isinstance(value.get("seeded"), bool)
            or not isinstance(value.get("items"), dict)
            or len(value["items"]) > MAX_STATE_ITEMS
        ):
            raise ResidentNewsError("resident-news state is invalid", code="STATE")
        return value

    def _write(self, value: dict) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ResidentNewsError("resident-news state could not be saved", code="STATE") from exc

    def is_seeded(self) -> bool:
        return self._read()["seeded"]

    def seed(self, items: Sequence[DiscoveryItem]) -> None:
        value = self._empty()
        value["seeded"] = True
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in items[-MAX_STATE_ITEMS:]:
            value["items"][item.item_id] = {
                "url": item.url,
                "title": item.title,
                "published_at": item.published_at.isoformat(),
                "status": "seeded",
                "observed_at": now_iso,
            }
        self._write(value)

    def unseen(self, items: Sequence[DiscoveryItem]) -> tuple[DiscoveryItem, ...]:
        known = self._read()["items"]
        return tuple(item for item in items if item.item_id not in known)[:MAX_BATCH_ITEMS]

    def record_classifications(self, items: Sequence[DiscoveryItem], decisions: Sequence[dict]) -> None:
        if len(items) != len(decisions):
            raise ResidentNewsError("classification result count mismatch", code="AI")
        by_id = {decision.get("id"): decision for decision in decisions}
        expected = {item.item_id for item in items}
        if set(by_id) != expected:
            raise ResidentNewsError("classification IDs mismatch", code="AI")
        value = self._read()
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in items:
            decision = by_id[item.item_id]
            relevant = decision.get("relevant")
            topic = decision.get("topic")
            priority = decision.get("priority")
            if not isinstance(relevant, bool) or priority not in {"high", "normal"}:
                raise ResidentNewsError("classification result is invalid", code="AI")
            if not isinstance(topic, str) or not 1 <= len(topic) <= 40:
                raise ResidentNewsError("classification topic is invalid", code="AI")
            value["items"][item.item_id] = {
                "url": item.url,
                "title": item.title,
                "published_at": item.published_at.isoformat(),
                "status": "eligible" if relevant else "dropped",
                "topic": topic,
                "priority": priority,
                "observed_at": now_iso,
            }
        self._prune(value)
        self._write(value)

    def _prune(self, value: dict) -> None:
        items = value["items"]
        if len(items) <= MAX_STATE_ITEMS:
            return
        ordered = sorted(
            items.items(),
            key=lambda pair: pair[1].get("published_at", ""),
            reverse=True,
        )
        kept = dict(ordered[:MAX_STATE_ITEMS])
        items.clear()
        items.update(kept)

    def next_eligible(self, now: datetime) -> Optional[tuple[str, dict]]:
        value = self._read()
        eligible: list[tuple[str, dict, datetime]] = []
        changed = False
        for item_id, record in value["items"].items():
            if record.get("status") != "eligible":
                continue
            try:
                published = datetime.fromisoformat(record["published_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if now.astimezone(timezone.utc) - published.astimezone(timezone.utc) > MAX_PENDING_AGE:
                record["status"] = "stale"
                changed = True
                continue
            eligible.append((item_id, record, published))
        if changed:
            self._write(value)
        if not eligible:
            return None
        eligible.sort(key=lambda row: (row[1].get("priority") != "high", row[2]))
        item_id, record, _ = eligible[0]
        return item_id, dict(record)

    def mark_source_missing(self, item_id: str) -> None:
        self._set_status(item_id, "source_missing")

    def mark_uncertain(self, item_id: str) -> None:
        self._set_status(item_id, "uncertain")

    def clear_uncertain(self, item_id: str) -> None:
        self._set_status(item_id, "eligible", only_if="uncertain")

    def mark_published(self, item_id: str, message_id: int, source_url: str) -> None:
        value = self._read()
        record = value["items"].get(item_id)
        if not isinstance(record, dict) or record.get("status") != "uncertain":
            raise ResidentNewsError("resident-news delivery reservation is missing", code="STATE")
        record["status"] = "published"
        record["message_id"] = message_id
        record["source_url"] = source_url
        self._write(value)

    def _set_status(self, item_id: str, status: str, *, only_if: Optional[str] = None) -> None:
        value = self._read()
        record = value["items"].get(item_id)
        if not isinstance(record, dict):
            raise ResidentNewsError("resident-news item is missing", code="STATE")
        if only_if is not None and record.get("status") != only_if:
            return
        record["status"] = status
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
            raise ResidentNewsError("another resident-news run is active", code="LOCK") from exc
        except OSError as exc:
            if lock is not None:
                lock.close()
            raise ResidentNewsError("resident-news state could not be locked", code="STATE") from exc
        try:
            yield
        finally:
            assert lock is not None
            lock.close()


def build_message(post: ResidentNewsPost, primary_url: str) -> str:
    label = source_label(primary_url)
    headline = html.escape(post.headline_ru)
    paragraphs = "\n\n".join(html.escape(value) for value in post.paragraphs_ru)
    source = (
        f'🔗 <b>Источник: <a href="{html.escape(primary_url, quote=True)}">'
        f'{html.escape(label)}</a></b>'
    )
    return with_footer(
        f"{html.escape(post.emoji)} <b>{headline}</b>\n\n{paragraphs}\n\n{source}"
    )


async def run_resident_news(
    now: datetime,
    state: ResidentNewsState,
    gemini_api_key: str,
    publish: Callable[[str], Awaitable[int]],
) -> str:
    """Run one bounded discovery/classification/publication lifecycle."""

    with state.exclusive_run():
        feed = await fetch_feed()
        if not feed:
            raise ResidentNewsError("EWN RSS contained no valid items", code="RSS")
        if not state.is_seeded():
            state.seed(feed)
            LOGGER.info("Resident-news RSS baseline seeded silently")
            return "seeded"

        unseen = state.unseen(feed)
        if unseen:
            decisions = await classify_resident_news(
                gemini_api_key,
                [
                    {
                        "id": item.item_id,
                        "title": item.title,
                        "description": item.description,
                    }
                    for item in unseen
                ],
            )
            state.record_classifications(unseen, decisions)

        selected = state.next_eligible(now)
        if selected is None:
            return "no_candidate"
        item_id, record = selected
        primary_url = await fetch_primary_link(record["url"])
        if primary_url is None:
            state.mark_source_missing(item_id)
            LOGGER.info("Resident-news candidate omitted: no approved first-party link")
            return "source_missing"

        source_text, primary_url = await fetch_primary_text(primary_url)
        composed = await compose_resident_news(
            gemini_api_key,
            discovery_title=record["title"],
            source_name=source_label(primary_url),
            source_text=source_text,
        )
        if composed.get("supported") is not True:
            state.mark_source_missing(item_id)
            LOGGER.info(
                "Resident-news candidate omitted: first-party source did not "
                "support the discovered topic"
            )
            return "source_unsupported"
        post = ResidentNewsPost(
            headline_ru=composed["headline_ru"],
            paragraphs_ru=tuple(composed["paragraphs_ru"]),
            emoji=composed["emoji"],
            status=composed["status"],
        )
        message = build_message(post, primary_url)
        state.mark_uncertain(item_id)
        try:
            message_id = await publish(message)
        except ResidentNewsDeliveryUncertain:
            LOGGER.warning("Resident-news delivery uncertain; automatic resend disabled")
            return "uncertain"
        except Exception:
            state.clear_uncertain(item_id)
            raise
        state.mark_published(item_id, message_id, primary_url)
        return "published"
