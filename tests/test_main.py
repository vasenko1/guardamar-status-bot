import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import (
    _current_morning_message_id,
    _produce_message,
    _run_command,
)
from telegrambot.diagnostics import SourceDiagnostic
from telegrambot.state import PublicationState, StateError


MADRID = ZoneInfo("Europe/Madrid")


class PreviewReportTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_refresh_current_edits_recorded_update_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "delivery.json"
            now = datetime.now(MADRID)
            state = PublicationState(state_path)
            state.mark_morning(now.date(), 10, now, "утреннее сообщение")
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

    async def test_appends_diagnostics_only_in_preview_wrapper(self):
        async def produce(*args, diagnostics=None, **kwargs):
            diagnostics.append(
                SourceDiagnostic(
                    "SB-NO-ACTIVE",
                    "SafeBeach",
                    "активных данных выбранных пляжей нет",
                )
            )
            return "готовый дайджест"

        with patch("telegrambot.__main__.produce_message", new=produce):
            message = await _produce_message(
                "key",
                datetime(2026, 7, 29, 10, 0, tzinfo=MADRID),
            )

        self.assertIn("готовый дайджест", message)
        self.assertIn("🔧 Диагностика источников", message)
        self.assertIn("[SB-NO-ACTIVE] SafeBeach", message)

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

        self.assertEqual(
            captured,
            {
                "municipal": Path("state/municipal-test.json"),
                "agenda": Path("state/agenda-test.json"),
            },
        )


if __name__ == "__main__":
    unittest.main()
