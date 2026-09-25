import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from telegrambot.digest import build_message
from telegrambot.emergency_risks import (
    EmergencyRiskDeliveryUncertain,
    EmergencyRiskError,
    EmergencyRiskState,
    HYDRO_NONE,
    HYDRO_PREEMERGENCIA,
    HYDRO_SITUATION_1,
    PrevifocRisk,
    _acknowledge,
    _transition,
    monitor_emergency_risks,
    parse_cce_emergencies_html,
    parse_cce_bulletin,
    parse_cce_text,
    parse_previfoc,
)
from telegrambot.models import MorningDigest

NOW = datetime.fromisoformat("2026-09-20T07:19:00+02:00")


def _previfoc_payload(fire=1, dry=1, alert_id=129166):
    return (
        '{"features":[{"attributes":{'
        f'"ZonaID":6,"RiesgoId":{fire},"TormentaID":{dry},'
        f'"Dia":1,"AlertaDiaID":{alert_id}'
        '}}]}'
    ).encode()


def _observed(status, when=NOW):
    return {"hydrology": status, "observed_at": when.isoformat()}


class EmergencyRiskTests(unittest.TestCase):
    def test_parse_previfoc_keeps_fire_and_dry_thunderstorms_independent(self):
        risk = parse_previfoc(_previfoc_payload(fire=2, dry=3))
        self.assertEqual(
            risk,
            PrevifocRisk(
                fire_level=2,
                dry_thunderstorm_level=3,
                alert_id=129166,
            ),
        )

    def test_parse_previfoc_fails_closed_on_wrong_contract(self):
        payloads = [
            b'{"features":[]}',
            b'{"features":[{"attributes":{"ZonaID":7,"RiesgoId":1,"TormentaID":1,"Dia":1,"AlertaDiaID":1}}]}',
            b'{"features":[{"attributes":{"ZonaID":6,"RiesgoId":4,"TormentaID":1,"Dia":1,"AlertaDiaID":1}}]}',
            b'{"features":[{"attributes":{"ZonaID":6,"RiesgoId":1,"TormentaID":1,"Dia":2,"AlertaDiaID":1}}]}',
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(EmergencyRiskError):
                    parse_previfoc(payload)

    def test_cce_html_exact_empty_marker_is_clear(self):
        payload = b"""
        <html><body><h1>Emergencias</h1>
        <div>SIN EMERGENCIAS VIGENTES</div></body></html>
        """
        self.assertEqual(parse_cce_emergencies_html(payload), HYDRO_NONE)

    def test_cce_html_recognizes_segura_situation(self):
        payload = """
        <html><body><h1>Emergencias vigentes</h1>
        <div>Plan especial frente al riesgo de inundaciones</div>
        <div>Cuenca del Segura</div>
        <div>SITUACIÓN 1</div>
        </body></html>
        """.encode()
        self.assertEqual(
            parse_cce_emergencies_html(payload),
            HYDRO_SITUATION_1,
        )

    def test_cce_situation_number_without_hydrological_context_is_not_accepted(self):
        payload = """
        <html><body><h1>Emergencias vigentes</h1>
        <div>Guardamar del Segura</div>
        <div>SITUACIÓN 1</div>
        </body></html>
        """.encode()
        with self.assertRaises(EmergencyRiskError):
            parse_cce_emergencies_html(payload)

    def test_cce_html_without_explicit_clear_or_segura_state_is_unknown(self):
        payload = """
        <html><body><h1>Emergencias vigentes</h1>
        <div>Otra emergencia activa en Castellón</div>
        </body></html>
        """.encode()
        with self.assertRaises(EmergencyRiskError) as exc:
            parse_cce_emergencies_html(payload)
        self.assertEqual(exc.exception.diagnostic_code, "UNKNOWN")

    def test_cce_bulletin_recognizes_segura_hydrological_preemergency(self):
        text = """
        FECHA 20/09/2026
        HORA 07:00
        PLANES DE EMERGENCIA ACTIVADOS
        PREEMERGENCIA HIDROLÓGICA
        CUENCA DEL SEGURA
        """
        self.assertEqual(
            parse_cce_text(text, bulletin=True),
            HYDRO_PREEMERGENCIA,
        )

    def test_cce_bulletin_without_segura_hydrology_is_negative_observation(self):
        text = """
        FECHA 20/09/2026
        HORA 07:00
        PLANES DE EMERGENCIA ACTIVADOS
        Sin planes hidrológicos activos para la cuenca del Júcar.
        """
        self.assertEqual(parse_cce_text(text, bulletin=True), HYDRO_NONE)

    def test_cce_bulletin_requires_current_local_date(self):
        current = """
        FECHA 20/09/2026
        HORA 07:00
        PLANES DE EMERGENCIA ACTIVADOS
        Sin planes hidrológicos activos.
        """
        self.assertEqual(parse_cce_bulletin(current, NOW), HYDRO_NONE)

        stale = current.replace("20/09/2026", "19/09/2026")
        with self.assertRaises(EmergencyRiskError) as exc:
            parse_cce_bulletin(stale, NOW)
        self.assertEqual(exc.exception.diagnostic_code, "STALE")

    def test_cce_bulletin_accepts_nonstandard_pdf_date_separator(self):
        text = """
        FECHA 20·09·2026
        HORA: 07:00
        PLANES DE EMERGENCIA ACTIVADOS
        Sin planes hidrológicos activos.
        """
        self.assertEqual(parse_cce_bulletin(text, NOW), HYDRO_NONE)

    def test_cce_bulletin_rejects_implausible_future_timestamp(self):
        future = """
        FECHA 20/09/2026
        HORA 08:30
        PLANES DE EMERGENCIA ACTIVADOS
        Sin planes hidrológicos activos.
        """
        with self.assertRaises(EmergencyRiskError) as exc:
            parse_cce_bulletin(future, NOW)
        self.assertEqual(exc.exception.diagnostic_code, "STALE")

    def test_latest_valid_cce_observation_can_clear_older_active_state(self):
        value = EmergencyRiskState.empty()
        value["cce_pdf"] = _observed(
            HYDRO_SITUATION_1, NOW - timedelta(hours=1)
        )
        value["cce_html"] = _observed(HYDRO_NONE, NOW)
        self.assertEqual(
            EmergencyRiskState.current_hydrology(value),
            HYDRO_NONE,
        )

    def test_active_hydrology_wins_over_other_negative_observation(self):
        value = EmergencyRiskState.empty()
        value["cce_html"] = _observed(HYDRO_NONE)
        value["cce_pdf"] = _observed(HYDRO_SITUATION_1)
        self.assertEqual(
            EmergencyRiskState.current_hydrology(value),
            HYDRO_SITUATION_1,
        )

    def test_fire_level_two_is_silent_without_prior_state_but_extreme_is_visible(self):
        value = EmergencyRiskState.empty()
        value["previfoc"] = {
            "fire_level": 2,
            "dry_thunderstorm_level": 1,
            "alert_id": 1,
            "observed_at": NOW.isoformat(),
        }
        self.assertIsNone(_transition(value))

        value["previfoc"]["fire_level"] = 3
        transition = _transition(value)
        self.assertIsNotNone(transition)
        self.assertIn("Экстремальная пожарная опасность сегодня", transition)
        self.assertIn("максимальный уровень — <b>3 из 3</b>", transition)

    def test_high_fire_transition_uses_calm_current_state_copy(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 1
        value["published"]["dry_level"] = 1
        value["previfoc"] = {
            "fire_level": 2,
            "dry_thunderstorm_level": 1,
            "alert_id": 2,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)

        self.assertIsNotNone(message)
        self.assertIn("🌲 <b>Пожарная опасность сегодня</b>", message)
        self.assertIn(
            "установлен высокий уровень — <b>2 из 3</b>",
            message,
        )
        self.assertIn(
            "В природных зонах сегодня стоит особенно внимательно "
            "обращаться с огнём.",
            message,
        )
        self.assertNotIn("барбекю", message)
        self.assertNotIn("окурки", message)
        self.assertNotIn("произошедшем пожаре", message)
        self.assertNotIn("Previfoc", message)

    def test_extreme_fire_transition_is_current_and_not_alarmist(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 2
        value["published"]["dry_level"] = 1
        value["previfoc"] = {
            "fire_level": 3,
            "dry_thunderstorm_level": 1,
            "alert_id": 3,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)

        self.assertIsNotNone(message)
        self.assertIn(
            "🔥 <b>Экстремальная пожарная опасность сегодня</b>",
            message,
        )
        self.assertIn(
            "установлен максимальный уровень — <b>3 из 3</b>",
            message,
        )
        self.assertIn("избегать любых источников огня", message)
        self.assertIn("соблюдать действующие ограничения", message)
        self.assertNotIn("произошёл", message)
        self.assertNotIn("Previfoc", message)

    def test_extreme_to_high_fire_shows_current_high_state_only(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 3
        value["published"]["dry_level"] = 1
        value["previfoc"] = {
            "fire_level": 2,
            "dry_thunderstorm_level": 1,
            "alert_id": 4,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)

        self.assertIsNotNone(message)
        self.assertIn("🌲 <b>Пожарная опасность сегодня</b>", message)
        self.assertIn("высокий уровень — <b>2 из 3</b>", message)
        self.assertNotIn("снижен", message)
        self.assertNotIn("экстремального", message)

    def test_fire_transition_to_level_one_is_not_public(self):
        for previous_fire in (2, 3):
            with self.subTest(previous_fire=previous_fire):
                value = EmergencyRiskState.empty()
                value["published"]["fire_level"] = previous_fire
                value["published"]["dry_level"] = 1
                value["previfoc"] = {
                    "fire_level": 1,
                    "dry_thunderstorm_level": 1,
                    "alert_id": 5,
                    "observed_at": NOW.isoformat(),
                }

                self.assertIsNone(_transition(value))

    def test_direct_low_to_extreme_fire_transition_uses_extreme_copy(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 1
        value["published"]["dry_level"] = 1
        value["previfoc"] = {
            "fire_level": 3,
            "dry_thunderstorm_level": 1,
            "alert_id": 6,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)

        self.assertIsNotNone(message)
        self.assertIn("Экстремальная пожарная опасность сегодня", message)
        self.assertIn("максимальный уровень — <b>3 из 3</b>", message)

    def test_dry_thunderstorm_transitions_show_only_current_active_state(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 1
        value["published"]["dry_level"] = 1
        value["previfoc"] = {
            "fire_level": 1,
            "dry_thunderstorm_level": 2,
            "alert_id": 1,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)
        self.assertIsNotNone(message)
        self.assertIn("⚡ <b>Сегодня возможны сухие грозы</b>", message)
        self.assertIn("сегодня отмечена вероятность сухих гроз", message)
        self.assertNotIn("профилактическая информация", message)

        value["published"]["dry_level"] = 2
        value["previfoc"]["dry_thunderstorm_level"] = 3
        message = _transition(value)
        self.assertIsNotNone(message)
        self.assertIn("Высокий риск сухих гроз сегодня", message)

        value["published"]["dry_level"] = 3
        value["previfoc"]["dry_thunderstorm_level"] = 2
        message = _transition(value)
        self.assertIsNotNone(message)
        self.assertIn("Сегодня возможны сухие грозы", message)
        self.assertNotIn("снижен", message)

        value["published"]["dry_level"] = 2
        value["previfoc"]["dry_thunderstorm_level"] = 1
        self.assertIsNone(_transition(value))

    def test_mixed_fire_raise_and_dry_clearance_shows_only_current_fire_risk(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 1
        value["published"]["dry_level"] = 2
        value["previfoc"] = {
            "fire_level": 2,
            "dry_thunderstorm_level": 1,
            "alert_id": 7,
            "observed_at": NOW.isoformat(),
        }

        message = _transition(value)

        self.assertIsNotNone(message)
        self.assertIn("🌲 <b>Пожарная опасность сегодня</b>", message)
        self.assertNotIn("сухих гроз снят", message.casefold())
        self.assertNotIn("✅", message)
        self.assertNotIn("Previfoc", message)

    def test_dry_thunderstorm_high_can_publish_without_fire_transition(self):
        value = EmergencyRiskState.empty()
        value["published"]["fire_level"] = 1
        value["previfoc"] = {
            "fire_level": 1,
            "dry_thunderstorm_level": 3,
            "alert_id": 1,
            "observed_at": NOW.isoformat(),
        }
        message = _transition(value)
        self.assertIsNotNone(message)
        self.assertIn("Высокий риск сухих гроз", message)
        self.assertNotIn("лесных пожаров", message)

    def test_morning_digest_omits_previfoc_but_keeps_hydrology(self):
        message = build_message(
            MorningDigest(
                weather=None,
                warnings=(),
                warnings_available=False,
                fire_risk_level=2,
                dry_thunderstorm_risk_level=3,
                hydrology_state=HYDRO_PREEMERGENCIA,
            ),
            now=NOW,
        )
        self.assertNotIn("Пожарная опасность", message)
        self.assertNotIn("Сухие грозы", message)
        self.assertIn(
            "🌊 CCE: действует гидрологическое предупреждение.",
            message,
        )

    def test_morning_values_require_fresh_previfoc_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["previfoc"] = {
                "fire_level": 3,
                "dry_thunderstorm_level": 3,
                "alert_id": 1,
                "observed_at": (NOW - timedelta(hours=3)).isoformat(),
            }
            state.write(value)
            self.assertEqual(
                state.morning_values(NOW),
                (None, None, None),
            )

    def test_v1_state_migrates_dry_high_without_fake_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.json"
            path.write_text(
                '{"version":1,"previfoc":{"fire_level":2,'
                '"dry_thunderstorm_level":2,"alert_id":9,'
                '"observed_at":"2026-09-20T07:19:00+02:00"},'
                '"cce_html":null,"cce_pdf":null,'
                '"published":{"fire_level":2,"dry_high":false,'
                '"hydrology":null}}',
                encoding="utf-8",
            )
            value = EmergencyRiskState(path).read()
            self.assertEqual(value["version"], 2)
            self.assertEqual(value["published"]["dry_level"], 2)
            self.assertIsNone(_transition(value))

    def test_v1_migration_preserves_fire_hydrology_and_dry_baseline(self):
        for dry_high, old_dry, expected_dry in (
            (False, 1, 1), (False, 2, 2), (True, 3, 3),
            (False, None, None), (True, None, 3),
        ):
            with self.subTest(dry_high=dry_high, old_dry=old_dry):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "risk.json"
                    state = EmergencyRiskState(path)
                    value = state.empty()
                    value["version"] = 1
                    value["published"] = {
                        "fire_level": 2,
                        "dry_high": dry_high,
                        "hydrology": HYDRO_SITUATION_1,
                    }
                    value["cce_html"] = _observed(HYDRO_SITUATION_1)
                    if old_dry is not None:
                        value["previfoc"] = {
                            "fire_level": 2,
                            "dry_thunderstorm_level": old_dry,
                            "alert_id": 9,
                            "observed_at": NOW.isoformat(),
                        }
                    path.write_text(json.dumps(value), encoding="utf-8")
                    migrated = state.read()
                    self.assertEqual(migrated["version"], 2)
                    self.assertEqual(migrated["published"], {
                        "fire_level": 2,
                        "dry_level": expected_dry,
                        "hydrology": HYDRO_SITUATION_1,
                    })
                    self.assertIsNone(_transition(migrated))
                    if old_dry == 3:
                        migrated["previfoc"]["dry_thunderstorm_level"] = 2
                        self.assertIn(
                            "Сегодня возможны сухие грозы",
                            _transition(migrated),
                        )
                        migrated["previfoc"]["dry_thunderstorm_level"] = 1
                        self.assertIsNone(_transition(migrated))
                    elif old_dry == 2:
                        migrated["previfoc"]["dry_thunderstorm_level"] = 3
                        self.assertIn("Высокий риск сухих гроз", _transition(migrated))

    def test_corrupt_risk_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.json"
            state = EmergencyRiskState(path)
            original = state.empty()
            original["previfoc"] = {
                "fire_level": 2, "dry_thunderstorm_level": 3,
                "alert_id": 9, "observed_at": NOW.isoformat(),
            }
            cases = []
            for field in ("version", "fire_level", "dry_thunderstorm_level"):
                candidate = json.loads(json.dumps(original))
                if field == "version":
                    candidate["version"] = True
                else:
                    candidate["previfoc"][field] = True
                cases.append(candidate)
            candidate = json.loads(json.dumps(original))
            candidate["version"] = 1
            candidate["published"] = {
                "fire_level": 2, "dry_high": False, "hydrology": None,
            }
            cases.append(candidate)
            for candidate in cases:
                with self.subTest(candidate=candidate):
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaises(EmergencyRiskError):
                        state.read()


    def test_previfoc_night_change_waits_until_first_morning_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["published"]["fire_level"] = 1
            value["published"]["dry_level"] = 1
            state.write(value)

            async def probable_previfoc():
                return PrevifocRisk(1, 2, 7)

            async def cce():
                return HYDRO_NONE

            night_calls = []

            async def night_publish(message):
                night_calls.append(message)
                return 100

            night = datetime.fromisoformat("2026-09-24T00:19:00+02:00")
            result = asyncio.run(
                monitor_emergency_risks(
                    night,
                    state,
                    night_publish,
                    fetch_previfoc_fn=probable_previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )

            self.assertEqual(result, "no_update")
            self.assertEqual(night_calls, [])
            stored = state.read()
            self.assertEqual(
                stored["previfoc"]["dry_thunderstorm_level"],
                2,
            )
            self.assertEqual(stored["published"]["dry_level"], 1)

            morning_calls = []

            async def morning_publish(message):
                morning_calls.append(message)
                return 101

            morning = datetime.fromisoformat("2026-09-24T07:19:00+02:00")
            result = asyncio.run(
                monitor_emergency_risks(
                    morning,
                    state,
                    morning_publish,
                    fetch_previfoc_fn=probable_previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )

            self.assertEqual(result, "published")
            self.assertEqual(len(morning_calls), 1)
            self.assertIn(
                "⚡ <b>Сегодня возможны сухие грозы</b>",
                morning_calls[0],
            )
            self.assertIn(
                "Для зоны Гуардамара сегодня отмечена вероятность сухих гроз.",
                morning_calls[0],
            )
            self.assertEqual(state.read()["published"]["dry_level"], 2)


    def test_morning_previfoc_notice_requires_fresh_same_run_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["published"]["fire_level"] = 1
            value["published"]["dry_level"] = 1
            value["previfoc"] = {
                "fire_level": 1,
                "dry_thunderstorm_level": 2,
                "alert_id": 11,
                "observed_at": "2026-09-24T06:19:00+02:00",
            }
            state.write(value)

            async def previfoc_failure():
                raise EmergencyRiskError("temporary", code="TIMEOUT")

            async def probable_previfoc():
                return PrevifocRisk(1, 2, 12)

            async def cce():
                return HYDRO_NONE

            calls = []

            async def publish(message):
                calls.append(message)
                return 100

            result = asyncio.run(
                monitor_emergency_risks(
                    datetime.fromisoformat("2026-09-24T07:19:00+02:00"),
                    state,
                    publish,
                    fetch_previfoc_fn=previfoc_failure,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "no_update")
            self.assertEqual(calls, [])
            self.assertEqual(state.read()["published"]["dry_level"], 1)

            result = asyncio.run(
                monitor_emergency_risks(
                    datetime.fromisoformat("2026-09-24T08:19:00+02:00"),
                    state,
                    publish,
                    fetch_previfoc_fn=probable_previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("Сегодня возможны сухие грозы", calls[0])


    def test_previfoc_night_reversal_never_becomes_a_stale_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["published"]["fire_level"] = 1
            value["published"]["dry_level"] = 1
            state.write(value)

            async def probable_previfoc():
                return PrevifocRisk(1, 2, 8)

            async def clear_previfoc():
                return PrevifocRisk(1, 1, 9)

            async def cce():
                return HYDRO_NONE

            calls = []

            async def publish(message):
                calls.append(message)
                return 100

            for when, source in (
                ("2026-09-24T00:19:00+02:00", probable_previfoc),
                ("2026-09-24T03:19:00+02:00", clear_previfoc),
                ("2026-09-24T07:19:00+02:00", clear_previfoc),
            ):
                result = asyncio.run(
                    monitor_emergency_risks(
                        datetime.fromisoformat(when),
                        state,
                        publish,
                        fetch_previfoc_fn=source,
                        fetch_cce_html_fn=cce,
                        fetch_cce_pdf_fn=cce,
                    )
                )
                self.assertEqual(result, "no_update")

            self.assertEqual(calls, [])
            stored = state.read()
            self.assertEqual(
                stored["previfoc"]["dry_thunderstorm_level"],
                1,
            )
            self.assertEqual(stored["published"]["dry_level"], 1)

    def test_night_hydrology_stays_immediate_without_acknowledging_previfoc(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["published"]["fire_level"] = 1
            value["published"]["dry_level"] = 1
            state.write(value)

            async def changed_previfoc():
                return PrevifocRisk(2, 2, 10)

            async def hydrology():
                return HYDRO_SITUATION_1

            calls = []

            async def publish(message):
                calls.append(message)
                return 100

            night = datetime.fromisoformat("2026-09-24T00:19:00+02:00")
            result = asyncio.run(
                monitor_emergency_risks(
                    night,
                    state,
                    publish,
                    fetch_previfoc_fn=changed_previfoc,
                    fetch_cce_html_fn=hydrology,
                    fetch_cce_pdf_fn=hydrology,
                )
            )

            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("CCE сообщает", calls[0])
            self.assertIn("Situación 1 по риску наводнений", calls[0])
            self.assertNotIn("лесных пожаров", calls[0])
            self.assertNotIn("Сухие грозы", calls[0])

            stored = state.read()
            self.assertEqual(stored["published"]["fire_level"], 1)
            self.assertEqual(stored["published"]["dry_level"], 1)
            self.assertEqual(
                stored["published"]["hydrology"],
                HYDRO_SITUATION_1,
            )

            calls.clear()
            morning = datetime.fromisoformat("2026-09-24T07:19:00+02:00")
            result = asyncio.run(
                monitor_emergency_risks(
                    morning,
                    state,
                    publish,
                    fetch_previfoc_fn=changed_previfoc,
                    fetch_cce_html_fn=hydrology,
                    fetch_cce_pdf_fn=hydrology,
                )
            )

            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("🌲 <b>Пожарная опасность сегодня</b>", calls[0])
            self.assertIn("⚡ <b>Сегодня возможны сухие грозы</b>", calls[0])
            self.assertNotIn("гидролог", calls[0].casefold())


    def test_silent_previfoc_clearance_advances_baseline_and_allows_reappearance(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["published"]["fire_level"] = 2
            value["published"]["dry_level"] = 2
            state.write(value)

            async def cce():
                return HYDRO_NONE

            calls = []

            async def publish(message):
                calls.append(message)
                return 100

            async def clear_previfoc():
                return PrevifocRisk(1, 1, 20)

            result = asyncio.run(
                monitor_emergency_risks(
                    datetime.fromisoformat("2026-09-25T13:19:00+02:00"),
                    state,
                    publish,
                    fetch_previfoc_fn=clear_previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "no_update")
            self.assertEqual(calls, [])
            stored = state.read()
            self.assertEqual(stored["published"]["fire_level"], 1)
            self.assertEqual(stored["published"]["dry_level"], 1)

            async def active_again():
                return PrevifocRisk(2, 2, 21)

            result = asyncio.run(
                monitor_emergency_risks(
                    datetime.fromisoformat("2026-09-25T14:19:00+02:00"),
                    state,
                    publish,
                    fetch_previfoc_fn=active_again,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("Пожарная опасность сегодня", calls[0])
            self.assertIn("Сегодня возможны сухие грозы", calls[0])

    def test_cce_failures_preserve_last_verified_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")
            value = state.empty()
            value["cce_html"] = _observed(
                HYDRO_SITUATION_1, NOW - timedelta(hours=1)
            )
            value["cce_pdf"] = _observed(
                HYDRO_SITUATION_1, NOW - timedelta(hours=1)
            )
            value["published"]["hydrology"] = HYDRO_SITUATION_1
            value["published"]["fire_level"] = 1
            state.write(value)

            async def previfoc():
                return PrevifocRisk(1, 1, 5)

            async def cce_failure():
                raise EmergencyRiskError("temporary", code="TIMEOUT")

            async def publish(_message):
                raise AssertionError(
                    "source failure must not publish an all-clear"
                )

            result = asyncio.run(
                monitor_emergency_risks(
                    NOW,
                    state,
                    publish,
                    fetch_previfoc_fn=previfoc,
                    fetch_cce_html_fn=cce_failure,
                    fetch_cce_pdf_fn=cce_failure,
                )
            )
            self.assertEqual(result, "no_update")
            self.assertEqual(
                EmergencyRiskState.current_hydrology(state.read()),
                HYDRO_SITUATION_1,
            )

    def test_uncertain_delivery_is_not_automatically_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EmergencyRiskState(Path(directory) / "risk.json")

            async def previfoc():
                return PrevifocRisk(3, 1, 5)

            async def cce():
                return HYDRO_NONE

            calls = []

            async def uncertain(message):
                calls.append(message)
                raise EmergencyRiskDeliveryUncertain()

            result = asyncio.run(
                monitor_emergency_risks(
                    NOW,
                    state,
                    uncertain,
                    fetch_previfoc_fn=previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "uncertain")
            self.assertEqual(len(calls), 1)

            async def must_not_publish(_message):
                raise AssertionError(
                    "uncertain identical transition must not be resent"
                )

            result = asyncio.run(
                monitor_emergency_risks(
                    NOW + timedelta(hours=1),
                    state,
                    must_not_publish,
                    fetch_previfoc_fn=previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "no_update")

            async def downgraded_previfoc():
                return PrevifocRisk(2, 1, 6)

            delivered = []

            async def publish_downgrade(message):
                delivered.append(message)
                return 100

            result = asyncio.run(
                monitor_emergency_risks(
                    NOW + timedelta(hours=2),
                    state,
                    publish_downgrade,
                    fetch_previfoc_fn=downgraded_previfoc,
                    fetch_cce_html_fn=cce,
                    fetch_cce_pdf_fn=cce,
                )
            )
            self.assertEqual(result, "published")
            self.assertEqual(len(delivered), 1)
            self.assertIn(
                "🌲 <b>Пожарная опасность сегодня</b>",
                delivered[0],
            )
            self.assertNotIn("снижен", delivered[0])


if __name__ == "__main__":
    unittest.main()
