# Product Awards remediation design review — 2026-10-03

## Purpose

Re-review ADR 0093 and the proposed Product Awards incident repair for logical
errors, unnecessary architecture, failure gaps and Termux cost before any
runtime code changes.

The review treats the user's priority as:

1. publish a verified useful product when one is available;
2. prefer supermarket variety when alternatives exist;
3. never weaken award/product evidence merely to fill a slot.

## Findings

### 1. The first retailer-rotation design was too strict

Rejected design:

- store `last_retailer_kind`;
- prohibit the same retailer;
- use a second fallback scan;
- allow silence when only the previous retailer remains.

Why it was wrong:

- it inverted the product priority by making presentation diversity more
  important than publication;
- it introduced state migration and manual-requeue consistency work for a
  non-safety preference;
- it could intentionally create an empty three-day slot even with a valid
  product.

Final decision: retailer diversity is best-effort only.

### 2. New retailer state is unnecessary

Existing `published_events` is append-ordered on confirmed delivery.

The last event ID is enough to derive the previous retailer when that event
still exists in the current reviewed registry. If it no longer exists, the
retailer preference can be treated as unknown because this preference is not a
deduplication or delivery-safety invariant.

Benefits:

- no schema bump;
- no additive state field;
- no migration;
- no rollback incompatibility;
- manual event requeue naturally changes the last published event view;
- fewer tests and failure modes.

### 3. Two selector passes are unnecessary

Rejected design: diversity scan + complete ordinary fallback scan with an
attempted-event set/cache.

Simpler equivalent:

- use the existing category order and source/rank rules;
- find one valid winner per category;
- keep the first same-retailer winner in one local fallback variable;
- continue to later categories;
- return the first valid different-retailer winner;
- if none exists, return the stored fallback.

This is one finite scan and needs no retailer ledger, second pass or
candidate-attempt state.

### 4. Media must not be an eligibility gate

The October incident proved that five Consum candidates had valid award/retail
facts and prices but were discarded only because image delivery failed.

That contradicts publish-first behavior.

Final eligibility remains:

- award evidence;
- exact current retail identity;
- current price.

Image is optional presentation enrichment.

Telegram Rich Messages permit HTML without a media element, so a no-image Rich
Message preserves the same article format and does not require a second
delivery product.

### 5. Keep the existing upload fallback, but demote it

The multipart upload path added on 29 September was based on an incorrect root
cause, but the mechanism itself is small, bounded and useful when Telegram
cannot fetch a genuinely reachable first-party image.

Keep:

remote image -> explicit REMOTE-MEDIA -> bounded local fetch/upload.

Add:

deterministic media-path failure -> same Rich Message without image.

Never fallback after an ambiguous send result.

This preserves value from existing code without allowing it to block
publication.

### 6. Do not probe every image before publication

A proposed Consum fix considered downloading an image merely to validate the
URL before selection.

Rejected because:

- it adds bandwidth to every due product;
- image no longer determines product eligibility;
- Telegram plus the existing bounded recovery path already provide delivery
  validation.

Use official field precedence and host allowlists; degrade to no-image on
failure.

### 7. Consum media selection needs host validation

Current `_remote_image` accepts any syntactically valid HTTPS host from a
retailer payload.

For Product Awards media, the selected URL should also belong to the reviewed
retailer-specific media-host allowlist.

Consum currently has an explicit CDN allowlist. Do not synthesize numbered
filenames: the official `media[]` already supplies them.

### 8. ALDI error predicates must not be over-broad

The earlier ADR draft proposed treating any of:

- `hasError=true`;
- `page=None`;
- `apiData=None`

as a product-specific error.

That is too broad. A future global frontend change could remove/move
`apiData` and would then be falsely diagnosed as a product-specific listing
failure.

Final classification:

- explicit `hasError=true` -> product-page error;
- healthy/ordinary page with missing/null/malformed `apiData` ->
  `RETAIL-DRIFT`;
- `page=None` is diagnostic context, not a standalone predicate.

### 9. Candidate-attempt caching is not justified by the incident

The October logs repeated the NALTROS ALDI request because every failed Consum
media candidate restarted selection.

Once image failure degrades to a no-image publication, the normal incident path
no longer restarts selection.

