# Supermarket opening-hours source audit — 2026-10-07

## Scope

This investigation evaluates a narrow resident-facing supermarket-closure
feature for **Guardamar del Segura only**.

Physical stores in scope:

1. Mercadona — Av. del Mediterrani / Avinguda del Mediterrani, Guardamar;
2. masymas — Av. del Puerto, Guardamar;
3. DIA — CL La Redonda, 40, Guardamar, official store ID `36111`.

San Fulgencio is deliberately **out of scope**. It is a separate municipality,
and the feature should remain a Guardamar city-information feature rather than
grow into nearby-store recommendations.

The user-facing product is closure-first:

- announce a non-routine closure only when the exact Guardamar store is
  first-party-confirmed closed on a date on which it would normally be open;
- announce a verified seasonal change when the store's recurring Sunday regime
  changes;
- do not announce routine weekly days off;
- do not announce shortened opening hours when the store remains open;
- group stores when the same date affects more than one;
- provide a beginning-of-week heads-up, a day-before reminder, and a same-day
  reminder without creating duplicate messages for the same run;
- never infer store state from a legal holiday/opening calendar alone.

No production implementation is approved by this file. Source contracts must be
proved on the production Termux TLS/network stack first.

## Existing project facts that should be reused

The repository already contains a manually reviewed annual Guardamar holiday
calendar in `src/telegrambot/holidays.py`.

For 2026 it already knows, among other dates:

- 7 October — local Virgen del Rosario holiday;
- 9 October — Comunitat Valenciana holiday;
- 12 October — Spain national holiday.

Therefore the supermarket workflow must **not add another daily/weekly network
request merely to re-fetch public-holiday dates**. The existing reviewed local
calendar may be used as explanatory/candidate context.

Even that calendar is not an authority for store state. It may explain that a
date is a holiday, but the factual claim "Mercadona/DIA/masymas is closed" must
come from the retailer's own exact-store schedule.

A closure and a holiday occurring on the same date do not, by themselves, prove
causation. Unless the retailer explicitly says so, resident-facing copy should
prefer:

"Сегодня местный праздник ...; по опубликованному графику магазин закрыт."

over:

"Магазин закрыт из-за праздника."

## Exact physical stores

### Mercadona — Guardamar del Segura

Retailer: Mercadona.

Official store-locator surface:
https://info.mercadona.es/es/supermercados

The project already has a healthy first-party Mercadona JSON product API under
`tienda.mercadona.es/api/`, but that API is warehouse/product oriented and
cannot be treated as evidence of physical-store hours.

The store locator itself must be probed. Do not assume an undocumented query
parameter such as `?s=03140` is the store-search contract until the locator
HTML/JavaScript proves it.

### masymas — Guardamar del Segura

Retailer: Juan Fornés / masymas.

Official locator:
https://www.masymas.com/localizadordetiendas/localizador.php

A reviewed official control endpoint exists:

`https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=13`

It returns a compact server-side store detail record including normal
`Horario`. ID 13 is Alcora, not Guardamar; it proves the route shape only.
The Guardamar ID must be discovered from the official locator contract rather
than brute-forced.

The official FAQ says opening hours on bridges and public holidays depend on
the locality and dates and advises customers to call. That is a warning that
the ordinary locator timetable may be **normal hours only**. If so, it is not
enough by itself for automatic holiday-closure publication.

Official FAQ:
https://www.masymas.com/es/atencion-al-cliente/preguntas-frecuentes.html

The project also knows a separate first-party ecommerce JSON API at
`tienda.masymas.com/api/rest/V1.0/` for exact products. That proves the
retailer has structured public interfaces, but no store-hours route may be
assumed from the product API.

### DIA — Guardamar del Segura

Official store ID: `36111`.

Official stable path:
https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111

The first-party page and provincial locator reliably expose the exact store
identity and current leaflet period. The crawler-visible SSR text does not
currently expose opening hours. A read-only probe must inspect embedded
Next.js data and the first-party route bundle to discover whether schedule data
comes from a compact JSON/API request.

The project already has a reviewed plain-HTTP browser-navigation header profile
for exact DIA product pages. That is evidence that a browser runtime is not
automatically needed; it is not permission to reuse product-page assumptions
for store hours without a separate contract.

## Source ranking

### Tier A — preferred production source

A first-party retailer JSON/API/AJAX response for the exact physical store that
contains date-aware hours.

Ideal contract fields include some combination of:

- stable physical-store ID;
- exact address/municipality;
- regular opening hours;
- date-specific special/holiday hours;
- explicit closed dates;
- future horizon of at least the current week;
- explicit effective dates for a seasonal schedule.

### Tier B — acceptable

A first-party exact-store HTML page that directly contains the same date-aware
information and can be parsed deterministically with strict identity markers.

