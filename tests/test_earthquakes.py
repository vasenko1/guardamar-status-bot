import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.earthquakes import (
    Earthquake,
    EarthquakeDeliveryUncertain,
    EarthquakeError,
    EarthquakeState,
    MAX_STATE_EVENTS,
    build_earthquake_message,
    build_earthquake_series_message,
    distance_and_bearing,
    monitor_earthquakes,
    parse_earthquakes,
    prune_state,
    qualifies,
)

MADRID = ZoneInfo("Europe/Madrid")


def _event(
    event_id="es2022soxzr",
    occurred_at=None,
    magnitude=2.8,
    latitude=38.0625,
    longitude=-0.6789,
):
    return Earthquake(
        event_id=event_id,
        occurred_at=occurred_at
        or datetime(2026, 8, 18, 12, 32, tzinfo=timezone.utc),
        magnitude=magnitude,
        latitude=latitude,
        longitude=longitude,
        location="SW GUARDAMAR DEL SEGURA.A",
    )


def _feed(*events):
    items = []
    for event in events:
        occurred = event.occurred_at.astimezone(timezone.utc)
        items.append(f"""
        <item>
          <title>-Info.terremoto: {occurred:%d/%m/%Y %-H:%M:%S}</title>
          <guid>http://www.ign.es/web/ign/portal/ultimos-terremotos?evid={event.event_id}</guid>
          <description>Se ha producido un terremoto de magnitud
            {event.magnitude:.1f} en {event.location} en la fecha
            {occurred:%d/%m/%Y} {occurred:%-H:%M:%S} en la siguiente
            localización: {event.latitude:.4f},{event.longitude:.4f}</description>
          <geo:lat>{event.latitude:.4f}</geo:lat>
          <geo:long>{event.longitude:.4f}</geo:long>
        </item>
        """)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" '
        'version="2.0"><channel>'
        + "".join(items)
        + "</channel></rss>"
    ).encode()


class EarthquakeFeedTests(unittest.TestCase):
    def test_parses_official_georss_fields_as_utc(self):
        event = parse_earthquakes(_feed(_event()))[0]

        self.assertEqual(event.event_id, "es2022soxzr")
        self.assertEqual(event.magnitude, 2.8)
        self.assertEqual(event.occurred_at.tzinfo, timezone.utc)
        self.assertEqual(event.latitude, 38.0625)
        self.assertEqual(event.longitude, -0.6789)

    def test_rejects_feed_when_every_item_is_invalid(self):
        payload = _feed(_event()).replace(
            b"<description>", b"<description>invalid "
        )
        with self.assertRaises(EarthquakeError):
            parse_earthquakes(payload)

    def test_conflicting_duplicate_is_not_accepted(self):
        first = _event()
        second = _event(magnitude=3.0)
        with self.assertRaises(EarthquakeError):
            parse_earthquakes(_feed(first, second))

    def test_rejects_document_type_declarations(self):
        payload = _feed(_event()).replace(
            b"<rss ", b'<!DOCTYPE rss SYSTEM "untrusted"><rss ', 1
        )
        with self.assertRaises(EarthquakeError):
            parse_earthquakes(payload)


