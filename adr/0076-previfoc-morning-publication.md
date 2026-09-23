# ADR 0076: Previfoc morning publication

## Status

Accepted.

## Context

The unified CCE/Previfoc watcher runs once per hour at minute `:19` and reads
Previfoc layer 0, `Dia=1`, for Guardamar zone 6.

Previfoc is a daily prevention product. The official source also exposes a
next-day value, so the value that becomes `Dia=1` at midnight may already have
been known before the calendar day changed. Treating the first post-midnight
poll as a breaking event produced messages such as a dry-thunderstorm
possibility at 00:19, even though the source did not say that the hazard began
at that minute or provide an hourly validity interval.

The same one-shot process also reads CCE emergency and hydrological authority
state. Those transitions can be operationally urgent and must not inherit a
Previfoc-specific quiet period.

## Decision

1. Keep the existing hourly `:19` `check-112` schedule and the same three
   bounded source reads. Do not add a second cron, resident worker or queue.
2. Continue storing every valid Previfoc observation before 07:00
   Europe/Madrid, but do not render it into a public transition and do not
   acknowledge it as published.
3. On the first run at or after 07:00, compare the current Previfoc observation
   with the last published Previfoc state. Publish only a delta that is still
   current.
4. If a Previfoc value changes after midnight and returns to the last published
   value before morning, publish nothing about that intermediate state.
5. After 07:00, later same-day Previfoc readjustments remain eligible on the
   next hourly run.
6. CCE and hydrological transitions remain eligible immediately at every
   hourly run. If such a transition is published during Previfoc quiet hours,
   acknowledge only the CCE/hydrological state; do not accidentally consume the
   pending Previfoc delta.
7. Previfoc copy must make its daily scope explicit with `сегодня` or
   `на сегодня`. For `TormentaID=2`, use:
   - `⚡ Сухие грозы возможны сегодня`;
   - `Для зоны Гуардамара повышен риск возникновения сухих гроз.`;
   - `Это профилактическая информация о погодном риске.`
8. Do not infer an hourly interval from AEMET or another source merely to make
   Previfoc look more precise than the official data.

## Consequences

The state model stays unchanged: the current observed Previfoc record is the
only pending candidate, while the existing published fields remain the
resident-facing baseline. This naturally discards overnight intermediate
values that no longer apply by morning.

The phone keeps the same network and scheduling cost. CCE emergency behavior is
unchanged, while routine Previfoc day-boundary transitions no longer wake the
group at midnight or imply an unsupported start time.
