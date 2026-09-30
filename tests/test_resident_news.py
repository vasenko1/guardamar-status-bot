import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegrambot.resident_news import (
    DiscoveryItem,
    ResidentNewsError,
    ResidentNewsPost,
    ResidentNewsState,
    build_message,
    first_primary_link,
    is_approved_primary_url,
    is_specific_primary_url,
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


def item(
    item_id="ewn:new",
    title="Useful change",
    published_at=None,
) -> DiscoveryItem:
    return DiscoveryItem(
        item_id=item_id,
        title=title,
        description="Residents will see a practical change.",
        url=f"https://euroweeklynews.com/2026/09/30/{item_id.replace(':', '-')}/",
        published_at=published_at or datetime(
            2026, 9, 30, 12, 0, tzinfo=timezone.utc
        ),
    )


class ResidentNewsParsingTests(unittest.TestCase):
    def test_feed_parser_keeps_bounded_metadata(self):
        parsed = parse_feed(RSS)
        self.assertEqual([value.item_id for value in parsed], ["ewn:renfe", "ewn:crime"])
        self.assertEqual(parsed[0].description, "A new sales system rolls out in phases.")
        self.assertEqual(parsed[0].published_at.tzinfo, timezone.utc)

    def test_feed_parser_accepts_plain_text_description(self):
        payload = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Plain description</title>
          <link>https://euroweeklynews.com/2026/09/30/plain/</link>
          <guid>ewn:plain</guid>
          <pubDate>Wed, 30 Sep 2026 12:00:00 +0200</pubDate>
          <description>Plain useful description without HTML.</description>
        </item></channel></rss>"""
        parsed = parse_feed(payload)
        self.assertEqual(parsed[0].description, "Plain useful description without HTML.")

    def test_feed_parser_skips_weather_category_owned_by_aemet(self):
        payload = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item>
          <title>Valencia braces for torrential rain</title>
          <link>https://euroweeklynews.com/2026/09/30/valencia-rain/</link>
          <guid>ewn:weather</guid>
          <pubDate>Wed, 30 Sep 2026 16:56:00 +0200</pubDate>
          <description>Storms threaten flash flooding.</description>
          <category><![CDATA[News from Spain]]></category>
          <category><![CDATA[Spain Weather]]></category>
        </item>
        <item>
          <title>Renfe changes ticket sales</title>
          <link>https://euroweeklynews.com/2026/09/30/renfe/</link>
          <guid>ewn:renfe2</guid>
          <pubDate>Wed, 30 Sep 2026 17:00:00 +0200</pubDate>
          <description>New ticket sales system.</description>
          <category><![CDATA[News from Spain]]></category>
        </item>
        </channel></rss>"""
        parsed = parse_feed(payload)
        self.assertEqual([value.item_id for value in parsed], ["ewn:renfe2"])

    def test_primary_link_uses_story_area_without_article_tag(self):
        page = b"""
        <html><body>
          <header>
            <a href="https://www.boe.es/diario_boe/txt.php?id=NAV">nav</a>
          </header>
          <h1>Renfe changes ticket sales</h1>
          <p>
            <a href="https://www.lamoncloa.gob.es/consejodeministros/Paginas/index.aspx">
              generic government index
            </a>
          </p>
          <p>
            <a href="https://grupo.renfe.com/es/es/sala-de-prensa/noticias/2026/09/renfe-transforma-sistema-de-venta">
              Renfe
            </a>
          </p>
          <h2>Comments</h2>
          <a href="https://www.boe.es/diario_boe/txt.php?id=FOOTER">footer</a>
        </body></html>
        """
        self.assertEqual(
            first_primary_link("https://euroweeklynews.com/story/", page),
            "https://grupo.renfe.com/es/es/sala-de-prensa/noticias/2026/09/renfe-transforma-sistema-de-venta",
        )

    def test_primary_link_requires_story_title(self):
        with self.assertRaises(Exception):
            first_primary_link(
                "https://euroweeklynews.com/story/",
                b'<html><a href="https://www.boe.es/test">BOE</a></html>',
            )

    def test_primary_link_skips_generic_official_landing_pages(self):
        page = b"""
        <html><body>
          <h1>Housing update</h1>
          <p><a href="https://www.lamoncloa.gob.es/consejodeministros/Paginas/index.aspx">Moncloa</a></p>
          <p><a href="https://www.congreso.es/es/">Congress</a></p>
          <p><a href="https://www.boe.es/">BOE</a></p>
          <h2>Comments</h2>
        </body></html>
        """
        self.assertIsNone(
            first_primary_link("https://euroweeklynews.com/story/", page)
        )

    def test_primary_allowlist_is_conservative(self):
        self.assertTrue(is_approved_primary_url("https://www.boe.es/test"))
        self.assertTrue(is_approved_primary_url("https://grupo.renfe.com/es/noticia"))
        self.assertTrue(is_approved_primary_url("https://www.dgt.es/noticia"))
        self.assertTrue(is_approved_primary_url("https://prensa.mites.gob.es/test"))
        self.assertFalse(is_approved_primary_url("https://elpais.com/test"))
        self.assertFalse(is_approved_primary_url("http://www.boe.es/test"))

    def test_specific_primary_url_rejects_generic_landing_pages(self):
        self.assertFalse(is_specific_primary_url("https://www.boe.es/"))
        self.assertFalse(is_specific_primary_url("https://www.congreso.es/es/"))
        self.assertFalse(
            is_specific_primary_url(
                "https://www.lamoncloa.gob.es/consejodeministros/Paginas/index.aspx"
            )
        )
        self.assertTrue(
            is_specific_primary_url(
                "https://grupo.renfe.com/es/es/sala-de-prensa/noticias/2026/09/renfe-transforma-sistema-de-venta"
            )
        )
        self.assertTrue(
            is_specific_primary_url(
                "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-20266"
            )
        )

    def test_source_labels(self):
        self.assertEqual(source_label("https://www.dgt.es/test"), "DGT")
        self.assertEqual(source_label("https://grupo.renfe.com/test"), "Renfe")
        self.assertEqual(source_label("https://www.boe.es/test"), "BOE")
        self.assertEqual(
            source_label("https://www.lamoncloa.gob.es/test"),
            "La Moncloa",
        )
        self.assertEqual(
            source_label("https://sede.agenciatributaria.gob.es/test"),
            "Agencia Tributaria",
        )
        self.assertEqual(
            source_label("https://www.mites.gob.es/test"),
            "Gobierno de España",
        )

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
        self.assertIn("обЪявления Гуардамар", message)

    def test_message_escapes_model_emoji_markup(self):
        post = ResidentNewsPost(
            headline_ru="Заголовок",
            paragraphs_ru=(
                "Первый достаточно длинный абзац о подтвержденном изменении.",
                "Второй достаточно длинный абзац с практическим смыслом.",
            ),
            emoji="<b>",
            status="effective",
        )
        message = build_message(post, "https://www.boe.es/test")
        self.assertTrue(message.startswith("&lt;b&gt; <b>Заголовок</b>"))
        self.assertNotIn("<b> <b>", message)


class ResidentNewsStateTests(unittest.TestCase):
    def test_first_run_seeds_without_creating_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            current = (item("ewn:one"), item("ewn:two"))
            state.seed(current)
            self.assertTrue(state.is_seeded())
            self.assertEqual(state.unseen(current), ())

    def test_stale_unseen_items_are_skipped_before_ai_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            stale = item(
                "ewn:stale-unseen",
                published_at=datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc),
            )
            recent = item(
                "ewn:recent-unseen",
                published_at=datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc),
            )
            now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

            selected = state.unseen((stale, recent), now=now)

            self.assertEqual(
                [candidate.item_id for candidate in selected],
                ["ewn:recent-unseen"],
            )
            self.assertEqual(
                state.unseen((stale, recent), now=now),
                (recent,),
            )

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

    def test_high_priority_precedes_older_normal_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            normal = item(
                "ewn:normal",
                published_at=datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc),
            )
            high = item(
                "ewn:high",
                published_at=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
            )
            state.record_classifications(
                (normal, high),
                (
                    {"id": "ewn:normal", "relevant": True, "topic": "rail", "priority": "normal"},
                    {"id": "ewn:high", "relevant": True, "topic": "tax", "priority": "high"},
                ),
            )
            selected = state.next_eligible(
                datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
            )
            self.assertEqual(selected[0], "ewn:high")

    def test_fourth_candidate_remains_for_next_day_after_three_publications(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            candidates = tuple(
                item(
                    f"ewn:{index}",
                    published_at=datetime(
                        2026, 9, 30, 9 + index, 0, tzinfo=timezone.utc
                    ),
                )
                for index in range(1, 5)
            )
            state.record_classifications(
                candidates,
                tuple(
                    {
                        "id": candidate.item_id,
                        "relevant": True,
                        "topic": "practical",
                        "priority": "high",
                    }
                    for candidate in candidates
                ),
            )

            for message_id in range(1, 4):
                selected = state.next_eligible(
                    datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
                )
                state.mark_uncertain(selected[0])
                state.mark_published(
                    selected[0],
                    message_id,
                    f"https://www.boe.es/test?id={message_id}",
                )

            next_day = state.next_eligible(
                datetime(2026, 10, 1, 11, 11, tzinfo=timezone.utc)
            )
            self.assertIsNotNone(next_day)
            self.assertEqual(next_day[0], "ewn:4")

    def test_never_tried_normal_candidate_precedes_failed_high_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            failed_high = item(
                "ewn:failed-high",
                published_at=datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc),
            )
            fresh_normal = item(
                "ewn:fresh-normal",
                published_at=datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc),
            )
            state.record_classifications(
                (failed_high, fresh_normal),
                (
                    {
                        "id": "ewn:failed-high",
                        "relevant": True,
                        "topic": "tax",
                        "priority": "high",
                    },
                    {
                        "id": "ewn:fresh-normal",
                        "relevant": True,
                        "topic": "rail",
                        "priority": "normal",
                    },
                ),
            )
            state.record_source_failure("ewn:failed-high", "TIMEOUT")
            selected = state.next_eligible(
                datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
            )
            self.assertEqual(selected[0], "ewn:fresh-normal")

    def test_candidate_older_than_48_hours_becomes_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            old = item(
                "ewn:old-news",
                published_at=datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc),
            )
            state.record_classifications(
                (old,),
                (
                    {
                        "id": "ewn:old-news",
                        "relevant": True,
                        "topic": "tax",
                        "priority": "high",
                    },
                ),
            )
            self.assertIsNone(
                state.next_eligible(
                    datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc)
                )
            )


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
            self.assertEqual(result, "no_publishable_candidate")
            publish.assert_not_awaited()

    async def test_missing_source_falls_through_to_next_candidate_same_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            first = item(
                "ewn:first",
                published_at=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
            )
            second = item(
                "ewn:second",
                published_at=datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
            )
            publish = AsyncMock(return_value=500)
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), first, second)),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:first", "relevant": True, "topic": "fuel", "priority": "high"},
                        {"id": "ewn:second", "relevant": True, "topic": "rail", "priority": "high"},
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(side_effect=[
                        None,
                        "https://grupo.renfe.com/es/noticia",
                    ]),
                ) as source_link,
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(return_value=(
                        "Renfe pondra en marcha un nuevo sistema de venta. "
                        "Comenzara el 28 de octubre y se implantara de forma gradual.",
                        "https://grupo.renfe.com/es/noticia",
                    )),
                ),
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={
                        "supported": True,
                        "headline_ru": "Renfe cambia la venta",
                        "paragraphs_ru": [
                            "Renfe cambia su sistema de venta de billetes a partir de octubre.",
                            "La implantacion sera gradual para los viajeros.",
                        ],
                        "emoji": "🚆",
                        "status": "announced",
                    }),
                ) as compose,
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "published")
            self.assertEqual(source_link.await_count, 2)
            compose.assert_awaited_once()
            publish.assert_awaited_once()

    async def test_transient_primary_failure_does_not_block_next_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            first = item("ewn:first")
            second = item(
                "ewn:second",
                published_at=datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
            )
            publish = AsyncMock(return_value=501)
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), first, second)),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:first", "relevant": True, "topic": "tax", "priority": "high"},
                        {"id": "ewn:second", "relevant": True, "topic": "rail", "priority": "high"},
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(side_effect=[
                        "https://www.boe.es/diario_boe/txt.php?id=FIRST",
                        "https://grupo.renfe.com/es/noticia",
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(side_effect=[
                        ResidentNewsError("timeout", code="TIMEOUT"),
                        (
                            "Renfe pondra en marcha un nuevo sistema de venta. "
                            "La implantacion sera gradual para los viajeros.",
                            "https://grupo.renfe.com/es/noticia",
                        ),
                    ]),
                ) as primary_text,
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={
                        "supported": True,
                        "headline_ru": "Renfe cambia la venta",
                        "paragraphs_ru": [
                            "Renfe cambia su sistema de venta de billetes a partir de octubre.",
                            "La implantacion sera gradual para los viajeros.",
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
            self.assertEqual(primary_text.await_count, 2)
            self.assertEqual(
                state.next_eligible(
                    datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
                )[0],
                "ewn:first",
            )

    async def test_run_inspects_at_most_three_source_less_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            fresh = tuple(
                item(
                    f"ewn:{index}",
                    published_at=datetime(
                        2026, 9, 30, 12, index, tzinfo=timezone.utc
                    ),
                )
                for index in range(1, 5)
            )
            publish = AsyncMock()
            decisions = [
                {
                    "id": candidate.item_id,
                    "relevant": True,
                    "topic": "practical",
                    "priority": "high",
                }
                for candidate in fresh
            ]
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), *fresh)),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=decisions),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(return_value=None),
                ) as source_link,
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "no_publishable_candidate")
            self.assertEqual(source_link.await_count, 3)
            remaining = state.next_eligible(
                datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
            )
            self.assertEqual(remaining[0], "ewn:4")
            publish.assert_not_awaited()

    async def test_duplicate_primary_source_falls_through_without_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:baseline"),))
            already = item(
                "ewn:already",
                published_at=datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc),
            )
            state.record_classifications(
                (already,),
                (
                    {
                        "id": "ewn:already",
                        "relevant": True,
                        "topic": "rail",
                        "priority": "high",
                    },
                ),
            )
            state.mark_uncertain("ewn:already")
            state.mark_published(
                "ewn:already",
                1,
                "https://grupo.renfe.com/es/same-source",
            )

            duplicate = item(
                "ewn:duplicate",
                published_at=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
            )
            next_item = item(
                "ewn:next",
                published_at=datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
            )
            publish = AsyncMock(return_value=502)
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(
                        item("ewn:baseline"),
                        duplicate,
                        next_item,
                    )),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:duplicate", "relevant": True, "topic": "rail", "priority": "high"},
                        {"id": "ewn:next", "relevant": True, "topic": "tax", "priority": "high"},
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(side_effect=[
                        "https://grupo.renfe.com/es/same-source",
                        "https://www.boe.es/diario_boe/txt.php?id=NEXT",
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(return_value=(
                        "El BOE publica una medida nueva de alcance nacional "
                        "que afecta a residentes y entra en vigor proximamente.",
                        "https://www.boe.es/diario_boe/txt.php?id=NEXT",
                    )),
                ),
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={
                        "supported": True,
                        "headline_ru": "Новое правило",
                        "paragraphs_ru": [
                            "Опубликовано новое правило общенационального действия.",
                            "Оно начнет применяться в указанную официальным источником дату.",
                        ],
                        "emoji": "📄",
                        "status": "approved",
                    }),
                ) as compose,
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "published")
            compose.assert_awaited_once()
            publish.assert_awaited_once()

    async def test_unsupported_source_consumes_only_one_composition_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            state = ResidentNewsState(Path(directory) / "news.json")
            state.seed((item("ewn:old"),))
            first = item("ewn:first")
            second = item(
                "ewn:second",
                published_at=datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
            )
            publish = AsyncMock()
            with (
                patch(
                    "telegrambot.resident_news.fetch_feed",
                    new=AsyncMock(return_value=(item("ewn:old"), first, second)),
                ),
                patch(
                    "telegrambot.resident_news.classify_resident_news",
                    new=AsyncMock(return_value=[
                        {"id": "ewn:first", "relevant": True, "topic": "tax", "priority": "high"},
                        {"id": "ewn:second", "relevant": True, "topic": "rail", "priority": "high"},
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(return_value="https://www.boe.es/diario_boe/txt.php?id=FIRST"),
                ) as source_link,
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(return_value=(
                        "Este texto oficial no confirma el cambio descrito por "
                        "el articulo editorial y trata de otra materia distinta.",
                        "https://www.boe.es/diario_boe/txt.php?id=FIRST",
                    )),
                ),
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={"supported": False}),
                ) as compose,
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "source_unsupported")
            source_link.assert_awaited_once()
            compose.assert_awaited_once()
            publish.assert_not_awaited()
            remaining = state.next_eligible(
                datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
            )
            self.assertEqual(remaining[0], "ewn:second")

    async def test_unrelated_primary_source_is_not_published(self):
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
                        {"id": "ewn:new", "relevant": True, "topic": "rail", "priority": "high"}
                    ]),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_link",
                    new=AsyncMock(return_value="https://grupo.renfe.com/es/other"),
                ),
                patch(
                    "telegrambot.resident_news.fetch_primary_text",
                    new=AsyncMock(return_value=(
                        "Este texto oficial trata de otro asunto distinto y no confirma "
                        "el cambio descubierto por el articulo editorial.",
                        "https://grupo.renfe.com/es/other",
                    )),
                ),
                patch(
                    "telegrambot.resident_news.compose_resident_news",
                    new=AsyncMock(return_value={"supported": False}),
                ),
            ):
                result = await run_resident_news(
                    datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
                    state,
                    "key",
                    publish,
                )
            self.assertEqual(result, "source_unsupported")
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
                        "supported": True,
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
