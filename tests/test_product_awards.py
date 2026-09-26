import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.product_awards import (
    AwardEditorialFacts,
    AwardSourceAdapter,
    AwardSourceItem,
    PageDocument,
    ProductAwardCandidate,
    ProductAwardError,
    ProductAwardState,
    RetailEvidence,
    RetailOfferVariant,
    _ocu_product_name,
    _resolve_private_label,
    build_current_publication,
    build_publication,
    discover_ocu_documents,
    discover_product_awards,
    load_ocu_item,
    parse_ocu_awards,
    parse_wccc_top20,
    refresh_mercadona_offers,
    scan_next_product_award,
)

MADRID = ZoneInfo("Europe/Madrid")


def candidate(
    *,
    source_kind="ocu",
    event_key="event-1",
    source_url="https://www.ocu.org/alimentacion/test/informe/example",
    retailer="Mercadona",
    private_label="Hacendado",
    product_name="salmorejo fresco de Hacendado",
    result="Mejor del Análisis",
    award_body="OCU",
    result_year=2026,
    score="70/100",
    source_price="3 €/л",
    sample_size=30,
):
    return ProductAwardCandidate(
        source_kind=source_kind,
        event_key=event_key,
        source_url=source_url,
        product_name=product_name,
        result=result,
        award_body=award_body,
        result_year=result_year,
        retail=RetailEvidence(
            retailer=retailer,
            relationship="private_label",
            label=private_label,
        ),
        score=score,
        source_price=source_price,
        editorial=AwardEditorialFacts(comparison_size=sample_size),
    )


