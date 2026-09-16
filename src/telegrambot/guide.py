"""One-shot synchronization for the linked city guide.

The first vertical slice keeps pool facility facts deterministic and stores only
a small normalized SimplyBook catalogue baseline. Registration availability is
deliberately not inferred until the provider's batched availability contract
has been validated on the production runtime.
"""

import argparse
import asyncio
import fcntl
import html
import json
import logging
import os
import tempfile
import urllib.parse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterator, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer
from .commands import parse_allowed_user_ids
from .pinned import (
    DEFAULT_PINNED_STATE_PATH,
    PinnedGuideState,
    publish_pinned_guide,
    telegram_message_link,
)
from .sporttia import (
    SporttiaSourceError,
    fetch_sporttia_catalog,
    merge_sporttia_catalog,
    valid_sporttia_snapshot,
)
from .state import StateError
from .telegram import (
    TelegramError,
    edit_message,
    pin_chat_message,
    send_message,
)

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_GUIDE_STATE_PATH = "state/guide.json"
AQUALIDER_ORIGIN = "https://aqualidernatacion.simplybook.it"
AQUALIDER_BASE_URL = f"{AQUALIDER_ORIGIN}/v2"
WIFI_SOURCE_PAGE_URL = "https://www.guardamardelsegura.es/wifis-municipales/"
WIFI_VERIFIED_ASSET_URL = (
    "https://www.guardamardelsegura.es/wp-content/uploads/2021/06/"
    "PLANO-WIFIS-GUARDAMAR-PU%CC%81BLICAS.pdf"
)
_GUIDE_STATE_VERSION = 1
_JSON_TYPES = frozenset({"application/json"})
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "guardamar-status-bot/1.0",
}
_WIFI_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}


