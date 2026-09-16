# Guardamar Municipal Pools and Swimming Courses

## Question

Can Guardamar's municipal pools and swimming courses support the proposed linked
`Places` + `Activities and clubs` guide, and can the underlying sources be
monitored safely enough to publish change notifications?

## Investigation date

2026-09-15

## Status

Pre-development investigation only. This note records source capabilities,
current facts, freshness problems, and implementation gates. It is not approval
to publish every discovered field or to automate a source that has not passed
freshness and access validation.

The pilot deliberately distinguishes four information types:

1. a durable **place** (pool/facility);
2. a recurring **activity** (swimming course/programme);
3. a date-specific **event** (competition, open day, etc. — existing event
   pipeline);
4. a material **change** that may deserve a separate public notification.

## Entities found

### Piscina Climatizada Manel Estiarte

A municipal indoor swimming pool. Official municipal material has used the
location `Avda. de Cervantes s/n` (some sports/booking systems reference the
wider municipal sports complex at Avenida Europa). The municipal telephone
list gives the pool phone as `966 72 65 93`.

Official contact source:

- https://www.guardamardelsegura.es/services/telephones-of-interest/

Sporttia exposes eight separately reservable `Calle de piscina` spaces for the
Guardamar municipal sports centre and sends users to its online booking UI.

Source:

- https://sporttia.com/centros/ayuntamiento-guardamar-del-segura
- https://play.sporttia.com/sportcenters/1509/home

### Piscinas Descubiertas Municipales

The outdoor municipal pools are distinct seasonal facilities inside the
Polideportivo Municipal. The current lifeguard technical specification describes
two water surfaces (312.5 and 100 m2) and seasonal lifeguard coverage.

The old municipal sports page still exposes `VERANO 2023` opening hours and a
`2 €` public-entry price. Those fields are explicitly historical and MUST NOT
be treated as current 2026 facts.

Source:

- https://www.guardamardelsegura.es/deportes-2/

## Current municipal swimming-course operator

Procurement file `8671/2024` covers operation of swimming courses in the indoor
and outdoor municipal pools. It was awarded on 2026-03-16 to:

`AQUALIDER ACTIVIDADES ACUATICAS S.L.`

Key procurement facts found in the published record:

- base budget: 38,000 EUR;
- estimated value: 339,360 EUR;
- awarded amount: 33,050 EUR;
- three bidders;
- contract duration: two years;
- a possible single two-year extension is reported by procurement aggregators.

Primary/secondary references used during investigation:

- https://contratos.gobierto.es/licitaciones/5015395?locale=es
- https://www.cashstalker.com/licitacion/2ceebaff-240f-4529-8287-7a7178ee173e

A separate 2026 minor contract also shows Aqualider providing a swimming
programme for people with functional diversity. That is evidence that special
programmes can exist outside the main public catalogue; it is not evidence that
the same programme is currently open for enrolment.

## Source inventory

### 1. Ayuntamiento sports landing page

The municipality's current sports landing page explicitly links residents to
Sporttia for consultation of sports-space schedules.

- https://www.guardamardelsegura.es/deportes-guardamar/

Use: authority/ownership context and navigation.

Do not use it as a complete current pool timetable: the separate pool page is
stale.

### 2. Sporttia public centre page

Public URL:

- https://sporttia.com/centros/ayuntamiento-guardamar-del-segura

Observed current capabilities:

- ordinary public HTML is readable without login;
- centre/location metadata is exposed;
- 15 sports spaces are listed, including eight pool lanes;
- online reservation is explicitly supported;
- the page currently exposes 15 municipal sports activities with registration
  status, activity dates, registration windows, age/year groups, schedules,
  venues, and requirements where configured;
- current 2026/27 municipal activities show real registration windows such as
  `01/09/26 al 30/09/26`.

Important limitation for this pilot:

**The current public Guardamar Sporttia page does not expose the municipal
swimming-course catalogue.** It exposes pool-lane reservation plus other
municipal sports schools/activities. Swimming courses are currently surfaced by
Aqualider/SimplyBook instead.

The direct reservation UI at:

- https://play.sporttia.com/sportcenters/1509/home

is a client-rendered application. Its lane availability/slot data was not
validated as a stable machine-readable public endpoint in this investigation.
No documented public Sporttia API was found.

Assessment:

- durable facility metadata: **green**;
- coarse monitoring of the public centre/activity catalogue: **green/amber**;
- exact live lane availability: **not yet validated**;
- swimming-course catalogue: **not present here at investigation time**.

### 3. Aqualider / SimplyBook public booking page

Public catalogue discovered through Booking.page:

- https://booking.page/en/company/page/aqualidernatacion
- provider link: https://aqualidernatacion.simplybook.it/

The page is clearly Guardamar-specific and currently exposes the following
swimming services.

#### Natación Bebés

- duration: 45 minutes;
- age: 8–36 months;
- described as indoor/heated pool;
- parent participation is described;
- no reliable current Guardamar price or exact weekly timetable surfaced in
  the indexed public text.

#### Natación Peques (Mañanas)

