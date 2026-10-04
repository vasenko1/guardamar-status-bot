import unittest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from telegrambot.event_access import (
    AccessOption,
    EventAccessRecord,
    EventAccessStateError,
    candidate_record_state,
    empty_state,
    migrate_v1_state,
    plan_event_access_record,
    prune_records,
    temporally_consistent,
    validate_state,
)


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=TZ)


def option(**changes):
    values = {
        "option_id": "default",
        "status": "unknown",
        "opens_on": None,
        "opens_time": None,
        "closes_on": None,
        "closes_time": None,
        "until_full": False,
        "action_url": None,
        "action_text": None,
    }
    values.update(changes)
    return AccessOption(**values)


def record(*options, **changes):
    values = {
        "record_id": "convega:post-1:stage-21",
        "source": "convega",
        "source_url": "https://convega.com/example",
        "access_kind": "registration",
        "title": "Поход с гидом по GR-92 · этап 21",
        "event_start_date": date(2026, 10, 4),
        "event_end_date": None,
        "place": "Guardamar del Segura",
        "route": None,
        "details": (),
        "schedule_note": None,
        "options": options or (option(),),
    }
    values.update(changes)
    return EventAccessRecord(**values)


def committed(decision, root_id=100):
    value = dict(decision.candidate_record)
    value["root_message_id"] = root_id
    value["audience_known"] = True
    return value


def legacy_state(**changes):
    baseline = {
        "convega:post-42197:stage-21": {
            "record_id": "convega:post-42197:stage-21",
            "source": "convega",
            "source_url": "https://convega.com/example",
            "title": "Ruta guiada GR-92 · Etapa 21",
            "event_start_date": "2026-10-04",
            "event_end_date": None,
            "registration_start_date": None,
            "registration_start_time": None,
            "registration_end_date": None,
            "registration_end_time": None,
            "status": "full",
            "last_explicit_status": "full",
            "until_full": True,
            "registration_url": None,
            "registration_contact": None,
        }
    }
    value = {
        "version": 1,
        "baseline": baseline,
        "announced_record_ids": [],
        "sent_triggers": [],
        "uncertain": None,
    }
    value.update(changes)
    return value


class EventAccessMigrationTests(unittest.TestCase):
    def test_production_like_v1_migrates_to_event_centric_state(self):
        migrated = migrate_v1_state(legacy_state())

        self.assertEqual(migrated["version"], 2)
        self.assertIsNone(migrated["uncertain"])
        item = migrated["records"]["convega:post-42197:stage-21"]
        self.assertEqual(item["source"], "convega")
        self.assertEqual(item["access_kind"], "registration")
        self.assertFalse(item["audience_known"])
        self.assertIsNone(item["root_message_id"])
        self.assertEqual(item["options"]["default"]["status"], "full")
        self.assertEqual(
            item["options"]["default"]["last_explicit_status"],
            "full",
        )

    def test_announced_v1_record_becomes_rootless_audience_known(self):
        value = legacy_state(
            announced_record_ids=["convega:post-42197:stage-21"]
        )

        migrated = migrate_v1_state(value)

        item = migrated["records"]["convega:post-42197:stage-21"]
        self.assertTrue(item["audience_known"])
        self.assertIsNone(item["root_message_id"])

    def test_colon_rich_legacy_trigger_maps_to_record_local_key(self):
        value = legacy_state(
            sent_triggers=[
                "opening-tomorrow:"
                "convega:post-42197:stage-21:2026-10-03"
            ]
        )

        migrated = migrate_v1_state(value)

        self.assertEqual(
            migrated["records"][
                "convega:post-42197:stage-21"
            ]["sent_triggers"],
            ["opening-tomorrow:default:2026-10-03"],
        )

    def test_invalid_legacy_trigger_fails_closed(self):
        value = legacy_state(sent_triggers=["opening-tomorrow:broken"])

        with self.assertRaises(EventAccessStateError):
            migrate_v1_state(value)

    def test_v1_uncertain_blocks_migration(self):
        value = legacy_state(uncertain={"legacy": True})

        with self.assertRaises(EventAccessStateError):
            migrate_v1_state(value)

    def test_malformed_legacy_record_fails_with_state_error(self):
        value = legacy_state()
        value["baseline"]["convega:post-42197:stage-21"] = "broken"

        with self.assertRaises(EventAccessStateError):
            migrate_v1_state(value)

    def test_root_requires_audience_known(self):
        value = empty_state()
        item = candidate_record_state(
            record(option(status="open", action_url="https://x.example")),
            None,
        )
        item["root_message_id"] = 123
        value["records"]["x"] = item

        with self.assertRaises(EventAccessStateError):
            validate_state(value)


