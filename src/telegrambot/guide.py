"""One-shot synchronization for the linked city guide.

The first vertical slice keeps pool facility facts deterministic and stores only
a small normalized SimplyBook catalogue baseline. Registration availability is
deliberately not inferred until the provider's batched availability contract
has been validated on the production runtime.
"""

import argparse
import asyncio
import fcntl
import hashlib
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
from .bathing_water import (
    BathingWaterSourceError,
    bathing_water_report_fingerprint,
    fetch_bathing_water_report,
    fetch_bathing_water_snapshot,
    valid_bathing_water_report_snapshot,
    valid_bathing_water_snapshot,
)
from .branding import with_footer
from .chess_school import (
    ChessSchoolSourceError,
    fetch_chess_school_snapshot,
    valid_chess_school_snapshot,
)
from .dinamizacion import (
    DinamizacionSourceError,
    discover_dinamizacion_campaign,
    fetch_dinamizacion_snapshot,
    refresh_dinamizacion_snapshot,
    valid_dinamizacion_snapshot,
)
from .literary_group import (
    LiteraryGroupSourceError,
    fetch_literary_group_snapshot,
    valid_literary_group_snapshot,
)
from .music_school import (
    MusicSchoolSourceError,
    fetch_music_school_catalog,
    merge_music_school_catalog,
    valid_music_school_snapshot,
)
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
from .wifi import (
    WIFI_VERIFIED_ASSET_URL,
    WifiSourceError,
    allowed_wifi_asset_url,
    fetch_current_wifi_asset,
    fetch_wifi_snapshot,
    valid_wifi_snapshot,
    wifi_baseline_snapshot,
    wifi_snapshot_fingerprint,
)
from .telegram import (
    TelegramError,
    edit_message,
    is_ambiguous_send_failure,
    pin_chat_message,
    send_message,
)

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_GUIDE_STATE_PATH = "state/guide.json"
AQUALIDER_ORIGIN = "https://aqualidernatacion.simplybook.it"
AQUALIDER_BASE_URL = f"{AQUALIDER_ORIGIN}/v2"
ORA_INFO_URL = "https://oraguardamar.gruposetex.es/tarifas-y-horarios"
_GUIDE_STATE_VERSION = 1
_JSON_TYPES = frozenset({"application/json"})
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "guardamar-status-bot/1.0",
}
_ORA_REQUEST_HEADERS = {
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
        bathing_water = value.get("bathing_water_snapshot")
        if (
            bathing_water is not None
            and not valid_bathing_water_snapshot(bathing_water)
        ):
            raise StateError(
                "guide state has an invalid bathing-water snapshot"
            )
        bathing_water_report = value.get("bathing_water_report_snapshot")
        if (
            bathing_water_report is not None
            and not valid_bathing_water_report_snapshot(bathing_water_report)
        ):
            raise StateError(
                "guide state has an invalid bathing-water report snapshot"
            )
        for field in (
            "bathing_water_pending_notice",
            "bathing_water_notice_uncertain",
        ):
            marker = value.get(field)
            if marker is not None and (
                not isinstance(marker, str) or not marker.strip()
            ):
                raise StateError(f"guide state has an invalid {field}")
        bathing_water_notice = value.get("bathing_water_notice")
        if bathing_water_notice is not None and (
            not isinstance(bathing_water_notice, dict)
            or not isinstance(bathing_water_notice.get("key"), str)
            or not bathing_water_notice["key"].strip()
            or not isinstance(bathing_water_notice.get("message_id"), int)
            or isinstance(bathing_water_notice.get("message_id"), bool)
            or bathing_water_notice["message_id"] <= 0
        ):
            raise StateError("guide state has an invalid bathing-water notice")
        wifi_snapshot = value.get("wifi_snapshot")
        if wifi_snapshot is not None and not valid_wifi_snapshot(wifi_snapshot):
            raise StateError("guide state has an invalid Wi-Fi snapshot")
        sporttia = value.get("sporttia_catalog")
        if sporttia is not None and not valid_sporttia_snapshot(sporttia):
            raise StateError("guide state has an invalid Sporttia snapshot")
        music_school = value.get("music_school_catalog")
        if music_school is not None and not valid_music_school_snapshot(music_school):
            raise StateError("guide state has an invalid music-school snapshot")
        chess_school = value.get("chess_school_snapshot")
        if chess_school is not None and not valid_chess_school_snapshot(chess_school):
            raise StateError("guide state has an invalid chess-school snapshot")
        literary_group = value.get("literary_group_snapshot")
        if literary_group is not None and not valid_literary_group_snapshot(literary_group):
            raise StateError("guide state has an invalid literary-group snapshot")
        dinamizacion = value.get("dinamizacion_snapshot")
        if dinamizacion is not None and not valid_dinamizacion_snapshot(dinamizacion):
            raise StateError("guide state has an invalid Dinamización snapshot")
        music_attempt_day = value.get("music_school_last_attempt_day")
        if music_attempt_day is not None:
            if not isinstance(music_attempt_day, str):
                raise StateError("guide state has an invalid music-school attempt day")
            try:
                date.fromisoformat(music_attempt_day)
            except ValueError as exc:
                raise StateError(
                    "guide state has an invalid music-school attempt day"
                ) from exc
        sporttia_attempt_day = value.get("sporttia_last_attempt_day")
        if sporttia_attempt_day is not None:
            if not isinstance(sporttia_attempt_day, str):
                raise StateError("guide state has an invalid Sporttia attempt day")
            try:
                date.fromisoformat(sporttia_attempt_day)
            except ValueError as exc:
                raise StateError(
                    "guide state has an invalid Sporttia attempt day"
                ) from exc
        for field, label in (
            ("bathing_water_last_attempt_day", "bathing-water"),
            ("wifi_last_attempt_day", "Wi-Fi"),
            ("chess_school_last_attempt_day", "chess-school"),
            ("literary_group_last_attempt_day", "literary-group"),
            ("dinamizacion_discovery_last_attempt_day", "Dinamización discovery"),
            ("dinamizacion_form_last_attempt_day", "Dinamización form"),
        ):
            attempt_day = value.get(field)
            if attempt_day is None:
                continue
            if not isinstance(attempt_day, str):
                raise StateError(f"guide state has an invalid {label} attempt day")
            try:
                date.fromisoformat(attempt_day)
            except ValueError as exc:
                raise StateError(
                    f"guide state has an invalid {label} attempt day"
                ) from exc
        successful_day = value.get("last_successful_sync_day")
        if successful_day is not None:
            if not isinstance(successful_day, str):
                raise StateError("guide state has an invalid successful sync day")
            try:
                date.fromisoformat(successful_day)
            except ValueError as exc:
                raise StateError(
                    "guide state has an invalid successful sync day"
                ) from exc
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
        parking_notice = value.get("parking_notice")
        if parking_notice is not None and (
            not isinstance(parking_notice, dict)
            or not isinstance(parking_notice.get("key"), str)
            or not isinstance(parking_notice.get("message_id"), int)
            or parking_notice["message_id"] <= 0
        ):
            raise StateError("guide state has an invalid parking notice")
        parking_uncertain = value.get("parking_notice_uncertain")
        if parking_uncertain is not None and not isinstance(parking_uncertain, str):
            raise StateError("guide state has an invalid uncertain parking notice")
        wifi_alerted = value.get("wifi_last_alerted_asset_url")
        if wifi_alerted is not None and (
            not isinstance(wifi_alerted, str) or not wifi_alerted.strip()
        ):
            raise StateError("guide state has an invalid legacy Wi-Fi source alert")
        for field in (
            "wifi_observed_asset_url",
            "wifi_pending_asset_url",
            "wifi_notice_uncertain_asset_url",
        ):
            item = value.get(field)
            if item is not None and (
                not isinstance(item, str) or not allowed_wifi_asset_url(item)
            ):
                raise StateError(f"guide state has an invalid {field}")
        wifi_notice = value.get("wifi_notice")
        if wifi_notice is not None and (
            not isinstance(wifi_notice, dict)
            or not allowed_wifi_asset_url(wifi_notice.get("asset_url", ""))
            or not isinstance(wifi_notice.get("message_id"), int)
            or isinstance(wifi_notice.get("message_id"), bool)
            or wifi_notice["message_id"] <= 0
        ):
            raise StateError("guide state has an invalid Wi-Fi notice")
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


def active_parking(local_day: date) -> str:
    """Return the deterministic seasonal Zona Azul mode for a local date."""

    paid_start = date(local_day.year, 6, 15)
    paid_end = date(local_day.year, 9, 15)
    return "paid" if paid_start <= local_day <= paid_end else "free"


def _attempt_due(
    last_attempt_day: Optional[str],
    local_day: date,
    interval_days: int,
) -> bool:
    """Return whether a low-frequency source is due inside the daily guide run."""

    if last_attempt_day is None:
        return True
    previous = date.fromisoformat(last_attempt_day)
    return (local_day - previous).days >= interval_days


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


def _allowed_ora_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "oraguardamar.gruposetex.es"
        and port in {None, 443}
        and parsed.path.rstrip("/") == "/tarifas-y-horarios"
        and parsed.username is None
        and parsed.password is None
    )


