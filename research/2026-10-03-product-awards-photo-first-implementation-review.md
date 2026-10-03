# Product Awards photo-first implementation review — 2026-10-03

## Scope

Fifth broad adversarial review and post-implementation static code review for
ADR 0096 plus the previously identified editorial-contract repairs.

Reviewed end to end:

- award/source admission;
- exact retail identity and price refresh;
- category/source/rank selection;
- retailer-diversity preference;
- cooldown/dedup/cursor/uncertain state;
- reviewed product-image resolution;
- Telegram remote/upload/no-image delivery;
- editorial rendering;
- current seven-category registry;
- Termux resource boundaries.

## Overall architecture assessment

No redesign is required.

The implementation remains deliberately small:

- the existing selector is unchanged in meaning;
- the state schema is unchanged;
- there is no image discovery job;
- there is no image search engine;
- there is no browser, OCR, AI or computer vision;
- there is no image cache;
- there is no background worker or new cron;
- a candidate has at most a small explicit set of reviewed image pages;
- image-page HTTP happens only after one product has already won selection, or
  during an explicit operator preview.

The new media path is therefore not a new subsystem. It is a bounded extension
of the existing Rich Message delivery path.

## Final runtime boundary

### Selection remains media-neutral

`select_publication()` still does only:

1. cooldown/state checks;
2. reviewed award verification;
3. exact current retailer identity/price verification;
4. source/rank and retailer-preference selection.

The selected `ProductAwardPublication.message` is deliberately built without
media. This prevents a future caller from accidentally sending an old retailer
image directly and guarantees that image resolution belongs to delivery, not
eligibility/selection.

### Delivery owns photography

After a product is selected, `iter_product_images()` lazily yields:

1. each explicitly reviewed primary official image source in configured order;
2. the exact retailer image already returned by the current retail adapter, when
   one exists and is on the reviewed host set.

For each resolved image:

1. try Telegram remote Rich Message;
2. after explicit `REMOTE-MEDIA`, perform one bounded direct image read;
3. try one multipart upload;
4. after deterministic failure, continue to the next reviewed image;
5. after all reviewed images are exhausted, send the same article without
   media.

Any ambiguous Telegram send stops immediately and keeps the existing uncertain
reservation. No later image and no no-image fallback may run after ambiguity.

## Reviewed image contracts in the current registry

Primary official image pages are intentionally explicit rather than discovered
at runtime:

- **Realfooding Gazpacho:** exact Realfooding product page, exact
  `Gazpacho Fresco` image alt;
- **Oleoestepa DOP Estepa:** exact Oleoestepa 1 L store page, exact product
  title/EAN and exact image alt;
- **AROM'ARTE Intenso:** exact DIA SKU 273821 page and exact product image alt;
- **Anís Chinchón Dulce:** exact González Byass Chinchón page and
  `Botella Chinchón Anís Dulce` image alt;
- **Ambar Especial:** official Ambar Especial product page and reviewed
  `especial nueva` product image alt;
- **Mahou Sin Filtrar:** exact Mahou San Miguel product page and exact
  `Mahou Cinco Estrellas Sin Filtrar` image alt.

**NALTROS** has no second primary image contract in this change. When the exact
ALDI product backend becomes healthy again, its already-reviewed primary ALDI
asset remains the retailer image path. The candidate is currently ineligible
for publication anyway because ALDI returns `RETAIL-PAGE-ERROR`.

A brand page may visually present the same exact beer in more than one package
format. The publication text still states the exact currently verified retail
format. No computer-vision package classifier is added merely to police
marketing photography of the same exact product identity.

## Editorial contract restored

The renderer now supports reviewed deterministic fields for:

- exact package/format;
- verified country when the source actually proves it;
- producer/manufacturer;
- retailer in the headline;
- one source-backed product-specific highlight/reason.

Scores/results remain in the body instead of becoming the default headline.

Carrefour price wording is deliberately precise:
`На сайте Carrefour сейчас указана цена ...`.
It does not claim Guardamar-local shelf stock.