### Tier C — research oracle only

Google/Maps/search engines/business directories and third-party opening-hours
sites. They can reveal expected test vectors and expose adapter mistakes, but
must never independently create a public closure claim.

## Critical distinction: routine vs exceptional closure

A date-specific `closed` value is not sufficient on its own. The feature must
also know whether that closure is routine.

Preferred evidence order:

1. retailer source explicitly separates regular hours and special/date-specific
   hours;
2. retailer source explicitly labels a date as a special closure;
3. a reviewed current-season retailer baseline proves that weekday is normally
   open and the exact date is now closed.

Do not infer a permanent seasonal regime from a single Sunday. If the source
does not explicitly publish a seasonal effective range, a one-off Sunday
difference may be described only as that specific Sunday's schedule.

A resident-facing "магазин переходит на зимний/летний график" message is allowed
only when the first-party source makes the recurring transition sufficiently
clear. Otherwise publish only the exact date, or stay silent.

## Research validation vectors

External structured listings are useful only as independent oracles during
research.

The important current vector is Wednesday 7 October 2026, an official local
Guardamar holiday. A fresh structured-business cross-check on 2026-10-07 shows
ordinary hours for adjacent weekdays but no Wednesday hours for all three exact
Guardamar physical stores:

- Mercadona, Av. del Mediterrani 14;
- masymas, Av. del Puerto 20;
- DIA, La Redonda 40.

This independently corroborates "closed today" for research, but it remains a
Tier-C oracle and cannot publish anything. The production feature must reproduce
the result only from retailer first-party schedule data.

The fresh official DIA Alicante locator independently confirms exact store
`36111` at La Redonda 40 and the current 7–13 October leaflet period, while
its crawler-visible text still does not expose store opening hours. That makes
the hidden/embedded first-party schedule contract the correct technical target,
not the leaflet itself.

Other useful 2026 Guardamar dates already present in `holidays.py`:

- 9 October;
- 12 October;
- 8 December;
- 25 December.

They are useful for testing that different retailers may make different
decisions on the same legal holiday.

## Retailer-specific questions the Termux probe must answer

### Mercadona

1. Can the base official locator be fetched with the production TLS stack?
2. Which first-party bundle/API supplies physical-store results?
3. What stable ID represents the Guardamar store?
4. Does the exact-store response include regular hours, special hours or
   future dated closures?
5. Does it expose a useful future horizon for weekly and next-day notices?
6. Can the accepted request be reproduced with one bounded HTTP GET and no
   cookie/browser session?

### masymas

1. What exact official store ID represents Guardamar?
2. Is `propiedadestienda.php?Id=<guardamar>` only a normal timetable?
3. Is there a separate first-party AJAX/schedule route for holiday exceptions?
4. Does any structured ecommerce/store endpoint expose date-aware physical-store
   hours?
5. If no date-aware first-party source exists, the automatic holiday feature
   must fail closed for masymas rather than combine a static timetable with a
   public holiday and guess.

### DIA

1. Does store 36111 embed schedule data in SSR/Next.js state?
2. Is there a `/_next/data/`, app-router/Flight, REST or GraphQL request that
   returns the exact store's hours?
3. Are regular and exceptional hours distinguishable?
4. What future horizon is available?
5. Can it be reproduced directly without JavaScript execution or cookies?

## Correct runtime shape if source contracts succeed

Do not create three workflows. Use one supermarket-hours workflow and one small
state file.

### Do not optimize request cadence before measuring the endpoints

The first research draft proposed one weekly refresh plus event-driven
revalidation. That can itself become overengineering.

If the final contracts are small exact-store responses, the simplest and more
reliable design is likely:

- one short-lived daily one-shot;
- at most one exact first-party request per store;
- three requests total on an ordinary day;
- deterministic normalization/comparison;
- at most one grouped resident-facing message;
- exit.

Three small GETs per day are operationally trivial compared with the existing
project and catch late schedule changes and non-holiday published closures that
a weekly-only design could miss.

Only if a proven retailer source is materially heavy should the implementation
introduce a lower cadence plus targeted revalidation. The production design
must be chosen from measured response sizes and request counts, not speculative
micro-optimization.

### Public-holiday/calendar use

`holidays.py` may:

- enrich copy with the known holiday name;
- provide useful test/candidate context;
- help explain why a closure is practically important.

It must not:

- mark a store closed;
- mark a store open;
- override the exact retailer schedule.

The GVA commercial-opening calendar is similarly advisory/legal context only.
It should not become a recurring runtime dependency unless a later approved
feature genuinely requires it.

### One-run publication policy

A single invocation should produce at most one supermarket message.

