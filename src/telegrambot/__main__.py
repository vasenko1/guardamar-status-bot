"""Run one Morning Digest publication, preview, or state inspection."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .aemet import AemetError, fetch_morning_digest, fetch_warnings
from .aemet_snapshot import (
    load_snapshot,
    preparation_busy,
    preparation_lock,
    write_snapshot,
)
from .agenda import (
    AgendaError,
    agenda_translation_items,
    refresh_agenda_catalog,
)
from .library_agenda import (
    LibraryAgendaError,
    library_translation_items,
    refresh_library_catalog,
)
from .am_guardamar import (
    AmGuardamarError,
    am_guardamar_translation_items,
    refresh_am_guardamar_catalog,
)
from .airport_schedule import AirportScheduleState, sync_airport_schedule
from .commands import listen_for_preview, parse_allowed_user_ids
from .delivery import publish_morning, refresh_beach_root
from .diagnostics import render_diagnostics
from .electricity import (
    ElectricityError,
    build_explanation_message,
    build_price_message,
    load_or_fetch_prices,
    publish_prices,
)
from .earthquakes import (
    EarthquakeDeliveryUncertain,
    EarthquakeError,
    EarthquakeState,
    fetch_earthquakes,
    monitor_earthquakes,
)
from .environment import (
    CAMS_DATA_URL,
    EnvironmentError,
    fetch_cams,
    fetch_meteosalud,
    fetch_meteosalud_cold,
)
from .environment_updates import (
    build_environment_update,
    build_meteosalud_update,
)
from .mayor import latest_beach_notice
from .municipal_agenda import (
    MunicipalAgendaError,
    municipal_translation_items,
    refresh_municipal_catalog,
)
from .event_translations import prepare_translations
from .hidraqua import HidraquaError, HidraquaState, monitor_once
from .gemini import GeminiError
from .pharmacy import PharmacyError, refresh_pharmacy_catalog
from .morning import _safebeach_is_in_season, produce_message
from .operational_updates import (
    OperationalUpdateState,
    OperationalUpdateStateError,
    build_beach_message,
    build_beach_root_message,
    build_update_message,
    clear_beach_ready,
    finalize_delivery,
    miss_beach_sample,
    observe_beaches,
    observe_warnings,
    scheduled_run,
    seed_beaches,
    seed_warnings,
)
from .pinned import (
    DEFAULT_PINNED_STATE_PATH,
    PinnedGuideState,
    preview_messages as pinned_preview_messages,
    publish_pinned_guide,
)
from .safebeach import (
    SafeBeachError,
    fetch_beach_status,
    is_complete_current_status,
    is_current_status,
)
from .weekend import produce_weekend_message, weekend_dates
from .models import BeachStatus, ColdHealthRisk, HeatHealthRisk
from .state import PublicationState, StateError
from .telegram import (
    TelegramError,
    delete_message,
    edit_message,
    edit_photo_caption,
    edit_photo_media,
    pin_chat_message,
    send_message,
    send_photo,
    send_poll,
)
from .transport_schedules import sync_transport_schedules

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/delivery.json"
DEFAULT_MUNICIPAL_AGENDA_STATE_PATH = "state/municipal_agenda.json"
DEFAULT_AGENDA_STATE_PATH = "state/agenda_guardamar.json"
DEFAULT_LIBRARY_AGENDA_STATE_PATH = "state/library_agenda.json"
DEFAULT_AM_GUARDAMAR_STATE_PATH = "state/am_guardamar.json"
DEFAULT_ELECTRICITY_STATE_PATH = "state/electricity.json"
DEFAULT_ELECTRICITY_SNAPSHOT_PATH = "state/electricity_prices.json"
DEFAULT_EVENT_TRANSLATIONS_PATH = "state/event_translations.json"
DEFAULT_AEMET_SNAPSHOT_PATH = "state/aemet.json"
DEFAULT_OPERATIONAL_UPDATE_STATE_PATH = "state/operational_updates.json"
DEFAULT_WEEKEND_STATE_PATH = "state/weekend.json"
DEFAULT_PHARMACY_STATE_PATH = "state/pharmacy.json"
DEFAULT_EARTHQUAKE_STATE_PATH = "state/earthquakes.json"
DEFAULT_HIDRAQUA_STATE_PATH = "state/hidraqua.json"
DEFAULT_CAMS_CACHE_PATH = "state/cams.json"
CAMS_UPDATE_CHECKPOINTS = frozenset({(10, 10), (10, 25), (10, 40)})


def _beach_ready_for_update(status, now: datetime, final_attempt: bool) -> bool:
    return is_complete_current_status(status, now) or (
        final_attempt and is_current_status(status, now)
    )


def _select_beach_for_update(
    state: PublicationState,
    candidate: Optional[BeachStatus],
    now: datetime,
    final_attempt: bool,
) -> Optional[BeachStatus]:
    """Persist valid partial data and select one whole publishable snapshot."""
    if is_current_status(candidate, now):
        state.remember_beach_candidate(now.date(), candidate, now)
    if is_complete_current_status(candidate, now) or (
        final_attempt and is_current_status(candidate, now)
    ):
        return candidate
    if not final_attempt:
        return None
    stored = state.beach_candidate(now.date(), now)
    if is_current_status(stored, now):
        return stored
    return None


def _cams_cycle_is_current(
    forecast_base: Optional[datetime], now: datetime
) -> bool:
    """Stop late checks once today's UTC CAMS cycle is accepted."""
    return forecast_base is not None and (
        forecast_base.astimezone(timezone.utc).date()
        >= now.astimezone(GUARDAMAR_TIMEZONE).date()
    )


