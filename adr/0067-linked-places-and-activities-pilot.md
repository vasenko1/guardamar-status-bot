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

- `Piscina Climatizada Manel Estiarte` is a durable place;
- swimming courses are recurring activities with age, schedule, price, season,
  and registration state;
- competitions/open days are date-specific events;
- a registration opening, closure, or material schedule change may justify a
  separate public update.

The source landscape is uneven. Sporttia exposes strong current structured
public data for municipal sports facilities and many municipal activities, but
its current Guardamar public page does not expose the swimming-course catalogue.
The current municipal swimming-course operator Aqualider exposes a rich public
SimplyBook/Booking.page catalogue, but the page retains expired seasonal entries,
contains contradictory copied descriptions, and returned HTTP 403 to a direct
automated fetch during investigation. Current pool hours and casual-entry price
also lack a sufficiently fresh authoritative public source.

See `research/2026-09-15-guardamar-municipal-pools-and-swimming.md` for the
source inventory and evidence boundaries.

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
- A place and an activity may link to each other without duplicating their full
  content. For example, the pool card may link to `Плавание`, and the swimming
  card may link back to the pool.
- Municipal/private ownership is metadata, not a top-level navigation branch.
- Topic groupings such as sport, culture, children, education, or museums are
  added only when real content volume requires another navigation level. Do not
  create empty category trees in advance.
- Preserve the existing evidence-first/fail-closed product rule: a field may be
  public only when the accepted source proves both the fact and sufficient
  freshness for the claim being made.
- Treat the Sporttia public centre page as a candidate automated source only for
  the fields it currently exposes reliably. Live slot availability remains a
  separate validation problem.
- Treat Aqualider/SimplyBook as a human-facing swimming-course source and a
  curated research source until stable permitted automated access and lifecycle
  semantics are validated. A visible `Book now` button alone does not prove
  current registration availability.
- Do not infer current pool opening hours from lifeguard-contract coverage and do
  not promote the municipality's `VERANO 2023` pool price/schedule as current.
- A change in stored/source data does not automatically produce a public
  message. Public change notifications require material user impact: a proven
  registration opening, new recurring programme, material price/schedule/venue
  change, or authoritative closure/opening notice.
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
- The pilot can proceed to card/UX design using already verified pool/operator
  facts even though full automatic swimming-course monitoring is not yet ready.
- Some desired fields will intentionally remain absent (for example current
  casual-entry price or guaranteed opening hours) until a fresh source is found.
- Aqualider automation may remain manual/curated if no stable public data surface
  can be validated. This is acceptable; avoiding false alerts is more important
  than maximizing automation.
- Additional Telegram hierarchy is introduced only when actual content volume
  requires it, reducing message-graph maintenance and migration risk.

## Follow-up work before acceptance

1. Draft the first place and swimming activity cards from the research inventory
   and review their Telegram navigation/linking.
2. Validate the public Aqualider/SimplyBook booking flow from the real runtime
   and browser without bypassing authentication or access controls.
3. Determine whether a stable public data surface exposes current services,
   prices, registration windows, and availability.
4. Validate Sporttia live lane-availability access separately if it is useful to
   residents; do not couple it to the course catalogue.
5. Decide which exact source facts are allowed to trigger a public notification
   and which update the pinned card silently.
6. Only after the UX and source contracts are accepted, implement the smallest
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
- **Build a generic city directory first: rejected.** It creates abstractions
  before source quality and real user demand are demonstrated.
- **Automate Aqualider immediately by scraping visible Booking.page text:
  rejected.** Current evidence shows stale seasonal records, contradictory
  descriptions, and direct-fetch access problems.
