"""Orchestrate guarded Morning Digest and beach-root publications."""

import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from .models import BeachNotice, BeachStatus
from .state import PublicationState, StateError
from .telegram import TelegramError

LOGGER = logging.getLogger(__name__)


async def refresh_beach_root(
    now: datetime,
    state: PublicationState,
    status: Optional[BeachStatus],
    notice: Optional[BeachNotice],
    produce_message: Callable[
        [Optional[BeachStatus], Optional[BeachNotice]], Optional[str]
    ],
    deliver_message: Callable[[str], Awaitable[int]],
    edit_root: Callable[[int, str], Awaitable[None]],
) -> tuple[str, Optional[int]]:
    """Create or edit the one daily beach root, retaining prior verified facts."""
    try:
        with state.exclusive_run():
            if state.morning_record(now.date()) is None:
                return "no_morning", None
            old_status, old_notice = state.beach_root_facts(now.date())
            effective_status = status or old_status
            effective_notice = notice or old_notice
            message = produce_message(effective_status, effective_notice)
            if message is None or not message.strip():
                return "no_update", state.beach_message_id(now.date())
            root_id = state.beach_message_id(now.date())
            if root_id is not None:
                try:
                    await edit_root(root_id, message)
                except TelegramError as exc:
                    if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
                        pass
                    elif exc.diagnostic_code == "MESSAGE-NOT-FOUND":
                        root_id = None
                    else:
                        raise
                if root_id is not None:
                    state.mark_beach_message(
                        now.date(), root_id, effective_status, effective_notice
                    )
                    return "refreshed", root_id
            root_id = await deliver_message(message)
            state.mark_beach_message(
                now.date(), root_id, effective_status, effective_notice
            )
            return "created", root_id
    except (StateError, TelegramError) as exc:
        LOGGER.error("FAILURE: beach root refresh failed: %s", exc)
        return "failure", None


async def publish_morning(
    now: datetime,
    state: PublicationState,
    produce_message: Callable[[], Awaitable[str]],
    deliver_message: Callable[[str], Awaitable[int]],
    finalize_publication: Optional[Callable[[], Awaitable[None]]] = None,
) -> str:
    """Send the early digest and finalize its baselines under the same state lock."""
    local_day = now.date()
    try:
        with state.exclusive_run():
            if (
                state.morning_record(local_day) is not None
                or state.is_published(local_day)
            ):
                LOGGER.info("SKIP: morning message already sent for %s", local_day)
                return "duplicate"
            try:
                message = await produce_message()
                if not message.strip():
                    raise ValueError("digest message is empty")
                message_id = await deliver_message(message)
            except Exception as exc:
                LOGGER.error("FAILURE: morning publication failed: %s", exc)
                return "failure"
            state.mark_morning(local_day, message_id, now)
            if finalize_publication is not None:
                try:
                    await finalize_publication()
                except Exception as exc:
                    LOGGER.warning(
                        "Morning post-publication baseline finalization failed: %s",
                        exc,
                    )
            LOGGER.info("SUCCESS: morning message delivered for %s", local_day)
            return "success"
    except StateError as exc:
        LOGGER.error("FAILURE: publication state cannot be trusted: %s", exc)
        return "failure"


async def publish_update(
    now: datetime,
    state: PublicationState,
    beach_status: Optional[BeachStatus],
    final_attempt: bool,
    find_mayor_notice: Callable[[datetime], Awaitable[Optional[BeachNotice]]],
    produce_message: Callable[
        [Optional[BeachStatus], Optional[BeachNotice]], Awaitable[str]
    ],
    deliver_message: Callable[[str], Awaitable[int]],
    delete_message: Callable[[int], Awaitable[None]],
    *,
    force_update: bool = False,
    immutable_morning: bool = False,
) -> str:
    """Legacy two-stage replacement retained for same-day state compatibility."""
    local_day = now.date()
    try:
        with state.exclusive_run():
            record = state.morning_record(local_day)
            if record is None:
                LOGGER.info("SKIP: no morning message exists for %s", local_day)
                return "no_morning"
            update_id = record.get("update_message_id")
            if isinstance(update_id, int):
                if record.get("morning_deleted") is not True:
                    try:
                        await delete_message(record["morning_message_id"])
                    except Exception as exc:
                        LOGGER.error(
                            "FAILURE: old morning message cleanup failed: %s", exc
                        )
                        return "cleanup_failure"
                    state.mark_morning_deleted(local_day)
                return "duplicate"

            beach_ready = beach_status is not None
            if not beach_ready and not final_attempt and not force_update:
                LOGGER.info("WAIT: SafeBeach has no eligible current flag yet")
                return "waiting"

            published_at = datetime.fromisoformat(record["morning_published_at"])
            try:
                mayor_notice = await find_mayor_notice(published_at)
            except Exception as exc:
                LOGGER.warning("Mayor channel update check failed: %s", exc)
                mayor_notice = None
            if not beach_ready and mayor_notice is None and not force_update:
                LOGGER.info("SKIP: no beach update became available")
                return "no_update"

            try:
                message = await produce_message(beach_status, mayor_notice)
                message_id = await deliver_message(message)
            except Exception as exc:
                LOGGER.error("FAILURE: updated digest delivery failed: %s", exc)
                return "failure"

            if immutable_morning:
                if beach_status is not None:
                    state.mark_beach_message(local_day, message_id, beach_status)
                LOGGER.info(
                    "SUCCESS: legacy operational update delivered without "
                    "replacing morning"
                )
                return "success"

            state.mark_update_sent(local_day, message_id, beach_status)
            try:
                await delete_message(record["morning_message_id"])
            except Exception as exc:
                LOGGER.error(
                    "FAILURE: update sent but old message cleanup failed: %s", exc
                )
                return "cleanup_failure"
            state.mark_morning_deleted(local_day)
            LOGGER.info("SUCCESS: morning message replaced for %s", local_day)
            return "success"
    except StateError as exc:
        LOGGER.error("FAILURE: publication state cannot be trusted: %s", exc)
        return "failure"
