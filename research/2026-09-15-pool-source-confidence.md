# Municipal pool source confidence matrix

## Date

2026-09-15; runtime validation updated 2026-09-16.

## Status

Current investigation result for the municipal-pool pilot. Confidence is assigned
**per fact and per use case**. Seasonal pool activation is governed by a simple
product calendar rather than annual multi-source inference.

## Product rule

Use this default seasonal state unless a later explicit exception is learned:

- **16 June–15 September, inclusive: outdoor municipal pool active;**
- **16 September–15 June, inclusive: indoor/heated Manel Estiarte active.**

A real trusted operational exception can be implemented when it occurs. Do not
build an exception framework or multi-source season inference in advance.

Public cards normally hide source/operator provenance. External links are shown
only when the resident needs them for an action such as booking or registration.

## Source confidence matrix

| Source | Good for | Confidence | Do not use for |
| --- | --- | --- | --- |
| Ayuntamiento `Deportes` page (`/deportes-2/`) | official summer-season pattern; general municipal sports-price table | **Amber/Green by field** | current exceptional closures; assuming every dated 2023 sentence is current |
| Ayuntamiento current `Deportes Guardamar` landing page | official navigation; municipal sports context | **Green** | swimming-course catalogue when absent |
| Ayuntamiento telephone directory | indoor pool telephone `966 72 65 93` | **Green** | hours, prices, courses |
| Municipal lifeguard technical specification | procurement/staffing context, facility descriptions | **Green only for contract facts** | operational pool season, public opening hours, `open now`, seasonal switch dates |
| Sporttia Guardamar public page | current municipal sports spaces; pool lanes; booking entry point; listed municipal programme data | **Green for fields actually exposed** | proving physical open/closed status; swimming catalogue if absent; unvalidated live lane availability |
| Swimming-course concession file `8671/2024` | proves an officially contracted municipal swimming service and identifies the internal operator | **Green internally** | resident-facing schedules/prices/availability |
| SimplyBook `/v2/service/` + `/v2/provider/` | small current public catalogue structure and service/provider relationships | **Green/Amber** | claiming a visible service is currently bookable or assigning season from copied descriptions alone |
| SimplyBook availability endpoints | one-off validation of real future availability | **Amber, bounded use only** | N-per-service polling; treating `200` alone as success |
| Old municipal `VERANO 2023` schedule block | supports the normal summer pattern and historical public-hours context | **Amber as corroboration** | exceptional current-day status or current September-free-entry claim |
| Community/group messages | discovery signal | **Red as evidence** | publication of exceptions without confirmation |

## 2026-09-16 SimplyBook runtime validation

The production Termux runtime made fresh requests without prior page bootstrap,
cookies, a cookie jar, CSRF headers, or a browser.

- `GET /v2/service/` returned `200 application/json`.
- `GET /v2/provider/` returned `200 application/json`.
- Both responses set a cookie, but the successful request did not require one.
- `/booking/time-slots/` and `/booking/working-days/` also accepted stateless
  requests during the investigation.

The current mapping showed services `2–10` attached to July/August fortnight
packages. Services `11–12` were named `Aquagym Julio` / `Aquagym Agosto` yet
attached to provider `Piscina climatizada`. This proves that copied service text
and provider names cannot independently establish season or venue.

A future-range `working-days` check from 2026-09-16 through 2027-03-15 found no
active days for services `2–11`. During the burst, the next request returned:

- HTTP status `200`;
- `Content-Type: text/html`;
- a `Please wait` balancer/queue page.

Therefore the implementation must require the expected MIME type and valid JSON,
and must not translate an HTML queue response into an empty catalogue or removed
programme. The burst also demonstrates why availability must not be polled once
per service.

The frontend contains `/booking/time-flexible-multi/` and code paths capable of
passing multiple service/provider IDs, but its exact production request/response
contract remains unvalidated. The first implementation deliberately does not
guess it. If one batch request cannot be validated later, automatic availability
remains out of scope rather than falling back to N requests.

## Fact confidence matrix

| Fact | Confidence / status | Basis | Publication decision |
| --- | --- | --- | --- |
| Outdoor pool season is **16 June–15 September** | **Product default / High** | owner-confirmed operating model plus official municipal summer pattern | use automatically unless an explicit exception overrides it |
| Indoor/heated pool season is **16 September–15 June** | **Product default / High** | owner-confirmed mutually exclusive seasonal operation | use automatically unless an explicit exception overrides it |
| Both indoor and outdoor pools operate simultaneously | **False for the product model** | owner-confirmed operation | never present simultaneous availability |
| Outdoor public-entry price is **2 € / day** | **Medium/High** | historic and undated official municipal material | not needed in the first card; revalidate before adding |
| Outdoor pool is **free in September** | **Low/Medium** | found only in dated `VERANO 2023` material | do not publish as current fact |
| Exact public opening hours | **Unverified for current public use** | current accepted sources do not establish them cleanly | omit |
| Indoor pool phone is **966 72 65 93** | **High** | current official municipal telephone directory | safe to publish |
| General/outdoor sports-complex phone | **Conflicting current/older municipal material** | older material gives `966 72 63 35`; another current municipal phone page labels the complex with `965 35 76 93` | omit from the first Polideportivo/outdoor cards |
| Manel Estiarte is the municipal heated/indoor pool | **High** | official municipal material | safe to publish |
| Outdoor pools are inside Polideportivo Municipal | **High** | official municipal material | safe to publish |
| Very-young-child `Bebés`/`Peques` swimming is summer-only | **Product rule / High** | owner-confirmed use of shallow outdoor pool | do not manufacture a winter indoor equivalent |
| A visible SimplyBook service means registration is open / spaces exist | **Low** | expired summer entries remain visible; future working days were empty | never use as an automatic trigger without validated availability |

## Minimal source policy for implementation

1. derive the active facility from the fixed default calendar;
2. publish only stable, independently supported facility facts;
3. fetch the two small SimplyBook catalogue endpoints sequentially and keep only
   a normalized last-good baseline;
4. accept only the exact HTTPS host, bounded `application/json`, valid schema and
   internally known references;
5. treat source failure, HTML queue pages and malformed JSON as no observation;
6. do not issue public programme-change alerts from catalogue visibility alone;
7. do not make N availability requests per service;
8. keep one direct booking link in the swimming card as the action the bot cannot
   perform itself.
