"""Bounded stateless reader for the Ajuntament de Guardamar Facebook timeline."""

import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from ._transport import BoundedFetchError, fetch_bounded


FACEBOOK_RENDERER_URL = "https://www.facebook.com/platform/plugin/tab/renderer/"
FACEBOOK_HOSTS = {"www.facebook.com"}
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 300_000
USER_AGENT = "Python-urllib/3.14"
# ``email.message`` normalizes away a charset in ``fetch_bounded``.  This is
# only a narrow sanity check; ``parse_renderer_response`` validates the actual
# renderer structure before accepting any posts.
RENDERER_CONTENT_TYPES = frozenset({
    "application/x-javascript",
    "application/javascript",
    "text/javascript",
})
DEFAULT_PAGE_URL = "https://www.facebook.com/253742187973912"
PAGE_CONFIG = {
    "app_id": "776730922422337",
    "href": DEFAULT_PAGE_URL,
    "width": 500,
    "height": 800,
    "has_cta": False,
    "has_small_header": False,
    "has_adapt_container_width": True,
    "has_cover": True,
    "has_posts": False,
    "tabs": "timeline",
    "can_personalize": False,
    "is_xfbml": False,
    "referer_uri": "",
}


class FacebookError(RuntimeError):
    """An operator-safe failure from the optional Facebook source."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status: Optional[int] = None
        self.safe_description = "лента Facebook временно недоступна"


@dataclass(frozen=True)
class FacebookPost:
    """One visible post card, without interpreting its event date."""

    source_id: str
    permalink: str
    published_at: Optional[datetime]
    text: Optional[str]
    image_urls: Tuple[str, ...] = ()


@dataclass
class _Card:
    links: List[str]
    timestamps: List[str]
    images: List[str]
    text_parts: List[str]
    message_depth: Optional[int] = None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+([,.;:!?])", r"\1", " ".join(html.unescape(value).split()))


def _absolute_permalink(value: str) -> Optional[str]:
    value = html.unescape(value)
    candidate = urllib.parse.urljoin("https://www.facebook.com", value)
    parsed = urllib.parse.urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.facebook.com"
        or "/posts/" not in parsed.path
    ):
        return None
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def _image_url(value: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(html.unescape(value))
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


class _TimelineParser(HTMLParser):
    """Read semantic Page Plugin markers from immediate feed cards only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: List[str] = []
        self._feed_depth: Optional[int] = None
        self._card: Optional[_Card] = None
        self.cards: List[_Card] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        fields = dict(attrs)
        if tag not in {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}:
            self._stack.append(tag)
        if fields.get("data-testid") == "newsFeedStream":
            self._feed_depth = len(self._stack)
            return
        if fields.get("role") == "feed" and self._feed_depth is not None:
            self._feed_depth = len(self._stack)
            return
        if (
            self._feed_depth is not None
            and tag == "div"
            and len(self._stack) == self._feed_depth + 1
        ):
            if self._card is not None:
                self.cards.append(self._card)
            self._card = _Card([], [], [], [])
        if self._card is None:
            return
        href = fields.get("href")
        if tag == "a" and href:
            permalink = _absolute_permalink(href)
            if permalink:
                self._card.links.append(permalink)
        timestamp = fields.get("data-utime")
        if tag == "abbr" and timestamp:
            self._card.timestamps.append(timestamp)
        source = fields.get("src")
        if tag == "img" and source:
            image = _image_url(source)
            if image:
                self._card.images.append(image)
        if fields.get("data-testid") == "post_message":
            self._card.message_depth = len(self._stack)

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._card.message_depth is not None:
            self._card.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is not None and (
            self._card.message_depth == len(self._stack) and tag == "div"
        ):
            self._card.message_depth = None
        is_card_end = (
            self._card is not None
            and self._feed_depth is not None
            and tag == "div"
            and len(self._stack) == self._feed_depth + 1
        )
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] == tag:
                del self._stack[index:]
                break
        if is_card_end:
            self.cards.append(self._card)
            self._card = None
        if self._feed_depth is not None and len(self._stack) < self._feed_depth:
            self._feed_depth = None


def _published_at(value: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_renderer_response(payload: bytes) -> Tuple[FacebookPost, ...]:
    """Validate one renderer JSON response and return visible post cards."""

    body = payload.decode("utf-8", "replace")
    if body.startswith("for (;;);"):
        body = body[len("for (;;);"):]
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FacebookError("Facebook renderer returned invalid JSON", code="JSON") from exc
    if not isinstance(document, dict) or document.get("error") is not None:
        raise FacebookError("Facebook renderer returned an error payload", code="PAYLOAD")
    nested = document.get("payload")
    if not isinstance(nested, dict):
        raise FacebookError("Facebook renderer has no payload", code="PAYLOAD")
    markup = nested.get("content", {}).get("markup", {}).get("__html")
    if not isinstance(markup, str) or "newsFeedStream" not in markup:
        raise FacebookError("Facebook renderer has no timeline markup", code="MARKUP")
    parser = _TimelineParser()
    parser.feed(markup)
    posts: List[FacebookPost] = []
    seen = set()
    for card in parser.cards:
        permalink = next(iter(card.links), None)
        if permalink is None or permalink in seen:
            continue
        seen.add(permalink)
        text = _clean_text(" ".join(card.text_parts)) or None
        images = tuple(dict.fromkeys(card.images))
        if text is None and not images:
            continue
        posts.append(FacebookPost(
            source_id=permalink,
            permalink=permalink,
            published_at=_published_at(card.timestamps[0]) if card.timestamps else None,
            text=text,
            image_urls=images,
        ))
    if not posts or not any(post.published_at is not None for post in posts):
        raise FacebookError("Facebook timeline contained no usable posts", code="TIMELINE")
    return tuple(posts)


def _is_facebook_renderer_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.facebook.com"
        and parsed.path == "/platform/plugin/tab/renderer/"
    )


def _renderer_url(page_url: str = DEFAULT_PAGE_URL) -> str:
    query = urllib.parse.urlencode({
        "key": "timeline",
        "__a": "1",
        "config_json": json.dumps({**PAGE_CONFIG, "href": page_url}, separators=(",", ":")),
    })
    return f"{FACEBOOK_RENDERER_URL}?{query}"


def _read_renderer(page_url: str = DEFAULT_PAGE_URL) -> bytes:
    try:
        payload, final_url, _ = fetch_bounded(
            _renderer_url(page_url),
            is_allowed_url=lambda url: urllib.parse.urlparse(url).hostname in FACEBOOK_HOSTS,
            accepted_types=RENDERER_CONTENT_TYPES,
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
    except BoundedFetchError as exc:
        error = FacebookError("Facebook renderer request failed", code=exc.code)
        error.server_status = exc.status
        raise error from exc
    if not _is_facebook_renderer_url(final_url):
        raise FacebookError("Facebook renderer redirected outside its endpoint", code="REDIRECT")
    return payload


async def fetch_facebook_posts(page_url: str = DEFAULT_PAGE_URL) -> Tuple[FacebookPost, ...]:
    """Fetch the recent public timeline without session or cookie state."""

    import asyncio

    payload = await asyncio.to_thread(_read_renderer, page_url)
    return parse_renderer_response(payload)
