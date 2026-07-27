# SafeBeach morning update observation

## Question

At what time does SafeBeach first expose an active current-day flag for
`Platja Centre / Babilònia` after the lifeguard service begins?

SafeBeach publishes no guaranteed API update time. The official high-season
service begins at 10:00, but the operational record may appear later.

## Temporary measurement

For 5–7 days, run `termux/observe-flag.sh` every five minutes from 09:50
through 10:40 Europe/Madrid:

```cron
50-59/5 9 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/observe-flag.sh
0-40/5 10 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/observe-flag.sh
```

The script appends one timestamped normalized result to
`state/safebeach-observation.log`. `None` means SafeBeach has no active flag
record that the production adapter can safely use. A `BeachStatus` value marks
an active eligible record and includes its flag color.

This is a bounded source investigation, not a production collector. Remove
both cron entries after the observation period.

## Interpretation

For each day, record the first transition from `None` to `BeachStatus`. Use
multiple days before choosing a retry time because staff or platform updates
may vary. Do not infer a current flag from the prior day's last value.
