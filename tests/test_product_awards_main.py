import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from telegrambot.__main__ import _run_command, main
from telegrambot.product_awards import (
    ProductAwardCandidate,
    ProductAwardPublication,
    ProductAwardState,
    RetailEvidence,
)
from telegrambot.telegram import TelegramError


class ProductAwardCliTests(unittest.TestCase):
    def test_public_cli_accepts_all_product_award_commands(self):
        for command in (
            "product-awards-preview",
            "product-awards-discover",
            "product-awards",
        ):
            with self.subTest(command=command):
                with (
                    patch("sys.argv", ["telegrambot", command]),
                    patch("telegrambot.__main__._run_command", return_value=object()),
                    patch("telegrambot.__main__.asyncio.run", return_value=0) as run,
                ):
                    with self.assertRaises(SystemExit) as raised:
                        main()
                self.assertEqual(raised.exception.code, 0)
                run.assert_called_once()


class ProductAwardCommandTests(unittest.IsolatedAsyncioTestCase):
    def candidate(self):
        return ProductAwardCandidate(
            source_kind="ocu",
            event_key="ocu:salmorejo:hacendado",
            source_url="https://www.ocu.org/alimentacion/test/informe/salmorejo",
            product_name="salmorejo fresco de Hacendado",
            result="Mejor del Análisis",
            award_body="OCU",
            result_year=2026,
            retail=RetailEvidence(
                retailer="Mercadona",
                relationship="private_label",
                label="Hacendado",
            ),
            score="70/100",
            source_price="3 €/л",
        )

    def publication(self, candidate=None):
        candidate = candidate or self.candidate()
        return ProductAwardPublication(
            candidate=candidate,
            message="🏆 <b>Salmorejo Hacendado</b>\n\nTexto editorial",
        )

    def seed_queue(self, path: Path, candidate=None):
        candidate = candidate or self.candidate()
        state = ProductAwardState(path)
        state.initialize_source("ocu", ())
        state.enqueue_candidates((candidate,), date.today())
        return state

    async def test_preview_is_read_only_and_needs_no_gemini_key(self):
        publication = self.publication()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            scan = Mock(return_value=publication)
            with (
                patch.dict(
                    "os.environ",
                    {"PRODUCT_AWARDS_STATE_PATH": str(state_path)},
                    clear=False,
                ),
                patch("telegrambot.__main__.scan_next_product_award", scan),
                patch("telegrambot.__main__.send_message", new=AsyncMock()) as send,
            ):
                self.assertEqual(await _run_command("product-awards-preview"), 0)

            scan.assert_called_once()
            self.assertTrue(scan.call_args.kwargs["preview"])
            send.assert_not_awaited()
            self.assertFalse(state_path.exists())

    async def test_discovery_queues_without_telegram_or_gemini(self):
        item = self.candidate()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            state = ProductAwardState(state_path)
            state.initialize_source("ocu", ())
            discover = Mock(return_value=(item,))
            with (
                patch.dict(
                    "os.environ",
                    {"PRODUCT_AWARDS_STATE_PATH": str(state_path)},
                    clear=False,
                ),
                patch("telegrambot.__main__.discover_product_awards", discover),
                patch("telegrambot.__main__.send_message", new=AsyncMock()) as send,
                patch.object(ProductAwardState, "queue_size", side_effect=[0, 1]),
            ):
                self.assertEqual(await _run_command("product-awards-discover"), 0)

            discover.assert_called_once()
            send.assert_not_awaited()

    async def test_confirmed_text_send_publishes_event(self):
        item = self.candidate()
        publication = self.publication(item)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            self.seed_queue(state_path, item)
            with (
                patch.dict(
                    "os.environ",
                    {
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "@group",
                        "PRODUCT_AWARDS_STATE_PATH": str(state_path),
                    },
                    clear=False,
                ),
                patch(
                    "telegrambot.__main__.build_product_award_publication",
                    return_value=publication,
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(return_value=88),
                ) as send,
            ):
                self.assertEqual(await _run_command("product-awards"), 0)

            send.assert_awaited_once()
            state = ProductAwardState(state_path)
            self.assertTrue(state.published(item.event_id))
            self.assertEqual(state.queue_size(), 0)
            self.assertEqual(state.uncertain_events(), ())

    async def test_ambiguous_send_stays_uncertain_without_resend(self):
        item = self.candidate()
        publication = self.publication(item)
        ambiguous = TelegramError("timeout", retryable=True, code="TIMEOUT")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            self.seed_queue(state_path, item)
            with (
                patch.dict(
                    "os.environ",
                    {
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "@group",
                        "PRODUCT_AWARDS_STATE_PATH": str(state_path),
                    },
                    clear=False,
                ),
                patch(
                    "telegrambot.__main__.build_product_award_publication",
                    return_value=publication,
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(side_effect=ambiguous),
                ),
            ):
                self.assertEqual(await _run_command("product-awards"), 0)

            state = ProductAwardState(state_path)
            self.assertEqual(state.queue_size(), 0)
            self.assertEqual(state.uncertain_events(), (item.event_id,))
            self.assertFalse(state.published(item.event_id))

    async def test_explicit_send_failure_requeues_for_next_day(self):
        item = self.candidate()
        publication = self.publication(item)
        failure = TelegramError(
            "bad request",
            retryable=False,
            code="HTTP-400",
            status=400,
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            self.seed_queue(state_path, item)
            with (
                patch.dict(
                    "os.environ",
                    {
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "@group",
                        "PRODUCT_AWARDS_STATE_PATH": str(state_path),
                    },
                    clear=False,
                ),
                patch(
                    "telegrambot.__main__.build_product_award_publication",
                    return_value=publication,
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(side_effect=failure),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await _run_command("product-awards")

            state = ProductAwardState(state_path)
            self.assertEqual(state.queue_size(), 1)
            self.assertEqual(state.uncertain_events(), ())
            self.assertIsNone(state.next_queue_item(date.today()))
            tomorrow = date.fromordinal(date.today().toordinal() + 1)
            self.assertIsNotNone(state.next_queue_item(tomorrow))


if __name__ == "__main__":
    unittest.main()
