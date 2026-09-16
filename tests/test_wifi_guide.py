import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegrambot.branding import FOOTER
from telegrambot.guide import (
    GuideSourceError,
    GuideState,
    WIFI_SOURCE_PAGE_URL,
    WIFI_VERIFIED_ASSET_URL,
    _allowed_wifi_source_url,
    _check_wifi_source,
    _extract_wifi_asset_url,
)
from telegrambot.pinned import build_places, build_wifi
from telegrambot.telegram import TelegramError


class WifiPinnedContentTests(unittest.TestCase):
    def test_wifi_card_contains_verified_points_networks_and_passwords(self):
        message = build_wifi("https://t.me/c/1/22")

        self.assertLessEqual(len(message), 4096)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertIn("7 муниципальных точек", message)
        self.assertEqual(message.count("<code>WiFi4EU</code>"), 3)
        self.assertIn("vegafibra_gratis", message)
        self.assertIn("wifi_1EO9C", message)
        self.assertIn("wifibiblioteca", message)
        self.assertIn("biblimar", message)
        self.assertIn("biblioteca infantil", message)
        self.assertIn("vicenteramos", message)
        self.assertIn("menjallibres", message)
        self.assertIn("К списку мест", message)
        self.assertIn("https://t.me/c/1/22", message)
        self.assertIn("google.com/maps/search", message)

    def test_places_branch_links_to_wifi_card(self):
        message = build_places(wifi_link="https://t.me/c/1/50")
        self.assertIn("Бесплатный Wi-Fi", message)
        self.assertIn("https://t.me/c/1/50", message)
        self.assertIn("7 муниципальных точек, сети и пароли", message)


class WifiSourceParsingTests(unittest.TestCase):
    def test_source_page_policy_is_narrow(self):
        self.assertTrue(_allowed_wifi_source_url(WIFI_SOURCE_PAGE_URL))
        self.assertTrue(
            _allowed_wifi_source_url(
                "https://guardamardelsegura.es/wifis-municipales/"
            )
        )
        for invalid in (
            "http://www.guardamardelsegura.es/wifis-municipales/",
            "https://www.guardamardelsegura.es/other/",
            "https://guardamardelsegura.es.evil.example/wifis-municipales/",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(_allowed_wifi_source_url(invalid))

    def test_extracts_one_linked_wifi_asset_and_keeps_query(self):
        payload = b"""
        <html><body>
          <a href="/wp-content/uploads/2026/10/wifi-map.pdf?rev=2#preview">
            <img src="/wp-content/uploads/2026/10/PLANO-WIFIS-GUARDAMAR-PUBLICAS.jpg">
          </a>
        </body></html>
        """
        self.assertEqual(
            _extract_wifi_asset_url(payload),
            "https://www.guardamardelsegura.es/wp-content/uploads/2026/10/"
            "wifi-map.pdf?rev=2",
        )

    def test_missing_or_ambiguous_asset_is_rejected(self):
        for payload in (
            b"<html><body><p>No map</p></body></html>",
            b"""
            <a href="/one.jpg"><img src="WIFIS-GUARDAMAR-PUBLICAS.jpg"></a>
            <a href="/two.jpg"><img src="WIFIS-GUARDAMAR-PUBLICAS-2.jpg"></a>
            """,
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(GuideSourceError):
                    _extract_wifi_asset_url(payload)


class WifiSourceWatchTests(unittest.IsolatedAsyncioTestCase):
    def _environment(self):
        return {"TELEGRAM_ALLOWED_USER_IDS": "200,100"}

    async def test_verified_asset_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            send = AsyncMock()
            with (
                patch.dict("os.environ", self._environment(), clear=False),
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=AsyncMock(return_value=WIFI_VERIFIED_ASSET_URL),
                ),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await _check_wifi_source("token", state, state_store)
            send.assert_not_awaited()
            self.assertFalse(state_store.path.exists())

    async def test_changed_asset_alerts_once_and_persists_only_dedupe_url(self):
        changed = (
            "https://cdn.example.org/guardamar/wifi-map.pdf?revision=2"
        )
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            send = AsyncMock(return_value=501)
            fetch = AsyncMock(return_value=changed)
            with (
                patch.dict("os.environ", self._environment(), clear=False),
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset", new=fetch
                ),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await _check_wifi_source("token", state, state_store)
                await _check_wifi_source("token", state, state_store)

            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[1], "100")
            self.assertTrue(send.await_args.kwargs["retry_only_rate_limits"])
            self.assertIn("Нужно проверить точки, SSID и пароли", send.await_args.args[2])
            saved = json.loads(state_store.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["wifi_last_alerted_asset_url"], changed)
            self.assertNotIn("wifi_last_checked_at", saved)
            self.assertNotIn("wifi_previous_asset_url", saved)

    async def test_failed_alert_is_not_marked_as_delivered(self):
        changed = "https://example.org/new-wifi-map.pdf"
        failure = TelegramError(
            "timeout", retryable=True, code="TIMEOUT"
        )
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            send = AsyncMock(side_effect=failure)
            with (
                patch.dict(
                    "os.environ",
                    {"TELEGRAM_ALLOWED_USER_IDS": "100"},
                    clear=False,
                ),
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=AsyncMock(return_value=changed),
                ),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await _check_wifi_source("token", state, state_store)

            send.assert_awaited_once()
            self.assertFalse(state_store.path.exists())
            self.assertNotIn("wifi_last_alerted_asset_url", state)

    async def test_missing_operator_allowlist_skips_network_work(self):
        fetch = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            with (
                patch.dict(
                    "os.environ",
                    {"TELEGRAM_ALLOWED_USER_IDS": ""},
                    clear=False,
                ),
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset", new=fetch
                ),
            ):
                await _check_wifi_source(
                    "token", state_store.read(), state_store
                )
        fetch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
