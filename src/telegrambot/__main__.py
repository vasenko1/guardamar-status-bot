"""Run one Morning Digest publication, preview, or state inspection."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
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
from .commands import listen_for_preview, parse_allowed_user_ids
from .delivery import publish_morning, publish_update
from .diagnostics import render_diagnostics
from .electricity import (
    ElectricityError,
    build_explanation_message,
    build_price_message,
    load_or_fetch_prices,
    publish_prices,
)
from .mayor import latest_beach_notice
from .municipal_agenda import (
    MunicipalAgendaError,
    municipal_translation_items,
    refresh_municipal_catalog,
)
from .event_translations import prepare_translations
from .gemini import GeminiError
from .pharmacy import PharmacyError, refresh_pharmacy_catalog
from .morning import _safebeach_is_in_season, produce_message
from .operational_updates import (
    OperationalUpdateState,
    OperationalUpdateStateError,
    build_update_message,
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
from .models import BeachStatus
from .state import PublicationState, StateError
from .telegram import (
    TelegramError,
    delete_message,
    edit_message,
    pin_chat_message,
    send_message,
    send_poll,
)

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/delivery.json"
DEFAULT_MUNICIPAL_AGENDA_STATE_PATH = "state/municipal_agenda.json"
DEFAULT_AGENDA_STATE_PATH = "state/agenda_guardamar.json"
DEFAULT_ELECTRICITY_STATE_PATH = "state/electricity.json"
DEFAULT_ELECTRICITY_SNAPSHOT_PATH = "state/electricity_prices.json"
DEFAULT_EVENT_TRANSLATIONS_PATH = "state/event_translations.json"
DEFAULT_AEMET_SNAPSHOT_PATH = "state/aemet.json"
DEFAULT_OPERATIONAL_UPDATE_STATE_PATH = "state/operational_updates.json"
DEFAULT_WEEKEND_STATE_PATH = "state/weekend.json"
DEFAULT_PHARMACY_STATE_PATH = "state/pharmacy.json"


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


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _current_morning_message_id(record: dict) -> int:
    """Resolve the one live digest message from a validated daily record."""

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
) -> None:
    """Prefer the full digest anchor and fall back only if it is gone."""

    try:
        await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            reply_to_message_id=reply_id,
        )
    except TelegramError as exc:
        if reply_id is None or exc.server_status != 400:
            raise
        logging.warning(
            "Daily digest reply anchor unavailable; sending standalone"
        )
        await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
        )


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
        diagnostics=diagnostics,
        translation_cache_path=Path(os.environ.get(
            "EVENT_TRANSLATIONS_PATH", DEFAULT_EVENT_TRANSLATIONS_PATH
        )),
        pharmacy_state_path=Path(os.environ.get(
            "PHARMACY_STATE_PATH", DEFAULT_PHARMACY_STATE_PATH
        )),
    )
    return message + render_diagnostics(diagnostics)


async def _refresh_event_catalogs_once(
    now: datetime,
    state: PublicationState,
    municipal_path: Path,
    agenda_path: Path,
) -> None:
    """Persist one bounded late event refresh independently of SafeBeach."""

    sources = (
        (
            "municipal",
            lambda: refresh_municipal_catalog(
                os.environ.get("GEMINI_API_KEY", "").strip(),
                now,
                municipal_path,
            ),
        ),
        ("agenda", lambda: refresh_agenda_catalog(now, agenda_path)),
    )
    try:
        with state.exclusive_run():
            if state.morning_record(now.date()) is None:
                return
            for name, refresh in sources:
                if state.event_catalog_sync_attempted(now.date(), name):
                    continue
                try:
                    await refresh()
                except Exception as exc:
                    logging.warning(
                        "Late event catalog sync failed for %s: %s",
                        name,
                        exc,
                    )
                state.mark_event_catalog_sync_attempted(now.date(), name)
    except StateError as exc:
        logging.info("Late event catalog sync deferred: %s", exc)


async def _run_command(command: str, extra: tuple = ()) -> int:
    now = datetime.now(GUARDAMAR_TIMEZONE)
    municipal_path = Path(os.environ.get(
        "MUNICIPAL_AGENDA_STATE_PATH",
        DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
    ))
    agenda_path = Path(os.environ.get(
        "AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH
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
    if command == "monitor-updates":
        schedule = scheduled_run(now)
        if schedule.beach_phase is None and not schedule.check_aemet:
            logging.info("SKIP: no operational update check is due")
            return 0
        api_key = (
            _required_environment("AEMET_API_KEY")
            if schedule.check_aemet else ""
        )
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        publication_state = PublicationState(Path(os.environ.get(
            "MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH
        )))
        monitor_state = OperationalUpdateState(Path(os.environ.get(
            "OPERATIONAL_UPDATE_STATE_PATH",
            DEFAULT_OPERATIONAL_UPDATE_STATE_PATH,
        )))
        with monitor_state.exclusive_run():
            value = monitor_state.read(now)
            daily_record = publication_state.morning_record(now.date())
            if daily_record is not None:
                seed_beaches(value, daily_record.get("beach_baseline"))
            if (
                not value.get("warnings_initialized")
                and daily_record is not None
            ):
                snapshot = load_snapshot(aemet_snapshot_path, now)
                if snapshot is not None and snapshot.warnings_available:
                    seed_warnings(value, snapshot.warnings)

            phase = schedule.beach_phase
            if phase == 1 and value.get("beach_pending") is not None:
                # A previous two-hour window can no longer be confirmed.
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
                    observe_warnings(
                        value,
                        await fetch_warnings(api_key, now),
                        now,
                    )
                except AemetError as exc:
                    logging.warning(
                        "Operational AEMET check failed: AEMET-%s",
                        exc.diagnostic_code,
                    )

            monitor_state.write(value)
            if value.get("beach_pending") is not None:
                logging.info("WAIT: beach change confirmation is pending")
                return 0
            message = build_update_message(value, now)
            if message is None:
                logging.info("SKIP: no confirmed operational changes")
                return 0

            reply_id = None
            if daily_record is not None:
                try:
                    reply_id = _current_morning_message_id(daily_record)
                except StateError:
                    reply_id = None
            await _send_operational_update(
                bot_token, chat_id, message, reply_id
            )
            finalize_delivery(value)
            monitor_state.write(value)
            logging.info("SUCCESS: operational update delivered")
            return 0
    if command == "sync-municipal-events":
        gemini_key = _required_environment("GEMINI_API_KEY")
        state_path = Path(os.environ.get(
            "MUNICIPAL_AGENDA_STATE_PATH",
            DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
        ))
        events = await refresh_municipal_catalog(
            gemini_key,
            datetime.now(GUARDAMAR_TIMEZONE),
            state_path,
        )
        logging.info(
            "Municipal event catalog synchronized: %d facts", len(events)
        )
        return 0

    if command == "sync-pharmacy":
        count = await refresh_pharmacy_catalog(now, pharmacy_path)
        logging.info("Pharmacy rota synchronized: %d duty rows", count)
        return 0

    if command == "sync-agenda-events":
        state_path = Path(os.environ.get(
            "AGENDA_STATE_PATH", DEFAULT_AGENDA_STATE_PATH
        ))
        events = await refresh_agenda_catalog(
            datetime.now(GUARDAMAR_TIMEZONE), state_path
        )
        logging.info(
            "Agenda Guardamar catalog synchronized: %d facts", len(events)
        )
        return 0

    if command == "poll":
        if len(extra) < 3:
            raise ValueError(
                "poll needs one question and at least two options"
            )
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
                moment = datetime.combine(
                    day, datetime.min.time(), GUARDAMAR_TIMEZONE
                )
                items.extend(
                    await municipal_translation_items(moment, municipal_path)
                )
                items.extend(
                    await agenda_translation_items(moment, agenda_path)
                )
            try:
                await prepare_translations(
                    gemini_key, items, translations_path, now
                )
            except (
                AgendaError,
                GeminiError,
                MunicipalAgendaError,
                ValueError,
            ) as exc:
                logging.warning(
                    "Weekend title preparation failed: %s", exc
                )

        if command == "weekend-preview":
            # Preview is read-only: it reads the existing translation cache
            # and never fills it, matching the morning preview contract.
            message = await produce_weekend_message(
                now,
                gemini_key,
                municipal_path,
                agenda_state_path=agenda_path,
                translation_cache_path=translations_path,
            )
            print(message or "No verified weekend events are available")
            return 0
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        weekend_state = PublicationState(Path(os.environ.get(
            "WEEKEND_STATE_PATH", DEFAULT_WEEKEND_STATE_PATH
        )))
        with weekend_state.exclusive_run():
            if weekend_state.is_published(saturday):
                logging.info(
                    "SKIP: weekend digest already published for %s", saturday
                )
                return 0
            await prepare_weekend_titles()
            message = await produce_weekend_message(
                now,
                gemini_key,
                municipal_path,
                agenda_state_path=agenda_path,
                translation_cache_path=translations_path,
            )
            if message is None:
                logging.info(
                    "SKIP: no verified weekend events for %s", saturday
                )
                return 0
            await send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
            )
            weekend_state.mark_published(saturday)
            logging.info(
                "SUCCESS: weekend digest delivered for %s", saturday
            )
            return 0

    if command == "prepare-event-translations":
        gemini_key = _required_environment("GEMINI_API_KEY")
        items = [
            *await municipal_translation_items(now, municipal_path),
            *await agenda_translation_items(now, agenda_path),
        ]
        translated = await prepare_translations(
            gemini_key, items, translations_path, now
        )
        logging.info(
            "Event translation cache prepared: %d new titles", translated
        )
        return 0

    if command == "prepare-aemet":
        api_key = _required_environment("AEMET_API_KEY")
        with preparation_lock(aemet_snapshot_path) as acquired:
            if not acquired:
                return 0
            digest = await fetch_morning_digest(api_key, now)
            await asyncio.to_thread(
                write_snapshot, aemet_snapshot_path, digest, now
            )
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
            paths_conflict = (
                snapshot_path.resolve() == state_path.resolve()
            )
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                "electricity state paths could not be resolved"
            ) from exc
        if paths_conflict:
            raise ValueError(
                "ELECTRICITY_SNAPSHOT_PATH must differ from "
                "ELECTRICITY_STATE_PATH"
            )
        state = PublicationState(state_path)
        if command == "electricity-update-explanation":
            explanation_id = state.electricity_explanation_message_id()
            if explanation_id is None:
                raise ValueError(
                    "electricity explanation message ID is unavailable"
                )
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
                data = await load_or_fetch_prices(
                    esios_key, target_date, snapshot_path
                )
            print(build_price_message(data))
            print("\n--- Ответ на сообщение ---\n")
            print(build_explanation_message())
            return 0
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        chat_id = _required_environment("TELEGRAM_CHAT_ID")
        result = await publish_prices(
            target_date,
            state,
            lambda: load_or_fetch_prices(
                esios_key, target_date, snapshot_path
            ),
            lambda message, reply_id: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
                reply_to_message_id=reply_id,
            ),
            lambda message: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
            ),
        )
        logging.info("Electricity publication: %s", result)
        return 0

    if command == "pinned-preview":
        print("\n\n====================\n\n".join(
            pinned_preview_messages()
        ))
        return 0

    if command == "pinned-send-preview":
        bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
        allowed_user_ids = parse_allowed_user_ids(
            _required_environment("TELEGRAM_ALLOWED_USER_IDS")
        )
        if len(allowed_user_ids) != 1:
            raise ValueError(
                "pinned preview requires exactly one allowed user ID"
            )
        private_chat_id = str(next(iter(allowed_user_ids)))
        for message in pinned_preview_messages():
            await send_message(
                bot_token,
                private_chat_id,
                message,
                disable_notification=True,
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
            messages = await publish_pinned_guide(
                chat_id,
                state,
                lambda message: send_message(
                    bot_token,
                    chat_id,
                    message,
                    disable_notification=True,
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
        logging.info(
            "Pinned guide published with %d linked messages", len(messages)
        )
        return 0

    api_key = _required_environment("AEMET_API_KEY")
    if command == "preview":
        print(
            await _produce_message(
                api_key, datetime.now(GUARDAMAR_TIMEZONE)
            )
        )
        return 0

    bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
    if command == "listen":
        allowed_user_ids = parse_allowed_user_ids(
            _required_environment("TELEGRAM_ALLOWED_USER_IDS")
        )
        await listen_for_preview(
            bot_token,
            allowed_user_ids,
            lambda now: _produce_message(api_key, now),
            pinned_preview_messages,
        )
        return 0

    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    state_path = Path(
        os.environ.get("MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH)
    )
    state = PublicationState(state_path)
    if command == "refresh-current":
        record = state.morning_record(now.date())
        if record is None:
            raise StateError(
                f"no morning message exists for {now.date().isoformat()}"
            )
        message_id = _current_morning_message_id(record)
        fallback = load_snapshot(aemet_snapshot_path, now)
        refreshed_aemet = []
        message = await produce_message(
            api_key,
            now,
            os.environ.get("GEMINI_API_KEY", "").strip(),
            municipal_path,
            agenda_state_path=agenda_path,
            translation_cache_path=translations_path,
            aemet_fallback=fallback,
            aemet_observer=refreshed_aemet.append,
            pharmacy_state_path=pharmacy_path,
        )
        await edit_message(bot_token, chat_id, message_id, message)
        if refreshed_aemet:
            write_snapshot(aemet_snapshot_path, refreshed_aemet[-1], now)
        logging.info("Current morning message %s refreshed", message_id)
        return 0
    if command in {"run", "morning"}:
        morning_aemet = []
        prepared = load_snapshot(
            aemet_snapshot_path, now, max_age=timedelta(minutes=60)
        )
        fetch_live = prepared is None and not preparation_busy(
            aemet_snapshot_path
        )
        result = await publish_morning(
            now,
            state,
            lambda: produce_message(
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
                collect_beach=False,
                translation_cache_path=translations_path,
                aemet_digest=prepared,
                fetch_aemet=fetch_live,
                aemet_observer=morning_aemet.append,
                pharmacy_state_path=pharmacy_path,
            ),
            lambda message: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
            ),
        )
        if result == "success" and morning_aemet:
            write_snapshot(aemet_snapshot_path, morning_aemet[-1], now)
        return 0 if result in {"success", "duplicate"} else 1

    async def find_notice(since: datetime):
        return await latest_beach_notice(now, since)

    update_aemet = []

    async def produce_update(status, notice):
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_key:
            try:
                items = [
                    *await municipal_translation_items(now, municipal_path),
                    *await agenda_translation_items(now, agenda_path),
                ]
                await prepare_translations(
                    gemini_key, items, translations_path, now
                )
            except (
                AgendaError,
                GeminiError,
                MunicipalAgendaError,
                ValueError,
            ) as exc:
                logging.warning(
                    "Late event translation preparation failed: %s", exc
                )
        fallback = load_snapshot(aemet_snapshot_path, now)
        return await produce_message(
            api_key,
            now,
            os.environ.get("GEMINI_API_KEY", "").strip(),
            municipal_path,
            agenda_state_path=agenda_path,
            collect_beach=False,
            beach_status=status,
            beach_notice=notice,
            translation_cache_path=translations_path,
            aemet_fallback=fallback,
            aemet_observer=update_aemet.append,
            pharmacy_state_path=pharmacy_path,
        )

    async def deliver_update(message: str) -> int:
        return await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
        )

    async def delete_old(message_id: int) -> None:
        await delete_message(bot_token, chat_id, message_id)

    existing = state.morning_record(now.date())
    if existing is None:
        logging.info("SKIP: no morning message exists for %s", now.date())
        return 0
    if isinstance(existing.get("update_message_id"), int):
        await _refresh_event_catalogs_once(
            now, state, municipal_path, agenda_path
        )
        result = await publish_update(
            now,
            state,
            None,
            False,
            find_notice,
            produce_update,
            deliver_update,
            delete_old,
        )
        return 0 if result == "duplicate" else 1

    in_beach_season = _safebeach_is_in_season(now)
    final_attempt = (now.hour, now.minute) >= (10, 40)
    beach = None
    if in_beach_season:
        try:
            candidate = await fetch_beach_status(now)
            beach = _select_beach_for_update(
                state, candidate, now, final_attempt
            )
        except SafeBeachError as exc:
            logging.warning(
                "SafeBeach update check failed: SB-%s",
                exc.diagnostic_code,
            )
            if final_attempt:
                beach = _select_beach_for_update(
                    state, None, now, final_attempt=True
                )
    await _refresh_event_catalogs_once(
        now, state, municipal_path, agenda_path
    )
    if not in_beach_season:
        logging.info("SKIP: SafeBeach update phase is out of season")
        return 0
    result = await publish_update(
        now,
        state,
        beach,
        final_attempt,
        find_notice,
        produce_update,
        deliver_update,
        delete_old,
    )
    if result in {"success", "cleanup_failure"} and update_aemet:
        write_snapshot(aemet_snapshot_path, update_aemet[-1], now)
    return 0 if result in {
        "success",
        "duplicate",
        "waiting",
        "no_update",
        "no_morning",
    } else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guardamar Morning Digest"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "run", "morning", "update", "refresh-current", "preview",
            "status", "listen",
            "electricity", "electricity-preview",
            "electricity-update-explanation",
            "pinned-preview", "pinned-send-preview", "pinned-publish",
            "sync-municipal-events",
            "sync-agenda-events",
            "sync-pharmacy",
            "prepare-event-translations",
            "prepare-aemet",
            "monitor-updates",
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
        state_path = Path(
            os.environ.get(
                "MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH
            )
        )
        try:
            successful_date = PublicationState(
                state_path
            ).last_successful_date()
        except StateError as exc:
            print(f"State error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            successful_date.isoformat()
            if successful_date
            else "No successful publication recorded"
        )
        return

    try:
        exit_code = asyncio.run(
            _run_command(arguments.command, tuple(arguments.extra))
        )
    except ElectricityError as exc:
        print(
            f"Command failed [ESIOS-{exc.diagnostic_code}]: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except (
        AemetError, AgendaError, MunicipalAgendaError, PharmacyError,
        TelegramError, StateError, OperationalUpdateStateError, ValueError
    ) as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        return
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
