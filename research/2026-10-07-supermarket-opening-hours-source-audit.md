# Supermarket opening-hours source audit — 2026-10-07

## Scope

This investigation evaluates a narrow resident-facing supermarket-closure
feature for Guardamar del Segura. The requested behavior is intentionally
closure-first:

- track the physical Mercadona in Guardamar del Segura;
- track the nearby physical Mercadona in San Fulgencio because it is a practical
  alternative for Guardamar residents;
- track the physical masymas in Guardamar del Segura;
- track the physical DIA in Guardamar del Segura;
- announce only a non-routine closure on a day that would normally be a working
  day;
- announce a verified seasonal transition when the store's normal Sunday
  opening/closure regime changes;
- do not announce routine weekly days off;
- do not turn a legally permitted trading day into a claim that a store is open;
- use the retailer's own source for the factual store schedule.

The desired notification lifecycle for a verified exceptional closure is:
one grouped notice near the beginning of the week, one reminder the day before,
and one reminder on the day itself. Stores sharing the same exceptional closure
should be grouped in resident-facing copy.

No production implementation is approved by this research file. This is a
source and architecture audit.

## Why San Fulgencio must be a separate physical store

The nearby Mercadona at C. Mar Adriático, S/N is legally in San Fulgencio and
therefore must retain a separate municipality/calendar identity from the
Guardamar store at Av. del Mediterrani, 14.

This distinction is operationally useful. On Wednesday 7 October 2026,
Guardamar has a local holiday (Virgen del Rosario) while San Fulgencio does
not. Current external structured listings show the Guardamar Mercadona closed
and the San Fulgencio Mercadona open 09:00–21:30. This is a useful validation
vector only; external map/search data is not an accepted production fact source.

The Diputación de Alicante 2026 municipal holiday table gives:

- Guardamar del Segura: 24 July and 7 October;
- San Fulgencio: 16 January and 8 October.

Source:
https://documentacion.diputacionalicante.es/fiestas.asp

This creates an especially useful two-day test pair:

- 2026-10-07: local holiday in Guardamar, not San Fulgencio;
- 2026-10-08: local holiday in San Fulgencio, not Guardamar.

The calendar is only a candidate generator. A local holiday is not proof that a
particular supermarket closes, and a commercial-opening authorization is not
proof that it opens.

## Physical stores in scope

### Mercadona — Guardamar del Segura

Reviewed identity:

- address: Avinguda / Av. del Mediterrani, 14, 03140 Guardamar del Segura;
- retailer: Mercadona;
- municipality: Guardamar del Segura.

Official store-locator surface:
https://info.mercadona.es/es/supermercados

### Mercadona — San Fulgencio

Reviewed identity:

- address: C. Mar Adriático, S/N, 03177 San Fulgencio;
- retailer: Mercadona;
- municipality: San Fulgencio;
- practical role: nearby alternative when Guardamar's store is exceptionally
  closed.

Official Mercadona documents also identify the San Fulgencio address. The
production schedule must still come from a current Mercadona store-hours
surface rather than from a static PDF.

Official store-locator surface:
https://info.mercadona.es/es/supermercados

### masymas — Guardamar del Segura

Reviewed identity:

- address: Av. del Puerto, 20, 03140 Guardamar del Segura;
- retailer: masymas.

Official locator:
https://www.masymas.com/localizadordetiendas/localizador.php

The locator is a useful candidate because it exposes a very small server-side
store-detail route:
https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=13

The reviewed Id=13 response is not Guardamar; it is only a control proving that
the official first-party locator has a compact per-store detail surface. The
Guardamar ID must be discovered from the locator contract, not brute-forced.

The official FAQ explicitly says holiday/bridge opening depends on locality and
date. Therefore a static normal timetable must not be assumed to contain
holiday exceptions:
https://www.masymas.com/es/atencion-al-cliente/preguntas-frecuentes.html

### DIA — Guardamar del Segura

Reviewed identity:

- official store ID: 36111;
- address: CL LA REDONDA, 40, 03140 Guardamar del Segura;
- retailer: DIA.

Official stable store path:
https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111

The current server-rendered page/search surface reliably exposes the store
identity and weekly leaflet identity, but the text-visible SSR representation
does not expose opening hours. The page therefore needs a bounded inspection of
its embedded Next.js data and same-host JavaScript to identify the first-party
request that supplies store schedule data.

## Legal/calendar layer

The legal calendar is valuable as a low-cost trigger/advisory layer, not as the
authoritative store state.

Useful first-party calendars include:

- official/local public holidays for Guardamar and San Fulgencio;
- Generalitat Valenciana annual permitted commercial Sundays/festive opening
  calendar;