Russian sample counts now use deterministic singular/few/many forms, fixing
`23 продуктов` to `23 продукта`.

### AROM'ARTE source-truth correction

The current DIA exact page proves the product, price and responsible company
Toscaf, S.A. with a Spanish address. It does not expose a separate
`País Origen` field for exact SKU 273821.

The first implementation draft therefore overclaimed `Испания` as production
country. That field was removed before PR. Toscaf remains the reviewed producer
fact; no production country is printed for AROM'ARTE unless an exact source
later proves it.

## Findings fixed during static code review

### 1. Generic OG image could bypass exact-image identity

The first image resolver draft searched exact `alt` text, but if no matching
image was found it could still accept a same-host `og:image`.

That could turn a brand banner/logo into the Product Awards photo.

Fix:

- when an image source defines `image_alt_markers`, only a matching image
  element is eligible;
- generic OG/Twitter/meta fallback is allowed only for a deliberately configured
  source with no exact-alt contract;
- added a regression test where a valid same-host generic OG image is rejected
  because the exact product alt is absent.

### 2. Selector still carried legacy retailer media

The selected publication originally retained
`build_message(candidate, offer)`, which could embed the old retailer image
even though the new delivery layer resolves photography itself.

That did not affect the current `_deliver_product_award()`, but it was a
future caller footgun.

Fix:

- selector output is now media-neutral;
- delivery/preview are the only places that resolve product images;
- a regression test proves selection never invokes image-page resolution.

### 3. Unsupported AROM'ARTE production-country claim

Fixed as described above.

### 4. Headline fallback could reintroduce numeric scores

Without an explicit `headline_award`, the first renderer draft used
`award_result` for OCU, which could put `90/100` back into a headline.

Fix:

- source/year fallback labels are neutral;
- explicit reviewed headline labels are supplied for production candidates.

### 5. Lazy image attributes

Some first-party product pages place a placeholder in `src` and the actual
product media in `data-src`, `data-lazy-src` or `srcset`.

The parser now records the small standard set rather than stopping at the first
attribute. Host and exact-alt validation still applies.

## Registry hardening

A new unit test enforces uniqueness of:

- category keys;
- production event IDs;
- production selection keys;
- source priorities inside one category;
- candidate ranks inside one source.

The current registry passes these invariants.

## Overengineering assessment

The implementation is justified by the explicit photo-first product
requirement and remains bounded.

Specifically rejected:

- generic media discovery;
- image search;
- DOM framework;
- CV/AI package matching;
- local image transformations;
- media cache;
- new state;
- new scheduling;
- source retries beyond the existing bounded paths;
- retailer image scraping for every category during selection.

Primary image-page reads are lazy and occur only for the selected candidate.
A normal successful remote image therefore adds one small product-page request
and no image download on the phone.

## Existing deferred risks remain deferred

This change deliberately does not solve unrelated medium-term items:

- promotion-price markup ambiguity requires a real source probe before code;
- `MAX_HISTORY=128` should eventually get pre-send capacity protection;
- positional `category_cursor` should be addressed before a future
  count/order-changing registry migration;
- candidate runway still requires reviewed editorial replenishment;
- a state-aware next-preview command is optional operator UX;
- stale six-retailer wording in ADR 0083 remains a documentation follow-up.

None is a blocker for the photo/editorial repair.

## Validation required before production deployment

The repository does not provide a dependable PR CI gate, so the exact merged
commit must pass on the production Termux device before checkout changes:

1. Python compileall;
2. focused Product Awards tests;
3. full repository unittest suite;
4. current production-state compatibility;
5. strict live source/retail proof;
6. strict live primary-photo resolution for every currently publishable
   candidate;
7. bounded image download/type/size validation for those photos;
8. read-only Product Awards preview showing image Rich Messages;
9. only then fast-forward production;
10. repeat exact source/photo proof and preview after deployment.

No Product Awards publication should be triggered by the deployment gate.

## Static review result

No blocking selector/state/delivery architecture issue remains after the fixes
above.

The remaining mandatory evidence is runtime validation of the exact first-party
image pages on Termux.
