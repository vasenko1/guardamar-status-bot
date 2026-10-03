# ADR 0092: Product Awards resilience and retailer preference

- Status: Accepted, implementation pending
- Date: 2026-10-03
- Refines: ADR 0083, ADR 0084

## Context

The 2–3 October 2026 Product Awards publication gap exposed two independent
runtime problems after the three-day cooldown expired.

First, the reviewed ALDI NALTROS product page no longer resolves as a current
product detail. Both reviewed public routes return HTTP 200 and a Next.js shell,
but `pageProps.hasError=true`, `page=None` and `apiData=None`. Two control
ALDI product pages on the same build still return full product payloads.

Second, every current Consum candidate returns a correct exact EAN, product name
and price while also returning two image surfaces. The current
`productData.imageURL` base filename returns HTTP 404, while the same official
payload's numbered `media[].url` entries return valid JPEGs. Production chose
the stale base field; Telegram therefore correctly rejected a missing asset and
the local recovery retried the same missing URL.

The 29 September diagnosis localized the Consum failure at the wrong layer.

A new editorial preference also applies: consecutive Product Awards posts
should use different supermarkets when a valid alternative exists. Publication
itself remains more important than retailer diversity.

The target runtime is a weak Android phone under Termux. The repair should
remove failure modes without adding a scheduler, queue, database, browser,
persistent cache or new state machine.

## Decision

### 1. Publication is primary; retailer diversity is best-effort

When a due run has a valid unpublished candidate, retailer diversity must not be
the reason for silence.

Use the retailer of the last confirmed published event only as a preference:

- prefer a valid product sold by a different retailer;
- if no different-retailer product is valid, publish the same retailer again;
- never choose a lower-ranked candidate inside a category merely to change
  supermarket;
- force mode keeps the same preference semantics.

### 2. Do not add retailer state

No `last_retailer_kind` field is needed.

`published_events` already preserves confirmed publication order. For
selection, inspect only its last event ID and resolve that ID against the
current reviewed registry:

- if the event is still known, use its configured `retailer_kind`;
- if there is no prior event or the old event no longer exists in the current
  registry, treat the previous retailer as unknown and use ordinary selection.

Retailer preference is not a safety invariant, so an unknown historical
retailer is acceptable. This avoids schema migration, extra state validation,
manual-requeue repair and rollback concerns.

### 3. Use one bounded scan with one in-memory fallback

Keep the existing category cursor and ordinary source-native priority/rank
semantics.

During one selection call:

1. walk categories in cursor order;
2. inside each category, find its first **valid** candidate using the current
   source/rank rules;
3. if there is no known previous retailer, return that publication immediately;
4. if its retailer differs from the previous retailer, return it immediately;
5. if it uses the same retailer and no fallback is stored yet, keep that
   publication in one local variable and continue with the next category;
6. after all categories have been inspected, return the stored same-retailer
   fallback, if any.

Do not inspect lower ranks after a valid candidate has already won its category.

This requires no second registry pass, no persistent rotation ledger and no
new candidate-attempt state.

The cost tradeoff is explicit: when the first valid category repeats the
previous retailer, the due run may verify later categories in search of a
different retailer. The registry is finite and reviewed; this additional work
occurs only on due runs.

### 4. A product image is enrichment, not publication eligibility

A Product Awards article still requires:

- valid reviewed award evidence;
- exact current retailer product identity;
- current price.

A product image is preferred but optional.

`RetailOffer.image_url` therefore becomes optional. A missing, stale or
undeliverable image must not invalidate an otherwise publishable product.

Rich Message delivery uses this order:

1. when an allowlisted exact image URL exists, try the normal remote-image Rich
   Message;
2. only after Telegram explicitly rejects remote media, keep ADR 0084's one
   bounded local image download and multipart upload attempt;
3. if the local image cannot be fetched, or the explicit upload path fails
   deterministically, send the same Rich Message **without the image**;
4. after any ambiguous Telegram send outcome, do not attempt another send.

Telegram Rich Messages support HTML content without media, so the final fallback
does not need a second message format or a normal `sendMessage` conversion.

A successful no-image delivery is a normal confirmed Product Awards
publication and consumes the three-day slot.

### 5. Fix Consum media precedence without probing every image

For `retailer_kind=consum`:

1. keep exact EAN/name/price validation unchanged;
2. inspect official `media[]` entries first, in source order;
3. accept only syntactically valid HTTPS URLs on the explicit Consum media-host
   allowlist;
