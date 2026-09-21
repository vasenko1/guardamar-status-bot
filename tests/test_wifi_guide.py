import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.guide import (
    GuideState,
    _publish_wifi_pending_notice,
    _refresh_wifi_source,
)
from telegrambot.wifi import (
    WIFI_SOURCE_PAGE_URL,
    WIFI_VERIFIED_ASSET_URL,
    WifiSourceError,
    allowed_wifi_asset_url,
    allowed_wifi_source_url,
    extract_wifi_asset_url,
    parse_wifi_pdf_text,
    valid_wifi_snapshot,
)
from telegrambot.pinned import build_places, build_root, build_wifi
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 21, 9, 2, tzinfo=MADRID)
CHANGED_ASSET = (
    "https://www.guardamardelsegura.es/wp-content/uploads/2026/10/"
    "wifi-map.pdf?rev=2"
)


def wifi_pdf_text(plaza_password="vegafibra"):
    return f"""
WIFIS PÚBLICAS en GUARDAMAR DEL SEGURA
ESCOLA DE MÚSICA
C/ Mercat, 2 - Wifi gratuita WiFi4EU
CASA DE CULTURA
C/ Colón, 60 - Wifi gratuita WiFi4EU
AVDA. LOS PINOS
Wifi gratuita WiFi4EU
PLAZA DE LA CONSTITUCIÓN
Red: vegafibra_gratis
Contraseña: {plaza_password}
PASEO MARÍTIMO. Avda. de Europa
Red: vegafibra_gratis
Contraseña: vegafibra
SALA DE ESTUDIOS 24/365 - C/ Mayor, 69
Red: wifi_1EO9C
Contraseña: vegafibra
BIBLIOTECA PÚBLICA - C/ San Jaime, 5
Red: wifibiblioteca - Contraseña: biblimar
Red: biblioteca infantil - Contraseña: menjallibres
Red: vicenteramos - Contraseña: menjallibres
"""


def changed_snapshot(password="plaza2026"):
    return parse_wifi_pdf_text(
        wifi_pdf_text(password),
        CHANGED_ASSET,
        NOW,
    )


def wifi_pdf_text_live_order():
    return """
WIFIS PÚBLICAS en GUARDAMAR DEL SEGURA
ESCOLA DE MÚSICA
C/ Mercat, 2 - Wifi gratuita WiFi4EU
PLAZA DE LA CONSTITUCIÓN
Red: vegafibra_gratis
Contraseña: vegafibra
PASEO MARÍTIMO. Avda. de Europa
Red: vegafibra_gratis
Contraseña: vegafibra
BIBLIOTECA PÚBLICA - C/ San Jaime, 5
Red: wifibiblioteca - Contraseña: biblimar
Red: biblioteca infantil - Contraseña: menjallibres
Red: vicenteramos - Contraseña: menjallibres
SALA DE ESTUDIOS 24/365 - C/ Mayor, 69
Red: wifi_1EO9C
Contraseña: vegafibra
CASA DE CULTURA
C/ Colón, 60 - Wifi gratuita WiFi4EU
AVDA. LOS PINOS
Wifi gratuita WiFi4EU
"""


class WifiPinnedContentTests(unittest.TestCase):
    def test_static_wifi_card_contains_reviewed_baseline(self):
        message = build_wifi("https://t.me/c/1/22")

        self.assertLessEqual(len(message), 4096)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertIn("7 муниципальных точек", message)
        self.assertEqual(message.count("<code>WiFi4EU</code>"), 3)
        self.assertIn("vegafibra_gratis", message)
        self.assertIn("wifi_1EO9C", message)
        self.assertIn("wifibiblioteca", message)
        self.assertIn("biblimar", message)
        self.assertIn("Полезное о Гуардамаре", message)

    def test_dynamic_wifi_card_uses_accepted_credentials(self):
        message = build_wifi(
            "https://t.me/c/1/22",
            changed_snapshot("plaza2026"),
        )

        self.assertLessEqual(len(message), 4096)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertIn("<code>plaza2026</code>", message)
        self.assertIn("<code>wifibiblioteca</code>", message)
        self.assertIn("google.com/maps/search", message)

    def test_root_links_to_wifi_and_places_does_not(self):
        root = build_root(wifi_link="https://t.me/c/1/50")
        places = build_places()
        self.assertIn("Бесплатный Wi-Fi", root)
        self.assertIn("https://t.me/c/1/50", root)
        self.assertNotIn("Бесплатный Wi-Fi", places)


