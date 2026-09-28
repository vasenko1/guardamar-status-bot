# TomTom incident ID churn in Guardamar — 28 September 2026

## Scope

This note records the production investigation behind the continuity rule in
ADR 0079. It is source-behaviour research, not a new runtime dependency.

The affected public restriction was the continuing full road closure on
Avenida del Mediterráneo between Calle Miguel Hernández and Avenida del País
Valenciano, first observed by the bot with a source start around
23 September 2026 16:45 Europe/Madrid.

## Resident-visible symptom

On 28 September the group received repeated contradictory transitions for the
same physical segment: a new closure alert, then a reopening reply, then
another new closure alert and another reopening reply.

The traffic cron itself remained hourly at minute `:37`. Production log
entries around the failure were:

- 14:37 — delivered 1;
- 15:37 — delivered 1;
- 16:37 — delivered 0;
- 17:37 — delivered 1;
- 18:37 — delivered 1;
- 19:37 — delivered 0.

The existing state machine required two successful absences before an end
notification, so a one-hour close/open transition for one stable provider ID
could not explain this sequence.

## Deployment hypothesis checked and rejected

The production Git reflog showed the first deployment on 28 September only at
19:31 local time and another at 19:52. Both were after the 14:37–18:37 false
transitions. The 19:31 fast-forward changed only the Product Awards feature and
its tests; the traffic module was unchanged.

`state/traffic.json` also retained all traffic lifecycle records across the
deployment. The monitor updated the same state again at 19:37.

The incident churn therefore was not caused by a deploy resetting traffic
state or by an extra traffic cron invocation.

## Three provider IDs for one physical restriction

Production state retained these three TomTom provider IDs:

1. `TTI-fd0cb5e0-307c-46df-9596-df50e5122d3e-TTR45347245744012000`
2. `TTI-51570b45-edd7-4046-b144-f8c5ead2cf16-TTR45347245744012000`
3. `TTI-b9e0c634-6369-4098-a899-0b703580a06a-TTR45347245744012000`

All three normalized records had:

- category `roadClosed`;
- `from = Calle Miguel Hernández`;
- `to = Avenida del País Valenciano`;
- street resolved as `Avenida del Mediterráneo`;
- ten LineString points;
- exactly the same ordered geometry at six decimal places;
- the same observed `TTR45347245744012000` suffix;
- source start times differing by only 0–30 seconds.

The first and second IDs had already been marked ended by the local state
machine. The third remained active.

## Direct TomTom lookup result

A bounded diagnostic lookup queried the three saved IDs directly.

- the current third ID returned an active `present` `roadClosed` incident;
- the first ID returned `null`;
- the second ID returned `null`.

The current bbox snapshot also contained only the third ID, with the same
boundaries and geometry and start time `2026-09-23T14:45:30Z`.

This confirms provider-ID replacement rather than a physical close/open/close
cycle.

The common `TTR...` suffix is useful diagnostic evidence, but no reviewed
public TomTom contract establishes it as a durable physical-event identifier.
Runtime therefore must not depend on parsing or persisting that suffix.

## Root cause in the bot

The original lifecycle used the complete TomTom provider ID as the state key.

For a provider replacement A -> B:

1. B was treated as a brand-new closure and published immediately.
2. A accumulated missing snapshots independently.
3. after two successful snapshots without A, the bot published a reopening,
   even though B in the same source still described the same physical closure.

The source and the two-confirmation debounce were individually behaving as
designed; the missing layer was physical-closure continuity before absence
counting.

## Accepted continuity constraints

The production fix keeps one provider ID as the current state key but permits a
strict in-memory handoff before missing counters advance.

A disappeared active ID and a newly observed ID are considered one continuing
physical restriction only when:

- the mapping is one-to-one;
- both records are road/lane closures;
- both source boundaries exist and match, or reverse together with the
  geometry;
- source start times differ by no more than two minutes;
- corresponding LineString endpoints differ by no more than five metres.

A clean handoff rekeys the existing lifecycle and preserves Telegram delivery
markers. Equivalent IDs that overlap in one snapshot are suppressed until a
clean handoff. Ambiguous candidate groups are not guessed: only the affected
missing lifecycle is frozen for that invocation and candidate replacement IDs
are suppressed.

The matching uses only the already fetched hourly bbox snapshot and existing
normalized state. It adds no TomTom request, database, alias history, resident
worker, dependency or state-schema field.

## Deliberately unchanged

The investigation did not justify changing:

- hourly polling at `:37`;
- `MISSING_CONFIRMATIONS = 2`;
- the 14-day bounded state retention;
- reverse-geocoding policy;
- future/present and lane/full-road transitions;
- Telegram delivery uncertainty handling;
- current reopening copy.

The technical fix changes what counts as a genuine absence; it does not add a
larger debounce or attempt to infer road status from API failures.
