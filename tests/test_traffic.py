import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.traffic import (
    TrafficError,
    TrafficIncident,
    TrafficLocation,
    TrafficState,
    build_alert_message,
    fallback_body,
    location_label,
    monitor_traffic,
    parse_incidents,
    traffic_facts,
)


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)


def incident(
    provider_id="TTR1",
    category="roadClosed",
    validity="present",
    probability="probable",
    starts_at=None,
    ends_at=None,
    from_place="Calle Miguel Hernández",
    to_place="Avenida del País Valenciano",
    descriptions=("Cerrado",),
):
    return TrafficIncident(
        provider_id=provider_id,
        category=category,
        validity=validity,
        probability=probability,
        starts_at=starts_at or datetime(2026, 9, 23, 16, 45, tzinfo=MADRID),
        ends_at=ends_at,
        from_place=from_place,
        to_place=to_place,
        descriptions_es=tuple(descriptions),
        coordinates=(
            (-0.6539507, 38.0837390),
            (-0.6544255, 38.0838021),
            (-0.6545838, 38.0838235),
        ),
    )


def location(
    municipality="Guardamar del Segura",
    subdivision=None,
    street="Avenida del Mediterráneo",
):
    return TrafficLocation(
        municipality=municipality,
        subdivision=subdivision,
        street=street,
        longitude=-0.6544255,
        latitude=38.0838021,
    )


def payload(*items):
    return json.dumps({"incidents": list(items)}).encode()


def raw_incident(
    *,
    identifier="TTR1",
    category="roadClosed",
    validity="present",
    probability="probable",
    start="2026-09-23T14:45:30Z",
    end=None,
    from_place="Calle Miguel Hernández",
    to_place="Avenida del País Valenciano",
    descriptions=("Cerrado",),
):
    return {
        "type": "Feature",
        "properties": {
            "id": identifier,
            "iconCategory": category,
            "startTime": start,
            "endTime": end,
            "from": from_place,
            "to": to_place,
            "timeValidity": validity,
            "probabilityOfOccurrence": probability,
            "events": [{"description": text} for text in descriptions],
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-0.6539507, 38.0837390],
                [-0.6544255, 38.0838021],
                [-0.6545838, 38.0838235],
            ],
        },
    }


class TrafficParsingTests(unittest.TestCase):
    def test_parses_only_road_and_lane_closures(self):
        rows = parse_incidents(payload(
            raw_incident(identifier="road", category="roadClosed"),
            raw_incident(identifier="lane", category="laneClosed"),
            raw_incident(identifier="works", category="roadWorks"),
            raw_incident(identifier="jam", category="jam"),
        ))

        self.assertEqual(
            [(row.provider_id, row.category) for row in rows],
            [("lane", "laneClosed"), ("road", "roadClosed")],
        )

    def test_null_like_optional_text_is_never_rendered(self):
        row = parse_incidents(payload(raw_incident(
            from_place="Null",
            to_place=None,
            descriptions=("null", "Cerrado"),
        )))[0]
        place = location(subdivision="null", street="Undefined")

        self.assertIsNone(row.from_place)
        self.assertIsNone(row.to_place)
        self.assertEqual(row.descriptions_es, ("Cerrado",))
        self.assertEqual(location_label(row, place), "Участок дороги в Гуардамаре")
        message = build_alert_message(row, place, "В Гуардамаре перекрыт проезд.")
        self.assertNotIn("null", message.casefold())
        self.assertNotIn("undefined", message.casefold())

    def test_malformed_relevant_closure_fails_whole_snapshot(self):
        item = raw_incident()
        item["properties"]["timeValidity"] = None

        with self.assertRaises(TrafficError):
            parse_incidents(payload(item))

    def test_null_end_time_is_missing_not_text(self):
        row = parse_incidents(payload(raw_incident(end="null")))[0]

        self.assertIsNone(row.ends_at)

    def test_invalid_geometry_fails_closed(self):
        item = raw_incident()
        item["geometry"] = {"type": "LineString", "coordinates": [[999, 38.0]]}

        with self.assertRaises(TrafficError):
            parse_incidents(payload(item))


