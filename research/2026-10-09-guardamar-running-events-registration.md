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


## Milestone 5 — organizer-first and strict open-registration gate (2026-10-09)

**Operator decision:** do not publish the future event merely because it has been listed in a calendar. Registration announcement is allowed only if actual participant registration is evidenced as currently actionable. This is a proposed requirement for the running-source slice and must be reconciled with generic event-access semantics before code changes.

Source roles:
1. Organizer's *contemporaneous, event-specific* first-party announcement/instructions (SOC SPORT/Sportmadness Alicante for 2026 Cross; GRD Vega Baja for 2026 Media Maratón).
2. Organizer-delegated registration operator (ChipLevante or the exact linked platform): source of truth for the real entry form, current open/closed/full status and registration windows.
3. Ayuntamiento/Guardamar Turismo: discover and cross-check locality/date/organizers, but never use a calendar entry alone to assert open registration.
4. Aggregators: non-authoritative discovery only, never publication evidence.

**Evidence gate:**
- `open` only if event-specific official/delegated page explicitly states registration open **and** offers an actionable application/payment/registration flow; OR an organizer's dated explicit currently valid open-registration instruction gives a usable sign-up contact/process. For contact-only registration, distinguish explicit “inscribe by contacting X” instructions from a generic organizer email listed for inquiries. Generic email or unrelated website by itself is NOT registration proof.
- A registration link alone is not enough if the destination says closed, full, not yet open, historical edition or is inaccessible/ambiguous.
- A merely listed future event, pricing ladder, theoretical closing date, organizer contact listing, historic form, or `INSCRIPCIONES` navigation label is NOT evidence of present open status.
- A real online form should be verified at least through an event-specific available selection/application step, never submit participant data or initiate payment. If required browser/JS makes status inaccessible in bounded Termux requests, fail closed.
- Prove current date/time window, year, exact Guardamar occurrence, access action URL or explicit organizer-proven email/phone instruction, status and freshness; preserve attribution. `unknown` until demonstrated otherwise. Do not extrapolate next-year availability.
- Once rooted, status transitions or material corrections use shared v3 EventAccess and its strict deduplication/uncertain-delivery policy. No special running state machine.

**Evidence observed:** 2026-12-06 Cross card https://www.chiplevante.com/es/prueba/cross-urbano-guardamar-del-segura-998-2026 has distance/price/organizer contact and links to rules/social posts, but current page text **does not show a validated event-specific active registration form or confirmed-open inscription action**. Therefore **NO REGISTRATION-OPEN PUBLICATION YET**. Organizer shown SOC SPORT - SPORTMADNESS ALICANTE, `socsport2018@socsport.net` is only a generic contact unless an explicit sign-up instruction is found. The ChipLevante service docs https://www.chiplevante.com/es/gestioninscripciones separately distinguish calendar event listing from managing registrations, confirming why these cannot be conflated.

2026 half-marathon https://www.chiplevante.com/es/prueba/2026MMGUARDAMAR-1015-2026 identifies organizer GRUPO DE RECREACIÓN DEPORTIVA VEGA BAJA; the event's actual registration endpoint https://inscripciones.chiplevante.com/es/evento/media-maraton-10k-dama-de-guardamar-2026/inscripcion/selecciona-tarifa currently says “Inscripciones cerradas”, historical opening 2026-02-05 09:00 and closing 2026-04-05 23:59. Demonstrates a useful **browserless status contract**, but it must be validated live from Termux for future events. The public chip timing card may still show pricing after registration has closed.

**Next milestone:** bounded read-only production probe of current 2026 Cross entry flow and organizer's official posts; inspect links without guessing slugs; verify the real enrollment platform and whether it publishes an actionable HTML state. Check actual organizer registration contact instruction, not generic contacts. Then adapt only source-proven running events using existing local event + EventAccess pipeline; add focused false-positive regression tests for “calendar only”, “price only”, “generic organizer email only”, “closed signup page”, “form pending” and “explicit currently open sign-up process”. Preserve the existing planning/sports-today behavior distinction for events with no access: operator's strict no-publication rule needs a specific scope decision before routing (do not silently apply to all other sports).



## Milestone 6 — October 2026 coverage check (2026-10-09)

