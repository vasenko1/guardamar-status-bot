# ADR 0046: Preserve text events and fail closed on vague dates and venues

## Status

Accepted

## Context

The 16 August digest exposed three related weaknesses in the municipal event
pipeline. A poster-specific reviewed drop list removed richer Todo Cultura text
rows even though it exists only to suppress known-bad image OCR. One old
reviewed summary then combined an 18:30 charity bingo with a separate 22:00
concert and hid another workshop. A model-supported place copied the event
context, `Feria de comercio Guardamar 2026 de la avenida de los Pinos`, and the
renderer turned the whole phrase into a Google Maps search. Finally, an
environmental-volunteer date range appeared as a Sunday event even though its
official schedule was Monday through Saturday.

These are general precedence and eligibility defects, not missing-source
facts. A one-date correction would leave later posters and programmes exposed
to the same failures.

## Decision

- A reviewed poster `drop_titles` clause may remove only a poster-only event.
  Any event with official HTML or Todo Cultura text provenance survives even
  when its title resembles a known OCR error.
- A reviewed occurrence is a recovery fact. When a same dated text occurrence
  exists, retain the text identity and verified structure, and use the reviewed
  occurrence only to fill missing bounded fields such as time, place,
  admission or participation. Never replace several text acts with one older
  reviewed summary.
- A non-exhibition date range is not evidence that an activity occurs every
  day. Publish only separately dated occurrences. Multi-day exhibitions keep
  their existing range and reviewed visiting-hours policy.
- Canonicalize a contextual venue that contains an explicit street, square,
  park or promenade before persistence and again before rendering. The source
  phrase remains evidence for validation, but the normalized event keeps only
  the compact geographic place.
- Create a Google Maps link only for a compact location. An instruction,
  event description, unconfirmed place or otherwise unsafe phrase remains
  visible plain text and never becomes a misleading search link.
- Keep the correction deterministic and lightweight: no new request, model
  call, dependency, schedule, background process or raw-source state.
- Pin the independently verified four 16 August Feria de Comercio occurrences
  as exact recovery facts so an in-place refresh repairs the live message even
  if the supplemental source is temporarily unavailable.

## Consequences

Fresh text can no longer disappear behind a monthly image correction. Broad
campaign and festival ranges may be omitted when the source does not provide
individual dated occurrences; this is the intentional fail-closed tradeoff and
is preferable to claiming activity on the wrong day. Unknown venues may lose a
map link while retaining their verified text. Existing compact venue links and
multi-day exhibitions remain unchanged.

The event catalog schema and Termux workload do not grow. Older snapshots are
revalidated through the same normalization path, so verbose places and vague
ranges are repaired or discarded without a one-off state migration.

## Alternatives rejected

- Correct only the 16 August output: fixes one message but preserves the source
  precedence defect.
- Let reviewed data always win: manual poster facts can become stale when a
  later text programme publishes separate acts.
- Link every non-empty place string: creates plausible but wrong maps from
  prose.
- Add weekday recurrence to generated event facts: expands the schema and AI
  contract when the safer product rule is to require separately dated acts.
