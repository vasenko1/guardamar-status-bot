"""Shared local-only event loading for proactive planning surfaces."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from zoneinfo import ZoneInfo

from .agenda import AgendaError, fetch_today_events, recurring_events
from .am_guardamar import AmGuardamarError, fetch_today_am_guardamar_events
from .convega import ConvegaSourceError, fetch_today_convega_events
from .diagnostics import SourceDiagnostic, source_error
from .facv import FacvSourceError, fetch_today_facv_events
from .fishing_enrichment import (
    DEFAULT_FEPYC_AUTHORITY_STATE_PATH,
    DEFAULT_FPCV_DETAILS_STATE_PATH,
)
from .library_agenda import LibraryAgendaError, fetch_today_library_events
from .models import Event
from .morning import _merge_events, _prefer_agenda_guardamar_venues
from .municipal_agenda import MunicipalAgendaError, fetch_today_municipal_events
from .pesca_cv import PescaCvSourceError, fetch_today_pesca_cv_events


LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")


def snapshot_observed_on(
    path: Path,
    timestamp_field: str,
    local_day: date,
) -> bool:
    """Return whether one base source snapshot was observed on local_day."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        raw = value.get(timestamp_field)
        if not isinstance(raw, str):
            return False
        observed = datetime.fromisoformat(raw)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        AttributeError,
    ):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    return observed.astimezone(GUARDAMAR_TIMEZONE).date() == local_day


async def _load_source(
    *,
    surface: str,
    name: str,
    diagnostic_prefix: str,
    path: Path,
    timestamp_field: str,
    required_snapshot_day: Optional[date],
    load: Callable[[], Awaitable[tuple[Event, ...]]],
    errors: tuple[type[Exception], ...],
    diagnostics: Optional[List[SourceDiagnostic]],
) -> tuple[Event, ...]:
    if (
        required_snapshot_day is not None
        and not snapshot_observed_on(
            path,
            timestamp_field,
            required_snapshot_day,
        )
    ):
        LOGGER.info(
            "%s omits stale/missing %s snapshot for observation day %s",
            surface,
            name,
            required_snapshot_day,
        )
        return ()
    try:
        return await load()
    except errors as exc:
        LOGGER.warning("%s omits invalid %s snapshot: %s", surface, name, exc)
        if diagnostics is not None:
            diagnostics.append(source_error(diagnostic_prefix, name, exc))
        return ()


async def load_local_planning_events(
    target: datetime,
    *,
    required_snapshot_day: Optional[date],
    include_recurring: bool,
    municipal_agenda_state_path: Path,
    agenda_state_path: Path,
    library_agenda_state_path: Path,
    am_guardamar_state_path: Path,
    facv_state_path: Path,
    pesca_cv_state_path: Path,
    fepyc_authority_state_path: Path = Path(
        DEFAULT_FEPYC_AUTHORITY_STATE_PATH
    ),
    pesca_cv_details_state_path: Path = Path(
        DEFAULT_FPCV_DETAILS_STATE_PATH
    ),
    convega_state_path: Path,
    translation_cache_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
    surface: str = "Planning events",
) -> tuple[Event, ...]:
    """Read and merge one target day from accepted local snapshots only.

    This helper performs no source HTTP and no AI. Base proactive/current
    claims can require one explicit source-observation day. Source-specific
    supplemental state retains its adapter-owned freshness rules.
    """

    agenda = await _load_source(
        surface=surface,
        name="Agenda Guardamar",
        diagnostic_prefix="AGENDA",
        path=agenda_state_path,
        timestamp_field="fetched_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_events(
            target,
            "",
            agenda_state_path,
            translation_cache_path,
        ),
        errors=(AgendaError,),
        diagnostics=diagnostics,
    )

    municipal = await _load_source(
        surface=surface,
        name="Agenda municipal",
        diagnostic_prefix="MUNI-AGENDA",
        path=municipal_agenda_state_path,
        timestamp_field="fetched_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_municipal_events(
            target,
            "",
            municipal_agenda_state_path,
            translation_cache_path=translation_cache_path,
            diagnostics=diagnostics,
        ),
        errors=(MunicipalAgendaError,),
        diagnostics=diagnostics,
    )

    library = await _load_source(
        surface=surface,
        name="Biblioteca Municipal",
        diagnostic_prefix="LIBRARY",
        path=library_agenda_state_path,
        timestamp_field="fetched_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_library_events(
            target,
            library_agenda_state_path,
            translation_cache_path,
        ),
        errors=(LibraryAgendaError,),
        diagnostics=diagnostics,
    )

    music = await _load_source(
        surface=surface,
        name="AM Guardamar",
        diagnostic_prefix="AM-GUARDAMAR",
        path=am_guardamar_state_path,
        timestamp_field="fetched_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_am_guardamar_events(
            target,
            am_guardamar_state_path,
            translation_cache_path,
        ),
        errors=(AmGuardamarError,),
        diagnostics=diagnostics,
    )

    chess = await _load_source(
        surface=surface,
        name="FACV",
        diagnostic_prefix="FACV",
        path=facv_state_path,
        timestamp_field="observed_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_facv_events(
            target,
            facv_state_path,
            translation_cache_path,
        ),
        errors=(FacvSourceError,),
        diagnostics=diagnostics,
    )

    fishing = await _load_source(
        surface=surface,
        name="Federación Pesca CV",
        diagnostic_prefix="PESCA-CV",
        path=pesca_cv_state_path,
        timestamp_field="observed_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_pesca_cv_events(
            target,
            pesca_cv_state_path,
            translation_cache_path,
            fepyc_authority_state_path=fepyc_authority_state_path,
            details_state_path=pesca_cv_details_state_path,
        ),
        errors=(PescaCvSourceError,),
        diagnostics=diagnostics,
    )

    convega = await _load_source(
        surface=surface,
        name="CONVEGA",
        diagnostic_prefix="CONVEGA",
        path=convega_state_path,
        timestamp_field="observed_at",
        required_snapshot_day=required_snapshot_day,
        load=lambda: fetch_today_convega_events(
            target,
            convega_state_path,
            translation_cache_path,
        ),
        errors=(ConvegaSourceError,),
        diagnostics=diagnostics,
    )

    municipal = _prefer_agenda_guardamar_venues(municipal, agenda)
    recurring = recurring_events(target) if include_recurring else ()
    return _merge_events(
        recurring,
        municipal,
        agenda,
        library,
        music,
        chess,
        fishing,
        convega,
    )
