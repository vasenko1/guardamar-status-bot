import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.models import Event
from telegrambot.planning_events import (
    load_local_planning_events,
    snapshot_observed_on,
)


TZ = ZoneInfo("Europe/Madrid")
OBSERVED = datetime(2026, 10, 9, 18, 30, tzinfo=TZ)
TARGET = datetime(2026, 10, 10, 12, 0, tzinfo=TZ)


def _paths(root: str):
    base = Path(root)
    return {
        "municipal_agenda_state_path": base / "municipal.json",
        "agenda_state_path": base / "agenda.json",
        "library_agenda_state_path": base / "library.json",
        "am_guardamar_state_path": base / "am.json",
        "facv_state_path": base / "facv.json",
        "pesca_cv_state_path": base / "pesca.json",
        "fepyc_authority_state_path": base / "fepyc.json",
        "pesca_cv_details_state_path": base / "pesca-details.json",
        "convega_state_path": base / "convega.json",
        "translation_cache_path": base / "translations.json",
    }


def _write_observed(path: Path, field: str, when: datetime) -> None:
    path.write_text(
        json.dumps({field: when.isoformat()}),
        encoding="utf-8",
    )


class PlanningSnapshotFreshnessTests(unittest.TestCase):
    def test_snapshot_observation_day_is_timezone_aware(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            _write_observed(path, "observed_at", OBSERVED)

            self.assertTrue(
                snapshot_observed_on(path, "observed_at", date(2026, 10, 9))
            )
            self.assertFalse(
                snapshot_observed_on(path, "observed_at", date(2026, 10, 8))
            )

    def test_missing_naive_or_invalid_timestamp_is_not_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"

            path.write_text('{"observed_at":"2026-10-09T18:30:00"}')
            self.assertFalse(
                snapshot_observed_on(path, "observed_at", date(2026, 10, 9))
            )

            path.write_text('{"observed_at":123}')
            self.assertFalse(
                snapshot_observed_on(path, "observed_at", date(2026, 10, 9))
            )

            path.write_text("not-json")
            self.assertFalse(
                snapshot_observed_on(path, "observed_at", date(2026, 10, 9))
            )


class PlanningLocalLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_sources_use_local_readers_and_explicit_pesca_enrichment_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            for key, field in (
                ("municipal_agenda_state_path", "fetched_at"),
                ("agenda_state_path", "fetched_at"),
                ("library_agenda_state_path", "fetched_at"),
                ("am_guardamar_state_path", "fetched_at"),
                ("facv_state_path", "observed_at"),
                ("pesca_cv_state_path", "observed_at"),
                ("convega_state_path", "observed_at"),
            ):
                _write_observed(paths[key], field, OBSERVED)

            municipal = AsyncMock(return_value=())
            agenda = AsyncMock(return_value=())
            library = AsyncMock(return_value=())
            music = AsyncMock(return_value=())
            chess = AsyncMock(return_value=())
            fishing = AsyncMock(return_value=())
            convega = AsyncMock(return_value=())

            with (
                patch(
                    "telegrambot.planning_events.fetch_today_municipal_events",
                    new=municipal,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_events",
                    new=agenda,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_library_events",
                    new=library,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_am_guardamar_events",
                    new=music,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_facv_events",
                    new=chess,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_pesca_cv_events",
                    new=fishing,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_convega_events",
                    new=convega,
                ),
            ):
                events = await load_local_planning_events(
                    TARGET,
                    required_snapshot_day=OBSERVED.date(),
                    include_recurring=False,
                    **paths,
                )

            self.assertEqual(events, ())
            for mocked in (
                municipal,
                agenda,
                library,
                music,
                chess,
                fishing,
                convega,
            ):
                mocked.assert_awaited_once()

            self.assertEqual(agenda.await_args.args[1], "")
            self.assertEqual(municipal.await_args.args[1], "")
            self.assertEqual(
                fishing.await_args.kwargs["fepyc_authority_state_path"],
                paths["fepyc_authority_state_path"],
            )
            self.assertEqual(
                fishing.await_args.kwargs["details_state_path"],
                paths["pesca_cv_details_state_path"],
            )

    async def test_shared_loader_preserves_existing_cross_source_merge_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            for key, field in (
                ("municipal_agenda_state_path", "fetched_at"),
                ("agenda_state_path", "fetched_at"),
                ("library_agenda_state_path", "fetched_at"),
                ("am_guardamar_state_path", "fetched_at"),
                ("facv_state_path", "observed_at"),
                ("pesca_cv_state_path", "observed_at"),
                ("convega_state_path", "observed_at"),
            ):
                _write_observed(paths[key], field, OBSERVED)

            municipal_event = Event(
                "Concierto Guardamar",
                TARGET,
                place="Casa de Cultura",
            )
            agenda_event = Event(
                "Concierto Guardamar",
                TARGET,
                ends_at=datetime(2026, 10, 10, 14, 0, tzinfo=TZ),
                place="Casa de Cultura",
                ticket_price_cents=500,
            )

            with (
                patch(
                    "telegrambot.planning_events.fetch_today_municipal_events",
                    new=AsyncMock(return_value=(municipal_event,)),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_events",
                    new=AsyncMock(return_value=(agenda_event,)),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_library_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_am_guardamar_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_facv_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_pesca_cv_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_convega_events",
                    new=AsyncMock(return_value=()),
                ),
            ):
                events = await load_local_planning_events(
                    TARGET,
                    required_snapshot_day=OBSERVED.date(),
                    include_recurring=False,
                    **paths,
                )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].title, "Concierto Guardamar")
            self.assertEqual(events[0].ends_at.hour, 14)
            self.assertEqual(events[0].ticket_price_cents, 500)

    async def test_stale_source_is_omitted_without_calling_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            for key, field in (
                ("municipal_agenda_state_path", "fetched_at"),
                ("agenda_state_path", "fetched_at"),
                ("library_agenda_state_path", "fetched_at"),
                ("am_guardamar_state_path", "fetched_at"),
                ("pesca_cv_state_path", "observed_at"),
                ("convega_state_path", "observed_at"),
            ):
                _write_observed(paths[key], field, OBSERVED)
            _write_observed(
                paths["facv_state_path"],
                "observed_at",
                datetime(2026, 10, 8, 18, 30, tzinfo=TZ),
            )

            chess = AsyncMock(
                return_value=(
                    Event(
                        "Старые шахматы",
                        TARGET,
                        sport="chess",
                    ),
                )
            )
            empty = AsyncMock(return_value=())
            with (
                patch(
                    "telegrambot.planning_events.fetch_today_municipal_events",
                    new=empty,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_library_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_am_guardamar_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_facv_events",
                    new=chess,
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_pesca_cv_events",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.planning_events.fetch_today_convega_events",
                    new=AsyncMock(return_value=()),
                ),
            ):
                events = await load_local_planning_events(
                    TARGET,
                    required_snapshot_day=OBSERVED.date(),
                    include_recurring=False,
                    **paths,
                )

            self.assertEqual(events, ())
            chess.assert_not_awaited()

    async def test_weekend_recurring_rules_survive_missing_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            sunday = datetime(2026, 10, 11, 12, 0, tzinfo=TZ)

            events = await load_local_planning_events(
                sunday,
                required_snapshot_day=OBSERVED.date(),
                include_recurring=True,
                **paths,
            )

            self.assertTrue(
                any("Рынок Campo de Guardamar" in event.title for event in events)
            )

    async def test_tomorrow_mode_does_not_gain_recurring_market(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            sunday = datetime(2026, 10, 11, 12, 0, tzinfo=TZ)

            events = await load_local_planning_events(
                sunday,
                required_snapshot_day=OBSERVED.date(),
                include_recurring=False,
                **paths,
            )

            self.assertEqual(events, ())


if __name__ == "__main__":
    unittest.main()
