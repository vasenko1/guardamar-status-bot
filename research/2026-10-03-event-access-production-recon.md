# Event-access production reconnaissance and event-centric state review

## Status

Completed 2026-10-03.

This research combines:

1. a live read-only first-party source reconnaissance performed against the
   current production source set; and
2. a read-only Termux production-state probe covering the deployed snapshots,
   translation cache, lifecycle state and source logs.

The Termux probe ran on production branch `main` at
`8a906a5d462a7a9c415897bba6013d791421263a`. The GitHub `main` branch was
already ahead only by documentation/research commits; no runtime delta relevant
to this probe existed.

No runtime code, cron, state or Telegram publication is changed by this
research.

ADR 0092 records the durable event-centric state decision produced by the
clean-sheet review.

## Why this probe exists

ADRs 0090-0091 established the product shape:

- one real event -> one Telegram root;
- registration/reservation/ticket access share one lifecycle;
- source-proven sessions become child options;
- later changes reply to the root.

Before multi-source implementation we still needed to prove:

- which accepted sources really expose actionable access;
- what identity each source can safely preserve;
- whether options are event slots or merely several action methods;
- whether current source horizons are sufficient;
- how cross-source ownership should work;
- how much state/trigger volume production can actually create.

A clean-sheet review also showed that ADR 0089's global parallel state
collections should not be copied into the multi-source revision. ADR 0092
therefore changes only the pending target state architecture, not deployed
runtime.

## Live first-party findings

### CONVEGA: source contract remains valid

The current GR-92 landing for the 4 October 2026 stage still exposes the
Guardamar route and currently reports `PLAZAS AGOTADAS`.

The current CONVEGA article identifies the 4 October Guardamar-Torrevieja stage,
states a 100-person limit and directs residents to the registration form on the
CONVEGA landing.

Implications:

- CONVEGA remains the strongest reference single-option access source;
- source-owned stage identity remains preferable to title/date identity;
- explicit `full` evidence is real and current;
- the current source demonstrates that availability can change independently
  from ordinary event presentation.

### Turismo / municipal cultural programme: one source really mixes access kinds

The current official cultural page demonstrates all of the following shapes:

- paid ticket sale during a stated Casa de Cultura sale window;
- free invitation through Agenda Guardamar;
- free walk-in admission until capacity;
- bounded workshop registration;
- guided-tour ticket purchase;
- direct registration/reservation form.

Implications:

- the lifecycle entity must be `event access`, not registration;
- `entrada libre hasta completar aforo` without advance action remains
  excluded from proactive access;
- physical sale windows require `action_text`, not a fake contact URL;
- recurring box-office hours are presentation, not daily open/closed lifecycle
  transitions;
- Municipal/Turismo cannot be modelled by one generic "URL means open" rule.

### Biblioteca: public catalogue horizon exceeds the current 7-day adapter window

On 3 October the official Guardamar library agenda publicly listed activities
through at least 26 October.

The deployed adapter intentionally keeps `HORIZON_DAYS = 7` for its current
Morning role.

Implications:

- seven days is not a safe global event-access horizon;
- the source itself can expose useful future events substantially earlier;
- access rollout must either widen only this source's bounded candidate horizon
  or prove that actionable registration never appears earlier;
- do not change the current Morning adapter horizon until the detail/action
  contract is measured.

The current Guardamar list does not by itself prove that every future activity
has registration. Event-specific detail/action evidence still needs the local
snapshot/detail probe.

### FACV: one option can have several action methods

Current 2026 Guardamar tournament articles explicitly provide:

- one tournament/article;
- registration by email;
- registration by WhatsApp;
- one web form;
- a maximum capacity of 220;
- a maximum registration deadline;
- prices and later price tiers.

Implications:

- email + WhatsApp + web form are several action methods for one option;
- they must not become three lifecycle options;
- price tiers remain presentation-only in v1;
- FACV can provide explicit capacity/deadline evidence;
- stable article/detail identity should own the lifecycle rather than the
  current title/date/place row key.

### Pesca CV: confirmed as a real long-lead access source

The official 2026 competition page currently lists a Provincial Alicante
Mar-Costa event for 17 October on La Roqueta and Centro beaches in Guardamar.

