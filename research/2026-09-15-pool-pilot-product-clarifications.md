# Pool Pilot Product Clarifications

## Date

2026-09-15

## Status

Owner-supplied product and local-operational clarification. This note supplements
`2026-09-15-guardamar-municipal-pools-and-swimming.md`; it does not replace the
web/source evidence recorded there.

## 1. Public source/operator exposure policy

The resident-facing product does not need to explain who operates a municipal
service when that fact does not help the resident use the service.

For the pool pilot:

- do not name Aqualider in ordinary public cards merely because it is the
  contracted swimming-course operator;
- keep provider/operator identity, procurement records, source hierarchy,
  freshness checks, and extraction logic internal;
- when the bot can reproduce current verified facts itself, publish the facts
  directly rather than linking residents to the upstream source;
- include an upstream URL only when the resident needs it to complete an action
  the bot cannot complete: booking, registration, payment, account access, or a
  similar workflow;
- when such a link is needed, prefer the direct action/deep link over a generic
  provider homepage;
- a source link should not be added merely as attribution if it adds no resident
  value and unnecessarily exposes the project's source map.

This is a product/competitive policy, not permission to hide uncertainty. If a
fact cannot be verified with sufficient freshness, omit the fact or qualify it
instead of presenting an unsupported claim.

## 2. Swimming season and mutually exclusive pool operation

The project owner supplied a corrected local-operational rule that applies to
the municipal pool system as a whole:

- **summer: only the outdoor municipal pool is in operation;**
- **winter: only the indoor/heated pool is in operation;**
- the two pool facilities are not operated in parallel;
- when the outdoor summer pool is operating, the indoor pool is drained/not in
  service;
- when the indoor winter pool is operating, the outdoor pool is drained/not in
  service.

Therefore the active venue for a swimming programme is first constrained by the
seasonal facility state. A course cannot legitimately be scheduled in the
inactive/drained pool merely because copied provider text names it.

### Default automatic season calendar

For the product, use the following **default automatic calendar unless a later
specific exception is learned**:

- **16 June through 15 September, inclusive: outdoor municipal pool active;**
- **16 September through 15 June, inclusive: indoor/heated Manel Estiarte active.**

This is now a product rule, not a multi-source inference performed every year.
The bot does not need a fresh annual announcement merely to switch between these
two normal seasons.

If Ayuntamiento, Deportes, the pool, or another trusted operational source later
announces an exceptional opening/closure or different switch date, that explicit
exception overrides the default calendar for the affected period. After the
exception ends, the normal calendar resumes.

The municipal lifeguard contract is **not an accepted source for the operational
pool calendar**. Its staffing/coverage clauses may be retained as procurement
context, but must not be used to decide which pool is open, public hours, or the
season switch.

For 2026 this means:

- **15 September 2026 is treated as the final day of the outdoor summer season;**
- **from 16 September 2026 the indoor/heated pool is treated as the active pool.**

No additional current notice is required for that normal switch under this
product rule. If a contrary operational notice appears, correct the state and
published information.

### Young-child programmes

There is an additional programme-level restriction for the very-young-child
`Bebés` / `Peques` family:

- these courses use the shallow outdoor pool;
- they are therefore **summer-only**;
- there is no corresponding winter version in the deep indoor pool.

This explains the contradiction found in the public booking catalogue where a
`Peques (Tardes)` title referenced `Piscina climatizada` while its description
referenced the outdoor pool. The product must not turn that copied title into a
winter indoor programme.

The provider catalogue uses separate `Natación Bebés` and `Natación Peques`
labels with different age wording. The project must still not silently merge,
rename, or remap those labels until the current programme names and age ranges
are verified.

### Adult and older-child programmes

Adult and older-child programmes may exist in both seasonal parts of the year,
but their venue follows the active pool:

- in summer, a current course may use the outdoor pool;
- in winter, a current course may use the indoor pool;
- this does **not** mean both pools are active at the same time.

The implementation therefore needs two distinct concepts:

1. **facility season/state** — which municipal pool is currently active by the
   default calendar or a specific exception;
2. **programme availability** — which courses exist during that season.

Do not encode venue independently from facility season, and do not infer that a
course continues across the seasonal switch unless current programme data proves
it.

## 3. Consequence for card drafting

The first public drafts should be resident-first and source-light.

Example information layers:

- place card: the currently active pool/facility, usable current facts,
  phone/contact if useful, booking action if available, and a link to `Плавание`
  inside the Telegram guide;
- swimming card: currently verified programme families, age/season/schedule/price
  only where fresh and internally consistent, and a link back to the currently
  active pool;
- external links: only direct booking/registration/payment actions that cannot be
  represented inside Telegram;
- no public `operator`, `source`, `procurement`, or monitoring-method fields.

Because only one municipal pool is active at a time, the public navigation must
not suggest simultaneous summer and winter availability. On 16 June and 16
September the relevant pool card/state changes automatically according to the
default calendar unless an explicit exception is active.

The research/ADR layer keeps the full evidence trail so maintainers can audit
why a fact is trusted without exposing that trail in the resident-facing
product.
