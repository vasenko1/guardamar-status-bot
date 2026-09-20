import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import unittest

from telegrambot.airport_schedule import AirportSchedule, Fare
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
        assert state["version"] == 2
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
    