class GuideSourceError(RuntimeError):
    """A bounded source response that is unsafe to use."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class GuideState:
    """Minimal normalized source baseline and seasonal-notice state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict:
        if not self.path.exists():
            return {"version": _GUIDE_STATE_VERSION}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("guide state is unreadable") from exc
        if not isinstance(value, dict) or value.get("version") != _GUIDE_STATE_VERSION:
            raise StateError("guide state has an invalid structure")
        snapshot = value.get("aqualider_catalog")
        if snapshot is not None and not _valid_snapshot(snapshot):
            raise StateError("guide state has an invalid Aqualider snapshot")
        sporttia = value.get("sporttia_catalog")
        if sporttia is not None and not valid_sporttia_snapshot(sporttia):
            raise StateError("guide state has an invalid Sporttia snapshot")
        notice = value.get("season_notice")
        if notice is not None and (
            not isinstance(notice, dict)
            or not isinstance(notice.get("key"), str)
            or not isinstance(notice.get("message_id"), int)
            or notice["message_id"] <= 0
        ):
            raise StateError("guide state has an invalid seasonal notice")
        uncertain = value.get("season_notice_uncertain")
        if uncertain is not None and not isinstance(uncertain, str):
            raise StateError("guide state has an invalid uncertain notice")
        wifi_alerted = value.get("wifi_last_alerted_asset_url")
        if wifi_alerted is not None and (
            not isinstance(wifi_alerted, str) or not wifi_alerted.strip()
        ):
            raise StateError("guide state has an invalid Wi-Fi source alert")
        return value

    def write(self, value: dict) -> None:
        normalized = dict(value)
        normalized["version"] = _GUIDE_STATE_VERSION
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=f".{self.path.name}."
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(normalized, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            temporary = None
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise StateError("guide state could not be written") from exc
        except Exception:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock_file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError("another guide sync is already active") from exc
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError("guide state could not be locked") from exc
        try:
            yield
        finally:
            assert lock_file is not None
            lock_file.close()


def active_pool(local_day: date) -> str:
    """Return the deterministic municipal pool season for a local date."""

    summer_start = date(local_day.year, 6, 16)
    summer_end = date(local_day.year, 9, 15)
    return "outdoor" if summer_start <= local_day <= summer_end else "indoor"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _allowed_aqualider_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "aqualidernatacion.simplybook.it"
        and port in {None, 443}
        and parsed.path.startswith("/v2/")
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_wifi_source_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
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


def _extract_wifi_asset_url(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuideSourceError(
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
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        canonical_path = urllib.parse.quote(
            urllib.parse.unquote(parsed.path),
            safe="/:@!$&'()*+,;=-._~",
        )
        urls.add(
            urllib.parse.urlunsplit(
                parsed._replace(path=canonical_path, fragment="")
            )
        )
    if len(urls) != 1:
        raise GuideSourceError(
            "Wi-Fi source asset is missing or ambiguous",
            code="WIFI-LINK" if not urls else "WIFI-AMBIGUOUS",
        )
    return urls.pop()


async def fetch_current_wifi_asset() -> str:
    """Return the one asset currently linked from the municipal Wi-Fi page."""

    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            WIFI_SOURCE_PAGE_URL,
            is_allowed_url=_allowed_wifi_source_url,
            limit_bytes=512 * 1024,
            timeout_seconds=15.0,
            headers=_WIFI_REQUEST_HEADERS,
            accepted_types=_HTML_TYPES,
        )
    except BoundedFetchError as exc:
        raise GuideSourceError(
            "Wi-Fi source request failed", code=f"WIFI-{exc.code}"
        ) from exc
    return _extract_wifi_asset_url(payload)


def _wifi_operator_ids() -> Tuple[int, ...]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not raw:
        return ()
    try:
        return tuple(sorted(parse_allowed_user_ids(raw)))
    except ValueError:
        logging.warning(
            "Wi-Fi source watch disabled: TELEGRAM_ALLOWED_USER_IDS is invalid"
        )
        return ()


def _wifi_alert_text(current_asset_url: str) -> str:
    verified = html.escape(WIFI_VERIFIED_ASSET_URL)
    current = html.escape(current_asset_url)
    return (
        "⚠️ <b>Изменился официальный источник муниципального Wi-Fi.</b>\n\n"
        "Нужно проверить точки, SSID и пароли.\n\n"
        f"Проверенная версия:\n<code>{verified}</code>\n\n"
        f"Новая версия:\n<code>{current}</code>"
    )


async def _check_wifi_source(
    bot_token: str,
    state: dict,
    guide_state: GuideState,
) -> None:
    operators = _wifi_operator_ids()
    if not operators:
        return
    try:
        current = await fetch_current_wifi_asset()
    except GuideSourceError as exc:
        logging.warning(
            "Wi-Fi source check deferred [GUIDE-%s]", exc.diagnostic_code
        )
        return
    if current == WIFI_VERIFIED_ASSET_URL:
        return
    if current == state.get("wifi_last_alerted_asset_url"):
        return

    for operator_id in operators:
        try:
            await send_message(
                bot_token,
                str(operator_id),
                _wifi_alert_text(current),
                disable_notification=False,
                retry_only_rate_limits=True,
            )
        except TelegramError as exc:
            logging.warning(
                "Wi-Fi source alert delivery failed [TELEGRAM-%s]",
                exc.diagnostic_code,
            )
            continue
        state["wifi_last_alerted_asset_url"] = current
        guide_state.write(state)
        logging.warning("Wi-Fi source changed; private operator alert sent")
        return

    logging.warning("Wi-Fi source change remains pending operator delivery")


def _positive_id(value, field: str) -> int:
    if isinstance(value, bool):
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    if isinstance(value, int):
        identifier = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        identifier = int(value)
    else:
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    if identifier <= 0:
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    return identifier


def _name(value, field: str) -> str:
    if not isinstance(value, str):
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 200:
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    return normalized


def _id_list(value, field: str) -> Tuple[int, ...]:
    if not isinstance(value, list) or len(value) > 256:
        raise GuideSourceError(f"invalid {field}", code="SCHEMA")
    identifiers = tuple(_positive_id(item, field) for item in value)
    if len(set(identifiers)) != len(identifiers):
        raise GuideSourceError(f"duplicate {field}", code="SCHEMA")
    return tuple(sorted(identifiers))


def _normalize_services(value) -> Tuple[dict, ...]:
    if not isinstance(value, list) or not value or len(value) > 256:
        raise GuideSourceError("invalid services payload", code="SCHEMA")
    services = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise GuideSourceError("invalid service record", code="SCHEMA")
        identifier = _positive_id(raw.get("id"), "service id")
        if identifier in seen:
            raise GuideSourceError("duplicate service id", code="SCHEMA")
        seen.add(identifier)
        services.append({
            "id": identifier,
            "name": _name(raw.get("name"), "service name"),
            "providers": list(_id_list(raw.get("providers", []), "provider id")),
        })
    return tuple(sorted(services, key=lambda item: item["id"]))


def _normalize_providers(value) -> Tuple[dict, ...]:
    if not isinstance(value, list) or not value or len(value) > 256:
        raise GuideSourceError("invalid providers payload", code="SCHEMA")
    providers = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise GuideSourceError("invalid provider record", code="SCHEMA")
        identifier = _positive_id(raw.get("id"), "provider id")
        if identifier in seen:
            raise GuideSourceError("duplicate provider id", code="SCHEMA")
        seen.add(identifier)
        providers.append({
            "id": identifier,
            "name": _name(raw.get("name"), "provider name"),
            "services": list(_id_list(raw.get("services", []), "service id")),
        })
    return tuple(sorted(providers, key=lambda item: item["id"]))


def _validate_cross_references(
    services: Sequence[dict], providers: Sequence[dict]
) -> None:
    service_ids = {item["id"] for item in services}
    provider_ids = {item["id"] for item in providers}
    service_pairs = set()
    provider_pairs = set()
    for service in services:
        if not set(service["providers"]).issubset(provider_ids):
            raise GuideSourceError("unknown provider reference", code="SCHEMA")
        service_pairs.update(
            (service["id"], provider_id)
            for provider_id in service["providers"]
        )
    for provider in providers:
        if not set(provider["services"]).issubset(service_ids):
            raise GuideSourceError("unknown service reference", code="SCHEMA")
        provider_pairs.update(
            (service_id, provider["id"])
            for service_id in provider["services"]
        )
    if service_pairs != provider_pairs:
        raise GuideSourceError("inconsistent service/provider references", code="SCHEMA")


def _valid_snapshot(value) -> bool:
    if not isinstance(value, dict):
        return False
    observed_at = value.get("observed_at")
    services = value.get("services")
    providers = value.get("providers")
    if (
        not isinstance(observed_at, str)
        or not isinstance(services, list)
        or not isinstance(providers, list)
    ):
        return False
    try:
        parsed = datetime.fromisoformat(observed_at)
        normalized_services = _normalize_services(services)
        normalized_providers = _normalize_providers(providers)
        _validate_cross_references(normalized_services, normalized_providers)
    except (ValueError, GuideSourceError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


async def _fetch_json(path: str, *, limit_bytes: int):
    url = f"{AQUALIDER_BASE_URL}/{path.lstrip('/')}"
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            url,
            is_allowed_url=_allowed_aqualider_url,
            limit_bytes=limit_bytes,
            timeout_seconds=15.0,
            headers=_REQUEST_HEADERS,
            accepted_types=_JSON_TYPES,
        )
    except BoundedFetchError as exc:
        raise GuideSourceError(
            "Aqualider request failed", code=exc.code
        ) from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuideSourceError("Aqualider JSON is invalid", code="JSON") from exc


async def fetch_aqualider_catalog(now: datetime) -> dict:
    """Fetch one compact, internally consistent public catalogue snapshot."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("guide observation time must be timezone-aware")
    services_raw = await _fetch_json("service/", limit_bytes=256 * 1024)
    providers_raw = await _fetch_json("provider/", limit_bytes=128 * 1024)
    services = _normalize_services(services_raw)
    providers = _normalize_providers(providers_raw)
    _validate_cross_references(services, providers)
    return {
        "observed_at": now.isoformat(),
        "services": list(services),
        "providers": list(providers),
    }


def _catalog_fingerprint(snapshot: Optional[dict]):
    if snapshot is None:
        return None
    return snapshot.get("services"), snapshot.get("providers")


def _season_notice_key(local_day: date) -> Optional[str]:
    """Return a notice key only when tomorrow changes the active pool."""

    current = active_pool(local_day)
    next_day = active_pool(local_day + timedelta(days=1))
    if current == next_day:
        return None
    return f"{local_day.year}:{next_day}"


def _season_notice_text(
    notice_key: str,
    chat_id: str,
    messages: Dict[str, int],
) -> str:
    indoor = telegram_message_link(chat_id, messages["pool_indoor"])
    outdoor = telegram_message_link(chat_id, messages["pool_outdoor"])
    swimming = telegram_message_link(chat_id, messages["swimming"])
    if notice_key.endswith(":outdoor"):
        return with_footer(
            "☀️ <b>Открытый муниципальный бассейн — с 16 июня</b>\n\n"
            f"С <b>16 июня</b> начинает работать <a href=\"{outdoor}\"><b>Открытый муниципальный бассейн</b></a>. "
            "Летний сезон продлится до <b>15 сентября</b>.\n\n"
            "Занятия зимнего сезона в крытом бассейне завершаются. "
            f"Информация о летних группах и записи — <a href=\"{swimming}\"><b>🏊 Плавание</b></a>."
        )
    return with_footer(
        "🏊 <b>Крытый бассейн Manel Estiarte — с 16 сентября</b>\n\n"
        f"С <b>16 сентября</b> начинает работать <a href=\"{indoor}\"><b>Крытый бассейн Manel Estiarte</b></a>. "
        "Сезон продлится до <b>15 июня</b>.\n\n"
        "Летние занятия завершаются. "
        f"Информация о занятиях нового сезона и записи — <a href=\"{swimming}\"><b>🏊 Плавание</b></a>."
    )


async def sync_guide(now: datetime) -> str:
    """Refresh the source baseline, reconcile cards, and send a due season note."""

    bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    guide_state = GuideState(Path(
        os.environ.get("GUIDE_STATE_PATH", "").strip()
        or DEFAULT_GUIDE_STATE_PATH
    ))
    pinned_state = PinnedGuideState(Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", "").strip()
        or DEFAULT_PINNED_STATE_PATH
    ))

    source_result = "unchanged"
    with guide_state.exclusive_run():
        state = guide_state.read()
        previous = state.get("aqualider_catalog")
        try:
            current = await fetch_aqualider_catalog(now)
        except GuideSourceError as exc:
            logging.warning(
                "Aqualider catalogue deferred [GUIDE-%s]", exc.diagnostic_code
            )
            source_result = "source-unavailable"
        else:
            if previous is None:
                source_result = "baseline"
            elif _catalog_fingerprint(previous) != _catalog_fingerprint(current):
                source_result = "catalog-changed"
                logging.info(
                    "Aqualider catalogue changed; no public programme alert is "
                    "eligible until batched availability is validated"
                )
            state["aqualider_catalog"] = current
            guide_state.write(state)

        local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
        previous_sporttia = state.get("sporttia_catalog")
        try:
            observed_sporttia = await fetch_sporttia_catalog(now)
        except SporttiaSourceError as exc:
            logging.warning(
                "Sporttia catalogue deferred [GUIDE-%s]",
                exc.diagnostic_code,
            )
        else:
            state["sporttia_catalog"] = merge_sporttia_catalog(
                previous_sporttia, observed_sporttia, local_day
            )
            guide_state.write(state)

        await _check_wifi_source(bot_token, state, guide_state)

        with pinned_state.exclusive_run():
            messages = await publish_pinned_guide(
                chat_id,
                pinned_state,
                lambda message: send_message(
                    bot_token,
                    chat_id,
                    message,
                    disable_notification=True,
                    retry_only_rate_limits=True,
                ),
                lambda message_id, message: edit_message(
                    bot_token, chat_id, message_id, message
                ),
                lambda message_id: pin_chat_message(
                    bot_token,
                    chat_id,
                    message_id,
                    disable_notification=True,
                ),
                sporttia_catalog=state.get("sporttia_catalog"),
                local_day=local_day,
            )

        notice_key = _season_notice_key(local_day)
        if notice_key is not None:
            sent = state.get("season_notice")
            uncertain = state.get("season_notice_uncertain")
            if uncertain == notice_key:
                logging.warning(
                    "Seasonal pool notice remains uncertain: %s", notice_key
                )
            elif not isinstance(sent, dict) or sent.get("key") != notice_key:
                try:
                    notice_id = await send_message(
                        bot_token,
                        chat_id,
                        _season_notice_text(notice_key, chat_id, messages),
                        disable_notification=False,
                        retry_only_rate_limits=True,
                    )
                except TelegramError as exc:
                    if exc.retryable and exc.server_status != 429:
                        state["season_notice_uncertain"] = notice_key
                        guide_state.write(state)
                    raise
                state.pop("season_notice_uncertain", None)
                state["season_notice"] = {
                    "key": notice_key,
                    "message_id": notice_id,
                }
                guide_state.write(state)
                logging.info("Seasonal pool notice published: %s", notice_key)

    return source_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Guardamar linked city guide")
    parser.add_argument("command", nargs="?", choices=("sync",), default="sync")
    parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        result = asyncio.run(sync_guide(datetime.now(GUARDAMAR_TIMEZONE)))
    except (GuideSourceError, StateError, TelegramError, ValueError) as exc:
        print(f"Command failed: {exc}", file=os.sys.stderr)
        raise SystemExit(2) from exc
    logging.info("Guide sync complete: %s", result)


if __name__ == "__main__":
    main()