class _VisibleTextParser(HTMLParser):
    """Collect normalized visible text from a small HTML source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized:
            self.parts.append(normalized)

    def text(self) -> str:
        return " ".join(self.parts).casefold()


def _ora_schedule_matches(payload: bytes) -> bool:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    parser = _VisibleTextParser()
    parser.feed(source)
    value = parser.text()
    required = (
        "15 de junio",
        "15 de septiembre",
        "lunes a viernes",
        "sábados",
        "domingos",
        "festivos",
        "10:00",
        "20:00",
    )
    return all(marker in value for marker in required)


async def verify_current_ora_schedule() -> None:
    """Fail closed unless the live ORA page still confirms the reviewed season."""

    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            ORA_INFO_URL,
            is_allowed_url=_allowed_ora_url,
            limit_bytes=512 * 1024,
            timeout_seconds=15.0,
            headers=_ORA_REQUEST_HEADERS,
            accepted_types=_HTML_TYPES,
        )
    except BoundedFetchError as exc:
        raise GuideSourceError(
            "ORA schedule request failed", code=f"ORA-{exc.code}"
        ) from exc
    if not _ora_schedule_matches(payload):
        raise GuideSourceError(
            "ORA schedule no longer matches the reviewed season",
            code="ORA-SCHEDULE",
        )


async def _refresh_wifi_source(
    now: datetime,
    state: dict,
    guide_state: GuideState,
) -> None:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date().isoformat()
    if state.get("wifi_last_attempt_day") == local_day:
        return
    state["wifi_last_attempt_day"] = local_day
    guide_state.write(state)
    try:
        current = await fetch_current_wifi_asset()
    except WifiSourceError as exc:
        logging.warning("Wi-Fi source check deferred [GUIDE-%s]", exc.diagnostic_code)
        return

    previous_asset = state.get("wifi_observed_asset_url") or WIFI_VERIFIED_ASSET_URL
    if current == previous_asset:
        if state.get("wifi_observed_asset_url") is None:
            state["wifi_observed_asset_url"] = current
            state.pop("wifi_last_alerted_asset_url", None)
            guide_state.write(state)
        return

    previous_snapshot = state.get("wifi_snapshot")
    if previous_snapshot is None:
        previous_snapshot = wifi_baseline_snapshot(now)
    if current == WIFI_VERIFIED_ASSET_URL:
        current_snapshot = wifi_baseline_snapshot(now)
    else:
        try:
            current_snapshot = await fetch_wifi_snapshot(current, now)
        except WifiSourceError as exc:
            logging.warning("Wi-Fi document deferred [GUIDE-%s]", exc.diagnostic_code)
            return

    changed = (
        wifi_snapshot_fingerprint(previous_snapshot)
        != wifi_snapshot_fingerprint(current_snapshot)
    )
    if current == WIFI_VERIFIED_ASSET_URL:
        state.pop("wifi_snapshot", None)
    else:
        state["wifi_snapshot"] = current_snapshot
    state["wifi_observed_asset_url"] = current
    state.pop("wifi_last_alerted_asset_url", None)
    if changed:
        # Notice delivery state belongs to the previous semantic snapshot, not
        # permanently to an asset URL. A later semantic change may legitimately
        # reuse an older municipal PDF URL.
        state.pop("wifi_notice", None)
        state.pop("wifi_notice_uncertain_asset_url", None)
        state["wifi_pending_asset_url"] = current
    guide_state.write(state)


_BATHING_RATING_ORDER = ("excellent", "good", "sufficient", "insufficient")
_BATHING_QUALITY_RU = {
    "excellent": "отличное",
    "good": "хорошее",
    "sufficient": "удовлетворительное",
    "insufficient": "недостаточное",
}
_BATHING_APPEARANCE_RU = {
    "excellent": "отлично",
    "good": "хорошо",
    "sufficient": "удовлетворительно",
    "insufficient": "неудовлетворительно",
}
_RU_MONTHS_GENITIVE = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _bathing_water_notice_key(snapshot: dict) -> str:
    fingerprint = repr(bathing_water_report_fingerprint(snapshot)).encode("utf-8")
    digest = hashlib.sha256(fingerprint).hexdigest()[:16]
    return f'{snapshot["report_start"]}:{snapshot["report_end"]}:{digest}'


def _bathing_water_period_text(snapshot: dict) -> str:
    start = date.fromisoformat(snapshot["report_start"])
    end = date.fromisoformat(snapshot["report_end"])
    if start.year == end.year and start.month == end.month:
        return (
            f"{start.day}–{end.day} {_RU_MONTHS_GENITIVE[end.month]} "
            f"{end.year}"
        )
    if start.year == end.year:
        return (
            f"{start.day} {_RU_MONTHS_GENITIVE[start.month]} – "
            f"{end.day} {_RU_MONTHS_GENITIVE[end.month]} {end.year}"
        )
    return (
        f"{start.day} {_RU_MONTHS_GENITIVE[start.month]} {start.year} – "
        f"{end.day} {_RU_MONTHS_GENITIVE[end.month]} {end.year}"
    )


def _append_bathing_names(lines: list, names: list, *, prefix: str) -> None:
    """Append a phone-width beach list with at most two names per line."""

    for offset in range(0, len(names), 2):
        chunk = ", ".join(html.escape(name) for name in names[offset:offset + 2])
        lines.append(f"{prefix if offset == 0 else '   '}{chunk}")


def _bathing_water_notice_text(snapshot: dict) -> str:
    beaches = snapshot["beaches"]
    lines = [
        "🧪 <b>Качество воды на пляжах</b>",
        f"🗓 {_bathing_water_period_text(snapshot)}",
        "",
        "<b>Анализ воды</b>",
    ]

    water_groups = {
        rating: [
            beach["name"] for beach in beaches
            if beach["water_analysis"] == rating
        ]
        for rating in _BATHING_RATING_ORDER
    }
    active_water_ratings = [
        rating for rating in _BATHING_RATING_ORDER
        if water_groups[rating]
    ]
    if len(active_water_ratings) == 1:
        rating = active_water_ratings[0]
        marker = "✅ " if rating == "excellent" else ""
        lines.append(
            f"{marker}{_BATHING_APPEARANCE_RU[rating].capitalize()} "
            f"— все {len(beaches)} пляжей"
        )
    else:
        for rating in _BATHING_RATING_ORDER:
            names = water_groups[rating]
            if not names:
                continue
            lines.append(f"• {_BATHING_APPEARANCE_RU[rating].capitalize()}:")
            _append_bathing_names(lines, names, prefix="   ")

    visual_exceptions = []
    for field, label in (
        ("water_appearance", "Вода"),
        ("sand_appearance", "Песок"),
    ):
        for rating in _BATHING_RATING_ORDER[1:]:
            names = [
                beach["name"] for beach in beaches
                if beach[field] == rating
            ]
            if names:
                visual_exceptions.append((label, rating, names))

    lines.extend(["", "👁 <b>Внешний осмотр</b>"])
    if not visual_exceptions:
        lines.append("✅ Вода и песок — отлично на всех пляжах")
    else:
        for label, rating, names in visual_exceptions:
            lines.append(
                f"• {label} — {_BATHING_APPEARANCE_RU[rating]}:"
            )
            _append_bathing_names(lines, names, prefix="   ")
        lines.append("Остальные визуальные оценки — отлично.")

    lines.extend([
        "",
        "🏛 Источник: Ayuntamiento de Guardamar del Segura",
    ])
    return with_footer("\n".join(lines))


async def _refresh_bathing_water_source(
    now: datetime,
    state: dict,
    guide_state: GuideState,
) -> None:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date().isoformat()
    if state.get("bathing_water_last_attempt_day") == local_day:
        return
    state["bathing_water_last_attempt_day"] = local_day
    guide_state.write(state)
    try:
        programme = await fetch_bathing_water_snapshot(now)
    except BathingWaterSourceError as exc:
        logging.warning(
            "Bathing-water programme deferred [GUIDE-%s]",
            exc.diagnostic_code,
        )
        return

    state["bathing_water_snapshot"] = programme
    guide_state.write(state)
    report_url = programme.get("latest_report_url")
    if not isinstance(report_url, str):
        return

    previous = state.get("bathing_water_report_snapshot")
    expected_identity = (
        programme.get("latest_report_start"),
        programme.get("latest_report_end"),
        report_url,
    )
    previous_identity = None
    if isinstance(previous, dict):
        previous_identity = (
            previous.get("report_start"),
            previous.get("report_end"),
            previous.get("report_url"),
        )
    if previous_identity == expected_identity:
        return

    try:
        current = await fetch_bathing_water_report(programme, now)
    except BathingWaterSourceError as exc:
        logging.warning(
            "Bathing-water weekly report deferred [GUIDE-%s]",
            exc.diagnostic_code,
        )
        return

    changed = (
        previous is not None
        and bathing_water_report_fingerprint(previous)
        != bathing_water_report_fingerprint(current)
    )
    state["bathing_water_report_snapshot"] = current
    if changed:
        state["bathing_water_pending_notice"] = _bathing_water_notice_key(current)
        state.pop("bathing_water_notice_uncertain", None)
    guide_state.write(state)


async def _publish_bathing_water_pending_notice(
    bot_token: str,
    chat_id: str,
    state: dict,
    guide_state: GuideState,
) -> None:
    pending = state.get("bathing_water_pending_notice")
    if not isinstance(pending, str):
        return
    report = state.get("bathing_water_report_snapshot")
    if (
        not isinstance(report, dict)
        or not valid_bathing_water_report_snapshot(report)
        or _bathing_water_notice_key(report) != pending
    ):
        raise StateError("guide state has mismatched bathing-water notice state")
    if state.get("bathing_water_notice_uncertain") == pending:
        logging.warning(
            "Bathing-water public notice remains uncertain: %s", pending
        )
        return
    sent = state.get("bathing_water_notice")
    if isinstance(sent, dict) and sent.get("key") == pending:
        state.pop("bathing_water_pending_notice", None)
        guide_state.write(state)
        return

    state["bathing_water_notice_uncertain"] = pending
    guide_state.write(state)
    try:
        message_id = await send_message(
            bot_token,
            chat_id,
            _bathing_water_notice_text(report),
            disable_notification=False,
            retry_only_rate_limits=True,
        )
    except TelegramError as exc:
        if is_ambiguous_send_failure(exc):
            logging.warning(
                "Bathing-water public notice delivery is uncertain "
                "[TELEGRAM-%s]",
                exc.diagnostic_code,
            )
            return
        state.pop("bathing_water_notice_uncertain", None)
        guide_state.write(state)
        raise
    state.pop("bathing_water_notice_uncertain", None)
    state.pop("bathing_water_pending_notice", None)
    state["bathing_water_notice"] = {
        "key": pending,
        "message_id": message_id,
    }
    guide_state.write(state)
    logging.info("Bathing-water weekly quality notice published")


def _wifi_notice_text(chat_id: str, messages: Dict[str, int]) -> str:
    wifi_link = telegram_message_link(chat_id, messages["wifi"])
    return with_footer(
        "📶 <b>Обновилась информация о муниципальном Wi-Fi</b>\n\n"
        f'<a href="{html.escape(wifi_link, quote=True)}"><b>Актуальные точки, сети и пароли</b></a> — в обновлённой карточке.'
    )


async def _publish_wifi_pending_notice(
    bot_token: str,
    chat_id: str,
    messages: Dict[str, int],
    state: dict,
    guide_state: GuideState,
) -> None:
    pending = state.get("wifi_pending_asset_url")
    if not isinstance(pending, str):
        return
    uncertain = state.get("wifi_notice_uncertain_asset_url")
    if uncertain == pending:
        logging.warning("Wi-Fi public notice remains uncertain for %s", pending)
        return
    notice = state.get("wifi_notice")
    if isinstance(notice, dict) and notice.get("asset_url") == pending:
        state.pop("wifi_pending_asset_url", None)
        guide_state.write(state)
        return

    state["wifi_notice_uncertain_asset_url"] = pending
    guide_state.write(state)
    try:
        message_id = await send_message(
            bot_token,
            chat_id,
            _wifi_notice_text(chat_id, messages),
            disable_notification=False,
            retry_only_rate_limits=True,
        )
    except TelegramError as exc:
        if is_ambiguous_send_failure(exc):
            logging.warning(
                "Wi-Fi public notice delivery is uncertain [TELEGRAM-%s]",
                exc.diagnostic_code,
            )
            return
        state.pop("wifi_notice_uncertain_asset_url", None)
        guide_state.write(state)
        raise
    state.pop("wifi_notice_uncertain_asset_url", None)
    state.pop("wifi_pending_asset_url", None)
    state["wifi_notice"] = {"asset_url": pending, "message_id": message_id}
    guide_state.write(state)
    logging.info("Wi-Fi public change notice published")


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


def _parking_notice_key(local_day: date) -> Optional[str]:
    """Return a notice key only when tomorrow changes seasonal ORA mode."""

    current = active_parking(local_day)
    next_day = active_parking(local_day + timedelta(days=1))
    if current == next_day:
        return None
    return f"{local_day.year}:{next_day}"


def _parking_notice_text(notice_key: str) -> str:
    """Render a self-contained ORA mode transition without a guide card."""

    if notice_key.endswith(":paid"):
        return with_footer(
            "🅿️ <b>Zona Azul — с завтрашнего дня платно</b>\n\n"
            "С <b>15 июня</b> в Гуардамаре действует платный режим Zona Azul.\n"
            "<b>Ежедневно · 10:00–20:00</b>.\n\n"
            "Платный режим действует до <b>15 сентября включительно</b>."
        )
    return with_footer(
        "🅿️ <b>Zona Azul — с завтрашнего дня бесплатно</b>\n\n"
        "С <b>16 сентября</b> сезонная Zona Azul в Гуардамаре бесплатна."
    )


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
        state.pop("last_successful_sync_day", None)
        guide_state.write(state)
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

        local_now = now.astimezone(GUARDAMAR_TIMEZONE)
        local_day = local_now.date()

        await _refresh_bathing_water_source(now, state, guide_state)

        previous_sporttia = state.get("sporttia_catalog")
        if state.get("sporttia_last_attempt_day") != local_day.isoformat():
            # Mark before network I/O so manual reruns cannot hammer the source
            # after a timeout, parse failure, or interrupted observation.
            state["sporttia_last_attempt_day"] = local_day.isoformat()
            guide_state.write(state)
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

        previous_music = state.get("music_school_catalog")
        if state.get("music_school_last_attempt_day") != local_day.isoformat():
            state["music_school_last_attempt_day"] = local_day.isoformat()
            guide_state.write(state)
            try:
                observed_music = await fetch_music_school_catalog(now)
            except MusicSchoolSourceError as exc:
                logging.warning(
                    "Music-school catalogue deferred [GUIDE-%s]",
                    exc.diagnostic_code,
                )
            else:
                state["music_school_catalog"] = merge_music_school_catalog(
                    previous_music, observed_music
                )
                guide_state.write(state)

        if _attempt_due(
            state.get("chess_school_last_attempt_day"),
            local_day,
            7,
        ):
            state["chess_school_last_attempt_day"] = local_day.isoformat()
            guide_state.write(state)
            try:
                state["chess_school_snapshot"] = await fetch_chess_school_snapshot(now)
            except ChessSchoolSourceError as exc:
                logging.warning(
                    "Chess-school source deferred [GUIDE-%s]",
                    exc.diagnostic_code,
                )
            else:
                guide_state.write(state)

        if _attempt_due(
            state.get("literary_group_last_attempt_day"),
            local_day,
            7,
        ):
            state["literary_group_last_attempt_day"] = local_day.isoformat()
            guide_state.write(state)
            try:
                state["literary_group_snapshot"] = (
                    await fetch_literary_group_snapshot(now)
                )
            except LiteraryGroupSourceError as exc:
                logging.warning(
                    "Literary-group source deferred [GUIDE-%s]",
                    exc.diagnostic_code,
                )
            else:
                guide_state.write(state)

        if (
            state.get("dinamizacion_discovery_last_attempt_day")
            != local_day.isoformat()
        ):
            state["dinamizacion_discovery_last_attempt_day"] = (
                local_day.isoformat()
            )
            guide_state.write(state)
            try:
                discovered = await discover_dinamizacion_campaign()
            except DinamizacionSourceError as exc:
                logging.warning(
                    "Dinamización discovery deferred [GUIDE-%s]",
                    exc.diagnostic_code,
                )
                discovered = None

            previous_program = state.get("dinamizacion_snapshot")
            campaign_changed = (
                discovered is not None
                and (
                    previous_program is None
                    or previous_program.get("campaign_url") != discovered[0]
                )
            )

            if campaign_changed:
                campaign_url, season = discovered
                state["dinamizacion_form_last_attempt_day"] = local_day.isoformat()
                guide_state.write(state)
                try:
                    observed_program = await fetch_dinamizacion_snapshot(
                        campaign_url,
                        season,
                        now,
                    )
                except DinamizacionSourceError as exc:
                    logging.warning(
                        "Dinamización detail/form deferred [GUIDE-%s]",
                        exc.diagnostic_code,
                    )
                else:
                    state["dinamizacion_snapshot"] = observed_program
                    guide_state.write(state)
            elif (
                previous_program is not None
                and state.get("dinamizacion_form_last_attempt_day")
                != local_day.isoformat()
            ):
                state["dinamizacion_form_last_attempt_day"] = local_day.isoformat()
                guide_state.write(state)
                try:
                    observed_program = await refresh_dinamizacion_snapshot(
                        previous_program,
                        now,
                    )
                except DinamizacionSourceError as exc:
                    logging.warning(
                        "Dinamización form refresh failed [GUIDE-%s]; "
                        "retrying through campaign detail",
                        exc.diagnostic_code,
                    )
                    try:
                        observed_program = await fetch_dinamizacion_snapshot(
                            previous_program["campaign_url"],
                            previous_program["season"],
                            now,
                        )
                    except DinamizacionSourceError as recovery_exc:
                        logging.warning(
                            "Dinamización detail recovery deferred [GUIDE-%s]",
                            recovery_exc.diagnostic_code,
                        )
                        observed_program = None
                if observed_program is not None:
                    state["dinamizacion_snapshot"] = observed_program
                    guide_state.write(state)

        await _refresh_wifi_source(now, state, guide_state)

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
                music_school_catalog=state.get("music_school_catalog"),
                chess_school_snapshot=state.get("chess_school_snapshot"),
                literary_group_snapshot=state.get("literary_group_snapshot"),
                dinamizacion_snapshot=state.get("dinamizacion_snapshot"),
                wifi_snapshot=state.get("wifi_snapshot"),
                local_day=local_day,
            )

        state["last_successful_sync_day"] = local_day.isoformat()
        guide_state.write(state)

        await _publish_wifi_pending_notice(
            bot_token, chat_id, messages, state, guide_state
        )
        await _publish_bathing_water_pending_notice(
            bot_token, chat_id, state, guide_state
        )

        parking_notice_key = _parking_notice_key(local_day)
        if parking_notice_key is not None and local_now.hour >= 18:
            sent_parking = state.get("parking_notice")
            uncertain_parking = state.get("parking_notice_uncertain")
            if uncertain_parking == parking_notice_key:
                logging.warning(
                    "Seasonal parking notice remains uncertain: %s",
                    parking_notice_key,
                )
            elif (
                not isinstance(sent_parking, dict)
                or sent_parking.get("key") != parking_notice_key
            ):
                try:
                    await verify_current_ora_schedule()
                except GuideSourceError as exc:
                    logging.warning(
                        "Seasonal parking notice deferred [GUIDE-%s]",
                        exc.diagnostic_code,
                    )
                else:
                    try:
                        parking_notice_id = await send_message(
                            bot_token,
                            chat_id,
                            _parking_notice_text(parking_notice_key),
                            disable_notification=False,
                            retry_only_rate_limits=True,
                        )
                    except TelegramError as exc:
                        if is_ambiguous_send_failure(exc):
                            state["parking_notice_uncertain"] = parking_notice_key
                            guide_state.write(state)
                        raise
                    state.pop("parking_notice_uncertain", None)
                    state["parking_notice"] = {
                        "key": parking_notice_key,
                        "message_id": parking_notice_id,
                    }
                    guide_state.write(state)
                    logging.info(
                        "Seasonal parking notice published: %s",
                        parking_notice_key,
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
                    if is_ambiguous_send_failure(exc):
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
