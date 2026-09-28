# 2026-09-29 — Guide sync overwrote live transport cards

## Question

Why did the public Alicante, Elche, Orihuela and Zenia Boulevard cards all show
static fallback text instead of their accepted exact-date timetables?

## Production evidence

The production diagnostic captured shortly after midnight on 29 September
showed:

- transport cron at 05:00 Europe/Madrid;
- guide cron at 09:02 Europe/Madrid;
- `state/transport.log` last modified at 05:02:25 on 28 September;
- `state/guide.log` last modified at 09:07:40 on 28 September;
- the 05:00 transport run completed successfully with 42 linked messages;
- Alicante, Elche, Orihuela and Zenia schedule state files were all refreshed
  between 05:01 and 05:02;
- Elche, Orihuela and Zenia contained complete current/next departure arrays;
- the 09:02 guide run completed successfully later that morning.

Orihuela uses Bus Sigüenza while Alicante/Elche/Zenia use Avanza/Costa Azul.
The simultaneous public fallback therefore cannot be explained by one Avanza
rate-limit.

## Code path

`sync-transport` already protects existing live timetable cards when it first
reconciles the shared pinned graph.

`sync_guide()` called the same generic `publish_pinned_guide()` without
`skip_keys`. Generic rendering therefore edited those same message IDs back to
their static `LEAF_MESSAGES` fallback text.

Manual `pinned-publish` had the same overwrite capability.

## Conclusion

The incident is an ownership conflict, not a demonstrated source-pressure
failure.

The minimal correction is to define the five transport-managed route keys once
and make generic guide publishers preserve an existing card under those keys.
A missing key may still bootstrap as fallback because the pinned reconciliation
layer ignores skip entries that are not yet in state.

Do not add retries, sleeps, extra cron jobs or a queue unless future transport
logs show a separate recurring source failure.
