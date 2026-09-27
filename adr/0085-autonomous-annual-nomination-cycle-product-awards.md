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

The active retailer scope is now intentionally local-first and remains exactly:

- Mercadona;
- Masymas / Juan Fornés Fornés;
- ALDI España;
- Lidl España;
- DIA España;
- Consum.

Carrefour is excluded completely from the autonomous scope. The reason is not
technical incapacity alone: there is no Carrefour supermarket in Guardamar, so
its weak local utility does not justify carrying the hardest retailer contract.

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

## Operational health and admin alerts

Autonomy must be observable without adding a monitoring daemon.

Each source/retailer adapter keeps a tiny health record inside the product-award
state:

- component id and kind;
- healthy/degraded/broken status;
- failure stage;
- stable diagnostic code;
- first and last failure timestamps;
- consecutive-failure count;
- whether the current failure transition has already alerted the administrator.

Expected content outcomes are not adapter failures. In particular:

- no retailer match;
- product sold out;
- award winner not sold by the six chains;
- no new source edition/revision;
- quality score below the publication gate

must not generate an operational alert.

Operational failures include:

- parser/schema drift;
- formerly valid endpoint becoming 404/403 in a contract-breaking way;
- invalid MIME/redirect/host contract;
- repeated transport failure;
- source result becoming structurally ambiguous;
- retailer search/refresh adapter no longer being able to parse previously
  supported first-party data.

Alert policy stays transition-based, not request-based:

- deterministic contract/schema failure: one immediate private admin alert;
- transient timeout/network/429: alert only after a small consecutive-failure
  threshold or sustained failure window;
- same failure stays silent after the first alert;
- one recovery message is sent when the component becomes healthy again;
- Telegram uncertain delivery remains a critical immediate admin alert because
  autonomous publication is intentionally blocked until reviewed.

The admin message must identify the feature and exact failed stage, for example:

`Product Awards / retailer search / Masymas / SEARCH-SCHEMA`

and include only safe operational context: diagnostic code, first/last failure,
impact, source host and remaining ready-pool runway. Never include tokens,
credentials, response bodies or arbitrary scraped text.

A second transition alert protects content continuity: when the ready pool
crosses a low-runway threshold, send one private warning such as
`9 ready events ~= 27 days at current cadence`. Clear/recover that warning
only after the pool is replenished above the recovery threshold.

This reuses the existing Telegram bot/delivery primitives and needs no new
notification framework or cron.

## Source cycles, revisions and supersession

Do not assume every source is annual.

For annual competitions, source cycle identity can be the edition/year.

For rolling sources such as OCU comparators, the adapter must derive a stable
result revision from source evidence such as an explicit updated date/result
revision and the winner/result identity. OCU documents that some comparators are
updated every 15-30 days while others update one or more times per year.

The generic field is therefore `source_cycle`, not `year`.

A newer source cycle supersedes an older event only when both represent the
same recurring semantic nomination. Publication history is retained.

This avoids both yearly reset logic and stale OCU winners surviving after a
newer comparison result exists.

## Discovery direction is source-specific

Do not force every source through one discovery strategy.

Each reviewed source declares one of three simple modes:

- award-first: enumerate a bounded winner set, then seek one exact retailer
  match;
- retailer-first: use a small official awarded-products surface from Lidl/DIA
  as a lead, then verify the independent award authority;
- hybrid: either direction may create the same semantic event, deduplicated by
  event/product identity.

Large global competitions should not cause thousands of retailer lookups merely
because their full result database exists.

## Rich evidence model for article-quality posts

The autonomous pool must retain enough verified evidence to render a useful
article, not merely a title and price.

Keep a compact common record plus source-specific verified facts.

Common award fields:

- organizer;
- programme/competition;
- source cycle/edition;
- category;
- semantic nomination;
- geographic scope;
- exact official result/tier/rank;
- score when source-defined;
- result URL;
- methodology URL when available;
- result/publication date when available.

Method/evaluation facts when explicitly supplied:

- number of products/samples/entries;
- number/type of judges or consumer testers;
- blind testing flag;
- number of judging stages;
- laboratory testing flag;
- sensory testing flag;
- evaluation criteria;
- threshold/finalist process;
- other short adapter-approved methodology facts.

Product facts when explicitly supplied:

