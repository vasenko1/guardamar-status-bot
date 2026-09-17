# Recurring activities and language source audit — 2026-09-17

Status: implementation planning / source validation. No production source contract is approved by this note alone.

This note consolidates the 17 September audit of recurring non-sport activities and language courses for the linked Guardamar guide. The goal is not to collect every possible class in town; it is to identify resident-useful items with evidence strong enough for a durable card and, where possible, a source cheap and deterministic enough for the Termux bot.

## Product decisions from the audit

### Add in the next implementation slice

1. `♟️ Шахматы`
   - regular school for children and adults;
   - Tuesday/Thursday, school activity within the published 16:00–20:00 range; exact group time is assigned by level;
   - beginner through advanced levels;
   - venue: Escuela de Música;
   - current club source: `https://ajedrezdamadeguardamar.com/cuotas/`;
   - PROMOCHESS contact is the preferred enrollment contact when current contact facts are verified.

2. `🎨 Творческие мастерские`
   - one aggregate card, not five index rows;
   - painting, ceramics, patchwork, pattern cutting/dressmaking, yarn/thread workshops;
   - current September publication says enrollment 21–25 September, 09:00–20:00, Casa de Cultura, limited places;
   - source: `https://guardamarturismo.com/agenda-cultural/`;
   - the official source currently labels the block `TALLERES 2025/2026` despite publishing the September 2026 enrollment dates. Do not silently rewrite the season label to 2026/27 unless the source does so.

3. `🤝 Муниципальные занятия и мастерские`
   - one aggregate card for the current `Programa de Dinamización Social 2026/2027`;
   - official campaign page: `https://www.guardamardelsegura.es/2026/09/07/programa-dinamizacion-social-2026-2027/`;
   - official form: `https://docs.google.com/forms/d/e/1FAIpQLSdG1kkxJhCHLSd-aZ7j55MFybZMfGHS6FytHgVrOTPo_66Oiw/viewform`;
   - original registration period: 9–16 September 2026;
   - the form explicitly says enrollment continues after the main period while vacancies remain;
   - Guardamar residents have priority; non-residents may participate only if vacancies remain;
   - current groups published by the form:
     - Movimiento Consciente — Mon/Wed 11:15–12:15 or 12:15–13:15;
     - Uso del móvil — Tue/Thu 09:30–10:30 or 10:30–11:30, from 10 November;
     - Arte Reciclado Creativo — Mon/Wed 16:30–18:30;
     - Pintura Textil — Fri 16:30–18:30;
     - Senderismo para Mayores — Mon/Wed 16:00–17:30 or 17:30–19:00;
     - Memoria para Mayores — Tue/Thu 16:30–18:00 or 18:00–19:30;
     - Informática para Mayores — Mon/Wed 17:00–18:00 or 18:00–19:00;
     - Escuela de Emociones — Wed 09:30–11:00, 14 Oct–16 Dec 2026;
   - admission is communicated by phone/email; unsuccessful applicants remain on a waiting list; the municipality may create extra groups when demand/resources permit.

4. `✍️ Литературное творчество`
   - regular Tertulia Literaria de Guardamar;
   - every Tuesday 11:00–13:00 in the Municipal Library auditorium;
   - official static source: `https://www.bibliotecaspublicas.es/guardamardelsegura/actividades-programas/Tertulia-Literaria-de-Guardamar.html`;
   - this is a durable recurring group, not an event-calendar item.

### Language item that is useful now but should be treated as reviewed seasonal data

5. `🇪🇸 Испанский · EPA`
   - current 2026/27 operator-provided municipal flyer confirms A1, A2, B1 and B1.2 for adults 18+;
   - enrollment in the flyer was 2–11 September 2026, in person at Casa de Cultura, 09:00–13:00;
   - requested documents: copy of DNI/NIE or valid passport, passport-size photo and completed enrollment form;
   - the flyer says A2 certification requires passing the course and 85% attendance; do **not** describe this as DELE-equivalent without a separate official basis;
   - official long-lived EPA page: `https://www.guardamardelsegura.es/2024/07/24/epa-escuela-de-personas-adultas-curso-2024-2025/` currently displays `CURSO 2026 / 2027` and links 2026/27 forms;
   - current timetable, current post-deadline vacancy status and current price/free status were not found in a stable machine-readable official source.

This card is therefore suitable only as a reviewed current-season snapshot until a stable current-year machine source is proven. Do not derive current facts from the 2025/26 timetable.

