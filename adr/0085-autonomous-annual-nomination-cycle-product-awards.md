# ADR 0085: Autonomous annual nomination-cycle product awards

- Status: Proposed
- Date: 2026-09-27

## Context

The production product-awards feature currently publishes at most one reviewed
award-winning supermarket product every three local calendar days. At that
cadence there are at most 122 publication opportunities in a 365-day year.

The first production version deliberately uses a tiny reviewed registry. That
was the right launch architecture, but it cannot autonomously supply a
year-round stream or roll itself forward when 2027/2028 award editions appear.

Research now shows that the useful unit is not merely a broad product category.
Award bodies commonly publish multiple consumer-meaningful nominations inside
one category: best red wine, best sparkling wine, best goat cheese, best blue
cheese, best mature-fruity AOVE, best Iberian bellota ham, and so on.

At the same time, medal tiers and technical competition classes are not always
publication-worthy nominations. A source can contain hundreds of classes without
creating hundreds of useful Telegram posts.

The target runtime remains a weak Android phone running Termux alongside many
other one-shot Guardamar services. The autonomous design must therefore avoid a
browser, OCR, runtime LLMs, fuzzy product matching, full catalogue crawls and a
server database.

The active retailer scope remains exactly:

- Mercadona;
- Carrefour España supermarket;
- ALDI España;
- Lidl España;
- DIA España;
- Consum.

## Decision

### 1. Make the publication unit a semantic nomination event

A publishable event is identified by:

- award organizer;
- award programme/competition;
- source edition;
- consumer product category;
- semantic nomination;
- geographic scope when material;
- exact winning commercial product.

The event is not created merely because a product has a Gold/Silver/Bronze
medal or appears in an unordered recognition list.

Examples of valid separate semantic nominations:

- cheese / best goat cheese;
- cheese / best blue cheese;
- wine / best red wine;
- wine / best sparkling wine;
- AOVE / best mature-fruity style;
- jamón / best bellota ibérico.

Equivalent nominations from different sources compete for one semantic slot when
they make materially the same consumer claim. Different award dimensions may
remain separate, for example laboratory comparative quality versus consumer
taste, provided the public wording preserves the distinction.

### 2. Keep a small explicit source manifest and source-specific adapters

Production must not search the open web for new award bodies.

A reviewed source manifest contains only approved recurring source families.
Each source adapter knows how to:

1. discover the latest available edition;
2. enumerate only the source's approved nominations;
3. read the explicit winner and, where genuinely ordered, limited fallback
   positions;
4. expose stable source-native identity fields;
5. fail closed when the source contract changes.

The first autonomous source set should be limited to recurring sources with
strong official public result surfaces, for example:

- OCU food comparators;
- MAPA Alimentos de España product awards;
- GourmetQuesos;
- International Wine Challenge;
- Bacchus;
- Concours Mondial de Bruxelles;
- World Beer Awards;
- EVOOLEUM.

Additional families remain opt-in research additions, not runtime web
discovery.

### 3. Editions roll forward per source, not globally on 1 January

There is no global annual reset.

Each source adapter tracks its own latest discovered edition. A 2027 event
becomes eligible only when that source explicitly publishes the 2027 result.
Until then, valid 2026 events may remain usable subject to freshness rules.

Event identity includes the source edition, so a new annual winner is a new
event without deleting historical publication state.

A new edition supersedes the older edition for the same source/nomination when
both represent the same recurring award slot.

### 4. Maintain a rolling ready buffer instead of precomputing 122 posts

The system does not need 122 ready events on 1 January.

Maintain a small rolling pool of verified nomination events, targeting roughly
20-30 ready events (60-90 days of runway) rather than a full-year stockpile.

Discovery/refill is bounded and infrequent. It may run from the existing daily
one-shot entrypoint only when:

- the ready buffer is below its low-water mark;
- a source-specific edition/check date is due; or
- a previously unavailable nomination needs a bounded retry.

Quiet days remain cheap.

The system never lowers evidence standards merely to fill a three-day slot.
The three-day cadence is a maximum publication rate, not a quota.

### 5. Add six small retailer search/identity adapters, not one generic crawler

Award discovery and retailer discovery stay separate.

For each of the six supported chains, a retailer adapter may have two
capabilities:

- candidate search: bounded official first-party search/index lookup for an
  exact award winner;
- exact offer refresh: exact official SKU/product-card validation immediately
  before publication.

Candidate search is always award-targeted. It never scans an entire catalogue.

Retail identity is accepted strongest-first by:

1. exact EAN/GTIN;
2. exact retailer SKU/product ID authoritatively tied to the awarded product;
3. exact commercial identity with all category-critical qualifiers and no
   competing variant.

No LLM, fuzzy matcher or normalized-name-only join may upgrade ambiguous
identity into a match.

A retailer may initially be validation-only if an official bounded search
contract is not yet proven. Lack of search support in one chain must not block
the other chains.

### 6. Prefer product diversity with a simple multi-pass selector

The scheduler does not need a scoring model.

When publication is due, consider ready events in deterministic source/category
rotation and select using three passes:

**Pass A**
- event not yet published;
- canonical product identity not yet published in the current diversity round;
- consumer category not among the most recent small category window.

**Pass B**
- event not yet published;
- canonical product identity still new in the current diversity round;
- ignore the category-spacing preference.

