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
SimplyBook/Booking.page catalogue, but the page retains expired seasonal entries,
contains contradictory copied descriptions, and returned HTTP 403 to a direct
automated fetch during investigation. Current pool hours and casual-entry price
also lack a sufficiently fresh authoritative public source.

A product clarification on 2026-09-15 established that the identity of an
underlying service operator is implementation/source provenance, not resident-
facing content. Residents need the service facts, not the procurement/operator
relationship. Source discovery is part of the project's competitive advantage
and should normally remain internal.

A corrected local-operational clarification also established the seasonal
facility model:

- in summer only the outdoor municipal pool operates;
- in winter only the indoor/heated municipal pool operates;
- the two pools are not active in parallel; the off-season pool is drained/not
  in service;
- very-young-child `Bebés` / `Peques` swimming uses the shallow outdoor pool and
  is therefore summer-only;
- adult and older-child programmes may exist in either seasonal period, but
  their venue follows the pool that is active for that season.

Exact seasonal cutover dates remain a separate fact that must be verified from
a fresh current source before public automation. Old municipal pages and
lifeguard-contract coverage are not enough by themselves to prove the public
switch date. A check on 2026-09-15 found supporting evidence for a 15 September
summer boundary but no explicit current 2026 public operational announcement
from Ayuntamiento/Deportes, the pool, or the service operator confirming that
15 September is the final public day. The current lifeguard specification covers
outdoor-pool service through 15 September but also explicitly allows schedule
variation and closure by the Sports Department.

See `research/2026-09-15-guardamar-municipal-pools-and-swimming.md` for the
source inventory and evidence boundaries, and
`research/2026-09-15-pool-pilot-product-clarifications.md` for the later product
clarifications.

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
  availability**. In the pool pilot, only one municipal pool is active at a
  time: outdoor in summer, indoor/heated in winter. Programme venue must be
  consistent with that active facility state.
- Do not infer that a programme survives a seasonal switch. A summer programme
  and a winter programme must each be supported by current evidence even when
  they have similar names.
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
- Preserve the existing evidence-first/fail-closed product rule: a field may be
  public only when the accepted source proves both the fact and sufficient
  freshness for the claim being made.
- Treat the Sporttia public centre page as a candidate automated source only for
  the fields it currently exposes reliably. Live slot availability remains a
  separate validation problem.
- Treat the swimming-course booking/provider surface as an internal curated
  research source until stable permitted automated access and lifecycle
  semantics are validated. A visible `Book now` button alone does not prove
  current registration availability.
- Do not copy contradictory programme text into the public guide. Programme
  venue, season, age, schedule, and price must come from a current internally
  consistent source state.
- Do not infer current pool opening hours from lifeguard-contract coverage and do
  not promote the municipality's `VERANO 2023` pool price/schedule as current.
- A public seasonal-switch statement or notification requires a current
  operational source explicitly stating the open/close or switch date. Accepted
  source classes are: Ayuntamiento/Concejalía de Deportes, an official pool or
  municipal sports-facility publication, the current contracted service operator
  when it clearly refers to Guardamar municipal operation, or another current
  official operational source. Community posts are discovery signals only.
- A change in stored/source data does not automatically produce a public
  message. Public change notifications require material user impact: a proven
  registration opening, new recurring programme, verified seasonal pool switch,
  material price/schedule/venue change, or authoritative closure/opening notice.
- The first successful observation of any automated source establishes a silent
  baseline; it must not announce the pre-existing catalogue as new.
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
- The pool card model will not imply simultaneous indoor/outdoor availability.
  When a verified seasonal switch occurs, the relevant facility state and any
  affected programme facts must switch consistently.
- This preserves a useful competitive asymmetry: the visible result can be
  shared freely, while the source map and monitoring process are not exposed by
  default.
- The pilot can proceed to card/UX design using already verified pool facts even
  though full automatic swimming-course monitoring is not yet ready.
- Some desired fields will intentionally remain absent (for example current
  casual-entry price, guaranteed opening hours, or exact seasonal cutover date)
  until a fresh source is found.
- Swimming-course automation may remain manual/curated if no stable public data
  surface can be validated. This is acceptable; avoiding false alerts is more
  important than maximizing automation.
- Additional Telegram hierarchy is introduced only when actual content volume
  requires it, reducing message-graph maintenance and migration risk.

## Follow-up work before acceptance

1. Draft the first place and swimming activity cards from the research inventory
   and review their Telegram navigation/linking.
2. Remove provider/operator naming and generic source links from the public-card
   drafts; retain only direct action links that residents actually need.
3. Validate the public swimming-course booking flow from the real runtime and a
   normal browser without bypassing authentication or access controls.
4. Determine whether a stable public data surface exposes current services,
   prices, registration windows, venue/season, and availability.
5. Verify the exact current seasonal cutover/open-close dates for the indoor and
   outdoor pools from a fresh operational source. Do not use stale municipal
   pages or contract coverage as the sole source for public switch dates.
6. Resolve the current `Bebés`/`Peques` label/age details before publishing a
   detailed child-swimming card, while preserving the established summer-only
   shallow-outdoor-pool constraint.
7. Validate Sporttia live lane-availability access separately if it is useful to
   residents; do not couple it to the course catalogue.
8. Decide which exact source facts are allowed to trigger a public notification
   and which update the pinned card silently.
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
  rejected.** Local operation is mutually exclusive by season; presenting both
  as concurrently usable would be misleading.
- **Use contract/old schedule dates as current season-switch truth: rejected.**
  They are useful baselines, but exact operational dates require a current
  explicit official statement.
- **Publicly list all underlying sources/operators: rejected.** It adds little
  resident value, clutters cards, exposes the project's source map, and makes
  copying the monitoring workflow easier. Direct action links remain allowed
  when necessary for the resident.
- **Build a generic city directory first: rejected.** It creates abstractions
  before source quality and real user demand are demonstrated.
- **Automate the swimming provider immediately by scraping visible Booking.page
  text: rejected.** Current evidence shows stale seasonal records,
  contradictory descriptions, and direct-fetch access problems.
