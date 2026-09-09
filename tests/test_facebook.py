import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from telegrambot.facebook import (
    FacebookError,
    FacebookPost,
    RENDERER_CONTENT_TYPES,
    _renderer_url,
    fetch_facebook_posts,
    parse_renderer_response,
)


def response(markup):
    return (
        "for (;;);" + json.dumps({
            "payload": {"content": {"markup": {"__html": markup}}}
        })
    ).encode()


MARKUP = '''
<div data-testid="newsFeedStream"><div id="card-one">
  <a href="/GuardamarAyuntamiento/posts/pfbid-first?ref=embed_page">
    <abbr data-utime="1788952755">today</abbr></a>
  <div data-testid="post_message">Concierto &amp; amigos <strong>en Guardamar</strong>.</div>
  <img src="https://cdn.example.test/poster.jpg?x=1">
</div><div id="card-two">
  <a href="/GuardamarAyuntamiento/posts/pfbid-second"><abbr data-utime="1788962440">today</abbr></a>
  <img src="https://cdn.example.test/image-only.jpg">
</div><div id="broken-card"><a href="/elsewhere/posts/nope">bad</a></div></div>
'''


class FacebookParserTests(unittest.IsolatedAsyncioTestCase):
    def test_parses_semantic_post_markers(self):
        posts = parse_renderer_response(response(MARKUP))

        self.assertEqual(len(posts), 2)
        self.assertEqual(
            posts[0].source_id,
            "https://www.facebook.com/GuardamarAyuntamiento/posts/pfbid-first",
        )
        self.assertEqual(posts[0].text, "Concierto & amigos en Guardamar.")
        self.assertEqual(posts[0].image_urls, ("https://cdn.example.test/poster.jpg?x=1",))
        self.assertEqual(posts[0].published_at, datetime.fromtimestamp(1788952755, timezone.utc))
        self.assertIsNone(posts[1].text)
        self.assertEqual(
            posts[1].source_id,
            "https://www.facebook.com/GuardamarAyuntamiento/posts/pfbid-second",
        )
        self.assertEqual(posts[1].published_at, datetime.fromtimestamp(1788962440, timezone.utc))
        self.assertEqual(posts[1].image_urls, ("https://cdn.example.test/image-only.jpg",))

    def test_renderer_content_type_sanity_check_accepts_common_javascript_types(self):
        self.assertEqual(
            RENDERER_CONTENT_TYPES,
            frozenset({
                "application/x-javascript",
                "application/javascript",
                "text/javascript",
            }),
        )

    def test_malformed_json_is_a_failure(self):
        with self.assertRaisesRegex(FacebookError, "invalid JSON"):
            parse_renderer_response(b"for (;;);not-json")

    def test_null_payload_is_a_failure(self):
        with self.assertRaisesRegex(FacebookError, "no payload"):
            parse_renderer_response(b"for (;;);{\"payload\":null}")

    def test_missing_markup_and_error_payload_are_failures(self):
        with self.assertRaises(FacebookError):
            parse_renderer_response(b"for (;;);{\"payload\":{}}")
        with self.assertRaises(FacebookError):
            parse_renderer_response(b"for (;;);{\"error\":1357055,\"payload\":null}")

    async def test_fetch_uses_the_stateless_renderer_reader(self):
        with patch("telegrambot.facebook._read_renderer", return_value=response(MARKUP)) as reader:
            posts = await fetch_facebook_posts()

        self.assertEqual(len(posts), 2)
        reader.assert_called_once_with()

    def test_renderer_url_has_no_dynamic_or_session_parameters(self):
        url = _renderer_url()
        self.assertIn("key=timeline", url)
        self.assertIn("__a=1", url)
        for forbidden in ("fb_dtsg", "__rev", "__dyn", "__hsi", "__hs", "__req"):
            self.assertNotIn(forbidden, url)
