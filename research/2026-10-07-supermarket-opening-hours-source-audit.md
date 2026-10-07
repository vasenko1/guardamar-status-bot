# Supermarket opening-hours source audit — 2026-10-07

## Scope

This investigation evaluates a narrow resident-facing supermarket-closure
feature for **Guardamar del Segura only**.

Final physical-store scope:

1. Mercadona — Av. del Mediterrani, Guardamar del Segura;
2. masymas — Av. del Puerto, Guardamar del Segura;
3. DIA — CL La Redonda, Guardamar del Segura.

San Fulgencio is deliberately out of scope. It is a separate municipality even
though its Mercadona is geographically close. The feature should remain about
Guardamar businesses and should not turn into a nearby-shopping directory.

The requested product behavior is closure-first:

- announce only a verified non-routine **full closure** on a date when the
  store would normally be open;
- do not announce routine weekly days off;
- do not announce ordinary shortened hours merely because a holiday changes the
  timetable;
- announce a verified seasonal transition once when the recurring Sunday
  open/closed regime changes;
- group stores when they share the same exceptional closure;
- use a first-party retailer source for the factual store schedule.

Desired reminder lifecycle for one verified exceptional closure:

- near the beginning of the week;
- the day before;
- the day itself.

These phases must collapse when they fall on the same local day. There must
never be two supermarket messages on one day saying essentially the same thing.

No production implementation is approved by this research file yet. Source
contracts must first pass the read-only Termux probe.

## Existing project assets that must be reused

### Guardamar holiday calendar

The project already has an annually reviewed deterministic Guardamar holiday
calendar in:

`src/telegrambot/holidays.py`

For 2026 it includes the national, regional and local Guardamar holidays,
including 7 October and 9 October.

Therefore this supermarket feature must **not add another scheduled network
request merely to learn Guardamar holidays**.

The holiday calendar can identify dates worth extra attention. It cannot prove
that a supermarket is closed.

Runtime precedence must remain:

    reviewed Guardamar calendar -> candidate/context only
    exact retailer store source -> factual open/closed state

A legal holiday, ZGAT period, or legally permitted commercial Sunday is never
itself evidence that a particular store opens or closes.

### Shared bounded HTTP transport

Production code should reuse:

`src/telegrambot/_transport.py::fetch_bounded`

Each retailer adapter must still define its own exact HTTPS host policy,
content-type allowlist, size limit, timeout and identity markers.

No new HTTP dependency is justified.

## Physical stores in scope

### Mercadona — Guardamar del Segura

Reviewed identity:

- municipality: Guardamar del Segura;
- postal code: 03140;
- address: Av. / Avinguda del Mediterrani, 14;
- retailer: Mercadona.

Official locator surface:

https://info.mercadona.es/es/supermercados

The existing Product Awards feature proves that Mercadona has lightweight
first-party JSON for the ecommerce catalogue, but the reviewed
`tienda.mercadona.es/api/products/...` contract is warehouse/product data and
must not be repurposed as evidence of physical-store opening hours.

### masymas — Guardamar del Segura

Reviewed identity:

- municipality: Guardamar del Segura;
- postal code: 03140;
- address: Av. del Puerto, 20;
- retailer: masymas / Juan Fornés.

Official locator:

https://www.masymas.com/localizadordetiendas/localizador.php

A small first-party detail route exists:

https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=...

The Guardamar ID must be discovered from the official locator contract, not by
brute-force numeric scanning.

The project already uses the separate first-party masymas ecommerce API for an
exact Product Awards SKU:

`https://tienda.masymas.com/api/rest/V1.0/catalog/product/<id>`

That proves a lightweight first-party API style exists, but the product API is
not evidence of store opening hours.

The official masymas FAQ says holiday/bridge opening depends on locality and
date. Therefore a static normal timetable is insufficient unless the exact
store source also carries the date-specific exception.

### DIA — Guardamar del Segura

Reviewed identity:

- official store ID: `36111`;
- address: CL LA REDONDA, 40;
- postal code: 03140;
- municipality: Guardamar del Segura;
- retailer: DIA.

Official stable store path:

https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111

The server-rendered/search representation exposes the exact physical-store
identity but not enough opening-hour data in plain visible text. The read-only
probe therefore inspects embedded Next.js data and only the same-host assets
needed to discover the first-party store-hours request.

The existing Product Awards feature already proves that DIA pages can be read
browser-free with bounded navigation-style HTTP headers. That does not prove
the store-hours contract, but it means browser automation is not justified
before the direct HTTP path has been exhausted.

