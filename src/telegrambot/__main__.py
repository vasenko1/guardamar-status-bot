"""Run one Morning Digest publication, preview, or state inspection."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .aemet import AemetError, fetch_morning_digest
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
from .morning import _safebeach_is_in_season, produce_message
from .safebeach import (
    SafeBeachError,
    fetch_beach_status,
    is_complete_current_status,
    is_current_status,
)
from .state import PublicationState, StateError
from .telegram import TelegramError, delete_message, edit_message, send_message

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/delivery.json"
DEFAULT_MUNICIPAL_AGENDA_STATE_PATH = "state/municipal_agenda.json"
DEFAULT_AGENDA_STATE_PATH = "state/agenda_guardamar.json"
DEFAULT_ELECTRICITY_STATE_PATH = "state/electricity.json"
DEFAULT_ELECTRICITY_SNAPSHOT_PATH = "state/electricity_prices.json"
DEFAULT_EVENT_TRANSLATIONS_PATH = "state/event_translations.json"
DEFAULT_AEMET_SNAPSHOT_PATH = "state/aemet.json"


def _beach_ready_for_update(status, now: datetime, final_attempt: bool) -> bool:
    return is_complete_current_status(status, now) or (
        final_attempt and is_current_status(status, now)
    )


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
    )
    return message + render_diagnostics(diagnostics)


async def _run_command(command: str) -> int:
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
    aemet_snapshot_path = Path(os.environ.get(
        "AEMET_SNAPSHOT_PATH", DEFAULT_AEMET_SNAPSHOT_PATH
    ))
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
        message = await produce_message(
            api_key,
            now,
            os.environ.get("GEMINI_API_KEY", "").strip(),
            municipal_path,
            agenda_state_path=agenda_path,
            translation_cache_path=translations_path,
            aemet_fallback=fallback,
        )
        await edit_message(bot_token, chat_id, message_id, message)
        logging.info("Current morning message %s refreshed", message_id)
        return 0
    if command in {"run", "morning"}:
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
            ),
            lambda message: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
            ),
        )
        return 0 if result in {"success", "duplicate"} else 1

    if not _safebeach_is_in_season(now):
        logging.info("SKIP: SafeBeach update phase is out of season")
        return 0

    async def find_notice(since: datetime):
        return await latest_beach_notice(now, since)

    async def produce_update(status, notice):
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        refreshes = await asyncio.gather(
            refresh_agenda_catalog(now, agenda_path),
            refresh_municipal_catalog(gemini_key, now, municipal_path),
            return_exceptions=True,
        )
        for source, result in zip(
            ("Agenda Guardamar", "Agenda municipal"), refreshes
        ):
            if isinstance(result, BaseException):
                logging.warning(
                    "Late catalog refresh failed for %s: %s",
                    source,
                    result,
                )
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

    final_attempt = (now.hour, now.minute) >= (10, 40)
    beach = None
    try:
        candidate = await fetch_beach_status()
        if _beach_ready_for_update(candidate, now, final_attempt):
            beach = candidate
    except SafeBeachError as exc:
        logging.warning(
            "SafeBeach update check failed: SB-%s",
            exc.diagnostic_code,
        )
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
            "sync-municipal-events",
            "sync-agenda-events",
            "prepare-event-translations",
            "prepare-aemet",
        ),
        default="run",
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
        exit_code = asyncio.run(_run_command(arguments.command))
    except ElectricityError as exc:
        print(
            f"Command failed [ESIOS-{exc.diagnostic_code}]: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except (
        AemetError, AgendaError, MunicipalAgendaError, TelegramError,
        StateError, ValueError
    ) as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        return
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
