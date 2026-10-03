# Event-access production reconnaissance and event-centric state review

## Status

Started 2026-10-03.

This research combines:

1. a live read-only first-party source reconnaissance performed against the
   current production source set; and
2. a pending read-only Termux state probe needed for facts that cannot be
   established from public pages alone.

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

## Still required from the Termux production-state probe

Public source reconnaissance cannot establish all runtime facts. The production
device must be inspected read-only for:

1. actual snapshot timestamps for Municipal, Agenda, Library, AM, FACV,
   Pesca CV and CONVEGA;
2. real current/future record counts;
3. stable source IDs already retained in each snapshot;
4. municipal `session_source_key` families and current action URLs;
5. Agenda Guardamar session/ticket rows and whether parent identity is absent;
6. Library detail URLs and detail-enrichment status for future rows;
7. FACV/Pesca current row identity and any retained detail URL;
8. AM post IDs with more than one extracted occurrence;
9. translation-cache coverage for future actionable candidates;
10. exact cross-source duplicate/action URLs in the current state;
11. maximum options per plausible root in the current snapshots;
12. current v1 event-registration state size, trigger count and
    `uncertain == null` migration precondition;
13. source log refresh times relative to 12:47.

No source refresh, Telegram send, state write, migration or cron change is
required for this probe.

## Implementation gate after local probe

Multi-source runtime implementation may begin only when the local probe closes
these remaining identity/volume questions.

Expected implementation shape after that probe:

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
