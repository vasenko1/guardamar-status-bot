# Event-access final pre-implementation review

- Date: 2026-10-03
- Status: Complete
- Scope: architecture, state, migration, planner semantics, Telegram delivery,
  source freshness, translation/presentation, scheduling, deployment/rollback,
  tests, resource cost, and future-source boundaries.
- Runtime changes: none.

## Executive conclusion

The event-access direction remains correct:

- source-owned access projections;
- one real event -> one Telegram root;
- one event may contain source-proven child options;
- event-centric persistent state;
- record-at-a-time planning;
- exactly one uncertain outbound reservation;
- reserve -> send -> commit;
- source-specific freshness;
- no database, queue, plugin framework, browser, worker, resident scheduler or
  runtime AI.

However, the final review found several details that must be fixed in the
accepted design before implementation. Most changes reduce code rather than
expand it.

The first runtime rollout should contain only:

1. the generic event-access domain and planner;
2. event-centric state v2;
3. explicit v1 -> v2 migration;
4. CONVEGA single-option projection;
5. text roots and strict text replies.

Photo roots, generic cross-source ownership suppression and every non-CONVEGA
source integration remain deferred until the first source that actually needs
them is ready.

## Final minimal code boundary

Use two runtime modules plus the existing source adapter.

### `event_access.py`

Pure, source-independent work only:

- `EventAccessRecord`;
- `AccessOption`;
- validation;
- semantic state encoding/validation;
- pure v1 -> v2 conversion helper;
- per-record planner.

It imports no source adapters and performs no filesystem, network or Telegram
I/O.

This small neutral module is justified because future source adapters must be
able to return event-access records without importing the notification runner
and creating circular dependencies.

### `event_registration_notifications.py`

Keep the deployed external module/wrapper name during rollout. It owns:

- state-file locking and atomic writes;
- explicit migration command and backup;
- CONVEGA batch loading/orchestration;
- text rendering;
- Telegram delivery;
- uncertain operator resolution;
- CLI/status/preview.

Do not split state, renderer and delivery into more modules in the first
rollout.

### `convega.py`

Add only:

- a pure CONVEGA -> `EventAccessRecord` projection;
- an access-specific freshness check.

The existing normal Event projection and source refresh remain intact.

## State v2: simplify the accepted conceptual layout

The prior ADR 0092 `semantic { ... }` + nested `root { ... }` shape is more
nesting than the first implementation needs.

Use one exact bounded record shape:

```text
{
  "version": 2,
  "records": {
    "<record_id>": {
      "source": "convega",
      "access_kind": "registration",

      "event_start_date": "YYYY-MM-DD",
      "event_end_date": null,

      "options": {
        "<option_id>": {
          "status": "unknown|open|full|closed",
          "last_explicit_status": null|"open"|"full"|"closed",

          "opens_on": null|"YYYY-MM-DD",
          "opens_time": null|"HH:MM",
          "closes_on": null|"YYYY-MM-DD",
          "closes_time": null|"HH:MM",

          "until_full": false,
          "action_url": null|"https://...",
          "action_text": null|"..."
        }
      },

      "audience_known": false,
      "root_message_id": null|123456,
      "sent_triggers": []
    }
  },

  "uncertain": null | {
    "created_at": "...",
    "record_id": "...",
    "operation": "root|reply",
    "message": "...",
    "candidate_record": { ...exact record state... }
  }
}
```

Do not persist:

- title;
- translated title;
- teaser;
- poster;
- place/route;
- rendered root prose;
- `published_at`;
- `media_kind`.

The only temporary presentation persistence is the exact `message` inside an
uncertain reservation because operator resolution must commit exactly the
reserved publication.

### State invariants

Validate at minimum:

- map key is the lifecycle `record_id`;
- `source` and `access_kind` are valid and do not change for an existing
  record;
- `event_end_date >= event_start_date`;
- option IDs are non-empty and unique;
- `open` requires a current source-backed `action_url` or `action_text`;
- time cannot exist without its corresponding date;
- `root_message_id`, when present, is a positive integer;
- `root_message_id != null => audience_known == true`;
- `audience_known == true && root_message_id == null` is valid only because
  migrated v1 audience knowledge or a future explicitly reviewed recovery may
  be rootless;
- sent trigger keys are unique and bounded;
- uncertain record ID matches the candidate being reserved.

Initial structural bounds should remain conservative:

- at most 64 retained event records;
- at most 16 options per event;
- at most 128 trigger keys per event.

