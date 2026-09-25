import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import unittest

from telegrambot.airport_schedule import AirportSchedule, Fare
from telegrambot.alicante_schedule import AlicanteFare, AlicanteSchedule
from telegrambot.intercity_schedule import IntercityFare, IntercitySchedule
from telegrambot.transport_notifications import (
    TransportNotificationError,
    _empty_state,
    build_message,
    collect_changes,
    load_state,
)


TZ = ZoneInfo("Europe/Madrid")


def _line(image: str, pdf: str = "a", reviewed: bool = True):
    return {
        "pdf_sha256": pdf * 64,
        "image_sha256": image * 64,
        "reviewed": reviewed,
    }


def _pinned(line1="a", line2="b", reviewed=True):
    return {
        "lines": {
            "line_1": _line(line1, "c", reviewed),
            "line_2": _line(line2, "d", reviewed),
        }
    }


def _schedule(
    service_date: date,
    *,
    to=("08:00", "10:00"),
    from_=("09:00", "11:00"),
    fare=None,
):
    return AirportSchedule(
        service_date=service_date,
        to_airport=tuple(to),
        from_airport=tuple(from_),
        guardamar_coordinates="38.087834,-0.655759",
        airport_coordinates="38.2822,-0.5582",
        fare=fare,
    )


def _alicante(
    service_date: date,
    *,
    to=("08:00", "10:00"),
    from_=("09:00", "11:00"),
    fare=None,
):
    return AlicanteSchedule(
        service_date=service_date,
        to_alicante=tuple(to),
        from_alicante=tuple(from_),
        fare=fare,
    )


def _intercity(
    service_date: date,
    *,
    to=("08:00", "10:00"),
    from_=("09:00", "11:00"),
    fare=None,
):
    return IntercitySchedule(
        service_date=service_date,
        outbound=tuple(to),
        inbound=tuple(from_),
        fare=fare,
    )


def _fare(cents=295, effective=date(2026, 1, 1), digest="a"):
    return Fare(
        cents=cents,
        effective_date=effective,
        source_url="https://www.bus-siguenza.com/wbus/tarifas/tarifa.pdf",
        etag=None,
        last_modified=None,
        pdf_sha256=digest * 64,
    )


def _baseline(day=date(2026, 9, 20)):
    state = _empty_state()
    state["urban"] = {
        "line_1": {
            "pdf_sha256": "c" * 64,
            "image_sha256": "a" * 64,
            "period": "regular",
        },
        "line_2": {
            "pdf_sha256": "d" * 64,
            "image_sha256": "b" * 64,
            "period": "regular",
        },
    }
    state["fare"] = {
        "cents": 295,
        "effective_date": "2026-01-01",
        "pdf_sha256": "a" * 64,
    }
    state["airport_next"] = {
        "service_date": day.isoformat(),
        "to_airport": ["08:00", "10:00"],
        "from_airport": ["09:00", "11:00"],
    }
    return state


def _kinds(state):
    pending = state["pending"]
    return [] if pending is None else [item["kind"] for item in pending["messages"]]


