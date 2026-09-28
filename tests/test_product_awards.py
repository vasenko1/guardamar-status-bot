import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import telegrambot.product_awards as awards
from telegrambot.product_awards import (
    ProductAwardState,
    RetailOffer,
    ReviewedCandidate,
    ReviewedCategory,
    ReviewedSource,
    _aldi_offer,
    _tol_offer,
    build_message,
    select_publication,
)


MADRID = ZoneInfo("Europe/Madrid")


def candidate(
    event_id: str,
    category: str = "test",
    *,
    rank: int = 1,
    source_kind: str = "producto_del_ano",
    award_scope: str = "exact_product",
) -> ReviewedCandidate:
    return ReviewedCandidate(
        category_key=category,
        selection_key=f"{category}:2026",
        event_id=event_id,
        source_name="Test Award",
        source_kind=source_kind,
        source_url="https://award.example/result",
        source_hosts=frozenset({"award.example"}),
        source_markers=("winner",),
        retailer="Test Market",
        retailer_kind="consum",
        retailer_url="https://shop.example/api/product/7",
        retailer_hosts=frozenset({"shop.example"}),
        retailer_markers=("Exact", "Product"),
        product_name="Exact Product",
        award_year=2026,
        source_category="Snacks",
        award_scope=award_scope,
        award_result="Producto del Año",
        product_id=7,
        expected_ean="8410000000000",
        rank=rank,
    )


def offer(
    *,
    price: str = "2,50 €",
    regular_price=None,
    product_name: str = "Exact Product",
) -> RetailOffer:
    return RetailOffer(
        retailer="Test Market",
        price=price,
        regular_price=regular_price,
        image_url="https://cdn.example/product.jpg",
        product_name=product_name,
    )


