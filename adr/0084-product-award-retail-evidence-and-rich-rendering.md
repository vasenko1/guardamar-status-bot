# ADR 0084: Retail evidence and rich deterministic rendering for product awards

- Status: Accepted
- Date: 2026-09-25
- Extends: ADR 0083

## Context

ADR 0083 established one shared deterministic award engine with source-specific
award adapters, one queue, per-source baselines and no LLM in the critical
path.

The first implementation deliberately limited candidates to supermarket
private labels. A second source and retailer investigation showed that this
scope is unnecessarily narrow. Useful resident-facing products can also be:

- retailer-exclusive products made by a third-party producer;
- ordinary branded products that win a credible award and are currently sold
  by a supported Spanish supermarket.

The same investigation also proved that current price and product photos are
technically available from several retailer catalogues, but exact product
identity is the hard problem. Visible names can collide between distinct SKUs,
one manufacturer can make both award-winning and non-award-winning products,
retailer brands can be reused in different countries, and marketplace listings
can look like supermarket stock.

The desired editorial output is richer than the first generic renderer. OCU,
GourmetQuesos, MUNDUS VINI and other sources publish useful structured facts
about sample size, judging method, category, score, tasting result, vintage,
grape, or other product-specific context. Those facts can be rendered
deterministically without runtime generative writing.

## Decision

### Keep award identity and retail identity separate

The award source remains authoritative for:

- award body and edition;
- exact award result/medal/tier;
- source-native event identity;
- category/class;
- score and judging facts explicitly published by the award source;
- exact awarded commercial product identity as exposed by that source.

Retail evidence is a separate layer responsible for proving that the exact
awarded product is currently associated with a supported Spanish supermarket.

### Narrow first-party entrant exception for a reviewed launch seed

The responsible award organizer remains the preferred authority for automated
award discovery and result semantics.

A one-time, hand-reviewed launch seed may use an official first-party
entrant/producer result announcement when the organizer does not expose a
complete accessible result table, but only when all of these are true:

- the announcement names the exact competition edition/year;
- it gives the exact commercial product plus explicit score/result/tier;
- the organizer independently documents the judging method and score semantics;
- a separate current retailer source proves the exact SKU/EAN, supplier,
  recipe/variant and current sale;
- there is no conflicting organizer or retailer evidence;
- the reviewed facts are frozen as dated seed data rather than turned into a
  generic scheduled producer-news parser;
- public copy attributes the result to the producer/entrant source.

This exception does not permit media reports, retailer marketing badges,
manufacturer equality alone, fuzzy joins or a permanent assumption that
producer claims are equivalent to an organizer result directory.

The supported relationship types are:

- private label;
- retailer-exclusive;
- listed third-party product.

Public copy must preserve the real relationship and must not call every listed
product a supermarket own brand.

### Exact product join

A retail join is accepted, in descending strength, when there is:

1. an exact EAN/GTIN match;
2. an exact retailer SKU/product ID authoritatively tied to the awarded
   commercial product;
3. an exact commercial identity match using the category-specific required
   qualifiers, with no competing same-name SKU.

Do not accept:

- manufacturer or supplier equality alone;
- brand equality alone;
- fuzzy or model-derived text similarity;
- the same product-family name with different variants;
- cross-country private-label inference;
- a third-party Carrefour marketplace listing as Carrefour supermarket stock;
- a producer/bulk-lot award transferred to an unlinked retail SKU.

No LLM or fuzzy matcher may override this gate.

### Category-specific identity

Use the smallest deterministic identity appropriate to the category.

Wine should preserve, when published, label/cuvée, vintage, designation
(DO/IGP/DOP), bottle size and other needed variant fields.

Cheese should preserve exact commercial name plus relevant milk/type,
maturation, flavour, format and maker.

AOVE should preserve exact commercial brand/variant and relevant cultivar,
campaign or style. A bulk lot or mill-level award is not automatically a
retail bottle award.

Jamón and cured meat should preserve the exact commercial product and
applicable ibérico percentage, feed class, quality figure, ageing/variant and
format.

Fresh meat/fish awards may apply to a cut or range rather than one tray size;
the renderer must preserve the awarded scope.

Olives should preserve exact variety/filling/flavour/salt variant and package
when needed.

### Retailer scope

The active retailer scope for category selection is:

- Mercadona;
- Carrefour España supermarket;
- ALDI España;
- Lidl España;
- DIA España;
- Consum.

Masymas / Juan Fornés was researched earlier but is now outside the active
product-award retailer scope.

Retailer evidence adapters are not award adapters. They do not receive their
own queues, state machines or schedules.

### Excluded retailer: Alcampo / Auchan

Alcampo / Auchan was technically researched and has usable exact product
cards, but it is intentionally outside this feature's retailer scope because
it has low practical local value for the Guardamar audience: there is no nearby
store that most residents can conveniently use.

