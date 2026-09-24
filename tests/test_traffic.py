import json
import tempfile
import urllib.parse
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
import telegrambot.traffic as traffic_module
from telegrambot.traffic import (
    TrafficDeliveryUncertain,
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
    event_categories=None,
):
    if event_categories is None:
        event_categories = (None,) * len(descriptions)
    events = []
    for text, event_category in zip(descriptions, event_categories):
        event = {"description": text}
        if event_category is not None:
            event["iconCategory"] = event_category
        events.append(event)
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
            "events": events,
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

    def test_request_does_not_filter_only_by_main_icon_category(self):
        with patch(
            "telegrambot.traffic._request_json",
            return_value=payload(raw_incident()),
        ) as request_json:
            rows = traffic_module._read_incidents("key")

        self.assertEqual(len(rows), 1)
        url = request_json.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertNotIn("iconCategories", query)
        self.assertEqual(query["timeValidity"], ["present,future"])

    def test_secondary_road_closed_event_is_not_missed(self):
        rows = parse_incidents(payload(raw_incident(
            identifier="works-closure",
            category="roadWorks",
            descriptions=("Obras", "Cerrado"),
            event_categories=("roadWorks", "roadClosed"),
        )))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, "roadClosed")
        self.assertEqual(rows[0].descriptions_es, ("Obras", "Cerrado"))

    def test_secondary_lane_closed_event_is_not_missed(self):
        rows = parse_incidents(payload(raw_incident(
            identifier="accident-lane",
            category="accident",
            descriptions=("Accidente", "Carril cerrado"),
            event_categories=("accident", "laneClosed"),
        )))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, "laneClosed")

    def test_road_closed_wins_when_both_closure_events_exist(self):
        rows = parse_incidents(payload(raw_incident(
            identifier="mixed",
            category="roadWorks",
            descriptions=("Carril cerrado", "Cerrado"),
            event_categories=("laneClosed", "roadClosed"),
        )))

        self.assertEqual(rows[0].category, "roadClosed")

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

    def test_lane_and_road_closures_share_one_title(self):
        road_message = build_alert_message(
            incident(category="roadClosed"),
            location(),
            "Перекрыт проезд.",
        )
        lane_message = build_alert_message(
            incident(category="laneClosed"),
            location(),
            "Перекрыта полоса движения.",
        )

        title = "🚧 <b>Перекрытие участка дороги</b>"
        self.assertIn(title, road_message)
        self.assertIn(title, lane_message)
        self.assertNotIn("<b>Перекрытие полосы движения</b>", lane_message)

    def test_valencian_urbanization_prefix_is_removed(self):
        label = location_label(
            incident(from_place=None, to_place=None),
            location(
                subdivision="Urbanització Pòrtic Mediterrani",
                street="Calle Paris",
            ),
        )

        self.assertEqual(label, "Pòrtic Mediterrani — Calle Paris")

    def test_fallback_preserves_spanish_street_casing(self):
        body = fallback_body(
            incident(category="laneClosed"),
            location(street="Avenida del Mediterráneo"),
            "ongoing",
            NOW,
        )

        self.assertIn("Avenida del Mediterráneo", body)
        self.assertNotIn("avenida del mediterráneo", body)

    def test_unknown_end_is_silent(self):
        body = fallback_body(incident(ends_at=None), location(), "new_present", NOW)

        self.assertNotIn("не указ", body.casefold())
        self.assertNotIn("неизвест", body.casefold())
        self.assertNotIn("оконч", body.casefold())

    def test_new_present_fallback_keeps_known_start_time(self):
        body = fallback_body(incident(), location(), "new_present", NOW)

        self.assertIn("16:45 23 сентября", body)

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

    async def test_known_incident_reuses_cached_reverse_geocode(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            locator = AsyncMock(return_value=location())

            async def fetcher(_key):
                return (incident(),)

            async def composer(_facts):
                return None

            async def publish(message, reply_to):
                sent.append((message, reply_to))
                return 123

            await monitor_traffic(
                state,
                NOW,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )
            await monitor_traffic(
                state,
                NOW + timedelta(hours=1),
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(locator.await_count, 1)

    async def test_known_incident_refreshes_location_only_when_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            locator = AsyncMock(side_effect=[
                location(street="Avenida del Mediterráneo"),
                location(street="Avenida de Cervantes"),
            ])

            async def fetcher(_key):
                return (incident(),)

            async def composer(_facts):
                return None

            async def publish(message, reply_to):
                sent.append((message, reply_to))
                return 500 + len(sent)

            await monitor_traffic(
                state,
                NOW,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )
            await monitor_traffic(
                state,
                NOW + timedelta(hours=1),
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )
            next_day = datetime(2026, 9, 25, 8, 30, tzinfo=MADRID)
            await monitor_traffic(
                state,
                next_day,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(locator.await_count, 2)
        self.assertIn("Avenida de Cervantes", sent[-1][0])

    async def test_known_incident_skips_publication_if_fresh_location_no_longer_confirms_guardamar(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            locator = AsyncMock(side_effect=[
                location(street="Avenida del Mediterráneo"),
                None,
            ])

            async def fetcher(_key):
                return (incident(),)

            async def composer(_facts):
                return None

            async def publish(message, reply_to):
                sent.append((message, reply_to))
                return 600 + len(sent)

            await monitor_traffic(
                state,
                NOW,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )
            next_day = datetime(2026, 9, 25, 8, 30, tzinfo=MADRID)
            delivered = await monitor_traffic(
                state,
                next_day,
                "key",
                composer,
                publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(delivered, 0)
        self.assertEqual(locator.await_count, 2)
        self.assertEqual(len(sent), 1)

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

    async def test_ambiguous_send_stops_run_and_preserves_uncertain_marker(self):
        first = incident(provider_id="TTR1")
        second = incident(provider_id="TTR2")
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            publish_calls = []

            async def fetcher(_key):
                return (first, second)

            async def locator(_item, _key):
                return location()

            async def composer(_facts):
                return None

            async def publish(_message, _reply_to):
                publish_calls.append("called")
                raise TrafficDeliveryUncertain()

            with self.assertRaises(TrafficDeliveryUncertain):
                await monitor_traffic(
                    state,
                    NOW,
                    "key",
                    composer,
                    publish,
                    fetcher=fetcher,
                    locator=locator,
                )

            value = state.read()

        self.assertEqual(len(publish_calls), 1)
        record = value["events"]["TTR1"]
        self.assertEqual(record["last_present_alert_date"], NOW.date().isoformat())
        self.assertIn("pending_delivery", record)
        self.assertNotIn("last_message_id", record)

    async def test_uncertain_initial_alert_does_not_create_orphan_reopen_message(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")

            async def first_fetch(_key):
                return (incident(),)

            async def locator(_item, _key):
                return location()

            async def composer(_facts):
                return None

            async def uncertain_publish(_message, _reply_to):
                raise TrafficDeliveryUncertain()

            with self.assertRaises(TrafficDeliveryUncertain):
                await monitor_traffic(
                    state,
                    NOW,
                    "key",
                    composer,
                    uncertain_publish,
                    fetcher=first_fetch,
                    locator=locator,
                )

            reopen_calls = []

            async def empty_fetch(_key):
                return ()

            async def publish(message, reply_to):
                reopen_calls.append((message, reply_to))
                return 777

            await monitor_traffic(
                state,
                NOW + timedelta(hours=1),
                "key",
                composer,
                publish,
                fetcher=empty_fetch,
                locator=locator,
            )
            await monitor_traffic(
                state,
                NOW + timedelta(hours=2),
                "key",
                composer,
                publish,
                fetcher=empty_fetch,
                locator=locator,
            )

        self.assertEqual(reopen_calls, [])

    async def test_explicit_send_failure_retries_as_new_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            calls = []

            async def fetcher(_key):
                return (incident(),)

            async def locator(_item, _key):
                return location()

            async def composer(_facts):
                return None

            async def failing_publish(_message, _reply_to):
                raise RuntimeError("telegram rejected")

            with self.assertRaises(RuntimeError):
                await monitor_traffic(
                    state,
                    NOW,
                    "key",
                    composer,
                    failing_publish,
                    fetcher=fetcher,
                    locator=locator,
                )

            async def successful_publish(message, reply_to):
                calls.append((message, reply_to))
                return 444

            delivered = await monitor_traffic(
                state,
                NOW + timedelta(hours=1),
                "key",
                composer,
                successful_publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("остаётся перекрыт", calls[0][0])

    async def test_failed_category_change_is_retried(self):
        lane = incident(category="laneClosed")
        road = incident(category="roadClosed")
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (lane,), sent)

            async def fetcher(_key):
                return (road,)

            async def locator(_item, _key):
                return location()

            async def composer(_facts):
                return None

            async def failing_publish(_message, _reply_to):
                raise RuntimeError("telegram rejected")

            with self.assertRaises(RuntimeError):
                await monitor_traffic(
                    state,
                    NOW + timedelta(hours=1),
                    "key",
                    composer,
                    failing_publish,
                    fetcher=fetcher,
                    locator=locator,
                )

            async def successful_publish(message, reply_to):
                sent.append((message, reply_to, 999))
                return 999

            delivered = await monitor_traffic(
                state,
                NOW + timedelta(hours=2),
                "key",
                composer,
                successful_publish,
                fetcher=fetcher,
                locator=locator,
            )

        self.assertEqual(delivered, 1)
        self.assertIn("теперь полностью перекрыт", sent[-1][0])
        self.assertIsNotNone(sent[-1][1])

    async def test_reappearing_ended_id_is_treated_as_new(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TrafficState(Path(directory) / "traffic.json")
            sent = []
            await self._run(state, NOW, (incident(),), sent)
            await self._run(state, NOW + timedelta(hours=1), (), sent)
            await self._run(state, NOW + timedelta(hours=2), (), sent)
            delivered = await self._run(
                state,
                NOW + timedelta(hours=3),
                (incident(),),
                sent,
            )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(sent), 3)
        self.assertNotIn("остаётся перекрыт", sent[-1][0])

    async def test_corrupt_nested_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traffic.json"
            path.write_text(
                json.dumps({
                    "version": 1,
                    "events": {
                        "TTR1": {
                            "provider_id": "TTR1",
                            "category": "roadClosed",
                        }
                    },
                }),
                encoding="utf-8",
            )
            state = TrafficState(path)

            with self.assertRaises(TrafficError):
                state.read()

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