class EventAccessPlannerTests(unittest.TestCase):
    def test_explicit_open_before_boundary_is_temporally_invalid(self):
        current = record(
            option(
                status="open",
                opens_on=date(2026, 10, 3),
                action_url="https://example.com/register",
            )
        )

        self.assertFalse(temporally_consistent(current, NOW))

    def test_explicit_open_after_deadline_is_temporally_invalid(self):
        current = record(
            option(
                status="open",
                closes_on=date(2026, 10, 1),
                action_url="https://example.com/register",
            )
        )

        self.assertFalse(temporally_consistent(current, NOW))

    def test_first_unknown_is_silent(self):
        decision = plan_event_access_record(record(), None, NOW)

        self.assertIsNone(decision.operation)
        self.assertEqual(decision.notices, ())

    def test_first_open_creates_root(self):
        current = record(
            option(status="open", action_url="https://example.com/register")
        )

        decision = plan_event_access_record(current, None, NOW)

        self.assertEqual(decision.operation, "root")
        self.assertEqual(decision.notices[0].kind, "active")
        self.assertTrue(decision.candidate_record["audience_known"])
        self.assertIsNone(decision.candidate_record["root_message_id"])

    def test_first_full_and_closed_are_silent(self):
        for status in ("full", "closed"):
            with self.subTest(status=status):
                decision = plan_event_access_record(
                    record(option(status=status)),
                    None,
                    NOW,
                )
                self.assertIsNone(decision.operation)

    def test_first_future_opening_tomorrow_creates_root(self):
        current = record(option(opens_on=date(2026, 10, 3)))

        decision = plan_event_access_record(current, None, NOW)

        self.assertEqual(decision.operation, "root")
        self.assertEqual(decision.notices[0].kind, "opening-tomorrow")
        self.assertEqual(
            decision.candidate_record["sent_triggers"],
            ["opening-tomorrow:default:2026-10-03"],
        )

    def test_future_opening_root_gets_positive_open_reply(self):
        advance = plan_event_access_record(
            record(option(opens_on=date(2026, 10, 3))),
            None,
            NOW,
        )
        previous = committed(advance)
        current = record(
            option(
                status="open",
                opens_on=date(2026, 10, 3),
                action_url="https://example.com/register",
            )
        )

        decision = plan_event_access_record(
            current,
            previous,
            datetime(2026, 10, 3, 12, 0, tzinfo=TZ),
        )

        self.assertEqual(decision.operation, "reply")
        self.assertEqual(decision.reply_to_message_id, 100)
        self.assertEqual(decision.notices[0].kind, "open")

    def test_one_day_advance_still_gets_open_reply(self):
        advance = plan_event_access_record(
            record(
                option(
                    opens_on=date(2026, 10, 3),
                    closes_on=date(2026, 10, 3),
                )
            ),
            None,
            NOW,
        )
        self.assertEqual(advance.notices[0].kind, "one-day-tomorrow")
        previous = committed(advance)

        decision = plan_event_access_record(
            record(
                option(
                    status="open",
                    opens_on=date(2026, 10, 3),
                    closes_on=date(2026, 10, 3),
                    action_url="https://example.com/register",
                )
            ),
            previous,
            datetime(2026, 10, 3, 9, 0, tzinfo=TZ),
        )

        self.assertEqual(decision.notices[0].kind, "open")

    def test_open_unknown_open_is_not_false_reopen(self):
        first = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/register",
                )
            ),
            None,
            NOW,
        )
        previous = committed(first)
        unknown = plan_event_access_record(
            record(option(status="unknown")),
            previous,
            NOW,
        )
        previous_unknown = dict(unknown.candidate_record)
        previous_unknown["root_message_id"] = 100

        again = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/register",
                )
            ),
            previous_unknown,
            NOW,
        )

        self.assertIsNone(again.operation)

    def test_full_unknown_open_is_reopened(self):
        previous = candidate_record_state(
            record(option(status="full")),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100
        unknown = plan_event_access_record(
            record(option(status="unknown")),
            previous,
            NOW,
        )
        previous_unknown = dict(unknown.candidate_record)
        previous_unknown["root_message_id"] = 100

        reopened = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/register",
                )
            ),
            previous_unknown,
            NOW,
        )

        self.assertEqual(reopened.notices[0].kind, "reopened")

    def test_open_to_full_and_closed_are_notified(self):
        for status in ("full", "closed"):
            with self.subTest(status=status):
                first = plan_event_access_record(
                    record(
                        option(
                            status="open",
                            action_url="https://example.com/register",
                        )
                    ),
                    None,
                    NOW,
                )
                previous = committed(first)

                changed = plan_event_access_record(
                    record(option(status=status)),
                    previous,
                    NOW,
                )

                self.assertEqual(changed.operation, "reply")
                self.assertEqual(changed.notices[0].kind, status)

    def test_terminal_to_terminal_is_silent(self):
        for before, after in (("full", "closed"), ("closed", "full")):
            with self.subTest(before=before, after=after):
                previous = candidate_record_state(
                    record(option(status=before)),
                    None,
                )
                previous["audience_known"] = True
                previous["root_message_id"] = 100

                changed = plan_event_access_record(
                    record(option(status=after)),
                    previous,
                    NOW,
                )

                self.assertIsNone(changed.operation)

    def test_missing_option_preserves_history(self):
        previous = candidate_record_state(
            record(
                option(
                    option_id="a",
                    status="open",
                    action_url="https://example.com/a",
                ),
                option(
                    option_id="b",
                    status="open",
                    action_url="https://example.com/b",
                ),
            ),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(
                option(
                    option_id="a",
                    status="full",
                )
            ),
            previous,
            NOW,
        )

        self.assertIn("b", decision.candidate_record["options"])
        self.assertEqual(
            decision.candidate_record["options"]["b"]["status"],
            "open",
        )
        self.assertEqual(decision.notices[0].kind, "full")

    def test_new_open_option_after_root_is_one_reply(self):
        previous = candidate_record_state(
            record(
                option(
                    option_id="a",
                    status="open",
                    action_url="https://example.com/a",
                )
            ),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(
                option(
                    option_id="a",
                    status="open",
                    action_url="https://example.com/a",
                ),
                option(
                    option_id="b",
                    status="open",
                    action_url="https://example.com/b",
                ),
            ),
            previous,
            NOW,
        )

        self.assertEqual(decision.operation, "reply")
        self.assertEqual(
            [notice.kind for notice in decision.notices],
            ["option-added"],
        )

    def test_first_known_and_changed_deadline(self):
        first = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/register",
                )
            ),
            None,
            NOW,
        )
        previous = committed(first)

        known = plan_event_access_record(
            record(
                option(
                    status="open",
                    closes_on=date(2026, 10, 10),
                    action_url="https://example.com/register",
                )
            ),
            previous,
            NOW,
        )
        self.assertEqual(known.notices[0].kind, "deadline-known")
        previous_known = dict(known.candidate_record)
        previous_known["root_message_id"] = 100

        changed = plan_event_access_record(
            record(
                option(
                    status="open",
                    closes_on=date(2026, 10, 11),
                    action_url="https://example.com/register",
                )
            ),
            previous_known,
            NOW,
        )
        self.assertEqual(changed.notices[0].kind, "deadline-changed")

    def test_unknown_with_deadline_does_not_create_closing_reminder(self):
        previous = candidate_record_state(record(), None)
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(option(closes_on=date(2026, 10, 3))),
            previous,
            NOW,
        )

        self.assertEqual(decision.notices[0].kind, "deadline-known")
        self.assertNotIn(
            "closing-tomorrow",
            [notice.kind for notice in decision.notices],
        )

    def test_action_change_while_open_is_notified(self):
        previous = candidate_record_state(
            record(
                option(
                    status="open",
                    action_url="https://example.com/old",
                )
            ),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/new",
                )
            ),
            previous,
            NOW,
        )

        self.assertEqual(decision.notices[0].kind, "action-changed")

    def test_date_only_boundary_does_not_invent_midnight(self):
        decision = plan_event_access_record(
            record(option(opens_on=date(2026, 10, 3))),
            None,
            NOW,
        )

        stored = decision.candidate_record["options"]["default"]
        self.assertEqual(stored["opens_on"], "2026-10-03")
        self.assertIsNone(stored["opens_time"])

    def test_multi_day_record_survives_until_end_date(self):
        state = candidate_record_state(
            record(
                event_start_date=date(2026, 9, 1),
                event_end_date=date(2026, 10, 2),
            ),
            None,
        )

        kept = prune_records(
            {"x": state},
            date(2026, 10, 2),
        )

        self.assertIn("x", kept)


if __name__ == "__main__":
    unittest.main()