class TransportNotificationTests(unittest.TestCase):
    def test_visual_urban_change_creates_schedule_message(self):
        today = date(2026, 9, 20)
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(line1="e"),
            _schedule(today, fare=_fare()),
            _baseline(today),
            _schedule(date(2026, 9, 21)),
        )
        assert _kinds(result) == ["schedule_changes"]
        assert result["pending"]["messages"][0]["events"][0] == {
            "type": "timetable_changed",
            "route": "line_1",
        }


    def test_pdf_metadata_change_with_same_rendered_image_is_silent(self):
        today = date(2026, 9, 20)
        pinned = _pinned()
        pinned["lines"]["line_1"]["pdf_sha256"] = "f" * 64
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            pinned,
            _schedule(today, fare=_fare()),
            _baseline(today),
            _schedule(date(2026, 9, 21)),
        )
        assert result["pending"] is None


    def test_wrong_airport_baseline_date_is_silent(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["airport_next"] = {
            "service_date": "2026-09-19",
            "to_airport": ["07:00"],
            "from_airport": ["08:00"],
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
        )
        assert result["pending"] is None


    def test_airport_exact_departure_change_is_schedule_message(self):
        today = date(2026, 9, 20)
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(
                today,
                to=("08:00", "10:30"),
                from_=("09:00", "11:00"),
                fare=_fare(),
            ),
            _baseline(today),
            _schedule(date(2026, 9, 21)),
        )
        assert _kinds(result) == ["schedule_changes"]
        event = result["pending"]["messages"][0]["events"][0]
        assert event["route"] == "airport"
        assert event["added_to"] == ["10:30"]
        assert event["removed_to"] == ["10:00"]


    def test_fare_and_schedule_become_two_semantic_messages(self):
        today = date(2026, 9, 20)
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(line1="e"),
            _schedule(
                today,
                fare=_fare(320, date(2026, 10, 1), "b"),
            ),
            _baseline(today),
            _schedule(date(2026, 9, 21)),
        )
        assert _kinds(result) == ["schedule_changes", "fare_changes"]


    def test_reviewed_summer_transition_is_detected_without_new_pdf(self):
        day = date(2027, 7, 1)
        state = _baseline(day)
        result = collect_changes(
            datetime(2027, 7, 1, 5, tzinfo=TZ),
            _pinned(),
            _schedule(day, fare=_fare()),
            state,
            _schedule(date(2027, 7, 2)),
        )
        assert _kinds(result) == ["schedule_changes"]
        events = result["pending"]["messages"][0]["events"]
        assert {event["route"] for event in events} == {"line_1", "line_2"}
        assert all(event["type"] == "period_changed" for event in events)
        assert all(event["period"] == "summer" for event in events)
        assert all(event["effective_date"] == "2027-07-01" for event in events)


    def test_delayed_period_transition_keeps_true_effective_date(self):
        day = date(2027, 7, 10)
        state = _baseline(day)
        result = collect_changes(
            datetime(2027, 7, 10, 5, tzinfo=TZ),
            _pinned(),
            _schedule(day, fare=_fare()),
            state,
            _schedule(date(2027, 7, 11)),
        )
        event = result["pending"]["messages"][0]["events"][0]
        assert event["effective_date"] == "2027-07-01"
        message = build_message(
            "schedule_changes",
            [event],
            "-100123",
            {event["route"]: 501},
            day,
        )
        assert "с 1 июля" in message
        assert "с сегодняшнего дня" not in message


    def test_unreviewed_line_does_not_claim_period_transition(self):
        day = date(2027, 7, 1)
        state = _baseline(day)
        result = collect_changes(
            datetime(2027, 7, 1, 5, tzinfo=TZ),
            _pinned(reviewed=False),
            _schedule(day, fare=_fare()),
            state,
            _schedule(date(2027, 7, 2)),
        )
        assert result["pending"] is None


    def test_stale_pending_expires_before_collecting_new_day(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["pending"] = {
            "created_date": "2026-09-19",
            "messages": [{
                "kind": "schedule_changes",
                "status": "pending",
                "events": [{"type": "timetable_changed", "route": "line_1"}],
                "message_id": None,
            }],
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
        )
        assert result["pending"] is None


    def test_same_day_pending_batch_is_immutable(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["pending"] = {
            "created_date": today.isoformat(),
            "messages": [{
                "kind": "schedule_changes",
                "status": "pending",
                "events": [{"type": "timetable_changed", "route": "line_1"}],
                "message_id": None,
            }],
        }
        result = collect_changes(
            datetime(2026, 9, 20, 6, tzinfo=TZ),
            _pinned(line2="e"),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
        )
        assert result == state


    def test_corrupt_v2_fare_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            broken = _baseline()
            broken["fare"] = {"cents": "oops"}
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(TransportNotificationError):
                load_state(path)


    def test_schedule_message_links_each_route_directly_to_its_card(self):
        message = build_message(
            "schedule_changes",
            [
                {"type": "timetable_changed", "route": "line_1"},
                {
                    "type": "departures_changed",
                    "route": "airport",
                    "added_to": ["10:30"],
                    "removed_to": ["10:00"],
                    "added_from": [],
                    "removed_from": [],
                },
            ],
            "-100123",
            {"line_1": 501, "airport": 502},
            date(2026, 9, 20),
        )
        assert "https://t.me/c/123/501" in message
        assert "https://t.me/c/123/502" in message
        assert "10:30" in message
        assert "10:00" in message
        assert "К списку транспорта" not in message


    def test_fare_message_is_separate_and_links_airport_card(self):
        message = build_message(
            "fare_changes",
            [{
                "type": "fare_changed",
                "route": "airport",
                "old_cents": 295,
                "new_cents": 320,
                "effective_date": "2026-10-01",
            }],
            "-100123",
            {"airport": 502},
            date(2026, 9, 20),
        )
        assert "Изменилась стоимость проезда" in message
        assert "https://t.me/c/123/502" in message
        assert "3,20 €" in message
        assert "2,95 €" in message


    def test_missing_route_card_fails_closed(self):
        with self.assertRaises(TransportNotificationError):
            build_message(
                "schedule_changes",
                [{"type": "timetable_changed", "route": "line_1"}],
                "-100123",
                {},
                date(2026, 9, 20),
            )


    def test_pending_transport_message_id_must_match_delivery_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            state = _baseline()
            state["pending"] = {
                "created_date": "2026-09-20",
                "messages": [{
                    "kind": "schedule_changes",
                    "status": "pending",
                    "events": [{
                        "type": "timetable_changed",
                        "route": "line_1",
                    }],
                    "message_id": 999,
                }],
            }
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(TransportNotificationError):
                load_state(path)


    def test_legacy_v1_idle_state_migrates_pending_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            path.write_text(
                json.dumps({
                    "version": 1,
                    "urban": {},
                    "fare": None,
                    "airport_next": None,
                    "pending": {
                        "created_date": "2026-09-20",
                        "urban_lines": ["line_1"],
                        "airport": None,
                        "fare": None,
                    },
                    "delivery_state": "idle",
                    "last_message_id": None,
                }),
                encoding="utf-8",
            )
            state = load_state(path)
        assert state["version"] == 5
        assert _kinds(state) == ["schedule_changes"]


    def test_legacy_uncertain_delivery_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            path.write_text(
                json.dumps({
                    "version": 1,
                    "urban": {},
                    "fare": None,
                    "airport_next": None,
                    "pending": None,
                    "delivery_state": "uncertain",
                    "last_message_id": 900,
                }),
                encoding="utf-8",
            )
            with self.assertRaises(TransportNotificationError):
                load_state(path)



    def test_alicante_exact_departure_change_is_schedule_message(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["alicante_next"] = {
            "service_date": today.isoformat(),
            "to_alicante": ["08:00", "10:00"],
            "from_alicante": ["09:00", "11:00"],
            "fare": {"cents": 420, "from_price": False},
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            _alicante(
                today,
                to=("08:00", "10:30"),
                fare=AlicanteFare(420, False),
            ),
            _alicante(
                date(2026, 9, 21),
                fare=AlicanteFare(420, False),
            ),
        )
        assert _kinds(result) == ["schedule_changes"]
        event = result["pending"]["messages"][0]["events"][0]
        assert event["route"] == "alicante"
        assert event["added_to"] == ["10:30"]
        assert event["removed_to"] == ["10:00"]

    def test_alicante_different_day_without_same_date_baseline_is_silent(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["alicante_next"] = {
            "service_date": "2026-09-19",
            "to_alicante": ["07:00"],
            "from_alicante": ["08:00"],
            "fare": {"cents": 420, "from_price": False},
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            _alicante(
                today,
                to=("08:00", "10:30"),
                fare=AlicanteFare(430, False),
            ),
            _alicante(date(2026, 9, 21)),
        )
        assert result["pending"] is None

    def test_alicante_fare_change_is_separate_fare_message(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["alicante_next"] = {
            "service_date": today.isoformat(),
            "to_alicante": ["08:00", "10:00"],
            "from_alicante": ["09:00", "11:00"],
            "fare": {"cents": 420, "from_price": False},
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            _alicante(today, fare=AlicanteFare(450, True)),
            _alicante(date(2026, 9, 21)),
        )
        assert _kinds(result) == ["fare_changes"]
        event = result["pending"]["messages"][0]["events"][0]
        assert event == {
            "type": "fare_changed",
            "route": "alicante",
            "old_cents": 420,
            "new_cents": 450,
            "old_from": False,
            "new_from": True,
            "effective_date": today.isoformat(),
        }
        message = build_message(
            "fare_changes",
            [event],
            "-100123",
            {"alicante": 503},
            today,
        )
        assert "https://t.me/c/123/503" in message
        assert "от 4,50 €" in message
        assert "4,20 €" in message

    def test_alicante_same_minimum_fare_mode_change_has_clear_copy(self):
        today = date(2026, 9, 20)
        event = {
            "type": "fare_changed",
            "route": "alicante",
            "old_cents": 495,
            "new_cents": 495,
            "old_from": False,
            "new_from": True,
            "effective_date": today.isoformat(),
        }
        message = build_message(
            "fare_changes",
            [event],
            "-100123",
            {"alicante": 503},
            today,
        )
        assert "цена теперь зависит от рейса" in message
        assert "от 4,95 €" in message
        assert "вместо 4,95 €" not in message

    def test_alicante_first_comparable_baseline_is_silent(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            _alicante(today, fare=AlicanteFare(420, False)),
            _alicante(
                date(2026, 9, 21),
                to=("08:30",),
                from_=("10:30",),
                fare=AlicanteFare(430, False),
            ),
        )
        assert result["pending"] is None
        assert result["alicante_next"]["service_date"] == "2026-09-21"
        assert result["alicante_next"]["fare"]["cents"] == 430

    def test_v2_state_migrates_with_empty_alicante_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            legacy = _baseline()
            legacy["version"] = 2
            legacy.pop("alicante_next", None)
            path.write_text(json.dumps(legacy), encoding="utf-8")
            state = load_state(path)
        assert state["version"] == 5
        assert state["alicante_next"] is None



    def test_elche_exact_departure_and_fare_changes_are_collected(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["elche_next"] = {
            "service_date": today.isoformat(),
            "outbound": ["08:00", "10:00"],
            "inbound": ["09:00", "11:00"],
            "fare": {
                "cents": 360,
                "from_price": False,
                "effective_date": None,
            },
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            None,
            None,
            _intercity(
                today,
                to=("08:00", "10:30"),
                fare=IntercityFare(380),
            ),
            _intercity(
                date(2026, 9, 21),
                fare=IntercityFare(380),
            ),
        )
        assert _kinds(result) == ["schedule_changes", "fare_changes"]
        schedule_event = result["pending"]["messages"][0]["events"][0]
        assert schedule_event["route"] == "elche"
        assert schedule_event["added_to"] == ["10:30"]
        assert schedule_event["removed_to"] == ["10:00"]
        fare_event = result["pending"]["messages"][1]["events"][0]
        assert fare_event["route"] == "elche"
        assert fare_event["old_cents"] == 360
        assert fare_event["new_cents"] == 380
        assert result["elche_next"]["service_date"] == "2026-09-21"

    def test_orihuela_same_date_baseline_avoids_weekend_false_positive(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["inland_next"] = {
            "service_date": "2026-09-19",
            "outbound": ["06:20"],
            "inbound": ["06:45"],
            "fare": {
                "cents": 345,
                "from_price": False,
                "effective_date": "2026-02-01",
            },
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            None,
            None,
            None,
            None,
            _intercity(
                today,
                to=("09:30",),
                from_=("08:00",),
                fare=IntercityFare(
                    345,
                    effective_date=date(2026, 2, 1),
                ),
            ),
            _intercity(date(2026, 9, 21)),
        )
        assert result["pending"] is None

    def test_orihuela_fare_change_uses_authoritative_effective_date(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["inland_next"] = {
            "service_date": today.isoformat(),
            "outbound": ["08:00", "10:00"],
            "inbound": ["09:00", "11:00"],
            "fare": {
                "cents": 345,
                "from_price": False,
                "effective_date": "2026-02-01",
            },
        }
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            None,
            None,
            None,
            None,
            _intercity(
                today,
                fare=IntercityFare(
                    365,
                    effective_date=date(2026, 10, 1),
                ),
            ),
            _intercity(date(2026, 9, 21)),
        )
        assert _kinds(result) == ["fare_changes"]
        event = result["pending"]["messages"][0]["events"][0]
        assert event["route"] == "inland"
        assert event["effective_date"] == "2026-10-01"
        message = build_message(
            "fare_changes",
            [event],
            "-100123",
            {"inland": 504},
            today,
        )
        assert "с 1 октября" in message
        assert "3,65 €" in message
        assert "https://t.me/c/123/504" in message

    def test_new_intercity_baselines_are_silent(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            None,
            None,
            _intercity(today, fare=IntercityFare(360)),
            _intercity(
                date(2026, 9, 21),
                fare=IntercityFare(360),
            ),
            _intercity(today, fare=IntercityFare(345)),
            _intercity(
                date(2026, 9, 21),
                fare=IntercityFare(
                    345,
                    effective_date=date(2026, 2, 1),
                ),
            ),
        )
        assert result["pending"] is None
        assert result["elche_next"]["fare"]["cents"] == 360
        assert result["inland_next"]["fare"]["cents"] == 345

    def test_zenia_exact_departure_and_fare_changes_are_collected(self):
        today = date(2026, 9, 20)
        state = _baseline(today)
        state["zenia_next"] = {
            "service_date": today.isoformat(),
            "outbound": ["08:00", "10:00"],
            "inbound": ["12:00", "14:00"],
            "fare": {
                "cents": 275,
                "from_price": False,
                "effective_date": None,
            },
        }

        result = collect_changes(
            datetime(2026, 9, 20, 5, tzinfo=TZ),
            _pinned(),
            _schedule(today, fare=_fare()),
            state,
            _schedule(date(2026, 9, 21)),
            None,
            None,
            None,
            None,
            None,
            None,
            _intercity(
                today,
                to=("08:00", "10:30"),
                from_=("12:00", "14:00"),
                fare=IntercityFare(295),
            ),
            _intercity(
                date(2026, 9, 21),
                fare=IntercityFare(295),
            ),
        )

        assert _kinds(result) == ["schedule_changes", "fare_changes"]
        schedule_event = result["pending"]["messages"][0]["events"][0]
        assert schedule_event["route"] == "zenia"
        assert schedule_event["added_to"] == ["10:30"]
        assert schedule_event["removed_to"] == ["10:00"]
        fare_event = result["pending"]["messages"][1]["events"][0]
        assert fare_event["route"] == "zenia"
        assert fare_event["old_cents"] == 275
        assert fare_event["new_cents"] == 295
        assert result["zenia_next"]["service_date"] == "2026-09-21"

        message = build_message(
            "schedule_changes",
            [schedule_event],
            "-100123",
            {"zenia": 505},
            today,
        )
        assert "Zenia Boulevard" in message
        assert "https://t.me/c/123/505" in message

    def test_v4_state_migrates_with_empty_zenia_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            legacy = _baseline()
            legacy["version"] = 4
            legacy.pop("zenia_next", None)
            path.write_text(json.dumps(legacy), encoding="utf-8")
            state = load_state(path)
        assert state["version"] == 5
        assert state["zenia_next"] is None


    def test_v3_state_migrates_with_empty_new_route_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transport.json"
            legacy = _baseline()
            legacy["version"] = 3
            legacy["alicante_next"] = None
            legacy.pop("elche_next", None)
            legacy.pop("inland_next", None)
            path.write_text(json.dumps(legacy), encoding="utf-8")
            state = load_state(path)
        assert state["version"] == 5
        assert state["elche_next"] is None
        assert state["inland_next"] is None


class TransportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def _pending_state(self):
        state = _baseline(date(2026, 9, 20))
        state["pending"] = {
            "created_date": "2026-09-20",
            "messages": [{
                "kind": "schedule_changes",
                "status": "pending",
                "events": [{
                    "type": "timetable_changed",
                    "route": "line_1",
                }],
                "message_id": None,
            }],
        }
        return state

    async def _run_failed_publish(self, error):
        from telegrambot.transport_notifications import publish

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "transport.json"
            state_path.write_text(
                json.dumps(self._pending_state()), encoding="utf-8"
            )
            with (
                patch.dict(
                    "os.environ",
                    {
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "-100123",
                        "TRANSPORT_NOTIFICATION_STATE_PATH": str(state_path),
                        "PINNED_GUIDE_STATE_PATH": str(Path(directory) / "pinned.json"),
                    },
                    clear=False,
                ),
                patch("telegrambot.transport_notifications.datetime") as clock,
                patch(
                    "telegrambot.transport_notifications.PinnedGuideState.read_payload",
                    return_value={
                        "messages": {"line_1": 501},
                        "uncertain_messages": [],
                    },
                ),
                patch(
                    "telegrambot.transport_notifications.send_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                clock.now.return_value = datetime(2026, 9, 20, 8, 42, tzinfo=TZ)
                with self.assertRaises(type(error)):
                    await publish()
            return load_state(state_path)

    async def test_explicit_http_400_returns_transport_message_to_pending(self):
        from telegrambot.telegram import TelegramError

        state = await self._run_failed_publish(TelegramError(
            "bad request", retryable=False, status=400, code="HTTP-400"
        ))
        self.assertEqual(state["pending"]["messages"][0]["status"], "pending")

    async def test_redirect_keeps_transport_message_uncertain(self):
        from telegrambot.telegram import TelegramError

        state = await self._run_failed_publish(TelegramError(
            "redirect", retryable=False, code="REDIRECT"
        ))
        self.assertEqual(state["pending"]["messages"][0]["status"], "uncertain")
