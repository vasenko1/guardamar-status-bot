# ADR 0092: Product Awards resilience and retailer rotation

- Status: Accepted, implementation pending
- Date: 2026-10-03
- Refines: ADR 0083, ADR 0084

## Context

The 2–3 October 2026 Product Awards publication gap exposed two independent
runtime problems after the three-day cooldown expired.

First, the reviewed ALDI NALTROS product page no longer resolves as a current
product detail. Both reviewed public routes return HTTP 200 and a Next.js shell,
but `pageProps.hasError=true`, `page=None` and `apiData=None`. Two control
ALDI product pages on the same build still return full product payloads. This is
therefore product-specific ALDI failure or delisting, not a global ALDI parser,
network, User-Agent or route failure.

Second, every current Consum candidate returns a correct exact EAN, product name
and price while also returning two different image surfaces. The
`productData.imageURL` base filename exists as a string but returns HTTP 404.
The official `media[].url` entries for the same exact product return valid
JPEGs. The runtime preferred the stale base field, so Telegram correctly
rejected the missing image and the local recovery then downloaded the same
missing URL and also received 404.

The 29 September diagnosis therefore localized the Consum failure at the wrong
layer. The reachable `_001.jpg` observed during that investigation was not the
URL actually selected by production.

A new editorial requirement also applies: two consecutive Product Awards posts
must not feature the same supermarket. Retailer diversity is part of the public
product experience, not merely a tie-breaker.

The target runtime remains a weak Android phone under Termux. The solution must
stay bounded, deterministic and browser-free.

## Decision

### 1. Make retailer diversity a preference, never a publication blocker

The primary Product Awards invariant is availability of useful content: when a
due run has at least one valid unpublished candidate, retailer diversity must
not be the reason the workflow stays silent.

The last **confirmed** Product Awards retailer is therefore a preference input,
not a hard exclusion. Use the stable retailer identity key already attached to
a reviewed candidate (the current `retailer_kind` concept), not the display
label.

The rule is:

- prefer a valid candidate from a retailer different from the last confirmed
  retailer;
- if no such candidate can be selected under the normal category/source/rank
  rules, allow the same retailer again;
- force/operator cooldown bypass preserves the same preference/fallback logic;
- an uncertain or failed Telegram delivery never advances the last retailer;
- retailer diversity alone never creates a silent due run.

A due run may still stay silent when every candidate fails the ordinary award,
exact-retail, price, media or delivery-safety requirements.

### 2. Use a two-pass selector and preserve source-native rank

Retailer diversity is not permission to demote an authoritative result.

Walk categories from the existing category cursor and keep the configured
source priority and source-native rank order.

Use two bounded passes over the same finite reviewed registry:

1. **diversity pass:** prefer categories whose next reachable candidate does
   not use the last confirmed retailer. When normal rank order reaches a
   same-retailer candidate, defer the remainder of that category for this pass
   rather than skipping that candidate to reach a lower rank;
2. **fallback pass:** only when the diversity pass finds no publishable
   candidate, walk the registry under the ordinary category/source/rank rules
   with no retailer exclusion. A same-retailer candidate may then publish.

Candidates already proved unavailable in pass one are remembered only in a
process-local attempted set and are not fetched again in pass two.

This keeps three invariants true:

1. publish when at least one normal candidate is valid;
2. prefer a different supermarket whenever a valid alternative exists;
3. never choose a lower-ranked product merely to manufacture retailer variety.

### 3. Keep one minimal retailer field in delivery state

Extend the existing atomic Product Awards state with one optional
`last_retailer_kind` field.

This is a backward-compatible additive state change. Existing schema-v1 files
without the field remain readable. On the first upgraded read, derive the value
from the most recently confirmed published event when that event is still known
to the reviewed registry; otherwise treat it as unknown. Every later confirmed
delivery writes the explicit retailer key.

No retailer history, queue, database or rotation ledger is added.

Operator recovery that manually removes the most recent published event must
also recompute or clear `last_retailer_kind`; normal runtime never edits
published history backwards.

### 4. Treat Consum `media[]` as the current exact image contract

For `retailer_kind=consum`:

1. keep exact product-code/EAN/name/price validation unchanged;
2. inspect the official product payload's `media[]` entries in source order;
3. use the first syntactically valid allowlisted HTTPS `url`/ `imageURL`;
4. do not synthesize `_001`, `_002` or other filenames;
5. only if no usable `media[]` entry exists, consider
   `productData.imageURL`, and accept that base field only after one bounded
   local image validation.

The current remote-URL Telegram path remains the cheapest first attempt. If
Telegram still rejects a valid first-party image, ADR 0084's one bounded local
download plus multipart upload remains the recovery path.

This change is Consum-specific. Do not generalize the stale-base-image behavior
to Masymas or another retailer without source evidence.

### 5. Recognize ALDI product-specific error state explicitly

Before parsing ALDI `apiData`, inspect the reviewed Next.js page state.

If `pageProps.hasError is true`, `page is None`, or `apiData is None`,
classify the exact product as a product-specific retailer failure and skip the
candidate for that invocation. Do not call it a successful current listing, do
not infer delisting as a public fact, and do not switch to browser automation,
search-engine snippets or an alternate route.

The current NALTROS candidate remains unpublished and retryable. If ALDI later
restores a valid exact product payload, the ordinary exact-object checks may
make it eligible again.

### 6. Do not re-fetch a failed candidate within one invocation

Keep one process-local set of Product Awards event IDs already evaluated during
the current command.

If delivery of a later selected candidate fails deterministically and selection
continues, candidates that already failed authority/retailer verification in
that same invocation are not fetched again.

This set is never persisted. A later daily invocation starts clean so temporary
source recovery remains automatic.

### 7. Keep the existing delivery and resource boundaries

No new cron, daemon, queue, browser, image processor, LLM, database, cache or
dependency is introduced.

The existing rules remain:

- one cheap daily cron invocation;
- three-local-day cooldown after a confirmed publication;
- one non-idempotent publication at most per invocation;
- exact source and retailer identity validation;
- bounded standard-library HTTP;
- uncertain-before-send reservation;
- no state consumption on a skipped/unpublishable candidate.

## Current-pool consequence

The current reviewed production registry is retailer-imbalanced:

- one ALDI candidate: NALTROS Brut;
- five Consum candidates;
- one Masymas candidate: Mahou Sin Filtrar.

Mahou is already published and NALTROS is currently product-erroring at ALDI.
Therefore a same-retailer Consum publication remains allowed when every
different-retailer candidate is unavailable. The imbalance is still an
editorial-health problem because repeated Consum posts can make the feature look
retailer-sponsored, so the reviewed pool should be expanded before relying on
runtime preference alone.

Registry enrichment for Mercadona, Lidl, DIA, Carrefour or another approved
local retailer is a separate evidence task. A retailer may be added only with
the existing award-authority and exact-current-retail proof; rotation must never
manufacture a weaker product merely to fill a slot.

## Validation required before implementation is complete

Tests must prove at least:

- old state without `last_retailer_kind` still loads;
- confirmed delivery records the retailer; failed/uncertain delivery does not;
- the diversity pass prefers a different retailer without falling through to a
  lower rank solely for variety;
- the selector can continue to a later category from a different retailer;
- when no different-retailer candidate is publishable, the fallback pass may
  publish the same retailer;
- retailer preference alone never causes silence or cooldown/cursor mutation;
- after another retailer publishes, the previously deferred category naturally
  regains first-pass priority;
- Consum chooses a real `media[].url` over a stale
  `productData.imageURL`;
- a Consum base-only image requires bounded validation;
- no synthetic Consum filename guessing is used;
- ALDI `hasError=true/apiData=None` is classified before product parsing;
- a candidate already failed in the current invocation is not fetched again
  after another candidate's deterministic media failure.

## Consequences

The runtime remains small and publication cadence is not weakened by retailer
diversity. Repeating one supermarket is acceptable when it is the only valid
choice, but a different valid retailer is preferred first.

The source investigation and exact retail registry remain the main mechanism
for improving long-run variety; runtime preference cannot compensate for an
imbalanced pool and must never substitute for award/retail evidence.
