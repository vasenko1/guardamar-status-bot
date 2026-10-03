import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from telegrambot.__main__ import _run_command, main
from telegrambot.product_awards import (
    ProductAwardError,
    ProductAwardPublication,
    ProductAwardState,
    RetailOffer,
    ReviewedCandidate,
)
from telegrambot.telegram import TelegramError


def publication() -> ProductAwardPublication:
    candidate = ReviewedCandidate(
        category_key="test",
        selection_key="test:2026",
        event_id="test:event",
        source_name="Test",
        source_kind="ocu",
        source_url="https://award.example/result",
        source_hosts=frozenset({"award.example"}),
        source_markers=("winner",),
        retailer="Test Market",
        retailer_kind="consum",
        retailer_url="https://shop.example/api/product/7",
        retailer_hosts=frozenset({"shop.example"}),
        retailer_markers=("Exact Product",),
        product_name="Exact Product",
        award_year=2026,
        source_category="Snacks",
        award_scope="exact_product",
        award_result="90/100",
        product_id=7,
        expected_ean="8410000000000",
    )
    return ProductAwardPublication(
        candidate=candidate,
        offer=RetailOffer(
            retailer="Test Market",
            price="2,50 €",
            image_url=(
                "https://cdn-consum.aktiosdigitalservices.com/"
                "product.jpg"
            ),
            product_name="Exact Product",
        ),
        message=(
            '<img src="https://cdn-consum.aktiosdigitalservices.com/'
            'product.jpg"/><p>message</p>'
        ),
    )


class ProductAwardCliTests(unittest.TestCase):
    def test_public_cli_accepts_product_award_commands(self):
        for command in ("product-awards-preview", "product-awards", "product-awards-force"):
            with self.subTest(command=command):
                with (
                    patch("sys.argv", ["telegrambot", command]),
                    patch("telegrambot.__main__._run_command", new=Mock(return_value=object())),
                    patch("telegrambot.__main__.asyncio.run", return_value=0) as run,
                ):
                    with self.assertRaises(SystemExit) as raised:
                        main()
                self.assertEqual(raised.exception.code, 0)
                run.assert_called_once()


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
                ) as select,
                patch(
                    "telegrambot.__main__.send_rich_message",
                    new=AsyncMock(return_value=123),
                ) as send,
            ):
                self.assertEqual(await _run_command("product-awards"), 0)

            send.assert_awaited_once()
            select.assert_called_once()
            self.assertFalse(select.call_args.kwargs["ignore_cooldown"])
            state = ProductAwardState(state_path)
            self.assertIn(item.candidate.event_id, state.published_events())
            self.assertIsNone(state.uncertain_event())
            self.assertIsNotNone(state._read()["last_delivery_day"])

    async def test_force_send_bypasses_only_cooldown_and_confirms_today(self):
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
                ) as select,
                patch(
                    "telegrambot.__main__.send_rich_message",
                    new=AsyncMock(return_value=456),
                ) as send,
            ):
                self.assertEqual(await _run_command("product-awards-force"), 0)

            send.assert_awaited_once()
            select.assert_called_once()
            self.assertTrue(select.call_args.kwargs["ignore_cooldown"])
            state = ProductAwardState(state_path)
            self.assertIn(item.candidate.event_id, state.published_events())
            self.assertIsNone(state.uncertain_event())
            self.assertIsNotNone(state._read()["last_delivery_day"])

    async def test_remote_media_rejection_uploads_same_candidate_and_confirms(self):
        item = publication()
        media_error = TelegramError(
            "bad request",
            retryable=False,
            code="REMOTE-MEDIA",
            status=400,
            server_description="Bad Request: RICH_MESSAGE_PHOTO_NO_MEDIA_FOUND",
        )
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
                ) as select,
                patch(
                    "telegrambot.__main__.send_rich_message",
                    new=AsyncMock(side_effect=media_error),
                ),
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    return_value=(b"jpeg", "image/jpeg"),
                ) as fetch_image,
                patch(
                    "telegrambot.__main__.send_rich_message_with_photo_upload",
                    new=AsyncMock(return_value=789),
                ) as upload,
            ):
                self.assertEqual(await _run_command("product-awards-force"), 0)

            select.assert_called_once()
            fetch_image.assert_called_once()
            resolved_image = fetch_image.call_args.args[0]
            self.assertEqual(resolved_image.url, item.offer.image_url)
            self.assertIn(
                "cdn-consum.aktiosdigitalservices.com",
                resolved_image.hosts,
            )
            upload.assert_awaited_once()
            self.assertIn(
                "tg://photo?id=product_photo",
                upload.call_args.args[2],
            )
            state = ProductAwardState(state_path)
            self.assertIn(item.candidate.event_id, state.published_events())
            self.assertIsNone(state.uncertain_event())
            self.assertFalse(
                list(Path(directory).glob(".product-award-media-*"))
            )

    async def test_failed_local_media_recovery_sends_same_candidate_without_image(self):
        item = publication()
        media_error = TelegramError(
            "bad request",
            retryable=False,
            code="REMOTE-MEDIA",
            status=400,
        )
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
                ) as select,
                patch(
                    "telegrambot.__main__.send_rich_message",
                    new=AsyncMock(side_effect=(media_error, 789)),
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    side_effect=ProductAwardError("media", code="MEDIA-NETWORK"),
                ) as fetch_image,
            ):
                self.assertEqual(await _run_command("product-awards-force"), 0)

            select.assert_called_once()
            fetch_image.assert_called_once()
            resolved_image = fetch_image.call_args.args[0]
            self.assertEqual(resolved_image.url, item.offer.image_url)
            self.assertIn(
                "cdn-consum.aktiosdigitalservices.com",
                resolved_image.hosts,
            )
            self.assertEqual(send.await_count, 2)
            self.assertIn("<img", send.await_args_list[0].args[2])
            self.assertNotIn("<img", send.await_args_list[1].args[2])

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
                    "telegrambot.__main__.send_rich_message",
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
                server_description="Bad Request: exact diagnostic",
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
                    "telegrambot.__main__.send_rich_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await _run_command("product-awards")

            self.assertIsNone(ProductAwardState(state_path).uncertain_event())


if __name__ == "__main__":
    unittest.main()
