# Tomorrow municipal-market alert review — 2026-10-05

## Scope

Review and implement the safest minimal way to include Guardamar's municipal
La Redonda market in the existing `Завтра в Гуардамаре` planning message,
including the holiday-driven move from Wednesday 7 October 2026 to Tuesday
6 October 2026.

## Existing reviewed facts

The project already has reviewed first-party/legal evidence for the market:

- Guardamar's 2023 non-sedentary-sales ordinance defines the weekly Wednesday
  municipal market at parking La Redonda and adjacent streets.
- If Wednesday is a holiday, that market is held on the preceding Tuesday.
- Customer hours are `07:00–13:30` from June through September and
  `08:00–13:30` during the rest of the year.
- The reviewed 2026 Guardamar holiday calendar includes 7 October as the local
  Virgen del Rosario holiday.
- `holidays.is_market_day()` already returns true for 2026-10-06 and false
  for 2026-10-07.
- The Morning Digest already uses the bounded `@AlcaldeGuardamar` exception
  check before asserting a scheduled La Redonda market.

Official references retained by the project:

- https://www.guardamardelsegura.es/wp-content/uploads/2023/09/BOP-NUEVA-ORDENANZA.pdf
- https://documentacion.diputacionalicante.es/fiestas.asp

## Gap

The existing next-day publication did not include recurring rules, so the
deterministically known municipal market never reached the previous evening's
planning message.

During implementation, `main` advanced with the sports/planning refactor.
That introduced `planning_events.load_local_planning_events()`, a shared
local-only loader that can optionally include recurring events. The final
solution is based on that newer architecture rather than mechanically rebasing
the earlier draft.

## Red-team cycles

### 1. Reuse the shared planning pipeline

A separate market message, scheduler, state file or event pipeline would
duplicate delivery logic and create another public-message lifecycle.

Decision: keep one `Завтра в Гуардамаре` publication and merge the reviewed
La Redonda occurrence into its existing Event stream after verification.

### 2. Do not leak the Sunday Campo market into this change

An initial implementation enabled generic recurring events in the shared
Tomorrow loader and relied on the production Sunday-through-Thursday schedule
to avoid a Sunday target. Focused tests exposed the hidden flaw: the producer
and preview can be invoked directly on Saturday, in which case generic recurring
events would add the separate Sunday Campo market and silently broaden scope.

Decision: keep `include_recurring=False` for Tomorrow's shared local loader.
Derive only the reviewed La Redonda occurrence with the existing market rule,
verify it, then merge that single event into the planning stream. Campo remains
owned by the Weekend/Morning behavior and is untouched.

### 3. Keep the shared planning loader local-only

The new shared loader explicitly promises no source HTTP or AI. Moving the
Mayor check into that helper would contaminate Weekend and future planning
surfaces with a source dependency.

Decision: load and merge local planning facts first with generic recurring
events disabled. Apply the narrow La Redonda rule and Mayor exception
verification only in `tomorrow_events.py` after the shared loader returns.

### 4. Avoid a stale positive claim

A calendar-only evening alert could say "tomorrow market" after an explicit
same-day cancellation or ad-hoc move was already published by the Mayor.

Decision: only when tomorrow is a reviewed La Redonda market, perform the
existing bounded Mayor-page check immediately before the assertion. If the
check fails, omit only the market; unrelated tomorrow events remain eligible.

### 5. Separate observation time from market date

The old `market_is_cancelled(now)` used one datetime for both source freshness
and the market date. Passing a future datetime would incorrectly shift the
seven-day source-freshness window.

Decision: keep real observation `now` for post freshness and pass an optional
explicit `market_day` to the classifier.

### 6. Make model validation truly fail closed

Previously a relevant market post plus an invalid positive classification
could fall through as `False`, which means "not cancelled".

Decision: a clean negative must be exactly `cancelled=false`, empty evidence,
and null event date. A positive must pass exact quotation/date validation.
Anything else raises a source error and the market is omitted.

### 7. Distinguish move TO from move FROM

"Mercadillo se traslada al martes 6" proves Tuesday 6 is the occurrence date.
A move away from Tuesday 6 means the opposite.

Decision: the classifier contract now explicitly defines move FROM target as a
positive suppression and move TO target as a negative result. Negative output
must still use the canonical empty-evidence/null-date form.

### 8. Preserve merged-event correctness

The shared Event merge may enrich the generic recurring title/place from a
catalog record. Cancellation must still remove that merged market.

Decision: identify the target market by the reviewed occurrence time plus
market title semantics (`рынок` / `mercad*`) and La Redonda/no-place
compatibility, rather than by object identity alone.

### 9. Do not repeat source/model work on recovery

Tomorrow Events historically constructed the publication before checking dated
delivery state. That was harmless while construction was local-only, but would
make the 20:25 recovery repeat Mayor/AI work after a successful 19:25 send.

Decision: the real send command now preflights the existing target-date delivery
state before publication construction. `sent` or `uncertain` exits before
source work. The existing second state check under the exclusive delivery lock
remains, so race protection is unchanged. Preview stays state-free.

### 10. Accept the bounded overnight freshness window

A cancellation published after the evening planning post can make that post
stale before morning. Closing this rare window would require a watcher and
post-edit lifecycle.

Decision: do not add overnight monitoring/edit state. Verify immediately before
the evening assertion and verify again through the existing Morning Digest
market check. This is an explicit freshness boundary, not an unhandled logic
branch.

## Expected behavior for 2026-10-05

At the Monday 5 October evening run, the target date is Tuesday 6 October.
The reviewed calendar moves the weekly market there because Wednesday
7 October is the local Virgen del Rosario holiday.

If the bounded Mayor check finds no validated exception, the existing
`Завтра в Гуардамаре` post includes the La Redonda market at
`08:00–13:30` plus a compact note explaining the Wednesday-holiday move.
Any other verified events for Tuesday remain in the same planning post.

The Tuesday 6 October run targets the holiday Wednesday 7 October and therefore
does not create a second market item.

## Implementation boundary

No new cron, database, state file, source, dependency, daemon, queue or
resident process is added. The shared planning loader remains local-only.
