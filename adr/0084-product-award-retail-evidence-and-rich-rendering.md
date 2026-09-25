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

The first supported retailer research set is:

- Mercadona;
- Lidl España;
- ALDI España;
- Consum;
- Carrefour España supermarket;
- Masymas / Juan Fornés Fornés;
- DIA España;
- Alcampo / Auchan.

Retailer evidence adapters are not award adapters. They do not receive their
own queues, state machines or schedules.

### Publication-time price refresh

A candidate may remain in the global queue for several days. Current retail
price must therefore not be frozen at award discovery.

If a stable retailer product identity is available, publication may perform
one bounded exact-SKU refresh immediately before rendering.

- Fresh exact price/availability may be included.
- Store/postcode/promotional context must be preserved.
- If price refresh fails or becomes ambiguous, omit the current-price sentence.
- Never substitute a search-engine or aggregator price.
- A changing price never changes award event identity.

Use a configured Guardamar retail context rather than user/device geolocation.

### Photos are optional exact-SKU enrichment

A product photo may be used only when:

- the exact retail product has already passed the identity gate;
- the media host is allowlisted HTTPS;
- content type and size are bounded;
- the image is tied to that exact SKU/product;
- the source-specific terms/licence permit the intended reuse.

Do not use search-engine images, generic brand photos or a photo selected by
fuzzy similarity.

If media identity, availability or reuse rights are unclear, publish text-only.
Photo failure must never invalidate a verified award event.

### Rich deterministic fact contract

The shared record may retain optional verified editorial facts such as:

- category/class;
- score/points;
- comparison or entry count;
- judge/tester count and type;
- judging/test method;
- source-backed tasting or quality distinction;
- source-backed nutrition/quality class;
- producer/maker;
- identity qualifiers such as vintage, DO, grape or maturation.

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

### Discovery can be award-first or retailer-first

Award-first sources discover awards and then attempt an exact retail join.

Retailer-first sources such as an official retailer award collection may
surface a small set of currently sold award-labelled products; the award still
must be verified against the responsible award authority before it becomes an
eligible award event.

Both directions feed the same ADR 0083 queue.

### Failure semantics

Distinguish two failures:

- inability to prove current retailer identity: fail closed for any claim that
  the award product is currently sold by that supermarket;
- inability to refresh optional price/photo after identity is already proven:
  degrade to a correct text-only article without current enrichment.

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

Rejected. The one-item-per-day queue can make a price stale before publication.

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