class WifiSourceParsingTests(unittest.TestCase):
    def test_source_page_policy_is_narrow(self):
        self.assertTrue(allowed_wifi_source_url(WIFI_SOURCE_PAGE_URL))
        self.assertTrue(
            allowed_wifi_source_url(
                "https://guardamardelsegura.es/wifis-municipales/"
            )
        )
        for invalid in (
            "http://www.guardamardelsegura.es/wifis-municipales/",
            "https://www.guardamardelsegura.es/other/",
            "https://guardamardelsegura.es.evil.example/wifis-municipales/",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(allowed_wifi_source_url(invalid))

    def test_asset_policy_accepts_only_municipal_https_pdf(self):
        self.assertTrue(allowed_wifi_asset_url(WIFI_VERIFIED_ASSET_URL))
        self.assertTrue(allowed_wifi_asset_url(CHANGED_ASSET))
        for invalid in (
            "http://www.guardamardelsegura.es/wp-content/uploads/wifi.pdf",
            "https://cdn.example.org/wifi.pdf",
            "https://www.guardamardelsegura.es/wifi.pdf",
            "https://www.guardamardelsegura.es/wp-content/uploads/wifi.jpg",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(allowed_wifi_asset_url(invalid))

    def test_extracts_one_municipal_linked_wifi_asset_and_keeps_query(self):
        payload = b"""
        <html><body>
          <a href="/wp-content/uploads/2026/10/wifi-map.pdf?rev=2#preview">
            <img src="/wp-content/uploads/2026/10/PLANO-WIFIS-GUARDAMAR-PUBLICAS.jpg">
          </a>
        </body></html>
        """
        self.assertEqual(extract_wifi_asset_url(payload), CHANGED_ASSET)

    def test_rejects_external_missing_or_ambiguous_asset(self):
        payloads = (
            b"""
            <a href="https://cdn.example.org/wifi.pdf">
              <img src="WIFIS-GUARDAMAR-PUBLICAS.jpg">
            </a>
            """,
            b"<html><body><p>No map</p></body></html>",
            b"""
            <a href="/wp-content/uploads/one.pdf">
              <img src="WIFIS-GUARDAMAR-PUBLICAS.jpg">
            </a>
            <a href="/wp-content/uploads/two.pdf">
              <img src="WIFIS-GUARDAMAR-PUBLICAS-2.jpg">
            </a>
            """,
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(WifiSourceError):
                    extract_wifi_asset_url(payload)

    def test_parses_complete_text_pdf_snapshot(self):
        snapshot = changed_snapshot("plaza2026")

        self.assertTrue(valid_wifi_snapshot(snapshot))
        self.assertEqual(snapshot["asset_url"], CHANGED_ASSET)
        self.assertEqual(len(snapshot["points"]), 7)
        plaza = next(
            item for item in snapshot["points"]
            if item["key"] == "constitution_square"
        )
        self.assertEqual(
            plaza["networks"],
            [{"ssid": "vegafibra_gratis", "password": "plaza2026"}],
        )
        library = next(
            item for item in snapshot["points"]
            if item["key"] == "library"
        )
        self.assertEqual(len(library["networks"]), 3)

    def test_parses_current_pdf_text_layer_order(self):
        snapshot = parse_wifi_pdf_text(
            wifi_pdf_text_live_order(),
            CHANGED_ASSET,
            NOW,
        )

        self.assertTrue(valid_wifi_snapshot(snapshot))
        self.assertEqual(
            [point["key"] for point in snapshot["points"]],
            [
                "music_school",
                "culture_house",
                "los_pinos",
                "constitution_square",
                "seafront",
                "study_room",
                "library",
            ],
        )

    def test_rejects_incomplete_or_extra_network_structure(self):
        incomplete = wifi_pdf_text().replace(
            "AVDA. LOS PINOS\nWifi gratuita WiFi4EU\n",
            "AVDA. LOS PINOS\n",
        )
        with self.assertRaises(WifiSourceError):
            parse_wifi_pdf_text(incomplete, CHANGED_ASSET, NOW)

        extra = wifi_pdf_text() + (
            "\nPUNTO NUEVO\nRed: unknown\nContraseña: secret\n"
        )
        with self.assertRaises(WifiSourceError):
            parse_wifi_pdf_text(extra, CHANGED_ASSET, NOW)


class WifiSourceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_asset_seeds_silent_baseline_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            fetch_asset = AsyncMock(return_value=WIFI_VERIFIED_ASSET_URL)
            fetch_snapshot = AsyncMock()
            with (
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=fetch_asset,
                ),
                patch(
                    "telegrambot.guide.fetch_wifi_snapshot",
                    new=fetch_snapshot,
                ),
            ):
                await _refresh_wifi_source(NOW, state, state_store)
                await _refresh_wifi_source(NOW, state, state_store)

            fetch_asset.assert_awaited_once()
            fetch_snapshot.assert_not_awaited()
            saved = state_store.read()
            self.assertEqual(
                saved["wifi_observed_asset_url"],
                WIFI_VERIFIED_ASSET_URL,
            )
            self.assertEqual(saved["wifi_last_attempt_day"], "2026-09-21")
            self.assertNotIn("wifi_pending_asset_url", saved)
            self.assertNotIn("wifi_snapshot", saved)

    async def test_new_asset_with_same_facts_is_silent(self):
        snapshot = parse_wifi_pdf_text(
            wifi_pdf_text("vegafibra"),
            CHANGED_ASSET,
            NOW,
        )
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            with (
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=AsyncMock(return_value=CHANGED_ASSET),
                ),
                patch(
                    "telegrambot.guide.fetch_wifi_snapshot",
                    new=AsyncMock(return_value=snapshot),
                ),
            ):
                await _refresh_wifi_source(NOW, state, state_store)

            saved = state_store.read()
            self.assertEqual(saved["wifi_observed_asset_url"], CHANGED_ASSET)
            self.assertEqual(saved["wifi_snapshot"], snapshot)
            self.assertNotIn("wifi_pending_asset_url", saved)

    async def test_changed_asset_persists_validated_snapshot_and_pending_notice(self):
        snapshot = changed_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            fetch_asset = AsyncMock(return_value=CHANGED_ASSET)
            fetch_snapshot = AsyncMock(return_value=snapshot)
            with (
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=fetch_asset,
                ),
                patch(
                    "telegrambot.guide.fetch_wifi_snapshot",
                    new=fetch_snapshot,
                ),
            ):
                await _refresh_wifi_source(NOW, state, state_store)
                await _refresh_wifi_source(NOW, state, state_store)

            fetch_asset.assert_awaited_once()
            fetch_snapshot.assert_awaited_once_with(CHANGED_ASSET, NOW)
            saved = state_store.read()
            self.assertEqual(saved["wifi_snapshot"], snapshot)
            self.assertEqual(saved["wifi_observed_asset_url"], CHANGED_ASSET)
            self.assertEqual(saved["wifi_pending_asset_url"], CHANGED_ASSET)

    async def test_parse_failure_preserves_reviewed_card_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            with (
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=AsyncMock(return_value=CHANGED_ASSET),
                ),
                patch(
                    "telegrambot.guide.fetch_wifi_snapshot",
                    new=AsyncMock(
                        side_effect=WifiSourceError(
                            "schema", code="WIFI-SCHEMA"
                        )
                    ),
                ),
            ):
                await _refresh_wifi_source(NOW, state, state_store)

            saved = state_store.read()
            self.assertNotIn("wifi_snapshot", saved)
            self.assertNotIn("wifi_pending_asset_url", saved)
            self.assertNotIn("wifi_observed_asset_url", saved)

    async def test_public_notice_links_updated_card_and_dedupes(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = {
                "version": 1,
                "wifi_pending_asset_url": CHANGED_ASSET,
            }
            state_store.write(state)
            send = AsyncMock(return_value=501)
            with patch("telegrambot.guide.send_message", new=send):
                await _publish_wifi_pending_notice(
                    "token",
                    "-100123",
                    {"wifi": 50},
                    state,
                    state_store,
                )
                await _publish_wifi_pending_notice(
                    "token",
                    "-100123",
                    {"wifi": 50},
                    state,
                    state_store,
                )

            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[1], "-100123")
            self.assertIn("Обновилась информация", send.await_args.args[2])
            self.assertIn("Актуальные точки, сети и пароли", send.await_args.args[2])
            saved = state_store.read()
            self.assertEqual(saved["wifi_notice"]["asset_url"], CHANGED_ASSET)
            self.assertEqual(saved["wifi_notice"]["message_id"], 501)
            self.assertNotIn("wifi_pending_asset_url", saved)
            self.assertNotIn("wifi_notice_uncertain_asset_url", saved)

    async def test_ambiguous_public_notice_is_not_retried_blindly(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = {
                "version": 1,
                "wifi_pending_asset_url": CHANGED_ASSET,
            }
            state_store.write(state)
            send = AsyncMock(
                side_effect=TelegramError(
                    "network", retryable=True, code="NETWORK"
                )
            )
            with patch("telegrambot.guide.send_message", new=send):
                await _publish_wifi_pending_notice(
                    "token", "-100123", {"wifi": 50}, state, state_store
                )
                await _publish_wifi_pending_notice(
                    "token", "-100123", {"wifi": 50}, state, state_store
                )

            send.assert_awaited_once()
            saved = state_store.read()
            self.assertEqual(
                saved["wifi_notice_uncertain_asset_url"],
                CHANGED_ASSET,
            )
            self.assertEqual(saved["wifi_pending_asset_url"], CHANGED_ASSET)

    async def test_explicit_public_notice_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = {
                "version": 1,
                "wifi_pending_asset_url": CHANGED_ASSET,
            }
            state_store.write(state)
            send = AsyncMock(
                side_effect=TelegramError(
                    "bad request",
                    retryable=False,
                    code="HTTP-400",
                    status=400,
                )
            )
            with patch("telegrambot.guide.send_message", new=send):
                with self.assertRaises(TelegramError):
                    await _publish_wifi_pending_notice(
                        "token", "-100123", {"wifi": 50}, state, state_store
                    )

            saved = state_store.read()
            self.assertNotIn("wifi_notice_uncertain_asset_url", saved)
            self.assertEqual(saved["wifi_pending_asset_url"], CHANGED_ASSET)


if __name__ == "__main__":
    unittest.main()
