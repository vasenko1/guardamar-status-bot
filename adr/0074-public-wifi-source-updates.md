# ADR 0074: Public municipal Wi-Fi source updates

## Status

Accepted — 2026-09-21

## Context

The municipal Wi-Fi card contains durable resident-facing points, SSIDs and
passwords. ADR 0068 treated a changed official map only as a private operator
review trigger. That leaves the public card stale even when a replacement
official document is machine-readable and its facts can be validated
deterministically.

The existing 09:02 guide sync already has the source lock, small atomic state,
pinned-message reconciliation and Poppler dependency needed for a bounded
update lifecycle.

## Decision

Reuse the existing guide sync; add no new scheduler or resident process.

At most once per local day:

1. Read the official municipal Wi-Fi landing page.
2. Require exactly one linked municipal HTTPS PDF under
   `/wp-content/uploads/`.
3. If its URL is unchanged, stop without downloading the PDF.
4. If changed, download it with strict size/type/time bounds and extract its
   text using the existing `pdftotext -layout` dependency.
5. Accept only a complete snapshot of the reviewed seven point identities and
   the reviewed network topology: one network at each point except exactly
   three at Biblioteca Pública. Credential values may change.
6. On any missing, extra, duplicate or unrecognized point/network, fail closed
   and preserve the previous public card.
7. Persist the accepted snapshot, reconcile the existing Wi-Fi card first, and
   only after successful card reconciliation send one public group notice with
   a direct link to that card.

The first observation of the reviewed baseline is silent. Private operator
alerts are not part of this lifecycle.

For the public change notice, use the shared conservative classification for
non-idempotent Telegram sends. Explicit rejection remains retryable on a later
guide run; an ambiguous result is recorded as uncertain and is not blindly
resent.

## Constraints

Do not add OCR, image recognition, AI extraction, Selenium, another cron row,
another state file, a generic document framework or a resident Wi-Fi worker.
Do not auto-accept a changed topology merely because some credentials were
parsed.

Same-URL byte replacement remains an accepted blind spot until production
evidence justifies one bounded content fingerprint.

## Consequences

Residents receive one low-frequency update only after the source facts have
been validated and the durable card already contains the new information.
Source/parser failures cannot erase the last accepted credentials or generate a
false change notice.

The phone normally pays only for the small daily landing-page request; a PDF
download occurs only after the linked asset URL changes.
