"""Orchestrate one guarded Morning Digest publication."""

import logging
from datetime import datetime
from typing import Awaitable, Callable

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
