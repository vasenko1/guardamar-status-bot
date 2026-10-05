# ADR 0080: Next-day planning notices for events and course registration

- Status: Accepted
- Date: 2026-09-24
- Refined by: ADR 0100 for dedicated sports presentation on the shared event pipeline

## Context

The bot already knows many future city events from the same local catalogs used
by the Morning Digest and Friday weekend digest. Course adapters also know
explicit registration windows before their opening and closing dates.

Residents benefit from learning actionable plans before the day starts, but a
naive "one notification per row" implementation would create alert fatigue and
would duplicate festivals, multi-day exhibitions, recurring markets and groups
that share one registration deadline. Re-fetching all event sources in the
evening would also add unnecessary network, Gemini and image-processing work on
the Android Termux device.

The existing event contract already carries source-backed details such as
teasers, duration, audience, admission, registration contacts and programme
identity. Some official sources also expose an event-specific image. The
feature should reuse those facts rather than introduce a new content or
notification framework.

## Decision

### Next-day events

- Add one primary tomorrow-events one-shot at 19:25 Europe/Madrid and one
  recovery invocation at 20:25 on Sunday through Thursday. Both run the same
  command and share the same delivery state.
- Friday and Saturday are excluded because Friday's "Афиша выходных" already
  covers Saturday and Sunday.
- The one-shot performs no source-network requests and no AI calls. It reads
  only the existing local event snapshots plus the prepared translation cache.
- A source contributes to the proactive notice only when its snapshot
  fetched_at/observed_at is on the current local date. Last-good data may
  remain useful elsewhere, but stale state never supports a new claim that an
  event happens tomorrow.
- Existing source readers, venue repair and cross-source merge remain the
  normalization path. The next-day feature does not introduce a second event
  model.
- Routine recurring calendar events are not added to this proactive flow.
  Existing source-level exclusions such as the routine youth-centre opening
  also remain in force.
- A one-day event is eligible. A dated range is eligible only on its first day
  or final day; middle days are silent. An explicit exhibition opening remains
  preferable to the generic exhibition row under the existing municipal rule.
- Rows sharing one non-empty programme_title form one editorial unit.
  Fiestas del Campo is therefore one resident-facing programme regardless of
  the number of programme rows.
- If there are no eligible units, send nothing.
- If there is one editorial unit, render the full existing event detail
  contract and allow one official event-specific image.
- If there are two or more units, send one "Завтра в Гуардамаре" text message.
  Keep factual event details but omit long teaser prose for scanability. Never
  send one message per event.

### Media

- Event and source records may carry one optional image_url.
- Persist only the validated HTTPS URL; never persist or archive image bytes.
- The first accepted media sources are deliberately narrow:
  - the already-discovered official Turismo poster for the Fiestas del Campo
    programme;
  - AM Guardamar's WordPress wp:featuredmedia response from the same bounded
    12-post REST read.
- AM Guardamar may use _embed=wp:featuredmedia, but this does not increase the
  number of source requests. Only amguardamar.es upload URLs with an accepted
  image MIME type are retained.
- Biblioteca, Agenda Guardamar and Facebook images remain disabled until their
  event-to-image identity and URL stability are separately proven.
- Telegram receives the validated public HTTPS URL in sendPhoto; Android does
  not download, transform or re-upload the image.
- Media is never required. If Telegram deterministically rejects an image, the
  same notice falls back to text. Ambiguous photo delivery never falls back to
  text automatically because that could create a duplicate.
- Telegram photo captions are used only when the complete rendered message fits
  the Bot API caption limit; otherwise the notice is sent as text.

### Translation preparation

- Extend the existing pre-morning translation preparation for municipal,
  Agenda Guardamar, Biblioteca and AM Guardamar from today to today plus
  tomorrow.
- Continue using the same bounded cache and translate only misses.
- Do not call Gemini from the 19:25 publication path.

### Course registration

This ADR amends ADR 0072's exact-day-only registration policy.

- Keep the current same-day opening and closing messages.
- Additionally create fresh-source date events for:
  - registration opening tomorrow;
  - registration closing tomorrow;
  - a one-day registration window tomorrow.
- All courses/groups with the same semantic event stay in one existing
  notification bucket. Do not stagger one alert per section.
- A one-day registration window produces one "open only tomorrow" advance
  event, not separate opening and closing alerts.
- registration_until_full still never becomes an absolute last-chance claim:
  the advance copy says only that the main registration period ends tomorrow.
- Chess, the literary group, football, Aqualider and any other source without a
  verified registration interval remain ineligible.
- Municipal cultural workshops/events also remain ineligible for deadline
  alerts until their source adapter exposes an event-specific registration
  start/end interval. A registration contact or nearby prose alone is not
  enough evidence to create a date-sensitive notification.

### Delivery and state

- Reuse the existing event-planning cron installer rather than add another
  scheduler or daemon.
- Keep one small state/tomorrow_events.json with only the target date,
  delivery state and confirmed Telegram message ID.
- Before the non-idempotent send, persist uncertain. Confirmed success becomes
  sent. An ambiguous failure remains uncertain and blocks automatic resend.
  A deterministic rejection clears the marker before a safe alternative send.
- The 20:25 recovery is delivery-safe: `sent` and `uncertain` both stop before
  another Telegram send. A 19:25 run that had no eligible publication writes no
  delivery marker, so the same local snapshots can be re-evaluated once after a
  transient local snapshot/read problem is repaired.
- No generic notification bus, database, queue, resident worker or internal
  scheduler is introduced.

## Consequences

The phone's normal next-day event lifecycle is at most two short local-only
invocations, each doing JSON reads and a deterministic merge. Across both
invocations there is still at most one Telegram publication because the same
crash-safe state gates delivery. It adds no evening source traffic, no browser,
no PDF work, no image decoding and no AI workload.

A single high-value event or festival can receive richer presentation while a
busy day still costs one group message. Course deadline spikes remain one
semantic notification instead of a stream of nearly identical alerts.

Very late source publications may miss the evening notice. That is an accepted
tradeoff: the next morning's normal source refresh and Morning Digest remain
the recovery path, which is cheaper and safer than a second daily full event
sync.


## Refinement: sports planning

ADR 0100 keeps this ADR's scheduling and one-message planning model but changes
how sporting events are presented once that implementation is deployed:

- sport remains part of the same normalized Event pipeline;
- Tomorrow and Friday Weekend render sport in a clearly separated subsection;
- no additional evening `sport tomorrow` message or scheduler is added;
- a separate current-day sports publication handles the same-day resident
  reminder/correction;
- Morning stops repeating sport only when that current-day path is operational;
- the planning delivery path must fail closed rather than silently truncate
  eligible sport events.


## Implementation refinement: shared dated planning delivery

On 2026-10-05 the crash-safe date-target state used by Tomorrow was extracted
into one small internal primitive without changing
`state/tomorrow_events.json` or its schema.

Friday Weekend now uses the same reservation semantics in a separate
`state/weekend_delivery.json`:

- reserve `uncertain` before a new Telegram send;
- retry automatically only explicit rate-limit rejection;
- keep timeout/network/5xx ambiguity uncertain so the 20:15 recovery cannot
  duplicate;
- clear deterministic unsent failure for a safe later recovery;
- on confirmed send, preserve the existing `state/weekend.json` target
  marker for rollback to the previous runtime and then confirm the new message
  ID.

Weekend acquires both the legacy and new delivery locks during publication so
old/new runtime overlap at a deployment boundary cannot create concurrent sends.

This hardening adds no source request, scheduler, dependency or resident
process.
