import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot._transport import BoundedFetchError
from telegrambot.guide import (
    GuideSourceError,
    GuideState,
    _allowed_aqualider_url,
    _fetch_json,
    _normalize_providers,
    _normalize_services,
    _validate_cross_references,
    active_pool,
    fetch_aqualider_catalog,
    sync_guide,
)
from telegrambot.state import StateError


MADRID = ZoneInfo("Europe/Madrid")


def sample_services(name="Natación Bebés"):
    return [
        {
            "id": "2",
            "name": name,
            "providers": [2],
        }
    ]


def sample_providers(name="Primera quincena de Julio"):
    return [
        {
            "id": "2",
            "name": name,
            "services": [2],
        }
    ]


def snapshot(moment, service_name="Natación Bebés"):
    return {
        "observed_at": moment.isoformat(),
        "services": [
            {"id": 2, "name": service_name, "providers": [2]},
        ],
        "providers": [
            {
                "id": 2,
                "name": "Primera quincena de Julio",
                "services": [2],
            },
        ],
    }


class PoolSeasonTests(unittest.TestCase):
    def test_fixed_pool_season_boundaries(self):
        cases = {
            date(2026, 6, 15): "indoor",
            date(2026, 6, 16): "outdoor",
            date(2026, 9, 15): "outdoor",
            date(2026, 9, 16): "indoor",
            date(2027, 1, 1): "indoor",
        }
        for local_day, expected in cases.items():
            with self.subTest(local_day=local_day):
                self.assertEqual(active_pool(local_day), expected)


class AqualiderSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_url_policy_is_exact_and_https_only(self):
        self.assertTrue(
            _allowed_aqualider_url(
                "https://aqualidernatacion.simplybook.it/v2/service/"
            )
        )
        for invalid in (
            "http://aqualidernatacion.simplybook.it/v2/service/",
            "https://simplybook.it/v2/service/",
            "https://aqualidernatacion.simplybook.it.evil.example/v2/service/",
            "https://aqualidernatacion.simplybook.it/other/service/",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(_allowed_aqualider_url(invalid))

    def test_normalization_keeps_only_small_catalogue_facts(self):
        services = _normalize_services(sample_services())
        providers = _normalize_providers(sample_providers())
        _validate_cross_references(services, providers)
        self.assertEqual(
            services,
            ({"id": 2, "name": "Natación Bebés", "providers": [2]},),
        )
        self.assertEqual(
            providers,
            ({
                "id": 2,
                "name": "Primera quincena de Julio",
                "services": [2],
            },),
        )

    def test_unknown_cross_reference_is_rejected(self):
        services = _normalize_services(sample_services())
        providers = _normalize_providers([
            {"id": "3", "name": "Other", "services": [2]}
        ])
        with self.assertRaises(GuideSourceError):
            _validate_cross_references(services, providers)

    async def test_fetch_requires_json_even_on_http_200(self):
        queued = BoundedFetchError(
            "Unexpected content type", code="CONTENT-TYPE"
        )
        with patch("telegrambot.guide.fetch_bounded", side_effect=queued):
            with self.assertRaises(GuideSourceError) as captured:
                await _fetch_json("service/", limit_bytes=1024)
        self.assertEqual(captured.exception.diagnostic_code, "CONTENT-TYPE")

    async def test_catalog_fetch_normalizes_two_stateless_endpoints(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        with patch(
            "telegrambot.guide._fetch_json",
            new=AsyncMock(side_effect=(sample_services(), sample_providers())),
        ) as fetch:
            result = await fetch_aqualider_catalog(moment)
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(result, snapshot(moment))


class GuideStateTests(unittest.TestCase):
    def test_state_round_trip_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            state = GuideState(path)
            moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            value = {"version": 1, "aqualider_catalog": snapshot(moment)}
            state.write(value)
            self.assertEqual(state.read(), value)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(StateError):
                state.read()


class GuideSyncTests(unittest.IsolatedAsyncioTestCase):
    def _environment(self, directory):
        return {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "-100123",
            "GUIDE_STATE_PATH": str(Path(directory) / "guide.json"),
            "PINNED_GUIDE_STATE_PATH": str(Path(directory) / "pinned.json"),
        }

    @staticmethod
    def _pinned_messages():
        return {
            "root": 100,
            "pool_indoor": 101,
            "pool_outdoor": 102,
            "swimming": 103,
        }

    async def test_first_success_is_silent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            publish = AsyncMock(return_value=self._pinned_messages())
            send = AsyncMock()
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.send_message", new=send),
            ):
                result = await sync_guide(moment)
            self.assertEqual(result, "baseline")
            send.assert_not_awaited()
            saved = json.loads(
                Path(directory, "guide.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["aqualider_catalog"], current)

    async def test_source_failure_preserves_last_good_and_still_reconciles_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            state = GuideState(Path(directory) / "guide.json")
            previous = snapshot(moment)
            state.write({"version": 1, "aqualider_catalog": previous})
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(
                        side_effect=GuideSourceError("queue", code="CONTENT-TYPE")
                    ),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                result = await sync_guide(moment)
            self.assertEqual(result, "source-unavailable")
            publish.assert_awaited_once()
            self.assertEqual(state.read()["aqualider_catalog"], previous)

    async def test_catalog_change_is_saved_without_public_programme_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_moment = datetime(2026, 9, 15, 16, 30, tzinfo=MADRID)
            moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            state = GuideState(Path(directory) / "guide.json")
            state.write({
                "version": 1,
                "aqualider_catalog": snapshot(previous_moment),
            })
            changed = snapshot(moment, service_name="Natación Bebés 2027")
            send = AsyncMock()
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=changed),
                ),
                patch(
                    "telegrambot.guide.publish_pinned_guide",
                    new=AsyncMock(return_value=self._pinned_messages()),
                ),
                patch("telegrambot.guide.send_message", new=send),
            ):
                result = await sync_guide(moment)
            self.assertEqual(result, "catalog-changed")
            send.assert_not_awaited()
            self.assertEqual(state.read()["aqualider_catalog"], changed)

    async def test_due_season_notice_is_sent_once(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 15, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            send = AsyncMock(return_value=501)
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await sync_guide(moment)
                await sync_guide(moment)
            send.assert_awaited_once()
            text = send.await_args.args[2]
            self.assertIn("Крытый бассейн Manel Estiarte", text)
            self.assertIn("https://t.me/c/123/101", text)
            self.assertIn("https://t.me/c/123/103", text)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["season_notice"]["key"], "2026:indoor")
            self.assertEqual(saved["season_notice"]["message_id"], 501)


if __name__ == "__main__":
    unittest.main()
