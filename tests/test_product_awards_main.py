import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegrambot.__main__ import _run_command
from telegrambot.product_awards import (
    ProductAwardPublication,
    ProductAwardState,
    RetailOffer,
    ReviewedCandidate,
)
from telegrambot.telegram import TelegramError


def publication() -> ProductAwardPublication:
    candidate = ReviewedCandidate(
        category_key="test",
        event_id="test:event",
        source_name="Test",
        source_url="https://award.example/result",
        source_hosts=frozenset({"award.example"}),
        source_markers=("winner",),
        retailer="Test Market",
        retailer_kind="carrefour",
        retailer_url="https://shop.example/product",
        retailer_hosts=frozenset({"shop.example"}),
        retailer_markers=("Exact Product",),
        retailer_title="Exact Product",
        package="1 l",
        result_line="Exact Product — победитель",
        detail_line="Проверенный результат.",
        source_link_label="Источник",
    )
    return ProductAwardPublication(
        candidate=candidate,
        offer=RetailOffer(
            retailer="Test Market",
            package="1 l",
            price="2,50 €",
            product_url="https://shop.example/product",
        ),
        message="message",
    )


class ProductAwardCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_needs_no_telegram_credentials(self):
        item = publication()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "telegrambot.__main__.preview_product_awards",
                return_value=(item,),
            ),
            patch("builtins.print") as output,
        ):
            self.assertEqual(await _run_command("product-awards-preview"), 0)
        output.assert_called_once()
        self.assertIn("message", output.call_args.args[0])

    async def test_successful_send_confirms_event(self):
        item = publication()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
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
                    "telegrambot.__main__.select_product_award_publication",
                    return_value=(0, item),
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(return_value=123),
                ) as send,
            ):
                self.assertEqual(await _run_command("product-awards"), 0)

            send.assert_awaited_once()
            state = ProductAwardState(state_path)
            self.assertIn(item.candidate.event_id, state.published_events())
            self.assertIsNone(state.uncertain_event())
            self.assertIsNotNone(state._read()["last_delivery_day"])

    async def test_ambiguous_send_remains_uncertain(self):
        item = publication()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            error = TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )
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
                    "telegrambot.__main__.select_product_award_publication",
                    return_value=(0, item),
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                self.assertEqual(await _run_command("product-awards"), 0)

            state = ProductAwardState(state_path)
            self.assertEqual(
                state.uncertain_event(),
                item.candidate.event_id,
            )
            self.assertNotIn(
                item.candidate.event_id,
                state.published_events(),
            )

    async def test_explicit_send_failure_clears_reservation(self):
        item = publication()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "awards.json"
            error = TelegramError(
                "bad request",
                retryable=False,
                code="HTTP-400",
                status=400,
            )
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
                    "telegrambot.__main__.select_product_award_publication",
                    return_value=(0, item),
                ),
                patch(
                    "telegrambot.__main__.send_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await _run_command("product-awards")

            self.assertIsNone(ProductAwardState(state_path).uncertain_event())


if __name__ == "__main__":
    unittest.main()