## Source acceptance hierarchy

### Tier A — preferred

A first-party retailer JSON/API/AJAX endpoint returning:

- exact physical-store identity;
- a current/future date-aware schedule;
- explicit closed/open state or unambiguous intervals;
- enough horizon to support the beginning-of-week reminder.

Desired properties:

- exact allowlisted HTTPS host;
- stable store identifier;
- no login;
- no JavaScript execution;
- no browser;
- no cookie session if avoidable;
- small response;
- deterministic contract markers.

### Tier B — acceptable

A first-party exact-store HTML page that itself contains the required
date-aware schedule. Parse only reviewed identity/date/hour markers.

### Not acceptable for publication facts

- Google/Maps;
- directories;
- search snippets;
- community reports;
- third-party timetable sites.

They may be used only as research/test oracles to detect an obviously broken
first-party parser.

## Current technical questions

### Mercadona

The production probe must establish:

1. whether the official locator is reachable under the production
   Python/OpenSSL stack;
2. the exact first-party request that supplies the Guardamar physical store;
3. the physical-store identifier;
4. whether the returned hours are date-aware rather than only a static weekly
   template;
5. whether future dates are available far enough ahead for the weekly notice.

### masymas

The production probe must establish:

1. the exact official Guardamar store ID;
2. whether the small per-store route carries exceptional/holiday hours;
3. whether another same-host AJAX request carries those exceptions;
4. whether the response horizon is sufficient for early-week warning.

No numeric ID crawl is allowed.

### DIA

The production probe must establish:

1. whether exact store 36111 embeds schedule data in `__NEXT_DATA__`;
2. whether a page-specific Next.js data/API route supplies the hours;
3. whether direct HTTP works without cookies/browser execution;
4. whether future dates are available;
5. the size and MIME of the smallest usable first-party response.

## Exceptional-closure semantics

The feature must not equate `closed in returned schedule` with
`exceptional closure` until it has a reviewed concept of the store's normal
recurring schedule.

Preferred evidence, strongest first:

1. the retailer explicitly labels a date as special/holiday/exceptional;
2. the first-party source exposes both recurring normal hours and date-specific
   overrides;
3. a small reviewed normal weekly baseline is stored/configured for the current
   operating season and exact-date retailer data is compared with it.

Do not infer a normal baseline from one unusual week.

If the accepted retailer source cannot distinguish a normal weekly closure from
an exception and no safe reviewed baseline exists, that retailer is not ready
for automatic publication.

A shortened opening day is not a closure. Under the requested product policy it
remains silent.

## Seasonal-transition semantics

Ordinary recurring Sundays stay silent.

A seasonal transition may produce one notice because it changes the resident's
recurring expectation. Both directions may be useful:

- Sundays become open for the summer regime;
- Sundays return to being closed outside that regime.

However, a single Sunday difference must never automatically be called a
seasonal transition.

Accept a seasonal transition only when one of these is true:

1. the retailer explicitly publishes the seasonal period/boundary;
2. the exact-store source exposes multiple future recurring Sundays proving a
   clear pattern boundary;
3. another reviewed first-party retailer publication explicitly defines the
   store's seasonal regime.

Otherwise describe only an exact-date closure/opening if that exact date itself
is eligible; do not invent a season.

## Notification collapse and grouping rules

The desired three-phase lifecycle is useful, but must not create repetitive
messages.

### Beginning-of-week

One grouped message may list all already verified exceptional closures still
ahead in the current Monday–Sunday week.

Do not include:

- routine Sunday closures;
- shortened-hours-only changes;
- already elapsed dates.

### Day before

One grouped message for stores verified closed tomorrow.

### Same day

One grouped message for stores verified closed today.

### Phase collapse

At most one supermarket closure message per local calendar day.

Examples:

- exceptional closure on Monday: send only the same-day message; do not also
  send a separate "this week" message;
- exceptional closure on Tuesday: Monday's beginning-of-week message already
  naturally says "tomorrow"; do not send a second Monday reminder for the same
  Tuesday closure;
- two stores closed on the same target date: one message, not two;
- two different exceptional closure dates in the same week: one beginning-of-
  week overview may list both; later reminders are date-specific.

This is a product rule, not a generic notification framework.

## Cadence: do not optimize before measuring response cost

The earlier draft assumed that one weekly refresh plus event-driven
revalidation was automatically best. That is not yet justified.

