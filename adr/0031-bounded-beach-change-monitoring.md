# ADR 0031: Bounded operational change monitoring

- Status: Accepted
- Date: 2026-08-07

## Context

The 07:30 digest and its later full replacement are snapshots. Verified beach
flags and official AEMET warnings can change materially afterwards. Silently
editing the full digest hides the change, while continuous polling would be
noisy and too expensive for the Termux device.

## Decision

Add one small one-shot operational monitor. It never remains resident and
uses a separate atomically replaced daily JSON state.

### Beach checks

- Run only from 20 June through 14 September and only inside normal lifeguard
  hours.
- In July and August, primary checks run at 11:00, 13:00, 15:00, 17:00 and
  19:00. In June and September they run at 12:00, 14:00, 16:00 and 18:00.
- Monitor all six known Guardamar zones.
- Every explicit flag transition qualifies, including green to yellow and
  yellow to green. Explicit jellyfish appearance and disappearance also
  qualify.
- A missing beach, field, stale page, invalid response or transport failure is
  unknown and never becomes a transition.
- A newly available flag creates a silent baseline. A first explicit positive
  jellyfish report remains a safety candidate.

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
- Reuse the approved full AEMET warning layout. When a beach confirmation is
  pending in the same window, hold the AEMET change and send both sections in
  one notification.

Air-quality monitoring is not part of this decision. The official open source
available for the area is station-based and does not provide a trustworthy
Guardamar measurement.

### Telegram delivery and history

Every operational message is a reply to the current full daily digest. The
stable anchor is resolved from `delivery.json` at send time: before replacement
it is the live 07:30 message; afterwards it is the later complete digest. It is
never the previous operational update, so updates do not form a fragile chain.

If the full digest identifier is absent or Telegram reports that the reply
anchor no longer exists, send the update as a standalone message. Keep older
updates unchanged as an audit trail; do not delete or silently edit them.

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
eligible for notification. The first valid beach response establishes the
flag baseline silently.

## Consequences

- Subscribers see every verified beach status transition without hidden
  green/yellow changes and receive changed official warnings.
- Multiple source changes in one window produce at most one notification.
- The device uses bounded short processes, small state and no new dependency.
- A beach change may be reported after the next two-hour window plus five or
  ten minutes. This is the accepted tradeoff for source stability and low
  load.

## Acceptance criteria

- No beach request outside the accepted season or scheduled service window.
- No confirmation request when there is no pending beach candidate.
- At most three SafeBeach requests per primary window.
- Missing data never clears a known flag or jellyfish value.
- All explicit confirmed flag colors can generate an update.
- AEMET failures never manufacture a warning cancellation.
- Natural warning expiry is silent; early cancellation is visible.
- Combined changes create one message replying to the full daily digest.
- A deleted reply anchor falls back to a standalone message.
- No database, daemon, new dependency or raw-source archive is introduced.
