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

The FPCV access reader uses the existing 36-hour normalized-detail freshness
contract. Future observations and stale observations fail closed.

### Multi-source orchestration

The existing explicit local EventAccess loader now has two branches:

1. CONVEGA, with its existing same-day/90-minute access freshness;
2. FPCV normalized details, with its existing 36-hour enrichment freshness.

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

Temporary GitHub Actions validation on application commit
`2cea4ad9124941b9e0b3414f7ceecd646cbaccaa`:

- Python 3.12 compile: PASS;
- `git diff --check`: PASS;
- focused FPCV/Pesca/EventAccess/Sports suite: **146 tests PASS**;
- full repository `unittest discover`: **1741 tests PASS**.

The temporary workflow is not part of the intended final branch diff.

## Remaining production gates

Code activation and schedule changes are deliberately separated.

Before deploying this slice:

1. rehearse the exact final feature tree under production Termux Python in a
   detached worktree;
2. inspect current production `pesca_cv_details.json` read-only;
3. prove production state remains EventAccess v3 with no uncertain delivery;
4. verify current `main` has not moved without review.

After code deployment, run the existing Pesca CV source refresh once with
production-safe guards or wait for the normal 05:10 lifecycle. That refresh may
rewrite only the regenerable FPCV details snapshot to v2 and should prove
`source_id=43/26` before EventAccess is allowed to use it.

The shared 12:47/13:47 EventAccess schedule is intentionally unchanged in this
slice. Because the reviewed FPCV deadline is 12:00, a separate full-crontab and
neighboring-runtime production probe is required before moving the existing two
shared checkpoints earlier. Do not add a third FPCV-specific cron.
