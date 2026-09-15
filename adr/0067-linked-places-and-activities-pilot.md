# 0067: Pilot linked places and recurring activities with municipal swimming

- Status: Proposed
- Date: 2026-09-15

## Context

The pinned `Полезное о Гуардамаре` graph currently exposes durable high-value
information such as cameras and transport. The next product gap is practical
city information that is neither a one-day event nor a transport/weather
status: places residents can use and recurring activities they can join.

A pre-development investigation used Guardamar's municipal pools and swimming
courses as a vertical slice. It found that the same real-world subject spans
several information lifecycles:

- a municipal pool is a durable place/facility;
- swimming courses are recurring activities with age, schedule, price, season,
  venue, and registration state;
- competitions/open days are date-specific events;
- a registration opening, seasonal facility switch, closure, or material
  schedule change may justify a separate public update.

The source landscape is uneven. Sporttia exposes strong current structured
public data for municipal sports facilities and many municipal activities, but
its current Guardamar public page does not expose the swimming-course catalogue.
The current swimming-course booking/provider surface exposes a rich public
SimplyBook/Booking.page catalogue, but the page retains expired seasonal entries
and contains contradictory copied descriptions. Current exact public hours and
some prices still require field-specific validation.

A product clarification on 2026-09-15 established that the identity of an
underlying service operator is implementation/source provenance, not resident-
facing content. Residents need the service facts, not the procurement/operator
relationship. Source discovery is part of the project's competitive advantage
and should normally remain internal.

The project owner also established the municipal pool operating model:

- in summer only the outdoor municipal pool operates;
- in winter only the indoor/heated municipal pool operates;
- the two pools are not active in parallel; the off-season pool is drained/not
  in service;
- very-young-child `Bebés` / `Peques` swimming uses the shallow outdoor pool and
  is therefore summer-only;
- adult and older-child programmes may exist in either seasonal period, but
  their venue follows the pool active for that season.

Rather than building a recurring multi-source inference process for normal
season changes, the product will use a fixed default calendar and allow explicit
exceptions to override it when needed.

See `research/2026-09-15-guardamar-municipal-pools-and-swimming.md`,
`research/2026-09-15-pool-pilot-product-clarifications.md`, and
`research/2026-09-15-pool-source-confidence.md`.

## Decision

If this pilot is accepted for implementation:

- Keep `📌 Полезное о Гуардамаре` as the user-facing root. Do **not** add an
  intermediate `Справочник Гуардамара` layer.
- Add two conceptually separate linked branches when there is enough verified
  content to justify them:
  - `📍 Места` for durable facilities/organizations;
  - `🎓 Занятия и секции` for recurring programmes independent of whether the
    operator is municipal or private.
- Use municipal swimming as the first vertical slice instead of first building a
  generic city database.
- Model information according to lifecycle, not topic taxonomy:
  - durable place facts belong to a place card;
  - recurring programme facts belong to an activity card;
  - one-off dated occurrences remain in the existing event pipeline;
  - material actionable changes may create separate public notifications.
- For seasonal facilities, keep **facility state** separate from **programme
  availability**.
- Use this default automatic facility calendar:
  - **16 June through 15 September, inclusive → outdoor municipal pool active;**
  - **16 September through 15 June, inclusive → indoor/heated Manel Estiarte
    active.**
- Do not require a fresh annual announcement to perform the normal 16 June / 16
  September switch. This is a product rule.
- A specific trusted operational announcement may override the default calendar
  for an exceptional closure, delayed opening, early switch, maintenance period,
  or other temporary deviation. After the exception ends, resume the default
  calendar.
- The municipal lifeguard contract is **not** an accepted source for pool
  operating state, season dates, or public opening hours. Do not use its nominal
  indoor `1 January–31 December` coverage to infer pool availability.
- Do not infer that a programme survives a seasonal switch. A summer programme
  and a winter programme must each be supported by current programme evidence
  even when they have similar names.
- Treat very-young-child `Bebés` / `Peques` swimming as summer-only because it
  uses the shallow outdoor pool; do not manufacture a winter indoor equivalent
  from contradictory copied provider text.
- A place and an activity may link to each other without duplicating their full
  content. For example, the active pool card may link to `Плавание`, and the
  swimming card may link back to the relevant pool.
- Municipal/private ownership is metadata, not a top-level navigation branch.
- The identity of the underlying operator/provider is **not** public guide
  content unless the resident genuinely needs that identity to complete an
  action. Do not publish procurement/operator explanations merely because the
  project uses them internally as evidence.
- Source URLs are internal by default. If the bot can safely reproduce current
  useful facts itself, the public card should present those facts directly
  without exposing the discovery/source chain. Add an external link only when it
  provides a user action the bot cannot perform itself, such as booking,
  registration, payment, or another necessary official workflow. Prefer a direct
  action link over a generic provider/home page.
- Topic groupings such as sport, culture, children, education, or museums are
  added only when real content volume requires another navigation level. Do not
  create empty category trees in advance.