- duration: 45 minutes;
- age: 3+;
- described as summer/outdoor pool;
- flexible weekly schedules/monthly packs are mentioned;
- no exact current price or timetable surfaced.

#### Natación Peques (Tardes)

- duration: 45 minutes;
- age: 3+;
- the title says `Piscina climatizada`;
- the description says sessions are in `piscina al aire libre`.

This is an internal source contradiction and MUST NOT be normalized by guessing.

#### Infantiles 1

- duration: 45 minutes;
- age: 7+;
- summer/outdoor pool;
- published times: `09:00–09:45` and `09:45–10:30`.

#### Infantiles 2

- duration: 45 minutes;
- age: 7+;
- summer/outdoor pool;
- published start times: `10:00`, `11:15`, `12:00`.

The source itself publishes those times; the application must not silently
"correct" them.

#### Infantiles 3

- duration: 45 minutes;
- age: 7+;
- heated/indoor pool;
- published start times: `17:30`, `18:15`, `19:00`.

#### Adultos tecnificación (Mañanas)

- duration: 45 minutes;
- age: 16+;
- intermediate/advanced technique/performance programme;
- described as morning sessions;
- no exact current Guardamar price/timetable surfaced.

#### Adultos tecnificación (Tardes)

- duration: 45 minutes;
- the title says afternoon but the copied description says `horario matutino`.

This is another source contradiction; exact period must not be inferred.

#### Adultos terapéutica

- duration: 45 minutes;
- adult therapeutic swimming/mobility programme.

The provider makes health-related benefit claims in its marketing text. The bot
should not reproduce medical-treatment claims; a guide card should use neutral
programme wording and link to the provider for details.

#### Aquagym Julio

- duration: 45 minutes;
- published price: `50 €` for July.

#### Aquagym Agosto

- duration: 45 minutes;
- published price: `50 €` for August.

#### Seasonal provider/package labels still visible on 2026-09-15

- Primera quincena de Julio: `49 €`, 11 sessions;
- Segunda quincena de Julio: `49 €`, 11 sessions;
- Primera quincena de Agosto: `45 €`, 10 sessions;
- Segunda quincena de Agosto: `45 €`, 10 sessions;
- `Piscina climatizada`.

These July/August entries remain visible after their season. Their continued
presence proves that **visibility is not a safe synonym for current enrolment
availability**.

The Booking.page also displays `Book now`, but because expired seasonal entries
remain visible and slot/calendar state could not be validated, `Book now` alone
MUST NOT trigger a public `registration open` notification.

A direct automated fetch of the Booking.page URL returned HTTP 403 in this
investigation environment even though search indexing exposes the catalogue.
That makes generic HTML polling unsuitable for production until access is
validated from the actual runtime and a stable permitted data surface is found.

Assessment:

- useful human link-out: **green**;
- curated course inventory: **amber**;
- automatic registration-open detection: **red until validated**;
- automatic price/schedule change alerts: **red until validated**.

### 4. SimplyBook API

SimplyBook has an official API with services, providers, public booking methods,
and availability methods. However the official authentication flow requires the
company login plus an API key, and the API key is obtained through the account's
API plugin.

Documentation:

- https://simplybook.me/en/api/developer-api/tab/doc_api

Therefore the existence of the SimplyBook API does **not** give this project an
unauthenticated supported integration with Aqualider. Do not scrape private API
calls or attempt to bypass access controls.

A future supported path would be either:

1. Aqualider voluntarily provides API access; or
2. the public booking application exposes a stable public data surface that can
   be used without credentials and is validated as appropriate for automated
   reading.

### 5. Municipal pool hours and public admission price

The municipal page still visible in 2026 explicitly labels its outdoor-pool
schedule `VERANO 2023` and gives a 2 EUR entry price. It is historical evidence,
not a current tariff.

The current lifeguard technical specification provides this baseline coverage:

- indoor Manel Estiarte: Jan 1–Dec 31, Mon–Fri 09:00–22:00, Sat 09:00–20:00;
- outdoor pools, Jun 16–30 and Sep 1–15: weekdays 11:30–14:00 and
  17:00–20:00, with an additional hour to 21:00 Mon/Wed/Fri; weekends
  11:30–20:00;
- outdoor pools, Jul 1–Aug 31: weekday coverage 09:00–20:00, with an
  additional hour to 21:00 Mon/Wed/Fri; weekends 11:30–20:00.

But the same specification explicitly says these schedules are initially set
and may vary according to the Sports Department's needs, **including closure of
the facilities**.

Primary technical specification:

- https://contrataciondelestado.es/wps/wcm/connect/PLACE_es/Site/area/docAccCmpnt?DocumentIdParam=157ecced-864a-45bc-9dd8-4c8bf9e2c7d0&cmpntname=GetDocumentsById&source=library&srv=cmpnt

Therefore:

- contract hours may be used as internal baseline/plausibility evidence;
- they MUST NOT power `open now`, guaranteed daily hours, or closure/opening
  notifications;
- no sufficiently fresh authoritative 2026 public-admission tariff was found in
  this investigation.

### 6. 2026 Manel Estiarte infrastructure works