- exact commercial name;
- brand;
- producer/manufacturer;
- origin;
- designation/protected origin;
- category-specific identity attributes such as vintage/grape, milk/maturation,
  cultivar, ibérico percentage or beer style;
- package/format where part of identity.

Retail facts remain separately sourced:

- retailer;
- exact SKU/product ID;
- EAN/GTIN when available;
- current package;
- current price/unit price;
- current availability;
- exact product URL;
- retail check timestamp/context.

Every fact must retain provenance: award authority, retailer or another reviewed
first-party source. Retailer data must never silently become award evidence.

Avoid a universal prose extractor or free-form AI field. A source adapter may
emit a small list of reviewed structured facts that its deterministic renderer
knows how to label.

This is already supported by real source richness: OCU documents anonymous
consumer-like product purchase and independent laboratory testing; MAPA cheese
publishes sample eligibility, five-expert sensory panels, two-stage selection,
80-point finalist threshold and laboratory checks; IWC publishes blind tasting,
3-4 expert panel judging and senior re-tasting/confirmation.

## Image policy and Telegram message shape

Telegram can fetch a photo directly from an HTTP(S) URL for `sendPhoto`.
That transport capability does not grant image-reuse rights.

Image source priority:

1. award authority/organizer press or media asset with explicit reuse rights;
2. producer/manufacturer press asset with explicit reuse rights;
3. retailer product image only when the retailer's terms/licence or direct
   permission clearly allows this Telegram use;
4. otherwise text-only.

A public image URL, Open Graph image or technically downloadable retailer photo
is not sufficient permission by itself.

Store media only as optional reviewed metadata:

- image URL;
- source host;
- exact-product identity tie;
- reuse-right status/evidence;
- MIME/size validation status.

Do not download and cache a product-image archive merely for this feature.

To avoid overengineering Telegram delivery, preserve a one-publication-message
invariant initially:

- when a legally reusable image exists and the complete deterministic article
  fits the Telegram photo-caption limit, use one photo+caption publication;
- otherwise publish the rich text-only article;
- do not introduce a two-message photo/article transaction merely to force an
  image, because partial two-message delivery would require new reservation and
  recovery semantics.

Telegram currently limits photo captions to 1024 characters and accepts remote
photo URLs, with additional file-size/MIME requirements. A text-only article
therefore remains the richer fallback.

## Minimal future state/property set

Do not introduce a relational schema or generic workflow engine.

A future compact state needs only:

**Source state**
- source id;
- source cycle/revision;
- next eligible check time;
- bounded discovery cursor/checkpoint;
- health record.

**Ready event**
- event id;
- semantic nomination key;
- source cycle;
- canonical product key;
- common award facts;
- small source-specific verified facts;
- exact retailer identity;
- optional approved image metadata;
- created/last-verified timestamps.

**Publication/diversity state**
- confirmed published event ids;
- product publication history;
- recent categories;
- current diversity-round product set;
- last confirmed delivery day;
- uncertain Telegram reservation.

No raw HTML, award-result archive, retailer catalogue dump, vector index or
database is needed.

## Production-device retailer contract proof

A read-only probe on the actual Redmi/Termux production network on
27 September 2026 materially strengthens the retailer side of this ADR.

The probe:

- kept repository HEAD unchanged;
- kept product-awards state absent;
- kept crontab byte-for-byte equivalent by hash;
- sent no Telegram message;
- used bounded anonymous HTTP only.

Observed results:

### Mercadona — GREEN

Warehouse-specific Algolia search for `alc1` returned HTTP 200 and eight
salmorejo/gazpacho candidates in a 19 KiB JSON response.

Exact product JSON for several returned SKUs also returned HTTP 200 and exposed:

- stable numeric product id;
- EAN;
- exact display name;
- brand;
- published flag;
- current price;
- reference price/unit.

The probe directly demonstrated two separate current SKUs with the same visible
commercial name `Salmorejo fresco Hacendado`:

- SKU 39901 / EAN 8480000399014;
- SKU 39966 / EAN 8480000399663.

This confirms that candidate search may produce several package/format offers
for one apparent commercial product and that exact identity must happen after
search.

Mercadona is accepted as **search + exact verify** for the prospective
autonomous architecture.

### Masymas / Juan Fornés — GREEN

The official Guardamar-relevant storefront returned HTTP 200 and exposed the
expected Fornés/Aktios/TOL markers.