When several triggers coincide, combine them instead of sending multiple posts.
For example, a Monday weekly heads-up and a Tuesday "tomorrow" reminder can be
rendered as one message that says both "на этой неделе" and "уже завтра".

The exact schedule/time is deliberately deferred until source contracts are
known. A separate short-lived one-shot is preferred over adding retailer
network dependencies to the 07:30 Morning Digest. A retailer timeout should
never delay the primary digest.

### Correction rule

Every public future-closure claim must remain correct after later successful
observations.

If a fresh first-party schedule later changes a previously announced future
closure to open, moves the closure date, or removes one store from a grouped
closure, silence is not sufficient: the bot created the stale expectation.
Publish at most one compact correction for that changed public claim (or use a
single idempotent edit only if the final Telegram design can guarantee that the
correction remains visible enough). A source failure is not evidence of a
reopening and must never trigger a correction.

This correction path is narrowly scoped to supermarket claims already made by
the bot. It is not a generic notification framework and requires no continuous
polling.

### State

Persist normalized facts only. No raw retailer HTML/JSON and no long history.

Likely state responsibilities:

- source contract/version;
- latest accepted exact-store schedule horizon;
- current reviewed/derived routine weekly baseline when safely known;
- bounded sent trigger keys for week/tomorrow/today/season;
- last successful observation timestamp per store;
- optional uncertain-delivery marker if a standalone Telegram send is used.

Do not add SQLite, a queue, a generic notification engine or retailer-specific
state files.

## Failure model

For each store independently:

- TLS/network timeout -> observation unavailable;
- non-success HTTP -> unavailable;
- redirect outside approved exact host set -> reject;
- wrong MIME -> reject;
- oversized payload -> reject;
- exact store identity/address missing -> contract drift;
- requested date absent -> no claim for that date;
- malformed/ambiguous hours -> reject that store;
- static normal timetable with no exceptional-date evidence -> insufficient for
  a holiday closure claim;
- holiday calendar says holiday but retailer says open -> retailer state wins;
- retailer source unavailable -> calendar alone cannot create a closure claim.

One retailer failure must not block valid observations for the other two.

## Overengineering gate

Reject:

- Playwright/Selenium/Chromium;
- JavaScript execution in production;
- browser cookies/session emulation unless an exact minimal HTTP contract proves
  it is unavoidable and is separately approved;
- a daemon or resident watcher;
- per-store cron rows/processes;
- database/message broker;
- raw-response archive;
- Google/Maps scraping;
- brute-force store-ID discovery;
- hourly polling;
- AI classification/generation of opening hours;
- a generic provider/notification framework for only three fixed stores;
- a second runtime public-holiday fetch duplicating `holidays.py`.

Prefer:

- existing `fetch_bounded`;
- exact HTTPS host/path allowlists after discovery;
- standard-library parsers/JSON;
- one workflow;
- one daily one-shot if the measured endpoints are small;
- one small atomic JSON state;
- deterministic grouped copy;
- fail-closed contract drift.

## Production probe design review

The production probe is research-only and may inspect a bounded subset of
first-party JavaScript to discover the endpoint. Production code must never do
that.

The probe intentionally imports the repository's existing
`telegrambot._transport.fetch_bounded` and uses the same Python
`urllib`/OpenSSL stack as production. A curl-only success is not sufficient
evidence because TLS/WAF behavior can differ between libcurl and Python.

The probe must:

- remain read-only;
- write only its text report below
  `~/.cache/guardamar-supermarket-hours-probe`;
- keep fetched retailer bodies in memory only and persist no raw response;
- make no Telegram call and touch no project state;
- fetch the Mercadona base locator before trying an exploratory postal-code URL;
- fetch only first-party script hosts under the retailer's registrable domain;
- list external scripts but not download them automatically;
- prioritize route/page-specific bundles instead of blindly taking the first N;
- scan the HTML itself for endpoint strings before any JS downloads;
- understand escaped JavaScript URL strings;
- bound number, size and duration of every request;
- report approximate request count and body bytes;
- check the existing local `holidays.py` rather than download another holiday
  calendar;
- leave the production branch/HEAD/worktree unchanged.

## Implementation gate

Do not write an ADR or production adapter until the Termux probe proves enough
for every retailer that is intended to launch.

A partial launch with only retailers that have a sound first-party date-aware
contract may be preferable to weakening the source policy for the remaining
one.

After endpoint discovery, run a **second narrow probe** that calls only the
candidate exact endpoints. That second probe must validate:

- exact store identity;
- current date;
- next-day/current-week horizon;
- regular vs exceptional schedule semantics;
- 7/9/12 October behavior where still observable;
- MIME/size/latency;
- no cookies/browser requirement;
- failure behavior for wrong store/date;
- stable deterministic parsing markers.

Only then should implementation architecture and public copy be finalized.