**Pass C**
- only after no event with a new product identity remains;
- allow a previously published product when it represents a different,
  unpublished semantic nomination.

This implements the editorial preference:
different products first, then legitimate repeat products in different
nominations.

If one product wins several nominations in the same source/edition and all are
known before publication, prefer one article carrying the strongest title plus
the additional distinctions rather than several near-duplicate posts.

### 7. Keep semantic duplicate handling simple

Use a small controlled nomination vocabulary rather than free-form AI
normalisation.

Minimum fields:

- category;
- subtype/style when consumer-meaningful;
- award dimension: quality / consumer taste / value;
- scope: Spain / Europe / world when material.

Two events with the same semantic tuple compete for one slot according to the
reviewed source-priority order.

Do not model every competition class. Only source nominations admitted by the
adapter appear in the autonomous pool.

### 8. Refresh retail evidence only at the two necessary moments

At discovery/refill time:

- find an exact supported-retailer identity;
- store only stable identity metadata, not a promised future price.

Immediately before publication:

- re-fetch that exact product;
- verify identity and availability;
- refresh package and current price;
- skip the event if current evidence no longer passes.

Do not continuously monitor stock or prices between these points.

### 9. Store a small generated pool, not raw source archives

Autonomy requires more state than the five-item launch registry, but not a
database.

Persist only compact atomic JSON data such as:

- latest edition/check metadata per source;
- ready nomination events;
- exact retailer identity proof fields;
- publication history;
- diversity-round product identities;
- recent category history;
- uncertain Telegram delivery reservation.

Do not persist full award pages, retailer catalogues or large result dumps.

A few hundred compact events are acceptable on Termux.

### 10. Bound discovery work

Every autonomous maintenance run has fixed budgets, for example:

- bounded number of source index requests;
- bounded nomination detail requests;
- bounded retailer searches per nomination;
- bounded candidate results inspected per retailer.

If the budget is exhausted, continuation waits for a later invocation.

There is no long-running process.

### 11. Fail closed without stopping the whole feature

One broken source or retailer adapter is isolated.

On parser/schema/access drift:

- mark that source/retailer contract unhealthy;
- do not create new events from it;
- continue using healthy sources;
- keep existing historical publication records;
- never guess around the failure.

Autonomy therefore means autonomous operation while reviewed external contracts
remain valid, plus graceful degradation when one changes. It does not mean that
third-party sites can be guaranteed never to require maintenance over several
years.

### 12. Preserve the current delivery safety rules

The current three-local-day cooldown, Telegram uncertain-send reservation,
confirmed-delivery state update, deterministic rendering and fail-closed exact
retail checks remain.

This ADR proposes replacing only the manually reviewed five-item discovery
model with a bounded recurring nomination-cycle pool. It does not require a
new Telegram publisher, database, daemon or second message framework.

## Source admission tiers

### Tier A: suitable for autonomous nomination discovery once adapters are proven

- OCU food comparators;
- MAPA product-award families;
- GourmetQuesos;
- International Wine Challenge;
- Bacchus;
- Concours Mondial de Bruxelles;
- World Beer Awards;
- EVOOLEUM.

### Tier B: useful after separate contract review

- World Championship Cheese Contest;
- World Cheese Awards;
- Great Taste;
- OLIVE JAPAN;
- Sabor del Año;
- MUNDUS VINI;
- other recurring reviewed sources with stable official result surfaces.

### Not admission evidence by itself

- generic medal lists with no winner semantics;
- innovation-only awards mixed into the quality stream;
- retailer marketing badges without independent result evidence;
- search-engine snippets;
- third-party price/comparison sites.

## Capacity target

The publication ceiling is approximately 122 posts per 365-day year, but the
system must not treat 122 as a quota.

A healthy autonomous system should aim for a rolling pool with enough surplus
to absorb unavailable products, duplicate winners and source drift. A practical
initial target is 20-30 ready events, continuously replenished as new editions
and nominations appear.

If the system eventually proves 150+ eligible events across a year, the
three-day cadence can remain continuously filled without weakening standards.

## Consequences

Benefits:

- substantially larger content runway without repetitive same-category posts;
- yearly source editions can roll forward without hand-entering every winner;
- retailer relevance remains mandatory;
- different products are preferred before any repeat product;
- source and retailer maintenance remain isolated and auditable;
- phone cost stays bounded.

Costs/tradeoffs:

- six retailer search contracts must be proven; exact-SKU refresh alone is not
  enough for autonomous discovery;
- source nomination allowlists need an initial one-time review;
- semantic nomination mapping is a small maintained taxonomy;
- external website changes can still require adapter maintenance;
- the generated pool is more stateful than the current five-item registry.

## Implementation gate

Do not implement this ADR until research has proved:

1. at least four Tier-A award source adapters can automatically enumerate
   nomination winners for a fresh edition;
2. bounded browser-free candidate search is proven for enough of the six
   retailers to make annual discovery useful;
3. exact-product refresh remains available for every retailer used publicly;
4. a dry-run research pass can produce a materially larger nomination pool
   without fuzzy matching or manually supplied product URLs;
5. diversity selection can be demonstrated from generated data without
   creating duplicate semantic nominations.

Until then, ADR 0083 remains the active production architecture.
