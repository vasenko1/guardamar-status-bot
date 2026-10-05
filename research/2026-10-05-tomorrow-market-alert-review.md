# Tomorrow municipal-market alert review — 2026-10-05

## Scope

Review the safest minimal way to include Guardamar's municipal La Redonda
market in the existing `Завтра в Гуардамаре` planning message, including the
holiday-driven move from Wednesday 7 October 2026 to Tuesday 6 October 2026.

## Current official evidence

- Guardamar's 2023 non-sedentary-sales ordinance, BOP Alicante no. 159,
  article 8, defines the weekly Wednesday municipal market at parking La
  Redonda and adjacent streets. If Wednesday is a holiday, the market is held
  on the preceding Tuesday.
- The same article defines customer hours as `07:00–13:30` from 1 June
  through 30 September and `08:00–13:30` for the rest of the year.
- Diputación de Alicante's official 2026 local-holiday list records Guardamar
  del Segura's local holiday on 7 October 2026 (Virgen del Rosario).
- A November 2025 Guardamar municipal decree for vacant weekly-market licences
  still cites the 2023 ordinance as its governing ordinance. No newer
  municipal market ordinance surfaced in the 2026-10-05 source check.

Official references:

- https://www.guardamardelsegura.es/wp-content/uploads/2023/09/BOP-NUEVA-ORDENANZA.pdf
- https://documentacion.diputacionalicante.es/fiestas.asp
- https://www.guardamardelsegura.es/wp-content/uploads/2025/11/2025111.pdf

## Existing code already correct

`holidays.is_market_day()` already returns true for 2026-10-06 and false for
2026-10-07. `agenda.recurring_events()` already renders the La Redonda market
with the reviewed seasonal hours. The Morning Digest already checks
`@AlcaldeGuardamar` for exact-date market exceptions.

The gap is presentation timing: `tomorrow_events.py` previously read only
event catalogs, so the deterministic recurring market never reached the
previous evening's planning message.

## Red-team cycles

### 1. Avoid scope expansion

Calling `recurring_events(target)` directly would also couple Tomorrow Events
to the separate Sunday Campo de Guardamar market. That is outside this change
and interacts with the deliberate Friday/Saturday planning split.

Decision: extract one pure `municipal_market_event(local_day)` helper and reuse
it from both Morning recurring events and Tomorrow Events.

### 2. Avoid a knowingly stale positive claim

A calendar-only previous-evening alert could claim "tomorrow market" after the
Mayor channel had already announced a cancellation or ad-hoc move. ADR 0013
exists precisely because the deterministic calendar alone is insufficient for
exceptions.

Decision: only when tomorrow is a scheduled La Redonda market, reuse the
existing bounded Mayor exception check. Failure omits the market but does not
remove unrelated tomorrow events. No new scheduler, state or source is added.

### 3. Keep observation time separate from event date

The old `market_is_cancelled(now)` used one datetime for both source freshness
and the market date. Passing a future datetime to check tomorrow would shift
the source-freshness reference.

Decision: retain real observation `now` for post freshness and pass an
optional explicit `market_day` to the classifier.

### 4. Make model validation truly fail closed

Previously a relevant market post plus an invalid positive classification could
fall through as `False` ("not cancelled"), allowing the market to be shown.

Decision: a clean negative requires exactly `cancelled=false`, empty evidence
and null event date. A positive must pass the existing exact-quotation/date
validator. Anything else raises a source error and the caller omits the market.

### 5. Disambiguate move direction

"Market moved to Tuesday 6" means Tuesday 6 is valid, while "market moved from
Tuesday 6" means it is not. The old prompt's wording "cancellation or move ...
on TARGET_DATE" was ambiguous.

Decision: the classifier contract now explicitly distinguishes move FROM the
target (suppress) from move TO the target (do not suppress), and every negative
result must use the same canonical empty evidence/null-date form.

### 6. Preserve existing delivery architecture

The existing Sunday–Thursday 19:25 run and 20:25 recovery already provide the
right previous-evening timing and crash-safe deduplication.

Decision: no new cron, Telegram state, message type, dependency, collector or
background process. The market is another verified event unit in the existing
planning publication. A Tuesday market moved by a holiday receives a compact
schedule note explaining the Wednesday holiday.

## Expected 2026-10-05 behaviour

At the Monday 5 October evening run, target day is Tuesday 6 October.
The reviewed calendar marks it as the market day because Wednesday 7 October
is an official Guardamar holiday. If the bounded Mayor check finds no validated
exception, the planning post includes:

- `08:00–13:30 — Рынок`
- parking La Redonda
- a note that it was moved from Wednesday because 7 October is the Virgen del
  Rosario holiday.

The Tuesday 6 October run targets the holiday Wednesday 7 October and therefore
does not create a second market item.