- Guardamar's applicable tourist-trading-zone rules where current and
  officially published.

These sources can answer "which dates are worth checking?" They cannot answer
"does this store open on this date?" because retailers may make different
choices on the same legally permitted day and individual store exceptions can
exist.

The runtime model must therefore be:

    public calendar -> candidate date only
    retailer store schedule -> factual open/closed state

Never invert that precedence.

## External validation vectors observed on 2026-10-07

External structured business listings are useful only as an independent test
oracle while the retailer endpoints are being discovered. They are not
eligible production fact sources under the project principles.

Observed vectors:

1. Wednesday 2026-10-07:
   - Mercadona Guardamar: closed;
   - Mercadona San Fulgencio: open 09:00–21:30;
   - masymas Guardamar: closed;
   - DIA Guardamar: closed.

2. Monday 2026-10-12, a national holiday:
   - masymas Guardamar is currently shown with a shortened opening;
   - DIA Guardamar is currently shown open;
   - Mercadona behavior differs from those chains.

This proves why a shared "holiday = closed" rule would be false.

3. Thursday 2026-10-08 is a San Fulgencio local holiday. It is an excellent
   near-term production probe date: the system must accept only the actual
   Mercadona San Fulgencio schedule, never infer closure from the municipality
   calendar.

## Source ranking

### Tier A — acceptable production source

A first-party retailer JSON/API/AJAX endpoint returning the exact physical
store identity and date-aware opening schedule.

Desired properties:

- HTTPS exact allowlisted host;
- stable physical-store identifier;
- date or weekday schedule with explicit special/holiday exceptions;
- small JSON or HTML response;
- no authentication;
- no browser/JavaScript execution;
- no cookies if avoidable;
- deterministic contract markers;
- bounded response size.

### Tier B — acceptable if no JSON exists

A first-party retailer HTML store page that itself contains the exact physical
store identity and current date-aware schedule. Parse only the narrow reviewed
markers required for the feature.

### Tier C — validation/fallback research only, not a publication source

Search engines, maps, directories and third-party timetable sites. They are
valuable for comparing expected behavior and detecting that a first-party
adapter may be wrong, but they must not independently create a public closure
claim.

## Retailer-specific technical status

### Mercadona

Known healthy first-party JSON exists for the online product catalogue under
`tienda.mercadona.es/api/`, and the project already uses one exact product
endpoint in Product Awards. That API is warehouse/product oriented and is not
evidence of physical-store opening hours.

The official physical-store locator is
`https://info.mercadona.es/es/supermercados`. The external research client can
be denied access to this surface, so a read-only Termux probe is required.

The probe must:

1. request the locator for postal-code searches 03140 and 03177;
2. inspect the returned HTML and embedded data;
3. enumerate only same-host JavaScript referenced by that page;
4. extract endpoint-like strings containing store/supermarket/opening/schedule
   concepts;
5. make no browser request and no brute-force store-ID crawl.

If a compact first-party JSON request can be reproduced directly, it becomes the
preferred adapter. If Mercadona exposes only static normal hours with no
date-aware exceptions, the source is insufficient for this feature by itself.

### masymas

This is currently the strongest simple-source candidate because the official
locator already exposes a compact server-side per-store detail route.

Open questions for the Termux probe:

- the exact Guardamar store ID;
- whether the locator/detail route exposes date-aware exceptional hours or only
  a static normal schedule;
- whether the page loads an additional AJAX schedule object for holidays;
- whether special dates are represented elsewhere on the same official host.

Do not brute-force `propiedadestienda.php?Id=N`. Discover the ID from the
official locator HTML/JS/selector response.

### DIA

The exact physical store already has stable ID `36111`, which is a strong
identity anchor.

The SSR page does not expose hours in its visible text, so the next step is to
inspect:

- `__NEXT_DATA__` if present;
- build ID and same-host `/_next/data/...` payload if present;
- same-host JavaScript chunks for the exact API route used by the store locator.

The project already has a reviewed browser-navigation HTTP header profile for
DIA product pages. That does not automatically authorize a store-hours adapter,
but it proves a bounded plain-HTTP approach is compatible with the existing
runtime if the first-party locator requires similar navigation headers.

No Selenium/Playwright should be introduced merely because the rendered page
is JavaScript-backed.

## Proposed minimal runtime architecture if the source probe succeeds

The target architecture is one supermarket-hours workflow, not four workflows.

### Collection

One short-lived one-shot refresh obtains the four physical-store schedules:

- Mercadona Guardamar;
- Mercadona San Fulgencio;
- masymas Guardamar;
- DIA Guardamar.

Where a retailer endpoint can return more than one of our physical stores in
one bounded response, prefer the single response. Otherwise make one exact
store request per physical store.