Do not evict active trigger history merely to satisfy a cap. If a valid source
would exceed a bound, fail closed and review that source contract before
raising the limit.

These are engineering safety bounds, not product limits.

## Boundaries must preserve unknown time

Do not collapse source dates into midnight datetimes.

Keep:

- `opens_on` + optional `opens_time`;
- `closes_on` + optional `closes_time`.

This prevents a date-only source statement from becoming the false claim
"opens at 00:00".

For event eligibility/pruning use `event_end_date or event_start_date`.
A multi-day event must not become "past" immediately after its first day.

## Missing evidence versus explicit evidence

A missing current fact is not an explicit clear.

When the current option observation omits a previously known:

- opening boundary;
- closing boundary;
- action identity;

preserve the previous last-known semantic value for comparison history, but do
not use that preserved value as current source evidence.

In particular:

- reminders are generated only from boundaries present in the current
  observation;
- rendering uses current action facts;
- a current `unknown` observation preserves `last_explicit_status`;
- current absence never means terminal.

No generic explicit-clear sentinel is needed until a source proves that
contract.

## Missing options

The accepted "missing option is not terminal" rule needs one more invariant.

A previously known option absent from the current successful observation:

- remains in semantic history;
- does not count as currently open;
- does not count as full/closed;
- blocks an aggregate claim that every option is unavailable.

For example, if option A is currently observed `full` and previously known
option B is missing, the bot may say "A is full" but must not say "no places
remain for this event".

The planner can derive this from:

```text
previous option IDs - currently observed option IDs
```

No persisted `missing` status is required.

## Terminal transition semantics

Avoid noisy terminal-to-terminal messages.

Notify:

- open -> full;
- open -> closed;
- full/closed -> open ("reopened");
- audience-known unknown -> full/closed when the audience had already been told
  about future access.

Do not notify merely for:

- full -> closed;
- closed -> full;
- full -> full;
- closed -> closed.

The resident action remains the same: access is unavailable.

## Future-opening root must later tell residents when access is usable

This is a real gap in the deployed v1 planner.

If the first root was created from:

- "tomorrow registration opens";
- "today at HH:MM registration opens";
- a one-day future registration window;

then a later positive source observation of `open` must produce one strict
reply with the current action.

Do not suppress this reply just because the advance reminder trigger was
already sent.

This applies to one-day windows as well.

If an exact opening time has already passed but the current source still says
`unknown`, do not infer open.

## Deadline semantics

Separate:

- first-known deadline;
- changed deadline.

For an already-known root:

- `None -> date` = "registration deadline is now known";
- `date A -> date B` = "registration deadline changed".

Deadline reminders ("tomorrow/today closes") require current positive evidence
that the access campaign is open. A deadline combined only with current
`unknown` is not enough to claim residents can still act.

A first root created from current `open` absorbs its deadline/reminder fact
into the root and acknowledges the corresponding trigger atomically.

## Action identity

Action URL/text affects whether a resident can actually act and therefore may
be retained in option semantic state.

Rules:

- an `open` option must provide current action evidence;
- current `unknown` without an action does not erase the previous last-known
  action identity;
- when an audience-known currently open option changes from one explicit action
  to another, one concise action-correction reply is eligible;
- if the same run already needs a stronger opening/reopening root/reply, that
  publication absorbs the current action and no second action-change reply is
  sent.

No automatic root editing is introduced.

## Trigger identity

After ADR 0092, triggers are already stored inside one event record.

Therefore new trigger IDs should not redundantly contain `record_id`.

Use an opaque record-local form conceptually like:

```text
<kind>:<option_id>:<boundary>
```

The exact boundary string includes the source-known date and, when known, time.

No code should parse new trigger IDs for runtime semantics. They are
deterministic opaque deduplication keys.

### Legacy trigger migration

V1 keys do contain record IDs and record IDs themselves contain colons.

Never migrate them using a naive `split(":")`.

For every legacy trigger:

1. test it against the finite known v1 trigger kinds;
2. test each known v1 baseline record ID as the exact middle component;
3. require the remainder to be a valid ISO boundary;
4. require exactly one matching record;
5. convert it to that record's deterministic default-option v2 trigger key.

Zero or multiple matches fail migration.

The 2026-10-03 production probe had zero legacy triggers, but the migration must
still be correct if state changes before deployment.

## Migration must be explicit, locked and reversible only before publication

Do not silently migrate from the normal cron run.

Add an explicit operator command:

```text
python -m telegrambot.event_registration_notifications migrate-state
```