class OcuAdapterTests(unittest.TestCase):
    def test_discovery_keeps_only_food_reports(self):
        page = PageDocument(
            url="https://www.ocu.org/ocu-salud",
            text="index",
            links=(
                "https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos?x=1",
                "https://www.ocu.org/alimentacion/dulces/noticias/helados",
                "https://www.ocu.org/alimentacion/leche",
                "https://www.ocu.org/salud/informe/foo",
            ),
        )
        with patch("telegrambot.product_awards._fetch_page", return_value=page):
            self.assertEqual(
                discover_ocu_documents(2026),
                (
                    "https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos",
                ),
            )

    def test_known_salmorejo_report_is_parsed_without_llm(self):
        text = """
        Informe
        Los mejores salmorejos envasados de 2026
        07 julio 2026
        Hemos analizado 30 salmorejos para que elijas el que más te guste.
        Fresco de Hacendado, el mejor salmorejo
        Teniendo en cuenta todos los criterios analizados, obtenemos que el salmorejo fresco de Hacendado (Mercadona), en botella PET, es el Mejor del Análisis, con una calificación global de 70/100.
        Es el mejor valorado en la cata profesional.
        Su precio es de 3 euros/litro.
        También destacamos el salmorejo Auchan (Alcampo), en envase de brick, que es el producto Compra Maestra.
        """
        document = PageDocument(
            "https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos",
            text,
            (),
        )
        result = parse_ocu_awards(document, 2026)
        self.assertEqual(len(result), 1)
        best = result[0]

        self.assertEqual(best.retailer, "Mercadona")
        self.assertEqual(best.private_label, "Hacendado")
        self.assertEqual(best.product_name, "salmorejo fresco de Hacendado")
        self.assertEqual(best.result, "Mejor del Análisis")
        self.assertEqual(best.score, "70/100")
        self.assertEqual(best.source_price, "3 €/л")
        self.assertEqual(best.sample_size, 30)
        self.assertEqual(best.retail.relationship, "private_label")
        self.assertIn("professional_tasting", best.editorial.method_flags)
        self.assertEqual(best.editorial.standout, "best_professional_tasting")

    def test_old_report_is_ignored_in_current_year(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            "07 julio 2025. Salmorejo Hacendado (Mercadona) es el Mejor del Análisis. © 2026 OCU",
            (),
        )
        self.assertEqual(parse_ocu_awards(document, 2026), ())

    def test_private_label_requires_word_boundary(self):
        self.assertIsNone(_resolve_private_label("estudio de consumo responsable"))
        self.assertEqual(
            _resolve_private_label("producto Consum Eco obtuvo el premio"),
            ("Consum", "Consum Eco"),
        )

    def test_most_specific_carrefour_label_wins(self):
        self.assertEqual(
            _resolve_private_label(
                "Aceite de oliva virgen extra Carrefour Extra (Carrefour)"
            ),
            ("Carrefour", "Carrefour Extra"),
        )

    def test_retailer_name_in_parentheses_is_not_private_label(self):
        self.assertIsNone(
            _resolve_private_label("Yogur Danone (Carrefour) es Compra Maestra")
        )
        self.assertIsNone(
            _resolve_private_label("Yogur Danone (DIA) es Compra Maestra")
        )
        self.assertEqual(
            _resolve_private_label("leche Carrefour (Carrefour) es Compra Maestra"),
            ("Carrefour", "Carrefour"),
        )
        self.assertEqual(
            _resolve_private_label("yogur DIA (DIA) es Compra Maestra"),
            ("DIA", "DIA"),
        )


    def test_alcampo_is_outside_local_retailer_scope(self):
        self.assertIsNone(
            _resolve_private_label("salmorejo Auchan (Alcampo)")
        )

    def test_horizontal_private_labels_include_dia(self):
        self.assertEqual(
            _resolve_private_label("yogur DIA (DIA)"),
            ("DIA", "DIA"),
        )


    def test_product_name_uses_local_words_before_label(self):
        line = (
            "Teniendo en cuenta todo, obtenemos que el salmorejo fresco "
            "de Hacendado (Mercadona) es el Mejor del Análisis."
        )
        self.assertEqual(
            _ocu_product_name(line, "Hacendado"),
            "salmorejo fresco de Hacendado",
        )

    def test_ocu_split_text_nodes_still_parse_private_label_award(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/quesos/informe/quesos",
            """
            Informe
            Los mejores quesos de 2026
            10 septiembre 2026
            Hemos analizado 20 productos.
            También destacamos el
            queso curado
            Deluxe (Lidl),
            que es el producto
            Compra Maestra
            con una calificación global de 68/100.
            Su precio es de
            9,50 euros/kilo.
            """,
            (),
        )
        result = parse_ocu_awards(document, 2026)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.retailer, "Lidl")
        self.assertEqual(item.private_label, "Deluxe")
        self.assertEqual(item.product_name, "queso curado Deluxe")
        self.assertEqual(item.result, "Compra Maestra")
        self.assertEqual(item.score, "68/100")
        self.assertEqual(item.source_price, "9,50 €/кг")
        self.assertEqual(item.sample_size, 20)

    def test_price_and_score_do_not_leak_to_previous_result(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            """
            07 julio 2026
            salmorejo fresco de Hacendado (Mercadona) es el Mejor del Análisis.
            gazpacho suave Deluxe (Lidl) es Compra Maestra.
            con una calificación global de 68/100.
            Su precio es de 2,50 euros/litro.
            """,
            (),
        )
        found = parse_ocu_awards(document, 2026)
        self.assertEqual(len(found), 2)
        first, second = found
        self.assertEqual(first.private_label, "Hacendado")
        self.assertIsNone(first.score)
        self.assertIsNone(first.source_price)
        self.assertEqual(second.private_label, "Deluxe")
        self.assertEqual(second.score, "68/100")
        self.assertEqual(second.source_price, "2,50 €/л")

    def test_ocu_local_editorial_facts_do_not_leak_to_next_product(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            """
            07 julio 2026
            Hemos analizado 20 productos.
            cata profesional
            salmorejo fresco de Hacendado (Mercadona) es el Mejor del Análisis.
            Es el mejor valorado en la cata profesional.
            queso curado Deluxe (Lidl) es Compra Maestra.
            """,
            (),
        )
        first, second = parse_ocu_awards(document, 2026)
        self.assertEqual(first.editorial.standout, "best_professional_tasting")
        self.assertIsNone(second.editorial.standout)

    def test_ocu_result_precedence_is_source_specific(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            """
            07 julio 2026
            producto suave Hacendado (Mercadona) es Compra Maestra.
            producto suave Hacendado (Mercadona) es Mejor del Análisis.
            """,
            (),
        )
        found = parse_ocu_awards(document, 2026)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].result, "Mejor del Análisis")

    def test_unparseable_award_product_fails_closed(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            "07 julio 2026\nHacendado es el Mejor del Análisis.",
            (),
        )
        with self.assertRaises(ProductAwardError):
            parse_ocu_awards(document, 2026)


    def test_ocu_loader_filters_below_85_and_orders_strongest_first(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            """
            07 julio 2026
            producto premium Hacendado (Mercadona) es Mejor del Análisis.
            con una calificación global de 85/100.
            producto reserva Deluxe (Lidl) es Mejor del Análisis.
            con una calificación global de 92/100.
            producto normal DIA (DIA) es Mejor del Análisis.
            con una calificación global de 84/100.
            """,
            (),
        )
        with patch("telegrambot.product_awards._fetch_page", return_value=document):
            item = load_ocu_item(document.url, 2026)
        self.assertEqual([candidate.score for candidate in item.candidates], [
            "92/100",
            "85/100",
        ])
        self.assertEqual([candidate.retailer for candidate in item.candidates], [
            "Lidl",
            "Mercadona",
        ])

    def test_ocu_high_subscore_without_high_overall_score_is_not_enough(self):
        document = PageDocument(
            "https://www.ocu.org/alimentacion/foo/informe/bar",
            """
            07 julio 2026
            Escala Saludable 90/100.
            producto clásico Carrefour (Carrefour) es Mejor del Análisis.
            con una calificación global de 70/100.
            """,
            (),
        )
        with patch("telegrambot.product_awards._fetch_page", return_value=document):
            item = load_ocu_item(document.url, 2026)
        self.assertEqual(item.candidates, ())