There is no reason for continuous polling. Opening schedules normally change
slowly.

### Candidate-driven network policy

Use the official public calendar to identify dates that can plausibly cause an
exception, but do not infer the result from the calendar.

A low-cost design is:

1. once near the start of the local week, refresh the four retailer schedules;
2. normalize only the current/next relevant week;
3. if no exceptional closure or seasonal transition exists, send nothing;
4. before a due "tomorrow" reminder, revalidate only the affected store(s);
5. before a due "today" reminder, revalidate only the affected store(s);
6. if revalidation fails or contradicts the saved schedule, fail closed for the
   affected claim.

This avoids daily four-store polling while protecting the high-value reminder
from a stale weekly snapshot.

### State

One small atomic JSON file is sufficient. Candidate shape:

```json
{
  "version": 1,
  "observed_at": "...",
  "week_start": "YYYY-MM-DD",
  "stores": {
    "mercadona_guardamar": {
      "source_id": "...",
      "days": {
        "YYYY-MM-DD": {"open": false, "hours": []}
      }
    }
  },
  "sent": [
    "week:YYYY-MM-DD:<closure-group-key>",
    "tomorrow:YYYY-MM-DD:<closure-group-key>",
    "today:YYYY-MM-DD:<closure-group-key>",
    "season:<store>:<transition-key>"
  ]
}
```

This is illustrative, not an approved schema. Persist normalized facts only.
Do not store raw retailer HTML/JSON or long history.

### Seasonal transitions

A one-week schedule difference must not automatically be labeled a permanent
seasonal transition.

Preferred evidence order:

1. first-party source explicitly publishes a seasonal date/range; or
2. the exact physical-store source exposes a future schedule whose normal
   Sunday regime changes at a clear boundary; or
3. absent explicit source metadata, treat the first differing Sunday as a
   date-specific opening/closure rather than claiming a season.

The resident-facing feature requested here is closure-focused. A seasonal
transition is worth one message because it changes the recurring expectation.
Routine Sundays after the transition produce no further messages.

### San Fulgencio alternative rule

When Mercadona Guardamar has a verified exceptional closure, the bot may append
a practical alternative only if the San Fulgencio physical store has a fresh,
first-party-confirmed open schedule for the same date.

Example meaning, not final copy:

"Меркадона в Гуардамаре сегодня закрыта. Если нужно, ближайшая Mercadona в
San Fulgencio сегодня работает ..."

If San Fulgencio cannot be freshly verified, omit the alternative rather than
guessing.

## Overengineering review

Reject:

- Playwright/Selenium/Chromium;
- a resident daemon;
- per-store cron rows;
- a database;
- scraping Google/Maps as a production dependency;
- an all-year raw schedule archive;
- hourly or daily four-store polling with no pending event;
- brute-force store-ID discovery;
- AI classification of store hours;
- generic notification framework work unless another existing primitive fits
  exactly.

Prefer:

- one module/workflow;
- standard-library HTTP through the existing bounded transport helper;
- exact host allowlists;
- one small normalized state file;
- one weekly refresh plus event-driven revalidation;
- existing cron installer conventions;
- deterministic date/open/closed comparisons;
- grouped resident-facing messages.

This design is materially smaller than a continuous monitoring system and fits
the Termux constraints.

## Failure model

For each retailer independently:

- timeout -> store observation unavailable;
- non-200 -> unavailable;
- redirect outside allowlist -> reject;
- unexpected MIME -> reject;
- identity marker missing -> contract drift, reject;
- date missing -> do not infer;
- malformed hours -> reject only that store observation;
- calendar says holiday but retailer schedule says open -> retailer schedule
  wins;
- retailer source unavailable -> no new closure claim from calendar alone.

A failure for one store must not block valid observations for the other stores.

## What the production Termux probe must prove before implementation

The companion read-only probe in
`research/2026-10-07-supermarket-hours-termux-probe.sh` is designed to answer:

1. Can the official Mercadona locator be fetched with the production TLS stack?
2. Which exact first-party request supplies Guardamar and San Fulgencio store
   schedule data?
3. What is the official store identifier for each Mercadona location?
4. What is the official Guardamar masymas ID?
5. Does masymas expose exceptional/date-aware hours or only normal hours?
6. Does DIA store 36111 embed schedule data in Next.js data or call a small API?
7. Can all accepted requests be reproduced without cookies/browser execution?
8. What response sizes and MIME types must be bounded?
9. Does today's 2026-10-07 schedule reproduce the independently observed
   Guardamar/San-Fulgencio split?
10. Does 2026-10-08 reveal how San Fulgencio represents its own local holiday?

Only after these questions are answered should an ADR or production adapter be
written.
