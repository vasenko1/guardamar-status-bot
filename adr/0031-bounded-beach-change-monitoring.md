# ADR 0031: Bounded operational change monitoring

- Status: Accepted; initial-publication rules superseded by ADR 0064
- Date: 2026-08-07

## Context

The immutable 07:30 Morning Digest, the separate daily beach root, and
official AEMET warnings can all receive later material source changes.
Continuous polling would be noisy and too expensive for the Termux device.

## Decision

Add one small one-shot operational monitor. It never remains resident and
uses a separate atomically replaced daily JSON state.

### Beach checks

- Run SafeBeach checks only from 1 June through 30 September and only inside
  the scheduled daytime windows.
- In July and August, primary checks run at 11:00, 13:00, 15:00, 17:00 and
  19:00. In June and September they run at 12:00, 14:00, 16:00 and 18:00.
- Monitor all six known Guardamar zones.
- Every explicit flag transition qualifies, including green to yellow and
  yellow to green. Explicit jellyfish appearance and disappearance also
  qualify.
- A missing beach, field, stale page, invalid response or transport failure is
  unknown and never becomes a transition.
- A newly available flag outside the initial 10:10–10:40 cycle enters the
  normal confirmation flow. If no daily beach root exists, the first confirmed
  status may create it as a recovery path. A first explicit positive jellyfish
  report remains a safety candidate.

Each possible change is checked again after five minutes. If the second sample
contains another new explicit state, that state receives one final check after
another five minutes. A third disagreement is treated as unstable source data
and is not published. Therefore one window makes at most three SafeBeach
requests and never starts an unbounded retry chain. Changes are confirmed per
beach and field, held briefly when necessary, and combined into one message.

### AEMET warning checks

- Fetch only the official CAP warning product, not the full weather bundle.
- Check every four hours after the later digest phase: 11:00, 15:00 and 19:00,
  shifted to 12:00, 16:00 and 20:00 during the June/September beach schedule.
- Compare a canonical set of event, level, start, end, probability and
  normalized description. XML order and whitespace do not create changes.
- Publish new warnings, level/time/content changes, and verified early
  cancellations. Natural expiry at the published end time advances state
  silently.
- A source failure, malformed response or unavailable warning product never
  means cancellation.
- Make each update self-contained as specified by ADR 0054: cancellations
  appear first, followed by the complete currently active warning set. When a
  beach confirmation is pending in the same window, hold the AEMET change and
  send both sections in one notification.

Air-quality monitoring is not part of this decision. The official open source
available for the area is station-based and does not provide a trustworthy
Guardamar measurement.

### Telegram delivery and history

Confirmed beach changes are replies to the daily beach root. Once that root
exists, the operational monitor does not silently rewrite its SafeBeach
snapshot; the change message is the audit trail. If no root existed by 10:40,
a first later confirmed status may create it. If Telegram reports the root
missing immediately before a reply, recreate it from confirmed state and retry
the reply.

AEMET operational messages continue to reply to the immutable Morning Digest.
Older update messages are never deleted or edited.

Advance confirmed source state only after Telegram confirms delivery. The Bot
API has no idempotency key, so a lost success response retains the existing
small duplicate edge.

## State

Store only the current local date, last confirmed explicit beach values,
latest usable beach context, bounded pending/ready changes, and the canonical
active AEMET set. Raw HTML, CAP documents and histories are not stored. Reset
the state when the Madrid local date changes and protect each run with one
non-blocking file lock.

Seed the AEMET baseline from the same-day prepared morning snapshot only when
a daily digest record exists. Otherwise a valid active warning found later is
eligible for notification. Seed beach state from the latest published beach
root when one exists; otherwise the first later confirmed beach status can
create that root.

## Consequences

- Subscribers see every verified beach status transition without hidden
  green/yellow changes and receive changed official warnings.
- One monitor window produces at most one beach-change reply and one AEMET
  warning reply; the two products keep their own anchors.
- The device uses bounded short processes, small state and no new dependency.
- A beach change may be reported after the next two-hour window plus five or
  ten minutes. This is the accepted tradeoff for source stability and low
  load.

## Acceptance criteria

- No SafeBeach request outside 1 June through 30 September or outside the
  scheduled daytime windows.
- No phase-two or phase-three confirmation request when there is no pending
  operational beach transition.
- At most three SafeBeach requests per primary window.
- Missing data never clears a known flag or jellyfish value.
- All explicit confirmed flag colors can generate an update.
- AEMET failures never manufacture a warning cancellation.
- Natural warning expiry is silent; early cancellation is visible.
- Confirmed beach changes reply to the daily beach root; AEMET changes reply
  to the immutable Morning Digest.
- A deleted beach root is recreated from confirmed state before its reply;
  the existing AEMET reply fallback remains unchanged.
- No database, daemon, new dependency or raw-source archive is introduced.