Question: Is there any Guardamar-hosted October 2026 road race, marathon, half-marathon, cross or other sporting occurrence beyond the already announced provincial fishing competition?

**Running result:** no Guardamar-hosted October running event was identified in the municipal October agenda, reviewed race listings, athletics/race provider searches and relevant organizer/calendar research available at this checkpoint. Nearby October runs in Torrevieja, Almoradí, La Marina or Elche must not be attributed to Guardamar. This is an **absence-of-evidence finding, not a proof that no future late announcement can appear**. The next specifically identified Guardamar cross is on 2026-12-06 and its active-registration gate remains unresolved; do not announce an October registration opening.

**Other sports:** the absence claim is false when extended to all sporting events:
- Official FPCV convocatoria https://federacionpescacv.com/convocatorias-clasificaciones-2026/ confirms the **2026-10-17** Provincial Alicante Mar-Costa Captura y suelta event at Guardamar's La Roqueta and Centro beaches (existing fishing feature; already announced by the operator).
- Official FFCV 2026/27 Segona FFCV, group 8 PDF https://ffcv.es/wp/wp-content/uploads/2026/08/Segona-FFCV-Grupo-8.pdf shows **Jornada 5 (2026-10-25)**, Guardamar Soccer C.D. "A" versus Sporting Saladar (home-listed). **This PDF only establishes the round/weekend and home designation; the exact game day, kickoff and physical venue are not confirmed by it.** Do not publish without live responsible-source venue/date/time validation. Its registration lifecycle is not the same as participant sign-up for mass races.
- Official municipality/tourism Rosario programme https://guardamarturismo.com/fiestas-de-la-virgen-del-rosario-de-guardamar-2026/ includes a petanque tournament on **2026-10-03**, already in the past as of this research.
- Official chess FACV calendar https://www.facv.org/appwebfacv/public/staff/torneos/calendario_oficial.php did not yield an October Guardamar championship in the reviewed 2026 rows.
- Official FPCV general club fishing calendar https://federacionpescacv.com/competiciones-de-nuestros-clubes/ lists October Guardamar `SOCIAL CLASIF.` club rows (10 and 31 October) that the existing reviewed filtering policy explicitly excludes as ordinary club qualifiers; their presence does not justify a broad new resident notification.

**Publication distinction:** no new confirmed-open **running registration** to announce today; this is not equivalent to “no more sports events to cover in October.” The already rooted fishing announcement should not be repeated absent a material lifecycle change; football can appear on Sports Today/planning only after the responsible fixture source confirms the city's physical venue and live schedule, not as an advance registration root.

**Remaining verification:** no Termux production state inspection was performed. No source-specific running adapter was implemented, no production side effect. Confirm live FFCV venue/kickoff and deployed source status in a separate fixture-source audit before claiming the football fixture is currently published by the bot.



## Milestone 7 — organizer-first broad source audit (2026-10-09)

Full findings and priority registry were recorded at
`research/2026-10-09-guardamar-sport-organizers-registration-audit.md` (same research branch).
This file is still the running/Cross-specific resume point. The other file is
the new broader sport-organizer resume point.

High-value discovery: Promochess, which partners with the local Dama chess club,
has **two specific future Guardamar registration products**:
- VII Torneo Abierto de Navidad, 2026-12-13:
  https://promochess.com/tienda/inscripcion-vii-torneo-navidad/
- VIII Open Esphouses, 5th circuit stage, 2027-04-18:
  https://promochess.com/tienda/etapa-5-guardamar-del-segura/

Both publicly show edition-matched signup, categories and add-to-cart; no
checkout/payment or Termux test was executed and no Telegram publication was
made. A stale `2025` deadline in Christmas 2026 event rules must not become
a bot trigger. Check for existing Telegram roots and source duplicate
ownership before any publication.

Cross 2026 still has no demonstrated active registration despite calendar +
prices; organizer SOC SPORT's linked Facebook/Instagram were inaccessible to
static web retrieval, and the ChipLevante `REGLAMENTO` link returned 404.
RFET tennis, FTTCV table tennis, athletics and triathlon were evaluated as
secondary candidate discovery sources. Do not mix `Guardamar de la Safor`
with Guardamar del Segura or publish sports belonging to another town.
