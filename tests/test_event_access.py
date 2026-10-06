import unittest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from telegrambot.event_access import (
    AccessOption,
    EventAccessRecord,
    EventAccessStateError,
    MAX_RECORDS,
    MAX_TRIGGERS_PER_RECORD,
    candidate_record_state,
    empty_state,
    migrate_v1_state,
    migrate_v2_state,
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


def v2_state(*, audience_known=True, root_message_id=100):
    return {
        "version": 2,
        "records": {
            "convega:post-1:stage-21": {
                "source": "convega",
                "access_kind": "registration",
                "event_start_date": "2026-10-04",
                "event_end_date": None,
                "options": {
                    "default": {
                        "status": "unknown",
                        "last_explicit_status": None,
                        "opens_on": None,
                        "opens_time": None,
                        "closes_on": None,
                        "closes_time": None,
                        "until_full": False,
                        "action_url": None,
                        "action_text": None,
                    }
                },
                "audience_known": audience_known,
                "root_message_id": root_message_id,
                "sent_triggers": [],
            }
        },
        "uncertain": None,
    }


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

        self.assertEqual(migrated["version"], 3)
        self.assertIsNone(migrated["uncertain"])
        item = migrated["records"]["convega:post-42197:stage-21"]
        self.assertEqual(item["source"], "convega")
        self.assertEqual(item["access_kind"], "registration")
        self.assertFalse(item["audience_known"])
        self.assertIsNone(item["root_message_id"])
        self.assertFalse(item["context_known"])
        self.assertEqual(item["title"], "Ruta guiada GR-92 · Etapa 21")
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

    def test_v2_migration_baselines_material_context_without_guessing(self):
        migrated = migrate_v2_state(v2_state())

        self.assertEqual(migrated["version"], 3)
        item = migrated["records"]["convega:post-1:stage-21"]
        self.assertFalse(item["context_known"])
        self.assertEqual(item["title"], "convega:post-1:stage-21")
        self.assertIsNone(item["place"])
        self.assertIsNone(item["schedule_note"])

        decision = plan_event_access_record(
            record(),
            item,
            NOW,
        )

        self.assertNotIn(
            "event-details-changed",
            [notice.kind for notice in decision.notices],
        )
        self.assertTrue(decision.candidate_record["context_known"])
        self.assertEqual(
            decision.candidate_record["place"],
            "Guardamar del Segura",
        )

    def test_v2_uncertain_blocks_migration(self):
        value = v2_state()
        value["uncertain"] = {"pending": True}

        with self.assertRaises(EventAccessStateError):
            migrate_v2_state(value)

    def test_v1_uncertain_blocks_migration(self):
        value = legacy_state(uncertain={"legacy": True})

        with self.assertRaises(EventAccessStateError):
            migrate_v1_state(value)

    def test_malformed_legacy_record_fails_with_state_error(self):
        value = legacy_state()
        value["baseline"]["convega:post-42197:stage-21"] = "broken"

        with self.assertRaises(EventAccessStateError):
            migrate_v1_state(value)

    def test_source_and_access_kind_are_immutable(self):
        previous = candidate_record_state(record(), None)

        with self.assertRaises(EventAccessStateError):
            candidate_record_state(
                record(source="other"),
                previous,
            )
        with self.assertRaises(EventAccessStateError):
            candidate_record_state(
                record(access_kind="ticket"),
                previous,
            )

    def test_state_bounds_fail_closed_instead_of_trimming(self):
        item = candidate_record_state(record(), None)
        value = empty_state()
        for index in range(MAX_RECORDS + 1):
            value["records"][f"record-{index}"] = dict(item)

        with self.assertRaises(EventAccessStateError):
            validate_state(value)

        bounded = empty_state()
        trigger_item = dict(item)
        trigger_item["sent_triggers"] = [
            f"trigger-{index}"
            for index in range(MAX_TRIGGERS_PER_RECORD + 1)
        ]
        bounded["records"]["record"] = trigger_item

        with self.assertRaises(EventAccessStateError):
            validate_state(bounded)

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

    def test_terminal_unknown_open_is_reopened(self):
        for terminal in ("full", "closed"):
            with self.subTest(terminal=terminal):
                previous = candidate_record_state(
                    record(option(status=terminal)),
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

    def test_migrated_audience_known_rootless_creates_complete_root(self):
        previous = candidate_record_state(
            record(option(status="full")),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = None

        decision = plan_event_access_record(
            record(
                option(
                    status="open",
                    action_url="https://example.com/register",
                )
            ),
            previous,
            NOW,
        )

        self.assertEqual(decision.operation, "root")
        self.assertEqual(decision.notices[0].kind, "reopened")
        self.assertTrue(decision.candidate_record["audience_known"])
        self.assertIsNone(decision.candidate_record["root_message_id"])
        self.assertEqual(
            decision.candidate_record["options"]["default"]["status"],
            "open",
        )

    def test_rootless_material_trigger_is_absorbed_into_new_root(self):
        previous = candidate_record_state(
            record(option(status="unknown")),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = None

        decision = plan_event_access_record(
            record(option(opens_on=date(2026, 10, 3))),
            previous,
            NOW,
        )

        self.assertEqual(decision.operation, "root")
        self.assertEqual(decision.notices[0].kind, "opening-tomorrow")
        self.assertEqual(
            decision.candidate_record["sent_triggers"],
            ["opening-tomorrow:default:2026-10-03"],
        )

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

    def test_deadline_and_action_change_share_one_reply(self):
        previous = candidate_record_state(
            record(
                option(
                    status="open",
                    closes_on=date(2026, 10, 10),
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
                    closes_on=date(2026, 10, 11),
                    action_url="https://example.com/new",
                )
            ),
            previous,
            NOW,
        )

        self.assertEqual(decision.operation, "reply")
        self.assertEqual(
            [notice.kind for notice in decision.notices],
            ["deadline-changed", "action-changed"],
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


    def test_access_boundary_cannot_extend_past_event_end(self):
        with self.assertRaises(ValueError):
            candidate_record_state(
                record(
                    option(
                        closes_on=date(2026, 10, 5),
                    )
                ),
                None,
            )

    def test_open_access_after_event_day_is_temporally_inconsistent(self):
        item = record(
            option(
                status="open",
                action_url="https://example.com/register",
            ),
            event_start_date=date(2026, 10, 1),
        )

        self.assertFalse(temporally_consistent(item, NOW))

    def test_event_date_change_is_one_rooted_notice(self):
        previous = candidate_record_state(record(), None)
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(event_start_date=date(2026, 10, 5)),
            previous,
            NOW,
        )

        self.assertEqual(decision.operation, "reply")
        self.assertEqual(
            [notice.kind for notice in decision.notices],
            ["event-date-changed"],
        )
        self.assertEqual(decision.reply_to_message_id, 100)

    def test_material_context_change_is_notified_after_baseline(self):
        previous = candidate_record_state(
            record(place="Centro Social", schedule_note="Старт 10:00"),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(place="Palau Sant Jaume", schedule_note="Старт 11:00"),
            previous,
            NOW,
        )

        self.assertEqual(
            [notice.kind for notice in decision.notices],
            ["event-details-changed"],
        )

    def test_missing_context_does_not_erase_last_proven_fact(self):
        previous = candidate_record_state(
            record(place="Centro Social"),
            None,
        )
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(place=None),
            previous,
            NOW,
        )

        self.assertEqual(
            decision.candidate_record["place"],
            "Centro Social",
        )
        self.assertNotIn(
            "event-details-changed",
            [notice.kind for notice in decision.notices],
        )

    def test_explicit_cancellation_is_notified_on_existing_root(self):
        previous = candidate_record_state(record(), None)
        previous["audience_known"] = True
        previous["root_message_id"] = 100

        decision = plan_event_access_record(
            record(occurrence_status="cancelled"),
            previous,
            NOW,
        )

        self.assertEqual(
            [notice.kind for notice in decision.notices],
            ["event-cancelled"],
        )

    def test_cancelled_event_cannot_keep_open_access(self):
        with self.assertRaises(ValueError):
            candidate_record_state(
                record(
                    option(
                        status="open",
                        action_url="https://example.com/register",
                    ),
                    occurrence_status="cancelled",
                ),
                None,
            )


if __name__ == "__main__":
    unittest.main()
