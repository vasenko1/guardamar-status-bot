import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.hidraqua import (
    HidraquaError, HidraquaEvent, HidraquaState, format_event,
    format_messages, monitor_once, normalize_events,
)


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 8, 10, 0, tzinfo=MADRID)


def event(identifier=1, motive="AVE", address="Calle Uno", streets="Calle Dos", end=1788861600000):
    ends_at = datetime.fromtimestamp(end / 1000, MADRID) if end else None
    return HidraquaEvent(identifier, "5EC", motive, address, streets, None, ends_at)


class HidraquaMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_is_quiet_then_only_new_event_is_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            send = AsyncMock()
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=(event(1),))):
                self.assertEqual(await monitor_once(state, NOW, send), 0)
            send.assert_not_awaited()
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=(event(1), event(2)))):
                self.assertEqual(await monitor_once(state, NOW, send), 1)
            send.assert_awaited_once()

    async def test_same_id_empty_and_disappeared_are_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            state.write({"version": 1, "events": {"1": {"first_seen_at": NOW.isoformat(), "published_at": NOW.isoformat()}}})
            send = AsyncMock()
            for rows in ((event(1),), ()):
                with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=rows)):
                    self.assertEqual(await monitor_once(state, NOW, send), 0)
            send.assert_not_awaited()

    async def test_known_id_with_changed_eta_or_status_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            state.write({"version": 1, "events": {"1": {"first_seen_at": NOW.isoformat(), "published_at": NOW.isoformat()}}})
            send = AsyncMock()
            changed_eta = event(1, end=1788870600000)
            changed_status = HidraquaEvent(1, "4AP", "AVE", "Calle Uno", None, None, None)
            for rows in ((changed_eta,), (changed_status,)):
                with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=rows)):
                    self.assertEqual(await monitor_once(state, NOW, send), 0)
            send.assert_not_awaited()

    async def test_deliberate_bootstrap_can_publish_current_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            send = AsyncMock()
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=(event(1),))):
                self.assertEqual(await monitor_once(state, NOW, send, publish_current_on_bootstrap=True), 1)
            send.assert_awaited_once()

    async def test_two_new_rows_are_grouped_and_duplicate_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            state.write({"version": 1, "events": {}})
            send = AsyncMock()
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=(event(1), event(2)))):
                self.assertEqual(await monitor_once(state, NOW, send), 2)
            self.assertEqual(send.await_count, 1)
            self.assertIn("🔹", send.await_args.args[0])
        payload = {"features": [
            {"attributes": {"CI_ID": 1, "CI_ESTADO": "5EC", "CI_MOTIVO": "AVE", "COD_MUNI": "03076"}},
            {"attributes": {"CI_ID": 1, "CI_ESTADO": "5EC", "CI_MOTIVO": "***", "COD_MUNI": "03076"}},
        ]}
        with self.assertRaises(HidraquaError):
            normalize_events(payload)

    async def test_error_leaves_existing_state_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hidraqua.json"
            state = HidraquaState(path)
            original = {"version": 1, "events": {"1": {"first_seen_at": NOW.isoformat(), "published_at": None}}}
            state.write(original)
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(side_effect=HidraquaError("bad"))):
                with self.assertRaises(HidraquaError):
                    await monitor_once(state, NOW, AsyncMock())
            self.assertEqual(state.read(), original)

    async def test_failed_group_is_not_marked_seen(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            state.write({"version": 1, "events": {}})
            send = AsyncMock(side_effect=RuntimeError("telegram down"))
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=(event(1), event(2)))):
                with self.assertRaises(RuntimeError):
                    await monitor_once(state, NOW, send)
            self.assertEqual(state.read()["events"], {})

    async def test_split_failure_marks_only_the_delivered_group(self):
        with tempfile.TemporaryDirectory() as directory:
            state = HidraquaState(Path(directory) / "hidraqua.json")
            state.write({"version": 1, "events": {}})
            send = AsyncMock(side_effect=[None, RuntimeError("telegram down")])
            rows = (event(1), event(2), event(3, motive="***"))
            with patch("telegrambot.hidraqua.fetch_active_events", new=AsyncMock(return_value=rows)):
                with self.assertRaises(RuntimeError):
                    await monitor_once(state, NOW, send, message_limit=1200)
            self.assertEqual(set(state.read()["events"]), {"1", "2"})


