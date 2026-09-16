# ADR 0069: Automated municipal Sporttia activity cards

## Status

Accepted — 2026-09-16

## Context

The linked guide already models swimming as an activity rather than a
place. The next recurring municipal activities are rhythmic gymnastics,
judo, multisport, inclusive multisport, senior gymnastics and the
Asociación Mujeres gymnastics group. Their current 2026/2027 rows are
published by the Guardamar municipal Sporttia centre page.

A production Termux probe on 2026-09-16 made exactly one non-redirecting
GET to the public centre page. It returned `200 text/html` in 0.386 s,
17,448 compressed bytes / 93,536 decoded bytes, with all 15 published
activity rows already present in server-rendered HTML. No browser,
session, cookie bootstrap, activity-page request or API reverse
engineering is required.

The page describes itself as a surface of activities with open
registration. Therefore disappearance from the page does not prove that
an already-started course has been cancelled; registration can simply
have closed.

## Decision

Reuse the existing 16:30 `sync-guide` one-shot. Attempt at most one bounded
Sporttia GET per Europe/Madrid calendar day, even if `sync-guide` is rerun
manually; mark the attempt before network I/O so failures are not retried the
same day. Redirects and retries remain disabled. Parse the
server-rendered offer rows with the Python standard-library HTML parser.
Do not fetch `play.sporttia.com` activity pages, JavaScript assets,
`api.sporttia.com`, or the alternate Markdown representation.

Normalize only resident-facing facts needed by the six explicit cards:
activity key, source ID and action URL, season dates, group order,
audience, schedule, venue, explicit `NUEVAS INSCRIPCIONES` windows and
a few directly stated requirements. Ignore the generic `Abierta` label,
prices and any inferred availability.

Store the normalized catalogue inside the existing `state/guide.json`.
A valid new observation replaces rows it still exposes, while an
unexpired last-good row remains until its explicit `season_end` if it
temporarily disappears from the open-registration surface. Expired rows
are not rendered. Malformed HTML, unexpected MIME, redirects, timeouts
or schema drift preserve the last-good snapshot.

Add six stable source-managed Telegram cards under `Занятия и секции`.
A card represents an activity, not a facility; venue is a fact of each
group, so the same card can later contain groups at more than one place.
Keep the implementation explicit: six keys and one compact shared
formatter, not a generic activity CMS, relation model or scheduler.

## Runtime shape

- no new cron;
- no daemon or polling loop;
- no dependency;
- no database or new state file;
- no operator confirmation or private alert;
- no browser automation;
- at most one Sporttia request per local calendar day.

Existing pinned-message state keeps the six Telegram message IDs. Other
guide reconciliations can preserve links without performing Sporttia
network work; the 16:30 guide sync remains the sole owner of their
source-backed content.

## Consequences

- Closing registration cannot erase an ongoing course from the guide.
- A source-layout failure cannot replace good cards with empty data.
- Group schedule or venue changes are applied automatically when the same
  activity row is observed again.
- The guide can later show one sport at multiple venues without changing
  the root information architecture.
- Registration status is derived only from explicit source date windows,
  never from Sporttia's contradictory generic `Abierta` label.
