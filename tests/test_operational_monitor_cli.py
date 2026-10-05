import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import _run_command
from telegrambot.aemet import AemetError
from telegrambot.models import BeachStatus, Warning
from telegrambot.operational_updates import (
    OperationalUpdateState,
    observe_warnings,
    seed_warnings,
)


MADRID = ZoneInfo("Europe/Madrid")


def _warning(now, *, level="yellow"):
    return Warning(
        event="Tormentas",
        level=level,
        starts_at=now - timedelta(minutes=15),
        ends_at=now + timedelta(hours=3),
        probability="40–70%",
    )


def _paths(directory):
    root = Path(directory)
    return {
        "MORNING_DIGEST_STATE_PATH": str(root / "delivery.json"),
        "OPERATIONAL_UPDATE_STATE_PATH": str(root / "operational.json"),
        "AEMET_SNAPSHOT_PATH": str(root / "aemet.json"),
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "@test-chat",
        "AEMET_API_KEY": "test-aemet-key",
    }


class OperationalMonitorCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_aemet_refetches_and_replaces_existing_pending_state(self):
        now = datetime(2026, 8, 7, 11, 51, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            env = _paths(directory)
            store = OperationalUpdateState(
                Path(env["OPERATIONAL_UPDATE_STATE_PATH"])
            )
            value = store.empty(now.date().isoformat())
            seed_warnings(value, (_warning(now, level="yellow"),))
            observe_warnings(
                value,
                (_warning(now, level="orange"),),
                now,
            )
            self.assertIsNotNone(value["warning_ready"])
            value["beach_pending"] = {
                "stage": 1,
                "candidates": [],
                "held": [],
            }
            store.write(value)

            latest = (_warning(now, level="red"),)
            fetch_warnings = AsyncMock(return_value=latest)
            send = AsyncMock(return_value=(123, False))

            with (
                patch.dict(os.environ, env, clear=False),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    fetch_warnings,
                ),
                patch(
                    "telegrambot.__main__._send_operational_update",
                    send,
                ),
            ):
                clock.now.return_value = now
                result = await _run_command("monitor-updates")

            self.assertEqual(result, 0)
            self.assertEqual(fetch_warnings.await_count, 1)
            self.assertEqual(send.await_count, 1)
            saved = store.read(now)
            self.assertIsNone(saved["warning_ready"])
            self.assertEqual(saved["warnings"][0]["level"], "red")
            self.assertIsNotNone(saved["beach_pending"])

    async def test_aemet_failure_preserves_pending_without_stale_delivery(self):
        now = datetime(2026, 8, 7, 11, 51, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            env = _paths(directory)
            store = OperationalUpdateState(
                Path(env["OPERATIONAL_UPDATE_STATE_PATH"])
            )
            value = store.empty(now.date().isoformat())
            seed_warnings(value, (_warning(now, level="yellow"),))
            observe_warnings(
                value,
                (_warning(now, level="orange"),),
                now,
            )
            store.write(value)

            fetch_warnings = AsyncMock(
                side_effect=AemetError(
                    "temporary",
                    code="HTTP-503",
                    retryable=True,
                )
            )
            send = AsyncMock()

            with (
                patch.dict(os.environ, env, clear=False),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.fetch_warnings",
                    fetch_warnings,
                ),
                patch(
                    "telegrambot.__main__._send_operational_update",
                    send,
                ),
            ):
                clock.now.return_value = now
                result = await _run_command("monitor-updates")

            self.assertEqual(result, 0)
            self.assertEqual(fetch_warnings.await_count, 1)
            self.assertEqual(send.await_count, 0)
            saved = store.read(now)
            self.assertIsNotNone(saved["warning_ready"])
            self.assertEqual(
                saved["warning_ready"]["current"][0]["level"],
                "orange",
            )

    async def test_pending_aemet_does_not_block_safebeach_primary_sample(self):
        now = datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            env = _paths(directory)
            store = OperationalUpdateState(
                Path(env["OPERATIONAL_UPDATE_STATE_PATH"])
            )
            value = store.empty(now.date().isoformat())
            seed_warnings(value, ())
            observe_warnings(
                value,
                (_warning(now, level="yellow"),),
                now,
            )
            self.assertIsNotNone(value["warning_ready"])
            store.write(value)

            beach = BeachStatus(
                flag_color=None,
                sea_temperature_c=None,
                nearby_flags=(("Centre", "yellow"),),
                jellyfish_beaches=(),
                jellyfish_states=(("Centre", False),),
                source_date=date(2026, 8, 7),
                updated_times=(("Centre", time(11, 0)),),
            )
            fetch_beach = AsyncMock(return_value=beach)

            with (
                patch.dict(os.environ, env, clear=False),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__._refresh_mayor_beach_notice",
                    new=AsyncMock(return_value="no_update"),
                ),
                patch(
                    "telegrambot.__main__.fetch_beach_status",
                    fetch_beach,
                ),
            ):
                clock.now.return_value = now
                result = await _run_command("monitor-updates")

            self.assertEqual(result, 0)
            self.assertEqual(fetch_beach.await_count, 1)
            saved = store.read(now)
            self.assertIsNotNone(saved["beach_pending"])
            self.assertIsNotNone(saved["warning_ready"])


if __name__ == "__main__":
    unittest.main()