Do not register Alcampo / Auchan in runtime private-label matching, retailer
enrichment, price refresh or product-award publication unless the local scope
is explicitly changed in a future decision.

### Publication-time retail offers

A candidate may remain in the global queue for several days. Current retail
price must therefore not be frozen at award discovery.

If stable retailer product identity is available, publication may perform one
bounded exact-product refresh immediately before rendering. The result is a
small list of exact retail offer variants rather than one chosen price.

Each visible offer preserves, when available:

- exact package/weight/volume;
- current price;
- current unit price;
- exact retailer product ID or EAN;
- exact product URL.

If the same awarded commercial product is sold in several package sizes or
retail formats, show all reviewed current variants and prices with a visible
format label. Do not choose one "representative" package on the bot's behalf.
A different flavour, recipe, maturation, vintage or otherwise distinct SKU does
not inherit the award merely because the brand or product family matches.

Store/postcode/promotional context must be preserved. Never substitute a search
engine, aggregator or stale cached price. Changing offers never change award
event identity.

Use a configured Guardamar retail context rather than user/device geolocation.

A public award article requires at least one freshly verified exact retail
offer. If the retailer refresh fails, the product disappears, or identity
becomes ambiguous, do not publish a price-less article and do not consume the
three-day delivery slot. Keep the queued event for a later retry.

### Photos are disabled by default and require explicit reuse clearance

An exact image URL is not a licence to republish the image.

The horizontal research found explicit intellectual-property restrictions on
copying, reproduction, distribution or public communication of site content
without permission for multiple researched retailers, including Lidl, Consum, Carrefour, DIA and
Masymas / Juan Fornés. The Masymas legal finding is retained as historical
research even though that retailer is no longer in active scope.

Therefore retailer product photos are disabled by default.

A Telegram product photo may be enabled for one source only when all of these
are true:

- the exact retail product has already passed the identity gate;
- the image is tied to that exact SKU/product;
- the media host is allowlisted HTTPS and retrieval is bounded;
- an explicit licence, permission, press/media policy or equivalent documented
  reuse right permits the intended publication.

Do not use search-engine images, generic brand photos, or a photo selected by
fuzzy similarity. Public accessibility of the media URL is not sufficient.

If media identity or reuse rights are unclear, publish text-only. Photo failure
must never invalidate a verified award event. Exact images may still be read
internally when useful for identity verification without being republished.

### Rich deterministic fact contract

The shared record may retain optional verified editorial facts such as:

- category/class;
- score/points;
- comparison or entry count;
- judge/tester count and type;
- judging/test method;
- source-backed tasting or quality distinction;
- source-backed nutrition/quality class;
- product description, tasting notes, composition and nutrition facts;
- producer/maker, producer location and production country;
- identity qualifiers such as vintage, DO, grape or maturation.

Whenever the public article names a producer, the production country is
mandatory. A city/region may be shown as extra context but never replaces the
country.

These facts are source-backed data, not generated prose.

Use small source-specific deterministic renderers where semantics differ.
Examples:

- OCU: comparison size, test dimensions, score, professional tasting,
  health-scale classification;
- consumer sensory awards: exact recognition and method without inventing a
  ranked first place;
- cheese contests: medal/place/class and verified competition/judging context;
- MUNDUS VINI: medal/edition, vintage, DO, grape and bottle identity;
- MAPA jamón: official category and expert sensory process.

Do not reintroduce runtime LLM editorial generation merely to make articles
longer.

### Category-first podium selection

The feed is not a catalogue of every highly scored product. Its editorial unit
is one **best currently purchasable product per reviewed supermarket category
and award edition**.

For each reviewed category/source pair, the source adapter may expose at most
three candidates in the source's explicit rank order:

1. check the source-native #1 product;
2. if its exact commercial product is not currently sold by an in-scope
   retailer, check #2;
3. if #2 also has no exact current retail match, check #3;
4. if none of the explicitly ranked top three has a verified current retail
   match, publish nothing for that category/edition.

Never infer second or third place from unordered finalists, medal lists,
alphabetical tables or equal medal tiers. If an authoritative source publishes
only one winner, the adapter checks only that winner.

The active retailer scope for this feature is exactly:

- Mercadona;
- Carrefour España supermarket;
- ALDI España;
- Lidl España;
- DIA España;
- Consum.

Masymas / Juan Fornés and Alcampo / Auchan remain historically researched but
are outside the active category-selection scope.

The category taxonomy is deliberately broad and reviewed. Do not multiply one
consumer concept into dozens of competition classes merely to create more
content. Cheese is one editorial category unless a future product decision
explicitly changes that. Wine may use consumer-meaningful styles such as red,
white, rosé and sparkling when the authoritative competition itself judges
those styles separately and does not publish a meaningful overall wine podium.