Its official convocatoria PDF, issued 14 September 2026, states:

- event date: 17 October 2026;
- location: La Roqueta and Centro, Guardamar;
- registrations are performed by clubs;
- registration deadline: 13 October at 12:00;
- federation contact information;
- a club registration form in the same official document.

Implications:

- Pesca CV is not merely a Morning/Weekend calendar source;
- it can expose actionable long-lead registration boundaries weeks before the
  event;
- the current calendar snapshot does not retain the convocatoria/access facts,
  so event-access support must project from the convocatoria detail/PDF, not
  infer registration from the calendar row;
- this is strong evidence for source-specific horizons and detail identities;
- the access action is club-mediated, so user-facing wording must not imply
  that any resident can directly self-register when the source restricts the
  action to clubs.

### Agenda Guardamar: public external probe is incomplete

The official host currently rejects generic external homepage fetching with
HTTP 403, while the deployed adapter already reaches and validates
occurrence-specific `/entradas/` URLs through its reviewed request path.

Code review still proves that the adapter:

- parses several session-specific ticket URLs from one detail page;
- validates each URL against exact date/time;
- then flattens those sessions into separate `Event` rows and discards the
  parent detail identity.

The live external probe cannot prove whether a ticket URL is:

- absent before sale;
- present while open;
- retained while sold out/closed.

That remains a production/local-source probe requirement. Do not promote
"ticket URL exists" into generic `open` evidence.

### AM Guardamar: still not proven as an access owner

The current adapter has stable WordPress post IDs and featured media, but the
live reconnaissance did not produce enough current first-party ticket or
registration examples to establish a durable access contract.

Keep AM Guardamar in the source inventory, but fail closed until a real
actionable post proves:

- stable parent/child occurrence identity where needed;
- access action semantics;
- ownership relative to Municipal/Agenda Guardamar.

## First-party references checked

- CONVEGA current landing:
  `https://convega.com/rutasguiadas-senderodelmediterraneo/`
- CONVEGA announcement:
  `https://convega.com/convega-organiza-dos-rutas-guiadas-por-el-gr-92-mejor-sendero-homologado-2025-de-la-comunitat-valenciana/`
- Turismo Guardamar cultural agenda:
  `https://guardamarturismo.com/agenda-cultural/`
- Biblioteca Pública Municipal de Guardamar agenda:
  `https://www.bibliotecaspublicas.es/guardamardelsegura/actividades-programas/Agenda-de-actividades.html`
- FACV Guardamar IRT Sub2400:
  `https://www.facv.org/iv-festival-internacional-esphouses-irt-sub2400`
- FACV Guardamar IRT Sub1800:
  `https://www.facv.org/iv-festival-internacional-esphouses-irt-sub1800`
- Federación de Pesca CV 2026 convocatorias:
  `https://federacionpescacv.com/convocatorias-clasificaciones-2026/`
- Pesca CV 17 October 2026 Guardamar convocatoria:
  `https://federacionpescacv.com/wp-content/uploads/2026/09/bases-prov-mar-costa-captura-y-suelta-2026.pdf`

All source checks were read-only. Agenda Guardamar generic homepage access
returned HTTP 403 from the external probe environment; no conclusion about its
ticket-state lifecycle was drawn from that failure.

## Cross-source ownership implications

The live sources reinforce the existing no-fuzzy-merge rule.

Likely ownership shapes remain:

- CONVEGA owns its own route registration;
- FACV owns its tournament registration;
- Pesca CV owns federation competition registration/convocatoria facts;
- Municipal/Turismo owns its direct forms, contacts and physical access
  instructions;
- Agenda Guardamar should own delegated occurrence-specific ticket/invitation
  actions once the exact municipal->Agenda join is proven;
- Biblioteca owns a library activity only when its own detail page/action
  proves access;
- AM Guardamar must not create a second root for a municipal/Agenda occurrence
  without deterministic continuity.

Once a root exists, ownership remains stable unless an explicit reviewed
migration path is introduced later.

## State architecture result

The production requirements are naturally event-centric.

Do not extend the deployed v1 state as four parallel global collections.

