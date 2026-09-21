# ADR 0075: Weekly municipal bathing-water quality notifications

## Status

Accepted.

## Context

The municipal page `Programa de control de las zonas de baño` already exposes
the current bathing season and links weekly official PDF reports. The existing
adapter discovered only the newest report URL and dates, so it had no
resident-facing value beyond source-state tracking.

The reviewed 2025 and 2026 reports are text-readable and contain one Spanish
table with exactly seven named Guardamar beaches. Each row has three official
qualitative fields:

- `Análisis Agua`;
- `Aspecto Agua`;
- `Aspecto Arena`.

The report also contains Enterococci and E. coli counts, but the municipality
already publishes the qualitative categories `EXCELENTE`, `BUENA`,
`SUFICIENTE`, and `INSUFICIENTE`.

## Decision

1. Keep the existing daily 09:02 `sync-guide` index check. Add no new cron,
   daemon, state file, browser, OCR, or AI dependency.
2. Download a report PDF only when the index points to a report period or URL
   different from the last accepted parsed report. This supports the
   municipality reusing one PDF URL for successive weeks because the index
   dates are part of the identity.
3. Reuse the already-required Poppler `pdftotext -layout` binary. The parser
   reads only the Spanish first page and requires:
   - the Guardamar bathing-water heading;
   - the report period to exactly match the index;
   - one table header containing the three reviewed qualitative columns;
   - exactly the seven reviewed beach rows;
   - exactly one recognized official rating in each qualitative cell.
4. Store only the normalized report period, source URL, observation time, and
   the three official qualitative ratings for each beach. Do not store raw PDF
   bytes and do not calculate a quality class from microbiological counts.
5. The first successfully parsed report after enabling the feature becomes a
   silent baseline. Every later new weekly report is eligible for one public
   group notice even when its qualitative ratings are unchanged, because the
   new sample period is itself resident-relevant.
6. A replacement URL for the same report period with identical normalized
   facts is accepted silently. If the same period is republished under a new
   URL with changed normalized facts, it is eligible for an updated notice.
7. A byte-level correction made under the same URL and the same report period
   is an accepted blind spot: the bot does not redownload an unchanged report
   identity every day merely to hash it.
8. Public copy uses 🧪 to distinguish laboratory water-quality reports from the
   existing beach-wave semantics. The main block reports `Análisis Agua` by
   beach. `Aspecto Agua` and `Aspecto Arena` are shown separately as visual
   inspection facts and never conflated with laboratory water quality.
9. Public wording translates the municipality's categories only; it does not
   add medical advice or infer safety from Enterococci/E. coli values.
10. New-message Telegram delivery follows the shared conservative ambiguity
    contract. State is pre-marked uncertain before the non-idempotent send;
    explicit failures remain retryable, while ambiguous outcomes are not
    blindly resent.

## Consequences

The integration now has a clear resident-facing purpose while remaining
bounded and cheap: one small HTML read per day and usually one PDF download per
new weekly report. A municipal template change fails closed and leaves the last
accepted report intact. Supporting a genuinely new beach topology or report
schema requires a reviewed code change rather than heuristic inference.