def _cams_update_checkpoint(now: datetime) -> bool:
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    return (local.hour, local.minute) in CAMS_UPDATE_CHECKPOINTS


def _cams_monitor_checkpoint(schedule) -> bool:
    """Use only the first invocation of an existing monitor window."""
    return schedule.beach_phase == 1 or (
        schedule.beach_phase is None and schedule.check_aemet
    )


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _current_morning_message_id(record: dict) -> int:
    """Resolve the live daily digest anchor, including legacy replacements."""
    update_id = record.get("update_message_id")
    if isinstance(update_id, int):
        return update_id
    if record.get("morning_deleted") is True:
        raise StateError("current morning message is unavailable")
    return record["morning_message_id"]


async def _send_operational_update(
    bot_token: str,
    chat_id: str,
    message: str,
    reply_id: Optional[int],
) -> tuple[int, bool]:
    """Prefer the requested anchor; recreate a root only if that anchor is gone."""
    try:
        message_id = await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            reply_to_message_id=reply_id,
        )
        return message_id, reply_id is not None
    except TelegramError as exc:
        if reply_id is None or exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise
        logging.warning("Telegram reply anchor unavailable; sending standalone")
        message_id = await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
        )
        return message_id, False


async def _produce_message(api_key: str, now: datetime) -> str:
    diagnostics = []
    message = await produce_message(
        api_key,
        now,
        os.environ.get("GEMINI_API_KEY", "").strip(),
        Path(
            os.environ.get(
                "MUNICIPAL_AGENDA_STATE_PATH",
                DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
            )
        ),
        agenda_state_path=Path(os.environ.get(
            "AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH
        )),
        library_agenda_state_path=Path(os.environ.get(
            "LIBRARY_AGENDA_STATE_PATH", DEFAULT_LIBRARY_AGENDA_STATE_PATH
        )),
        am_guardamar_state_path=Path(os.environ.get(
            "AM_GUARDAMAR_STATE_PATH", DEFAULT_AM_GUARDAMAR_STATE_PATH
        )),
        diagnostics=diagnostics,
        translation_cache_path=Path(os.environ.get(
            "EVENT_TRANSLATIONS_PATH", DEFAULT_EVENT_TRANSLATIONS_PATH
        )),
        pharmacy_state_path=Path(os.environ.get(
            "PHARMACY_STATE_PATH", DEFAULT_PHARMACY_STATE_PATH
        )),
        cams_data_url=os.environ.get("CAMS_DATA_URL", CAMS_DATA_URL).strip(),
        cams_cache_path=Path(os.environ.get(
            "CAMS_CACHE_PATH", DEFAULT_CAMS_CACHE_PATH
        )),
    )
    return message + render_diagnostics(diagnostics)


async def _refresh_event_catalogs_once(
    now: datetime,
    state: PublicationState,
    municipal_path: Path,
    agenda_path: Path,
    translations_path: Optional[Path] = None,
) -> None:
    """Persist one bounded late event refresh independently of SafeBeach."""
    sources = [
        (
            "municipal",
            lambda: refresh_municipal_catalog(
                os.environ.get("GEMINI_API_KEY", "").strip(),
                now,
                municipal_path,
            ),
        ),
        ("agenda", lambda: refresh_agenda_catalog(now, agenda_path)),
    ]
    refreshed = False
    try:
        with state.exclusive_run():
            if state.morning_record(now.date()) is None:
                return
            for name, refresh in sources:
                if state.event_catalog_sync_attempted(now.date(), name):
                    continue
                try:
                    await refresh()
                    refreshed = True
                except Exception as exc:
                    logging.warning("Late event catalog sync failed for %s: %s", name, exc)
                state.mark_event_catalog_sync_attempted(now.date(), name)
            if (
                refreshed
                and translations_path is not None
                and os.environ.get("GEMINI_API_KEY", "").strip()
            ):
                items = [
                    *await municipal_translation_items(now, municipal_path),
                    *await agenda_translation_items(now, agenda_path),
                ]
                await prepare_translations(
                    os.environ["GEMINI_API_KEY"].strip(),
                    items,
                    translations_path,
                    now,
                )
    except StateError as exc:
        logging.info("Late event catalog sync deferred: %s", exc)
    except (AgendaError, GeminiError, MunicipalAgendaError, ValueError) as exc:
        logging.warning("Late event translation preparation failed: %s", exc)


