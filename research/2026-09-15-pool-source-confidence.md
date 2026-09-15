# Municipal pool source confidence matrix

## Date

2026-09-15

## Status

Current investigation result for the municipal-pool pilot. Confidence is assigned
**per fact and per use case**. Seasonal pool activation is now governed by a
simple product calendar rather than by annual multi-source inference.

## Product rule

Do not build a multi-source inference engine for ordinary pool operations.

Use this default seasonal state unless a later explicit exception is learned:

- **16 June–15 September, inclusive: outdoor municipal pool active;**
- **16 September–15 June, inclusive: indoor/heated Manel Estiarte active.**

If a trusted operational notice later gives an exceptional closure/opening or a
different switch date, apply that exception and then return to the default
calendar.

Public cards should normally hide source/operator provenance. External links are
shown only when the resident needs them for an action such as booking or
registration.

## Source confidence matrix

| Source | Good for | Confidence | Do not use for |
| --- | --- | --- | --- |
| Ayuntamiento `Deportes` page (`/deportes-2/`) | official summer-season pattern; general municipal sports-price table; `Piscina descubierta 2 € baño/día` | **Amber/Green by field** | `open now` exceptions; assuming every dated 2023 sentence is current |
| Ayuntamiento current `Deportes Guardamar` landing page | official navigation; Sporttia as the municipality's schedule/booking surface | **Green** | detailed swimming-course catalogue when absent |
| Ayuntamiento telephone directory | pool telephone `966 72 65 93` | **Green** | hours, prices, courses |
| Municipal lifeguard technical specification | procurement/staffing context, facility descriptions | **Green only for contract facts** | operational pool season, public opening hours, `open now`, seasonal switch dates |
| Sporttia Guardamar public page | current municipal sports spaces; eight pool lanes; booking entry point; listed municipal programme registration data | **Green for fields actually exposed** | proving physical open/closed status; swimming-course catalogue if absent; unvalidated live lane availability |
| Swimming-course concession file `8671/2024` | proves that municipal swimming courses are an officially contracted service and identifies the internal operator | **Green internally** | resident-facing schedules/prices/availability |
| Booking.page / SimplyBook swimming catalogue | discovery of course families, age labels, some schedules/prices and direct booking workflow | **Amber** | unattended current-state monitoring until freshness and contradictions are resolved |
| Old municipal `VERANO 2023` schedule block | supports the normal summer pattern and provides historical public-hours context | **Amber as corroboration** | exceptional current-day status or current September-free-entry claim |
| Community/group messages | discovery signal | **Red as evidence** | publication of exceptions without confirmation |

## Fact confidence matrix

| Fact | Confidence / status | Basis | Publication decision |
| --- | --- | --- | --- |
| Outdoor pool season is **16 June–15 September** | **Product default / High** | owner-confirmed operating model plus official municipal summer pattern | use automatically unless an explicit exception overrides it |
| Indoor/heated pool season is **16 September–15 June** | **Product default / High** | owner-confirmed mutually exclusive seasonal operation | use automatically unless an explicit exception overrides it |
| **15 September 2026 is the final outdoor-pool day** | **Accepted by product rule** | default calendar | safe to use for normal seasonal state |
| **Indoor pool is active from 16 September 2026** | **Accepted by product rule** | default calendar | safe to use for normal seasonal state |
| Both indoor and outdoor pools operate simultaneously | **False for the product model** | owner-confirmed operation | never present simultaneous availability |
| Outdoor public-entry price is **2 € / day** | **Medium/High** | appears in the 2023 seasonal block and again in a separate undated official municipal sports-price table | reasonable card candidate; keep separate from season-state logic |
| Outdoor pool is **free in September** | **Low/Medium** | found only in the dated `VERANO 2023` block | do not publish as current fact without newer confirmation |
| September public hours are exactly `11:30–14:00` and `17:00–20:00` weekdays | **Medium/Low** | published in the 2023 block; no accepted current operational-hours source | do not present as guaranteed current hours yet |
| Indoor public hours are exactly Mon–Fri `09:00–22:00`, Sat `09:00–20:00` | **Unverified for public use** | lifeguard contract is explicitly excluded from operational-calendar decisions | do not publish until a proper pool/Deportes source supports them |
| Pool phone is **966 72 65 93** | **High** | current official municipal telephone directory | safe to publish |
| Manel Estiarte is the municipal heated/indoor pool | **High** | official municipal material | safe to publish |
| Outdoor pools are inside Polideportivo Municipal, Avenida de Europa S/N | **High** | official municipal/procurement material | safe to publish |
| Sporttia exposes eight reservable pool lanes | **High for catalogue fact** | current Sporttia public page | safe to mention if useful; does not prove live availability |
| Very-young-child `Bebés`/`Peques` swimming is summer-only | **Product rule / High** | owner-confirmed use of shallow outdoor pool | do not create a winter indoor equivalent |
| A Booking.page `Book now` button means registration is currently open / spaces exist | **Low** | expired summer entries remain visible and catalogue copy contains contradictions | never use as an automatic trigger without validation |

## Lifeguard specification: explicit exclusion from operating-state logic

The municipal lifeguard procurement document must **not** be used to decide:

- which pool is currently active;
- when the indoor or outdoor season starts or ends;
- public opening hours;
- whether the pool is open now.

It describes contractual staffing/coverage requirements, not the operating
calendar we use for residents. Its nominal indoor `1 January–31 December` clause
is incompatible with the confirmed seasonal operating model and is therefore a
clear reason to keep it out of this decision path.

It may still be retained as internal procurement/infrastructure context where
that is useful.

## Minimal source policy for implementation

For the first pool version:

1. derive the active facility from the fixed default calendar: outdoor 16 Jun–15
   Sep, indoor 16 Sep–15 Jun;
2. allow a specific trusted operational announcement to override the calendar
   when an exceptional closure/opening occurs;
3. use Ayuntamiento pages for stable facility/contact/tariff facts that are
   clearly supported;
4. use Sporttia only for the fields it directly exposes;
5. use the swimming booking surface for programme/action details only where the
   information is current enough to trust.

Do not build monitoring of multiple publishers just to rediscover the normal
season dates every year.
