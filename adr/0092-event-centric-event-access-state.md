# 0092: Store one-off event-access lifecycle state per event

- Status: Accepted
- Date: 2026-10-03
- Implementation: v2 deployed; v3 material-context refinement pending validation
- Refined by: `research/2026-10-03-event-access-final-preimplementation-review.md`

## Context

ADR 0089 deployed a narrow CONVEGA-only registration lifecycle with four
parallel global collections:

- semantic baseline;
- announced-record IDs;
- sent-trigger IDs;
- one uncertain publication reservation.

ADR 0090 introduced one Telegram root per real event. ADR 0091 generalized the
semantic domain from one registration action to registration/reservation/ticket
access with source-proven child options.

The clean-sheet reviews showed that carrying the ADR 0089 global layout into
the new lifecycle would preserve an accidental batching-oriented state shape.

The stronger invariant is:

**one source-owned event record owns one access lifecycle and at most one
Telegram root.**

State should mirror that invariant while remaining one small atomic JSON file.

## 2026-10-06 refinement: version 3 tracks material root context

The deployed v2 layout remains the historical first event-centric rollout.
Sports-source review exposed one missing lifecycle requirement: once an event
has a long-lived Telegram root, a responsible source may later correct material
event facts such as the date, place or schedule. V2 can compare dates but
cannot compare place/schedule because those facts were intentionally
presentation-only.

Version 3 therefore adds only the bounded event context required for correction
detection:

```text
place?
route?
schedule_note?
context_known
occurrence_status?   # scheduled | cancelled | postponed
```

This is not a second event database. Title, `details`, fees, poster URLs,
rendered copy and other presentation facts remain outside persistent lifecycle
state. Title-only editorial changes therefore never create a material
correction reply.

`context_known=false` is a migration baseline marker. A migrated v2 record
learns its first fresh v3 place/route/schedule silently; only later
source-proven changes can notify. Missing current place/route/schedule evidence
does not erase the last proven value.

An explicit `cancelled` or `postponed` state may notify on an existing root.
Disappearance of that marker does not restore the event. Restoration requires
an explicit source-proven `scheduled` observation. A cancelled occurrence
cannot simultaneously expose current `open` access.

Access opening/closing boundaries may not extend beyond
`event_end_date or event_start_date`. An explicit `open` status after the event
has ended is temporally inconsistent and is omitted.

### Version 2 -> version 3 migration

Migration remains an explicit operator action under the same lifecycle lock.

- normal `run` never auto-migrates v2;
- `status` reports v2 as `migration_required=true`;
- require `uncertain == null`;
- validate the complete v2 state before mutation;
- create a private non-overwriting `.v2-backup.json`;
- preserve source, access kind, dates, option history, audience knowledge,
  root message IDs and trigger history;
- initialize material context with `context_known=false`;
- validate v3 completely, then atomically replace the production state.

Existing v1 state may migrate directly to v3 through the same explicit command
and retains the existing v1 backup contract.

Before the first confirmed v3 root/reply, an operator may roll back the code and
restore the exact v2 backup. After any confirmed v3 publication, restoring v2
is unsafe because v2 cannot represent the new material correction/history
semantics; use a forward fix or explicit reconciliation instead.

## Decision

### State version 2 is event-centric and flat per record

This subsection records the deployed historical v2 shape. The 2026-10-06 v3
refinement above supersedes only the material-context persistence and migration
parts; the event-centric ownership/bounds remain unchanged.

Use one exact bounded entry per lifecycle record.

Conceptually:

```text
version = 2

records {
  <record_id> {
    source
    access_kind

    event_start_date
    event_end_date?

    options {
      <option_id> {
        status
        last_explicit_status

        opens_on?
        opens_time?
        closes_on?
        closes_time?

        until_full
        action_url?
        action_text?
      }
    }

    audience_known
    root_message_id?
    sent_triggers[]
  }
}

uncertain?
```

Do not add an extra `semantic { ... }` nesting layer or a nested root object in
the first rollout. The event entry is already the unit of semantic and delivery
state.

Persist only facts needed for lifecycle comparison, root identity, pruning and
deduplication.

Do **not** persist normal presentation facts such as:

- title or translated title;
- teaser/description;
- poster/image URL;
- place/route;
- rendered rich-card prose;
- root publication time;
- media kind.

Current presentation remains on the current projected `EventAccessRecord`.

### State invariants

The validator must fail closed when any invariant is violated.

At minimum:

- each map key is a non-empty lifecycle `record_id`;
- `source` and `access_kind` are valid;
- for an existing record, `source` and `access_kind` are immutable;
- `event_end_date >= event_start_date`;
- option IDs are non-empty and unique;
- option status is one of `unknown/open/full/closed`;
- `last_explicit_status` is null or `open/full/closed`;
- an `open` option has current source-backed action evidence;
- an option time cannot exist without its corresponding date;
- `root_message_id`, when present, is a positive integer;
- `root_message_id != null` implies `audience_known=true`;
- sent trigger keys are unique;
- uncertain state refers to exactly one record and its exact candidate state.

`audience_known=true` with `root_message_id=null` remains valid because a
migrated ADR 0089 publication may be known to residents without an individual
recoverable root.

### Structural bounds

The first rollout uses conservative safety bounds, not product limits:

- at most 64 retained lifecycle records;
- at most 16 options per event;
- at most 128 trigger keys per event;
- exactly one uncertain outbound operation.

Do not silently evict active trigger history to satisfy a cap. If a valid future
source exceeds a bound, fail closed and review that source contract before
raising the bound.

The current production probe measured one retained lifecycle record, zero
triggers, no municipal source-proven session family and a maximum of four
repeated Agenda occurrences under one ticket path. The chosen bounds therefore
retain substantial headroom without permitting unbounded state growth.

### Preserve unknown time

Store source-known boundary dates and optional times separately:

```text
opens_on + opens_time?
closes_on + closes_time?
```

Do not convert a date-only source fact into midnight.

For event retention and "past event" decisions use
`event_end_date or event_start_date`, so an active multi-day event is not
discarded after its first day.

### Missing facts are not explicit clears

A current source observation may omit a previously known boundary/action.

In the first rollout, omission means "no current evidence", not an explicit
semantic clear.

Preserve prior last-known semantic values for comparison history, but:

- reminders use only boundaries present in the **current observation**;
- rendering uses only current source-backed action facts;
- current `unknown` does not erase `last_explicit_status`.

No generic explicit-clear sentinel is introduced until an actual source
contract requires it.

### Missing options remain unresolved

A previously known option absent from the current successful observation:

- remains in semantic history;
- does not count as currently open;
- does not count as full/closed;
- blocks an aggregate claim that all options are unavailable.

The planner derives missing options from previous option IDs minus current
option IDs. No persisted `missing` status is added.

### Trigger history is record-local

Do not carry ADR 0089's global trigger list forward.

New trigger IDs are already stored inside one event record, so they do not
repeat `record_id`.

Conceptually:

```text
<kind>:<option_id>:<boundary>
```

The boundary component includes the source-known date and, when known, time.

Runtime treats new trigger IDs as opaque equality keys; it does not parse them
for semantic decisions.

### One-record planner

The planner operates on one observed event and one previous event state:

```text
plan_record(observed_record, previous_record_state, now)
    -> silent candidate
     | root publication candidate
     | strict reply publication candidate
```

The orchestrator processes records in deterministic order.

For every record:

1. a silent semantic update may commit immediately;
2. a publication is reserved;
3. Telegram send is attempted;
4. only confirmed success commits that record;
5. only then may the next record be processed.

No candidate commit for unrelated records is prepared/committed as part of one
publication transaction.

### Uncertain state is one exact record transaction

Use one global uncertain slot:

```text
uncertain {
  created_at
  record_id
  operation        # root | reply
  message
  candidate_record
}
```

No separate trigger arrays, root object, publication queue or batch candidate
belong in uncertain state.

The exact rendered text is retained only while uncertain so operator resolution
commits the reserved operation, not a recomputed variant.

#### Confirmed root

Reserve a candidate with:

- `audience_known=true`;
- `root_message_id=null`.

After Telegram returns a positive message ID, commit the candidate with that
ID and clear uncertainty.

#### Ambiguous root

Keep uncertainty.

`resolve-sent` must require the operator-supplied positive Telegram root
message ID and commit it into the candidate.

#### Confirmed/ambiguous reply

A reply candidate already contains its existing root message ID.

Confirmed success commits normally.

An ambiguous reply keeps uncertainty; operator `resolve-sent` needs no reply
message ID because reply IDs are not stored.

#### State-write failure after Telegram success

After Telegram has returned confirmed success, never attempt a compensating
resend in the same process.

If the final atomic state write fails, terminate. The next invocation reads the
actual state file:

- if the commit landed, the publication is acknowledged;
- if the prior uncertain reservation remains, automatic publication stays
  blocked.

This preserves safety across the unavoidable post-send persistence edge.

### Pruning is event-local

When an event is older than the reviewed retention window, remove its one
`records[record_id]` entry.

Its:

