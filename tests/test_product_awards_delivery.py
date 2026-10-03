import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from telegrambot.__main__ import _deliver_product_award
from telegrambot.product_awards import (
    ProductAwardError,
    ProductAwardPublication,
    ProductAwardState,
    ResolvedProductImage,
    RetailOffer,
    ReviewedCandidate,
    build_message,
)
from telegrambot.telegram import TelegramError


def publication(*, image_url="https://cdn-consum.aktiosdigitalservices.com/product.jpg"):
    candidate = ReviewedCandidate(
        category_key="snacks",
        selection_key="snacks:2026",
        event_id="snacks:test:product",
        source_name="OCU",
        source_kind="ocu",
        source_url="https://award.example/result",
        source_hosts=frozenset({"award.example"}),
        source_markers=("winner",),
        retailer="Consum",
        retailer_kind="consum",
        retailer_url="https://tienda.consum.es/api/product/7",
        retailer_hosts=frozenset({"tienda.consum.es"}),
        retailer_markers=("Exact", "Product"),
        product_name="Exact Product",
        award_year=2026,
        source_category="Snacks",
        award_scope="exact_product",
        award_result="90/100",
        product_id=7,
        expected_ean="8410000000000",
    )
    offer = RetailOffer(
        retailer="Consum",
        price="2,50 €",
        image_url=image_url,
        product_name="Exact Product",
    )
    return ProductAwardPublication(
        candidate=candidate,
        offer=offer,
        message=build_message(candidate, offer),
    )


def remote_media_error():
    return TelegramError(
        "remote media",
        retryable=False,
        code="REMOTE-MEDIA",
        status=400,
        description="Telegram could not fetch media",
    )


class ProductAwardDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deterministic_first_image_failure_tries_second_reviewed_image(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            first = ResolvedProductImage(
                url="https://brand.example/first.jpg",
                hosts=frozenset({"brand.example"}),
                source_name="brand",
            )
            second = ResolvedProductImage(
                url="https://retailer.example/second.jpg",
                hosts=frozenset({"retailer.example"}),
                source_name="retailer",
            )
            with (
                patch(
                    "telegrambot.__main__.iter_product_award_images",
                    return_value=iter((first, second)),
                ),
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=[remote_media_error(), 201],
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    side_effect=ProductAwardError(
                        "brand image missing",
                        code="MEDIA-HTTP-404",
                    ),
                ) as fetch,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertEqual(message_id, 201)
            self.assertEqual(send.await_count, 2)
            self.assertIn(first.url, send.await_args_list[0].args[2])
            self.assertIn(second.url, send.await_args_list[1].args[2])
            fetch.assert_called_once_with(first)
            self.assertIn(item.candidate.event_id, state.published_events())

    async def test_ambiguous_first_image_never_attempts_second_image(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            first = ResolvedProductImage(
                url="https://brand.example/first.jpg",
                hosts=frozenset({"brand.example"}),
                source_name="brand",
            )
            second = ResolvedProductImage(
                url="https://retailer.example/second.jpg",
                hosts=frozenset({"retailer.example"}),
                source_name="retailer",
            )
            ambiguous = TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )
            with (
                patch(
                    "telegrambot.__main__.iter_product_award_images",
                    return_value=iter((first, second)),
                ),
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=ambiguous,
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                ) as fetch,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertIsNone(message_id)
            send.assert_awaited_once()
            self.assertIn(first.url, send.await_args.args[2])
            fetch.assert_not_called()
            self.assertEqual(state.uncertain_event(), item.candidate.event_id)

    async def test_local_media_failure_falls_back_to_no_image_rich_message(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            with (
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=[remote_media_error(), 103],
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    side_effect=ProductAwardError(
                        "missing image",
                        code="MEDIA-HTTP-404",
                    ),
                ) as fetch,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertEqual(message_id, 103)
            self.assertEqual(send.await_count, 2)
            self.assertIn("<img", send.await_args_list[0].args[2])
            self.assertNotIn("<img", send.await_args_list[1].args[2])
            fetch.assert_called_once()
            self.assertIn(item.candidate.event_id, state.published_events())
            self.assertEqual(state.last_delivery_day(), date(2026, 10, 3))
            self.assertIsNone(state.uncertain_event())

    async def test_uploaded_media_rejection_falls_back_to_no_image(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            upload_rejection = TelegramError(
                "upload rejected",
                retryable=False,
                code="HTTP-400",
                status=400,
                description="Telegram rejected upload",
            )
            with (
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=[remote_media_error(), 104],
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    return_value=(b"jpeg", "image/jpeg"),
                ),
                patch(
                    "telegrambot.__main__.send_rich_message_with_photo_upload",
                    side_effect=upload_rejection,
                ) as upload,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertEqual(message_id, 104)
            upload.assert_awaited_once()
            self.assertEqual(send.await_count, 2)
            self.assertNotIn("<img", send.await_args_list[1].args[2])
            self.assertIsNone(state.uncertain_event())

    async def test_ambiguous_uploaded_media_delivery_never_falls_through(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            ambiguous = TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )
            with (
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=remote_media_error(),
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                    return_value=(b"jpeg", "image/jpeg"),
                ),
                patch(
                    "telegrambot.__main__.send_rich_message_with_photo_upload",
                    side_effect=ambiguous,
                ) as upload,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertIsNone(message_id)
            send.assert_awaited_once()
            upload.assert_awaited_once()
            self.assertEqual(state.uncertain_event(), item.candidate.event_id)
            self.assertNotIn(item.candidate.event_id, state.published_events())

    async def test_ambiguous_remote_delivery_never_falls_through(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication()
            ambiguous = TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )
            with (
                patch(
                    "telegrambot.__main__.send_rich_message",
                    side_effect=ambiguous,
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                ) as fetch,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertIsNone(message_id)
            send.assert_awaited_once()
            fetch.assert_not_called()
            self.assertEqual(state.uncertain_event(), item.candidate.event_id)
            self.assertNotIn(item.candidate.event_id, state.published_events())

    async def test_offer_without_image_delivers_once_without_media_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            item = publication(image_url=None)
            self.assertNotIn("<img", item.message)
            with (
                patch(
                    "telegrambot.__main__.send_rich_message",
                    return_value=105,
                ) as send,
                patch(
                    "telegrambot.__main__.fetch_product_award_image",
                ) as fetch,
                patch(
                    "telegrambot.__main__.send_rich_message_with_photo_upload",
                ) as upload,
            ):
                message_id = await _deliver_product_award(
                    state,
                    0,
                    item,
                    "token",
                    "chat",
                    date(2026, 10, 3),
                )

            self.assertEqual(message_id, 105)
            send.assert_awaited_once()
            fetch.assert_not_called()
            upload.assert_not_called()
            self.assertIn(item.candidate.event_id, state.published_events())


if __name__ == "__main__":
    unittest.main()
