"""Prepare FACV/Pesca titles in the existing shared event translation cache."""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .event_translations import prepare_translations
from .facv import DEFAULT_STATE_PATH as FACV_DEFAULT_STATE_PATH
from .facv import FacvSourceError, facv_translation_items
from .pesca_cv import DEFAULT_STATE_PATH as PESCA_DEFAULT_STATE_PATH
from .pesca_cv import PescaCvSourceError, pesca_cv_translation_items

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_TRANSLATIONS_PATH = "state/event_translations.json"


async def prepare_federation_event_translations(now: datetime) -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    items = []
    facv_path = Path(os.environ.get("FACV_EVENTS_STATE_PATH", FACV_DEFAULT_STATE_PATH))
    pesca_path = Path(
        os.environ.get("PESCA_CV_EVENTS_STATE_PATH", PESCA_DEFAULT_STATE_PATH)
    )
    try:
        items.extend(await facv_translation_items(now, facv_path))
    except FacvSourceError as exc:
        logging.warning("FACV translations skipped: %s", exc)
    try:
        items.extend(await pesca_cv_translation_items(now, pesca_path))
    except PescaCvSourceError as exc:
        logging.warning("Pesca CV translations skipped: %s", exc)

    if not items:
        return 0
    cache_path = Path(
        os.environ.get("EVENT_TRANSLATIONS_PATH", DEFAULT_TRANSLATIONS_PATH)
    )
    return await prepare_translations(api_key, items, cache_path, now)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        translated = asyncio.run(
            prepare_federation_event_translations(datetime.now(GUARDAMAR_TIMEZONE))
        )
    except ValueError as exc:
        print(f"Command failed: {exc}", file=os.sys.stderr)
        raise SystemExit(2) from exc
    logging.info("Federation event translation cache prepared: %d new titles", translated)


if __name__ == "__main__":
    main()