## Do not add yet

- `Club de lectura` — the library confirms the program exists, but a current 2026/27 schedule/enrollment contract has not been found.
- EOI Guardamar language cards — there is an official Guardamar section under EOI Torrevieja, but current Guardamar-specific 2026/27 language/group/timetable evidence must be obtained before publication. Do not substitute Torrevieja-only offerings.
- EPA English/Valencian — previous-year schedules confirm these directions existed, but the 2025/26 hours must not be carried forward as 2026/27 facts. Wait for current-year evidence.
- Cruz Roja Spanish — recurring Spanish-for-foreigners activity is supported by 2026 evidence, but no first-party current timetable/enrollment surface was found. Do not automate from third-party/community pages.
- PANGEA / INTEGRA Spanish — treat as campaign-driven programs. Add only when a current Guardamar campaign with dates/enrollment is published.
- private schools/academies — keep outside this municipal/public-source rollout unless a separate product decision opens the guide to commercial providers.
- museums — no regular open-enrollment groups found.
- separate athletics card — current municipal athletics content overlaps the already implemented `DEPORTE +` activity family.

## Source suitability and cost

| Item | Source strategy | Network cost | Automation quality | Decision |
| --- | --- | ---: | --- | --- |
| Dinamización Social | Ayuntamiento WordPress feed/list discovers campaign; fetch detail on change; fetch linked Google Form on change | ~1 tiny discovery GET/day + detail only on change | High: official text + form is text-readable, no OCR/LLM required | Automate |
| Casa de Cultura creative workshops | Reuse already-fetched `guardamarturismo.com/agenda-cultural/` text in `municipal_agenda.py` | **0 new GET/day** if normalized in existing municipal sync | High for published enrollment facts; title has stale season label | Automate narrowly |
| Chess | Official club page | 0 daily GETs | Good durable facts, but changes are seasonal/rare | Static reviewed card; revalidate seasonally |
| Tertulia Literaria | Official Biblioteca static page | 0 daily GETs | Very good durable schedule | Static reviewed card; revalidate seasonally |
| EPA Spanish | Mutable official EPA page + current flyer/manual evidence | preferably 0 daily GETs until contract is proven | Medium: official page is reused across years and important details may be image-only | Reviewed seasonal card first |
| EPA English/Valencian | current machine source not yet found | — | Insufficient current-year evidence | Defer |
| EOI Guardamar | current local section timetable not yet found | — | Insufficient for exact local card | Defer |
| Cruz Roja Spanish | no current first-party timetable surface found | — | Poor for deterministic polling | Defer dynamic automation |
| PANGEA/INTEGRA | municipal campaign publications when present | piggyback municipal discovery | Good only when explicit current campaign exists | Future classifier |

## Recommended source contracts

### 1. Ayuntamiento municipal campaign discovery

The municipality is WordPress-based and exposes `/feed/`. Production must still verify the exact final URL/content type/size/encoding from the Termux device before coding.

Implementation shape:

- one bounded discovery request during the existing 16:30 guide sync;
- explicit classifier for `PROGRAMA DINAMIZACIÓN SOCIAL` only in the first slice;
- on a new or changed matching campaign, fetch its detail page once;
- follow only the explicit registration/detail link allowed by that campaign contract;
- normalize the relevant facts into `state/guide.json` (or an equally small existing guide snapshot), not raw HTML;
- preserve same-season last-good facts on source failure;
- do not poll the Google Form every day after the accepted campaign/form fingerprint is unchanged;
- do not build a general municipal CMS framework.

Later, the same discovery surface may support explicit classifiers for EPA notices, Dale Vida a los Años, holiday programs, PANGEA/INTEGRA campaigns, etc.; each needs its own evidence contract before public output.

### 2. Casa de Cultura workshops from the existing Turismo fetch

`municipal_agenda.py` already downloads `https://guardamarturismo.com/agenda-cultural/` as a bounded official municipal source. Do not add a second daily fetch solely for workshops.

Preferred implementation:

- add a narrow deterministic extractor for the `TALLERES` block to `municipal_agenda.py` or a small helper owned by that source;
- store only a compact normalized workshop snapshot alongside the accepted municipal catalog/state;
- let the 16:30 guide sync consume that local accepted snapshot;
- only publish facts explicitly present: workshop names, registration dates/times, place, limited-place wording;
- if schedule/price/course-season are absent, omit them;
- preserve the literal source season label internally when needed for diagnostics; do not invent a corrected season.

