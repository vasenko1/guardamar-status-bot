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

### 1. Make consecutive-retailer exclusion a hard publication rule

The last **confirmed** Product Awards retailer becomes temporarily ineligible
for the next confirmed Product Awards publication.

Use the stable retailer identity key already attached to a reviewed candidate
(the current `retailer_kind` concept), not the display label.

The rule is strict:

- a force/operator cooldown bypass does not bypass retailer rotation;
- an uncertain Telegram outcome does not advance the last retailer;
- a deterministic failed send does not advance the last retailer;
- when every otherwise eligible remaining category would repeat the last
  retailer, publish nothing;
- a silent run does not consume the three-day slot or change the category
  cursor.

No same-retailer fallback is allowed merely to maintain cadence.

### 2. Preserve category/source rank semantics while rotating retailers

Retailer rotation is not permission to demote an authoritative result.

Walk categories from the existing category cursor. Inside a category, preserve
the configured source priority and source-native rank order.

When the next candidate reached in that order belongs to the last confirmed
retailer, defer the **rest of that category for this invocation** and continue
with the next broad category. Do not skip a rotation-blocked #1 merely to
publish #2 or a secondary source from another supermarket.

Higher-ranked candidates that already failed their normal exact authority or
retail verification may still allow the next ranked candidate to be reached in
the ordinary way. The retailer gate applies when each candidate is reached.

This keeps both invariants true:

1. source-native quality ordering remains authoritative;
2. the public retailer sequence never repeats consecutively.

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
Therefore, after the next successful Consum publication, strict retailer
rotation may intentionally produce no later publication until ALDI recovers or
a new reviewed candidate from a different supermarket is added.

This is expected behavior, not a reason to weaken the rotation rule.

Registry enrichment for Mercadona, Lidl, DIA, Carrefour or another approved
local retailer is a separate evidence task. A retailer may be added only with
the existing award-authority and exact-current-retail proof; rotation must never
manufacture a weaker product merely to fill a slot.

## Validation required before implementation is complete

Tests must prove at least:

- old state without `last_retailer_kind` still loads;
- confirmed delivery records the retailer; failed/uncertain delivery does not;
- force mode cannot repeat the same retailer;
- a same-retailer next candidate defers its category without source/retailer
  HTTP and without falling through to a lower rank solely for diversity;
- the selector can continue to a later category from a different retailer;
- all-same-retailer remainder produces no publication and no state/cooldown
  mutation;
- after another retailer publishes, the previously deferred category becomes
  eligible again;
- Consum chooses a real `media[].url` over a stale
  `productData.imageURL`;
- a Consum base-only image requires bounded validation;
- no synthetic Consum filename guessing is used;
- ALDI `hasError=true/apiData=None` is classified before product parsing;
- a candidate already failed in the current invocation is not fetched again
  after another candidate's deterministic media failure.

## Consequences

The runtime remains small, but publication cadence becomes deliberately
content-dependent. Retailer diversity may create silence when the reviewed pool
is too concentrated in one chain.

That silence is preferable to presenting Product Awards as if the feature
covered different supermarkets while repeatedly showing the same retailer.

The source investigation and exact retail registry remain the mechanism for
improving variety; runtime heuristics do not substitute for evidence.
