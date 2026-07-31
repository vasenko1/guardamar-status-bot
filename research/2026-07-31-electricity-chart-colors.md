# Electricity chart color comparison — 2026-07-31

## Scope

Five supplied daily bar charts for 27–31 July 2026 were compared only to
identify their presentation rule. They are not accepted as a price source;
the product continues to use official ESIOS indicator `1001`.

## Finding

The primary chart for every supplied date assigns exactly eight hourly prices
to each of three groups:

- green: the eight lowest prices of that day;
- orange: the middle eight prices;
- red: the eight highest prices.

The boundaries move with the day's distribution and therefore are not fixed
€/MWh or €/kWh thresholds.

One additional table image for 28 July colors the same values differently and
appears to use fixed ranges. It conflicts with the primary 28 July bar chart
and with the repeated five-day bar-chart pattern, so it is not used to infer
the product rule.

## Product interpretation

Use relative daily thirds as compact planning hints. The colors are local
presentation metadata, not categories returned or endorsed by ESIOS. The bot
uses green, yellow, and red for those thirds even though the reference charts
use orange for the middle third. Preserve equal price levels as one color even
when this makes group sizes unequal.
