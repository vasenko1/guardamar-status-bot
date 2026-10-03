# 0092: Store one-off event-access lifecycle state per event

- Status: Accepted
- Date: 2026-10-03
- Implementation: Pending production-state probe and rollout

## Context

ADR 0089 deployed a narrow CONVEGA-only registration lifecycle. Its state was
correct for that first version:

- one global semantic baseline;
- one global announced-record list;
- one global sent-trigger list;
- one global uncertain publication reservation.

ADR 0090 then changed the publication identity to one Telegram root per real
event, and ADR 0091 generalized the semantic domain from registration to
registration/reservation/ticket access with source-proven child options.

A full clean-sheet review showed that extending the ADR 0089 parallel global
collections into the multi-source/multi-option revision would preserve an
accidental v1 storage shape. It would be valid, but harder to reason about,
prune and recover because one event's semantic baseline, audience knowledge,
root metadata and trigger history would live in several separate structures.

The product invariant is now stronger and simpler:

**one source-owned event record owns one access lifecycle and at most one
Telegram root.**

State should mirror that invariant.

## Decision

### Event-centric persistent state

The next event-access schema stores lifecycle data under one bounded per-event
entry.

Conceptually:

```text
version
records {
  <record_id> {
    semantic {
      access_kind
      event identity/correction facts
      options {
        <option_id> {
          status
          last_explicit_status
          opens_at?
          closes_at?
          until_full
          action identity needed for lifecycle semantics
        }
      }
    }

    audience_known
    root? {
      message_id
      published_at
      media_kind
    }
    sent_triggers[]
  }
}

uncertain?
```

This is a small JSON state, not a database schema or permission to add generic
persistence infrastructure.

Presentation-only facts such as poster URL, translated teaser, decorative
details and current rich-card prose remain in the current projected
`EventAccessRecord`; they are not duplicated into semantic persistence.

### No parallel global announced/root/trigger collections

Do not carry the v1 layout forward as separate global:

```text
baseline
announced_record_ids
root_messages
sent_triggers
```

For the new schema:

- audience knowledge lives beside that event as `audience_known`;
- the Telegram root lives beside that event as `root`;
- trigger history lives beside that event as `sent_triggers`;
- semantic option state lives beside that event as `semantic`.

This makes one lifecycle record the unit of validation, pruning, testing and
operator recovery.

### One-record planner

The semantic planner operates on exactly one observed event record and its
previous per-event state.

Conceptually:

```text
plan_record(observed_record, previous_record_state, now)
    -> silent semantic update
     | root publication
     | strict reply publication
```

The orchestrator may process several independent records in deterministic order,
but it never computes a candidate commit for unrelated records before their
publication succeeds.

### One-record crash-safe reservation

Before one root or reply send, persist one `uncertain` reservation containing
only the affected record operation and that record's exact candidate state.

Conceptually:

```text
uncertain {
  record_id
  operation
  rendered_payload
  candidate_record_state
  created_at
  root_message_id?   # required only when operator resolves an ambiguous root as sent
}
```

Confirmed success commits only that event entry and clears uncertainty.

A deterministic failure that proves no Telegram side effect clears uncertainty
and leaves the prior event state unchanged.

An ambiguous send keeps the reservation and blocks automatic continuation, as
in ADRs 0089-0090.

This is the same lightweight single-slot transactional-outbox pattern, but the
transaction boundary now matches the product identity.

### Pruning is event-local

When an expired event leaves the reviewed retention window, remove one
`records[record_id]` entry. Its semantic option history, audience flag, root
metadata and trigger history disappear together.

Do not maintain an unrelated global trigger FIFO whose eviction can be caused
by other events.

Bounds remain explicit:

- bounded number of active/retained event records;
- bounded options per record from source contracts;
- bounded triggers per record;
- exactly one uncertain outbound operation.

Final numeric bounds must be derived from the production-state probe rather
than copied from ADR 0089's `512` global trigger cap.

### Source collection remains outside lifecycle state

The event-access runner consumes existing local normalized snapshots through
small pure source-specific projections.

It must not grow into a second source-refresh subsystem.

Target boundary:

```text
existing bounded source refreshes
        ↓
normalized local snapshots
        ↓
pure source-specific project_access()
        ↓
AccessSourceBatch(source, observed_at, records)
        ↓
per-source freshness
        ↓
deterministic access ownership
        ↓
plan one record
        ↓
reserve -> send -> commit
```

A stale source batch is omitted independently. It must not suppress fresh
records from other sources.

The existing CONVEGA wrapper may remain as a deployment-compatible backstop in
the first rollout, but new sources must not copy its "refresh from the
notification runner" pattern without measured timing evidence.

### V1 migration

Perform one deterministic migration from the deployed ADR 0089 state.

Deployment precondition:

```text
legacy uncertain == null
```

If not, stop deployment until the operator resolves that delivery.

For each valid v1 baseline record:

- create one event-centric `records[record_id]`;
- set `access_kind="registration"`;
- migrate it as one deterministic default option;
- preserve current and last explicit status evidence;
- set `audience_known=true` when the ID was in legacy
  `announced_record_ids`;
- move that record's legacy trigger IDs into its local `sent_triggers`;
- set `root=null` because v1 did not own per-event roots.

Do not invent Telegram message IDs.

If a migrated audience-known event later needs publication while `root=null`,
create one complete replacement/current-state root and store its ID; do not send
an orphan reply and do not pretend the event was never announced.

After a successful atomic migration, normal runtime supports only the new state
version. Do not keep a permanent dual-schema compatibility path.

### External names need not change during functional rollout

Internal new types should use event-access terminology.

Do not couple the functional migration to cosmetic production renames of:

- `termux/run-event-registration.sh`;
- `EVENT_REGISTRATION_STATE_PATH`;
- `state/event_registration_notifications.json`;
- existing log paths.

A later isolated cleanup may rename them after rollout.

## Consequences

### Benefits

- persistent shape matches one-event/one-root product identity;
- no drift between separate baseline/announced/root/trigger maps;
- record-at-a-time crash safety becomes explicit;
- pruning cannot leave orphan audience/root/trigger metadata;
- active events do not compete for one global trigger FIFO;
- simpler unit tests and operator inspection;
- still one tiny atomic JSON file and one uncertain slot.

### Costs

- the first multi-source rollout needs one state migration rather than a small
  additive v1 extension;
- trigger migration must associate legacy keys with their record ID;
- state validation becomes nested, though still bounded and deterministic.

## Alternatives rejected

### Extend the ADR 0089 parallel global collections

Functionally workable, but it preserves a v1 batching-oriented storage shape
after batching is no longer the lifecycle identity.

### Separate state file per event

Rejected. It increases file churn, locking and cleanup complexity for no
benefit at the expected scale.

### Database / SQLite / Redis

Rejected. The data volume and transaction model remain tiny; one atomic JSON
file is easier to recover on Termux.

### Persist presentation state with semantic state

Rejected. Poster/translation/prose changes are not access lifecycle changes.

### Let the notification runner refresh every source

Rejected. Collection and lifecycle publication remain separate bounded
responsibilities.
