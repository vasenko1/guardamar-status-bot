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
    _aldi_price,
    _price_after_title,
    build_message,
    select_publication,
)


MADRID = ZoneInfo("Europe/Madrid")


def candidate(
    event_id: str,
    category: str = "test",
    *,
    source_priority: int = 1,
    rank: int = 1,
) -> ReviewedCandidate:
    return ReviewedCandidate(
        category_key=category,
        event_id=event_id,
        source_name="Test Award",
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
        source_priority=source_priority,
        rank=rank,
    )


class PriceParserTests(unittest.TestCase):
    def test_aldi_price_is_tied_to_exact_package_line(self):
        text = (
            "NALTROS Cava brut 11,5% vol. tasting notes "
            "3.15 0,75 l unidad l = 4.20"
        )
        self.assertEqual(_aldi_price(text, "0,75 l"), "3,15 €")

    def test_title_price_ignores_values_before_product(self):
        text = (
            "navigation 99,99 € Exact Product 1 l "
            "7,65 € 7,65 €/l Añadir"
        )
        self.assertEqual(
            _price_after_title(text, "Exact Product 1 l"),
            "7,65 €",
        )

    def test_missing_price_fails_closed(self):
        self.assertIsNone(_price_after_title("Exact Product Añadir", "Exact Product"))


class StateTests(unittest.TestCase):
    def test_three_day_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            start = date(2026, 9, 27)
            state.mark_uncertain("event")
            state.confirm("event", 0, start)
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
            state.confirm("event", 1, date(2026, 9, 27))
            self.assertIn("event", state.published_events())
            self.assertEqual(state.category_cursor(), 2)


class SelectionTests(unittest.TestCase):
    def test_cooldown_causes_zero_source_or_retail_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            today = date(2026, 9, 27)
            state.mark_uncertain("already")
            state.confirm("already", 0, today - timedelta(days=1))
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
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_delivery_day": None,
                    "published_events": published,
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
        first = candidate("first", source_priority=1, rank=1)
        second = candidate("second", source_priority=1, rank=2)
        fallback = candidate("fallback", source_priority=2, rank=1)
        categories = (
            ReviewedCategory(
                "test",
                (
                    ReviewedSource("primary", 1, (first, second)),
                    ReviewedSource("secondary", 2, (fallback,)),
                ),
            ),
        )
        offer = RetailOffer("Test Market", "1 l", "2,50 €", "https://shop.example/product")
        calls = []

        def verify(item):
            calls.append(("award", item.event_id))

        def refresh(item):
            calls.append(("retail", item.event_id))
            if item.event_id == "second":
                return offer
            return None

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

    def test_next_source_is_used_only_after_primary_is_exhausted(self):
        first = candidate("first", source_priority=1, rank=1)
        fallback = candidate("fallback", source_priority=2, rank=1)
        categories = (
            ReviewedCategory(
                "test",
                (
                    ReviewedSource("primary", 1, (first,)),
                    ReviewedSource("secondary", 2, (fallback,)),
                ),
            ),
        )
        offer = RetailOffer("Test Market", "1 l", "2,50 €", "https://shop.example/product")
        calls = []

        def refresh(item):
            calls.append(item.event_id)
            return offer if item.event_id == "fallback" else None

        with tempfile.TemporaryDirectory() as directory:
            state = ProductAwardState(Path(directory) / "awards.json")
            with (
                patch.object(awards, "CATEGORIES", categories),
                patch.object(awards, "_verify_award"),
                patch.object(awards, "_refresh_offer", side_effect=refresh),
            ):
                selected = select_publication(
                    datetime(2026, 9, 27, 14, 20, tzinfo=MADRID),
                    state,
                )
        self.assertEqual(calls, ["first", "fallback"])
        self.assertEqual(selected[1].candidate.event_id, "fallback")


class RenderingTests(unittest.TestCase):
    def test_message_contains_current_offer_and_two_sources(self):
        item = candidate("event")
        offer = RetailOffer(
            "Test Market",
            "1 l",
            "2,50 €",
            "https://shop.example/product",
        )
        message = build_message(item, offer)
        self.assertIn("2,50 €", message)
        self.assertIn("Карточка товара", message)
        self.assertIn("Источник", message)
        self.assertIn("обЪявления Гуардамар", message)


if __name__ == "__main__":
    unittest.main()
