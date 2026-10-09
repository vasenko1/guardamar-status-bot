# Guardamar running races / registration coverage — 2026-10-09

## Status / resume point

**OPEN RESEARCH — source gap confirmed, no application code changed, no production deployment.**
Research branch: `research/guardamar-running-events-2026-10-09`.
Consult this document first when continuing in another chat. Findings are from repository main and public web observed on 2026-10-09; production snapshots and registration endpoint have **not** been tested.

## Question

Do we reliably capture marathons, half-marathons, city cross races, road races, and their registration lifecycle when the competition physically takes place in Guardamar del Segura?

## Milestone 1 — repository instructions and architecture read (completed)

Read `AGENTS.md` first, then required KB `00_Project_Overview.md` through `04_Runtime_Constraints.md`.
Also reviewed `research/2026-09-17-guardamar-sports-event-sources.md`, `research/2026-10-05-sports-event-implementation-plan.md`, `research/2026-10-05-sports-event-publication-architecture-review.md`, `adr/0100-dedicated-sports-event-presentation.md`, and `research/README.md`.
Relevant code inspected: `src/telegrambot/event_access.py` (generic EventAccessRecord/AccessOption v3), `src/telegrambot/sports_today.py`, `src/telegrambot/sports_presentation.py`.

Contract: one source-specific lightweight adapter into normalized Event plus optional source-owned EventAccessRecord. Reuse generic access state, event-planning pipeline, Sports Today, existing one-shot source-refresh / event-access timing. No browser, daemon, per-sport cron, speculative status, global keyword classifier or new sport registration engine. Physical locality must be proven.

## Milestone 2 — existing source coverage (completed)

2026-09-17 research explicitly deferred ChipLevante/ChampionChip: technically usable server-rendered race calendar and detail pages, but **no future Guardamar event then found**. FACV (chess) and FPCV (fishing) were implemented; a dedicated running adapter is **not** evidenced in the current repository tree (`src/telegrambot/` includes `event_access.py`, `convega.py`, `sports_today.py` but no running/ChipLevante module). Existing municipal/Turismo event ingestion could incidentally discover races, but cannot be treated as proven complete registration monitoring. No read of production live state has been performed.

2026-10-05 architecture review specifically lists Turismo/mass participation sport as a subsequent source slice, not completed by general Sports Today. Generic access v3 supports `registration`, multiple options, open/full/closed, boundaries and source-backed corrections; this does not provide data until an adapter projects it.

## Milestone 3 — public first-party race sources (completed)

1. **ChampionChip Levante calendar**, event registration/timing platform: https://www.chiplevante.com/ . On 2026-10-09 its public calendar links a genuine **future** Guardamar event.
2. **XXIII CROSS URBANO DE GUARDAMAR 2026**: https://www.chiplevante.com/es/prueba/cross-urbano-guardamar-del-segura-998-2026 . Organizer is listed as SOC SPORT — SPORTMADNESS ALICANTE. Source specifies Sunday **2026-12-06**, city Guardamar, adult cross **7.5 km at 18:30** and children's races **16:30**. Adult entries cap **1200**, children **600**. Fees adult **EUR 12 through 2026-11-22**, **EUR 15 through 2026-11-29 or registrations end**; children **EUR 3 through 2026-11-29 or end**; processing/bank fees additional. These are **advertised fee windows, not proof of current open registration**. Public page as retrieved did not visibly establish a current actionable registration URL or explicit open/full status. Do not publish registration-open solely from prices/date.
3. **Guardamar Turismo**, official town tourism authority: https://guardamarturismo.com/en/guardamar-half-marathon-2026/ ; its 2026 half-marathon article describes an April 12 race, 21.097 km and 10.5 km, stated time limits and sold-out access at article time. The dated event is past; do **not** assume a 2027 recurrence.
4. **2026 Guardamar half marathon ChipLevante event page**, historical example: https://www.chiplevante.com/es/prueba/2026MMGUARDAMAR-1015-2026 . Demonstrates multi-distance / changing fee windows; past event, no future registration alert.
5. Third-party race aggregators give **conflicting dates** (some show 2026-12-05 for Cross). They are neither authoritative nor eligible for publication; the actual platform's event page states **2026-12-06**. Resolve any future municipal/platform disagreement against responsible organizer's contemporaneous authoritative notice, not a guessed date.

## Current assessment

**Gap confirmed**: general sports publication and access infrastructure exists, but race-specific discovery and confirmed access-status projection are not enabled. A future high-value race is now visible on the previously deferred platform, so its admission gate should be reconsidered.

Do not claim the Dec 6 race was omitted by the production bot without checking accepted production snapshots, nor claim registration currently open without observing an official actionable page/status.

## Milestone 4 — remaining source and runtime gates (TODO)

- Check official organizer SOC SPORT / Sportmadness source and Guardamar Turismo/Ayuntamiento for the exact 2026 Cross programme, approved participant access link, registration **opening** timestamp, current status, closing timestamp (or until-full semantics), any cancellation/postponement and event-specific official poster.
- Establish whether ChipLevante public event calendar/detail HTML is deterministically retrievable without JS, cookies or authentication from the actual Termux production device. One **read-only bounded source probe**, capturing HTTP code, MIME, bytes, elapsed time, redirects, HTML identity and action endpoints; protect production secrets, state, git HEAD and live services.
- Check if **inscripciones.chiplevante.com** has publicly accessible per-event status/registration link; do not assume links or infer `open` from fee text. If status is only in JS/private flow, fail closed and design a minimal source-supported fallback or delegate to explicit organizer source.
- Audit existing municipal/AM Guardamar/Turismo event source snapshots and registration source projection for same event and prevent duplicate occurrence with deterministic event-specific identity. Distinguish organizer/timing platform authority for sign-up from municipality authority for street closures.
- Evaluate other official timing operators and athletics authority (FACV athletics vs chess FACV; relevant Federación de Atletismo CV) only if concrete Guardamar coverage gaps remain. Avoid platform-wide crawling or trusting generic event aggregators.
- Decide whether race registration notice should support distinct adult/child `AccessOption` records only if independently actionable; keep labelled 7.5 km / child categories, correct start times and deadlines; never manufacture 21K/10K for the cross.
- Confirm registration lifecycle timing (shared 10:47/11:47 after latest FPCV slice, verify deployment) and what to do if publication begins after registration was already open (first-known-open root vs opening-today claim).
- Implement only after source proof and operator architecture review, then focused tests + full suite + production-safe preview and deploy gate per AGENTS.md.

## Recommendation

Approve a narrow **ChipLevante Guardamar running source investigation**, not an immediate production publish/adapter. It is now justified by the observed 2026-12-06 Cross. First prove registration status and a reliable participant action URL and investigate municipal overlap. No separate marathon subsystem or cron. Preserve this research file as the resumable checkpoint; record validated contracts and test results here at each milestone.