class HidraquaFormattingTests(unittest.TestCase):
    def test_safe_text_handles_missing_address_streets_and_eta(self):
        text = format_event(event(address=None, streets=None, end=None))
        self.assertIn("аварии на водопроводной сети", text)
        self.assertIn("Гуардамаре", text)
        self.assertNotIn("примерно к", text)

    def test_improvement_text_and_dst_epoch(self):
        text = format_event(event(motive="***"))
        self.assertIn("работах по улучшению", text)
        rows = normalize_events({"features": [{"attributes": {
            "CI_ID": 7, "CI_ESTADO": "4AP", "CI_MOTIVO": "AVE", "COD_MUNI": "03076",
            "CI_FH_INI_PREV": 1774747800000,
        }}]})
        self.assertEqual(rows[0].starts_at.strftime("%Y-%m-%d %H:%M %Z"), "2026-03-29 03:30 CEST")

    def test_location_streets_links_and_escaping(self):
        item = event(
            address="Calle Currica 51-51, 03140, Guardamar (Urbanització Bonavista)",
            streets="LA NANSA, COSTABELLA, LA MARINA",
        )
        text = format_event(item)
        self.assertIn("Urbanització Bonavista", text)
        self.assertIn("Calle Currica, 51", text)
        self.assertIn("Также затронуты улицы", text)
        self.assertEqual(text.count("https://www.google.com/maps/search/?"), 4)
        self.assertIn("query=Calle+Currica%2C+51", text)
        unsafe = format_event(event(address='Calle <x>& "7"', streets="A&B"))
        self.assertIn("Calle &lt;x&gt;&amp; &quot;7&quot;", unsafe)
        self.assertIn("A&amp;B", unsafe)

    def test_urbanization_with_unnumbered_street_uses_na_not_district(self):
        text = format_event(event(
            address="Avenida de Argentina, Guardamar del Segura (Urbanización El Raso)",
            streets=None,
        ), grouped=True)
        self.assertIn("В <b>Urbanización El Raso</b> на 📍", text)
        self.assertIn("<b>Avenida de Argentina</b>", text)
        self.assertNotIn("в районе 📍 <a", text)
        self.assertNotIn("Argentina</b></a>, произошла", text)

    def test_grouped_numbered_address_has_separator_comma(self):
        text = format_event(event(
            address="Calle Currica 51-51, Guardamar (Urbanització Bonavista)",
            streets=None,
        ), grouped=True)
        self.assertIn("Calle Currica, 51</b></a>, произошла авария", text)

    def test_grouped_messages_footer_and_size_boundary(self):
        rows = (event(1), event(2), event(3, motive="***"))
        grouped = format_messages(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0][0], (1, 2, 3))
        self.assertIn("сразу о нескольких", grouped[0][1])
        self.assertIn("⚠️ Возможно временное", grouped[0][1])
        self.assertIn("обЪявления Гуардамар", grouped[0][1])
        split = format_messages(rows, max_length=1200)
        self.assertGreater(len(split), 1)
        self.assertEqual(sum((list(ids) for ids, _ in split), []), [1, 2, 3])
        for _, payload in split:
            self.assertIn("обЪявления Гуардамар", payload)

    def test_every_final_payload_has_shared_footer(self):
        for rows in ((event(1),), (event(1), event(2))):
            for _, payload in format_messages(rows):
                self.assertTrue(payload.endswith("</a>"))
                self.assertIn("https://t.me/MarketGuardamar", payload)
