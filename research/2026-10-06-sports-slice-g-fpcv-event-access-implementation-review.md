# Sports Slice G — FPCV EventAccess implementation review

Date: 2026-10-06
Branch: `feat/fpcv-event-access-main`
Base: `946353651fd858bf69ae54b0ff0be727aed2336f`

## Scope

This slice enables FPCV as the second source in the existing EventAccess
lifecycle. It does not add a second sports subsystem, source poll, scheduler,
database, queue, provider registry or persistent access state.

The source network/parser remains the existing 05:10 Pesca CV lifecycle. The
12:47/13:47 EventAccess runner reads only normalized local snapshots.

## Reviewed source contract

Responsible source:

- FPCV annual convocatoria index:
  `https://federacionpescacv.com/convocatorias-clasificaciones-2026/`
- reviewed exact Guardamar convocatoria:
  `https://federacionpescacv.com/wp-content/uploads/2026/09/bases-prov-mar-costa-captura-y-suelta-2026.pdf`

The reviewed 17 October 2026 document proves:

- Campeonato Provincial de Alicante;
- Mar-Costa / qualification context;
- Guardamar beach venue;
- registration through clubs;
- deadline 13 October at 12:00;
- participant amount €20;
- exact programme already normalized by Sports Slice C;
- source-assigned document number `43/26`.

The source-assigned number is the only reviewed identity fact suitable for a
long-lived EventAccess root. Date, venue, URL, date-based join key and content
hash are mutable evidence and therefore are not lifecycle identity.

## Implementation

### Existing FPCV observation

`fishing_enrichment.parse_fpcv_convocatoria_text()` now extracts the exact
convocatoria number while it is already processing the bounded text-layer PDF.
The year suffix must match the event year.

`state/pesca_cv_details.json` is explicitly evolved from version 1 to version
2. New code accepts v1 for ordinary event presentation, but a v1 record without
the source-assigned identity cannot create proactive access. The next ordinary
successful source refresh re-extracts an unchanged legacy document once and
writes the identity-bearing v2 snapshot.

No EventAccess state migration is needed.

### EventAccess projection

The local FPCV projection uses:

- `record_id = fpcv:convocatoria:43-26`;
- source `fpcv`;
- access kind `registration`;
- one `club-registration` option;
- source-proven deadline;
- source-proven place and schedule note;
- explicit scheduled/cancelled occurrence state;
- club-mediated action wording with no invented public registration URL.

The €20 amount remains `Взнос участника` presentation detail. It is not
mapped to spectator ticket pricing.

Ordinary fishing enrichment keeps its existing 36-hour horizon. Proactive FPCV
EventAccess is stricter: the identity-bearing observation must be from the same
Europe/Madrid local date and must not be in the future. Yesterday's last-good
details may still enrich an event but cannot assert current access state.

### Multi-source orchestration

The existing explicit local EventAccess loader now has two branches:

1. CONVEGA, with its existing same-day/90-minute access freshness;
2. FPCV normalized details, with same-Europe/Madrid-day access freshness over
   the existing daily 05:10 observation.

A stale source is omitted independently. Records are sorted deterministically
by event date, source and record ID. Duplicate IDs across sources fail closed.
The single global uncertain-delivery reservation remains unchanged.

The EventAccess runner still performs no source HTTP and no PDF extraction.

## Rollback properties

`state/pesca_cv_events.json` is untouched.

Before the first v2 details refresh, the new code safely reads the old v1
details but withholds FPCV access until stable identity exists.

After v2 details has been written, an immediate rollback to the previous strict
v1 details reader would ignore only FPCV enrichment until that older 05:10
source refresh reconstructs its own compatible details file. The base fishing
calendar remains available. EventAccess v3 lifecycle state is unaffected.

After any confirmed EventAccess root/reply, the existing v3 lifecycle rollback
boundary from ADR 0092 still applies.

## Automated validation

The application changes first passed their feature-branch gate, then were
rebuilt onto the moving production branch and revalidated each time `main`
advanced independently. The latest gate has
`main@3b04925ce4bf5c026f1245ad960e74f48e9a55a3` as an ancestor. The later
main commits touch Hidraqua and SafeBeach research only; they do not modify an
FPCV/EventAccess application file.

Production read-only probing then exposed one real PDF-layout issue:
Termux `pdftotext -layout` renders the first-page header as
`Número ... francis@federacionpescacv.com ... 43/26`, so a regex requiring
the number immediately after `Número` rejected the unchanged source facts.
The parser was narrowed to one bounded 120-character post-marker window and
requires exactly one `N/YY` token inside that window. A second token remains
ambiguous and fails closed. No other PDF semantic check was relaxed.

After that live-layout fix, the complete gate was repeated on workflow commit
`569c8f0b206368bad9c0b518bf8250fbd2d0becc`:

- Python 3.12 compile: PASS;
- `git diff --check 3b04925... HEAD`: PASS;
- focused FPCV/Pesca/EventAccess/Sports suite: **148 tests PASS**;
- full repository `unittest discover`: **1745 tests PASS**.

The temporary validation workflow was removed after the successful run; no
application or test file changed afterwards.

## Production source and schedule gate

The final production read-only probe on 2026-10-06 passed all remaining source
and timing gates:

- exact reviewed PR passed 148 focused tests under production Termux Python;
- the live official PDF parsed successfully after the bounded layout fix;
- temp-only refresh upgraded FPCV details v1 -> v2 and recovered
  `source_id=43/26`;
- the projected lifecycle identity is
  `fpcv:convocatoria:43-26`;
- same-Europe/Madrid-day access freshness accepted the fresh live observation;
- preview produced the expected open-registration root and no Telegram send;
- every production state/source hash remained unchanged.

The live crontab/runtime inventory also closes the checkpoint-timing gate. The
SafeBeach 10:10-10:40 edit window finishes before 10:47; resident-news runs at
11:11; operational monitoring runs at 10:51/11:51 and earthquake checks at
10:55/11:55. EventAccess itself completed in under one second in the observed
12:47/13:47 runs, while the CONVEGA sync took only a few seconds.

Therefore the two existing shared EventAccess rows move together from
12:47/13:47 to 10:47/11:47. This gives 73 and 13 minutes of lead time before a
reviewed 12:00 deadline, preserves the existing one-hour primary/recovery
spacing and keeps the second run inside CONVEGA's <=90-minute freshness window
when the first refresh succeeds. No third FPCV-specific cron is added.

The only remaining deployment gate is to verify current `main`/PR SHA,
re-run the final changed-file/test guard and install the reviewed managed cron
block atomically with deployment.

After code deployment, run the existing Pesca CV source refresh once with
production-safe guards or wait for the normal 05:10 lifecycle. That refresh may
rewrite only the regenerable FPCV details snapshot to v2 and should prove
`source_id=43/26` before EventAccess is allowed to use it.

The shared 12:47/13:47 EventAccess schedule is intentionally unchanged in this
slice. Because the reviewed FPCV deadline is 12:00, a separate full-crontab and
neighboring-runtime production probe is required before moving the existing two
shared checkpoints earlier. Do not add a third FPCV-specific cron.
