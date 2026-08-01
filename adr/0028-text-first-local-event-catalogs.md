# ADR 0028: Text-first local event catalogs

## Status

Accepted and implemented

## Context

Morning collection from multiple event sites adds latency and avoidable load.
The official Turismo Guardamar cultural-agenda page now publishes a useful
monthly program as text, while its MUPI image still contains some additional
items. Gemini Vision alone can misread stylized poster text or repeat the same
plausible error on a second pass. Agenda Guardamar also requires several
bounded detail-page reads.

## Decision

- Refresh two small normalized event catalogs before the morning run: Turismo
  Guardamar at 05:10 and Agenda Guardamar at 05:30 local time.
- The 07:30 digest reads those catalogs only; it does not contact either event
  site or run poster OCR.
- Treat the official Turismo Guardamar HTML program as the primary municipal
  event record. Call Gemini text extraction only when its bounded monthly text
  changes.
- Treat the linked MUPI image as supplementary. Download and process it only
  for a new official URL. Require two blind structured readings: the second
  call receives the image but no first-pass candidates. Keep only facts whose
  date, time, and title agree. Official text wins on a duplicate or conflict.
- Permit a narrow correction tied to one exact official poster after a human
  review proves a material OCR error. Such a correction may repair only facts
  visible in that poster and does not become a general recurring-event rule.
- Store source-language facts and provenance, never generated Russian copy or
  raw pages/images. Replace each JSON catalog atomically.
- Retain only the existing seven-day month-transition window. Do not build an
  event history, generic cache service, watcher, or resident collector.
- On a refresh failure, preserve the last valid catalog. A corrupt catalog is
  not used. Failure of optional MUPI processing may not erase or block valid
  official text events.

## Consequences

The morning run is faster and creates no event-source burst. Normal days make
one bounded page request to each event source before dawn; unchanged municipal
text consumes no Gemini quota, and an unchanged poster is not downloaded.
Event state expands to two small JSON files and two short cron invocations.

The catalogs may lag a same-morning edit made after their refresh. This is
accepted for ordinary events; urgent notices remain the responsibility of
their dedicated current sources, not the event catalog.

Independent readings can disagree and omit a real poster-only event. This is
the intended fail-closed tradeoff. Passing first-pass candidates into the
second reading is prohibited because it creates confirmation bias without
adding independent evidence.

## Alternatives rejected

- OCR as the primary source: less reliable than available official text.
- Local OCR: unnecessary CPU, storage, and maintenance on the Android device.
- Collect all event sources at 07:30: slower and concentrates network load.
- Continuous synchronization: no product value for one daily digest.
- Store raw documents or translations: increases state and staleness risk.