If the final contracts are tiny JSON responses, the simplest reliable runtime
may be one daily one-shot making at most one request per retailer:

- three source requests per successful day;
- about 90 requests in a 30-day month;
- no resident process;
- no internal retry storm;
- immediate visibility of a mid-week schedule change.

That is likely simpler and safer than a complex request-suppression state
machine.

If one accepted source is a large HTML page, a lower cadence may be justified:

- refresh near the beginning of the week;
- revalidate an affected store before a due tomorrow/today reminder;
- preserve last-good normalized schedule only for bounded comparison.

The production cadence must therefore be chosen **after** the probe records the
smallest usable response size and horizon for each retailer.

Do not optimize request count at the cost of more state, more branches, or a
higher chance of missing a new closure.

## Candidate normalized state

One small atomic JSON file should be enough for the entire feature.

Only normalized facts and delivery keys are eligible. No raw retailer
HTML/JSON history.

Illustrative shape only:

```json
{
  "version": 1,
  "observed_at": "2026-10-07T...",
  "stores": {
    "mercadona_guardamar": {
      "source_id": "...",
      "normal_signature": "...",
      "days": {
        "2026-10-07": {"open": false, "intervals": []}
      }
    }
  },
  "sent": [
    "week:2026-W41:<semantic-key>",
    "tomorrow:2026-10-09:<semantic-key>",
    "today:2026-10-09:<semantic-key>",
    "season:mercadona_guardamar:<semantic-key>"
  ]
}
```

The final schema should be smaller if the accepted source contract permits it.

## Failure model

Retailers fail independently.

- timeout -> no fresh observation for that store;
- non-200 -> no fresh observation;
- redirect outside exact allowlist -> reject;
- wrong MIME -> reject;
- exact store identity missing -> contract drift;
- requested/future date missing -> do not infer;
- malformed hours -> reject that store/date;
- calendar says holiday but retailer source says open -> retailer source wins;
- calendar says holiday but retailer source is unavailable -> no new closure
  claim;
- stale last-good data may support diagnostics but must not create a fresh
  today/tomorrow claim beyond its reviewed freshness window.

One broken retailer must not suppress valid notices for another.

## User-facing copy rules

Copy should read like a local resident wrote it, not like a database report.

Prefer:

- `В среду Mercadona и DIA будут закрыты — в Гуардамаре местный праздник.`
- `Завтра Mercadona не работает.`
- `Сегодня Mercadona, masymas и DIA закрыты.`

When the reason is independently known from the reviewed Guardamar calendar,
it may be added naturally.

Avoid:

- `Статус магазина: CLOSED`;
- legal boilerplate about ZGAT;
- source/debug wording;
- repeating ordinary weekly schedules;
- mentioning shortened hours when the policy is closure-only;
- claiming `из-за праздника` when the date/source relationship is not
  actually reviewed.

Final Russian templates belong in implementation tests once exact source
semantics are known.

## Overengineering review

Explicitly rejected:

- Mercadona San Fulgencio or other nearby-city stores;
- Playwright/Selenium/Chromium;
- browser screenshots;
- per-store cron jobs;
- a daemon;
- a database;
- raw schedule archives;
- Google/Maps as a production dependency;
- brute-force store-ID discovery;
- AI/LLM interpretation of opening hours;
- a new generic provider or notification framework;
- a second network holiday-calendar collector;
- source-specific background workers;
- hourly polling.

Preferred direction if source contracts pass:

- one narrow `supermarket_hours` workflow;
- three small source adapters;
- existing standard-library bounded transport;
- one compact atomic state;
- deterministic exact-date comparisons;
- grouped messages;
- one external cron entry at most, unless the final design can reuse an
  existing semantically appropriate one-shot without coupling failures.

## Architecture fit

The feature has genuine local resident value and matches the project's
`material disruption / closure` principle.

It remains acceptable only if:

- facts come from first-party retailer sources;
- no heavy dependency is added;
- source failure is silent/fail-closed;
- network work is bounded;
- state is small;
- no continuous process is introduced;
- ordinary schedules remain quiet.

Do not implement merely because third-party maps happen to expose good hours.

## Read-only production probe gate

The companion probe:

`research/2026-10-07-supermarket-hours-termux-probe.sh`

must answer, for **only the three Guardamar stores**:

1. smallest viable first-party request;
2. exact physical-store identity;
3. status, MIME, response size and redirect behavior;
4. whether cookies/authentication are required;
5. exact representation of 2026-10-07;
6. future schedule horizon;
7. whether special hours are distinguishable from normal weekly hours;
8. whether browser execution is unnecessary;
9. whether the source can support a safe normal-vs-exception comparison;
10. whether the total runtime cost favors simple daily collection or a lower
    cadence.

Implementation, ADR, cron and public-message code should wait for that evidence.

## Validation matrix after endpoint discovery

The implementation must later prove at least:

### Positive behavior

- one Guardamar store exceptionally closed on a normal working weekday;
- two/three stores closed on the same date -> one grouped message;
- different closure dates in one week -> one weekly overview;
- tomorrow reminder;
- today reminder;
- phase collapse on Monday/Tuesday edge cases;
- verified seasonal Sunday-open transition;
- verified seasonal Sunday-closed transition.

### Negative behavior

- routine Sunday closure -> silence;
- ordinary open weekday -> silence;
- shortened holiday hours but still open -> silence;
- public holiday where the retailer chooses to open -> silence;
- source unavailable -> no guessed closure;
- malformed one-store payload -> other stores still usable;
- stale snapshot -> no fresh today/tomorrow claim;
- one unusual Sunday -> no invented seasonal transition;
- rerun after confirmed delivery -> no duplicate;
- ambiguous Telegram delivery -> no automatic duplicate.

### Resource behavior

- no browser process;
- no AI;
- no source history;
- no per-store cron;
- exact host allowlists;
- bounded response sizes and timeouts;
- no network holiday lookup when the reviewed local calendar already covers
  the needed date context.


## Repeated pre-device audit — 2026-10-07

The design and research probe were re-reviewed repeatedly before asking the
operator to run anything on the production phone. The review found and removed
several real defects from the first draft:

- San Fulgencio was removed completely from product scope after the requirement
  was clarified. The feature now has exactly three Guardamar physical stores.
- A second runtime holiday-calendar fetch was removed because the repository
  already owns the reviewed annual Guardamar calendar in `holidays.py`.
- The speculative weekly-refresh/event-driven request policy was downgraded
  from a design decision to a measured choice. If exact responses are small,
  one three-store daily one-shot is simpler and more robust.
- The probe no longer assumes Mercadona's exploratory `?s=03140` query is a
  supported search contract; it inspects the base locator first.
- Blind "first six JavaScript files" inspection was replaced by bounded,
  prioritized first-party script inspection, while external scripts are only
  listed.
- The probe no longer uses curl as evidence for production compatibility. It
  imports the same `telegrambot._transport.fetch_bounded` Python/urllib
  transport used by the application, so TLS, redirects, MIME and byte limits
  are exercised on the real runtime stack.
- Fetched retailer bodies are kept only in memory. The only persisted artifact
  is a text diagnostic report outside project state.
- The service User-Agent now matches production exactly. JavaScript discovery
  uses the service profile first and only one already-reviewed navigation
  header fallback after an explicit 403/406.
- Escaped URL forms common in minified JavaScript are normalized for discovery,
  avoiding false negatives without executing JavaScript.
- The report redacts token/key/secret-shaped values, suppresses hidden/password
  input values, and applies the same redaction to form actions/options.
- The public behavior explicitly ignores shortened-but-open days. Only a full
  exceptional closure is part of the normal reminder lifecycle.
- A narrow correction rule was added: a later successful first-party
  observation that reverses an already-published future closure must correct
  the bot's own stale claim. Source failure can never imply reopening.

A fresh public cross-check on the same date also confirms that DIA's official
Alicante locator still exposes the exact Guardamar physical store
`36111`, La Redonda 40, with the 7–13 October 2026 leaflet period. The
crawler-visible surface still does not expose opening hours, so leaflet dates
must not be mistaken for store-hour evidence.

A third-party Guardamar masymas listing currently labels 12 October as closed,
while other public sources observed during the broader investigation have shown
different holiday/opening patterns at different times. This inconsistency is
useful only as evidence that third-party hours are unsafe as a production
fallback.

The final pre-device conclusion is therefore deliberately conservative:

1. discover and prove the retailer's own exact-store schedule contract;
2. run a second narrow exact-endpoint probe;
3. only then decide implementation/cadence and write an ADR;
4. launch only stores whose first-party source can prove date-aware exceptional
   closures;
5. leave a retailer silent rather than infer a closure from a holiday calendar,
   ordinary weekly timetable, or third-party listing.

At this gate no production code, cron, state schema, Telegram behavior, ADR or
stable KB decision has been changed.