Use one entry per lifecycle record containing:

- semantic option state;
- `audience_known`;
- optional Telegram root metadata;
- record-local sent triggers.

Keep exactly one global uncertain outbound reservation because the process
sends one operation at a time and ambiguous delivery must block automatic
continuation.

This is recorded in ADR 0092.

## Termux production-state probe results

The read-only probe completed successfully without source refreshes, network
requests, Telegram calls or state writes.

### Snapshot freshness and volume

At 16:59 Europe/Madrid on 2026-10-03:

- Municipal snapshot: fetched 10:10, 71 total facts, 44 current/future facts;
- Agenda Guardamar snapshot: fetched 10:10, 13 current/future occurrences;
- Biblioteca snapshot: fetched 05:11, one retained event;
- AM Guardamar snapshot: fetched 05:11, zero posts/events;
- FACV snapshot: observed 05:11, zero Guardamar events;
- Pesca CV snapshot: observed 05:11, two Guardamar competition rows;
- CONVEGA snapshot: observed 10:06, two route records.

The 10:10 Municipal/Agenda timestamps come from the existing later catalog
refresh path, while the normal source logs confirm pre-morning refreshes around
05:11 and 05:30.

This means the access runner can safely consume local source snapshots and does
not need to become a general refresh orchestrator. A later source refresh may
improve same-day freshness, but that is an existing collection concern.

### Deployed migration state

The ADR 0089 v1 state is tiny and migration-ready:

- version: 1;
- one baseline record;
- zero announced records;
- zero sent triggers;
- `uncertain=false`.

The single baseline is
`convega:post-42197:stage-21`, currently explicit `full` with
`last_explicit_status=full`.

Therefore ADR 0092's deployment precondition
`legacy uncertain == null` is satisfied on the measured production state.

The migration is still required to remain fail-closed at deployment time;
the probe is evidence, not permission to remove the runtime precondition.

### Municipal/Turismo

The current snapshot contains ten rows with some access-like fields, but no
current `session_source_key` family.

Important examples include:

- Todo Cultura activities with a contact but no proof that the contact is a
  current one-off reservation action;
- a Google Form registration for the same-day Hogwarts activity;
- municipal rows delegating guided-tour purchase to Agenda Guardamar
  `/espectaculo/` parent pages.

Therefore:

- Municipal/Turismo is ready for a narrow source projection only for explicit,
  reviewed access evidence;
- generic presence of `registration_contact` is not sufficient because
  routine CSJ rows expose the same durable contact;
- the current snapshot does not provide evidence for implementing a generic
  multi-session municipal family yet;
- source-proven session support remains in the model, but rollout must not
  fabricate options when no family is present.

### Agenda Guardamar

Production confirms 13 future ticket occurrences through 30 October.

Two recurring products each appear four times under the same
`/entradas/<id>/<slug>.html` path with occurrence-specific query parameters.

This proves:

- the existing flattened occurrence rows retain a useful source path identity;
- a parent product can have several future occurrences;
- current snapshot cardinality is small (observed maximum four occurrences per
  repeated ticket path).

But the snapshot does **not** retain:

- the parent detail-page identity as an explicit field;
- event image/poster metadata;
- a source-backed sale status separate from URL existence.

Therefore Agenda Guardamar is not ready for generic proactive ticket
publication merely because a ticket URL is present. Before enabling this source,
retain explicit parent identity and prove the URL/state contract for
not-yet-open/open/sold-out/closed behavior.

### Biblioteca

Production retained only one exhibition row, even though the public library
page exposes later activities beyond the current seven-day adapter horizon.

The retained row has a stable first-party detail URL and
`detail_loaded=true`, but no access action.

This confirms the horizon gap and means Biblioteca should remain gated from
event-access rollout until a bounded wider candidate read plus event-specific
reservation evidence is implemented.

### AM Guardamar

The current snapshot has zero posts/events.

No new production evidence closes the access contract. Keep AM Guardamar
disabled as an access owner until a real actionable post is observed.

### FACV

The current snapshot has zero Guardamar tournament rows.