class EarthquakePolicyTests(unittest.TestCase):
    def test_known_guardamar_example_is_about_four_kilometres_southwest(self):
        distance, bearing = distance_and_bearing(_event())

        self.assertAlmostEqual(distance, 3.65, places=1)
        self.assertGreater(bearing, 202.5)
        self.assertLess(bearing, 247.5)

    def test_requires_magnitude_2_7_and_distance_at_most_10_km(self):
        self.assertTrue(qualifies(_event(magnitude=2.7)))
        self.assertFalse(qualifies(_event(magnitude=2.69)))
        self.assertFalse(qualifies(_event(latitude=38.20, longitude=-0.6553)))

    def test_message_uses_one_fact_line_map_and_blank_line_before_footer(self):
        message = build_earthquake_message(_event())

        self.assertIn("📈 <b>Землетрясение рядом</b>", message)
        self.assertIn(
            "🕒 14:32 - зарегистрировано землетрясение "
            "магнитудой <b>2,8</b>",
            message,
        )
        self.assertIn(
            'href="https://maps.google.com/?q=38.0625,-0.6789"',
            message,
        )
        self.assertIn(
            "Эпицентр: примерно в 4 км к юго-западу от Гуардамара",
            message,
        )
        self.assertTrue(message.endswith("\n\n" + FOOTER))
        self.assertNotIn("Информация IGN", message)
        self.assertNotIn("предваритель", message.casefold())

    def test_series_is_one_bounded_message_with_map_links(self):
        events = tuple(
            _event(
                event_id=f"esseries{index}",
                occurred_at=datetime(
                    2026, 8, 18, 12, 30 + index, tzinfo=timezone.utc
                ),
                magnitude=2.7 + index / 10,
            )
            for index in range(6)
        )

        message = build_earthquake_series_message(events)

        self.assertIn("📈 <b>Несколько толчков рядом</b>", message)
        self.assertIn("IGN зарегистрировал 6 землетрясений рядом", message)
        self.assertIn("Ещё событий ранее: 1", message)
        self.assertEqual(message.count("https://maps.google.com/?q="), 5)
        self.assertTrue(message.endswith("\n\n" + FOOTER))

    def test_series_shows_dates_when_it_crosses_local_midnight(self):
        before = _event(
            event_id="esbefore",
            occurred_at=datetime(2026, 8, 18, 21, 50, tzinfo=timezone.utc),
        )
        after = _event(
            event_id="esafter",
            occurred_at=datetime(2026, 8, 18, 22, 20, tzinfo=timezone.utc),
        )

        message = build_earthquake_series_message((before, after))

        self.assertIn("18.08, 23:50", message)
        self.assertIn("19.08, 00:20", message)


class EarthquakeStateTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _publisher(messages, message_id=101):
        async def publish(message, existing_id):
            messages.append((message, existing_id))
            return existing_id or message_id

        return publish

    async def test_first_run_seeds_silently_then_new_event_is_sent_once(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        old = _event(
            event_id="esold",
            occurred_at=now.astimezone(timezone.utc) - timedelta(hours=1),
        )
        new = _event(
            event_id="esnew",
            occurred_at=now.astimezone(timezone.utc) - timedelta(minutes=20),
        )
        messages = []
        publisher = self._publisher(messages)
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            first = await monitor_earthquakes(
                now, state, AsyncMock(return_value=(old,)), publisher
            )
            second = await monitor_earthquakes(
                now, state, AsyncMock(return_value=(old, new)), publisher
            )
            third = await monitor_earthquakes(
                now, state, AsyncMock(return_value=(old, new)), publisher
            )

        self.assertEqual((first, second, third), (0, 1, 0))
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0][1])

    async def test_first_run_record_can_alert_after_fresh_revision(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        initial = _event(event_id="esseeded", magnitude=2.6)
        revised = _event(event_id="esseeded", magnitude=2.8)
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            await monitor_earthquakes(
                now,
                state,
                AsyncMock(return_value=(initial,)),
                self._publisher(messages),
            )
            delivered = await monitor_earthquakes(
                now + timedelta(minutes=30),
                state,
                AsyncMock(return_value=(revised,)),
                self._publisher(messages),
            )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(messages), 1)

    async def test_old_event_closes_but_fresh_low_magnitude_can_be_revised(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            value = state.empty()
            value["initialized"] = True
            state.write(value)
            result = await monitor_earthquakes(
                now,
                state,
                AsyncMock(return_value=(
                    _event(
                        event_id="esold",
                        occurred_at=now.astimezone(timezone.utc)
                        - timedelta(hours=7),
                    ),
                    _event(event_id="esrevised", magnitude=2.6),
                )),
                self._publisher(messages),
            )
            revised = await monitor_earthquakes(
                now + timedelta(hours=1),
                state,
                AsyncMock(return_value=(
                    _event(event_id="esrevised", magnitude=2.8),
                )),
                self._publisher(messages),
            )
            stored = {item["id"]: item for item in state.read()["events"]}

        self.assertEqual((result, revised), (0, 1))
        self.assertEqual(stored["esold"]["status"], "closed")
        self.assertEqual(stored["esrevised"]["status"], "alerted")
        self.assertEqual(len(messages), 1)

    async def test_four_events_are_combined_without_loss(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        events = tuple(
            _event(
                event_id=f"esburst{index}",
                occurred_at=now.astimezone(timezone.utc)
                - timedelta(minutes=10 - index),
            )
            for index in range(4)
        )
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            value = state.empty()
            value["initialized"] = True
            state.write(value)

            delivered = await monitor_earthquakes(
                now,
                state,
                AsyncMock(return_value=events),
                self._publisher(messages),
            )
            stored = state.read()

        self.assertEqual(delivered, 4)
        self.assertEqual(len(messages), 1)
        self.assertIn("4 землетрясения", messages[0][0])
        self.assertEqual(
            {item["status"] for item in stored["events"]}, {"alerted"}
        )

    async def test_later_tremor_edits_active_series(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        first = _event(
            event_id="esfirst",
            occurred_at=now.astimezone(timezone.utc) - timedelta(minutes=20),
        )
        second = _event(
            event_id="essecond",
            occurred_at=now.astimezone(timezone.utc) + timedelta(minutes=20),
        )
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            value = state.empty()
            value["initialized"] = True
            state.write(value)
            await monitor_earthquakes(
                now, state, AsyncMock(return_value=(first,)),
                self._publisher(messages),
            )
            await monitor_earthquakes(
                now + timedelta(hours=1),
                state,
                AsyncMock(return_value=(first, second)),
                self._publisher(messages),
            )

        self.assertEqual(len(messages), 2)
        self.assertIsNone(messages[0][1])
        self.assertEqual(messages[1][1], 101)
        self.assertIn("Несколько толчков рядом", messages[1][0])

    async def test_failed_send_leaves_event_eligible_for_next_run(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        event = _event(
            event_id="esretry",
            occurred_at=now.astimezone(timezone.utc) - timedelta(minutes=20),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            value = state.empty()
            value["initialized"] = True
            state.write(value)
            with self.assertRaises(RuntimeError):
                await monitor_earthquakes(
                    now,
                    state,
                    AsyncMock(return_value=(event,)),
                    AsyncMock(side_effect=RuntimeError("telegram failed")),
                )

            self.assertEqual(state.read()["events"], [])

    async def test_uncertain_send_is_remembered_without_automatic_duplicate(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=MADRID)
        event = _event(
            event_id="esuncertain",
            occurred_at=now.astimezone(timezone.utc) - timedelta(minutes=20),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            value = state.empty()
            value["initialized"] = True
            state.write(value)
            with self.assertRaises(EarthquakeDeliveryUncertain):
                await monitor_earthquakes(
                    now,
                    state,
                    AsyncMock(return_value=(event,)),
                    AsyncMock(side_effect=EarthquakeDeliveryUncertain()),
                )

            stored = state.read()

        self.assertEqual(stored["events"][0]["status"], "uncertain")

    def test_concurrent_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state = EarthquakeState(Path(directory) / "earthquakes.json")
            with state.exclusive_run():
                with self.assertRaises(EarthquakeError):
                    with state.exclusive_run():
                        pass

    def test_prune_removes_old_entries_and_enforces_bound(self):
        now = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
        events = [
            {
                "id": f"es{index}",
                "occurred_at": (now - timedelta(minutes=index)).isoformat(),
                "magnitude": 2.0,
                "latitude": 38.0,
                "longitude": -0.6,
                "status": "closed",
            }
            for index in range(MAX_STATE_EVENTS + 4)
        ]
        events.append({
            "id": "esexpired",
            "occurred_at": (now - timedelta(days=15)).isoformat(),
            "magnitude": 2.0,
            "latitude": 38.0,
            "longitude": -0.6,
            "status": "closed",
        })
        value = {
            "version": 2,
            "initialized": True,
            "events": events,
            "series": None,
        }

        self.assertTrue(prune_state(value, now))
        self.assertEqual(len(value["events"]), MAX_STATE_EVENTS)
        self.assertNotIn("esexpired", {item["id"] for item in value["events"]})

    async def test_corrupt_state_is_quarantined_and_reseeded_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "earthquakes.json"
            path.write_text("{}", encoding="utf-8")
            state = EarthquakeState(path)

            delivered = await monitor_earthquakes(
                datetime(2026, 8, 18, 15, 0, tzinfo=MADRID),
                state,
                AsyncMock(return_value=(_event(),)),
                AsyncMock(),
            )

            self.assertEqual(delivered, 0)
            self.assertTrue(path.with_name("earthquakes.json.invalid").exists())
            self.assertTrue(state.read()["initialized"])