- option history;
- audience flag;
- root ID;
- trigger history

are pruned together.

Do not maintain independent global FIFOs that can leave orphan delivery state.

### Source collection remains outside lifecycle state

Event-access publication consumes normalized local source snapshots through
small source-specific projections.

Target boundary:

```text
bounded source refresh
      ↓
normalized local snapshot
      ↓
pure source-specific access projection
      ↓
per-source freshness
      ↓
plan one record
      ↓
reserve -> send -> commit
```

Do not build a second general source-refresh subsystem.

The first runtime rollout has only one enabled source (CONVEGA), so no generic
cross-source ownership resolver is implemented yet. Explicit ownership
suppression is added only with the first source pair that actually overlaps.

### V1 migration is explicit, not a cron side effect

The 2026-10-03 production probe measured:

- state version 1;
- one baseline record;
- zero announced records;
- zero sent triggers;
- `uncertain=null`.

The state may still change before deployment, so runtime must revalidate the
actual file.

Normal `run` must not silently migrate v1.

Provide an explicit operator command:

```text
python -m telegrambot.event_registration_notifications migrate-state
```

Under the same lifecycle lock:

1. read and strictly validate v1;
2. require `uncertain == null`;
3. create one private v1 backup without overwriting a conflicting backup;
4. construct v2 entirely in memory;
5. validate v2;
6. atomically replace the production state.

If state is already valid v2, the migration command exits successfully without
rewriting it.

No source request or Telegram operation occurs during migration.

### V1 mapping

For every valid v1 baseline record:

- create `records[record_id]`;
- preserve the source;
- set `access_kind="registration"`;
- preserve event start/end dates;
- create one deterministic default option;
- preserve current status and last explicit status;
- map registration start/end date+time to option opening/closing boundaries;
- preserve `until_full`;
- map current URL/contact action into option action fields;
- set `audience_known=true` only when present in legacy
  `announced_record_ids`;
- set `root_message_id=null`.

Do not invent a Telegram root ID.

A migrated audience-known/rootless event creates one complete current-state root
on its next material publication instead of sending an orphan reply.

### Legacy trigger migration

V1 trigger IDs contain record IDs, and record IDs themselves may contain
colons. Never parse them with a naive `split(":")`.

For every legacy trigger:

1. test the finite accepted v1 trigger kinds;
2. test every known baseline record ID as the exact middle component;
3. require a valid ISO boundary suffix;
4. require exactly one matching record;
5. rewrite it to that record's deterministic default-option v2 trigger key.

Zero or multiple matches abort migration.

The measured production state currently has zero legacy triggers, but the code
must remain correct if state changes before rollout.

### Backup and rollback boundary

The migration backup exists to recover the deployment only before v2 has
created new resident-facing history.

Before any confirmed v2 root/reply publication, the operator may restore:

- the previous production commit;
- the exact v1 backup.

After the first confirmed v2 publication, restoring v1 is unsafe because v1
cannot represent the new root/trigger history and may create duplicates.

After that boundary, use a forward fix or explicit manual reconciliation.

### External production names stay stable

Do not combine functional rollout with cosmetic renames of:

- `termux/run-event-registration.sh`;
- `EVENT_REGISTRATION_STATE_PATH`;
- `state/event_registration_notifications.json`;
- current log paths.

Internal types may use `EventAccess*` terminology.

## Consequences

### Benefits

- one event is one state/recovery unit;
- migration is operator-visible and reversible before publication;
- root identity and semantic history cannot drift across separate global maps;
- trigger history cannot be evicted by unrelated events;
- record-at-a-time crash safety is direct;
- state remains one tiny local JSON file;
- future multi-option sources do not require another persistent-schema redesign.

### Costs

- one explicit migration command is required during rollout;
- validation is stricter than ADR 0089;
- legacy trigger mapping needs a small migration-only parser;
- after first v2 publication, rollback must be forward rather than restoring v1.

## Alternatives rejected

### Extend ADR 0089's parallel global collections

Rejected because those collections encode the old batch-publication shape.

### Automatically migrate inside normal cron execution

Rejected because schema migration should not be hidden inside a resident-facing
publication path.

### Store root publication time/media kind now

Rejected. The first rollout is text-only and neither field participates in
current lifecycle decisions.

### Separate state file per event

Rejected. It adds filesystem/locking/cleanup work without useful scale benefit.

### SQLite / Redis / message broker

Rejected. Current volume and transaction semantics remain trivial for one
atomic JSON file.

### Persist full presentation state

Rejected. Current presentation comes from current projections/cache and is not
lifecycle truth.