class SourceContractTests(unittest.TestCase):
    def test_award_fetch_keeps_lightweight_headers(self):
        item = candidate("award")
        with patch.object(
            awards,
            "fetch_bounded",
            return_value=(
                b"<html><body>winner</body></html>",
                item.source_url,
                "text/html",
            ),
        ) as fetch:
            awards._verify_award(item)

        headers = fetch.call_args.kwargs["headers"]
        self.assertEqual(headers["User-Agent"], awards.USER_AGENT)
        self.assertNotIn("Sec-Fetch-Mode", headers)

    def test_consum_detail_requires_exact_ean_and_returns_media(self):
        item = candidate("retail")
        payload = {
            "ean": item.expected_ean,
            "productData": {
                "name": "Exact Product",
                "imageURL": "https://cdn.example/product.jpg",
            },
            "priceData": {
                "prices": [
                    {
                        "id": "PRICE",
                        "value": {"centAmount": 2.50},
                    },
                    {
                        "id": "OFFER_PRICE",
                        "value": {"centAmount": 2.00},
                    },
                ],
            },
        }
        with patch.object(awards, "_fetch_json", return_value=payload):
            result = _tol_offer(item)

        self.assertEqual(result.price, "2,00 €")
        self.assertEqual(result.regular_price, "2,50 €")
        self.assertEqual(result.product_name, "Exact Product")
        self.assertEqual(result.image_url, "https://cdn.example/product.jpg")

    def test_consum_detail_rejects_ean_drift(self):
        item = candidate("retail")
        payload = {
            "ean": "999",
            "productData": {
                "name": "Exact Product",
                "imageURL": "https://cdn.example/product.jpg",
            },
            "priceData": {
                "prices": [
                    {"id": "PRICE", "value": {"centAmount": 2.50}},
                ],
            },
        }
        with patch.object(awards, "_fetch_json", return_value=payload):
            with self.assertRaises(awards.ProductAwardError) as caught:
                _tol_offer(item)
        self.assertEqual(caught.exception.diagnostic_code, "RETAIL-DRIFT")

    def test_masymas_prefers_validated_300_variant(self):
        item = ReviewedCandidate(
            **{
                **candidate("masymas").__dict__,
                "retailer_kind": "masymas",
                "retailer_url": "https://tienda.masymas.com/api/product/7",
                "retailer_hosts": frozenset({
                    "tienda.masymas.com",
                    "cdn-fornes.aktiosdigitalservices.com",
                }),
            }
        )
        payload = {
            "ean": item.expected_ean,
            "productData": {
                "name": "Exact Product",
                "imageURL": (
                    "https://cdn-fornes.aktiosdigitalservices.com/"
                    "media/135x135/product.jpg"
                ),
            },
            "priceData": {
                "prices": [
                    {"id": "PRICE", "value": {"centAmount": 1.00}},
                ],
            },
        }
        with (
            patch.object(awards, "_fetch_json", return_value=payload),
            patch.object(awards, "_image_exists", return_value=True) as image,
        ):
            result = _tol_offer(item)

        self.assertEqual(
            result.image_url,
            "https://cdn-fornes.aktiosdigitalservices.com/"
            "media/300x300/product.jpg",
        )
        image.assert_called_once()

    def test_aldi_offer_uses_object_id_and_primary_media(self):
        item = ReviewedCandidate(
            **{
                **candidate("aldi").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
                "retailer_url": "https://www.aldi.es/p/cava-brut-190300.html",
                "retailer_hosts": frozenset({"www.aldi.es", "aldi.es"}),
                "retailer_markers": ("NALTROS", "Cava brut", "0,75 l"),
                "product_name": "NALTROS Brut",
                "product_id": 190300,
                "expected_ean": None,
                "source_kind": "ocu",
                "award_result": "94/100",
            }
        )
        payload = {
            "props": {
                "pageProps": {
                    "apiData": json.dumps({
                        "items": [{
                            "objectID": "190300",
                            "brandName": "NALTROS ®",
                            "name": "Cava brut",
                            "salesUnit": "0,75 l unidad",
                            "isAvailable": True,
                            "isComingSoon": False,
                            "isRecall": False,
                            "currentPrice": {"priceValue": 3.15},
                            "assets": [{
                                "type": "primary",
                                "url": "https://s7g10.scene7.com/is/image/aldinord/cava",
                            }],
                        }]
                    })
                }
            }
        }
        source = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )
        result = _aldi_offer(item, source)

        self.assertEqual(result.price, "3,15 €")
        self.assertEqual(
            result.image_url,
            "https://s7g10.scene7.com/is/image/aldinord/cava",
        )
        self.assertIn("NALTROS", result.product_name)


class RenderingTests(unittest.TestCase):
    def test_rich_message_has_visual_paragraph_boundary_and_no_external_links(self):
        item = candidate("event")
        message = build_message(item, offer())

        self.assertIn("</p>\n<p>", message)
        self.assertIn("<blockquote expandable>", message)
        self.assertIn("<img src=", message)
        self.assertIn("2,50 €", message)
        self.assertIn("обЪявления Гуардамар", message)
        self.assertNotIn("award.example", message)
        self.assertNotIn("shop.example", message)

    def test_range_award_identifies_current_member_without_claiming_extra_win(self):
        item = candidate("range", award_scope="range")
        current = offer(product_name="Exact Product Café")
        message = build_message(item, current)

        self.assertIn("Награда относится к линейке", message)
        self.assertIn("один из продуктов этой линейки", message)
        self.assertIn("Exact Product Café", message)

    def test_world_beer_renderer_uses_natural_medal_grammar(self):
        item = ReviewedCandidate(
            **{
                **candidate("beer").__dict__,
                "source_kind": "world_beer_awards",
                "product_name": "Ambar Especial",
                "source_category": "International Lager",
                "award_result": "gold_country_winner",
            }
        )
        message = build_message(
            item,
            offer(price="0,75 €", regular_price="0,89 €"),
        )

        self.assertIn("Пиво Ambar Especial получило золото", message)
        self.assertIn("победителем Испании", message)
        self.assertIn("0,75 €", message)
        self.assertIn("0,89 €", message)
        self.assertNotIn("Ambar Especial - бронзу", message)

    def test_ocu_renderer_uses_correct_russian_score_form(self):
        item = ReviewedCandidate(
            **{
                **candidate("ocu").__dict__,
                "source_kind": "ocu",
                "product_name": "NALTROS Brut",
                "source_category": "cava",
                "award_result": "94/100",
                "sample_size": 25,
            }
        )
        message = build_message(item, offer(price="3,15 €"))

        self.assertIn("94/100", message)
        self.assertIn("25 cava", message)
        self.assertNotIn("94 баллов", message)
        self.assertNotIn("Amarillo pajizo", message)