Normal `run` detects v1 and fails closed with "migration required".

Migration under the lifecycle lock:

1. reads and strictly validates v1;
2. requires `uncertain == null`;
3. writes one private v1 backup without overwriting a conflicting existing
   backup;
4. constructs v2 in memory;
5. validates v2;
6. atomically replaces the production state.

No network or Telegram operation occurs.

If state is already v2, migration exits successfully without rewriting it.

### Rollback boundary

Before any v2 Telegram publication, the operator may restore the v1 backup and
the previous production commit.

After the first confirmed v2 root/reply publication, **do not restore v1 state**:
v1 cannot represent the new root/trigger history and rollback could duplicate
resident messages.

After that point use a forward fix or an explicitly reviewed manual
reconciliation.

Document this in the production deploy script/instructions.

## Uncertain delivery simplification

The uncertain reservation does not need separate trigger arrays, root metadata
or a queue.

It contains exactly one record candidate and the exact text payload.

### Root success

```text
reserve candidate with audience_known=true, root_message_id=null
send text root
receive Telegram message_id
commit candidate with root_message_id=returned ID
clear uncertain
```

### Ambiguous root

Keep uncertain. `resolve-sent` must require a positive operator-supplied
Telegram message ID and commit that ID into the candidate.

### Reply success

The candidate already contains the existing root ID. Confirmed send commits it.

### Ambiguous reply

`resolve-sent` needs no reply message ID because reply identity is not stored.

### Post-send state-write failure

After Telegram has returned confirmed success, never compensate by sending
again in the same process.

If the final atomic state write fails, terminate. The next invocation must read
the actual file:

- if the commit landed, the publication is already acknowledged;
- if the prior uncertain reservation remains, automatic publication remains
  blocked.

Do not attempt an automatic "undo" or same-process resend.

## Telegram delivery policy

Every event-access root and reply creates a new Telegram message.

Therefore:

- use `retry_only_rate_limits=True`;
- retry only an explicit HTTP 429 rejection;
- timeout/network/5xx/invalid success response remain ambiguous;
- deterministic 4xx/config/message-length failures are unsent;
- strict replies keep
  `allow_sending_without_reply=false`.

A deterministic `MESSAGE-NOT-FOUND` for a reply target fails closed in the
first rollout. Do not implement automatic replacement-root recovery yet.

## First rollout is text-only

ADR 0090's photo-root policy remains a valid future presentation rule, but it
does not belong in the first runtime change.

The only currently ready access source is CONVEGA and it does not require a
poster transaction.

First rollout:

- one self-contained HTML text root;
- strict HTML text replies.

Defer:

- remote photo send;
- caption-length branching;
- deterministic photo-to-text fallback;
- `media_kind`;
- media file ID storage;
- missing-photo recovery.

This materially reduces the ambiguous-delivery surface of the first state
migration.

## No generic ownership resolver in the first rollout

The production probe found no exact cross-source action overlap and only
CONVEGA is ready to publish.

Therefore the first implementation should not contain a generic ownership
resolver/suppression engine.

It should only:

- require unique source-owned record IDs;
- validate immutable source/access-kind identity.

When the second access source is ready, add its one explicit deterministic
ownership/delegation rule before enabling it.

The architecture still rejects fuzzy cross-source matching.

## CONVEGA freshness must be stronger than "today"

The production probe measured CONVEGA at 10:06 while the lifecycle runs at
12:47 and 13:47.

Registration availability can change within a day, so `fresh-today` is too
weak for an access claim.

Add a source-specific access freshness contract:

- CONVEGA access snapshot must be from the same local day;
- must not be in the future;
- must be no more than 90 minutes old.

The wrapper may attempt one normal CONVEGA refresh when this condition is not
met.

The notification runner independently re-checks the same freshness after the
refresh. This is important because the CONVEGA refresh intentionally preserves
last-good state and may return successfully while the source request failed.

With the current 12:47/13:47 schedule:

- a successful ~12:47 observation can be reused at 13:47;
- a 10:06 morning snapshot is rejected at 12:47;
- if the 12:47 refresh fails and only the 10:06 last-good remains, publication
  is skipped;
- 13:47 can make the bounded recovery attempt again.

Do not generalize this 90-minute rule to other future sources. Each source gets
its own reviewed freshness contract when enabled.

## CONVEGA presentation must not depend on runtime AI

The production probe found no prepared cache entry for the current CONVEGA
title.

Do not solve this by translating inside the send path.

