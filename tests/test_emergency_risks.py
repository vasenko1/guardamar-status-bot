from datetime import datetime, timedelta
from pathlib import Path

import pytest

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


def test_parse_previfoc_keeps_fire_and_dry_thunderstorms_independent():
    risk = parse_previfoc(_previfoc_payload(fire=2, dry=3))
    assert risk == PrevifocRisk(
        fire_level=2,
        dry_thunderstorm_level=3,
        alert_id=129166,
    )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"features":[]}',
        b'{"features":[{"attributes":{"ZonaID":7,"RiesgoId":1,"TormentaID":1,"Dia":1,"AlertaDiaID":1}}]}',
        b'{"features":[{"attributes":{"ZonaID":6,"RiesgoId":4,"TormentaID":1,"Dia":1,"AlertaDiaID":1}}]}',
        b'{"features":[{"attributes":{"ZonaID":6,"RiesgoId":1,"TormentaID":1,"Dia":2,"AlertaDiaID":1}}]}',
    ],
)
def test_parse_previfoc_fails_closed_on_wrong_contract(payload):
    with pytest.raises(EmergencyRiskError):
        parse_previfoc(payload)


def test_cce_html_exact_empty_marker_is_clear():
    payload = b"""
    <html><body><h1>Emergencias</h1>
    <div>SIN EMERGENCIAS VIGENTES</div></body></html>
    """
    assert parse_cce_emergencies_html(payload) == HYDRO_NONE


def test_cce_html_recognizes_segura_situation():
    payload = """
    <html><body><h1>Emergencias vigentes</h1>
    <div>Plan especial frente al riesgo de inundaciones</div>
    <div>Cuenca del Segura</div>
    <div>SITUACIÓN 1</div>
    </body></html>
    """.encode()
    assert parse_cce_emergencies_html(payload) == HYDRO_SITUATION_1


def test_cce_bulletin_recognizes_segura_hydrological_preemergency():
    text = """
    FECHA 20/09/2026
    HORA 07:00
    PLANES DE EMERGENCIA ACTIVADOS
    PREEMERGENCIA HIDROLÓGICA
    CUENCA DEL SEGURA
    """
    assert parse_cce_text(text, bulletin=True) == HYDRO_PREEMERGENCIA


def test_cce_bulletin_without_segura_hydrology_is_negative_observation():
    text = """
    FECHA 20/09/2026
    HORA 07:00
    PLANES DE EMERGENCIA ACTIVADOS
    Sin planes hidrológicos activos para la cuenca del Júcar.
    """
    assert parse_cce_text(text, bulletin=True) == HYDRO_NONE


def test_hydrology_clear_requires_both_cce_surfaces():
    value = EmergencyRiskState.empty()
    value["cce_html"] = _observed(HYDRO_NONE)
    assert EmergencyRiskState.current_hydrology(value) is None

    value["cce_pdf"] = _observed(HYDRO_NONE)
    assert EmergencyRiskState.current_hydrology(value) == HYDRO_NONE


def test_active_hydrology_wins_over_other_negative_observation():
    value = EmergencyRiskState.empty()
    value["cce_html"] = _observed(HYDRO_NONE)
    value["cce_pdf"] = _observed(HYDRO_SITUATION_1)
    assert EmergencyRiskState.current_hydrology(value) == HYDRO_SITUATION_1


def test_fire_level_two_is_morning_only_but_extreme_is_standalone():
    value = EmergencyRiskState.empty()
    value["previfoc"] = {
        "fire_level": 2,
        "dry_thunderstorm_level": 1,
        "alert_id": 1,
        "observed_at": NOW.isoformat(),
    }
    assert _transition(value) is None

    value["previfoc"]["fire_level"] = 3
    transition = _transition(value)
    assert transition is not None
    assert "экстремальный" in transition[0]


def test_extreme_fire_downgrade_is_published_after_acknowledgement():
    value = EmergencyRiskState.empty()
    value["previfoc"] = {
        "fire_level": 3,
        "dry_thunderstorm_level": 1,
        "alert_id": 1,
        "observed_at": NOW.isoformat(),
    }
    _acknowledge(value)
    assert value["published"]["fire_extreme"] is True

    value["previfoc"]["fire_level"] = 2
    message, _ = _transition(value)
    assert "Экстремальная пожарная опасность снята" in message
    assert "сохраняется <b>высокий</b>" in message


def test_dry_thunderstorm_high_can_publish_without_extreme_fire():
    value = EmergencyRiskState.empty()
    value["previfoc"] = {
        "fire_level": 1,
        "dry_thunderstorm_level": 3,
        "alert_id": 1,
        "observed_at": NOW.isoformat(),
    }
    message, _ = _transition(value)
    assert "высокий риск сухих гроз" in message
    assert "экстремальный" not in message


def test_morning_digest_renders_only_compact_material_risk_lines():
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
    assert "🔥 Пожарная опасность: <b>высокая</b>." in message
    assert "⚡ Сухие грозы: <b>высокий риск</b>." in message
    assert "🌊 CCE: действует гидрологическое предупреждение." in message
    assert "низкий/средний" not in message


def test_morning_values_require_fresh_previfoc_observation(tmp_path):
    state = EmergencyRiskState(tmp_path / "risk.json")
    value = state.empty()
    value["previfoc"] = {
        "fire_level": 3,
        "dry_thunderstorm_level": 3,
        "alert_id": 1,
        "observed_at": (NOW - timedelta(hours=3)).isoformat(),
    }
    state.write(value)
    assert state.morning_values(NOW) == (None, None, None)


def test_monitor_preserves_active_pdf_when_html_clears_and_pdf_fails(tmp_path):
    state = EmergencyRiskState(tmp_path / "risk.json")
    value = state.empty()
    value["cce_html"] = _observed(HYDRO_SITUATION_1, NOW - timedelta(hours=1))
    value["cce_pdf"] = _observed(HYDRO_SITUATION_1, NOW - timedelta(hours=1))
    value["published"]["hydrology"] = HYDRO_SITUATION_1
    state.write(value)

    async def previfoc():
        return PrevifocRisk(1, 1, 5)

    async def html_clear():
        return HYDRO_NONE

    async def pdf_failure():
        raise EmergencyRiskError("temporary", code="TIMEOUT")

    async def publish(_message):
        raise AssertionError("no false clearance should be published")

    result = __import__("asyncio").run(
        monitor_emergency_risks(
            NOW,
            state,
            publish,
            fetch_previfoc_fn=previfoc,
            fetch_cce_html_fn=html_clear,
            fetch_cce_pdf_fn=pdf_failure,
        )
    )
    assert result == "no_update"
    assert EmergencyRiskState.current_hydrology(state.read()) == HYDRO_SITUATION_1


def test_uncertain_delivery_is_not_automatically_duplicated(tmp_path):
    state = EmergencyRiskState(tmp_path / "risk.json")

    async def previfoc():
        return PrevifocRisk(3, 1, 5)

    async def cce():
        return HYDRO_NONE

    calls = []

    async def uncertain(message):
        calls.append(message)
        raise EmergencyRiskDeliveryUncertain()

    import asyncio

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
    assert result == "uncertain"
    assert len(calls) == 1

    async def must_not_publish(_message):
        raise AssertionError("uncertain identical transition must not be resent")

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
    assert result == "uncertain"
