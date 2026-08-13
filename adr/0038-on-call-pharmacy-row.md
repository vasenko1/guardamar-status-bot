# 0038: On-call pharmacy row from the official provincial rota

- Status: Accepted
- Date: 2026-08-12

## Context

The on-call pharmacy is daily practical information with one legally
authoritative publisher, the Colegio Oficial de Farmacéuticos de Alicante.
Its search page is JavaScript-rendered and therefore unusable under the
project constraints, but `research/2026-08-12-farmacia-guardia-source.md`
verified that the page links one official annual XLSX with the complete
provincial rota, parseable with the standard library alone (single sheet,
inline strings, Excel serial dates).

## Decision

- A pre-morning `sync-pharmacy` command makes one bounded fetch of the
  current year's workbook (exact official hosts, accepted content types,
  4 MB cap) and atomically
  stores only Guardamar rows for the next 45 days as a small normalized
  catalog (`state/pharmacy.json`): date, title-cased name and address, and
  a deterministic Russian rendering of the published shift, zero-padded to
  `HH:MM` (`De 9:00 a 9:00` → `круглосуточно (с 09:00)`, otherwise
  `09:00–00:00`). The raw workbook is never stored, and rows with
  unrecognized hours are dropped rather than guessed.
- The download cap bounds only the compressed archive, so the sheet's
  declared uncompressed size is checked against a separate limit before any
  extraction, mirroring the CAP-archive bound in `aemet.py`. The real 2026
  sheet expands from 2 MB to roughly 22 MB, so an unbounded read would let a
  crafted archive inside the 4 MB cap exhaust memory on the target device.
- The college currently serves the workbook as `application/octetstream`
  (a misspelling); the accepted set pins that observed value alongside the
  two standard spellings so a server correction cannot break the sync,
  while any other type fails closed. Cron runs the sync weekly (Sunday `05:50`)
  with the deploy-day retry absorbing failures.
- The Morning Digest reads today's rows from the catalog only — no network
  at 07:30 — and renders at most two lines under `💊 Дежурная аптека:`,
  24-hour duty first, each with the standard Google-Maps address link. A
  missing catalog, missing date, or unreadable file silently omits the
  section.
- The yearly filename (`guardias2027.xlsx`) is derived from the current
  local year; an early-January gap before publication fails closed in the
  sync and leaves the digest row absent.

## Consequences

- Benefits: high-value daily information from the authoritative source at
  one bounded request per week; no AI, no new dependency, stdlib XLSX
  parsing.
- Costs: one more sync command, wrapper, state file, and cron row; a
  format change in the annual workbook breaks the sync loudly (NO-ROWS or
  INVALID-WORKBOOK diagnostics) while the digest degrades silently.
- Follow-up: verify after the first on-device sync that displayed duties
  match the college's own search for a few dates; check in early January
  that the new year's file appears under the expected name.

## Alternatives considered

- Scraping the search page or its WordPress AJAX endpoint — rejected:
  JavaScript execution is prohibited and the endpoint is undocumented.
- Fetching the workbook during the 07:30 run — rejected: the morning
  process makes no non-essential network requests; catalogs are prepared
  beforehand, matching the event-catalog pattern.