The CONVEGA record already contains stable stage facts. Render a deterministic
Russian presentation such as:

```text
Маршрут GR-92 · этап 21
```

from the structured stage value.

Other future sources may require a prepared reviewed/cache translation. If a
required Russian root presentation is unavailable, fail closed until the
existing preparation workflow has it.

## Python 3.9 compatibility

`pyproject.toml` still declares `requires-python = ">=3.9"`.

The implementation must not accidentally use syntax/runtime features introduced
later, including:

- PEP 604 `X | Y` union syntax;
- `match/case`;
- `enum.StrEnum`;
- `@dataclass(slots=True)`;
- `kw_only=True`.

Use the project's existing Python-3.9-compatible typing/dataclass style unless
the project runtime floor is separately raised.

## Test requirements before merge

The new tests should be table-driven where practical and cover at least:

### Migration/state

- no-file -> empty v2;
- measured production-like v1 migration;
- v1 announced/rootless migration;
- v1 legacy trigger IDs containing colon-rich record IDs;
- ambiguous/invalid trigger mapping fails;
- v1 uncertain blocks migration;
- existing v2 migration command is idempotent;
- backup collision mismatch fails closed;
- root => audience invariant;
- source/access-kind mutation rejected;
- state bounds rejected rather than silently trimmed.

### Planner

- first unknown/open/full/closed;
- first future opening;
- advance opening -> positive open reply;
- one-day advance -> positive open reply;
- open -> unknown -> open is not a false reopen;
- full -> unknown -> open is reopened;
- closed -> unknown -> open is reopened;
- open -> full;
- open -> closed;
- full -> closed is silent;
- closed -> full is silent;
- missing option preserves history but blocks aggregate terminal claim;
- new option after root;
- first-known deadline;
- changed deadline;
- unknown + deadline does not create a closing reminder;
- action change while open;
- date-only boundary preserves unknown time;
- multi-day event remains eligible through its end date.

### Delivery

- root success stores returned root ID;
- root 429 may retry;
- root timeout/network/5xx never retries automatically;
- ambiguous root resolution requires operator root ID;
- reply uses strict root ID;
- ambiguous reply resolution does not require reply ID;
- deterministic missing root fails closed;
- state-write failure after confirmed Telegram success never triggers same-run
  resend;
- uncertain blocks later records;
- earlier committed records remain committed when a later record becomes
  uncertain.

### Freshness/presentation

- CONVEGA >90 minutes old is rejected;
- refresh preserving old last-good does not make it access-fresh;
- future timestamp is rejected;
- deterministic CONVEGA Russian title requires no translation cache.

Run:

- the targeted event-access/CONVEGA tests;
- the complete existing test suite before merge;
- a Python compile/import smoke check on the production interpreter after
  deployment.

No new CI infrastructure is required solely for this feature.

## Deployment sequence

Prefer deployment after the day's 13:47 lifecycle window.

1. Record current production commit and clean status.
2. Fetch canonical `origin/main` and apply the existing ADR 0055 ancestor
   gate.
3. Fast-forward to the merged implementation.
4. Run targeted tests/smoke checks on the phone.
5. Run lifecycle `status`; confirm v1 is still untouched and migration is
   required.
6. Run explicit `migrate-state`.
7. Verify backup + valid v2 `status`.
8. Run read-only `preview`; current measured CONVEGA `full` baseline should
   remain silent unless source facts have changed.
9. Do not manually send a test message to the public group.
10. Let the next scheduled lifecycle invocation use normal source/delivery
    paths.
11. After the first confirmed v2 publication, treat state rollback as unsafe
    and forward-fix any later problem.

If changed Python is reachable from the resident private preview listener,
restart/verify that service under ADR 0055. If the changed modules are not
imported by the listener, do not restart unrelated services.

## Explicitly deferred after this review

Do not implement in the first rollout:

- photo roots;
- generic ownership resolver;
- Agenda Guardamar access;
- Biblioteca access;
- FACV access;
- Pesca CV access;
- AM Guardamar access;
- automatic missing-root replacement;
- root editing;
- cancellation lifecycle;
- price-change lifecycle;
- generic event-time/place correction engine;
- per-event timers;
- continuous polling;
- database/SQLite/Redis;
- generic plugin/source registry;
- runtime AI translation.

## Final go/no-go

After the ADR corrections linked to this review are merged, the architecture is
ready for implementation.

No further broad architecture research is required for the CONVEGA + core
rollout.

Any newly enabled source still requires its own small source-contract review,
not another redesign of the core.