Guardamar procured renewal of the water-heating and climate systems with
renewable thermal energy and rooftop photovoltaic support (file `2031/2025`).
The procurement specifies approximately 90 days / three months of works.

This is useful source context, but procurement of works does not prove a public
closure or a specific user-facing operational impact. Do not publish a closure
unless a current operational/municipal notice explicitly establishes it.

## Safe fields for a first place card

| Field | State | Notes |
| --- | --- | --- |
| `Piscina Climatizada Manel Estiarte` name | safe | official municipal usage |
| municipal ownership/context | safe | municipality + procurement |
| pool phone `966 72 65 93` | safe | municipal phone directory |
| pool-lane reservation link | safe | Sporttia |
| eight Sporttia pool lanes | safe | current public Sporttia page |
| Aqualider as municipal swimming-course operator | safe | 8671/2024 award |
| Aqualider course-information/booking link | safe | public operator page |
| exact current public opening hours | **not safe yet** | contract is only baseline; website page is stale |
| current casual-entry price | **not safe yet** | only stale 2023 municipality page found |
| `open now` status | **not safe** | no authoritative live source |
| current free lane/slot counts | **not validated** | Sporttia SPA needs a separate technical test |

## Safe fields for a first swimming-activities card

The current Aqualider catalogue supports a curated overview that swimming
programmes exist for babies, children and adults, with the specific age and
schedule facts listed above where the provider actually publishes them.

Do not yet claim:

- that registration is currently open for a specific course;
- that a `Book now` button proves available places;
- current prices for services where the page does not expose a Guardamar price;
- current exact schedule when the text is contradictory or clearly seasonal;
- that an old summer service remains active merely because it remains indexed.

## Proposed Telegram information shape (provisional)

Do not create a card per Aqualider service yet. Start with the smallest useful
message graph and split only when the content becomes too large.

### Place branch

`📌 Полезное о Гуардамаре`

→ `📍 Места`

→ a sports/pools grouping only when more than one useful place makes that
subdivision worthwhile

→ `🏊 Piscina Climatizada Manel Estiarte`

The place card should contain durable facility facts, phone, lane-booking link,
and a link to swimming activities. It should omit unverified current hours and
casual-entry price.

A separate outdoor-pool place card is reasonable once its current seasonal
status can be sourced reliably.

### Activity branch

`📌 Полезное о Гуардамаре`

→ `🎓 Занятия и секции`

→ `🏊 Плавание`

The first swimming card should be an overview of current supported programme
families with one authoritative operator link, plus a backlink to the pool
place. Split into child cards only if the list cannot stay readable or if
separate stable deep links become useful.

### Existing event branch remains separate

A competition, one-off open day, exhibition, or other dated pool event remains
an event and must use the existing event pipeline. It does not become a
permanent activity merely because it happens at a pool.

## Change-notification policy for the pilot

Potentially public/actionable:

- a registration window is proven to have opened;
- a new recurring programme is introduced;
- an already published price, schedule, age rule, or venue materially changes;
- an authoritative current source announces a closure/opening or material
  operating-hours change.

Normally silent:

- spelling/copy corrections;
- phone/link maintenance;
- removal of an expired July/August package after the fact;
- HTML/layout changes without a semantic user impact;
- changes that cannot be proven semantically from the source.

As with transport notifications, the first successful automated observation
should establish a baseline silently rather than announce the entire existing
catalogue as "new".

## Monitoring feasibility

| Source/data | Automated fetch today | Semantic quality | Pilot status |
| --- | --- | --- | --- |
| Sporttia public centre HTML | yes | strong for listed fields | good candidate |
| Sporttia direct live booking slots | not validated | potentially strong | investigate separately |
| Aqualider Booking.page HTML | 403 in direct fetch | rich but stale/inconsistent | do not automate yet |
| SimplyBook supported API | requires operator API key | strong if access exists | unavailable without cooperation |
| Ayuntamiento old pool page | yes | stale (`VERANO 2023`) | never use as current |
| lifeguard procurement schedule | yes | authoritative baseline, not live | internal evidence only |
| municipal/operator explicit notices | source-specific | potentially authoritative | use when a stable source is found |

## Next technical experiment

Before any Aqualider monitor is implemented:

1. Test the public Aqualider/SimplyBook booking flow from the real production
   environment (Termux) and a normal browser, without authentication bypass.
2. Inspect whether the public page contains stable embedded JSON or calls a
   documented/permitted unauthenticated public endpoint for service catalogue,
   calendar, price, and availability.
3. Record exact sample payloads and stable identifiers for services/providers.
4. Verify that an expired seasonal service can be distinguished from an active
   registration window.
5. Verify at least one real change across two snapshots before designing a
   notification diff.
6. If no stable public data surface exists, keep Aqualider as a human-facing
   link and use curated/manual review rather than brittle scraping.

## Implementation gate

Do not implement the generic city guide, a generic activity database, or an
Aqualider change monitor from this note alone.

The pilot is ready for UX/card design because enough trustworthy durable facts
exist. Automatic swimming registration/price/schedule notifications remain
blocked until the Aqualider access/freshness experiment above passes.
