import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot._transport import BoundedFetchError
from telegrambot.dinamizacion import DinamizacionSourceError
from telegrambot.guide import (
    GuideSourceError,
    GuideState,
    WIFI_VERIFIED_ASSET_URL,
    _allowed_aqualider_url,
    _bathing_water_notice_key,
    _bathing_water_notice_text,
    _allowed_ora_url,
    _fetch_json,
    _normalize_providers,
    _normalize_services,
    _ora_schedule_matches,
    _parking_notice_key,
    _publish_bathing_water_pending_notice,
    _refresh_bathing_water_source,
    _parking_notice_text,
    _season_notice_key,
    _validate_cross_references,
    active_parking,
    active_pool,
    fetch_aqualider_catalog,
    sync_guide,
)
from telegrambot.sporttia import SporttiaSourceError
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


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


def bathing_report(
    moment,
    *,
    start="2026-06-15",
    end="2026-06-21",
    url=(
        "https://www.guardamardelsegura.es/wp-content/uploads/"
        "2026/06/report.pdf"
    ),
    centro_water="good",
    roqueta_sand="good",
    ortigues_sand="good",
):
    beaches = []
    for name in (
        "Tusales", "Vivers", "Babilonia", "Centro",
        "La Roqueta", "Moncayo", "Ortigues",
    ):
        beaches.append({
            "name": name,
            "water_analysis": "excellent",
            "water_appearance": centro_water if name == "Centro" else "excellent",
            "sand_appearance": (
                roqueta_sand if name == "La Roqueta"
                else ortigues_sand if name == "Ortigues"
                else "excellent"
            ),
        })
    return {
        "observed_at": moment.isoformat(),
        "report_start": start,
        "report_end": end,
        "report_url": url,
        "beaches": beaches,
    }


def bathing_programme(moment, report):
    return {
        "observed_at": moment.isoformat(),
        "season_year": int(report["report_start"][:4]),
        "season_start": f'{report["report_start"][:4]}-06-01',
        "season_end": f'{report["report_start"][:4]}-09-15',
        "latest_report_start": report["report_start"],
        "latest_report_end": report["report_end"],
        "latest_report_url": report["report_url"],
    }


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


