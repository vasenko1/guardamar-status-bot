# ADR 0086: Transport-owned linked guide cards

## Status

Accepted.

## Context

The linked city guide and the transport synchronizer share one
`PinnedGuideState` Telegram graph.

The 05:00 `sync-transport` job owns several dynamic transport cards whose
resident-facing content is built from accepted timetable state:

- `airport`;
- `alicante`;
- `elche`;
- `inland` (Orihuela);
- `zenia`.

The generic pinned-guide renderer also has static fallback text for these keys
so a missing card can be bootstrapped into the linked graph.

Production diagnostics on 28 September 2026 showed that the 05:00 transport
sync successfully refreshed all accepted timetable states and completed with
42 linked messages. The later 09:02 guide sync then reconciled the shared graph
without excluding transport-owned keys, replacing the live timetable cards with
their static fallback text. Orihuela was affected together with the Avanza
routes even though it uses Bus Sigüenza, which ruled out one common Avanza
rate-limit as the cause of the public symptom.

## Decision

1. Keep one shared `PinnedGuideState` graph and the existing 05:00 transport /
   09:02 guide schedules.
2. Define one `TRANSPORT_MANAGED_KEYS` tuple in `pinned.py` for
   `airport`, `alicante`, `elche`, `inland` and `zenia`.
3. Existing messages under those keys are owned by `sync-transport`. Generic
   guide reconciliation and manual `pinned-publish` pass those keys through
   `skip_keys` and must not overwrite their live content.
4. The skip contract remains bootstrap-safe: `publish_pinned_guide()` skips a
   key only when that key already exists in `PinnedGuideState`. A completely
   missing transport-managed key may therefore still be created as a static
   fallback so the linked graph stays complete.
5. `sync-transport` remains the repair path for an existing transport-managed
   message whose Telegram message was deleted. Its route-specific synchronizer
   observes `MESSAGE-NOT-FOUND`, recreates the live card under the established
   delivery rules and updates the shared message ID.
6. The `transport` navigator itself is not transport-managed by this tuple.
   Generic guide reconciliation may continue to update the navigator, root and
   all guide-owned cards.
7. Add no retry queue, delay, daemon, extra cron row, state schema or source
   request solely for this incident. Source-pressure handling should be changed
   only if future transport logs prove a real recurring source failure.

## Consequences

One Telegram card has one content owner. Guide reconciliation can no longer
erase an accepted live timetable several hours after transport sync.

The existing static fallback remains useful for first bootstrap without becoming
a second runtime owner. Recovery is explicit: use `sync-transport` to repair
transport-owned cards, and use guide/pinned reconciliation for guide-owned
cards.

The fix adds no network calls and no additional runtime work on the Termux
device.