class StateTests(unittest.TestCase):
    def test_three_day_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            start = date(2026, 9, 27)
            state.mark_uncertain("event")
            state.confirm("event", "test:2026", 0, start)
            self.assertFalse(state.due(start + timedelta(days=1)))
            self.assertFalse(state.due(start + timedelta(days=2)))
            self.assertTrue(state.due(start + timedelta(days=3)))

    def test_uncertain_delivery_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            ProductAwardState(path).mark_uncertain("event")
            self.assertEqual(ProductAwardState(path).uncertain_event(), "event")

    def test_confirm_advances_category_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.mark_uncertain("event")
            state.confirm("event", "test:2026", 1, date(2026, 9, 27))
            self.assertIn("event", state.published_events())
            self.assertEqual(state.category_cursor(), 2)


class SelectionTests(unittest.TestCase):
    def test_cooldown_causes_zero_network_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            today = date(2026, 9, 27)
            state.mark_uncertain("already")
            state.confirm("already", "already:2026", 0, today - timedelta(days=1))
            with (
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer") as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 27, 14, 20, tzinfo=MADRID),
                    state,
                )
            self.assertIsNone(selected)
            verify.assert_not_called()
            refresh.assert_not_called()

    def test_exhausted_registry_causes_zero_network_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            published = [
                item.event_id
                for category in awards.CATEGORIES
                for source in category.sources
                for item in source.candidates
            ]
            selections = [
                item.selection_key
                for category in awards.CATEGORIES
                for source in category.sources
                for item in source.candidates
            ]
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": None,
                    "published_events": published,
                    "published_selections": selections,
                    "category_cursor": 0,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            state = ProductAwardState(path)
            with (
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer") as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 27, 14, 20, tzinfo=MADRID),
                    state,
                )
        self.assertIsNone(selected)
        verify.assert_not_called()
        refresh.assert_not_called()

    def test_source_rank_order_is_preserved(self):
        first = candidate("first", rank=1)
        second = candidate("second", rank=2)
        fallback = candidate("fallback", rank=1)
        categories = (
            ReviewedCategory(
                "test",
                (
                    ReviewedSource("primary", 1, (first, second)),
                    ReviewedSource("secondary", 2, (fallback,)),
                ),
            ),
        )
        calls = []

        def verify(item):
            calls.append(("award", item.event_id))

        def refresh(item):
            calls.append(("retail", item.event_id))
            if item.event_id == "second":
                return offer()
            raise awards.ProductAwardError("unavailable", code="TEST")

        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award", side_effect=verify),
                patch.object(awards, "_refresh_offer", side_effect=refresh),
            ):
                selected = select_publication(
                    datetime(2026, 9, 27, 14, 20, tzinfo=MADRID),
                    state,
                )

        self.assertIsNotNone(selected)
        self.assertEqual(selected[1].candidate.event_id, "second")
        self.assertEqual(
            calls,
            [
                ("award", "first"),
                ("retail", "first"),
                ("award", "second"),
                ("retail", "second"),
            ],
        )

    def test_published_selection_blocks_other_ranked_candidates(self):
        first = candidate("first", rank=1)
        second = candidate("second", rank=2)
        categories = (
            ReviewedCategory(
                "test",
                (ReviewedSource("primary", 1, (first, second)),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": None,
                    "published_events": ["first"],
                    "published_selections": ["test:2026"],
                    "category_cursor": 0,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            state = ProductAwardState(path)
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer") as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 30, 14, 20, tzinfo=MADRID),
                    state,
                )
        self.assertIsNone(selected)
        verify.assert_not_called()
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