More importantly, the hypothesised first-party TOL catalogue endpoint was
confirmed on the production phone:

`/api/rest/V1.0/catalog/product?q=<term>`

It returned HTTP 200 JSON with a `products` list. Current candidate records
exposed:

- stable numeric product id;
- EAN;
- product name.

Examples from the probe include product id 2034 / EAN 8411700011302 and other
normal catalogue entries.

Search behaviour is not exact-token-only. A query for `chinchon` also matched
products such as `salchichón`. Therefore Masymas search must be treated as a
candidate generator only; strict product identity/EAN/variant verification is
mandatory.

The probe also checked two former Carrefour-backed winners:

- `realfooding` returned one unrelated product (`Pan 100% Integral`);
- `oleoestepa` returned zero products.

These are **NO VERIFIED MATCH / unresolved** results, not proof of absence.

Masymas is accepted as **search + identity verify** for the prospective
architecture. A separate exact-detail endpoint is desirable enrichment but is
not required for candidate generation because search already exposes EAN.

### ALDI España — GREEN

Peninsula Algolia search returned HTTP 200 with three NALTROS variants:

- brut nature;
- brut;
- semiseco.

Each candidate exposed article/object id, brand, product name, sales unit,
availability and current price.

The existing exact NALTROS page also returned HTTP 200 and retained the expected
first-party application markers.

ALDI is accepted as **search + exact verify**.

### Consum — GREEN

First-party REST search returned HTTP 200 and a current Chinchón candidate with:

- stable product id 19967;
- EAN 8410023172240;
- exact product name.

The exact REST detail endpoint for the returned id also returned HTTP 200 and
the same EAN/name identity.

Consum is accepted as **search + exact verify** and remains the cleanest
search/detail contract in the target set.

### DIA España — retailer-first + exact only

The generic DIA search microservice returned HTTP 403 from the actual production
phone.

The exact AROM'ARTE product page returned HTTP 200 with the expected stable SKU,
identity and add-to-cart markers.

Therefore the autonomous design must not depend on DIA generic search. DIA is
retained only through:

- official retailer-first award/category pages that expose exact current SKUs;
- already-known exact product URLs/SKUs;
- publication-time exact SSR verification.

This is simpler and better aligned with the lean architecture than adding
special anti-bot behaviour for DIA search.

### Lidl España — GREEN/POSITIVE-ONLY

The first-party `/q/api/search` contract returned HTTP 200 JSON from the
production phone and 35 cheese results.

The response exposed:

- item/code/ERP identifiers;
- brand;
- full product title;
- current price when present;
- canonical product URL.

The first returned exact product page also returned HTTP 200.

The broad `queso` query produced about 447 KiB of JSON, so runtime use must
remain award-targeted and bounded; broad category queries are not appropriate
for normal autonomous refill.

Lidl remains **positive-only search + exact verify** because its web assortment
is not a complete absence oracle.

### Final retailer capability model after the phone probe

| Retailer | Candidate discovery | Exact verification | Status |
| --- | --- | --- | --- |
| Mercadona | warehouse Algolia | first-party product JSON / EAN | GREEN |
| Masymas / Juan Fornés | first-party TOL REST search with EAN | search identity + future detail enrichment | GREEN |
| ALDI España | peninsula Algolia | exact first-party product/app data | GREEN |
| Consum | first-party REST search | first-party REST detail / EAN | GREEN |
| DIA España | retailer-first award/category leads only | exact SSR SKU page | GREEN for retailer-first; generic search excluded |
| Lidl España | first-party JSON search | exact first-party page | GREEN/POSITIVE-ONLY |

There is no remaining requirement for Carrefour or for any browser-based retail
search.

## Retail search/index research outcome

The 27 September 2026 read-only search/index investigation changes the proposed
retail architecture in several useful ways.

### Search capability is asymmetric

Do not require all six retailers to expose the same capability.

Current browser-free research supports this initial capability model:

| Retailer | Candidate search/index | Exact product refresh | Initial autonomous role |
| --- | --- | --- | --- |
| Mercadona | yes, public storefront Algolia index tied to warehouse | yes, first-party product JSON | search + verify |
| Masymas / Juan Fornés | probable first-party Aktios TOL catalogue/search contract; production-device proof still required | official online store and current web price/availability are established; exact API contract pending device probe | pending -> search + verify if TOL contract is confirmed |
| ALDI España | yes, public storefront Algolia index, regional | yes, first-party product/embedded app data | search + verify |
| Consum | yes, first-party REST catalogue search | yes, first-party REST product with product id/EAN | search + verify |
| DIA España | technically yes, first-party search/category JSON | yes, SSR exact product | retailer-first / cautious search + verify |
| Lidl España | technically yes, first-party search JSON, incomplete grocery assortment | exact first-party product page | retailer-first / positive-only search + verify |

Masymas must not be treated as the unrelated Asturias "masymas" retailer.
The target is Juan Fornés Fornés, S.A., whose official online store serves the
Valencian/Murcian chain and whose public company terms state that towns with a
Masymas supermarket are within the delivery scope. Guardamar has a Juan Fornés
Masymas store.

The current official online storefront loads Aktios-hosted assets, and Aktios
lists both Consum and Masymas as users of its supermarket eCommerce platform.
That makes a TOL-style first-party REST catalogue contract a strong hypothesis,
but not yet a proven runtime contract. The final read-only Termux probe must
confirm the exact Masymas search/product endpoints before ADR 0085 can be
accepted.

### Candidate search is positive evidence, not an absence oracle

The default rule for every retailer adapter is:

**search hit may establish a candidate; search miss does not prove that the
product is not sold.**

This is mandatory for incomplete/offer-driven surfaces such as Lidl and is also
the safer general rule for undocumented storefront backends.

Therefore an explicit source rank #1 must not be demoted to #2 merely because a
retailer search did not find it. A lower-ranked fallback is allowed only when
the source/retailer evidence positively establishes that the higher-ranked
commercial product is not an eligible current match, or when the reviewed
source contract itself permits a different fallback rule.

Unknown remains unknown.

### Add a pre-search commercial-identity gate

Do not spend retailer requests on award results that cannot identify a retail
product.

Before candidate search, require enough award-side identity to distinguish a
commercial SKU, for example brand + exact product/label plus category-critical
variant fields.

Reject or defer before retailer search when the result describes only:

- a producer or mill;
- a bulk lot with no tied commercial bottle/SKU;
- an unnamed range;
- a foreign retailer private label outside the six target chains;
- a wine without required vintage/cuvée/DO identity when the award is vintage
  specific.

This is especially important for MAPA AOVE bulk-lot awards and for global wine
competitions containing foreign supermarket private labels.

### Refill sources in a static high-yield order

Do not add a scoring model.

The dry sample shows materially different supermarket-match yield by source
family. The reviewed source manifest should therefore have a simple static
refill order:

1. supermarket-oriented comparative sources such as OCU;
2. retailer-first awarded-product leads from Lidl/DIA, verified against the
   independent award authority;
3. Spanish specialist/national sources such as MAPA and GourmetQuesos;
4. large international competitions such as IWC/CMB/World Beer Awards.

A lower-priority source still contributes diversity, but the phone does not
burn its request budget on thousands of global winners while the ready buffer
can be filled cheaply from supermarket-oriented sources.

### Use retailer hints before broad search

A nomination event may carry a small ordered retailer-hint list derived only
from explicit evidence.

Examples:

- OCU says ALDI -> check ALDI first;
- DIA awarded-products page provides a numeric DIA SKU -> no generic retailer
  search is required;
- exact EAN -> use EAN-capable search/identity paths first.

If no hint exists, try only the proven bounded adapters under the run budget.
Stop after one exact supported-retailer match; finding every chain or the
cheapest chain is not required.

### Current contract notes

Mercadona search uses the web storefront's public search-only Algolia
configuration and a warehouse-specific index. The public search credentials can
rotate, so the adapter must treat them as discoverable storefront
configuration, not a permanent secret or constant. Exact Guardamar product
validation remains bound to warehouse context.

ALDI search is likewise backed by a regional public storefront Algolia index.
The peninsula index is the relevant default for Guardamar. Search result fields
already expose product identity, sales unit, current price and availability,
but the exact first-party page remains the publication-time authority.

Consum exposes the cleanest first-party REST search/detail pair found in the
research. Search returns product ids and product data; exact detail can expose
EAN. Consum should be among the first retailer adapters implemented.

DIA exposes first-party search/category microservices and stable numeric product
ids, but its robots/search policy makes aggressive generic search undesirable.
Prefer DIA's own awarded/category surfaces and exact SKU paths; any generic
search use must remain bounded and separately policy-reviewed.