The external first-party reconnaissance still proves that FACV articles can
carry registration methods, capacity and deadlines, but the deployed calendar
snapshot retains no detail/article identity. FACV access therefore requires a
small article/detail projection before rollout.

### Pesca CV

Production contains two future calendar rows:

- 17 October `MAR COSTA`;
- 23-29 November `Mar Costa Dúos`.

The current normalized rows contain only calendar facts
(title/date/place/organizer/level/source URL), with no convocatoria/detail URL
or registration fields.

Combined with the external 17 October convocatoria evidence, this gives a clear
implementation requirement: enrich only exact accepted competition rows with
their official convocatoria identity/access facts. Never infer registration
from the calendar row alone.

### CONVEGA

Production confirms the expected strong source contract:

- stable record ID `convega:post-42197:stage-21`;
- Guardamar relevance;
- explicit current `full`;
- `until_full=true`;
- stable source and landing URLs.

CONVEGA is ready to serve as the migration/reference adapter for the new
event-centric engine.

### Translation readiness

The current cache has 131 entries, but the probe found misses among future
Municipal and Agenda titles and for the current CONVEGA title.

This is not a reason to add runtime translation. It confirms the existing ADR
0091 rule: future access projections must feed the same pre-morning translation
preparation function so only actionable future candidates are prepared.

Do not require all 44 Municipal future rows to be translated. Only projected
event-access candidates need guaranteed presentation readiness.

### Cross-source overlap

No exact cross-source URL overlap was present in the current snapshots.

That does not invalidate ownership rules. It means current data provides no
evidence for a generic cross-source resolver.

Keep explicit ownership and deterministic exact joins only. The existing
Municipal `/espectaculo/` links and Agenda `/entradas/` occurrences show why
an exact source-specific delegation join is preferable to fuzzy event matching.

### Cardinality and bounds

Observed production maxima are small:

- municipal source-proven session-family size: 0 in the current snapshot;
- repeated Agenda ticket-path occurrences: 4;
- retained v1 lifecycle records: 1;
- v1 trigger count: 0.

These measurements support the existing one-file/event-centric design and
provide no justification for a database, queue or generic source registry.

They are not sufficient to treat `4` as a permanent product cap. Numeric
option/trigger limits should be conservative structural bounds derived from the
accepted source parsers during implementation, not from one day's observed
maximum.

### Schedule evidence

Source logs show:

- Municipal/Library/AM/FACV/Pesca normal refresh around 05:11;
- Agenda Guardamar normal refresh around 05:30;
- translation preparation at 06:00/06:30/07:00;
- ADR 0089 lifecycle runs at 12:47 and 13:47.

On the probe day both lifecycle runs completed `no_message`, consistent with
the only relevant CONVEGA record already being `full` and never announced.

No second generic event-access refresh is justified by this probe.

## Implementation gate after local probe

The architecture gate is now **open**, but source rollout remains explicitly
capability-gated.

Safe to implement now:

1. the ADR 0092 event-centric state migration and validator;
2. one-record planner / reserve -> send -> commit engine;
3. generic `EventAccessRecord` / `AccessOption` semantics;
4. CONVEGA as the first/reference projection;
5. source-batch freshness and explicit ownership plumbing;
6. future-access translation selection driven by the same pure projections.

Source adapters may be enabled only when their missing contract is closed:

- Municipal/Turismo: explicit access-evidence filtering; no generic contact
  rule and no unproven session grouping;
- Agenda Guardamar: retain parent identity and verify sale-state semantics;
- Biblioteca: wider bounded future candidate horizon plus reservation evidence;
- FACV: retain article/detail identity and action facts;
- Pesca CV: retain exact convocatoria identity/access facts;
- AM Guardamar: wait for a real actionable first-party sample.

Expected implementation shape:

```text
existing bounded source refreshes
        ↓
pure source-specific access projections
        ↓
AccessSourceBatch(source, observed_at, records)
        ↓
per-source freshness
        ↓
deterministic ownership suppression
        ↓
plan one EventAccessRecord
        ↓
event-centric state
        ↓
reserve one uncertain operation
        ↓
rich root OR strict reply
        ↓
commit only that record
```

No database, plugin framework, browser, continuous polling, generic commerce
engine or second Event model is justified.
