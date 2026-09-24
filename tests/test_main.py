import json
import os
import tempfile
import unittest
from datetime import datetime, time, timezone
from pathlib import Path
from unittest.mock import AsyncMock, call, patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import (
    _cams_cycle_is_current,
    _cams_monitor_checkpoint,
    _cams_update_checkpoint,
    _current_morning_message_id,
    _refresh_event_catalogs_once,
    _safebeach_initial_checkpoint,
    _send_operational_update,
    _produce_message,
    _run_command,
)
from telegrambot.agenda import AgendaError
from telegrambot.diagnostics import SourceDiagnostic
from telegrambot.environment import EnvironmentError
from telegrambot.hidraqua import HidraquaDeliveryUncertain
from telegrambot.models import (
    AirQualitySummary,
    BeachNotice,
    BeachStatus,
    PollenSummary,
)
from telegrambot.operational_updates import MonitorRun
from telegrambot.state import PublicationState, StateError
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")


class PreviewReportTests(unittest.IsolatedAsyncioTestCase):
    async def _run_late_cams_refresh(
        self,
        old_base,
        new_base,
        morning_air,
        cached_air,
        new_air,
        *,
        morning_pollen=None,
        cached_pollen=None,
        new_pollen=None,
        cached_base=None,
    ):
        """Run one late checkpoint with a separately reconstructed cache."""
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime(2026, 9, 11, 10, 40, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            state.mark_cams_environment(
                now.date(), old_base, morning_air, morning_pollen
            )
            fetch = AsyncMock(side_effect=[
                (cached_air, cached_pollen, cached_base or old_base),
                (new_air, new_pollen, new_base),
            ])
            sent = AsyncMock(return_value=30)
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.fetch_cams", new=fetch),
                patch("telegrambot.__main__.ensure_accepted_cams_snapshot"),
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_meteosalud_cold",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("update"), 0)
                environment_state = PublicationState(
                    state_path
                ).morning_environment_state(now.date())
            return sent, fetch, environment_state

    async def test_late_cams_ignores_elapsed_morning_air_category(self):
        old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        future = AirQualitySummary(("PM10",), "во второй половине дня", category=3)
        sent, fetch, state = await self._run_late_cams_refresh(
            old_base,
            new_base,
            AirQualitySummary(("PM10",), "утром", category=4),
            future,
            future,
        )
        sent.assert_not_awaited()
        self.assertFalse(fetch.await_args_list[0].kwargs["allow_remote"])
        self.assertTrue(fetch.await_args_list[0].kwargs["remaining_day"])
        self.assertEqual(state[2:], (new_base, future, None))

    async def test_late_cams_reports_genuine_future_improvement(self):
        old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        sent, _, _ = await self._run_late_cams_refresh(
            old_base,
            new_base,
            AirQualitySummary(("PM10",), "утром", category=4),
            AirQualitySummary(("PM10",), "во второй половине дня", category=4),
            AirQualitySummary(("PM10",), "во второй половине дня", category=3),
        )
        sent.assert_awaited_once()
        self.assertIn("С воздухом стало лучше", sent.await_args.args[2])

    async def test_late_cams_reports_genuine_future_worsening(self):
        old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        sent, _, _ = await self._run_late_cams_refresh(
            old_base,
            new_base,
            AirQualitySummary(("PM10",), "утром", category=3),
            AirQualitySummary(("PM10",), "во второй половине дня", category=3),
            AirQualitySummary(("PM10",), "во второй половине дня", category=4),
        )
        sent.assert_awaited_once()
        self.assertIn("Сегодня с воздухом лучше быть осторожнее", sent.await_args.args[2])

    async def test_late_cams_mismatched_cache_accepts_without_comparing(self):
        old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        mismatched = datetime(2026, 9, 9, tzinfo=timezone.utc)
        new_air = AirQualitySummary(("PM10",), "во второй половине дня", category=4)
        sent, _, state = await self._run_late_cams_refresh(
            old_base,
            new_base,
            AirQualitySummary(("PM10",), "утром", category=3),
            AirQualitySummary(("PM10",), "во второй половине дня", category=3),
            new_air,
            cached_base=mismatched,
        )
        sent.assert_not_awaited()
        self.assertEqual(state[2:], (new_base, new_air, None))

    async def test_late_cams_compares_pollen_on_the_same_remaining_interval(self):
        old_base = datetime(2026, 9, 10, tzinfo=timezone.utc)
        new_base = datetime(2026, 9, 11, tzinfo=timezone.utc)
        future = PollenSummary(("оливы",), "во второй половине дня")
        sent, _, _ = await self._run_late_cams_refresh(
            old_base, new_base, None, None, None,
            morning_pollen=PollenSummary(("оливы",), "утром"),
            cached_pollen=future,
            new_pollen=future,
        )
        sent.assert_not_awaited()

    def test_cams_refresh_uses_one_early_checkpoint_then_normal_monitoring(self):
        self.assertFalse(_cams_update_checkpoint(
            datetime(2026, 9, 11, 10, 10, tzinfo=MADRID)
        ))
        self.assertFalse(_cams_update_checkpoint(
            datetime(2026, 9, 11, 10, 25, tzinfo=MADRID)
        ))
        self.assertTrue(_cams_update_checkpoint(
            datetime(2026, 9, 11, 10, 40, tzinfo=MADRID)
        ))
        self.assertFalse(_cams_update_checkpoint(
            datetime(2026, 9, 11, 10, 45, tzinfo=MADRID)
        ))
        self.assertTrue(_cams_monitor_checkpoint(MonitorRun(1, False)))
        self.assertTrue(_cams_monitor_checkpoint(MonitorRun(None, True)))
        self.assertFalse(_cams_monitor_checkpoint(MonitorRun(2, False)))

    def test_safebeach_initial_cycle_has_exact_1040_boundary(self):
        self.assertTrue(_safebeach_initial_checkpoint(
            datetime(2026, 9, 11, 10, 10, tzinfo=MADRID)
        ))
        self.assertTrue(_safebeach_initial_checkpoint(
            datetime(2026, 9, 11, 10, 40, tzinfo=MADRID)
        ))
        self.assertFalse(_safebeach_initial_checkpoint(
            datetime(2026, 9, 11, 10, 45, tzinfo=MADRID)
        ))
        self.assertFalse(_safebeach_initial_checkpoint(
            datetime(2026, 9, 11, 10, 12, tzinfo=MADRID)
        ))

    def test_cams_refresh_stops_after_current_utc_cycle(self):
        now = datetime(2026, 10, 25, 10, 10, tzinfo=MADRID)
        self.assertTrue(_cams_cycle_is_current(
            datetime.fromisoformat("2026-10-25T00:00:00+00:00"), now
        ))
        self.assertFalse(_cams_cycle_is_current(
            datetime.fromisoformat("2026-10-24T00:00:00+00:00"), now
        ))

    async def test_cams_1040_miss_recovers_on_normal_monitor_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            monitor_path = Path(directory) / "operational.json"
            first = datetime(2026, 9, 11, 10, 40, tzinfo=MADRID)
            second = datetime(2026, 9, 11, 12, 0, tzinfo=MADRID)
            old_base = datetime.fromisoformat("2026-09-10T00:00:00+00:00")
            new_base = datetime.fromisoformat("2026-09-11T00:00:00+00:00")
            state = PublicationState(state_path)
            state.mark_morning(first.date(), 10, first)
            state.mark_morning_environment(first.date(), None, old_base)
            fetch = AsyncMock(side_effect=[
                (None, None, old_base),
                EnvironmentError("not published yet"),
                (None, None, old_base),
                (None, None, new_base),
            ])
            sent = AsyncMock(return_value=30)
            common = {
                "AEMET_API_KEY": "aemet",
                "TELEGRAM_BOT_TOKEN": "telegram",
                "TELEGRAM_CHAT_ID": "group",
                "MORNING_DIGEST_STATE_PATH": str(state_path),
                "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
            }
            with (
                patch.dict(os.environ, common),
                patch("telegrambot.__main__.datetime") as clock,
                patch("telegrambot.__main__.fetch_cams", new=fetch),
                patch("telegrambot.__main__.ensure_accepted_cams_snapshot"),
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_meteosalud_cold",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.scheduled_run",
                    return_value=MonitorRun(None, True),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
            ):
                clock.now.side_effect = [first, second]
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(await _run_command("update"), 0)
                self.assertEqual(await _run_command("monitor-updates"), 0)
            self.assertEqual(fetch.await_count, 4)
            sent.assert_not_awaited()
            self.assertEqual(
                PublicationState(state_path).morning_environment(first.date())[2],
                new_base,
            )

    async def test_partial_safebeach_creates_and_refreshes_one_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            first = datetime(2026, 7, 21, 10, 10, tzinfo=MADRID)
            second = datetime(2026, 7, 21, 10, 15, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(first.date(), 10, datetime(
                2026, 7, 21, 7, 30, tzinfo=MADRID
            ))
            first_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=first.date(),
                nearby_flags=(("Centre", "green"),),
                updated_times=(("Centre", time(10, 5)),),
            )
            second_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=second.date(),
                nearby_flags=(
                    ("Centre", "green"),
                    ("Roqueta", "yellow"),
                ),
                updated_times=(
                    ("Centre", time(10, 5)),
                    ("Roqueta", time(10, 12)),
                ),
            )
            sent = AsyncMock(return_value=20)
            edited = AsyncMock()
            beach_fetch = AsyncMock(side_effect=[first_status, second_status])
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._cams_update_checkpoint",
                    return_value=False,
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=beach_fetch,
                ),
                patch(
                    "telegrambot.__main__.latest_beach_notice",
                    new=AsyncMock(return_value=None),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=edited),
            ):
                clock.now.side_effect = [first, second]
                self.assertEqual(await _run_command("update"), 0)
                self.assertEqual(await _run_command("update"), 0)

            sent.assert_awaited_once()
            edited.assert_awaited_once()
            self.assertEqual(
                PublicationState(state_path).beach_message_id(first.date()),
                20,
            )
            self.assertEqual(
                PublicationState(state_path).beach_root_facts(first.date())[
                    0
                ].nearby_flags,
                second_status.nearby_flags,
            )

    async def test_update_after_1040_skips_safebeach_but_keeps_mayor_check(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime(2026, 9, 21, 10, 45, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(
                now.date(),
                10,
                datetime(2026, 9, 21, 7, 30, tzinfo=MADRID),
            )
            beach_fetch = AsyncMock()
            notice = BeachNotice(
                "Купание запрещено",
                True,
                datetime(2026, 9, 21, 10, 44, tzinfo=MADRID),
            )
            mayor_fetch = AsyncMock(return_value=notice)
            sent = AsyncMock(return_value=20)
            edited = AsyncMock()
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=beach_fetch,
                ),
                patch(
                    "telegrambot.__main__.latest_beach_notice",
                    new=mayor_fetch,
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=edited),
            ):
                clock.now.return_value = now
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(await _run_command("update"), 0)

            beach_fetch.assert_not_awaited()
            mayor_fetch.assert_awaited_once()
            sent.assert_awaited_once()
            edited.assert_not_awaited()
            saved_status, saved_notice = PublicationState(
                state_path
            ).beach_root_facts(now.date())
            self.assertIsNone(saved_status)
            self.assertEqual(saved_notice, notice)

    async def test_late_first_safebeach_waits_for_confirmation_before_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            monitor_path = Path(directory) / "operational.json"
            first = datetime(2026, 9, 21, 12, 0, tzinfo=MADRID)
            second = datetime(2026, 9, 21, 12, 5, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(
                first.date(),
                10,
                datetime(2026, 9, 21, 7, 30, tzinfo=MADRID),
            )
            first_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=first.date(),
                nearby_flags=(("Centre", "green"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 0)),),
            )
            second_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=second.date(),
                nearby_flags=(("Centre", "green"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 5)),),
            )
            sent = AsyncMock(return_value=20)
            edited = AsyncMock()
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._refresh_mayor_beach_notice",
                    new=AsyncMock(return_value="no_update"),
                ),
                patch(
                    "telegrambot.__main__._cams_monitor_checkpoint",
                    return_value=False,
                ),
                patch(
                    "telegrambot.__main__.load_snapshot",
                    return_value=None,
                ),
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(side_effect=[first_status, second_status]),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=edited),
            ):
                clock.now.side_effect = [first, second]
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(await _run_command("monitor-updates"), 0)
                sent.assert_not_awaited()
                self.assertIsNone(
                    PublicationState(state_path).beach_message_id(first.date())
                )
                self.assertEqual(await _run_command("monitor-updates"), 0)

            sent.assert_awaited_once()
            edited.assert_not_awaited()
            saved = PublicationState(state_path)
            self.assertEqual(saved.beach_message_id(first.date()), 20)
            self.assertEqual(
                saved.beach_root_facts(first.date())[0].nearby_flags,
                second_status.nearby_flags,
            )

    async def test_confirmed_safebeach_fills_existing_mayor_only_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            monitor_path = Path(directory) / "operational.json"
            first = datetime(2026, 9, 21, 12, 0, tzinfo=MADRID)
            second = datetime(2026, 9, 21, 12, 5, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(
                first.date(),
                10,
                datetime(2026, 9, 21, 7, 30, tzinfo=MADRID),
            )
            notice = BeachNotice(
                "Купание запрещено",
                True,
                datetime(2026, 9, 21, 11, 0, tzinfo=MADRID),
            )
            state.mark_beach_message(first.date(), 20, notice=notice)
            first_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=first.date(),
                nearby_flags=(("Centre", "green"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 0)),),
            )
            second_status = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=second.date(),
                nearby_flags=(("Centre", "green"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 5)),),
            )
            sent = AsyncMock()
            edited = AsyncMock()
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._refresh_mayor_beach_notice",
                    new=AsyncMock(return_value="no_update"),
                ),
                patch(
                    "telegrambot.__main__._cams_monitor_checkpoint",
                    return_value=False,
                ),
                patch(
                    "telegrambot.__main__.load_snapshot",
                    return_value=None,
                ),
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(side_effect=[first_status, second_status]),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=edited),
            ):
                clock.now.side_effect = [first, second]
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(await _run_command("monitor-updates"), 0)
                edited.assert_not_awaited()
                self.assertEqual(await _run_command("monitor-updates"), 0)

            sent.assert_not_awaited()
            edited.assert_awaited_once()
            saved_status, saved_notice = PublicationState(
                state_path
            ).beach_root_facts(first.date())
            self.assertEqual(
                saved_status.nearby_flags,
                second_status.nearby_flags,
            )
            self.assertEqual(saved_notice, notice)

    async def test_safebeach_query_window_uses_normal_recovery_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime(2026, 9, 21, 10, 25, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            beach_fetch = AsyncMock(return_value=None)
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._cams_update_checkpoint",
                    return_value=False,
                ),
                patch(
                    "telegrambot.__main__._refresh_event_catalogs_once",
                    new=AsyncMock(),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=beach_fetch,
                ),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("update"), 0)

        beach_fetch.assert_awaited_once_with(now)

    async def test_operational_beach_change_replies_without_editing_existing_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            monitor_path = Path(directory) / "operational.json"
            first = datetime(2026, 9, 21, 12, 0, tzinfo=MADRID)
            second = datetime(2026, 9, 21, 12, 5, tzinfo=MADRID)
            publication = PublicationState(state_path)
            publication.mark_morning(
                first.date(),
                10,
                datetime(2026, 9, 21, 7, 30, tzinfo=MADRID),
            )
            baseline = BeachStatus(
                flag_color="green",
                sea_temperature_c=26,
                source_date=first.date(),
                nearby_flags=(("Centre", "green"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(10, 40)),),
            )
            publication.mark_beach_message(first.date(), 20, baseline)

            changed_first = BeachStatus(
                flag_color="yellow",
                sea_temperature_c=26,
                source_date=first.date(),
                nearby_flags=(("Centre", "yellow"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 0)),),
            )
            changed_second = BeachStatus(
                flag_color="yellow",
                sea_temperature_c=26,
                source_date=second.date(),
                nearby_flags=(("Centre", "yellow"),),
                jellyfish_states=(("Centre", False),),
                updated_times=(("Centre", time(12, 5)),),
            )
            sent = AsyncMock(return_value=30)
            edited = AsyncMock()
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._refresh_mayor_beach_notice",
                    new=AsyncMock(return_value="no_update"),
                ),
                patch(
                    "telegrambot.__main__._cams_monitor_checkpoint",
                    return_value=False,
                ),
                patch(
                    "telegrambot.__main__.load_snapshot",
                    return_value=None,
                ),
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(side_effect=[
                        changed_first,
                        changed_second,
                    ]),
                ),
                patch("telegrambot.__main__.send_message", new=sent),
                patch("telegrambot.__main__.edit_message", new=edited),
            ):
                clock.now.side_effect = [first, second]
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(await _run_command("monitor-updates"), 0)
                self.assertEqual(await _run_command("monitor-updates"), 0)

            edited.assert_not_awaited()
            sent.assert_awaited_once()
            self.assertEqual(
                sent.await_args.kwargs["reply_to_message_id"],
                20,
            )
            self.assertIn("🟡 Centre / Babilònia", sent.await_args.args[2])
            self.assertEqual(
                PublicationState(state_path).beach_root_facts(first.date())[
                    0
                ].nearby_flags,
                baseline.nearby_flags,
            )

    async def test_operational_checkpoint_accepts_late_cams_without_editing_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            monitor_path = Path(directory) / "operational.json"
            now = datetime(2026, 9, 11, 12, 0, tzinfo=MADRID)
            old_base = datetime.fromisoformat("2026-09-10T00:00:00+00:00")
            new_base = datetime.fromisoformat("2026-09-11T00:00:00+00:00")
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            state.mark_morning_environment(now.date(), None, old_base, cold_level=2)
            edited = AsyncMock()
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                    "OPERATIONAL_UPDATE_STATE_PATH": str(monitor_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.fetch_cams",
                    new=AsyncMock(return_value=(None, None, new_base)),
                ) as fetch,
                patch("telegrambot.__main__.ensure_accepted_cams_snapshot"),
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(return_value=None),
                ),
                patch("telegrambot.__main__.edit_message", new=edited),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    new=AsyncMock(return_value=()),
                ),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("monitor-updates"), 0)

            self.assertEqual(fetch.await_count, 2)
            edited.assert_not_awaited()
            self.assertEqual(
                PublicationState(state_path).morning_environment(now.date()),
                (None, 2, new_base),
            )

    async def test_late_meteosalud_failure_preserves_previous_level(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime(2026, 9, 11, 10, 10, tzinfo=MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            state.mark_morning_environment(
                now.date(), 2,
                datetime(2026, 9, 11, tzinfo=timezone.utc),
                cold_level=1,
            )
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.fetch_meteosalud",
                    new=AsyncMock(side_effect=EnvironmentError("offline")),
                ),
                patch(
                    "telegrambot.__main__.fetch_meteosalud_cold",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    new=AsyncMock(return_value=None),
                ),
                patch("telegrambot.__main__.send_message", new=AsyncMock()),
            ):
                clock.now.return_value = now
                self.assertEqual(await _run_command("update"), 0)
            self.assertEqual(
                PublicationState(state_path).morning_environment(now.date())[:2],
                (2, 1),
            )

    async def test_hidraqua_maps_ambiguous_send_to_domain_uncertainty(self):
        async def monitor(state, now, publisher, **_kwargs):
            with self.assertRaises(HidraquaDeliveryUncertain):
                await publisher("water notice")
            return 0

        telegram_error = TelegramError(
            "network", retryable=True, code="NETWORK"
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "hidraqua.json"
            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "@group",
                    "HIDRAQUA_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.monitor_once", new=monitor),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(side_effect=telegram_error),
                ),
            ):
                result = await _run_command("monitor-hidraqua")

        self.assertEqual(result, 0)

    async def test_earthquake_monitor_needs_only_telegram_configuration(self):
        monitor = AsyncMock(return_value=0)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "earthquakes.json"
            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "@group",
                    "EARTHQUAKE_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.monitor_earthquakes", new=monitor),
            ):
                result = await _run_command("monitor-earthquakes")

        self.assertEqual(result, 0)
        monitor.assert_awaited_once()
        self.assertEqual(monitor.await_args.args[1].path, state_path)

    async def test_earthquake_new_message_retries_only_explicit_rate_limit(self):
        sent = AsyncMock(return_value=123)

        async def monitor(now, state, fetcher, publisher):
            self.assertEqual(await publisher("alert", None), 123)
            return 1

        with (
            patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": "telegram",
                "TELEGRAM_CHAT_ID": "@group",
            }),
            patch("telegrambot.__main__.monitor_earthquakes", new=monitor),
            patch("telegrambot.__main__.send_message", new=sent),
        ):
            result = await _run_command("monitor-earthquakes")

        self.assertEqual(result, 0)
        self.assertTrue(sent.await_args.kwargs["retry_only_rate_limits"])

    async def test_earthquake_series_recreates_deleted_message(self):
        edited = AsyncMock(side_effect=TelegramError(
            "missing",
            retryable=False,
            code="MESSAGE-NOT-FOUND",
            status=400,
        ))
        sent = AsyncMock(return_value=456)

        async def monitor(now, state, fetcher, publisher):
            self.assertEqual(await publisher("series", 123), 456)
            return 1

        with (
            patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": "telegram",
                "TELEGRAM_CHAT_ID": "@group",
            }),
            patch("telegrambot.__main__.monitor_earthquakes", new=monitor),
            patch("telegrambot.__main__.edit_message", new=edited),
            patch("telegrambot.__main__.send_message", new=sent),
        ):
            result = await _run_command("monitor-earthquakes")

        self.assertEqual(result, 0)
        edited.assert_awaited_once()
        sent.assert_awaited_once()

    async def test_pinned_preview_needs_no_weather_configuration(self):
        with patch("builtins.print") as output:
            result = await _run_command("pinned-preview")

        self.assertEqual(result, 0)
        self.assertIn("Полезное о Гуардамаре", output.call_args.args[0])

    async def test_pinned_send_preview_targets_single_allowed_operator(self):
        send = AsyncMock(return_value=1)
        with (
            patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": "telegram",
                "TELEGRAM_ALLOWED_USER_IDS": "123",
            }),
            patch("telegrambot.__main__.send_message", new=send),
        ):
            result = await _run_command("pinned-send-preview")

        self.assertEqual(result, 0)
        self.assertGreater(send.await_count, 1)
        for item in send.await_args_list:
            self.assertEqual(item.args[:2], ("telegram", "123"))
            self.assertTrue(item.kwargs["disable_notification"])

    async def test_pinned_send_preview_rejects_ambiguous_operator(self):
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "telegram",
            "TELEGRAM_ALLOWED_USER_IDS": "123,456",
        }):
            with self.assertRaises(ValueError):
                await _run_command("pinned-send-preview")

    async def test_late_event_catalogs_refresh_only_once_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 8, 7, 10, 10, tzinfo=MADRID)
            state.mark_morning(now.date(), 10, now)
            municipal = AsyncMock(return_value=())
            agenda = AsyncMock(return_value=())
            with (
                patch("telegrambot.__main__.refresh_municipal_catalog", new=municipal),
                patch("telegrambot.__main__.refresh_agenda_catalog", new=agenda),
            ):
                await _refresh_event_catalogs_once(
                    now,
                    state,
                    Path(directory) / "municipal.json",
                    Path(directory) / "agenda.json",
                )
                await _refresh_event_catalogs_once(
                    now,
                    state,
                    Path(directory) / "municipal.json",
                    Path(directory) / "agenda.json",
                )

        municipal.assert_awaited_once()
        agenda.assert_awaited_once()

    async def test_late_event_refresh_prepares_new_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            now = datetime(2026, 9, 11, 10, 10, tzinfo=MADRID)
            state.mark_morning(now.date(), 10, now)
            prepared = AsyncMock(return_value=2)
            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "key"}),
                patch(
                    "telegrambot.__main__.refresh_municipal_catalog",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.refresh_agenda_catalog",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.municipal_translation_items",
                    new=AsyncMock(return_value=(("municipal", "teaser"),)),
                ),
                patch(
                    "telegrambot.__main__.agenda_translation_items",
                    new=AsyncMock(return_value=()),
                ),
                patch("telegrambot.__main__.prepare_translations", new=prepared),
            ):
                translations = Path(directory) / "translations.json"
                await _refresh_event_catalogs_once(
                    now,
                    state,
                    Path(directory) / "municipal.json",
                    Path(directory) / "agenda.json",
                    translations,
                )

        prepared.assert_awaited_once()
        self.assertEqual(prepared.await_args.args[2], translations)

    async def test_translation_preparation_isolates_catalog_failure(self):
        prepared = AsyncMock(return_value=1)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_API_KEY": "key",
                        "MUNICIPAL_AGENDA_STATE_PATH": str(
                            Path(directory) / "municipal.json"
                        ),
                        "AGENDA_STATE_PATH": str(
                            Path(directory) / "agenda.json"
                        ),
                        "LIBRARY_AGENDA_STATE_PATH": str(
                            Path(directory) / "library.json"
                        ),
                        "AM_GUARDAMAR_STATE_PATH": str(
                            Path(directory) / "am.json"
                        ),
                        "FACV_EVENTS_STATE_PATH": str(
                            Path(directory) / "facv.json"
                        ),
                        "PESCA_CV_EVENTS_STATE_PATH": str(
                            Path(directory) / "pesca.json"
                        ),
                        "EVENT_TRANSLATIONS_PATH": str(
                            Path(directory) / "translations.json"
                        ),
                    },
                ),
                patch(
                    "telegrambot.__main__.municipal_translation_items",
                    new=AsyncMock(return_value=(
                        ("municipal_agenda", "Película municipal"),
                    )),
                ),
                patch(
                    "telegrambot.__main__.agenda_translation_items",
                    new=AsyncMock(side_effect=AgendaError("catalog missing")),
                ),
                patch(
                    "telegrambot.__main__.library_translation_items",
                    new=AsyncMock(return_value=(
                        ("library_agenda", "Actividad biblioteca"),
                    )),
                ),
                patch(
                    "telegrambot.__main__.am_guardamar_translation_items",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.facv_translation_items",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.pesca_cv_translation_items",
                    new=AsyncMock(return_value=()),
                ),
                patch(
                    "telegrambot.__main__.prepare_translations",
                    new=prepared,
                ),
            ):
                self.assertEqual(
                    await _run_command("prepare-event-translations"),
                    0,
                )

        prepared.assert_awaited_once()
        self.assertEqual(
            prepared.await_args.args[1],
            [
                ("municipal_agenda", "Película municipal"),
                ("library_agenda", "Actividad biblioteca"),
            ],
        )

    def test_current_message_prefers_published_update(self):
        self.assertEqual(
            _current_morning_message_id({
                "morning_message_id": 10,
                "update_message_id": 20,
                "morning_deleted": True,
            }),
            20,
        )

    def test_current_message_uses_live_early_message(self):
        self.assertEqual(
            _current_morning_message_id({
                "morning_message_id": 10,
                "update_message_id": None,
                "morning_deleted": False,
            }),
            10,
        )

    def test_current_message_rejects_deleted_record_without_update(self):
        with self.assertRaises(StateError):
            _current_morning_message_id({
                "morning_message_id": 10,
                "update_message_id": None,
                "morning_deleted": True,
            })

    async def test_operational_update_replies_to_full_digest(self):
        send = AsyncMock(return_value=30)
        with patch("telegrambot.__main__.send_message", new=send):
            result = await _send_operational_update(
                "token", "group", "update", 20
            )

        self.assertEqual(result, (30, True))
        send.assert_awaited_once_with(
            "token",
            "group",
            "update",
            disable_notification=False,
            reply_to_message_id=20,
        )

    async def test_operational_update_falls_back_if_anchor_is_gone(self):
        send = AsyncMock(side_effect=[
            TelegramError(
                "missing reply",
                retryable=False,
                code="MESSAGE-NOT-FOUND",
                status=400,
            ),
            30,
        ])
        with patch("telegrambot.__main__.send_message", new=send):
            result = await _send_operational_update(
                "token", "group", "update", 20
            )

        self.assertEqual(result, (30, False))
        self.assertEqual(send.await_args_list, [
            call(
                "token",
                "group",
                "update",
                disable_notification=False,
                reply_to_message_id=20,
            ),
            call(
                "token",
                "group",
                "update",
                disable_notification=False,
            ),
        ])

    async def test_operational_update_does_not_hide_other_http_400(self):
        send = AsyncMock(side_effect=TelegramError(
            "bad html",
            retryable=False,
            code="HTTP-400",
            status=400,
        ))
        with patch("telegrambot.__main__.send_message", new=send):
            with self.assertRaises(TelegramError):
                await _send_operational_update(
                    "token", "group", "update", 20
                )
        send.assert_awaited_once()

    async def test_refresh_current_edits_legacy_recorded_update_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime.now(MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            state.mark_update_sent(now.date(), 20)
            edited = {}

            async def produce(*args, **kwargs):
                return "обновлённое сообщение"

            async def edit(token, chat_id, message_id, message):
                edited.update({
                    "token": token,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "message": message,
                })

            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.produce_message", new=produce),
                patch("telegrambot.__main__.edit_message", new=edit),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                result = await _run_command("refresh-current")

        self.assertEqual(result, 0)
        self.assertEqual(edited, {
            "token": "telegram",
            "chat_id": "group",
            "message_id": 20,
            "message": "обновлённое сообщение",
        })

    async def test_refresh_current_edits_immutable_morning_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime.now(MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now)
            edited = AsyncMock()

            async def produce(*args, **kwargs):
                self.assertIsNone(kwargs["aemet_digest"])
                self.assertTrue(kwargs["fetch_aemet"])
                return "обновлённое утреннее сообщение"

            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.produce_message", new=produce),
                patch("telegrambot.__main__.edit_message", new=edited),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
            ):
                self.assertEqual(await _run_command("refresh-current"), 0)

            edited.assert_awaited_once_with(
                "telegram", "group", 10, "обновлённое утреннее сообщение"
            )
            self.assertIsNone(
                PublicationState(state_path).morning_record(now.date())[
                    "update_message_id"
                ]
            )

    async def test_successful_live_morning_fetch_updates_aemet_snapshot(self):
        observed_digest = object()

        async def produce(*args, **kwargs):
            kwargs["aemet_observer"](observed_digest)
            return "утреннее сообщение"

        async def publish(now, state, producer, sender, finalizer=None):
            await producer()
            if finalizer is not None:
                await finalizer()
            return "success"

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(Path(directory) / "delivery.json"),
                    "AEMET_SNAPSHOT_PATH": str(Path(directory) / "aemet.json"),
                }),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
                patch("telegrambot.__main__.preparation_busy", return_value=False),
                patch("telegrambot.__main__.produce_message", new=produce),
                patch("telegrambot.__main__.publish_morning", new=publish),
                patch("telegrambot.__main__.write_snapshot") as write,
                patch(
                    "telegrambot.__main__.monitor_suma",
                    new=AsyncMock(return_value="no_trigger"),
                ) as suma,
            ):
                result = await _run_command("morning")

        self.assertEqual(result, 0)
        self.assertIs(write.call_args.args[1], observed_digest)
        suma.assert_awaited_once()

    async def test_morning_failure_still_attempts_suma_without_masking_failure(self):
        morning_failure = RuntimeError("morning failed")
        suma = AsyncMock(return_value="no_trigger")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(Path(directory) / "delivery.json"),
                    "AEMET_SNAPSHOT_PATH": str(Path(directory) / "aemet.json"),
                    "SUMA_STATE_PATH": str(Path(directory) / "suma.json"),
                }),
                patch("telegrambot.__main__.load_snapshot", return_value=None),
                patch("telegrambot.__main__.preparation_busy", return_value=False),
                patch(
                    "telegrambot.__main__.publish_morning",
                    new=AsyncMock(side_effect=morning_failure),
                ),
                patch("telegrambot.__main__.monitor_suma", new=suma),
            ):
                with self.assertRaisesRegex(RuntimeError, "morning failed"):
                    await _run_command("morning")

        suma.assert_awaited_once()

    async def test_appends_diagnostics_only_in_preview_wrapper(self):
        async def produce(*args, diagnostics=None, **kwargs):
            diagnostics.append(SourceDiagnostic(
                "CAMS-NETWORK",
                "CAMS",
                "источник прогноза временно недоступен",
            ))
            return "готовый дайджест"

        with patch("telegrambot.__main__.produce_message", new=produce):
            message = await _produce_message(
                "key",
                datetime(2026, 7, 29, 10, 0, tzinfo=MADRID),
            )

        self.assertIn("готовый дайджест", message)
        self.assertIn("🔧 Диагностика источников", message)
        self.assertIn("[CAMS-NETWORK] CAMS", message)

    async def test_weekend_preview_neither_publishes_nor_writes_state(self):
        prepared = AsyncMock(return_value=0)
        with tempfile.TemporaryDirectory() as directory:
            translations = Path(directory) / "translations.json"
            weekend_state = Path(directory) / "weekend.json"
            with (
                patch("telegrambot.__main__.prepare_translations", new=prepared),
                patch(
                    "telegrambot.__main__.produce_weekend_message",
                    new=AsyncMock(return_value="афиша"),
                ),
                patch("telegrambot.__main__.send_message", new=AsyncMock()) as sent,
                patch.dict(os.environ, {
                    "EVENT_TRANSLATIONS_PATH": str(translations),
                    "WEEKEND_STATE_PATH": str(weekend_state),
                    "GEMINI_API_KEY": "configured-key",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "@chat",
                }),
            ):
                result = await _run_command("weekend-preview")

            self.assertEqual(result, 0)
            prepared.assert_not_awaited()
            sent.assert_not_awaited()
            self.assertFalse(translations.exists())
            self.assertFalse(weekend_state.exists())

    async def test_preview_uses_both_configured_event_catalogs(self):
        captured = {}

        async def produce(*args, diagnostics=None, **kwargs):
            captured["municipal"] = args[3]
            captured["agenda"] = kwargs["agenda_state_path"]
            return "готовый дайджест"

        with (
            patch("telegrambot.__main__.produce_message", new=produce),
            patch.dict(
                "os.environ",
                {
                    "MUNICIPAL_AGENDA_STATE_PATH": "state/municipal-test.json",
                    "AGENDA_STATE_PATH": "state/agenda-test.json",
                },
            ),
        ):
            await _produce_message(
                "key",
                datetime(2026, 8, 1, 7, 30, tzinfo=MADRID),
            )

        self.assertEqual(captured, {
            "municipal": Path("state/municipal-test.json"),
            "agenda": Path("state/agenda-test.json"),
        })


if __name__ == "__main__":
    unittest.main()
