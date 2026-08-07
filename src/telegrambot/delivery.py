"""Orchestrate one guarded Morning Digest publication."""

import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from .models import BeachNotice, BeachStatus

from .state import PublicationState, StateError

LOGGER = logging.getLogger(__name__)


async def attempt_delivery(
    now: datetime,
    state: PublicationState,
    produce_message: Callable[[], Awaitable[str]],
    deliver_message: Callable[[str], Awaitable[None]],
) -> str:
    """Publish once unless this local date already has a confirmed success."""

    local_day = now.date()
    try:
        with state.exclusive_run():
            if state.is_published(local_day):
                LOGGER.info(
                    "SKIP: Morning Digest already published for %s",
                    local_day,
                )
                return "duplicate"

            try:
                message = await produce_message()
                if not message.strip():
                    raise ValueError("digest message is empty")
            except Exception as exc:
                LOGGER.error(
                    "SKIP: Morning Digest could not be produced safely: %s",
                    exc,
                )
                return "skipped"

            try:
                await deliver_message(message)
            except Exception as exc:
                LOGGER.error(
                    "FAILURE: Telegram delivery failed: %s",
                    exc,
                )
                return "failure"

            state.mark_published(local_day)
            LOGGER.info(
                "SUCCESS: Morning Digest delivered for %s",
                local_day,
            )
            return "success"
    except StateError as exc:
        LOGGER.error("FAILURE: delivery state cannot be trusted: %s", exc)
        return "failure"


async def publish_morning(
    now: datetime,
    state: PublicationState,
    produce_message: Callable[[], Awaitable[str]],
    deliver_message: Callable[[str], Awaitable[int]],
) -> str:
    """Send the early full digest and retain its Telegram identifier."""

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
            state.mark_morning(local_day, message_id, now, message)
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
) -> str:
    """Replace the early message only after a confirmed beach update."""

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
                            "FAILURE: old morning message cleanup failed: %s",
                            exc,
                        )
                        return "cleanup_failure"
                    state.mark_morning_deleted(local_day)
                return "duplicate"

            beach_ready = beach_status is not None
            if not beach_ready and not final_attempt:
                LOGGER.info("WAIT: SafeBeach has no eligible current flag yet")
                return "waiting"

            published_at = datetime.fromisoformat(
                record["morning_published_at"]
            )
            try:
                mayor_notice = await find_mayor_notice(published_at)
            except Exception as exc:
                LOGGER.warning("Mayor channel update check failed: %s", exc)
                mayor_notice = None
            if not beach_ready and mayor_notice is None:
                LOGGER.info("SKIP: no beach update became available")
                return "no_update"

            try:
                message = await produce_message(beach_status, mayor_notice)
                message_id = await deliver_message(message)
            except Exception as exc:
                LOGGER.error("FAILURE: updated digest delivery failed: %s", exc)
                return "failure"

            state.mark_update_sent(local_day, message_id, beach_status)
            try:
                await delete_message(record["morning_message_id"])
            except Exception as exc:
                LOGGER.error(
                    "FAILURE: update sent but old message cleanup failed: %s",
                    exc,
                )
                return "cleanup_failure"
            state.mark_morning_deleted(local_day)
            LOGGER.info("SUCCESS: morning message replaced for %s", local_day)
            return "success"
    except StateError as exc:
        LOGGER.error("FAILURE: publication state cannot be trusted: %s", exc)
        return "failure"