class BathingWaterGuideTests(unittest.IsolatedAsyncioTestCase):
    def test_notice_uses_test_tube_and_separates_lab_from_visual_inspection(self):
        moment = datetime(2026, 6, 22, 9, 2, tzinfo=MADRID)
        text = _bathing_water_notice_text(bathing_report(moment))

        self.assertIn("🧪 <b>Качество воды на пляжах</b>", text)
        self.assertIn("качество воды отличное на всех 7 пляжах", text)
        self.assertIn("Внешний вид воды: хорошо — Centro", text)
        self.assertIn("Состояние песка: хорошо — La Roqueta, Ortigues", text)
        self.assertIn("Остальные показатели визуального осмотра — отлично", text)
        self.assertIn("15–21 июня 2026", text)
        self.assertIn("Официальный отчёт", text)
        self.assertNotIn("🌊", text)

    def test_notice_groups_nonexcellent_lab_results_by_beach(self):
        moment = datetime(2026, 6, 22, 9, 2, tzinfo=MADRID)
        report = bathing_report(moment)
        report["beaches"][0]["water_analysis"] = "good"
        report["beaches"][1]["water_analysis"] = "sufficient"
        report["beaches"][2]["water_analysis"] = "insufficient"

        text = _bathing_water_notice_text(report)

        self.assertIn("Отличное — Centro, La Roqueta, Moncayo, Ortigues", text)
        self.assertIn("Хорошее — Tusales", text)
        self.assertIn("Удовлетворительное — Vivers", text)
        self.assertIn("Недостаточное — Babilonia", text)

    async def test_first_parsed_report_is_silent_baseline(self):
        moment = datetime(2026, 6, 22, 9, 2, tzinfo=MADRID)
        report = bathing_report(moment)
        programme = bathing_programme(moment, report)
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state = state_store.read()
            with (
                patch(
                    "telegrambot.guide.fetch_bathing_water_snapshot",
                    new=AsyncMock(return_value=programme),
                ),
                patch(
                    "telegrambot.guide.fetch_bathing_water_report",
                    new=AsyncMock(return_value=report),
                ),
            ):
                await _refresh_bathing_water_source(moment, state, state_store)

            saved = state_store.read()
            self.assertEqual(saved["bathing_water_report_snapshot"], report)
            self.assertNotIn("bathing_water_pending_notice", saved)

    async def test_new_report_period_sets_one_pending_notice_even_with_same_url(self):
        first_moment = datetime(2026, 6, 22, 9, 2, tzinfo=MADRID)
        next_moment = datetime(2026, 6, 29, 9, 2, tzinfo=MADRID)
        first = bathing_report(first_moment)
        second = bathing_report(
            next_moment,
            start="2026-06-22",
            end="2026-06-28",
            url=first["report_url"],
        )
        programme = bathing_programme(next_moment, second)
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state_store.write({
                "version": 1,
                "bathing_water_report_snapshot": first,
            })
            state = state_store.read()
            fetch = AsyncMock(return_value=second)
            with (
                patch(
                    "telegrambot.guide.fetch_bathing_water_snapshot",
                    new=AsyncMock(return_value=programme),
                ),
                patch(
                    "telegrambot.guide.fetch_bathing_water_report",
                    new=fetch,
                ),
            ):
                await _refresh_bathing_water_source(next_moment, state, state_store)

            saved = state_store.read()
            self.assertEqual(fetch.await_count, 1)
            self.assertEqual(saved["bathing_water_report_snapshot"], second)
            self.assertEqual(
                saved["bathing_water_pending_notice"],
                _bathing_water_notice_key(second),
            )

    async def test_public_notice_is_recorded_and_not_duplicated(self):
        moment = datetime(2026, 6, 29, 9, 2, tzinfo=MADRID)
        report = bathing_report(moment, start="2026-06-22", end="2026-06-28")
        key = _bathing_water_notice_key(report)
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state_store.write({
                "version": 1,
                "bathing_water_report_snapshot": report,
                "bathing_water_pending_notice": key,
            })
            state = state_store.read()
            send = AsyncMock(return_value=701)
            with patch("telegrambot.guide.send_message", new=send):
                await _publish_bathing_water_pending_notice(
                    "token", "-100123", state, state_store
                )
                await _publish_bathing_water_pending_notice(
                    "token", "-100123", state, state_store
                )

            self.assertEqual(send.await_count, 1)
            saved = state_store.read()
            self.assertEqual(saved["bathing_water_notice"]["message_id"], 701)
            self.assertNotIn("bathing_water_pending_notice", saved)
            self.assertNotIn("bathing_water_notice_uncertain", saved)

    async def test_explicit_public_notice_failure_remains_pending(self):
        moment = datetime(2026, 6, 29, 9, 2, tzinfo=MADRID)
        report = bathing_report(moment, start="2026-06-22", end="2026-06-28")
        key = _bathing_water_notice_key(report)
        rejected = TelegramError(
            "bad request", retryable=False, status=400, code="HTTP-400"
        )
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state_store.write({
                "version": 1,
                "bathing_water_report_snapshot": report,
                "bathing_water_pending_notice": key,
            })
            state = state_store.read()
            send = AsyncMock(side_effect=rejected)
            with patch("telegrambot.guide.send_message", new=send):
                with self.assertRaises(TelegramError):
                    await _publish_bathing_water_pending_notice(
                        "token", "-100123", state, state_store
                    )

            saved = state_store.read()
            self.assertEqual(saved["bathing_water_pending_notice"], key)
            self.assertNotIn("bathing_water_notice_uncertain", saved)

    async def test_ambiguous_public_notice_is_not_blindly_retried(self):
        moment = datetime(2026, 6, 29, 9, 2, tzinfo=MADRID)
        report = bathing_report(moment, start="2026-06-22", end="2026-06-28")
        key = _bathing_water_notice_key(report)
        timeout = TelegramError("timeout", retryable=True, code="TIMEOUT")
        with tempfile.TemporaryDirectory() as directory:
            state_store = GuideState(Path(directory) / "guide.json")
            state_store.write({
                "version": 1,
                "bathing_water_report_snapshot": report,
                "bathing_water_pending_notice": key,
            })
            state = state_store.read()
            send = AsyncMock(side_effect=timeout)
            with patch("telegrambot.guide.send_message", new=send):
                await _publish_bathing_water_pending_notice(
                    "token", "-100123", state, state_store
                )
                await _publish_bathing_water_pending_notice(
                    "token", "-100123", state, state_store
                )

            self.assertEqual(send.await_count, 1)
            saved = state_store.read()
            self.assertEqual(saved["bathing_water_notice_uncertain"], key)
            self.assertEqual(saved["bathing_water_pending_notice"], key)


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

    def test_notice_key_exists_only_before_a_pool_change(self):
        cases = {
            date(2026, 6, 14): None,
            date(2026, 6, 15): "2026:outdoor",
            date(2026, 6, 16): None,
            date(2026, 9, 14): None,
            date(2026, 9, 15): "2026:indoor",
            date(2026, 9, 16): None,
            date(2026, 12, 31): None,
        }
        for local_day, expected in cases.items():
            with self.subTest(local_day=local_day):
                self.assertEqual(_season_notice_key(local_day), expected)


