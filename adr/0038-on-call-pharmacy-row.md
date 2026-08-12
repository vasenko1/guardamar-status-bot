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
  current year's workbook (exact official hosts, 4 MB cap) and atomically
  stores only Guardamar rows for the next 45 days as a small normalized
  catalog (`state/pharmacy.json`): date, title-cased name and address, and
  a deterministic Russian rendering of the published shift
  (`De 9:00 a 9:00` → `круглосуточно (с 9:00)`, otherwise `start–end`).
  The raw workbook is never stored, and rows with unrecognized hours are
  dropped rather than guessed. Cron runs the sync weekly (Sunday `05:50`)
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
