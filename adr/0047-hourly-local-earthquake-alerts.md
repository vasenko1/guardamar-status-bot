# ADR 0047: Hourly local earthquake notices

## Status

Accepted

## Context

Residents may value a concise confirmation when IGN records an earthquake in
Guardamar's immediate area. This information does not fit the once-daily
Morning Digest, but a resident service, frequent polling, broad regional feed,
or generated map would conflict with the weak Android target and the project's
quiet product contract.

IGN publishes an official public GeoRSS document with event identifiers,
magnitude, UTC occurrence time, place text, and coordinates. It does not expose
a separately documented public REST API for this use. The GeoRSS is small and
can be processed with the Python standard library.

## Decision

- Run one short process at minute 55 of every hour. This avoids the 04:00
  deployment and every known morning, beach, transport, pharmacy, weekend, and
  electricity cron slot.
- Make the monitor and deployment acquire the same runtime lock. A conflict
  skips the monitor or deployment before code can change underneath a running
  process. The following scheduled invocation is the recovery path.
- Make one HTTPS request to the exact official IGN GeoRSS endpoint, with a
  ten-second timeout, 256 KiB body limit, no redirect outside the allowlist,
  and no internal retry.
- Parse at most 128 items with the standard library. Cross-check coordinates
  repeated in the description and GeoRSS fields. Fail closed on a malformed or
  wholly unrecognized non-empty feed.
- Use unrounded great-circle distance from Guardamar. An event qualifies only
  at magnitude 2.7 or greater and no farther than 10 km.
- Seed existing qualifying events silently. Keep a fresh lower-magnitude event
  observable for six hours so a later IGN revision across the threshold can
  produce the notice. Revisions of a current published series update its
  rendered parameters without another notification.
- Combine qualifying events occurring within one rolling six-hour window in
  one Telegram message. Show at most the latest five, retain a bounded count,
  and edit the stored message for later events. Recreate it only after an
  explicit `MESSAGE-NOT-FOUND` result.
- Retry a new `sendMessage` automatically only after explicit HTTP 429. An
  explicit rejection leaves the event eligible for the next hourly invocation;
  an ambiguous transport result is recorded as uncertain to avoid an automatic
  duplicate. Telegram has no idempotency key, so perfect exactly-once delivery
  is impossible after a lost success response.
- Store the latest normalized event parameters, status, and current series
  message reference atomically, with a 14-day and 256-record cap. Quarantine at
  most one corrupt state file and seed the current feed silently. Keep no raw
  XML, map image, tiles, or unbounded source history. Rotate the monitor log at
  1 MiB and retain one prior file.
- Render one Russian message headed `📈 Землетрясение рядом`, with local time,
  decimal-comma magnitude,
  rounded distance and one of eight directions. Link the epicenter label to
  exact decimal coordinates in Google Maps and leave one blank line before the
  standard footer. Do not add an IGN link, advice, or preliminary-data text.

## Consequences

The maximum ordinary source load is 24 small requests per day and no process
remains resident. A notice may arrive up to about one hour after IGN adds it,
which is appropriate for an informational group and explicitly not emergency
alerting. A source or network failure produces no message and recovers at the
next hour. A deployment can postpone a check by one hour without losing a
still-fresh qualifying event.

A group of nearby recorded events does not prove a seismological relationship,
so the message says `Несколько толчков рядом` and never infers `афтершок`.

The map link is convenient but not a factual source. Distance, direction,
magnitude, and time are derived only from the official feed. No static map is
attached because IGN does not publish a guaranteed immediate image endpoint,
and on-device map rendering would add requests, storage, and failure modes.

## Alternatives rejected

- Check every five, 30, or 45 minutes: the feature is informational, so the
  extra phone and network work does not justify the shorter delay.
- Cover 50 to 250 km with tiered magnitude thresholds: that creates regional
  noise and weakens the immediate-area value.
- Generate or screenshot a map: this needs another provider, browser or tile
  requests and cleanup while adding little beyond the exact point link.
- Poll from a resident process: unnecessary battery, memory, and recovery
  cost compared with cron.
- Publish the current feed on installation: risks flooding the group with an
  event that predates the feature.
