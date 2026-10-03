# Product Awards implementation review — 2026-10-03

## Scope

Post-implementation review of PR #275 after the Product Awards remediation code,
tests and durable documentation were written.

This is a code review of the actual implementation, not the earlier design
review.

## Files reviewed

Runtime:

- `src/telegrambot/product_awards.py`;
- `src/telegrambot/__main__.py`.

Tests:

- `tests/test_product_awards.py`;
- `tests/test_product_awards_delivery.py`;
- existing Rich Message transport tests.

Durable documents were cross-checked against the final runtime behavior,
including ADR 0083, ADR 0084 and ADR 0093.

## Review findings fixed before approval

### Python 3.9 compatibility

The first implementation draft introduced two PEP 604 `|` type annotations.
The project declares `requires-python = ">=3.9"`, while that syntax requires
Python 3.10.

Fix:

- removed the new `dict | list` annotation from the ALDI helper;
- removed the new `str | None` test annotation.

No new Python syntax now exceeds the declared runtime floor.

### Partial temporary-file leak

The first upload-recovery draft assigned the temporary path only after writing
image bytes. If the write failed after the file had been created, cleanup did
not know the path and could leave a private temporary file behind.

Fix:

- capture `temporary.name` immediately after file creation;
- keep deletion in the outer `finally`.

### Cleanup must not overturn a successful send

The pre-existing cleanup style could let an `unlink()` failure escape after a
successful Telegram send and successful state confirmation.

That would not create an automatic duplicate because state was already
confirmed, but it would produce a misleading failed process exit.

Fix:

- temporary media deletion is now best-effort;
- cleanup failure is logged as a warning and cannot change delivery success.

## Selection review

The final selector adds no persistent retailer field and no second scan.

Review confirms:

- previous retailer is derived from the last confirmed event already stored in
  `published_events`;
- an old event absent from the current registry degrades to no retailer
  preference rather than a state error;
- source priority and source-native rank remain unchanged;
- the first valid candidate still wins its own category;
- a same-retailer category winner is held only as one in-memory fallback;
- later categories may supply a different-retailer winner;
- when no different-retailer winner exists, the stored same-retailer candidate
  publishes;
- retailer preference therefore cannot create a silent due run by itself.

The extra HTTP cost exists only on due runs when the first valid category repeats
the previous retailer and later categories must be checked. Current registry
size makes this bounded and acceptable.

## Retail/source review

### Consum

The implementation now:

- validates exact EAN/name/price as before;
- reads official `media[]` before the stale base `productData.imageURL`;
- accepts media only from the reviewed Consum CDN host;
- does not synthesize numbered filenames;
- keeps an exact product publishable when no image is usable.

This directly addresses the production forensic evidence.

### ALDI

The implementation now distinguishes:

- explicit `pageProps.hasError is True` -> `RETAIL-PAGE-ERROR`;
- healthy/ordinary page with missing/null/malformed `apiData` ->
  `RETAIL-DRIFT`.

`page=None` alone is not used as a product-error predicate.

ALDI media is restricted to the reviewed Scene7 host and is optional. A media
host change therefore degrades presentation instead of blocking a valid exact
offer.

### Masymas

Existing exact EAN/price behavior is preserved. The current 300x300 preference
probe remains source-specific and does not determine product eligibility.

## Delivery-safety review

All non-idempotent send transitions preserve the existing uncertain-delivery
rule.

### Remote Rich Message

Before send:

- event is reserved as uncertain.

On result:

- confirmed -> normal state confirmation;
- ambiguous -> reservation remains, no fallback send;
- explicit non-media rejection -> reservation is cleared and error remains
  fail-closed;
- explicit `REMOTE-MEDIA` -> safe media recovery may begin.

### Local upload recovery

After an explicit remote-media rejection:

- local image fetch is bounded and allowlisted;
- upload uses a private temporary file;
- event is reserved again before upload;
- confirmed upload -> normal confirmation;
- ambiguous upload -> reservation remains and no no-image send occurs;
- deterministic upload/media-path failure -> reservation is cleared before the
  no-image fallback.

### No-image fallback

The fallback rebuilds the same deterministic Rich Message with media omitted.

- it reserves the event before send;
- confirmed send uses the same normal `confirm` path;
- ambiguous result remains reserved and stops;
- deterministic rejection clears the reservation and raises.

This preserves at-most-once safety while preventing image failure from
discarding a verified product.

## Test review

New tests cover:

- Consum `media[]` precedence over stale base image;
- unreviewed media-host rejection;
- exact offer with no media;
- ALDI explicit page error;
- ALDI missing `apiData` contract drift;
- ALDI exact offer with no primary image;
- no-image renderer;
- ordered last-published event lookup;
- different-retailer preference;
- same-retailer fallback;
- no rank demotion for retailer variety;
- removed/unknown historical event behavior;
- remote-media -> local media failure -> no-image send;
- deterministic upload rejection -> no-image send;
- ambiguous remote send -> no fallback;
- ambiguous upload -> no fallback;
- direct exact offer without image.

The project currently exposes no pull-request GitHub Actions/status checks for
this head commit. Therefore this review does **not** claim that tests were
executed in GitHub.

The production deployment procedure must run, against the exact reviewed commit
before changing the live checkout:

1. Python compileall;
2. Product Awards unit tests;
3. Rich Telegram Product Awards tests;
4. the complete unittest suite;
5. a read-only live Product Awards preview.

Any failure aborts deployment before the production checkout is advanced.

## Documentation review

Fresh `main` claimed ADR 0092 for event-centric event-access state while the
Product Awards design work was in progress.

The Product Awards refinement was therefore renumbered to **ADR 0093** and
ported onto current main rather than copying the older docs branch wholesale.

This preserves the two newer event-access commits and avoids an ADR collision.

## Residual risks

No blocking code-review issues remain.

Accepted residual risks:

- retailer diversity can cause extra bounded source reads on a due run;
- retailer/CDN media can drift, but no-image delivery now preserves the post;
- an unrelated deterministic Telegram Rich Message rejection remains
  fail-closed rather than trying another product;
- the current registry is still Consum-heavy;
- the four Producto del Año entries still require the separately documented
  source-semantic re-review.

The last two are catalogue/editorial workstreams and are deliberately excluded
from this incident repair.

## Review result

**No blocking code-review findings remain after fixes.**

The implementation matches ADR 0093, preserves the existing state schema and
Termux architecture, and is ready for the mandatory production-device test
gate before live checkout update.