A process-local candidate cache could still save requests in exotic future
delivery failures, but it adds API/state flow complexity for a path that is no
longer expected.

Decision: do not add it now. Revisit only with new production evidence.

### 10. Retailer preference can increase due-run HTTP cost

If the first valid category winner repeats the last retailer, the selector must
inspect later categories to know whether a different-retailer valid candidate
exists.

This is inherent in the requirement.

The cost is acceptable now because:

- the registry is finite and manually reviewed;
- no requests happen on cooldown days;
- Product Awards run only once daily and publication is due every three local
  days;
- no second scan is added.

Do not add an arbitrary lookahead cap now. If the reviewed registry grows
materially and production traces show problematic cost, re-review with measured
data.

### 11. Pool rebuilding must not block the incident repair

The runtime failure fix is small and independently valuable.

The retailer-balance audit and Producto del Año source-policy review are
separate editorial/catalogue workstreams. Combining all of them into one code
change would enlarge the blast radius and delay restoration of reliable
publication.

Recommended sequencing:

A. implement/test the runtime repair;
B. deploy/observe one due cycle;
C. rebuild the reviewed registry in a separate change;
D. remove or retain Producto del Año candidates based on source-semantic review.

### 12. Avoid a numeric retailer quota

An earlier audit draft proposed a target number of retailers in the unpublished
pool.

Rejected as arbitrary.

Use editorial review instead: investigate whether one chain dominates because
its evidence is stronger or merely because its API is easier. Runtime always
publishes the best valid available material.

### 13. Due-run silence needs explicit observability, not another alert system

Even with publish-first semantics, a due run may legitimately send nothing
when:

- registry is exhausted;
- every award/retailer/price contract fails;
- an uncertain prior Telegram send blocks recovery.

The current logs show candidate failures but lack one final outcome summary.

Add one final concise log reason. Do not add a new operator Telegram alert,
daemon or failure-state machine solely for this feature.

### 14. Media reuse/terms is a documented policy gap

Earlier research required source-specific reuse/terms review before product
photos were enabled. ADR 0084 later operationalized first-party retailer media
without carrying that rule clearly into the durable design.

Do not make this a runtime blocker or legal framework.

For new retailer-media contracts:

- record the reviewed first-party media host and source/terms basis;
- if reuse is unclear, publish the verified article without image.

The new no-image fallback makes conservative media policy cheap.

## Final minimal implementation shape

### Selection

- derive previous retailer from existing last published event when possible;
- one category scan;
- one local same-retailer fallback publication;
- no new persistent state;
- no second pass;
- no retailer quota.

### Retail validation

- award/identity/current price remain mandatory;
- Consum chooses allowlisted `media[]` before the base image;
- image URL is optional;
- ALDI explicit `hasError=true` is distinct from contract drift.

### Delivery

- image available -> remote Rich Message;
- explicit remote-media rejection + locally allowlisted host -> bounded upload;
- deterministic media failure -> no-image Rich Message;
- ambiguous result -> stop, preserve uncertain;
- confirmed result -> existing `confirm`.

### Observability

- candidate diagnostics remain;
- one final due-run outcome log is added;
- no monitoring subsystem.

## Residual risks after the simplification

1. **Extra due-run reads for diversity.** Accepted and bounded; measure before
   optimizing.
2. **Stale/removed last registry event.** Retailer preference becomes unknown;
   publication correctness is unaffected.
3. **Retailer media-host drift.** Image may disappear; no-image publication
   preserves the article.
4. **ALDI changes error semantics.** Healthy missing payload remains drift,
   avoiding a false delisting conclusion.
5. **Pool concentration.** Runtime preference cannot fix the catalogue; handle
   through reviewed registry research.
6. **Award-source quality.** Producto del Año entries need separate semantic
   re-review.
7. **Media reuse rights.** Keep retailer-specific review and fall back to
   no-image when unclear.

## Review result

The original remediation draft had real overengineering and two logic errors:
hard retailer blocking and media-fatal eligibility.

After simplification, the proposed repair is proportionate to the observed
failure:

- no new infrastructure;
- no new persistent state;
- one small selector behavior change;
- two source-specific parser/media corrections;
- one delivery degradation path;
- one logging improvement.

No runtime code was changed during this design review.