### Exceptional-product quality floor

Podium position does not automatically make a weak comparison worth
publishing.

- where the source publishes a meaningful comparable overall 0-100 score, the
  candidate must normally score **at least 85/100**;
- only the source's overall/global product score can satisfy that floor;
- a nutrition subscore, tasting subscore or other partial metric cannot qualify
  a product;
- for sources whose highest source-native tier is itself an explicitly
  exceptional podium/championship result, the reviewed source contract may use
  that tier instead of a numeric floor.

Ranking is always source/category-native. The shared engine must not compare a
cheese score, wine medal and OCU score on one universal ladder.

### Three-day publication cadence

Discovery and retail verification may still run daily when cheap, but public
delivery is limited to **at most one category winner every three local calendar
days**.

The cooldown is state-based from the last confirmed delivery day rather than a
calendar cron such as every third date. Missed or empty days therefore do not
shift into an unsafe schedule, and a category with no eligible top-three retail
match simply stays silent.

### Daily article presentation

The headline leads with the product, the supermarket where residents can buy
it, and the award/result. Numeric score is useful evidence in the body but is
not used as the headline.

The main visible section should contain the changing resident value: product
identity, result, score, product characteristics, producer/country and current
retail offers.

Repeated explanation of a competition or test method belongs in a Telegram
HTML expandable blockquote (`<blockquote expandable>`), headed `Как оценивали`.
This keeps daily posts compact while preserving methodological detail on demand.

### Award result precedence is source-specific

The shared engine must not maintain one universal ranking across unrelated
award systems. Great Taste stars, OCU value labels, cheese medals, category
places and wine distinctions do not form one meaningful common ladder.

If one source can expose several results for the same source-native event, that
adapter must canonicalize or explicitly prioritize them before returning the
candidate. The core may merge complementary metadata for an identical event
but must not decide that one unrelated award vocabulary is globally "higher"
than another.

### Discovery can be award-first or retailer-first

Award-first sources discover awards and then attempt an exact retail join.

Retailer-first sources such as an official retailer award collection may
surface a small set of currently sold award-labelled products; the award still
must be verified against the responsible award authority before it becomes an
eligible award event.

Both directions feed the same ADR 0083 queue.

### Failure semantics

Distinguish two failures:

- inability to prove a fresh current retailer offer, exact identity or price:
  fail closed for public delivery and leave the queued event available for a
  later retry;
- inability to obtain an optional reusable product photo after the text article
  is otherwise verified: publish text-only.

The award itself must never be rewritten or guessed to compensate for retail
enrichment failure.

## Consequences

The feed can cover much more useful supermarket content without abandoning the
deterministic architecture.

The data model becomes slightly richer, but the operational architecture stays
small: no retailer-specific cron jobs, database, browser, LLM parser or
continuous catalogue polling is added.

Exact retailer adapters are intentionally heterogeneous. Consum may expose an
EAN and product code directly while Mercadona or Masymas may require a small
source-specific JSON contract. This duplication is preferable to one generic
fuzzy product matcher.

Current price becomes more trustworthy because it is refreshed at publication
rather than copied from an award article or stale discovery snapshot.

Rich articles become possible from verified source facts rather than generated
claims.

## Rejected alternatives

### Match award products to catalogues by normalized name

Rejected. Mercadona already demonstrated two current SKU IDs with the same
visible Salmorejo Hacendado name.

### Treat a producer relationship as product identity

Rejected. A producer may supply many products. MAPA AOVE additionally awards
bulk homogeneous lots, so a winning producer does not imply that a supermarket
bottle from the same producer won.

### Treat retailer award pages as the sole award authority

Rejected as a universal rule. Retailer pages are excellent discovery and
retail identity evidence, but independent award semantics should come from the
responsible award body when that source is available.

### Snapshot price during award discovery

Rejected. Queue delay and the three-day public cadence can make a price stale
before publication.

### Use any public product photo found on the web

Rejected. Exact SKU identity and source reuse terms matter; image search would
reintroduce ambiguity and copyright risk.

## Implementation order

1. Complete the existing OCU production-device read-only preview.
2. Before first production state is established, evolve the candidate/state
   schema to separate award facts from optional retail evidence.
3. Add retailer evidence adapters incrementally; start with simple current
   contracts and retain fail-closed matching.
4. Probe Mercadona and Masymas browser-free JSON contracts before coding them.
5. Expand OCU's verified editorial fact set and renderer.
6. Add one real current award family after its live source contract is proven.
7. Enable photo delivery only after exact media identity and source terms are
   reviewed.

See research/2026-09-25-supermarket-product-awards.md for the dated source
matrix and live findings.
