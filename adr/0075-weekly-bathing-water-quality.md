# ADR 0075: Weekly bathing-zone control notifications

## Status

Accepted.

## Context

The municipal page `Programa de control de las zonas de baño` publishes the
current bathing season and links official weekly PDF reports named
`Análisis de las aguas e inspección semanal`.

The control authority is the Generalitat Valenciana's `Servicio de Calidad de
Aguas`. Its bathing-water programme covers laboratory water quality together
with visual inspection of bathing zones. The reviewed Guardamar reports contain
exactly seven beach rows and three qualitative fields:

- `Análisis Agua` / `Anàlisi Aigua`;
- `Aspecto Agua` / `Aspecte Aigua`;
- `Aspecto Arena` / `Aspecte Arena`.

Reports also contain Enterococci and E. coli counts, but the source already
publishes qualitative categories. The bot must not derive its own public
classification from microbiological counts.

Observed 2026 publication times did not have one fixed weekday: reports were
uploaded on Thursday, Friday, Saturday or Monday, with server timestamps ranging
from morning to 19:14 local time. Actual sample dates are separately printed in
the beach rows and can differ from the report's covered week.

## Decision

1. Add no resident service, DB, queue, browser, OCR or AI dependency. Use one
   short-lived `sync-bathing-water.sh` one-shot at 19:35 Europe/Madrid during
   June-August and through 20 September. The September grace allows a final
   report to arrive up to five days after the official 15 September season end.
2. Keep bathing-water work out of the normal 09:02 guide sync so the guide's
   other sources are not fetched a second time. Both flows share the existing
   atomic `GuideState` and its exclusive run lock.
3. The one-shot reads the small municipal index once per local day. Download a
   report PDF only when the newest report period or URL differs from the last
   accepted parsed report. A reused PDF URL across successive weeks is safe
   because the report date range is part of the identity.
4. Reuse the already-required Poppler `pdftotext -layout` binary. Accept only
   the reviewed Spanish or Valencian first-page layouts, requiring:
   - the Guardamar bathing-zone programme heading;
   - an embedded report period exactly matching the index;
   - at least one actual sample date printed as `Fecha/Data desc. punto1/punt1`,
     all inside that report period;
   - one of the reviewed Spanish/Valencian qualitative table headers;
   - exactly the seven reviewed beach identities;
   - exactly one recognized official rating in each qualitative cell.
5. Normalize and persist only observation time, report period, report URL,
   unique sample dates, and the three official qualitative ratings per beach.
   Discard raw PDF bytes after parsing.
6. Public copy is phone-first:
   - title `🧪 Контроль зон купания`;
   - `📅 Пробы:` shows actual sample dates, not the weekly report range;
   - `Лабораторный анализ воды` is the primary block;
   - `Визуальный контроль` lists only non-excellent water/sand exceptions;
   - beach names wrap at no more than two per line;
   - no resident-facing PDF URL;
   - the source line is `🏛 Данные: Servicio de Calidad de Aguas · Generalitat Valenciana`;
   - the standard forwarding-safe group footer is appended with `with_footer()`.
7. The first successfully parsed report is published immediately only when it is
   still fresh: local date no later than `report_end + 5 days`. An older first
   report becomes a silent baseline. Every later new weekly report is eligible
   for one public notice even if its qualitative ratings are unchanged because
   its new sampling cycle is itself resident-relevant.
8. A replacement URL for the same report period with identical normalized facts
   is accepted silently. If the same period is republished under a new URL with
   changed normalized facts, it is eligible for an updated notice.
9. A byte-level correction made under the same URL and same report period is an
   accepted blind spot: the bot does not redownload an unchanged identity every
   day merely to hash it.
10. Public wording translates only the source's official categories. It does
    not add medical advice, infer bathing safety from Enterococci/E. coli values,
    or collapse laboratory quality and visual inspection into one synthetic
    beach score.
11. New-message Telegram delivery follows the shared conservative ambiguity
    contract. State is pre-marked uncertain before non-idempotent send;
    explicit failures remain retryable, while ambiguous outcomes are not blindly
    resent.

## Consequences

The integration now has a bounded resident-facing purpose with minimal load:
one small HTML read each evening during the season/grace period and normally one
PDF download per newly published weekly report. A template, language, beach
topology, date or rating outside the reviewed contracts fails closed and keeps
the last accepted report intact.
