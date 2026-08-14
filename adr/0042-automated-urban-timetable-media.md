# 0042: Automated urban timetable media

- Status: Accepted
- Date: 2026-08-14
- Supersedes the media and manual-refresh restrictions in ADR 0041

## Context

The municipality publishes each Guardamar urban line as a one-page PDF, not
as a reusable image. Residents need the timetable visible in Telegram and the
active July-August or September-June regime identified without an operator
checking the source manually. The production device remains a weak Android
phone, and the linked guide must retain stable navigation and recover from
deleted bot-authored messages.

## Decision

Add one externally scheduled, short-lived `sync-transport` command. It reads a
compact official WordPress index, makes conditional requests for the two
official PDFs and renders a PNG only after a changed PDF is downloaded twice
identically. `pdfinfo` requires one page and `pdftoppm` performs the bounded
render. No browser, OCR, AI, resident process or Python media dependency is
added.

The current reviewed PDF hashes may use their verified calendar periods and
notes. An unknown valid official PDF is still shown, but receives a generic
caption without carrying forward unverified notes or seasonal claims. The
caption retains the direct PDF link for full-quality viewing.

Each line becomes one Telegram photo message. Caption-only changes use
`editMessageCaption`; changed images use `editMessageMedia`. A new photo is
sent exactly once because Telegram has no idempotency key. A transient or
ambiguous response is stored as `delivery_uncertain` and blocks another send.
Confirmed missing messages are recreated, the transport navigator is updated,
and obsolete text or photo messages are deleted only after the new graph is
stored and linked.

Pinned-guide state version 2 migrates version 1 in place, preserves all known
message IDs, stores bounded media metadata and cleanup IDs, keeps one previous
atomic state generation, and fsyncs the containing directory. Current and
previous PNGs are retained as bounded recovery material. All guide publication
and transport synchronization share the same non-blocking file lock.

Termux cron invokes the command once at 05:00 Europe/Madrid. On day one of each
month it performs one unconditional verification download per PDF; otherwise
unchanged sources normally return HTTP 304. The normal daily run also probes
managed messages through idempotent edits and re-pins the compact root.

## Consequences

- Full PDF downloads and CPU-heavy rendering occur only on source changes or
  the monthly verification.
- Telegram receives no media upload when an image is unchanged.
- The existing text-to-photo transition is recoverable but necessarily creates
  two new message IDs; the navigator changes before old text is removed.
- Poppler is one explicit Termux system dependency. Its absence fails only the
  transport sync and cannot break the Morning Digest.
- A source outage preserves the last accepted media. One invalid or unstable
  candidate never replaces it.
- Telegram cannot resolve a lost success response to `sendPhoto`; an uncertain
  delivery therefore requires operator inspection rather than risking a
  duplicate.

## Alternatives considered

- Keep PDFs as links only: avoids rendering but makes the most-used city routes
  harder to scan in Telegram.
- Poll continuously: unnecessary, wasteful and incompatible with Termux.
- OCR every PDF: adds cost and nondeterminism; unknown revisions can use a safe
  generic caption instead.
- Store only Telegram `file_id`: token changes or lost state would remove the
  local recovery path.
