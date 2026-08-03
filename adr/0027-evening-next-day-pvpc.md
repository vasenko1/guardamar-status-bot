# ADR 0027: Evening next-day PVPC table

## Status

Accepted — 2026-07-31

## Context

Users with PVPC or indexed electricity tariffs can move energy-intensive work
to cheaper hours, but a wholesale-market chart is not the household PVPC
energy term. The target phone is narrow and the runtime is a weak Termux
device.

## Decision

Add one isolated evening feature using official ESIOS indicator `1001` for
`Península`. Run short external invocations at 20:30, 20:35, 20:45, 21:00 and
21:20, after the official 20:15–20:20 publication target, and publish at most
once for tomorrow's Madrid date. An invocation makes at most one bounded
request and makes none after confirmed publication or when a complete snapshot
already exists. The same external schedule retries empty, incomplete and
unavailable results until a complete snapshot is stored.

Require all 24 hourly values and convert €/MWh to €/kWh. After the first
complete response, atomically store one normalized target-day snapshot with
the source, indicator, geographic scope, date, and 24 hourly values. Render
and publish only from that verified local snapshot. The snapshot contains no
token or raw API response and is replaced when the target date changes. Render
the two-column table inside Telegram HTML `<pre>` so its columns use a
monospace font. The heading explicitly says `завтра` and includes the date.
On the first successful publication, send a small explanation, persist its
message ID, and send the price table as its reply. On later days, send only the
new table as a reply to the same explanation. Colors compare hours
within the published local day: the cheapest third is green, the middle third
yellow, and the most expensive third red. Equal prices are not split across a
boundary; when both boundaries are the same, that shared level is yellow.
These colors are presentation metadata and are not attributed to ESIOS.

The recommendation uses the longest continuous run of green hours, so its
wording cannot contradict the table colors. Equal-length runs are ordered by
their total price and then by the earlier start. When tie-heavy prices produce
no green hours, omit the recommendation.

The persistent explanation defines PVPC, tells readers how to identify it on
their bill, states that the table is not the whole bill, excludes fixed
tariffs, and names `ESIOS / Red Eléctrica`. The recommendation is one logical
line; Telegram may wrap it naturally for the device width.

Store the last published target date and the persistent explanation message ID
separately from the one-day normalized price snapshot. Check the success marker before reading the snapshot or
contacting ESIOS. A missing, wrong-date, or corrupt snapshot may be replaced
only after one new complete API response; a write failure prevents public
delivery. Publication and authorized preview share the same non-blocking local
lock so they cannot make concurrent duplicate requests. The explanation must
succeed and be persisted before the first table is sent; if the table then
fails, the next invocation reuses the same explanation rather than duplicating
it. Refuse configuration that points the snapshot and publication marker to
the same file.

## Consequences

- One API key, one source module, one script, one tiny publication-state file,
  and one bounded normalized price snapshot are used.
- After the first complete response is successfully stored for a target day,
  later cron invocations and authorized previews reuse the snapshot; after
  confirmed publication, invocations exit before any ESIOS access.
- No resident process, database, AI, scraper, or dependency is added.
- A DST transition day without exactly 24 local hours is omitted rather than
  forced into a misleading 24-row layout.
- The feature is exact only for PVPC; the persistent explanation states this
  explicitly and avoids repeating the same education every day.