4. if no usable `media[]` entry exists, consider
   `productData.imageURL` only when it is also on the allowlist;
5. do not synthesize `_001`, `_002` or other filenames;
6. do not download an image merely to decide whether the product itself is
   eligible.

Reachability is handled by the delivery recovery path. If all image paths fail,
the article degrades to no-image publication.

This is Consum-specific evidence. Do not generalize its field precedence to
other retailers without a source probe.

### 6. Make ALDI error classification precise

Parse the Next.js page state before `apiData`.

- `pageProps.hasError is True` -> classify as a product-page error for this
  candidate and fail it closed for the invocation;
- healthy/ordinary page state with missing, null or malformed `apiData` ->
  classify as retailer contract drift;
- otherwise continue with the existing exact object ID, identity-marker,
  availability and price checks.

Do not use `page is None` by itself as a product-error predicate.

This avoids turning a future global ALDI frontend change into a false
product-specific diagnosis.

NALTROS remains unpublished and retryable on a later daily due run.

### 7. Keep the existing delivery-safety boundary

Before every non-idempotent send attempt, reserve the event as uncertain.

- explicit deterministic failure clears the reservation before another safe
  fallback attempt;
- ambiguous send outcome leaves the reservation and stops;
- confirmed remote-image, uploaded-image or no-image delivery uses the same
  existing `confirm` path;
- no retry path may create a second message after an ambiguous result.

### 8. Improve due-run observability without a new alerting system

A due run that publishes nothing should finish with one concise final log reason,
for example:

- registry exhausted;
- all candidates unavailable/unprovable;
- uncertain prior delivery blocks resend.

Do not add a new operator-notification channel, monitoring daemon or persistent
failure state solely for Product Awards.

Candidate-level diagnostic logs remain the evidence for the exact source/media
failure.

## Registry rebalance is separate from the incident repair

The current reviewed registry is editorially imbalanced:

- one ALDI candidate;
- five Consum candidates;
- one Masymas candidate.

Earlier project research already proved strong Mercadona award-to-SKU joins and
identified viable Lidl, DIA and Carrefour award/retail surfaces. The current
Consum concentration is therefore a registry-construction artifact, not
evidence that other chains lack strong products.

Rebuilding the pool is a separate research/configuration workstream and must not
delay the small runtime repair above.

Research priority:

1. revalidate already-proven Mercadona/WCCC joins;
2. investigate Lidl, DIA and Carrefour candidates;
3. add another healthy ALDI candidate when evidence supports one;
4. keep Masymas locally relevant;
5. retain valid Consum candidates, but do not expand Consum first merely because
   its exact-product API is easy;
6. re-review the four Producto del Año 2026 candidates against ADR 0083 source
   admission because retailer technical convenience is not award-quality
   evidence.

This is not a retailer quota. If only one retailer has valid products, the bot
continues publishing that retailer.

## Scope deliberately rejected

Do not add:

- a retailer quota;
- a retailer-history ledger;
- `last_retailer_kind` state;
- a second selector pass;
- a persistent negative-candidate cache;
- `attempted_event_ids` state;
- image filename guessing;
- image reachability probes for publication eligibility;
- browser/Playwright;
- LLM product matching;
- a new cron or discovery worker.

## Validation required before implementation is complete

Tests must prove at least:

- previous retailer is derived from the last published event when that event is
  still present in the registry;
- unknown/removed historical event causes ordinary selection, not failure;
- same-retailer first valid category is kept as fallback while a later
  different-retailer valid category is preferred;
- when no different-retailer candidate is valid, the stored same-retailer
  fallback publishes;
- a valid candidate prevents lower ranks in its category from being used merely
  for retailer diversity;
- no new state field is written for retailer preference;
- Consum prefers allowlisted `media[].url` over the stale base image;
- non-allowlisted media URLs are ignored;
- absence or failure of every image still produces a no-image publication;
- ambiguous remote/upload/no-image delivery never triggers another automatic
  send;
- ALDI `hasError=true` is classified as product-page failure;
- ALDI missing/null `apiData` without `hasError=true` remains contract
  drift;
- a due run with no publication writes one final summary reason.

## Consequences

The repair stays small and makes the product more reliable:

- retailer variety improves when the reviewed pool supports it;
- retailer preference never suppresses the only valid article;
- media cannot block a verified product;
- no state migration is required;
- no second selector pass or candidate cache is required;
- ALDI diagnostics become more truthful.

Pool quality remains the long-run control against the appearance of retailer
promotion; runtime heuristics are only a presentation preference.
