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

The holiday calendar can explain a verified closure and can identify dates
worth extra attention. It must **not** gate retailer collection because the
requested feature also covers exceptional closures for non-holiday reasons.

Runtime precedence must remain:

    exact retailer store source -> factual open/closed state
    reviewed Guardamar calendar -> optional reason/context only

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

## Historical / archive evidence

No first-party retailer archive has yet been found that provides a trustworthy
date-by-date history of opening/closure state for these exact three Guardamar
stores.

Historical public material is still useful as a **research validation oracle**,
not as production evidence. In particular, 2026 press coverage identifies the
Guardamar Mercadona among Alicante coastal stores opening on summer Sundays and
documents the end of Mercadona's summer regime at the end of August. This is
useful for testing whether a future first-party adapter can reproduce a known
past seasonal pattern, but the bot must not publish from press or directory
archives.

Third-party timetable sites for masymas and DIA expose some dated schedules,
but their holiday claims are inconsistent across providers and dates. They are
not a safe fallback.

Do not build a raw daily archive merely to compensate for missing retailer
history. If seasonal inference later requires local history, retain only a
bounded normalized **regime-change history**, for example:

- store key;
- effective date;
- recurring weekday open/closed signature;
- first-party source observation timestamp.

Routine identical days do not need another history row. Raw HTML/JSON is never
archived.

The preferred outcome remains an exact retailer source that publishes enough
future/special schedule information that historical inference is unnecessary.

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

Do not infer a normal baseline from one unusual week. Do not hard-code a
Saturday/Sunday assumption from memory, third-party listings or conversation
examples; each physical store's recurring baseline must be reviewed against
first-party evidence and must permit seasonal replacement.

All target-date calculations use `Europe/Madrid`. If the reviewed Guardamar
holiday calendar for a future year has not yet been added, retailer collection
still runs; only the optional holiday reason/context is omitted.

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

The requested lifecycle does **not** require three schedulers. One daily
morning evaluation can produce every phase and at most one supermarket message
for that local day.

For each successful run, deterministic composition considers:

1. verified exceptional closures **today**;
2. verified exceptional closures **tomorrow**;
3. on Monday, other verified exceptional closures later in the same
   Monday–Sunday week;
4. a newly discovered closure later in the current week only when it was not
   knowable on Monday and is still at least two days away;
5. one due verified seasonal-transition notice.

All due units are merged into one natural resident-facing message. There is no
second supermarket post on the same day.

### Edge cases

- closure on Monday: Sunday's run may publish `завтра`; Monday publishes
  `сегодня`. There is no redundant Monday weekly overview for that same
  closure;
- closure on Tuesday: Monday's message naturally serves both the weekly and
  `завтра` purpose; no second Monday reminder is sent;
- closure on Wednesday or later and already known on Monday: Monday gives the
  early-week notice, the preceding day gives `завтра`, and the date itself
  gives `сегодня`;
- closure first appears after Monday: the first fresh observation may produce
  one bounded early notice while it is still two or more days away; otherwise
  the next eligible phase is `завтра`;
- two or three stores closed on the same date: one grouped unit;
- several exceptional closure dates in one week: one early overview may list
  them, while later reminders stay date-specific;
- a same-day closure plus another later-week closure: compose one message with
  the urgent same-day fact first.

Routine Sundays and shortened-hours-only differences never enter this
composer. This remains a narrow product rule, not a generic notification
framework.

## Cadence: prefer one daily one-shot if the endpoints are small

The earlier draft assumed that one weekly refresh plus event-driven
revalidation was automatically best. That would add state and branches before
we know they buy anything.

If the final contracts are small JSON responses, the preferred design is one
short daily morning process making at most one schedule request per retailer:

- at most three retailer requests per successful day;
- about 90 requests in a 30-day month;
- one scheduler entry, not separate weekly/tomorrow/today jobs;
- no resident process;
- no internal retry storm;
- mid-week schedule changes are visible on the next morning run;
- Sunday can provide the `завтра` warning for an exceptional Monday closure.

The process should run in a free morning slot chosen only after checking the
existing cron timeline. It should remain independent of Morning Digest, SUMA,
Sports Today and guide delivery so one workflow cannot suppress another.

If an accepted source proves materially large, a lower collection cadence may
be justified for that source, but only after measurement. Any request
suppression must remain simpler than making the request it saves.

The production cadence must therefore be chosen **after** the probe records the
smallest usable response size and future horizon for each retailer.

