import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.pinned import LEAF_MESSAGES, PinnedGuideState
from telegrambot.telegram import TelegramError
from telegrambot.transport_schedules import (
    DownloadedPdf,
    LINES,
    TransportScheduleError,
    build_line_caption,
    sync_transport_schedules,
)


def _messages():
    keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
    return {key: number for number, key in enumerate(keys, start=1)}


class TransportCaptionTests(unittest.TestCase):
    def test_uses_only_the_current_reviewed_period(self):
        link = "https://t.me/c/1/20"
        summer = build_line_caption(
            LINES["line_1"],
            datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
            LINES["line_1"].default_url,
            link,
            True,
        )
        regular = build_line_caption(
            LINES["line_1"],
            datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Madrid")),
            LINES["line_1"].default_url,
            link,
            True,
        )
        unknown = build_line_caption(
            LINES["line_1"],
            datetime(2027, 7, 1, tzinfo=ZoneInfo("Europe/Madrid")),
            LINES["line_1"].default_url,
            link,
            False,
        )

        self.assertIn("июль и август, каждый день", summer)
        self.assertNotIn("сентябрь-июнь", summer)
        self.assertIn("сентябрь-июнь", regular)
        self.assertNotIn("июль и август", regular)
        self.assertIn("Актуальное расписание", unknown)
        self.assertNotIn("Los Secanos", unknown)
        for caption in (summer, regular, unknown):
            self.assertLessEqual(len(caption), 1024)
            self.assertNotIn("—", caption)


class TransportStateMigrationTests(unittest.TestCase):
    def test_reads_version_one_without_losing_message_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pinned.json"
            expected = _messages()
            path.write_text(json.dumps({
                "version": 1,
                "chat_id": "-100123",
                "messages": expected,
            }), encoding="utf-8")
            state = PinnedGuideState(path)

            payload = state.read_payload("-100123")
            state.write_payload("-100123", payload)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["messages"], expected)
            self.assertEqual(saved["lines"], {})
            self.assertTrue((Path(directory) / "pinned.previous.json").exists())

    def test_corrupt_current_state_recovers_previous_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pinned.json"
            state = PinnedGuideState(path)
            state.write("-100123", {"root": 1})
            state.write("-100123", {"root": 2})
            path.write_text("not json", encoding="utf-8")

            recovered = state.read_payload("-100123")

            self.assertEqual(recovered["messages"], {"root": 1})


class TransportSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrates_both_text_messages_then_updates_index(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            original = _messages()
            state.write("-100123", original)
            payloads = {
                key: f"%PDF-{key}".encode() for key in LINES
            }

            def download(url, etag, modified, force=False):
                key = "line_1" if "L01" in url else "line_2"
                return DownloadedPdf(payloads[key], url, "tag", "date")

            def render(payload, destination):
                destination.write_bytes(b"png-" + payload)
                return hashlib.sha256(destination.read_bytes()).hexdigest()

            next_ids = iter(((101, "file-1"), (102, "file-2")))

            async def send(path, caption):
                self.assertTrue(path.exists())
                self.assertIn("К списку транспорта", caption)
                return next(next_ids)

            edit_text = AsyncMock()
            delete = AsyncMock()
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    return_value={
                        key: definition.default_url
                        for key, definition in LINES.items()
                    },
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    side_effect=download,
                ),
                patch(
                    "telegrambot.transport_schedules.render_pdf",
                    side_effect=render,
                ),
            ):
                result = await sync_transport_schedules(
                    datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                    "-100123",
                    state,
                    send,
                    AsyncMock(),
                    AsyncMock(),
                    edit_text,
                    delete,
                )

            self.assertEqual(result["line_1"], 101)
            self.assertEqual(result["line_2"], 102)
            index = edit_text.await_args.args[1]
            self.assertIn("https://t.me/c/123/101", index)
            self.assertIn("https://t.me/c/123/102", index)
            self.assertEqual(
                {call.args[0] for call in delete.await_args_list},
                {original["line_1"], original["line_2"]},
            )
            saved = state.read_payload("-100123")
            self.assertTrue(saved["lines"]["line_1"]["media"])
            self.assertTrue(saved["lines"]["line_2"]["media"])

    async def test_unchanged_run_probes_captions_without_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = _messages()
            state.write("-100123", messages)
            payload = state.read_payload("-100123")
            image_dir = Path(directory) / "transport"
            image_dir.mkdir()
            for key, definition in LINES.items():
                image = image_dir / f"{key}-current.png"
                image.write_bytes(b"accepted")
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                payload["lines"][key] = {
                    "media": True,
                    "source_url": definition.default_url,
                    "pdf_sha256": definition.reviewed_sha256,
                    "reviewed": True,
                    "image_sha256": digest,
                    "published_image_sha256": digest,
                }
            state.write_payload("-100123", payload)
            unchanged = TelegramError(
                "unchanged", retryable=False,
                code="MESSAGE-NOT-MODIFIED", status=400,
            )
            edit_caption = AsyncMock(side_effect=unchanged)
            send = AsyncMock()
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    side_effect=TransportScheduleError("offline"),
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    return_value=None,
                ),
            ):
                await sync_transport_schedules(
                    datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                    "-100123", state, send, AsyncMock(), edit_caption,
                    AsyncMock(), AsyncMock(),
                )

            send.assert_not_awaited()
            self.assertEqual(edit_caption.await_count, 2)

    async def test_uncertain_send_is_persisted_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write("-100123", _messages())

            def download(url, etag, modified, force=False):
                return DownloadedPdf(b"%PDF-stable", url, None, None)

            def render(payload, destination):
                destination.write_bytes(b"png")
                return "image-sha"

            error = TelegramError(
                "timeout", retryable=True, code="TIMEOUT"
            )
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    return_value={
                        key: definition.default_url
                        for key, definition in LINES.items()
                    },
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    side_effect=download,
                ),
                patch(
                    "telegrambot.transport_schedules.render_pdf",
                    side_effect=render,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_transport_schedules(
                        datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                        "-100123", state,
                        AsyncMock(side_effect=error), AsyncMock(), AsyncMock(),
                        AsyncMock(), AsyncMock(),
                    )

            saved = state.read_payload("-100123")
            self.assertTrue(saved["lines"]["line_1"]["delivery_uncertain"])

    async def test_explicit_rate_limit_does_not_mark_photo_send_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write("-100123", _messages())

            def download(url, etag, modified, force=False):
                return DownloadedPdf(b"%PDF-stable", url, None, None)

            def render(payload, destination):
                destination.write_bytes(b"png")
                return "image-sha"

            rate_limited = TelegramError(
                "rate limited", retryable=True, code="HTTP-429", status=429
            )
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    return_value={
                        key: definition.default_url
                        for key, definition in LINES.items()
                    },
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    side_effect=download,
                ),
                patch(
                    "telegrambot.transport_schedules.render_pdf",
                    side_effect=render,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_transport_schedules(
                        datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                        "-100123",
                        state,
                        AsyncMock(side_effect=rate_limited),
                        AsyncMock(),
                        AsyncMock(),
                        AsyncMock(),
                        AsyncMock(),
                    )

            saved = state.read_payload("-100123")
            self.assertIsNot(
                saved["lines"].get("line_1", {}).get("delivery_uncertain"),
                True,
            )

    async def test_failed_media_edit_keeps_the_last_accepted_local_image(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = _messages()
            state.write("-100123", messages)
            payload = state.read_payload("-100123")
            image_dir = Path(directory) / "transport"
            image_dir.mkdir()
            for key, definition in LINES.items():
                image = image_dir / f"{key}-current.png"
                image.write_bytes(f"old-{key}".encode())
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                payload["lines"][key] = {
                    "media": True,
                    "source_url": definition.default_url,
                    "pdf_sha256": "old-pdf",
                    "image_sha256": digest,
                    "published_image_sha256": digest,
                    "reviewed": False,
                }
            state.write_payload("-100123", payload)

            def download(url, etag, modified, force=False):
                return DownloadedPdf(b"%PDF-new", url, None, None)

            def render(payload, destination):
                destination.write_bytes(b"new-image")
                return hashlib.sha256(b"new-image").hexdigest()

            rejected = TelegramError(
                "forbidden", retryable=False, code="HTTP-403", status=403
            )
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    return_value={
                        key: definition.default_url
                        for key, definition in LINES.items()
                    },
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    side_effect=download,
                ),
                patch(
                    "telegrambot.transport_schedules.render_pdf",
                    side_effect=render,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_transport_schedules(
                        datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                        "-100123", state, AsyncMock(),
                        AsyncMock(side_effect=rejected), AsyncMock(),
                        AsyncMock(), AsyncMock(),
                    )

            self.assertEqual(
                (image_dir / "line_1-current.png").read_bytes(),
                b"old-line_1",
            )
            self.assertFalse((image_dir / ".line_1-candidate.png").exists())

    async def test_partial_migration_preserves_new_and_obsolete_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            original = _messages()
            state.write("-100123", original)

            def download(url, etag, modified, force=False):
                return DownloadedPdf(b"%PDF-stable", url, None, None)

            def render(payload, destination):
                destination.write_bytes(b"png")
                return "image-sha"

            send = AsyncMock(side_effect=(
                (101, "file-1"),
                TelegramError(
                    "forbidden", retryable=False,
                    code="HTTP-403", status=403,
                ),
            ))
            with (
                patch(
                    "telegrambot.transport_schedules.discover_pdf_urls",
                    return_value={
                        key: definition.default_url
                        for key, definition in LINES.items()
                    },
                ),
                patch(
                    "telegrambot.transport_schedules.download_pdf",
                    side_effect=download,
                ),
                patch(
                    "telegrambot.transport_schedules.render_pdf",
                    side_effect=render,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_transport_schedules(
                        datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Madrid")),
                        "-100123", state, send, AsyncMock(), AsyncMock(),
                        AsyncMock(), AsyncMock(),
                    )

            saved = state.read_payload("-100123")
            self.assertEqual(saved["messages"]["line_1"], 101)
            self.assertEqual(
                saved["messages"]["line_2"], original["line_2"]
            )
            self.assertIn(
                original["line_1"], saved["obsolete_messages"]
            )


if __name__ == "__main__":
    unittest.main()
