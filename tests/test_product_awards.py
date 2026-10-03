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
    ResolvedProductImage,
    RetailOffer,
    ReviewedCandidate,
    ReviewedCategory,
    ReviewedImageSource,
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
    source_kind: str = "ocu",
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
        award_result="90/100",
        product_id=7,
        expected_ean="8410000000000",
        rank=rank,
    )


def offer(
    *,
    price: str = "2,50 €",
    regular_price=None,
    product_name: str = "Exact Product",
    image_url="https://cdn.example/product.jpg",
) -> RetailOffer:
    return RetailOffer(
        retailer="Test Market",
        price=price,
        regular_price=regular_price,
        image_url=image_url,
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

    def test_registry_is_quality_first_and_has_expected_retailers(self):
        items = [
            item
            for category in awards.CATEGORIES
            for source in category.sources
            for item in source.candidates
        ]

        self.assertEqual(len(awards.CATEGORIES), 7)
        self.assertFalse(any(item.source_kind == "producto_del_ano" for item in items))
        self.assertEqual(
            {item.category_key for item in items},
            {
                "sparkling_cava",
                "gazpacho",
                "aove",
                "coffee_capsules",
                "spirits_anis",
                "international_lager",
                "classic_pilsener",
            },
        )
        self.assertEqual(
            {item.retailer_kind for item in items},
            {"aldi", "carrefour", "dia", "consum", "masymas"},
        )

    def test_registry_identifiers_and_ordering_are_unique(self):
        categories = awards.CATEGORIES
        self.assertEqual(
            len({category.key for category in categories}),
            len(categories),
        )

        candidates = [
            item
            for category in categories
            for source in category.sources
            for item in source.candidates
        ]
        self.assertEqual(
            len({item.event_id for item in candidates}),
            len(candidates),
        )
        self.assertEqual(
            len({item.selection_key for item in candidates}),
            len(candidates),
        )

        for category in categories:
            priorities = [source.priority for source in category.sources]
            self.assertEqual(len(set(priorities)), len(priorities))
            for source in category.sources:
                ranks = [item.rank for item in source.candidates]
                self.assertEqual(len(set(ranks)), len(ranks))

    def test_html_retail_offer_uses_navigation_headers_and_exact_card_price(self):
        item = ReviewedCandidate(
            **{
                **candidate("carrefour").__dict__,
                "retailer": "Carrefour",
                "retailer_kind": "carrefour",
                "retailer_url": "https://www.carrefour.es/supermercado/product/p",
                "retailer_hosts": frozenset({"www.carrefour.es"}),
                "retailer_markers": ("Exact Product 1 l", "Maker"),
                "retailer_title": "Exact Product 1 l",
                "expected_ean": None,
            }
        )
        html_source = (
            "<html><body>"
            "<header>Exact Product 1 l 0,00 €</header>"
            "<main>Exact Product 1 l Maker 4,05 € Añadir</main>"
            "</body></html>"
        )
        with patch.object(awards, "_fetch_html", return_value=html_source) as fetch:
            result = awards._html_retail_offer(item)

        self.assertEqual(result.price, "4,05 €")
        self.assertIsNone(result.image_url)
        self.assertEqual(result.product_name, "Exact Product 1 l")
        self.assertEqual(fetch.call_args.kwargs["headers"], awards.RETAIL_NAVIGATION_HEADERS)

    def test_html_retail_offer_fails_closed_when_exact_card_is_unavailable(self):
        item = ReviewedCandidate(
            **{
                **candidate("dia").__dict__,
                "retailer": "DIA",
                "retailer_kind": "dia",
                "retailer_url": "https://www.dia.es/category/p/1",
                "retailer_hosts": frozenset({"www.dia.es"}),
                "retailer_markers": ("Exact Product", "Maker"),
                "retailer_title": "Exact Product",
                "expected_ean": None,
            }
        )
        html_source = (
            "<html><body>Exact Product Maker temporalmente agotado "
            "3,80 € Añadir</body></html>"
        )
        with patch.object(awards, "_fetch_html", return_value=html_source):
            with self.assertRaises(awards.ProductAwardError) as caught:
                awards._html_retail_offer(item)

        self.assertEqual(caught.exception.diagnostic_code, "RETAIL-UNAVAILABLE")

    def test_html_retail_offer_requires_all_exact_markers(self):
        item = ReviewedCandidate(
            **{
                **candidate("markers").__dict__,
                "retailer": "Carrefour",
                "retailer_kind": "carrefour",
                "retailer_url": "https://www.carrefour.es/supermercado/product/p",
                "retailer_hosts": frozenset({"www.carrefour.es"}),
                "retailer_markers": ("Exact Product", "Required Maker"),
                "retailer_title": "Exact Product",
                "expected_ean": None,
            }
        )
        with patch.object(
            awards,
            "_fetch_html",
            return_value="<html><body>Exact Product 4,05 € Añadir</body></html>",
        ):
            with self.assertRaises(awards.ProductAwardError) as caught:
                awards._html_retail_offer(item)

        self.assertEqual(caught.exception.diagnostic_code, "RETAIL-DRIFT")

    def test_product_image_download_uses_resolved_source_hosts(self):
        url = (
            "https://cdn-consum.aktiosdigitalservices.com/"
            "tol/consum/media/product/img/300x300/product.jpg"
        )
        image = ResolvedProductImage(
            url=url,
            hosts=frozenset({"cdn-consum.aktiosdigitalservices.com"}),
            source_name="Consum exact product",
        )
        with patch.object(
            awards,
            "fetch_bounded",
            return_value=(b"jpeg", url, "image/jpeg"),
        ) as fetch:
            payload, content_type = awards.fetch_product_image(image)

        self.assertEqual(payload, b"jpeg")
        self.assertEqual(content_type, "image/jpeg")
        allow = fetch.call_args.kwargs["is_allowed_url"]
        self.assertTrue(allow(url))
        self.assertFalse(allow("https://example.com/product.jpg"))
        self.assertEqual(fetch.call_args.kwargs["limit_bytes"], awards.IMAGE_LIMIT_BYTES)

    def test_reviewed_image_source_prefers_exact_alt_match(self):
        source = ReviewedImageSource(
            name="Brand product",
            page_url="https://brand.example/product",
            page_hosts=frozenset({"brand.example"}),
            image_hosts=frozenset({"brand.example"}),
            page_markers=("Exact Product", "1 L"),
            image_alt_markers=("Exact Product",),
        )
        html_source = (
            '<html><head><meta property="og:image" '
            'content="https://brand.example/generic.jpg"></head>'
            '<body><h1>Exact Product</h1><p>1 L</p>'
            '<img alt="Exact Product front" src="/exact.jpg"></body></html>'
        )
        with patch.object(awards, "_fetch_html", return_value=html_source):
            image = awards._resolve_reviewed_image_source(source)

        self.assertEqual(image.url, "https://brand.example/exact.jpg")
        self.assertEqual(image.source_name, "Brand product")

    def test_reviewed_image_source_rejects_unapproved_image_host(self):
        source = ReviewedImageSource(
            name="Brand product",
            page_url="https://brand.example/product",
            page_hosts=frozenset({"brand.example"}),
            image_hosts=frozenset({"brand.example"}),
            page_markers=("Exact Product",),
            image_alt_markers=("Exact Product",),
        )
        html_source = (
            '<html><body><h1>Exact Product</h1>'
            '<img alt="Exact Product" src="https://cdn.other.example/exact.jpg">'
            '</body></html>'
        )
        with patch.object(awards, "_fetch_html", return_value=html_source):
            with self.assertRaises(awards.ProductAwardError) as caught:
                awards._resolve_reviewed_image_source(source)

        self.assertEqual(caught.exception.diagnostic_code, "MEDIA-DRIFT")

    def test_consum_detail_requires_exact_ean_and_returns_media(self):
        item = candidate("retail")
        payload = {
            "ean": item.expected_ean,
            "productData": {
                "name": "Exact Product",
                "imageURL": (
                    "https://cdn-consum.aktiosdigitalservices.com/"
                    "tol/consum/media/product/img/300x300/product.jpg"
                ),
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
        self.assertEqual(
            result.image_url,
            "https://cdn-consum.aktiosdigitalservices.com/"
            "tol/consum/media/product/img/300x300/product.jpg",
        )

    def test_consum_prefers_media_array_over_stale_base_image(self):
        item = candidate("retail-media")
        payload = {
            "ean": item.expected_ean,
            "productData": {
                "name": "Exact Product",
                "imageURL": (
                    "https://cdn-consum.aktiosdigitalservices.com/"
                    "tol/consum/media/product/img/300x300/7.jpg"
                ),
            },
            "media": [
                {
                    "url": (
                        "https://cdn-consum.aktiosdigitalservices.com/"
                        "tol/consum/media/product/img/300x300/7_001.jpg"
                    )
                }
            ],
            "priceData": {
                "prices": [
                    {"id": "PRICE", "value": {"centAmount": 2.50}},
                ],
            },
        }
        with patch.object(awards, "_fetch_json", return_value=payload):
            result = _tol_offer(item)

        self.assertTrue(result.image_url.endswith("/7_001.jpg"))

    def test_consum_ignores_unreviewed_media_hosts(self):
        item = candidate("retail-host")
        payload = {
            "ean": item.expected_ean,
            "productData": {
                "name": "Exact Product",
                "imageURL": "https://untrusted.example/base.jpg",
            },
            "media": [
                {"url": "https://untrusted.example/product_001.jpg"},
            ],
            "priceData": {
                "prices": [
                    {"id": "PRICE", "value": {"centAmount": 2.50}},
                ],
            },
        }
        with patch.object(awards, "_fetch_json", return_value=payload):
            result = _tol_offer(item)

        self.assertIsNone(result.image_url)

    def test_consum_missing_media_keeps_exact_offer_publishable(self):
        item = candidate("retail-no-media")
        payload = {
            "ean": item.expected_ean,
            "productData": {"name": "Exact Product"},
            "priceData": {
                "prices": [
                    {"id": "PRICE", "value": {"centAmount": 2.50}},
                ],
            },
        }
        with patch.object(awards, "_fetch_json", return_value=payload):
            result = _tol_offer(item)

        self.assertIsNone(result.image_url)
        self.assertEqual(result.price, "2,50 €")

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
                    "apiData": json.dumps([
                        {},
                        {
                            "res": {
                                "products": [{
                                    "objectID": "190300",
                                    "brandName": "NALTROS ®",
                                    "name": "Cava brut",
                                    "salesUnit": "0,75 l unidad",
                                    "productReferences": [{
                                        "type": "KVArticleNumber",
                                        "value": "1903",
                                    }],
                                    "isAvailable": True,
                                    "isComingSoon": False,
                                    "isRecall": False,
                                    "currentPrice": {"priceValue": 3.15},
                                    "assets": [{
                                        "type": "primary",
                                        "url": "https://s7g10.scene7.com/is/image/aldinord/cava",
                                    }],
                                }]
                            }
                        },
                    ])
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


    def test_aldi_missing_primary_media_keeps_offer_publishable(self):
        item = ReviewedCandidate(
            **{
                **candidate("aldi-no-media").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
                "retailer_url": "https://www.aldi.es/p/cava-brut-190300.html",
                "retailer_hosts": frozenset({"www.aldi.es", "aldi.es"}),
                "retailer_markers": ("NALTROS", "Cava brut", "0,75 l"),
                "product_id": 190300,
                "expected_ean": None,
            }
        )
        payload = {
            "props": {
                "pageProps": {
                    "apiData": json.dumps([{
                        "objectID": "190300",
                        "brandName": "NALTROS",
                        "name": "Cava brut",
                        "salesUnit": "0,75 l unidad",
                        "isAvailable": True,
                        "isComingSoon": False,
                        "isRecall": False,
                        "currentPrice": {"priceValue": 3.15},
                        "assets": [],
                    }])
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
        self.assertIsNone(result.image_url)

    def test_aldi_explicit_page_error_is_not_generic_drift(self):
        item = ReviewedCandidate(
            **{
                **candidate("aldi-error").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
                "retailer_url": "https://www.aldi.es/p/cava-brut-190300.html",
                "retailer_hosts": frozenset({"www.aldi.es", "aldi.es"}),
                "retailer_markers": ("NALTROS",),
                "product_id": 190300,
                "expected_ean": None,
            }
        )
        source = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({
                "props": {
                    "pageProps": {
                        "hasError": True,
                        "page": None,
                        "apiData": None,
                    }
                }
            })
            + "</script>"
        )

        with self.assertRaises(awards.ProductAwardError) as caught:
            _aldi_offer(item, source)

        self.assertEqual(caught.exception.diagnostic_code, "RETAIL-PAGE-ERROR")

    def test_aldi_missing_api_data_without_error_remains_drift(self):
        item = ReviewedCandidate(
            **{
                **candidate("aldi-drift").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
                "retailer_url": "https://www.aldi.es/p/cava-brut-190300.html",
                "retailer_hosts": frozenset({"www.aldi.es", "aldi.es"}),
                "retailer_markers": ("NALTROS",),
                "product_id": 190300,
                "expected_ean": None,
            }
        )
        source = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"apiData": None}}})
            + "</script>"
        )

        with self.assertRaises(awards.ProductAwardError) as caught:
            _aldi_offer(item, source)

        self.assertEqual(caught.exception.diagnostic_code, "RETAIL-DRIFT")


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

    def test_rich_message_can_render_without_image(self):
        item = candidate("no-image")
        message = build_message(item, offer(image_url=None))

        self.assertNotIn("<img", message)
        self.assertIn("2,50 €", message)
        self.assertIn("обЪявления Гуардамар", message)

    def test_rich_message_can_explicitly_omit_available_image(self):
        item = candidate("no-image-explicit")
        message = build_message(item, offer(), include_image=False)

        self.assertNotIn("<img", message)

    def test_generic_ocu_renderer_uses_category_sample_and_result(self):
        item = ReviewedCandidate(
            **{
                **candidate("gazpacho").__dict__,
                "source_kind": "ocu",
                "product_name": "Realfooding Gazpacho",
                "source_category": "gazpachos",
                "award_result": "Mejor del Análisis, 90/100",
                "sample_size": 39,
            }
        )
        message = build_message(item, offer(price="4,05 €"))

        self.assertIn("39 продуктов", message)
        self.assertIn("gazpachos", message)
        self.assertIn("Mejor del Análisis, 90/100", message)
        self.assertIn("физически тестировала", message)
        self.assertNotIn("25 cava", message)

    def test_mapa_renderer_names_official_winner_without_score(self):
        item = ReviewedCandidate(
            **{
                **candidate("mapa").__dict__,
                "source_kind": "mapa",
                "product_name": "Anís Chinchón Dulce",
                "source_category": "Mejor Bebida Espirituosa con Indicación Geográfica",
                "award_result": "Galardonado 2026",
                "award_year": 2026,
            }
        )
        message = build_message(item, offer(price="13,79 €"))

        self.assertIn("Premio Alimentos de España 2026", message)
        self.assertIn("Test Market", message)
        self.assertIn("Министерство сельского хозяйства Испании", message)
        self.assertIn("Mejor Bebida Espirituosa", message)
        self.assertNotIn("/100", message)

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

        self.assertIn("Ambar Especial — World Beer Awards 2026 · Test Market", message)
        self.assertIn("победителем Испании", message)
        self.assertIn("0,75 €", message)
        self.assertIn("0,89 €", message)
        self.assertNotIn("Ambar Especial - бронзу", message)

    def test_ocu_sample_count_uses_correct_russian_declension(self):
        item = ReviewedCandidate(
            **{
                **candidate("aove").__dict__,
                "sample_size": 23,
            }
        )
        message = build_message(item, offer())
        self.assertIn("23 продукта", message)
        self.assertNotIn("23 продуктов", message)

    def test_editorial_contract_includes_retailer_package_country_producer_and_highlight(self):
        item = ReviewedCandidate(
            **{
                **candidate("editorial").__dict__,
                "retailer": "Carrefour",
                "retailer_kind": "carrefour",
                "headline_award": "Mejor del Análisis OCU",
                "package_label": "1 л, PET",
                "country_label": "Испания",
                "producer_label": "CAÑA NATURE, S.L.U.",
                "highlight": "90/100 и лучший результат дегустации.",
            }
        )
        message = build_message(item, offer(price="3,99 €"))

        self.assertIn(
            "Exact Product — Mejor del Análisis OCU · Carrefour",
            message,
        )
        self.assertIn("📦 1 л, PET", message)
        self.assertIn("🌍 Испания", message)
        self.assertIn("🏭 CAÑA NATURE, S.L.U.", message)
        self.assertIn("Почему выделился", message)
        self.assertIn("На сайте Carrefour сейчас указана цена", message)
        headline = message.split("</p>", 1)[0]
        self.assertNotIn("90/100", headline)

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
        self.assertIn("25 продуктов", message)
        self.assertIn("cava", message)
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


    def test_current_production_state_shape_is_valid_after_registry_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-29",
                    "published_events": [
                        "classic_pilsener:wba-2026:mahou-sin-filtrar",
                    ],
                    "published_selections": ["classic_pilsener:2026"],
                    "category_cursor": 0,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            state = ProductAwardState(path)

            self.assertEqual(state.category_cursor(), 0)
            self.assertEqual(
                state.last_published_event_id(),
                "classic_pilsener:wba-2026:mahou-sin-filtrar",
            )
            self.assertTrue(state.has_unpublished())
            self.assertEqual(
                awards._retailer_for_event(state.last_published_event_id()),
                "masymas",
            )

    def test_last_published_event_preserves_confirmation_order(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.mark_uncertain("first")
            state.confirm("first", "first:2026", 0, date(2026, 9, 27))
            state.mark_uncertain("second")
            state.confirm("second", "second:2026", 1, date(2026, 9, 30))

            self.assertEqual(state.last_published_event_id(), "second")


class SelectionTests(unittest.TestCase):
    def test_unknown_previous_event_does_not_block_ordinary_selection(self):
        current = candidate("current", "current")
        categories = (
            ReviewedCategory(
                "current",
                (ReviewedSource("current", 1, (current,)),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-27",
                    "published_events": ["removed:event"],
                    "published_selections": ["removed:2026"],
                    "category_cursor": 0,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award"),
                patch.object(awards, "_refresh_offer", return_value=offer()),
            ):
                selected = select_publication(
                    datetime(2026, 9, 30, 14, 20, tzinfo=MADRID),
                    ProductAwardState(path),
                )

        self.assertEqual(selected[1].candidate.event_id, current.event_id)

    def test_prefers_later_different_retailer_over_same_retailer_fallback(self):
        previous = candidate("previous", "previous")
        same = candidate("same", "same")
        different = ReviewedCandidate(
            **{
                **candidate("different", "different").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
            }
        )
        categories = (
            ReviewedCategory(
                "previous",
                (ReviewedSource("history", 1, (previous,)),),
            ),
            ReviewedCategory(
                "same",
                (ReviewedSource("same", 1, (same,)),),
            ),
            ReviewedCategory(
                "different",
                (ReviewedSource("different", 1, (different,)),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-27",
                    "published_events": [previous.event_id],
                    "published_selections": [previous.selection_key],
                    "category_cursor": 1,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer", return_value=offer()) as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 30, 14, 20, tzinfo=MADRID),
                    ProductAwardState(path),
                )

        self.assertEqual(selected[1].candidate.event_id, different.event_id)
        self.assertEqual(
            [call.args[0].event_id for call in verify.call_args_list],
            [same.event_id, different.event_id],
        )
        self.assertEqual(refresh.call_count, 2)

    def test_same_retailer_fallback_publishes_when_no_alternative_is_valid(self):
        previous = candidate("previous", "previous")
        same = candidate("same", "same")
        unavailable = ReviewedCandidate(
            **{
                **candidate("unavailable", "other").__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
            }
        )
        categories = (
            ReviewedCategory(
                "previous",
                (ReviewedSource("history", 1, (previous,)),),
            ),
            ReviewedCategory(
                "same",
                (ReviewedSource("same", 1, (same,)),),
            ),
            ReviewedCategory(
                "other",
                (ReviewedSource("other", 1, (unavailable,)),),
            ),
        )

        def refresh(item):
            if item.event_id == unavailable.event_id:
                raise awards.ProductAwardError("gone", code="TEST")
            return offer()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-27",
                    "published_events": [previous.event_id],
                    "published_selections": [previous.selection_key],
                    "category_cursor": 1,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award"),
                patch.object(awards, "_refresh_offer", side_effect=refresh),
            ):
                selected = select_publication(
                    datetime(2026, 9, 30, 14, 20, tzinfo=MADRID),
                    ProductAwardState(path),
                )

        self.assertEqual(selected[1].candidate.event_id, same.event_id)

    def test_retailer_preference_does_not_demote_within_category(self):
        previous = candidate("previous", "previous")
        first = candidate("first", "ranked", rank=1)
        second = ReviewedCandidate(
            **{
                **candidate("second", "ranked", rank=2).__dict__,
                "retailer": "ALDI",
                "retailer_kind": "aldi",
            }
        )
        categories = (
            ReviewedCategory(
                "previous",
                (ReviewedSource("history", 1, (previous,)),),
            ),
            ReviewedCategory(
                "ranked",
                (ReviewedSource("ranked", 1, (first, second)),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-27",
                    "published_events": [previous.event_id],
                    "published_selections": [previous.selection_key],
                    "category_cursor": 1,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer", return_value=offer()),
            ):
                selected = select_publication(
                    datetime(2026, 9, 30, 14, 20, tzinfo=MADRID),
                    ProductAwardState(path),
                )

        self.assertEqual(selected[1].candidate.event_id, first.event_id)
        self.assertEqual(
            [call.args[0].event_id for call in verify.call_args_list],
            [first.event_id],
        )

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

    def test_cooldown_bypass_selects_next_unpublished_category(self):
        first = candidate("first", "first")
        second = candidate("second", "second")
        categories = (
            ReviewedCategory(
                key="first",
                sources=(ReviewedSource("A", 1, (first,)),),
            ),
            ReviewedCategory(
                key="second",
                sources=(ReviewedSource("B", 1, (second,)),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": "2026-09-28",
                    "published_events": [first.event_id],
                    "published_selections": [first.selection_key],
                    "category_cursor": 1,
                    "uncertain_event": None,
                }),
                encoding="utf-8",
            )
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer", return_value=offer()) as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 29, 10, 45, tzinfo=MADRID),
                    ProductAwardState(path),
                    ignore_cooldown=True,
                )

        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], 1)
        self.assertEqual(selected[1].candidate.event_id, second.event_id)
        verify.assert_called_once_with(second)
        refresh.assert_called_once_with(second)

    def test_cooldown_bypass_cannot_publish_twice_on_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            today = date(2026, 9, 29)
            state.mark_uncertain("already")
            state.confirm("already", "already:2026", 0, today)
            with (
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer") as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 29, 18, 0, tzinfo=MADRID),
                    state,
                    ignore_cooldown=True,
                )

        self.assertIsNone(selected)
        verify.assert_not_called()
        refresh.assert_not_called()

    def test_cooldown_bypass_does_not_override_uncertain_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.mark_uncertain("ambiguous")
            with (
                patch.object(awards, "_verify_award") as verify,
                patch.object(awards, "_refresh_offer") as refresh,
            ):
                selected = select_publication(
                    datetime(2026, 9, 29, 10, 45, tzinfo=MADRID),
                    state,
                    ignore_cooldown=True,
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