class WcccAdapterTests(unittest.TestCase):
    def test_reviewed_top20_entrepinares_maps_to_exact_mercadona_sku(self):
        document = PageDocument(
            "https://worldchampioncheese.org/2026-wccc-top-20-finalists/",
            """
            2026 WCCC Top 20 Finalists
            Class #: 114 – Hard Mixed Milk Cheeses
            Cheese: Seleccion Tostado Mixed Milk Cheese Extra Aged
            Maker: Queserías Entrepinares S.A.U.
            Company: Queserías Entrepinares
            Location: Valladolid, Spain
            """,
            (),
        )
        found = parse_wccc_top20(document, 2026)
        self.assertEqual(len(found), 1)
        item = found[0]
        self.assertEqual(item.retailer, "Mercadona")
        self.assertEqual(item.retail.product_id, "50952")
        self.assertEqual(item.retail.ean, "8480000509529")
        self.assertEqual(item.editorial.production_country, "Испания")
        self.assertEqual(item.editorial.producer, "Queserías Entrepinares S.A.U.")
        self.assertEqual(item.editorial.comparison_size, 3375)
        self.assertEqual(item.editorial.judge_count, 56)
        self.assertEqual(item.result, "Top 20 finalist")

    def test_wccc_reviewed_mapping_fails_closed_if_maker_changes(self):
        document = PageDocument(
            "https://worldchampioncheese.org/2026-wccc-top-20-finalists/",
            """
            2026 WCCC Top 20 Finalists
            Class #: 114 – Hard Mixed Milk Cheeses
            Cheese: Seleccion Tostado Mixed Milk Cheese Extra Aged
            Maker: Different Maker
            Company: Queserías Entrepinares
            Location: Valladolid, Spain
            """,
            (),
        )
        with self.assertRaises(ProductAwardError):
            parse_wccc_top20(document, 2026)


