# Guardamar Municipal Source Map

## Question

Which official local publishers may later supply traffic notices, operational
updates, and same-day events for the Morning Digest?

## Status

This is working context supplied by the project owner on 2026-07-27. It is not
approval to implement every source. Exact official URLs, access methods,
freshness, attribution, payload stability, and failure behavior still require
source-by-source validation.

Current product contracts and ADRs take precedence where this note differs
from older source assumptions.

## Candidate source roles

### Telegram channel `@AlcaldeGuardamar`

Potential value:

- operational municipal announcements;
- same-day and emergency notices;
- schedule changes;
- festival-day notices;
- important event announcements.

Selection rules:

- use explicit facts useful to residents;
- ignore photo- or video-only posts unless reliable text contains the needed
  facts;
- do not turn the channel into a general news feed;
- do not paraphrase speculation.

Access constraint to validate: a Telegram bot does not automatically receive
posts from an arbitrary channel. Confirm the publisher's official status and
whether the bot can be added or another permitted lightweight access method
exists before approving this source.

### Policía Local Guardamar

Potential value:

- street closures;
- traffic and access changes;
- parking or movement restrictions;
- beach or public-safety notices.

Traffic inclusion requires all of:

1. an explicit official restriction;
2. the affected street or streets;
3. a time or validity window;
4. the stated reason.

Do not infer a closure from an event or parade route. If the notice lacks
concrete streets, time, or reason, omit the traffic section.

Further validation on 2026-07-27 identified the official page
`https://policiaguardamar.com/cortecallefiestas.html`. It explicitly states
that from 15 through 29 July the remaining approaches are closed and access to
Centro de Salud and the bus terminal is via C/ San Francisco. This one notice
is suitable for strict bounded HTML matching.

The linked `pdf/cortecalle_fiestas13.pdf` is historical and describes
different routing, so it must not be used as current data. The site still has
no general live traffic feed and the MVP still must not scrape Facebook.

### Cultura Guardamar

Potential value:

- concerts;
- theatre and cinema;
- exhibitions;
- castle and other official cultural events.

Use only official events relevant today with a clear date and time.

Validation on 2026-07-27 found a TLS hostname mismatch and placeholder/demo
posts on the current site. It is not suitable for the MVP.

### Biblimar

Potential value:

- library events;
- children's and family activities;
- workshops;
- library exhibitions.

This source is optional. Include only official, clearly time-bound items.

### AM Guardamar / music school

Potential value:

- concerts and recitals;
- school performances;
- official music-school events.

Use only clearly scheduled official events and suppress duplicates already
covered by Cultura Guardamar.

### Agenda Guardamar

Potential value:

- official calendar and ticketed events;
- larger public and festival events.

Treat this as a secondary official event source, not a replacement for
operational municipal notices.

Validation on 2026-07-27 found bounded HTML programming pages and event detail
pages containing Schema.org title and start-time fields. The site identifies
the Ayuntamiento as operator. This source is approved in ADR 0007 for at most
two events occurring today.

### Junta Central Moros y Cristianos

Potential value:

- official Moros y Cristianos program;
- festival schedule and parade routes.

This is seasonal and eligible only while the festival is active. A route alone
does not prove a traffic restriction; traffic still requires an explicit
police or municipal closure notice.

## Sources excluded from the MVP digest

- SPORTTIA;
- health-centre news as a daily source;
- community or commercial news;
- unofficial aggregators;
- publishers that are not responsible official authorities.

## Cross-source event policy

- Include only events relevant today or immediately actionable today.
- Require an explicit date and time.
- Keep a small fixed maximum count.
- Deduplicate the same event across official sources.
- Prefer the source directly responsible for the event.
- Omit ambiguous, stale, promotional, or media-only items.

## Stable digest placement

Municipal data may populate only the existing optional sections:

1. `⚠️ Внимание`
2. `🚧 Движение`
3. `🎉 Сегодня`

It must not change the fixed section order, add a source footer, expand the
message beyond one phone screen, or weaken the deterministic no-AI policy.

## Current contracts that supersede older wording

- The sea row is mandatory; unavailable values render as `—`.
- SafeBeach supplies only an active `Platja Centre / Babilònia` flag and,
  when available, its water temperature.
- AEMET Centro / La Roqueta may supply forecast water temperature as a
  fallback.
- AEMET never supplies or implies a beach flag.
- Weather warnings remain exclusively AEMET CAP data.

See ADR 0004 for the canonical layout and ADR 0006 for the sea-temperature
fallback.

## Recommended validation order

1. Policía Local Guardamar, because explicit closures have high same-day value.
2. `@AlcaldeGuardamar`, if official status and lightweight access are proven.
3. Cultura Guardamar and Agenda Guardamar for a small events slice.
4. Biblimar and AM Guardamar only to fill demonstrated event gaps.
5. Junta Central only during the active festival period.

For each candidate, record the exact official URL, update frequency, structured
access options, freshness marker, sample payload, duplication behavior,
runtime cost, and safe failure rule before implementation.
