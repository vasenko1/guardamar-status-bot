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

The exact calendar dates for the seasonal switch are a separate operational
fact. They must be obtained from a fresh current source before the bot publishes
or automates statements such as `summer pool opens on X` or `indoor pool closes
on Y`. Do not derive the exact switch date from an old page or from a lifeguard
contract alone.

### Current 2026 switch-date evidence gap

A fresh check on 2026-09-15 did **not** find an explicit current public notice
from Guardamar Ayuntamiento/Deportes, the pool itself, or the current service
operator saying that 15 September 2026 is the final public day of the outdoor
pool season or giving the exact indoor-pool reopening date.

There is strong supporting evidence for 15 September as the expected summer
boundary:

- the current municipal lifeguard technical specification schedules outdoor-pool
  coverage for `1 al 15 de septiembre`;
- the old municipal pool page also used a `16 de junio al 15 de septiembre`
  summer period, but that page is explicitly labelled `VERANO 2023`.

Neither item is sufficient by itself for an unqualified current public claim.
The current technical specification explicitly allows schedule variations based
on Sports Department needs, including facility closure. Therefore `15 September`
is an internal baseline/expectation until confirmed by a fresh operational
announcement.

For a public seasonal-switch notification, accepted evidence should be one of:

1. a current Ayuntamiento/Concejalía de Deportes announcement;
2. a current official pool/sports-facility announcement;
3. a current announcement from the contracted service operator clearly referring
   to Guardamar's municipal pool operation;
4. another current official operational source that explicitly states the open/
   close or switch date.

A resident/community message saying `today is the last day` is a useful discovery
signal, but it is not publication evidence by itself.

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

1. **facility season/state** — which municipal pool is currently active;
2. **programme availability** — which courses exist during that season.

Do not encode venue independently from facility season, and do not infer that a
course continues across the seasonal switch unless a current source proves it.

## 3. Consequence for card drafting

The first public drafts should be resident-first and source-light.

Example information layers:

- place card: the currently relevant pool/facility, usable current facts,
  phone/contact if useful, booking action if available, and a link to `Плавание`
  inside the Telegram guide;
- swimming card: currently verified programme families, age/season/schedule/price
  only where fresh and internally consistent, and a link back to the currently
  active pool;
- external links: only direct booking/registration/payment actions that cannot be
  represented inside Telegram;
- no public `operator`, `source`, `procurement`, or monitoring-method fields.

Because only one municipal pool is active at a time, the public navigation
should not suggest simultaneous summer and winter availability. When the season
switches, the relevant pool card/state and any affected swimming-programme facts
should switch together once the change is verified.

The research/ADR layer keeps the full evidence trail so maintainers can audit
why a fact is trusted without exposing that trail in the resident-facing
product.