class TrafficFormattingTests(unittest.TestCase):
    def test_reviewed_location_copy_uses_street_and_boundaries(self):
        label = location_label(incident(), location())

        self.assertEqual(
            label,
            "Avenida del Mediterráneo — между Calle Miguel Hernández "
            "и Avenida del País Valenciano",
        )

    def test_urbanization_is_added_and_prefix_removed(self):
        label = location_label(
            incident(from_place=None, to_place=None),
            location(
                subdivision="Urbanización El Raso",
                street="Calle Manuel Fernández",
            ),
        )

        self.assertEqual(label, "El Raso — Calle Manuel Fernández")

    def test_unknown_end_is_silent(self):
        body = fallback_body(incident(ends_at=None), location(), "new_present", NOW)

        self.assertNotIn("не указ", body.casefold())
        self.assertNotIn("неизвест", body.casefold())
        self.assertNotIn("оконч", body.casefold())

    def test_known_future_end_is_described_as_expected(self):
        body = fallback_body(
            incident(ends_at=NOW + timedelta(hours=3)),
            location(),
            "new_present",
            NOW,
        )

        self.assertIn("Ожидается", body)
        self.assertIn("19:30", body)

    def test_past_end_never_overrides_present(self):
        body = fallback_body(
            incident(ends_at=NOW - timedelta(minutes=30)),
            location(),
            "ongoing",
            NOW,
        )

        self.assertNotIn("15:59", body)
        self.assertNotIn("Ожидается", body)

    def test_facts_omit_unknown_values_instead_of_serializing_null(self):
        item = incident(
            ends_at=None,
            from_place=None,
            to_place=None,
            descriptions=(),
        )
        facts = traffic_facts(item, location(subdivision=None), "new_present", NOW)

        self.assertNotIn("end_local", facts)
        self.assertNotIn("from", facts)
        self.assertNotIn("to", facts)
        self.assertNotIn("urbanization", facts)
        self.assertNotIn("details_es", facts)
        self.assertNotIn("null", json.dumps(facts, ensure_ascii=False).casefold())

    def test_message_has_link_and_shared_footer(self):
        message = build_alert_message(
            incident(),
            location(),
            "В Гуардамаре перекрыт проезд по Avenida del Mediterráneo.",
        )

        self.assertIn("🚧 <b>Перекрытие участка дороги</b>", message)
        self.assertIn("https://www.google.com/maps/search/?", message)
        self.assertIn("Avenida del Mediterráneo", message)
        self.assertTrue(message.endswith("\n\n" + FOOTER))


class TrafficLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        state,
        now,
        rows,
        sent,
        *,
        resolved=None,
        composer_text=None,
    ):
        async def fetcher(_key):
            return tuple(rows)

        async def locator(_incident, _key):
            return resolved if resolved is not None else location()

        async def composer(_facts):
            return composer_text

        async def publish(message, reply_to):
            message_id = 100 + len(sent)
            sent.append((message, reply_to, message_id))
            return message_id

        return await monitor_traffic(
            state,
            now,
            "tomtom-key",
            composer,
            publish,
            fetcher=fetcher,
            locator=locator,
        )

    async def test_new_present_alerts_once_then_repeats_next_morning(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []

            self.assertEqual(
                await self._run(state, NOW, (incident(),), sent),
                1,
            )
            self.assertEqual(
                await self._run(
                    state, NOW + timedelta(minutes=20), (incident(),), sent
                ),
                0,
            )
            next_day_early = datetime(2026, 9, 25, 7, 30, tzinfo=MADRID)
            self.assertEqual(
                await self._run(state, next_day_early, (incident(),), sent),
                0,
            )
            next_day = datetime(2026, 9, 25, 8, 30, tzinfo=MADRID)
            self.assertEqual(
                await self._run(state, next_day, (incident(),), sent),
                1,
            )

        self.assertEqual(len(sent), 2)
        self.assertIn("остаётся перекрыт", sent[1][0])
        self.assertIsNone(sent[1][1])

    async def test_future_alerts_day_before_then_present_alerts_on_start_day(self):
        tomorrow = NOW + timedelta(days=1)
        future = incident(
            validity="future",
            starts_at=tomorrow.replace(hour=9, minute=0),
        )
        present = incident(
            validity="present",
            starts_at=tomorrow.replace(hour=9, minute=0),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []

            self.assertEqual(await self._run(state, NOW, (future,), sent), 1)
            self.assertEqual(
                await self._run(state, NOW + timedelta(hours=1), (future,), sent),
                0,
            )
            start = tomorrow.replace(hour=9, minute=30)
            self.assertEqual(await self._run(state, start, (present,), sent), 1)

        self.assertEqual(len(sent), 2)
        self.assertIn("Завтра", sent[0][0])
        self.assertNotIn("Завтра", sent[1][0])

    async def test_future_more_than_one_day_is_silent(self):
        future = incident(
            validity="future",
            starts_at=NOW + timedelta(days=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []

            self.assertEqual(await self._run(state, NOW, (future,), sent), 0)

        self.assertEqual(sent, [])

    async def test_two_successful_absences_reply_that_road_is_open(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (incident(),), sent)
            self.assertEqual(
                await self._run(state, NOW + timedelta(hours=1), (), sent),
                0,
            )
            self.assertEqual(
                await self._run(state, NOW + timedelta(hours=2), (), sent),
                1,
            )

        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1][1], sent[0][2])
        self.assertIn("Дорога снова открыта", sent[1][0])

    async def test_lane_reopening_has_lane_specific_reply(self):
        lane = incident(category="laneClosed")
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (lane,), sent)
            await self._run(state, NOW + timedelta(hours=1), (), sent)
            await self._run(state, NOW + timedelta(hours=2), (), sent)

        self.assertIn("Полоса движения снова открыта", sent[-1][0])

    async def test_category_change_is_one_useful_reply(self):
        lane = incident(category="laneClosed")
        road = incident(category="roadClosed")
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (lane,), sent)
            self.assertEqual(
                await self._run(
                    state, NOW + timedelta(hours=1), (road,), sent
                ),
                1,
            )
            self.assertEqual(
                await self._run(
                    state, NOW + timedelta(hours=2), (road,), sent
                ),
                0,
            )

        self.assertEqual(sent[1][1], sent[0][2])
        self.assertIn("теперь полностью перекрыт", sent[1][0])

    async def test_reason_end_and_geometry_changes_do_not_push_same_day(self):
        original = incident()
        changed = incident(
            descriptions=("Cerrado", "Obras"),
            ends_at=NOW + timedelta(hours=4),
            to_place="Avenida de Cervantes",
        )
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (original,), sent)
            self.assertEqual(
                await self._run(
                    state, NOW + timedelta(hours=1), (changed,), sent
                ),
                0,
            )

        self.assertEqual(len(sent), 1)

    async def test_external_municipality_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            result = await self._run(
                state,
                NOW,
                (incident(),),
                sent,
                resolved=location(municipality="San Fulgencio"),
            )

        self.assertEqual(result, 0)
        self.assertEqual(sent, [])

    async def test_unpublishable_probability_does_not_alert_or_fake_open(self):
        uncertain = incident(probability="risk_of")
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            self.assertEqual(await self._run(state, NOW, (uncertain,), sent), 0)
            self.assertEqual(
                await self._run(
                    state, NOW + timedelta(hours=1), (uncertain,), sent
                ),
                0,
            )

        self.assertEqual(sent, [])

    async def test_gemini_failure_uses_deterministic_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []

            async def fetcher(_key):
                return (incident(),)

            async def locator(_item, _key):
                return location()

            async def composer(_facts):
                raise RuntimeError("gemini down")

            async def publish(message, reply_to):
                sent.append((message, reply_to))
                return 321

            delivered = await monitor_traffic(
                state,
                NOW,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(delivered, 1)
        self.assertIn("перекрыт проезд", sent[0][0])


if __name__ == "__main__":
    unittest.main()