Lidl exposes a first-party JSON search contract, but the online result set is
not a complete supermarket grocery catalogue. Treat positive matches as useful
and misses as unknown. Its official awarded-products page is more valuable as a
retailer-first lead surface.

Masymas / Juan Fornés has an official current online store with live web prices
and stock-dependent ordering terms. The storefront uses Aktios eCommerce/TOL
infrastructure, the same platform family used by Consum. Its concrete
browser-free product/search API is intentionally not inferred from platform
similarity alone; production-device proof is required before implementation.

## Dry-sample evidence

A stratified research sample of 49 current award events was checked across the
six target retailers using official indexed surfaces, exact known retailer
contracts and strict commercial identity rules.

The sample intentionally mixed high-yield supermarket-oriented sources with
low-yield specialist/global competitions, so its aggregate percentage must not
be extrapolated directly to the final feed.

Observed current state:

- 3/49 remain directly publishable inside the revised local retailer scope:
  NALTROS/ALDI, AROM'ARTE/DIA and Anís Chinchón via DIA/Consum;
- 2 formerly READY events (Realfooding Gazpacho and Oleoestepa DOP Estepa) were
  Carrefour-only proofs and are now UNRESOLVED until another active retailer,
  especially Masymas, is proven;
- one additional exact current retail product is already known but is blocked
  by a higher-ranked unresolved candidate in the same source/category;
- one additional exact award product is currently sold out;
- one GourmetQuesos winner produced a strong Consum exact-commercial candidate
  that still requires final detail/EAN proof;
- most GourmetQuesos, MAPA wine/cheese/jamón and sampled IWC winners produced no
  exact current first-party match in the six chains.

The useful stratified signal is stronger than the aggregate:

- OCU supermarket-oriented sample: still the highest match potential, but two
  former Carrefour-backed matches must now be re-resolved in the local scope;
- MAPA non-AOVE product winners: low but non-zero current match yield;
- GourmetQuesos: very low current target-chain match yield despite excellent
  award semantics;
- sampled IWC champion/great-value winners: no current exact target-chain match
  established.

This supports high-yield-first refill rather than equal scanning of every award
family.

The dry sample also confirmed several false-positive traps that exact matching
must reject:

- same brand, wrong product/variant;
- award producer appearing only in a Carrefour Marketplace third-party bundle;
- product appearing in an event/editorial page but not as a supermarket shelf
  item;
- same product family with no exact winning commercial variant.

## Multiple package variants of one awarded product

Retail search may return several SKUs that are genuinely the same awarded
commercial product in different package sizes or pack counts. This is useful
consumer information and should not be discarded merely because SKU/EAN differs.

Keep two identities separate:

- **canonical awarded product**: the commercial product/formulation that won;
- **retail offer SKU**: one currently sold package/size of that product.

Alternative package offers may be grouped into one article only when evidence
shows that the award applies across them and that the SKUs differ only in
package/quantity, not recipe, formulation, maturation, vintage, flavour,
origin, quality tier or another award-critical attribute.

Evidence may come from:

- award authority explicitly treating package size as non-material;
- first-party retailer detail proving same brand/name, responsible producer,
  legal product identity and relevant composition/variant fields;
- manufacturer/authority product-family evidence that ties the formats to the
  same commercial product.

Visible-name equality alone is not enough.

When several equivalent package offers are proven, they share one canonical
product key for diversity/deduplication. The renderer may show a compact set of
current options, for example 0.33 L and 1 L with their prices/unit prices,
without spending separate publication slots.

This is optional enrichment, not an eligibility dependency. One exact valid
offer is still sufficient for publication.

## Implementation gate

Do not implement this ADR until research has proved:

1. at least four Tier-A award source adapters can automatically enumerate
   nomination winners for a fresh edition;
2. production-device retail discovery is proven for Mercadona, Masymas, ALDI,
   Consum and Lidl, while DIA retailer-first lead surfaces plus exact SSR
   verification are sufficient without generic search;
3. exact-product refresh remains available for every retailer used publicly;
4. a dry-run research pass can produce a materially larger nomination pool
   without fuzzy matching or manually supplied product URLs;
5. diversity selection can be demonstrated from generated data without
   creating duplicate semantic nominations.

Until then, ADR 0083 remains the active production architecture.