Do not optimize request count at the cost of more state, more branches, stale
today/tomorrow facts, or missed mid-week changes.

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
    "early:2026-10-09:mercadona_guardamar",
    "tomorrow:2026-10-09:mercadona_guardamar",
    "today:2026-10-09:mercadona_guardamar",
    "season:mercadona_guardamar:<semantic-key>"
  ],
  "uncertain_batch": null
}
```

Delivery identity belongs to **store + target date + phase**, not to the
rendered group of stores. Grouping is presentation only. If another store is
confirmed later for the same target date, it can become newly eligible without
making stores already covered in that phase eligible again.

Before a non-idempotent Telegram send, reserve the whole rendered batch.
Confirmed success marks every included store/date/phase key sent. Ambiguous
delivery keeps one bounded `uncertain_batch` and is never retried
automatically. Deterministic failure may release the reservation for a later
bounded attempt. Prefer an existing project delivery-state primitive if it
matches this contract exactly; do not create a generic notification framework.

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
  today/tomorrow claim beyond its reviewed freshness window;
- if the bot already published a future full-closure claim and a later
  successful first-party observation proves that store open on that same date,
  publish one compact correction for the bot's own stale claim. A shortened
  but open interval also counts as a reversal of a prior "closed" claim.
  Source failure, missing data or third-party evidence can never imply
  reopening.

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
- a closure first discovered after Monday receives the correct next eligible
  phase without fabricating a missed Monday message;
- a store added later to an already-notified target date does not re-notify
  stores already covered in that phase;
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
- ambiguous Telegram delivery -> no automatic duplicate;
- a changed grouped-store composition cannot change already-sent per-store
  phase identity.

### Resource behavior

- no browser process;
- no AI;
- no source history;
- no per-store cron;
- exact host allowlists;
- bounded response sizes and timeouts;
- no network holiday lookup when the reviewed local calendar already covers
  the needed date context;
- retailer collection is not gated by holidays, so non-holiday exceptional
  closures remain discoverable.


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
- The probe does not promote Mercadona's exploratory `?s=03140` query into a
  production contract. It inspects the base locator first, then uses the
  postcode query only as a bounded first-party research request for exact
  Guardamar evidence.
- Blind "first six JavaScript files" inspection was replaced by bounded,
  prioritized first-party script inspection, while external scripts are only
  listed.
- The probe no longer uses curl as evidence for production compatibility. It
  imports the same `telegrambot._transport.fetch_bounded` Python/urllib
  transport used by the application, so TLS, redirects, MIME and byte limits
  are exercised on the real runtime stack.
- Fetched retailer bodies are kept only in memory. The only persisted artifact
  is a text diagnostic report outside project state.
- Retailer pages are tried first with the current project service HTTP
  profile. Only an explicit HTTP 403/406 permits one already-reviewed
  navigation-header fallback; JavaScript assets stay on the lightweight
  service profile.
- Escaped URL forms common in minified JavaScript are normalized for discovery,
  avoiding false negatives without executing JavaScript.
- Diagnostic snippets and URLs redact token/API-key/secret-shaped values
  before printing. The probe does not print cookies or authorization headers.
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


## Final pre-device consistency gate

After the repeated design/probe review, a machine consistency pass was run
against the research branch before requesting any production-device execution.

Result: **24/24 checks passed**.

The gate verified:

- exactly three Guardamar stores are in product scope;
- San Fulgencio is absent from the executable probe;
- the research branch is based on the reviewed production `main`;
- the branch changes only files under `research/`;
- holidays are context only and never gate retailer collection;
- the existing local `telegrambot.holidays` calendar is reused;
- the probe makes no holiday-calendar network request;
- the same production `fetch_bounded` transport is exercised;
- no curl-specific evidence path is used;
- no browser automation, AI, Telegram call or project-state write exists;
- no `/tmp` assumption exists;
- the service User-Agent is attempted first;
- the one navigation-style fallback is restricted to explicit HTTP 403/406;
- HTTPS host policy is exact and redirect-safe;
- page/asset byte limits are explicit;
- there is no unbounded retry loop;
- production branch, HEAD and exact worktree status are compared before/after;
- embedded Python is parsed before any source audit runs;
- delivery identity is store + target date + phase;
- ambiguous delivery is crash-safe and not automatically retried;
- closures first discovered after Monday have a defined next eligible phase;
- a later verified reversal of a future closure has a correction path;
- shortened-but-open days stay silent;
- routine Sunday closures stay silent;
- one unusual Sunday cannot manufacture a seasonal transition;
- any future local history is bounded normalized regime-change history only.

At this point no additional pre-device defect is known. The remaining unknowns
are empirical source contracts and can only be closed by the read-only Termux
probe.


## First production probe results — 2026-10-07 20:30 CEST

The reviewed broad discovery probe completed successfully on the production
Termux device. It started and ended on production `main`
`b907b069fe6bba499b31ca129a818ebe2263bacb`, with an unchanged clean working
tree and exit code 0.

This run materially narrows the source problem.

### Mercadona

The official locator was directly reachable through the production Python/TLS
stack:

- HTTP success;
- `text/html`;
- about 41 KiB;
- no redirect.

The HTML itself publishes the retailer's schedule semantics, including
`Próximos festivos`, `Horario supermercado`, and codes including
`C: Festivo Cerrado` and `FA: Festivo abierto ...`.

More importantly, the page publishes the current data source:

`https://storage.googleapis.com/pro-bucket-wcorp-files/json/data.js?... `