- Preserve the existing evidence-first/fail-closed rule for fields other than the
  accepted season calendar: a public field must have enough evidence and
  freshness for the claim being made.
- Treat the Sporttia public centre page as an automated source only for fields it
  currently exposes reliably. Live slot availability remains a separate
  validation problem.
- Treat the swimming-course booking/provider surface as an internal curated
  research source until stable permitted automated access and lifecycle
  semantics are validated. A visible `Book now` button alone does not prove
  current registration availability.
- Do not copy contradictory programme text into the public guide. Programme
  venue, age, schedule, and price must come from a current internally consistent
  source state.
- A change in stored/source data does not automatically produce a public
  message. Public change notifications require material user impact: a proven
  registration opening, new recurring programme, explicit exceptional facility
  change, material price/schedule/venue change, or authoritative closure/opening
  notice.
- The normal June/September seasonal switch may update the relevant pool card and
  state automatically from the calendar; it does not require a monitoring
  framework across several sources.
- The first successful observation of any automated programme/source feed
  establishes a silent baseline; it must not announce the pre-existing catalogue
  as new.
- Reuse the existing linked pinned-message machinery. Do not introduce a generic
  CMS, ontology framework, universal place database, or new persistence stack
  for this pilot unless the vertical slice demonstrates a concrete need.

## Consequences

- The user-facing navigation remains shallow: `Полезное` directly exposes
  durable product branches instead of adding a redundant `Справочник` level.
- Places and recurring activities can grow independently and support future
  museum/culture/education cases without forcing everything into `Sport` or
  `Children`.
- Public cards remain resident-first: they show what residents need to know and
  do, while source provenance, procurement context, provider identity, fallback
  logic, and monitoring details stay internal unless a direct action requires an
  external link.
- The pool card model never implies simultaneous indoor/outdoor availability.
- The ordinary seasonal state is deterministic and very cheap to maintain:
  outdoor from 16 June, indoor from 16 September.
- If the municipality changes a season date in a particular year, the project
  applies an explicit exception rather than building a complex inference engine.
- For 2026, 15 September is treated as the final outdoor-pool day and 16
  September as the first indoor-pool day under the default product calendar.
- Some desired fields still remain separate validation problems, especially exact
  public opening hours, some tariffs, and programme registration state.
- Swimming-course automation may remain manual/curated if no stable public data
  surface can be validated. Avoiding false alerts remains more important than
  maximizing automation.
- Additional Telegram hierarchy is introduced only when actual content volume
  requires it, reducing message-graph maintenance and migration risk.

## Follow-up work before acceptance

1. Draft the first place and swimming activity cards and review their Telegram
   navigation/linking.
2. Remove provider/operator naming and generic source links from public-card
   drafts; retain only direct action links residents actually need.
3. Implement the minimal deterministic season state if/when the pool pilot moves
   to code: 16 Jun outdoor, 16 Sep indoor, with a simple explicit override path
   only if a real exception becomes necessary.
4. Validate the public swimming-course booking flow from the real runtime and a
   normal browser without bypassing authentication or access controls.
5. Determine whether a stable public data surface exposes current services,
   prices, registration windows, and availability.
6. Resolve current `Bebés`/`Peques` label/age details before publishing a
   detailed child-swimming card, while preserving the summer-only constraint.
7. Validate Sporttia live lane availability only if it proves useful; do not
   couple it to the course catalogue.
8. Decide which programme/source changes trigger a public notification and which
   update the pinned card silently.
9. Only after the UX and source contracts are accepted, implement the smallest
   pool vertical slice and tests.

## Alternatives considered

- **Top-level `Спорт и занятия`: rejected.** It is too topic-specific and would
  collide with future museum, culture, education, children, and private activity
  information.
- **Intermediate `Справочник Гуардамара`: rejected for the pilot.** `Полезное о
  Гуардамаре` already serves as the persistent navigation root; another layer
  adds a click and message-graph complexity without adding user meaning.
- **One all-in-one pool card: rejected.** Facility facts and recurring course
  facts have different lifecycles, sources, and change semantics.
- **Model indoor/outdoor pools as simultaneously available seasonal choices:
  rejected.** Local operation is mutually exclusive by season.
- **Require fresh annual proof of every normal season switch: rejected.** It adds
  operational complexity without enough value. Use the fixed calendar and fix
  exceptions when they actually occur.
- **Use the lifeguard contract as an operational calendar: rejected.** Its
  staffing clauses do not describe actual seasonal pool operation.
- **Publicly list all underlying sources/operators: rejected.** It adds little
  resident value, clutters cards, exposes the project's source map, and makes
  copying the monitoring workflow easier. Direct action links remain allowed
  when necessary for the resident.
- **Build a generic city directory first: rejected.** It creates abstractions
  before source quality and real user demand are demonstrated.
- **Automate the swimming provider immediately by scraping visible Booking.page
  text: rejected.** Current evidence shows stale seasonal records,
  contradictory descriptions, and direct-fetch access problems.