class MercadonaRetailRefreshTests(unittest.TestCase):
    def wccc_candidate(self):
        document = PageDocument(
            "https://worldchampioncheese.org/2026-wccc-top-20-finalists/",
            """
            2026 WCCC Top 20 Finalists
            Class #: 114 – Hard Mixed Milk Cheeses
            Cheese: Seleccion Tostado Mixed Milk Cheese Extra Aged
            Maker: Queserías Entrepinares S.A.U.
            Company: Queserías Entrepinares
            Location: Valladolid, Spain
            """,
            (),
        )
        return parse_wccc_top20(document, 2026)[0]

    def payload(self):
        return {
            "id": "50952",
            "ean": "8480000509529",
            "brand": "Hacendado",
            "published": True,
            "is_variable_weight": True,
            "share_url": (
                "https://tienda.mercadona.es/product/50952/"
                "queso-anejo-tostado-mezcla-hacendado-pieza"
            ),
            "details": {
                "suppliers": [{"name": "Queserías Entrepinares S.A.U."}],
            },
            "price_instructions": {
                "unit_price": 6.19,
                "reference_price": 16.74,
                "reference_format": "kg",
                "unit_size": 0.37,
                "size_format": "kg",
                "approx_size": True,
            },
        }

    def test_exact_sku_refresh_returns_current_offer(self):
        item = self.wccc_candidate()
        with patch(
            "telegrambot.product_awards._fetch_json",
            return_value=self.payload(),
        ):
            offers = refresh_mercadona_offers(item)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].package, "около 370 г")
        self.assertEqual(offers[0].price, "6,19 €")
        self.assertEqual(offers[0].unit_price, "16,74 €/кг")
        self.assertEqual(offers[0].ean, "8480000509529")

    def test_exact_sku_refresh_rejects_supplier_mismatch(self):
        item = self.wccc_candidate()
        payload = self.payload()
        payload["details"] = {"suppliers": [{"name": "Another Supplier"}]}
        with (
            patch("telegrambot.product_awards._fetch_json", return_value=payload),
            self.assertRaises(ProductAwardError),
        ):
            refresh_mercadona_offers(item)

    def test_current_publication_requires_verified_live_offer(self):
        item = self.wccc_candidate()
        with patch(
            "telegrambot.product_awards.refresh_retail_offers",
            return_value=(),
        ):
            self.assertIsNone(build_current_publication(item))

    def test_current_publication_has_store_price_and_expandable_method(self):
        item = self.wccc_candidate()
        offer = RetailOfferVariant(
            package="около 370 г",
            price="6,19 €",
            unit_price="16,74 €/кг",
            product_id="50952",
            ean="8480000509529",
        )
        with patch(
            "telegrambot.product_awards.refresh_retail_offers",
            return_value=(offer,),
        ):
            publication = build_current_publication(item)
        self.assertIsNotNone(publication)
        message = publication.message
        self.assertIn("в Mercadona — вошёл в мировой Top 20 сыров", message)
        self.assertNotIn("99,25", message.split("</b>", 1)[0])
        self.assertIn("около 370 г", message)
        self.assertIn("6,19 €", message)
        self.assertIn("16,74 €/кг", message)
        self.assertIn("Queserías Entrepinares S.A.U., Вальядолид, Испания", message)
        self.assertIn("<blockquote expandable>", message)


class CandidateIdentityTests(unittest.TestCase):
    def test_ocu_event_identity_changes_for_new_year(self):
        url = "https://www.ocu.org/alimentacion/foo/informe/bar"
        page_2026 = PageDocument(
            url,
            (
                "07 julio 2026\n"
                "salmorejo fresco de Hacendado (Mercadona) "
                "es el Mejor del Análisis."
            ),
            (),
        )
        page_2027 = PageDocument(
            url,
            (
                "07 julio 2027\n"
                "salmorejo fresco de Hacendado (Mercadona) "
                "es el Mejor del Análisis."
            ),
            (),
        )
        first = parse_ocu_awards(page_2026, 2026)[0]
        second = parse_ocu_awards(page_2027, 2027)[0]
        self.assertNotEqual(first.event_id, second.event_id)

    def test_two_products_same_brand_in_one_report_have_distinct_events(self):
        url = "https://www.ocu.org/alimentacion/foo/informe/bar"
        page = PageDocument(
            url,
            (
                "07 julio 2026\n"
                "salmorejo fresco de Hacendado (Mercadona) "
                "es el Mejor del Análisis.\n"
                "gazpacho suave de Hacendado (Mercadona) "
                "es Compra Maestra."
            ),
            (),
        )
        found = parse_ocu_awards(page, 2026)
        self.assertEqual(len(found), 2)
        self.assertNotEqual(found[0].event_id, found[1].event_id)

    def test_event_identity_is_defined_by_source_adapter(self):
        first = candidate(event_key="ocu:item:123", result="Mejor del Análisis")
        updated = candidate(
            event_key="ocu:item:123",
            result="Compra Maestra",
            score="71/100",
        )
        other = candidate(event_key="ocu:item:124")
        self.assertEqual(first.event_id, updated.event_id)
        self.assertNotEqual(first.event_id, other.event_id)


