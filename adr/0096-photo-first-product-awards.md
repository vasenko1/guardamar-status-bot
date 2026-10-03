# ADR 0096: Photo-first Product Awards delivery contract

- Status: Implemented in main; production validation pending
- Date: 2026-10-03
- Refines: ADR 0083, ADR 0084, ADR 0093, ADR 0095

## Context

The post-production review briefly proposed making the current Product Awards
registry text-only because some retailer-media reuse rights were not yet
documented clearly enough.

That conclusion conflicts with the accepted product experience.

A Product Awards post is inherently visual: users should immediately see what
the awarded product looks like. A no-image article is acceptable only as a
degraded recovery mode when an exact product image cannot be delivered safely
after bounded best-effort recovery.

The existing runtime already has useful pieces:

- exact product identity is verified before publication;
- some retailer adapters expose exact first-party product media;
- Telegram Rich Messages support remote media;
- ADR 0084 / ADR 0093 provide bounded local download/upload recovery;
- ADR 0093 already permits a final no-image send after deterministic media
  failure without weakening award/retail eligibility.

The missing piece is a clear **photo-first source policy**. The bot should not
depend on one retailer CDN or give up after the first image source fails. It
should try a small reviewed set of exact official product-image sources while
remaining suitable for Termux.

## Decision

### 1. A photo is the normal Product Awards presentation

Every normal Product Awards publication should include an exact photo of the
awarded product.

No-image publication is a degraded fallback only. It is allowed when all
reviewed image paths for the selected exact product are blocked by one or more
of:

- exact-image identity cannot be proved;
- approved image-source/reuse conditions are not satisfied;
- the reviewed source no longer exposes the exact image;
- bounded image download fails;
- Telegram rejects both reviewed remote and bounded uploaded media paths;
- another deterministic image-path failure prevents safe delivery.

Image failure must never turn into a false product claim or automatic duplicate.

### 2. Use a small reviewed image-source hierarchy

For one selected candidate, try only explicitly reviewed official sources in
candidate order. Normal preference is:

1. official producer / brand product page or official press/media asset;
2. official award-organizer product image when it represents the exact awarded
   product;
3. official retailer exact-product image.

A lower source is tried only when the preceding reviewed image source is
unavailable or unusable.

Do not perform runtime image search, search-engine lookup, fuzzy matching,
computer vision, screenshot capture or browser automation.

Each candidate may have only a small explicit set of reviewed image contracts.
The runtime must not crawl a whole site to discover alternatives.

### 3. Exact image identity is mandatory

An image source is usable only when it is tied to the exact commercial product
selected for publication.

Variant-critical qualifiers must match when relevant:

- brand and product line;
- flavor / recipe / style;
- bottle or package format;
- vintage / designation / cuvée for wine;
- other category-specific differentiators.

A generic brand image, family shot, unrelated pack size or similar-looking
product is not an acceptable fallback.

### 4. Image-source suitability is an explicit reviewed contract

Technical accessibility is not enough and a public URL is never promoted to a
runtime image source automatically.

Every active image path must be explicitly admitted during source review and
stored in the candidate's reviewed image contract: official page, allowed image
hosts, exact page markers and exact image identity markers where available.

The runtime does not search for alternative images and does not infer legal or
editorial suitability from a URL at execution time. A separate machine-readable
licence/state field is not required; admission itself is the review boundary.

If a reviewed image source later becomes unsuitable or ambiguous, remove that
contract. The product remains eligible and the bot continues through the next
reviewed exact image source before degrading.

### 5. Preserve bounded delivery recovery

For each usable reviewed image source:

1. prefer the ordinary remote-image Rich Message;
2. if Telegram explicitly rejects remote media and the image host is approved
   for bounded local retrieval, download once with existing type/size/host
   bounds;
3. retry the same Rich Message once using Telegram multipart upload;
4. if that image source fails deterministically, continue to the next reviewed
   exact image source when one exists;
5. only after every reviewed image source is exhausted may the same verified
   article be sent without media.

After any ambiguous Telegram send outcome, stop immediately. Do not try another
image or a no-image fallback after ambiguity.

### 6. Keep image acquisition cheap

The photo-first requirement must not add:

- a browser;
- image processing;
- OCR;
- runtime web/image search;
- AI image selection;
- persistent image cache;
- background image worker;
- new cron;
- generic media discovery framework.

A candidate may require one or a few bounded exact image reads only on a due
publication run.

Non-due days remain zero-network for Product Awards.

### 7. Prefer product/brand media over retailer dependency where practical

The reviewed registry currently has promising official product-image surfaces:

- Realfooding Gazpacho: official Realfooding product page;
- Oleoestepa DOP Estepa: official Oleoestepa product range;
- Anís Chinchón Dulce: official González Byass Chinchón page;
- Ambar Especial: official Ambar product page;
- Mahou Sin Filtrar: official Mahou product page;
- AROM'ARTE Intenso: official DIA exact-product page;
- NALTROS Brut: official ALDI exact-product page.

These are image-source candidates, not automatic approval. Exact image URLs,
identity and reuse basis must be reviewed before activation.

The purpose of this hierarchy is resilience: an article should not lose its
photo merely because the retailer image field/CDN is stale when an exact
official producer image is available.

### 8. No-image fallback still consumes the slot after confirmed delivery

If all photo paths fail deterministically but award identity, exact current
retail identity and current price remain valid, the selected product may still
publish without media.

That confirmed degraded publication:

- uses the same event/selection identity;
- advances the same category cursor;
- records the same delivery day;
- consumes the normal three-day slot.

This is an emergency presentation fallback, not a separate content mode.

## Validation

Before implementation is complete, tests must prove:

- a normal selected product with one valid reviewed image sends with media;
- source #2 is tried only after source #1 fails deterministically;
- exact image identity mismatch skips that image source;
- an unapproved media source is skipped rather than used;
- remote-media rejection can use bounded upload recovery;
- deterministic failure of one image source can move to the next reviewed image;
- deterministic exhaustion of all reviewed image sources sends the same article
  without media;
- ambiguous delivery at any send attempt stops all further sends;
- cooldown/source/retailer selection behavior is unchanged;
- no runtime image search/browser/cache/background work is introduced.

## Consequences

Product Awards remain visually useful by default without making image delivery a
hard publication veto.

The design may add a few explicit image contracts to the reviewed registry, but
it does not add a new subsystem.

The previous fourth-pass recommendation to make the current registry text-only
is superseded by this ADR.

## Implementation shape

The reviewed implementation keeps selection media-neutral. After one candidate
wins normal award/retail selection, delivery lazily resolves its reviewed image
sources in order. Exact-alt contracts fail closed and cannot fall back to a
generic same-host OG banner. The existing current retailer image is appended as
a fallback only when the retail adapter already exposes one.

The same change restores the deterministic article contract: retailer in the
headline, exact package, verified country when available, producer, one
source-backed product highlight, precise Carrefour website-price wording and
correct Russian sample-count declension.

See
`research/2026-10-03-product-awards-photo-first-implementation-review.md`.
