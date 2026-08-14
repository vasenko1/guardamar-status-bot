import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, call, patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import (
    _current_morning_message_id,
    _refresh_event_catalogs_once,
    _send_operational_update,
    _produce_message,
    _run_command,
)
from telegrambot.diagnostics import SourceDiagnostic
from telegrambot.state import PublicationState, StateError
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")


class PreviewReportTests(unittest.IsolatedAsyncioTestCase):
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
                patch(
                    "telegrambot.__main__.refresh_municipal_catalog",
                    new=municipal,
                ),
                patch(
                    "telegrambot.__main__.refresh_agenda_catalog",
                    new=agenda,
                ),
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
            await _send_operational_update("token", "group", "update", 20)

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
                code="HTTP-400",
                status=400,
            ),
            30,
        ])
        with patch("telegrambot.__main__.send_message", new=send):
            await _send_operational_update("token", "group", "update", 20)

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

    async def test_refresh_current_edits_recorded_update_in_place(self):
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

    async def test_successful_live_morning_fetch_updates_aemet_snapshot(self):
        observed_digest = object()

        async def produce(*args, **kwargs):
            kwargs["aemet_observer"](observed_digest)
            return "утреннее сообщение"

        async def publish(now, state, producer, sender):
            await producer()
            return "success"

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {
                    "AEMET_API_KEY": "aemet",
                    "TELEGRAM_BOT_TOKEN": "telegram",
                    "TELEGRAM_CHAT_ID": "group",
                    "MORNING_DIGEST_STATE_PATH": str(
                        Path(directory) / "delivery.json"
                    ),
                    "AEMET_SNAPSHOT_PATH": str(
                        Path(directory) / "aemet.json"
                    ),
                }),
                patch(
                    "telegrambot.__main__.load_snapshot", return_value=None
                ),
                patch(
                    "telegrambot.__main__.preparation_busy",
                    return_value=False,
                ),
                patch("telegrambot.__main__.produce_message", new=produce),
                patch("telegrambot.__main__.publish_morning", new=publish),
                patch("telegrambot.__main__.write_snapshot") as write,
            ):
                result = await _run_command("morning")

        self.assertEqual(result, 0)
        self.assertIs(write.call_args.args[1], observed_digest)

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

    async def test_weekend_preview_neither_publishes_nor_writes_state(self):
        prepared = AsyncMock(return_value=0)
        with tempfile.TemporaryDirectory() as directory:
            translations = Path(directory) / "translations.json"
            weekend_state = Path(directory) / "weekend.json"
            with (
                patch(
                    "telegrambot.__main__.prepare_translations",
                    new=prepared,
                ),
                patch(
                    "telegrambot.__main__.produce_weekend_message",
                    new=AsyncMock(return_value="афиша"),
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(),
                ) as sent,
                patch.dict(os.environ, {
                    "EVENT_TRANSLATIONS_PATH": str(translations),
                    "WEEKEND_STATE_PATH": str(weekend_state),
                    "GEMINI_API_KEY": "configured-key",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "@chat",
                }),
            ):
                result = await _run_command("weekend-preview")

            # A configured Gemini key must not turn preview into a writer.
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

        self.assertEqual(
            captured,
            {
                "municipal": Path("state/municipal-test.json"),
                "agenda": Path("state/agenda-test.json"),
            },
        )


if __name__ == "__main__":
    unittest.main()