class RendererTests(unittest.TestCase):
    def test_ocu_best_in_test_message_is_deterministic(self):
        publication = build_publication(candidate())
        self.assertIn(
            "Salmorejo fresco de Hacendado в Mercadona — лучший в тесте OCU",
            publication.message,
        )
        self.assertIn("OCU сравнила 30 продуктов", publication.message)
        self.assertIn("Mejor del Análisis", publication.message)
        self.assertIn("70/100", publication.message)
        self.assertIn("В исследовании указана цена 3 €/л", publication.message)
        self.assertIn("Исследование OCU", publication.message)
        self.assertIn("обЪявления Гуардамар", publication.message)
        self.assertNotIn("текущая цена", publication.message.casefold())

    def test_ocu_rich_verified_facts_are_rendered_without_llm(self):
        base = candidate()
        item = ProductAwardCandidate(
            source_kind=base.source_kind,
            event_key=base.event_key,
            source_url=base.source_url,
            product_name=base.product_name,
            result=base.result,
            award_body=base.award_body,
            result_year=base.result_year,
            retail=base.retail,
            score=base.score,
            source_price=base.source_price,
            editorial=AwardEditorialFacts(
                comparison_size=30,
                method_flags=(
                    "labeling",
                    "composition",
                    "nutrition",
                    "professional_tasting",
                ),
                standout="best_professional_tasting",
                quality_label="Buena Elección",
            ),
        )
        message = build_publication(item).message
        self.assertIn("проверяли маркировку и состав", message)
        self.assertIn("профессиональную дегустацию", message)
        self.assertIn("лучшим по этому этапу", message)
        self.assertIn("Buena Elección", message)

    def test_ocu_compra_maestra_is_not_described_as_best_quality(self):
        item = candidate(
            retailer="Lidl",
            private_label="Deluxe",
            product_name="producto Deluxe",
            result="Compra Maestra",
            score="65/100",
            source_price="2,18 €/л",
        )
        publication = build_publication(item)
        self.assertIn("Compra Maestra", publication.message)
        self.assertIn("соотношение качества и цены", publication.message)
        self.assertNotIn("лучший результат сравнительного теста", publication.message)

    def test_future_private_label_adapter_uses_generic_renderer(self):
        item = candidate(
            source_kind="wine",
            event_key="wine:42",
            source_url="https://example.com/award/42",
            retailer="ALDI",
            private_label="Example Label",
            product_name="Example Reserva 2025",
            result="Gold",
            award_body="Example Wine Awards",
            score=None,
            source_price=None,
            sample_size=None,
        )
        message = build_publication(item).message
        self.assertIn("Gold", message)
        self.assertIn("Example Wine Awards", message)
        self.assertIn("собственной марки Example Label", message)
        self.assertIn("ALDI", message)

    def test_listed_brand_is_not_called_private_label(self):
        item = ProductAwardCandidate(
            source_kind="olive-oil",
            event_key="oil:42",
            source_url="https://example.com/award/42",
            product_name="Casa Juncal Picual",
            result="Gold",
            award_body="Example Olive Oil Awards",
            result_year=2026,
            retail=RetailEvidence(
                retailer="Mercadona",
                relationship="listed",
                product_id="12345",
                product_url="https://tienda.mercadona.es/product/12345/example",
            ),
        )
        message = build_publication(item).message
        self.assertIn("который продаётся в Mercadona", message)
        self.assertNotIn("собственной марки", message)

    def test_exact_current_offers_override_source_study_price(self):
        message = build_publication(
            candidate(source_price="3 €/л"),
            current_offers=(
                RetailOfferVariant(
                    package="1 л",
                    price="2,90 €",
                    unit_price="2,90 €/л",
                    product_id="39966",
                ),
                RetailOfferVariant(
                    package="330 мл",
                    price="1,25 €",
                    unit_price="3,79 €/л",
                    product_id="39901",
                ),
            ),
        ).message
        self.assertIn("Сейчас в Mercadona", message)
        self.assertIn("<b>1 л</b> — 2,90 € · 2,90 €/л", message)
        self.assertIn("<b>330 мл</b> — 1,25 € · 3,79 €/л", message)
        self.assertNotIn("В исследовании указана цена 3 €/л", message)

    def test_methodology_is_expandable_and_not_repeated_in_main_copy(self):
        item = ProductAwardCandidate(
            source_kind="cheese",
            event_key="wccc:1",
            source_url="https://example.com/wccc/1",
            product_name="Ibérico Añejo Hacendado",
            result="Gold",
            award_body="World Championship Cheese Contest 2026",
            result_year=2026,
            retail=RetailEvidence(
                retailer="Mercadona",
                relationship="private_label",
                label="Hacendado",
                product_id="12345",
            ),
            score="97,20/100",
            editorial=AwardEditorialFacts(
                producer="Valle de San Juan",
                producer_location="Palencia",
                production_country="Испания",
                headline_claim="получил международную награду",
                product_summary="Выдержанный сыр из смеси трёх видов молока.",
                tasting_notes=("насыщенный вкус", "твёрдая и ломкая текстура"),
                method_summary=(
                    "В конкурсе участвовало 3 375 продуктов. "
                    "Сыры оценивали профессиональные судьи."
                ),
            ),
        )
        message = build_publication(item).message
        self.assertIn(
            "Ibérico Añejo Hacendado в Mercadona — получил международную награду",
            message,
        )
        self.assertNotIn("97,20", message.split("</b>", 1)[0])
        self.assertIn("Итоговая оценка — 97,20/100", message)
        self.assertIn("Valle de San Juan, Palencia, Испания", message)
        self.assertIn("<blockquote expandable><b>Как оценивали</b>", message)
        self.assertEqual(message.count("В конкурсе участвовало 3 375 продуктов"), 1)

    def test_producer_requires_country(self):
        with self.assertRaises(ProductAwardError):
            AwardEditorialFacts(producer="Example Producer")


