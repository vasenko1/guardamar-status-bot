from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.airport_schedule import AirportSchedule, Fare
from telegrambot.branding import FOOTER
from telegrambot.transport_notifications import (
    _airport_baseline,
    _empty_state,
    build_message,
    collect_changes,
)


TZ = ZoneInfo("Europe/Madrid")


def _schedule(
    service_date: date,
    *,
    to_airport=("08:00", "10:00"),
    from_airport=("09:00", "11:00"),
    fare=None,
):
    return AirportSchedule(
        service_date=service_date,
        to_airport=tuple(to_airport),
        from_airport=tuple(from_airport),
        guardamar_coordinates="38.087834,-0.655759",
        airport_coordinates="38.282222,-0.558056",
        fare=fare,
    )


def _pinned(image_1="1" * 64, image_2="2" * 64, pdf_1="a" * 64, pdf_2="b" * 64):
    return {
        "lines": {
            "line_1": {"pdf_sha256": pdf_1, "image_sha256": image_1},
            "line_2": {"pdf_sha256": pdf_2, "image_sha256": image_2},
        }
    }


def test_first_collection_only_establishes_baselines():
    today = date(2026, 9, 15)
    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(),
        _schedule(today),
        _empty_state(),
        _schedule(date(2026, 9, 16)),
    )

    assert result["pending"] is None
    assert result["urban"]["line_1"]["image_sha256"] == "1" * 64
    assert result["airport_next"]["service_date"] == "2026-09-16"


def test_visual_urban_change_creates_generic_line_event():
    today = date(2026, 9, 15)
    state = _empty_state()
    state["urban"] = {
        "line_1": {"pdf_sha256": "a" * 64, "image_sha256": "1" * 64},
        "line_2": {"pdf_sha256": "b" * 64, "image_sha256": "2" * 64},
    }

    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(image_1="3" * 64, pdf_1="c" * 64),
        _schedule(today),
        state,
        _schedule(date(2026, 9, 16)),
    )

    assert result["pending"]["urban_lines"] == ["line_1"]


def test_pdf_metadata_change_without_visual_change_does_not_notify():
    today = date(2026, 9, 15)
    state = _empty_state()
    state["urban"] = {
        "line_1": {"pdf_sha256": "a" * 64, "image_sha256": "1" * 64},
        "line_2": {"pdf_sha256": "b" * 64, "image_sha256": "2" * 64},
    }

    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(image_1="1" * 64, pdf_1="c" * 64),
        _schedule(today),
        state,
        _schedule(date(2026, 9, 16)),
    )

    assert result["pending"] is None


def test_airport_diff_compares_same_service_date_not_yesterday():
    today = date(2026, 9, 15)
    state = _empty_state()
    state["airport_next"] = _airport_baseline(
        _schedule(today, to_airport=("08:00", "10:00"), from_airport=("09:00", "11:00"))
    )

    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(),
        _schedule(today, to_airport=("08:00", "10:30"), from_airport=("09:00", "11:00")),
        state,
        _schedule(date(2026, 9, 16)),
    )

    airport = result["pending"]["airport"]
    assert airport["added_to"] == ["10:30"]
    assert airport["removed_to"] == ["10:00"]


def test_wrong_baseline_date_never_creates_airport_change():
    today = date(2026, 9, 15)
    state = _empty_state()
    state["airport_next"] = _airport_baseline(
        _schedule(date(2026, 9, 14), to_airport=("07:00",))
    )

    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(),
        _schedule(today),
        state,
        _schedule(date(2026, 9, 16)),
    )

    assert result["pending"] is None


def test_base_fare_change_is_reported_with_effective_date():
    today = date(2026, 9, 15)
    state = _empty_state()
    state["fare"] = {
        "cents": 295,
        "effective_date": "2026-01-01",
        "pdf_sha256": "a" * 64,
    }
    new_fare = Fare(
        cents=320,
        effective_date=date(2026, 10, 1),
        source_url="https://www.bus-siguenza.com/wbus/tarifas/tarifa.pdf",
        etag=None,
        last_modified=None,
        pdf_sha256="b" * 64,
    )

    result = collect_changes(
        datetime(2026, 9, 15, 5, tzinfo=TZ),
        _pinned(),
        _schedule(today, fare=new_fare),
        state,
        _schedule(date(2026, 9, 16)),
    )

    assert result["pending"]["fare"] == {
        "old_cents": 295,
        "new_cents": 320,
        "effective_date": "2026-10-01",
    }


def test_message_keeps_editorial_style_and_existing_footer():
    message = build_message(
        {
            "created_date": "2026-09-15",
            "urban_lines": ["line_1"],
            "airport": None,
            "fare": None,
        },
        "https://t.me/c/123/456",
        date(2026, 9, 15),
    )

    assert message.startswith("🚌 <b>Транспорт · изменения</b>")
    assert "<b>автобуса №1</b>" in message
    assert "Puerto Deportivo" not in message
    assert "↔" not in message
    assert "⚠️" not in message
    assert "❗" not in message
    assert message.count(FOOTER) == 1


def test_future_base_fare_message_uses_only_standard_ticket():
    message = build_message(
        {
            "created_date": "2026-09-15",
            "urban_lines": [],
            "airport": None,
            "fare": {
                "old_cents": 295,
                "new_cents": 320,
                "effective_date": "2026-10-01",
            },
        },
        "https://t.me/c/123/456",
        date(2026, 9, 15),
    )

    assert "С <b>1 октября</b> обычный билет" in message
    assert "<b>3,20 €</b> вместо 2,95 €." in message
    assert "абонемент" not in message.casefold()
    assert "карт" not in message.casefold()