class ParkingSeasonTests(unittest.TestCase):
    def test_fixed_parking_season_boundaries(self):
        cases = {
            date(2026, 6, 14): "free",
            date(2026, 6, 15): "paid",
            date(2026, 9, 15): "paid",
            date(2026, 9, 16): "free",
            date(2027, 1, 1): "free",
        }
        for local_day, expected in cases.items():
            with self.subTest(local_day=local_day):
                self.assertEqual(active_parking(local_day), expected)

    def test_notice_key_exists_only_before_parking_change(self):
        cases = {
            date(2026, 6, 13): None,
            date(2026, 6, 14): "2026:paid",
            date(2026, 6, 15): None,
            date(2026, 9, 14): None,
            date(2026, 9, 15): "2026:free",
            date(2026, 9, 16): None,
        }
        for local_day, expected in cases.items():
            with self.subTest(local_day=local_day):
                self.assertEqual(_parking_notice_key(local_day), expected)

    def test_paid_notice_copy_is_parking_only(self):
        text = _parking_notice_text("2026:paid")
        self.assertIn("с завтрашнего дня платно", text)
        self.assertIn("С <b>15 июня</b>", text)
        self.assertIn("10:00–20:00", text)
        self.assertIn("15 сентября включительно", text)
        self.assertNotIn("карточк", text)
        self.assertNotIn("SafeBeach", text)
        self.assertNotIn("Пляж", text)

    def test_free_notice_copy_is_parking_only(self):
        text = _parking_notice_text("2026:free")
        self.assertIn("с завтрашнего дня бесплатно", text)
        self.assertIn("С <b>16 сентября</b>", text)
        self.assertNotIn("карточк", text)
        self.assertNotIn("SafeBeach", text)
        self.assertNotIn("Пляж", text)

    def test_ora_url_policy_is_exact_https(self):
        self.assertTrue(
            _allowed_ora_url(
                "https://oraguardamar.gruposetex.es/tarifas-y-horarios"
            )
        )
        for invalid in (
            "http://oraguardamar.gruposetex.es/tarifas-y-horarios",
            "https://gruposetex.es/tarifas-y-horarios",
            "https://oraguardamar.gruposetex.es.evil.example/tarifas-y-horarios",
            "https://oraguardamar.gruposetex.es/otra-ruta",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(_allowed_ora_url(invalid))

    def test_ora_schedule_requires_reviewed_dates_days_and_hours(self):
        valid = """
        <h6>DEL 15 DE JUNIO AL 15 DE SEPTIEMBRE</h6>
        <p>Lunes a viernes, sábados, domingos y festivos</p>
        <p>10:00 AM - 20:00 PM</p>
        """.encode("utf-8")
        self.assertTrue(_ora_schedule_matches(valid))
        self.assertFalse(
            _ora_schedule_matches(
                valid.replace(b"20:00", b"21:00")
            )
        )


class AqualiderSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_url_policy_is_exact_https_and_total(self):
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
            "https://aqualidernatacion.simplybook.it:bad/v2/service/",
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

    def test_non_integer_identifier_is_rejected(self):
        invalid = sample_services()
        invalid[0]["id"] = 2.5
        with self.assertRaises(GuideSourceError):
            _normalize_services(invalid)

    def test_unknown_cross_reference_is_rejected(self):
        services = _normalize_services(sample_services())
        providers = _normalize_providers([
            {"id": "3", "name": "Other", "services": [2]}
        ])
        with self.assertRaises(GuideSourceError):
            _validate_cross_references(services, providers)

    def test_one_sided_cross_reference_is_rejected(self):
        services = _normalize_services(sample_services())
        providers = _normalize_providers([
            {"id": "2", "name": "Period", "services": []}
        ])
        with self.assertRaises(GuideSourceError) as captured:
            _validate_cross_references(services, providers)
        self.assertEqual(captured.exception.diagnostic_code, "SCHEMA")

    async def test_fetch_requires_json_even_on_http_200(self):
        queued = BoundedFetchError(
            "Unexpected content type", code="CONTENT-TYPE"
        )
        with patch("telegrambot.guide.fetch_bounded", side_effect=queued):
            with self.assertRaises(GuideSourceError) as captured:
                await _fetch_json("service/", limit_bytes=1024)
        self.assertEqual(captured.exception.diagnostic_code, "CONTENT-TYPE")

    async def test_catalog_fetch_rejects_naive_observation_time_before_network(self):
        fetch = AsyncMock()
        with patch("telegrambot.guide._fetch_json", new=fetch):
            with self.assertRaises(ValueError):
                await fetch_aqualider_catalog(datetime(2026, 9, 16, 16, 30))
        fetch.assert_not_awaited()

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

    def test_uncertain_parking_notice_state_requires_a_string_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            path.write_text(
                json.dumps({"version": 1, "parking_notice_uncertain": 123}),
                encoding="utf-8",
            )
            with self.assertRaises(StateError):
                GuideState(path).read()

    def test_uncertain_notice_state_requires_a_string_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            path.write_text(
                json.dumps({"version": 1, "season_notice_uncertain": 123}),
                encoding="utf-8",
            )
            with self.assertRaises(StateError):
                GuideState(path).read()


class GuideSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bathing_water_fetch = AsyncMock(
            side_effect=lambda now: {
                "observed_at": now.isoformat(),
                "season_year": now.year,
                "season_start": f"{now.year}-06-01",
                "season_end": f"{now.year}-09-15",
                "latest_report_start": None,
                "latest_report_end": None,
                "latest_report_url": None,
            }
        )
        self.bathing_water_patch = patch(
            "telegrambot.guide.fetch_bathing_water_snapshot",
            new=self.bathing_water_fetch,
        )
        self.bathing_water_patch.start()
        self.addCleanup(self.bathing_water_patch.stop)

        self.wifi_asset_fetch = AsyncMock(return_value=WIFI_VERIFIED_ASSET_URL)
        self.wifi_asset_patch = patch(
            "telegrambot.guide.fetch_current_wifi_asset",
            new=self.wifi_asset_fetch,
        )
        self.wifi_asset_patch.start()
        self.addCleanup(self.wifi_asset_patch.stop)

        self.sporttia_fetch = AsyncMock(
            side_effect=lambda now: {
                "observed_at": now.isoformat(),
                "activities": [],
            }
        )
        self.sporttia_patch = patch(
            "telegrambot.guide.fetch_sporttia_catalog",
            new=self.sporttia_fetch,
        )
        self.sporttia_patch.start()
        self.addCleanup(self.sporttia_patch.stop)
        self.music_fetch = AsyncMock(
            side_effect=lambda now: {
                "observed_at": now.isoformat(),
                "season": "2026/27",
                "schedule_url": None,
                "jardin_registration": None,
                "school_registration": None,
            }
        )
        self.music_patch = patch(
            "telegrambot.guide.fetch_music_school_catalog",
            new=self.music_fetch,
        )
        self.music_patch.start()
        self.addCleanup(self.music_patch.stop)

        self.chess_fetch = AsyncMock(
            side_effect=lambda now: {
                "observed_at": now.isoformat(),
                "source_url": "https://ajedrezdamadeguardamar.com/cuotas/",
                "days": ["tuesday", "thursday"],
                "start_time": "16:00",
                "end_time": "20:00",
                "level_from": "INICIACIÓN",
                "level_to": "AVANZADO",
            }
        )
        self.chess_patch = patch(
            "telegrambot.guide.fetch_chess_school_snapshot",
            new=self.chess_fetch,
        )
        self.chess_patch.start()
        self.addCleanup(self.chess_patch.stop)

        self.literary_fetch = AsyncMock(
            side_effect=lambda now: {
                "observed_at": now.isoformat(),
                "source_url": (
                    "https://www.bibliotecaspublicas.es/guardamardelsegura/"
                    "actividades-programas/Tertulia-Literaria-de-Guardamar.html"
                ),
                "day": "tuesday",
                "start_time": "11:00",
                "end_time": "13:00",
                "venue": "library_auditorium",
            }
        )
        self.literary_patch = patch(
            "telegrambot.guide.fetch_literary_group_snapshot",
            new=self.literary_fetch,
        )
        self.literary_patch.start()
        self.addCleanup(self.literary_patch.stop)

        self.dinamizacion_discovery = AsyncMock(return_value=None)
        self.dinamizacion_patch = patch(
            "telegrambot.guide.discover_dinamizacion_campaign",
            new=self.dinamizacion_discovery,
        )
        self.dinamizacion_patch.start()
        self.addCleanup(self.dinamizacion_patch.stop)

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
            self.assertEqual(
                saved["last_successful_sync_day"],
                moment.date().isoformat(),
            )

    async def test_failed_card_reconciliation_does_not_leave_success_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 9, 2, tzinfo=MADRID)
            current = snapshot(moment)
            state = GuideState(Path(directory) / "guide.json")
            state.write({
                "version": 1,
                "last_successful_sync_day": moment.date().isoformat(),
            })
            failure = StateError("pinned reconciliation failed")
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch(
                    "telegrambot.guide.publish_pinned_guide",
                    new=AsyncMock(side_effect=failure),
                ),
            ):
                with self.assertRaises(StateError):
                    await sync_guide(moment)
            saved = state.read()
            self.assertNotIn("last_successful_sync_day", saved)

    async def test_sporttia_is_attempted_at_most_once_per_local_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 14, 0, tzinfo=MADRID)
            later = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)
                await sync_guide(later)
            self.assertEqual(self.sporttia_fetch.await_count, 1)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["sporttia_last_attempt_day"], "2026-09-16")

    async def test_bathing_water_is_attempted_at_most_once_per_local_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 9, 2, tzinfo=MADRID)
            later = datetime(2026, 9, 16, 19, 45, tzinfo=MADRID)
            current = snapshot(moment)
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)
                await sync_guide(later)
            self.assertEqual(self.bathing_water_fetch.await_count, 1)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(
                saved["bathing_water_last_attempt_day"],
                "2026-09-16",
            )
            self.assertEqual(
                saved["bathing_water_snapshot"]["season_start"],
                "2026-06-01",
            )

    async def test_music_school_is_attempted_at_most_once_per_local_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 14, 0, tzinfo=MADRID)
            later = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)
                await sync_guide(later)
            self.assertEqual(self.music_fetch.await_count, 1)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(
                saved["music_school_last_attempt_day"], "2026-09-16"
            )
            self.assertEqual(saved["music_school_catalog"]["season"], "2026/27")

    async def test_sporttia_failure_is_not_retried_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 14, 0, tzinfo=MADRID)
            later = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            self.sporttia_fetch.side_effect = SporttiaSourceError(
                "timeout", code="TIMEOUT"
            )
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=snapshot(moment)),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)
                await sync_guide(later)
            self.assertEqual(self.sporttia_fetch.await_count, 1)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["sporttia_last_attempt_day"], "2026-09-16")
            self.assertNotIn("sporttia_catalog", saved)

    async def test_dinamizacion_form_failure_recovers_via_campaign_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 18, 16, 30, tzinfo=MADRID)
            campaign_url = (
                "https://www.guardamardelsegura.es/2026/09/07/"
                "programa-dinamizacion-social-2026-2027/"
            )
            previous = {
                "observed_at": datetime(
                    2026, 9, 17, 16, 30, tzinfo=MADRID
                ).isoformat(),
                "season": "2026/27",
                "campaign_url": campaign_url,
                "form_url": "https://docs.google.com/forms/d/e/old/viewform",
                "registration_start": "2026-09-09",
                "registration_end": "2026-09-16",
                "registration_until_full": True,
                "resident_priority": True,
                "groups": [
                    {
                        "key": "mindful_movement",
                        "schedules": ["Пн/Ср · 11:15–12:15"],
                        "start_date": None,
                        "end_date": None,
                    }
                ],
            }
            recovered = dict(previous)
            recovered["observed_at"] = moment.isoformat()
            recovered["form_url"] = (
                "https://docs.google.com/forms/d/e/new/viewform"
            )

            state = GuideState(Path(directory) / "guide.json")
            state.write({
                "version": 1,
                "dinamizacion_snapshot": previous,
            })
            publish = AsyncMock(return_value=self._pinned_messages())
            discovery = AsyncMock(return_value=(campaign_url, "2026/27"))
            refresh = AsyncMock(
                side_effect=DinamizacionSourceError(
                    "old form unavailable",
                    code="HTTP-404",
                )
            )
            recover = AsyncMock(return_value=recovered)

            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=snapshot(moment)),
                ),
                patch(
                    "telegrambot.guide.discover_dinamizacion_campaign",
                    new=discovery,
                ),
                patch(
                    "telegrambot.guide.refresh_dinamizacion_snapshot",
                    new=refresh,
                ),
                patch(
                    "telegrambot.guide.fetch_dinamizacion_snapshot",
                    new=recover,
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)

            refresh.assert_awaited_once_with(previous, moment)
            recover.assert_awaited_once_with(
                campaign_url,
                "2026/27",
                moment,
            )
            saved = state.read()
            self.assertEqual(
                saved["dinamizacion_snapshot"]["form_url"],
                "https://docs.google.com/forms/d/e/new/viewform",
            )

    async def test_sync_lock_covers_pinned_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            entered = asyncio.Event()
            release = asyncio.Event()

            async def blocking_publish(*args, **kwargs):
                entered.set()
                await release.wait()
                return self._pinned_messages()

            fetch = AsyncMock(return_value=current)
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=fetch,
                ),
                patch(
                    "telegrambot.guide.publish_pinned_guide",
                    new=blocking_publish,
                ),
            ):
                first = asyncio.create_task(sync_guide(moment))
                await asyncio.wait_for(entered.wait(), timeout=2.0)
                try:
                    with self.assertRaises(StateError):
                        await asyncio.wait_for(sync_guide(moment), timeout=2.0)
                    self.assertEqual(fetch.await_count, 1)
                finally:
                    release.set()
                result = await asyncio.wait_for(first, timeout=2.0)
            self.assertEqual(result, "baseline")

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

    async def test_wifi_change_updates_card_before_public_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 21, 9, 2, tzinfo=MADRID)
            current = snapshot(moment)
            changed_url = (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/10/wifi-map.pdf"
            )
            wifi_snapshot = {
                "observed_at": moment.isoformat(),
                "asset_url": changed_url,
                "points": [
                    {"key": "music_school", "networks": [
                        {"ssid": "WiFi4EU", "password": None}
                    ]},
                    {"key": "culture_house", "networks": [
                        {"ssid": "WiFi4EU", "password": None}
                    ]},
                    {"key": "los_pinos", "networks": [
                        {"ssid": "WiFi4EU", "password": None}
                    ]},
                    {"key": "constitution_square", "networks": [
                        {"ssid": "vegafibra_gratis", "password": "newpass"}
                    ]},
                    {"key": "seafront", "networks": [
                        {"ssid": "vegafibra_gratis", "password": "vegafibra"}
                    ]},
                    {"key": "study_room", "networks": [
                        {"ssid": "wifi_1EO9C", "password": "vegafibra"}
                    ]},
                    {"key": "library", "networks": [
                        {"ssid": "wifibiblioteca", "password": "biblimar"},
                        {"ssid": "biblioteca infantil", "password": "menjallibres"},
                        {"ssid": "vicenteramos", "password": "menjallibres"},
                    ]},
                ],
            }
            sequence = []

            async def publish(*args, **kwargs):
                sequence.append("card")
                self.assertEqual(kwargs["wifi_snapshot"], wifi_snapshot)
                messages = self._pinned_messages()
                messages["wifi"] = 150
                return messages

            async def send(*args, **kwargs):
                sequence.append("notice")
                self.assertIn("Обновилась информация", args[2])
                return 601

            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch(
                    "telegrambot.guide.fetch_current_wifi_asset",
                    new=AsyncMock(return_value=changed_url),
                ),
                patch(
                    "telegrambot.guide.fetch_wifi_snapshot",
                    new=AsyncMock(return_value=wifi_snapshot),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await sync_guide(moment)

            self.assertEqual(sequence, ["card", "notice"])
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["wifi_snapshot"], wifi_snapshot)
            self.assertEqual(saved["wifi_notice"]["message_id"], 601)
            self.assertNotIn("wifi_pending_asset_url", saved)

    async def test_due_parking_notice_waits_for_evening(self):
        with tempfile.TemporaryDirectory() as directory:
            morning = datetime(2026, 6, 14, 9, 2, tzinfo=MADRID)
            current = snapshot(morning)
            send = AsyncMock()
            verify = AsyncMock()
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.verify_current_ora_schedule", new=verify),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await sync_guide(morning)
            verify.assert_not_awaited()
            send.assert_not_awaited()

    async def test_due_parking_notice_is_verified_and_sent_once_in_evening(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 6, 14, 19, 45, tzinfo=MADRID)
            current = snapshot(moment)
            send = AsyncMock(return_value=601)
            verify = AsyncMock()
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.verify_current_ora_schedule", new=verify),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await sync_guide(moment)
                await sync_guide(moment)
            verify.assert_awaited_once()
            send.assert_awaited_once()
            self.assertTrue(send.await_args.kwargs["retry_only_rate_limits"])
            text = send.await_args.args[2]
            self.assertIn("Zona Azul — с завтрашнего дня платно", text)
            self.assertIn("С <b>15 июня</b>", text)
            self.assertIn("10:00–20:00", text)
            self.assertIn("15 сентября включительно", text)
            self.assertNotIn("SafeBeach", text)
            self.assertNotIn("карточк", text)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["parking_notice"]["key"], "2026:paid")
            self.assertEqual(saved["parking_notice"]["message_id"], 601)

    async def test_parking_notice_fails_closed_when_ora_contract_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 6, 14, 19, 45, tzinfo=MADRID)
            current = snapshot(moment)
            send = AsyncMock()
            verify = AsyncMock(
                side_effect=GuideSourceError(
                    "changed",
                    code="ORA-SCHEDULE",
                )
            )
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
                patch("telegrambot.guide.verify_current_ora_schedule", new=verify),
                patch("telegrambot.guide.send_message", new=send),
            ):
                await sync_guide(moment)
            verify.assert_awaited_once()
            send.assert_not_awaited()
            self.assertNotIn(
                "parking_notice",
                GuideState(Path(directory) / "guide.json").read(),
            )

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
            self.assertTrue(send.await_args.kwargs["retry_only_rate_limits"])
            text = send.await_args.args[2]
            self.assertIn("Крытый бассейн Manel Estiarte", text)
            self.assertIn("https://t.me/c/123/101", text)
            self.assertIn("https://t.me/c/123/103", text)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(saved["season_notice"]["key"], "2026:indoor")
            self.assertEqual(saved["season_notice"]["message_id"], 501)

    async def test_ambiguous_season_notice_is_recorded_and_not_retried_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 15, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            timeout = TelegramError(
                "timeout", retryable=True, code="TIMEOUT"
            )
            send = AsyncMock(side_effect=timeout)
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
                with self.assertRaises(TelegramError):
                    await sync_guide(moment)
                state = GuideState(Path(directory) / "guide.json").read()
                self.assertEqual(
                    state["season_notice_uncertain"], "2026:indoor"
                )
                result = await sync_guide(moment)
            self.assertEqual(result, "unchanged")
            self.assertEqual(send.await_count, 1)


if __name__ == "__main__":
    unittest.main()