This gives the guide a current program card with no additional network cost.

### 3. Static/slow sources

Chess and Tertulia do not justify daily polling. Implement them as reviewed durable guide facts with their official source URLs and a clearly documented seasonal/manual revalidation path. If a future need for automatic season turnover appears, add one narrow low-frequency check only after measuring the value; do not add a daemon or daily request now.

### 4. EPA/language sources

Do not force automation where the publisher does not provide clean current text.

For the first language slice:

- keep current EPA Spanish facts as a reviewed 2026/27 snapshot;
- omit unknown current schedule, price and vacancy status;
- do not infer `free`, `paid`, `DELE`, or current English/Valencian hours;
- continue monitoring the municipal campaign discovery surface for a future explicit language/EPA post;
- only make English, Valencian, EOI or Cruz Roja source-managed after current first-party evidence is found.

## Information architecture

Keep the existing single `🎓 Занятия и секции` index and visual grouping. Do not introduce a new Telegram navigation layer merely because more activities exist.

Suggested grouping after this slice:

- existing `🏃 Спорт и движение`;
- existing `🎵 Музыка`;
- a compact `🎨 Творчество и развитие` or `🤝 Другие занятия` visual block containing creative workshops, municipal workshops, chess and literary creation where scanning remains clear;
- add a `🌍 Языки` visual heading only when there are enough **current** language cards to justify it. One reviewed Spanish card alone does not require a new hierarchy.

A visual heading is presentation only; it does not create a category message/state layer.

## Notifications

Do not combine new source parsing and new public notification delivery in one first deploy unless needed for an already-open registration window.

Recommended sequence:

1. source normalization + durable guide cards;
2. verify production reconciliation/recovery;
3. then add a small program-notification runner, reusing the proven sports notification invariants (silent baseline, semantic changes only, `uncertain` before send, batching, no source request in notification process).

Material future program notifications may include a new current program, registration opening/extension/deadline, changed schedule/venue/audience, newly explicit `until full` wording or explicit cancellation. Raw HTML changes, source failure or item disappearance alone are non-events.

Because Dinamización currently says registration continues while vacancies remain, do not translate that into `places available now` unless the source explicitly confirms current capacity. The correct wording is that registration **may continue while vacancies remain**.

## Implementation order

### Phase A — production source probe (no public side effects)

Before code changes, verify from the actual Termux production network:

- Ayuntamiento `/feed/` final URL, content type, response size and redirects;
- Dinamización detail page final URL/type/size;
- Google Form final URL/type/size and whether the expected text is visible in a normal GET;
- existing Turismo agenda page final URL/type/size;
- optionally inspect local accepted municipal state/logs to see whether the `TALLERES` text is currently retained or discarded after event normalization.

### Phase B — static cards

Add Chess and Tertulia with tests for rendering, internal/up navigation and recovery. No new source fetches or cron rows.

### Phase C — creative workshop card

Extend the existing municipal agenda normalization to emit one small `TALLERES` snapshot and let the guide create/reconcile one aggregate card. No new daily request.

### Phase D — Dinamización Social adapter

Add a small source-specific municipal-program module. Keep `guide.py` orchestration-only. Use one daily discovery request and detail/form only on change. Add deterministic parser/state/recovery tests.

### Phase E — EPA Spanish reviewed card

Add only after the exact resident-facing wording and storage location for manually reviewed seasonal facts are agreed. No OCR/vision runtime dependency. Current flyer facts can seed 2026/27; unknown fields remain omitted.

### Phase F — program change notifications

Only after B–E cards are stable. Copy invariants, not code architecture, from sports notifications. Do not add a new cron if the existing 16:30 guide sync can run the notification step immediately after reconciliation.

### Phase G — language expansion

Research/implement one by one when current official evidence is available:

- EPA English 2026/27;
- EPA Valencian 2026/27;
- local EOI Guardamar current language/level/timetable;
- Cruz Roja Spanish current local groups/enrollment;
- current PANGEA/INTEGRA campaigns.

## Required production probe before coding

A manual read-only probe from the production device is useful and preferable to guessing from desktop/web behavior. Record only status/final URL/content type/bytes/time and relevant response headers; do not send credentials or modify state.

After that probe, the first implementation should remain small: static Chess/Tertulia, zero-extra-GET creative workshops, then one-source Dinamización. This ordering delivers useful cards quickly while keeping the dynamic parser work evidence-driven and cheap.