async def _run_command(command: str, extra: tuple = ()) -> int:
    now = datetime.now(GUARDAMAR_TIMEZONE)
    municipal_path = Path(os.environ.get(
        "MUNICIPAL_AGENDA_STATE_PATH",
        DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
    ))
    agenda_path = Path(os.environ.get(
        "AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH
    ))
    library_path = Path(os.environ.get(
        "LIBRARY_AGENDA_STATE_PATH", DEFAULT_LIBRARY_AGENDA_STATE_PATH
    ))
    am_guardamar_path = Path(os.environ.get(
        "AM_GUARDAMAR_STATE_PATH", DEFAULT_AM_GUARDAMAR_STATE_PATH
    ))
    translations_path = Path(os.environ.get(
        "EVENT_TRANSLATIONS_PATH", DEFAULT_EVENT_TRANSLATIONS_PATH
    ))
    pharmacy_path = Path(os.environ.get(
        "PHARMACY_STATE_PATH", DEFAULT_PHARMACY_STATE_PATH
    ))
    aemet_snapshot_path = Path(os.environ.get(
        "AEMET_SNAPSHOT_PATH", DEFAULT_AEMET_SNAPSHOT_PATH
    ))
    cams_data_url = os.environ.get("CAMS_DATA_URL", CAMS_DATA_URL).strip()
    cams_cache_path = Path(os.environ.get(
        "CAMS_CACHE_PATH", DEFAULT_CAMS_CACHE_PATH
    ))

    async def edit_current_digest(
        state: PublicationState,
        api_key: str,
        bot_token: str,
        chat_id: str,
        *,
        fetch_cams_remote: bool,
    ) -> None:
        """Legacy operator recovery for a day already replaced by an old release."""
        record = state.morning_record(now.date())
        if record is None:
            raise StateError(
                f"no morning message exists for {now.date().isoformat()}"
            )
        if not isinstance(record.get("update_message_id"), int):
            raise ValueError(
                "refresh-current is disabled for immutable Morning Digest days"
            )
        message_id = _current_morning_message_id(record)
        fallback = load_snapshot(aemet_snapshot_path, now)
        refreshed_aemet = []
        heat_level, cold_level, _ = state.morning_environment(now.date())
        refreshed_environment = []
        message = await produce_message(
            api_key,
            now,
            os.environ.get("GEMINI_API_KEY", "").strip(),
            municipal_path,
            agenda_state_path=agenda_path,
            library_agenda_state_path=library_path,
            am_guardamar_state_path=am_guardamar_path,
            translation_cache_path=translations_path,
            aemet_fallback=fallback,
            aemet_observer=refreshed_aemet.append,
            pharmacy_state_path=pharmacy_path,
            cams_data_url=cams_data_url,
            cams_cache_path=cams_cache_path,
            fetch_cams_remote=fetch_cams_remote,
            fetch_meteosalud_data=False,
            heat_health_fallback=(
                HeatHealthRisk(heat_level) if heat_level is not None else None
            ),
            cold_health_fallback=(
                ColdHealthRisk(cold_level) if cold_level is not None else None
            ),
            environment_observer=lambda heat, cold, base: refreshed_environment.append(
                (heat, cold, base)
            ),
        )
        try:
            await edit_message(bot_token, chat_id, message_id, message)
        except TelegramError as exc:
            if exc.diagnostic_code != "MESSAGE-NOT-MODIFIED":
                raise
        if refreshed_aemet:
            write_snapshot(aemet_snapshot_path, refreshed_aemet[-1], now)
        if refreshed_environment:
            heat, cold, base = refreshed_environment[-1]
            state.mark_morning_environment(
                now.date(),
                heat.level if heat is not None else None,
                base,
                cold_level=cold.level if cold is not None else None,
            )
        logging.info("Legacy current digest %s refreshed", message_id)

    async def check_late_environment(
        state: PublicationState,
        bot_token: str,
        chat_id: str,
    ) -> None:
        """Accept valid late source states and notify only material changes."""
        record = state.morning_record(now.date())
        if record is None:
            return
        if isinstance(record.get("update_message_id"), int):
            logging.info("SKIP: legacy replacement day keeps its existing lifecycle")
            return

        heat_level, cold_level, current_base, old_air, old_pollen = (
            state.morning_environment_state(now.date())
        )
        try:
            reply_id = _current_morning_message_id(record)
        except StateError:
            reply_id = None
        effective_base = current_base

        if not _cams_cycle_is_current(current_base, now):
            try:
                new_air, new_pollen, available_base = await fetch_cams(
                    cams_data_url, cams_cache_path, now, remaining_day=True
                )
            except EnvironmentError as exc:
                logging.warning(
                    "CAMS late refresh unavailable; preserving baseline: %s", exc
                )
            else:
                if current_base is None or available_base > current_base:
                    message = build_environment_update(
                        old_air, new_air, old_pollen, new_pollen, now
                    )
                    if message is not None:
                        await _send_operational_update(
                            bot_token, chat_id, message, reply_id
                        )
                    state.mark_cams_environment(
                        now.date(), available_base, new_air, new_pollen
                    )
                    effective_base = available_base
                    logging.info(
                        "CAMS semantic baseline accepted forecast base %s",
                        available_base.isoformat(),
                    )
                else:
                    logging.info(
                        "CAMS refresh pending: accepted forecast base is %s",
                        current_base.isoformat(),
                    )

        previous_heat, previous_cold = heat_level, cold_level
        heat_resolved = cold_resolved = False
        try:
            heat = await fetch_meteosalud(now)
        except EnvironmentError as exc:
            logging.warning("Late Meteosalud heat unavailable: %s", exc)
        else:
            if heat is not None:
                heat_level = heat.level
                heat_resolved = True
        try:
            cold = await fetch_meteosalud_cold(now)
        except EnvironmentError as exc:
            logging.warning("Late Meteosalud cold unavailable: %s", exc)
        else:
            if cold is not None:
                cold_level = cold.level
                cold_resolved = True

        if heat_resolved or cold_resolved:
            message = build_meteosalud_update(
                previous_heat,
                heat_level if heat_resolved else previous_heat,
                previous_cold,
                cold_level if cold_resolved else previous_cold,
                now,
            )
            if message is not None:
                await _send_operational_update(
                    bot_token, chat_id, message, reply_id
                )
            state.mark_morning_environment(
                now.date(),
                heat_level,
                effective_base,
                cold_level=cold_level,
            )

    if command == "monitor-hidraqua":
        state = HidraquaState(Path(os.environ.get(
            "HIDRAQUA_STATE_PATH", DEFAULT_HIDRAQUA_STATE_PATH
        )))
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        publish_current = os.environ.get(
            "HIDRAQUA_PUBLISH_CURRENT_ON_BOOTSTRAP", ""
        ).strip().casefold() == "true"
        with state.exclusive_run():
            sent = await monitor_once(
                state,
                now,
                lambda message: send_message(
                    bot_token, chat_id, message, disable_notification=False,
                    max_attempts=1, retry_only_rate_limits=True,
                ),
                publish_current_on_bootstrap=publish_current,
            )
        logging.info("Hidraqua monitor delivered: %d", sent)
        return 0

    if command == "monitor-updates":
        schedule = scheduled_run(now)
        if schedule.beach_phase is None and not schedule.check_aemet:
            logging.info("SKIP: no operational update check is due")
            return 0
        api_key = _required_environment("AEMET_API_KEY") if schedule.check_aemet else ""
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        publication_state = PublicationState(Path(os.environ.get(
            "MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH
        )))
        if _cams_monitor_checkpoint(schedule):
            try:
                await check_late_environment(publication_state, bot_token, chat_id)
            except (StateError, TelegramError, ValueError) as exc:
                logging.warning(
                    "Late environment check deferred to a later checkpoint: %s", exc
                )

        monitor_state = OperationalUpdateState(Path(os.environ.get(
            "OPERATIONAL_UPDATE_STATE_PATH", DEFAULT_OPERATIONAL_UPDATE_STATE_PATH
        )))
        with monitor_state.exclusive_run():
            value = monitor_state.read(now)
            daily_record = publication_state.morning_record(now.date())
            if daily_record is not None:
                seed_beaches(value, daily_record.get("beach_baseline"))
            if not value.get("warnings_initialized") and daily_record is not None:
                snapshot = load_snapshot(aemet_snapshot_path, now)
                if snapshot is not None and snapshot.warnings_available:
                    seed_warnings(value, snapshot.warnings)

            phase = schedule.beach_phase
            latest_beach = None
            if phase == 1 and value.get("beach_pending") is not None:
                value["beach_pending"] = None
            elif (
                phase == 3
                and isinstance(value.get("beach_pending"), dict)
                and value["beach_pending"].get("stage") == 1
            ):
                miss_beach_sample(value, phase)
            has_ready_update = bool(value.get("beach_ready")) or isinstance(
                value.get("warning_ready"), dict
            )
            should_fetch_beach = (phase == 1 and not has_ready_update) or (
                phase in {2, 3}
                and isinstance(value.get("beach_pending"), dict)
                and value["beach_pending"].get("stage") == phase - 1
            )
            if should_fetch_beach:
                try:
                    beach = await fetch_beach_status(now)
                    if is_current_status(beach, now):
                        latest_beach = beach
                        observe_beaches(value, beach, phase)
                    else:
                        miss_beach_sample(value, phase)
                except SafeBeachError as exc:
                    logging.warning(
                        "Operational SafeBeach check failed: SB-%s",
                        exc.diagnostic_code,
                    )
                    miss_beach_sample(value, phase)

            if schedule.check_aemet and value.get("warning_ready") is None:
                try:
                    observe_warnings(value, await fetch_warnings(api_key, now), now)
                except AemetError as exc:
                    logging.warning(
                        "Operational AEMET check failed: AEMET-%s",
                        exc.diagnostic_code,
                    )

            monitor_state.write(value)
            if value.get("beach_pending") is not None:
                logging.info("WAIT: beach change confirmation is pending")
                return 0

            beach_anchor = publication_state.beach_message_id(now.date())
            if latest_beach is not None:
                root_result, beach_anchor = await refresh_beach_root(
                    now,
                    publication_state,
                    latest_beach,
                    None,
                    build_beach_root_message,
                    lambda message: send_message(
                        bot_token, chat_id, message, disable_notification=False
                    ),
                    lambda message_id, message: edit_message(
                        bot_token, chat_id, message_id, message
                    ),
                )
                if root_result == "failure":
                    return 1

            beach_message = build_beach_message(value, now)
            if beach_message is not None:
                sent_id, anchored = await _send_operational_update(
                    bot_token, chat_id, beach_message, beach_anchor
                )
                clear_beach_ready(value)
                monitor_state.write(value)
                if not anchored:
                    publication_state.set_beach_message_id(now.date(), sent_id)

            message = build_update_message(value, now)
            if message is None:
                logging.info("SKIP: no confirmed AEMET operational changes")
                return 0

            reply_id = None
            if daily_record is not None:
                try:
                    reply_id = _current_morning_message_id(daily_record)
                except StateError:
                    reply_id = None
            await _send_operational_update(bot_token, chat_id, message, reply_id)
            finalize_delivery(value)
            monitor_state.write(value)
            logging.info("SUCCESS: operational AEMET update delivered")
            return 0

    if command == "monitor-earthquakes":
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        earthquake_state = EarthquakeState(Path(os.environ.get(
            "EARTHQUAKE_STATE_PATH", DEFAULT_EARTHQUAKE_STATE_PATH
        )))

        async def publish_earthquake(message: str, message_id: Optional[int]) -> int:
            if message_id is not None:
                try:
                    await edit_message(bot_token, chat_id, message_id, message)
                    return message_id
                except TelegramError as exc:
                    if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
                        return message_id
                    if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
                        raise
            try:
                return await send_message(
                    bot_token,
                    chat_id,
                    message,
                    disable_notification=False,
                    retry_only_rate_limits=True,
                )
            except TelegramError as exc:
                if exc.server_status == 429 or (
                    exc.server_status is not None and exc.server_status < 500
                ):
                    raise
                raise EarthquakeDeliveryUncertain() from exc

        delivered = await monitor_earthquakes(
            now, earthquake_state, fetch_earthquakes, publish_earthquake
        )
        if delivered:
            logging.info("SUCCESS: %d local earthquake alert(s) delivered", delivered)
        else:
            logging.info("SKIP: no new local earthquake")
        return 0

    if command == "sync-municipal-events":
        gemini_key = _required_environment("GEMINI_API_KEY")
        state_path = Path(os.environ.get(
            "MUNICIPAL_AGENDA_STATE_PATH", DEFAULT_MUNICIPAL_AGENDA_STATE_PATH
        ))
        events = await refresh_municipal_catalog(
            gemini_key, datetime.now(GUARDAMAR_TIMEZONE), state_path
        )
        logging.info("Municipal event catalog synchronized: %d facts", len(events))
        return 0

    if command == "sync-library-events":
        events = await refresh_library_catalog(now, library_path)
        logging.info("Library agenda catalog synchronized: %d facts", len(events))
        return 0

    if command == "sync-am-guardamar-events":
        events = await refresh_am_guardamar_catalog(
            _required_environment("GEMINI_API_KEY"), now, am_guardamar_path
        )
        logging.info("AM Guardamar catalog synchronized: %d facts", len(events))
        return 0

    if command == "sync-pharmacy":
        count = await refresh_pharmacy_catalog(now, pharmacy_path)
        logging.info("Pharmacy rota synchronized: %d duty rows", count)
        return 0

    if command == "sync-agenda-events":
        state_path = Path(os.environ.get("AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH))
        events = await refresh_agenda_catalog(
            datetime.now(GUARDAMAR_TIMEZONE), state_path
        )
        logging.info("Agenda Guardamar catalog synchronized: %d facts", len(events))
        return 0

    if command == "poll":
        if len(extra) < 3:
            raise ValueError("poll needs one question and at least two options")
        message_id = await send_poll(
            _required_environment("TELEGRAM_BOT_TOKEN"),
            _required_environment("TELEGRAM_CHAT_ID"),
            extra[0],
            list(extra[1:]),
        )
        logging.info("SUCCESS: poll %s delivered", message_id)
        return 0

    if command in {"weekend", "weekend-preview"}:
        saturday, sunday = weekend_dates(now)
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

        async def prepare_weekend_titles() -> None:
            if not gemini_key:
                return
            items = []
            for day in (saturday, sunday):
                moment = datetime.combine(day, datetime.min.time(), GUARDAMAR_TIMEZONE)
                items.extend(await municipal_translation_items(moment, municipal_path))
                items.extend(await agenda_translation_items(moment, agenda_path))
                items.extend(await library_translation_items(moment, library_path))
                items.extend(await am_guardamar_translation_items(moment, am_guardamar_path))
            try:
                await prepare_translations(gemini_key, items, translations_path, now)
            except (AgendaError, GeminiError, MunicipalAgendaError, ValueError) as exc:
                logging.warning("Weekend title preparation failed: %s", exc)

        if command == "weekend-preview":
            diagnostics = []
            message = await produce_weekend_message(
                now,
                gemini_key,
                municipal_path,
                agenda_state_path=agenda_path,
                library_agenda_state_path=library_path,
                am_guardamar_state_path=am_guardamar_path,
                translation_cache_path=translations_path,
                diagnostics=diagnostics,
            )
            print(
                (message or "No verified weekend events are available")
                + render_diagnostics(diagnostics)
            )
            return 0
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        weekend_state = PublicationState(Path(os.environ.get(
            "WEEKEND_STATE_PATH", DEFAULT_WEEKEND_STATE_PATH
        )))
        with weekend_state.exclusive_run():
            if weekend_state.is_published(saturday):
                logging.info("SKIP: weekend digest already published for %s", saturday)
                return 0
            await prepare_weekend_titles()
            message = await produce_weekend_message(
                now,
                gemini_key,
                municipal_path,
                agenda_state_path=agenda_path,
                library_agenda_state_path=library_path,
                am_guardamar_state_path=am_guardamar_path,
                translation_cache_path=translations_path,
            )
            if message is None:
                logging.info("SKIP: no verified weekend events for %s", saturday)
                return 0
            await send_message(bot_token, chat_id, message, disable_notification=False)
            weekend_state.mark_published(saturday)
            logging.info("SUCCESS: weekend digest delivered for %s", saturday)
            return 0

    if command == "prepare-event-translations":
        gemini_key = _required_environment("GEMINI_API_KEY")
        items = [
            *await municipal_translation_items(now, municipal_path),
            *await agenda_translation_items(now, agenda_path),
            *await library_translation_items(now, library_path),
            *await am_guardamar_translation_items(now, am_guardamar_path),
        ]
        translated = await prepare_translations(
            gemini_key, items, translations_path, now
        )
        logging.info("Event translation cache prepared: %d new titles", translated)
        return 0

    if command == "prepare-aemet":
        api_key = _required_environment("AEMET_API_KEY")
        with preparation_lock(aemet_snapshot_path) as acquired:
            if not acquired:
                return 0
            digest = await fetch_morning_digest(api_key, now)
            await asyncio.to_thread(write_snapshot, aemet_snapshot_path, digest, now)
        logging.info("AEMET morning snapshot prepared")
        return 0

    if command in {
        "electricity",
        "electricity-preview",
        "electricity-update-explanation",
    }:
        target_date = (now + timedelta(days=1)).date()
        esios_key = os.environ.get("ESIOS_API_KEY", "").strip()
        snapshot_path = Path(
            os.environ.get("ELECTRICITY_SNAPSHOT_PATH", "").strip()
            or DEFAULT_ELECTRICITY_SNAPSHOT_PATH
        )
        state_path = Path(
            os.environ.get("ELECTRICITY_STATE_PATH", "").strip()
            or DEFAULT_ELECTRICITY_STATE_PATH
        )
        try:
            paths_conflict = snapshot_path.resolve() == state_path.resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError("electricity state paths could not be resolved") from exc
        if paths_conflict:
            raise ValueError(
                "ELECTRICITY_SNAPSHOT_PATH must differ from ELECTRICITY_STATE_PATH"
            )
        state = PublicationState(state_path)
        if command == "electricity-update-explanation":
            explanation_id = state.electricity_explanation_message_id()
            if explanation_id is None:
                raise ValueError("electricity explanation message ID is unavailable")
            await edit_message(
                _required_environment("TELEGRAM_BOT_TOKEN"),
                _required_environment("TELEGRAM_CHAT_ID"),
                explanation_id,
                build_explanation_message(),
            )
            logging.info("Electricity explanation updated")
            return 0
        if command == "electricity-preview":
            with state.exclusive_run():
                data = await load_or_fetch_prices(esios_key, target_date, snapshot_path)
            print(build_price_message(data))
            print("\n--- Ответ на сообщение ---\n")
            print(build_explanation_message())
            return 0
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        result = await publish_prices(
            target_date,
            state,
            lambda: load_or_fetch_prices(esios_key, target_date, snapshot_path),
            lambda message, reply_id: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
                reply_to_message_id=reply_id,
            ),
            lambda message: send_message(
                bot_token, chat_id, message, disable_notification=False
            ),
        )
        logging.info("Electricity publication: %s", result)
        return 0

    if command == "pinned-preview":
        print("\n\n====================\n\n".join(pinned_preview_messages()))
        return 0

    if command == "pinned-send-preview":
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        allowed_user_ids = parse_allowed_user_ids(
            _required_environment("TELEGRAM_ALLOWED_USER_IDS")
        )
        if len(allowed_user_ids) != 1:
            raise ValueError("pinned preview requires exactly one allowed user ID")
        private_chat_id = str(next(iter(allowed_user_ids)))
        for message in pinned_preview_messages():
            await send_message(
                bot_token, private_chat_id, message, disable_notification=True
            )
        logging.info("Pinned guide preview sent to the private operator")
        return 0

    if command == "pinned-publish":
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        state = PinnedGuideState(Path(os.environ.get(
            "PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH
        )))
        with state.exclusive_run():
            payload = await asyncio.to_thread(state.read_payload, chat_id)
            if any(value.get("media") is True for value in payload["lines"].values()):
                raise ValueError("media guide must be repaired with sync-transport")
            messages = await publish_pinned_guide(
                chat_id,
                state,
                lambda message: send_message(
                    bot_token, chat_id, message, disable_notification=True
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
            )
        logging.info("Pinned guide published with %d linked messages", len(messages))
        return 0

    if command == "sync-transport":
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        state = PinnedGuideState(Path(os.environ.get(
            "PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH
        )))
        with state.exclusive_run():
            existing = await asyncio.to_thread(state.read_payload, chat_id)
            await publish_pinned_guide(
                chat_id,
                state,
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
                skip_keys=("airport",) if "airport" in existing["messages"] else (),
            )
            await sync_airport_schedule(
                datetime.now(GUARDAMAR_TIMEZONE),
                chat_id,
                state,
                AirportScheduleState(state.path.with_name("airport_schedule.json")),
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
            )
            messages = await sync_transport_schedules(
                datetime.now(GUARDAMAR_TIMEZONE),
                chat_id,
                state,
                lambda path, caption: send_photo(
                    bot_token, chat_id, path, caption, disable_notification=True
                ),
                lambda message_id, path, caption: edit_photo_media(
                    bot_token, chat_id, message_id, path, caption
                ),
                lambda message_id, caption: edit_photo_caption(
                    bot_token, chat_id, message_id, caption
                ),
                lambda message_id, message: edit_message(
                    bot_token, chat_id, message_id, message
                ),
                lambda message_id: delete_message(bot_token, chat_id, message_id),
            )
        logging.info("Transport schedules synchronized with %d linked messages", len(messages))
        return 0

    api_key = _required_environment("AEMET_API_KEY")
    if command == "preview":
        print(await _produce_message(api_key, datetime.now(GUARDAMAR_TIMEZONE)))
        return 0

    bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
    if command == "listen":
        allowed_user_ids = parse_allowed_user_ids(
            _required_environment("TELEGRAM_ALLOWED_USER_IDS")
        )
        await listen_for_preview(
            bot_token,
            allowed_user_ids,
            lambda moment: _produce_message(api_key, moment),
            pinned_preview_messages,
        )
        return 0

    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    state_path = Path(os.environ.get("MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH))
    state = PublicationState(state_path)

    if command == "refresh-current":
        await edit_current_digest(
            state,
            api_key,
            bot_token,
            chat_id,
            fetch_cams_remote=True,
        )
        return 0

    if command in {"run", "morning"}:
        morning_aemet = []
        morning_environment_detail = []
        prepared = load_snapshot(
            aemet_snapshot_path, now, max_age=timedelta(minutes=60)
        )
        fetch_live = prepared is None and not preparation_busy(aemet_snapshot_path)
        result = await publish_morning(
            now,
            state,
            lambda: produce_message(
                api_key,
                now,
                os.environ.get("GEMINI_API_KEY", "").strip(),
                Path(os.environ.get(
                    "MUNICIPAL_AGENDA_STATE_PATH",
                    DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
                )),
                agenda_state_path=Path(os.environ.get(
                    "AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH
                )),
                library_agenda_state_path=library_path,
                am_guardamar_state_path=am_guardamar_path,
                collect_beach=False,
                translation_cache_path=translations_path,
                aemet_digest=prepared,
                fetch_aemet=fetch_live,
                aemet_observer=morning_aemet.append,
                pharmacy_state_path=pharmacy_path,
                cams_data_url=cams_data_url,
                cams_cache_path=cams_cache_path,
                environment_detail_observer=lambda heat, cold, air, pollen, base: (
                    morning_environment_detail.append((heat, cold, air, pollen, base))
                ),
            ),
            lambda message: send_message(
                bot_token, chat_id, message, disable_notification=False
            ),
        )
        if result == "success" and morning_aemet:
            write_snapshot(aemet_snapshot_path, morning_aemet[-1], now)
        if result == "success" and morning_environment_detail:
            heat, cold, air, pollen, base = morning_environment_detail[-1]
            state.mark_morning_environment(
                now.date(),
                heat.level if heat is not None else None,
                base,
                cold_level=cold.level if cold is not None else None,
            )
            if base is not None:
                state.mark_cams_environment(now.date(), base, air, pollen)
        return 0 if result in {"success", "duplicate"} else 1

    existing = state.morning_record(now.date())
    if existing is None:
        logging.info("SKIP: no morning message exists for %s", now.date())
        return 0

    if isinstance(existing.get("update_message_id"), int):
        await _refresh_event_catalogs_once(
            now, state, municipal_path, agenda_path, translations_path
        )
        logging.info("SKIP: legacy replacement day retained until local rollover")
        return 0

    if _cams_update_checkpoint(now):
        try:
            await check_late_environment(state, bot_token, chat_id)
        except (StateError, TelegramError, ValueError) as exc:
            logging.warning("Late environment checkpoint deferred: %s", exc)

    await _refresh_event_catalogs_once(
        now, state, municipal_path, agenda_path, translations_path
    )

    if not _safebeach_is_in_season(now):
        logging.info("SKIP: SafeBeach update phase is out of season")
        return 0
    final_attempt = (now.hour, now.minute) >= (10, 40)
    beach = None
    try:
        candidate = await fetch_beach_status(now)
        beach = _select_beach_for_update(state, candidate, now, final_attempt)
    except SafeBeachError as exc:
        logging.warning("SafeBeach update check failed: SB-%s", exc.diagnostic_code)
        if final_attempt:
            beach = _select_beach_for_update(state, None, now, final_attempt=True)

    if beach is None and not final_attempt:
        logging.info("WAIT: SafeBeach has no eligible current flag yet")
        return 0

    published_at = datetime.fromisoformat(existing["morning_published_at"])
    try:
        notice = await latest_beach_notice(now, published_at)
    except Exception as exc:
        logging.warning("Mayor channel update check failed: %s", exc)
        notice = None
    if beach is None and notice is None:
        logging.info("SKIP: no beach root facts became available")
        return 0

    result, _ = await refresh_beach_root(
        now,
        state,
        beach,
        notice,
        build_beach_root_message,
        lambda message: send_message(
            bot_token, chat_id, message, disable_notification=False
        ),
        lambda message_id, message: edit_message(
            bot_token, chat_id, message_id, message
        ),
    )
    return 0 if result in {"created", "refreshed", "no_update", "no_morning"} else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Guardamar Morning Digest")
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "run", "morning", "update", "refresh-current", "preview",
            "status", "listen",
            "electricity", "electricity-preview",
            "electricity-update-explanation",
            "pinned-preview", "pinned-send-preview", "pinned-publish",
            "sync-transport",
            "sync-municipal-events",
            "sync-agenda-events",
            "sync-library-events",
            "sync-am-guardamar-events",
            "sync-pharmacy",
            "prepare-event-translations",
            "prepare-aemet",
            "monitor-updates",
            "monitor-earthquakes",
            "monitor-hidraqua",
            "weekend", "weekend-preview",
            "poll",
        ),
        default="run",
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="poll only: one question followed by two to ten options",
    )
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if arguments.command == "status":
        state_path = Path(os.environ.get("MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH))
        try:
            successful_date = PublicationState(state_path).last_successful_date()
        except StateError as exc:
            print(f"State error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            successful_date.isoformat()
            if successful_date else "No successful publication recorded"
        )
        return

    try:
        exit_code = asyncio.run(_run_command(arguments.command, tuple(arguments.extra)))
    except ElectricityError as exc:
        print(
            f"Command failed [ESIOS-{exc.diagnostic_code}]: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except (
        AemetError,
        AgendaError,
        EarthquakeError,
        LibraryAgendaError,
        AmGuardamarError,
        HidraquaError,
        MunicipalAgendaError,
        PharmacyError,
        TelegramError,
        StateError,
        OperationalUpdateStateError,
        ValueError,
    ) as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        return
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