plus a separate `data_total.js`.

The exploratory `?s=03140` request returned essentially the same page shell;
it is therefore not an accepted store-search API contract.

Next gate: read the page-linked exact `data.js` object, identify the Guardamar
record and prove its date/holiday schema. The Google Storage host is acceptable
only for the exact Mercadona-linked bucket/path discovered from the official
Mercadona page; it must not become a generic storage allowlist.

### masymas

The base official locator already proves the exact physical Guardamar point
without any third-party source:

- coordinates `38.09703600,-0.65669190`;
- address `AVDA. PUERTO, 18 Y 20`;
- locality `GUARDAMAR DEL SEGURA-ALICANTE`;
- phone `966727946`.

The locator's initial GET does not expose the reviewed
`propiedadestienda.php?Id=...` store identifier near that map record and does
not expose a useful date-specific exception schedule.

The HTML form explicitly POSTs `IdProvincia`. The next narrow probe should
therefore follow that existing first-party form contract for Alicante, discover
the Guardamar selector value deterministically, then read only the resulting
Guardamar row/detail. No numeric ID scan is justified.

### DIA

The exact store page for official store `36111` was directly reachable:

- HTTP success;
- `text/html`;
- about 29 KiB;
- no redirect.

This run disproves the earlier Next.js hypothesis. `__NEXT_DATA__` is absent.

The page template exposes exactly the concepts needed by the product:

- `horariosTienda2` for ordinary store hours;
- `festivosTienda` for special dates;
- `horariosAperturaFestivo` for holiday opening hours;
- an empty holiday-hours value renders `Cerrado`;
- `fechaApertura`, `inicioCierreTemp` and `finCierreTemp` model temporary
  closure/reopening state.

The same exact official page also publishes:

- `/tiendas/js/shopFinder.js?5.146.0`;
- `https://www.dia.es/clubdia/ES/tiendas.v2753.json.gz`.

The broad probe intentionally stopped after eight generic assets and therefore
did not fetch the more relevant `shopFinder.js`. This is now treated as a
discovery-budget limitation, not evidence that the contract is absent.

Next gate: fetch only the page-discovered `shopFinder.js` and versioned gzip
dataset, then extract exact store `36111` and the schedule/holiday fields.

### Probe-redaction correction

The broad probe's diagnostic redaction was narrower than its research note
claimed: a client-visible Google Maps browser key present in Mercadona HTML was
printed because the variable/query naming did not match the original
token-pattern allowlist.

This was not a bot credential and came from public client-side HTML, but the
research probe has nevertheless been hardened so a repeat run redacts
`keyGoogleMaps` and generic query `key=` values. The narrow exact-source
probe avoids printing the Mercadona page body at all.

### Architecture impact

The first production run makes the proposed architecture simpler, not more
complex:

- do not scrape rendered maps;
- do not execute JavaScript;
- do not retain the broad discovery asset walk in production;
- do not use Mercadona's `?s=03140` shell as a schedule source;
- do not use DIA Next.js machinery;
- do not brute-force masymas IDs.

The companion narrow probe is:

`research/2026-10-07-supermarket-hours-exact-source-probe.sh`

It tests only the three now-evidenced first-party contracts and remains
read-only. Production implementation is still gated on that probe.
