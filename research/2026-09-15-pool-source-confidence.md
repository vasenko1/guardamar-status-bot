# Municipal pool source confidence matrix

## Date

2026-09-15

## Status

Current investigation result for the municipal-pool pilot. This note supersedes
any earlier blanket statement that a whole source is simply "trusted" or
"stale". Confidence is assigned **per fact and per use case**.

## Product rule

Do not build a multi-source inference engine for ordinary pool operations. Use a
small number of direct facts that can be supported clearly. A source may be
excellent for one fact and unsuitable for another.

Public cards should normally hide source/operator provenance. External links are
shown only when the resident needs them for an action such as booking or
registration.

## Source confidence matrix

| Source | Good for | Confidence | Do not use for |
| --- | --- | --- | --- |
| Ayuntamiento `Deportes` page (`/deportes-2/`) | official historical summer schedule; general municipal sports-price table; `Piscina descubierta 2 € baño/día` | **Amber/Green by field** | live open/closed status; assuming every dated 2023 sentence is current |
| Ayuntamiento current `Deportes Guardamar` landing page | official navigation; Sporttia as the municipality's schedule/booking surface | **Green** | exact pool hours or seasonal switch dates |
| Ayuntamiento telephone directory | pool telephone `966 72 65 93` | **Green** | hours, prices, courses |
| Current municipal lifeguard technical specification | facility identity; indoor/outdoor locations; planned lifeguard coverage; outdoor coverage period through 15 September | **Green for contract facts, Amber for operational baseline** | `open now`; guaranteed public opening hours; proving exact seasonal switch in actual operation |
| Sporttia Guardamar public page | current municipal sports spaces; eight pool lanes; booking entry point; listed municipal programme registration data | **Green for fields actually exposed** | proving that the pool is physically open now; swimming-course catalogue if absent; unvalidated live lane availability |
| Swimming-course concession file `8671/2024` | proves that municipal swimming courses are an officially contracted service and identifies the current internal operator | **Green internally** | resident-facing schedules/prices/availability |
| Booking.page / SimplyBook swimming catalogue | discovery of course families, age labels, some schedules/prices and direct booking workflow | **Amber** | unattended current-state monitoring until freshness and contradictions are resolved |
| Old municipal `VERANO 2023` schedule block | historical season pattern and cross-check | **Amber as corroboration only** | sole source for 2026 public claims |
| Community/group messages | discovery signal | **Red as evidence** | publication without confirmation |

## Fact confidence matrix

| Fact | Confidence on 2026-09-15 | Evidence / limitation | Publication decision |
| --- | --- | --- | --- |
| Outdoor municipal pool normally uses a summer season ending **15 September** | **High** | the official 2023 pool block says 16 Jun–15 Sep; the current lifeguard specification independently schedules outdoor coverage through 15 Sep | safe as the **normal/planned season boundary**, not as proof of an exceptional same-day change |
| **15 September 2026 is definitely the final actual public day** | **Medium** | strong planned-boundary evidence, but no fresh 2026 operational notice explicitly says "last day today" | do not phrase as a live fact unless directly confirmed |
| **Indoor pool opens/returns on 16 September 2026** | **Medium/Low** | consistent with local seasonal operation supplied by project owner, but no fresh official 2026 source explicitly gives 16 Sep reopening | do not publish unqualified yet |
| Outdoor public-entry price is **2 € / day** | **Medium/High** | appears in the 2023 seasonal block and again in a separate undated official municipal sports-price table | reasonable card candidate, but not a legally guaranteed 2026 tariff until fresher tariff evidence is found |
| Outdoor pool is **free in September** | **Low/Medium** | found only in the dated `VERANO 2023` block | do not publish as current 2026 fact |
| September public hours are exactly `11:30–14:00` and `17:00–20:00` weekdays | **Medium/Low for public hours** | 2023 page says this; current lifeguard specification also covers these hours but additionally covers 20:00–21:00 Mon/Wed/Fri and is a staffing contract, not a public-hours notice | do not present as guaranteed live opening hours |
| Indoor hours are exactly Mon–Fri `09:00–22:00`, Sat `09:00–20:00` | **Low for public hours** | current technical specification says this for lifeguard coverage but also nominally lists indoor coverage Jan–Dec, which does not match the known seasonal operating model | internal baseline only |
| Pool phone is **966 72 65 93** | **High** | current official municipal telephone directory | safe to publish |
| Manel Estiarte is the municipal heated/indoor pool | **High** | official municipal and procurement documents | safe to publish |
| Outdoor pools are inside Polideportivo Municipal, Avenida de Europa S/N | **High** | current technical specification | safe to publish |
| Sporttia exposes eight reservable pool lanes | **High for catalogue fact** | current Sporttia public page | safe to mention if useful; does not prove live availability |
| Swimming programmes exist for children/adults and are operated under a current municipal concession | **High internally** | current concession file | public cards should show programmes, not operator/procurement details |
| A Booking.page `Book now` button means registration is currently open / spaces exist | **Low** | expired summer entries remain visible and catalogue copy contains contradictions | never use as an automatic trigger without deeper validation |

## Important interpretation of the lifeguard specification

The current procurement technical specification is authoritative about what the
contract asks the lifeguard provider to cover, but it is **not the same thing as
a live operating calendar**.

It says:

- indoor pool: nominal coverage Jan 1–Dec 31, Mon–Fri 09:00–22:00, Sat 09:00–20:00;
- outdoor pools: Jun 16–30 and Sep 1–15, then Jul 1–Aug 31 with longer hours;
- all schedules are initial and may vary according to Sports Department needs,
  including closure.

Because the indoor Jan–Dec clause conflicts with the locally observed seasonal
model (one pool active by season, the other drained), the contract must not be
used to infer actual simultaneous operation.

## Minimal source policy for implementation

For the first pool version, avoid a monitoring framework across many publishers.
Use only:

1. current Ayuntamiento/Sports pages for stable facility facts and tariff fields
   that are clearly presented as general information;
2. Sporttia for fields it currently exposes structurally;
3. the swimming booking surface only for current programme/action details after
   a manual or technical freshness check;
4. explicit current official notices if a closure/opening/change is actually
   published.

If a simple operational fact cannot be obtained confidently from one clear
current source, omit it rather than infer it from several weak signals.

## 16 September publication gate

Do **not** automatically publish `С сегодняшнего дня работает крытый бассейн`
solely from the 15 September summer boundary.

That statement becomes Green when one of the following is obtained:

- a current Ayuntamiento/Deportes notice;
- a current pool/sports-facility notice;
- a current operational notice in the booking surface;
- direct confirmation from the municipal pool/Deportes that the indoor pool is
  open from 16 September.

Until then the normal season boundary is well supported, but the exact 2026
indoor reopening date remains unconfirmed.