class EngineTests(unittest.TestCase):
    def test_first_run_baselines_ids_without_loading_pages(self):
        loaded = []

        def discover(year):
            self.assertEqual(year, 2026)
            return ("one", "two")

        def load(item_id, year):
            loaded.append((item_id, year))
            return AwardSourceItem((candidate(event_key=item_id),))

        adapter = AwardSourceAdapter("fake", discover, load)
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (adapter,)):
                found = discover_product_awards(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                )
            self.assertEqual(found, ())
            self.assertEqual(loaded, [])
            self.assertTrue(state.source_initialized("fake"))
            self.assertTrue(state.seen("fake:2026:one"))
            self.assertTrue(state.seen("fake:2026:two"))
            self.assertEqual(state.queue_size(), 0)

    def test_new_adapter_gets_its_own_baseline_without_backfill(self):
        ocu = AwardSourceAdapter(
            "ocu",
            lambda year: ("old-ocu",),
            lambda item_id, year: AwardSourceItem((candidate(event_key=item_id),)),
        )
        wine_loaded = []
        wine = AwardSourceAdapter(
            "wine",
            lambda year: ("old-wine-1", "old-wine-2"),
            lambda item_id, year: (
                wine_loaded.append(item_id)
                or AwardSourceItem((candidate(
                    source_kind="wine",
                    event_key=item_id,
                    award_body="Wine Awards",
                ),))
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("ocu", ("ocu:2026:old-ocu",))
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (ocu, wine)):
                found = discover_product_awards(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                )
            self.assertEqual(found, ())
            self.assertTrue(state.source_initialized("wine"))
            self.assertTrue(state.seen("wine:2026:old-wine-1"))
            self.assertTrue(state.seen("wine:2026:old-wine-2"))
            self.assertEqual(wine_loaded, [])
            self.assertEqual(state.queue_size(), 0)

    def test_same_item_url_is_rechecked_in_new_year(self):
        loaded = []
        adapter = AwardSourceAdapter(
            "fake",
            lambda year: ("same-url",),
            lambda item_id, year: (
                loaded.append((item_id, year))
                or AwardSourceItem((candidate(
                    source_kind="fake",
                    event_key=f"{year}:{item_id}",
                    result_year=year,
                ),))
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ("fake:2026:same-url",))
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (adapter,)):
                found = discover_product_awards(
                    datetime(2027, 1, 2, tzinfo=MADRID),
                    state,
                )
        self.assertEqual(len(found), 1)
        self.assertEqual(loaded, [("same-url", 2027)])

    def test_new_source_item_is_loaded_queued_and_marked_seen(self):
        adapter = AwardSourceAdapter(
            "fake",
            lambda year: ("new",),
            lambda item_id, year: AwardSourceItem(
                (candidate(event_key=f"{item_id}:{year}"),)
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (adapter,)):
                found = discover_product_awards(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                )
            self.assertEqual(len(found), 1)
            self.assertEqual(state.queue_size(), 1)
            self.assertTrue(state.seen("fake:2026:new"))

    def test_parser_failure_keeps_item_open_for_next_day(self):
        def fail(item_id, year):
            raise ProductAwardError("bad source shape", code="PARSER")

        adapter = AwardSourceAdapter("fake", lambda year: ("new",), fail)
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (adapter,)):
                found = discover_product_awards(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                )
            self.assertEqual(found, ())
            self.assertFalse(state.seen("fake:2026:new"))

    def test_source_failure_does_not_block_another_adapter(self):
        def down(year):
            raise ProductAwardError("down", code="NETWORK")

        good = AwardSourceAdapter(
            "good",
            lambda year: ("new",),
            lambda item_id, year: AwardSourceItem((candidate(event_key="good"),)),
        )
        bad = AwardSourceAdapter("bad", down, lambda item_id, year: AwardSourceItem(()))
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("good", ())
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (bad, good)):
                found = discover_product_awards(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                )
            self.assertEqual(len(found), 1)
            self.assertEqual(state.queue_size(), 1)

    def test_preview_is_read_only(self):
        adapter = AwardSourceAdapter(
            "fake",
            lambda year: ("one",),
            lambda item_id, year: AwardSourceItem((candidate(event_key="one"),)),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            state = ProductAwardState(path)
            with patch("telegrambot.product_awards.SOURCE_ADAPTERS", (adapter,)):
                publication = scan_next_product_award(
                    datetime(2026, 9, 25, tzinfo=MADRID),
                    state,
                    preview=True,
                )
            self.assertIsNotNone(publication)
            self.assertFalse(path.exists())


class ProductAwardStateTests(unittest.TestCase):
    def test_queue_deduplicates_same_source_event(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            first = candidate(event_key="stable", score=None)
            richer = candidate(event_key="stable", score="70/100")
            self.assertEqual(
                state.enqueue_candidates((first,), date(2026, 9, 25)),
                (1, 0, 0),
            )
            added, updated, ignored = state.enqueue_candidates(
                (richer,),
                date(2026, 9, 25),
            )
            self.assertEqual((added, updated, ignored), (0, 1, 0))
            self.assertEqual(state.queue_size(), 1)

    def test_core_does_not_rank_conflicting_award_vocabularies(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            first = candidate(event_key="stable", result="Gold")
            conflicting = candidate(event_key="stable", result="Super Gold")
            state.enqueue_candidates((first,), date(2026, 9, 25))
            with self.assertRaises(ProductAwardError):
                state.enqueue_candidates((conflicting,), date(2026, 9, 25))

    def test_one_delivery_slot_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            first = candidate(event_key="one")
            second = candidate(event_key="two", product_name="другой продукт Hacendado")
            state.enqueue_candidates((first, second), date(2026, 9, 25))

            item = state.next_queue_item(date(2026, 9, 25))
            self.assertIsNotNone(item)
            self.assertTrue(state.begin_delivery(item, date(2026, 9, 25)))
            state.confirm_delivery(item.event_id, date(2026, 9, 25))

            self.assertIsNone(state.next_queue_item(date(2026, 9, 25)))
            self.assertIsNotNone(state.next_queue_item(date(2026, 9, 26)))

    def test_ambiguous_delivery_reservation_blocks_automatic_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            item_candidate = candidate(event_key="one")
            state.enqueue_candidates((item_candidate,), date(2026, 9, 25))
            item = state.next_queue_item(date(2026, 9, 25))
            self.assertTrue(state.begin_delivery(item, date(2026, 9, 25)))
            self.assertEqual(state.queue_size(), 0)
            self.assertEqual(state.uncertain_events(), (item.event_id,))
            self.assertIsNone(state.next_queue_item(date(2026, 9, 26)))

    def test_explicit_failure_requeues_for_future_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            state.initialize_source("fake", ())
            item_candidate = candidate(event_key="one")
            state.enqueue_candidates((item_candidate,), date(2026, 9, 25))
            item = state.next_queue_item(date(2026, 9, 25))
            self.assertTrue(state.begin_delivery(item, date(2026, 9, 25)))
            state.restore_failed_delivery(item)
            self.assertEqual(state.queue_size(), 1)
            self.assertEqual(state.uncertain_events(), ())
            self.assertIsNone(state.next_queue_item(date(2026, 9, 25)))
            self.assertIsNotNone(state.next_queue_item(date(2026, 9, 26)))

    def test_corrupt_overlapping_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "awards.json"
            state = ProductAwardState(path)
            state.initialize_source("fake", ())
            event_id = candidate().event_id
            raw = json.loads(path.read_text())
            raw["published_events"] = [event_id]
            raw["uncertain_events"] = [event_id]
            path.write_text(json.dumps(raw))
            with self.assertRaises(ProductAwardError):
                state.queue_size()


if __name__ == "__main__":
    unittest.main()
