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
once for tomorrow's Madrid date. Every invocation makes one bounded request;
the same external schedule retries empty, incomplete and unavailable results.

Require all 24 hourly values, convert €/MWh to €/kWh, and keep no cache. Render
the two-column table inside Telegram HTML `<pre>` so its columns use a
monospace font. The heading explicitly says `завтра` and includes the date.
Send a small explanation as a reply to the price table. ESIOS thresholds keep
their official three colors; values at or above 90% of the daily maximum are
additionally red as a documented presentation rule.

The recommendation uses the continuous six-hour window with the lowest total
price, with the earlier window winning an exact tie.

The main message names `ESIOS / Red Eléctrica` and distinguishes exact PVPC
use from indicative use for other indexed contracts. The recommendation is
one logical line; Telegram may wrap it naturally for the device width.

Store only the last published target date. If the explanation fails after the
main table succeeds, keep the success marker so the main table is not sent
again.

## Consequences

- One API key, one source module, one script, and one tiny state file are added.
- No resident process, database, AI, scraper, or dependency is added.
- A DST transition day without exactly 24 local hours is omitted rather than
  forced into a misleading 24-row layout.
- The feature is relevant only to PVPC and indexed tariffs, which the message
  states explicitly.
