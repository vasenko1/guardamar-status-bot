import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegrambot.resident_news import (
    DiscoveryItem,
    ResidentNewsPost,
    ResidentNewsState,
    build_message,
    first_primary_link,
    is_approved_primary_url,
    parse_feed,
    run_resident_news,
    source_label,
)


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Renfe changes ticket sales</title>
  <link>https://euroweeklynews.com/2026/09/29/renfe-change/</link>
  <guid>ewn:renfe</guid>
  <pubDate>Tue, 29 Sep 2026 17:47:00 +0200</pubDate>
  <description><![CDATA[<p>A new sales system rolls out in phases.</p>]]></description>
</item>
<item>
  <title>Ordinary crime story</title>
  <link>https://euroweeklynews.com/2026/09/30/crime/</link>
  <guid>ewn:crime</guid>
  <pubDate>Wed, 30 Sep 2026 10:59:00 +0200</pubDate>
  <description><![CDATA[<p>This is not practical resident news.</p>]]></description>
</item>
</channel></rss>
"""


def item(item_id="ewn:new", title="Useful change") -> DiscoveryItem:
    return DiscoveryItem(
        item_id=item_id,
        title=title,
        description="Residents will see a practical change.",
        url=f"https://euroweeklynews.com/2026/09/30/{item_id.replace(':', '-')}/",
        published_at=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
    )


class ResidentNewsParsingTests(unittest.TestCase):
    def test_feed_parser_keeps_bounded_metadata(self):
        parsed = parse_feed(RSS)
        self.assertEqual([value.item_id for value in parsed], ["ewn:renfe", "ewn:crime"])
        self.assertEqual(parsed[0].description, "A new sales system rolls out in phases.")
        self.assertEqual(parsed[0].published_at.tzinfo, timezone.utc)

    def test_primary_link_uses_first_approved_article_link(self):
        article = b"""
        <html><body><article>
          <a href="https://example.com/opinion">other</a>
          <a href="https://www.dgt.es/muevete-con-seguridad/">DGT</a>
          <a href="https://www.boe.es/diario_boe/txt.php?id=TEST">BOE</a>
        </article></body></html>
        """
        self.assertEqual(
            first_primary_link("https://euroweeklynews.com/story/", article),
            "https://www.dgt.es/muevete-con-seguridad/",
        )

    def test_primary_link_requires_article_body(self):
        with self.assertRaises(Exception):
            first_primary_link(
                "https://euroweeklynews.com/story/",
                b'<html><a href="https://www.boe.es/test">BOE</a></html>',
            )

    def test_primary_allowlist_is_conservative(self):
        self.assertTrue(is_approved_primary_url("https://www.boe.es/test"))
        self.assertTrue(is_approved_primary_url("https://grupo.renfe.com/es/noticia"))
        self.assertTrue(is_approved_primary_url("https://www.dgt.es/noticia"))
        self.assertTrue(is_approved_primary_url("https://prensa.mites.gob.es/test"))
        self.assertFalse(is_approved_primary_url("https://elpais.com/test"))
        self.assertFalse(is_approved_primary_url("http://www.boe.es/test"))

    def test_source_labels(self):
        self.assertEqual(source_label("https://www.dgt.es/test"), "DGT")
        self.assertEqual(source_label("https://grupo.renfe.com/test"), "Renfe")
        self.assertEqual(source_label("https://www.boe.es/test"), "BOE")

    def test_message_is_narrative_and_links_primary_source(self):
        post = ResidentNewsPost(
            headline_ru="Renfe меняет покупку билетов",
            paragraphs_ru=(
                "С конца октября начинается поэтапный переход на новую систему продаж.",
                "Пассажирам обещают более понятное сравнение тарифов и меньше шагов при покупке.",
            ),
            emoji="🚆",
            status="announced",
        )
        message = build_message(post, "https://grupo.renfe.com/es/noticia")
        self.assertIn("🚆 <b>Renfe меняет покупку билетов</b>", message)
        self.assertIn("Источник:", message)
        self.assertIn(">Renfe</a>", message)
        self.assertNotIn("Кого касается:", message)


class ResidentNewsStateTests(unittest.TestCase):
    def test_first_run_seeds_without_creating_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            current = (item("ewn:one"), item("ewn:two"))
            state.seed(current)
            self.assertTrue(state.is_seeded())
            self.assertEqual(state.unseen(current), ())

    def test_classifications_keep_relevant_candidate_for_later_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            fresh = (item("ewn:good"), item("ewn:noise"))
            state.record_classifications(
                fresh,
                (
                    {"id": "ewn:good", "relevant": True, "topic": "transport", "priority": "high"},
                    {"id": "ewn:noise", "relevant": False, "topic": "crime", "priority": "normal"},
                ),
            )
            selected = state.next_eligible(
                datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
            )
            self.assertIsNotNone(selected)
            self.assertEqual(selected[0], "ewn:good")


class ResidentNewsLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_valid_feed_is_silent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            publish = AsyncMock()
            with patch(
                "telegrambot.resident_news.fetch_feed",
                new=AsyncMock(return_value=(item("ewn:one"),)),
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "seeded")
            publish.assert_not_awaited()

    async def test_relevant_item_without_primary_link_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            publish = AsyncMock()
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), item("ewn:new"))),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:new", "relevant": True, "topic": "motoring", "priority": "high"}
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(return_value=None),
                ),
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "source_missing")
            publish.assert_not_awaited()

    async def test_complete_lifecycle_publishes_one_primary_grounded_post(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            publish = AsyncMock(return_value=321)
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), item("ewn:new"))),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:new", "relevant": True, "topic": "rail", "priority": "high"}
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(return_value="https://grupo.renfe.com/es/noticia"),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(return_value=(
                        "Renfe pondra en marcha un nuevo sistema de venta. "
                        "Comenzara el 28 de octubre y se implantara de forma gradual. "
                        "Facilitara la comparacion de viajes y tarifas.",
                        "https://grupo.renfe.com/es/noticia",
                    )),
                ),
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={
                        "headline_ru": "Renfe меняет систему покупки билетов",
                        "paragraphs_ru": [
                            "С 28 октября Renfe начинает поэтапно внедрять новую систему продаж.",
                            "Пассажирам станет проще сравнивать поездки и тарифы до покупки.",
                        ],
                        "emoji": "🚆",
                        "status": "announced",
                    }),
                ),
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "published")
            publish.assert_awaited_once()
            self.assertIn("grupo.renfe.com", publish.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
