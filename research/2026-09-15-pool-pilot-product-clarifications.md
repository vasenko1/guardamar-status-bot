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

## 2. Swimming season and venue clarification

The project owner supplied local operational context for pool usage by age/group:

- the relevant very-young-child / `Peques` format is associated with the shallow
  outdoor pool;
- the indoor pool is deep and this young-child format is not a winter indoor
  programme;
- adult swimming programmes can use both the indoor and outdoor municipal pools,
  depending on programme and season;
- therefore the product must not apply a blanket rule such as `summer = outdoor`
  or `winter = indoor` to all swimming programmes;
- copied source wording such as `Piscina climatizada` is not enough to override
  the known young-child venue/season constraint.

This local clarification helps explain the contradiction found in the public
booking catalogue, where a `Peques (Tardes)` title referenced the heated/indoor
pool while its description referenced the outdoor pool.

However the public catalogue also exposes separate `Natación Bebés` and
`Natación Peques` labels with different age text. Because that terminology does
not cleanly align with the local clarification, implementation must **not**
silently merge, rename, or remap those source labels. Before a detailed public
child-swimming card is published, the current programme name, age group, season,
and venue should be verified from a fresh operational source or direct booking
flow.

Safe product implication now:

- treat the relevant very-young-child swimming format as seasonal/outdoor unless
  a fresh verified source proves a different current arrangement;
- do not show a winter indoor `Peques` programme based only on contradictory
  provider copy;
- treat adult venue as programme/season-specific rather than fixed to one pool;
- do not expose the provider/source identity in the final card unless a direct
  action link is required.

## 3. Consequence for card drafting

The first public drafts should be resident-first and source-light.

Example information layers:

- place card: pool name, usable current facts, phone/contact if useful, booking
  action if available, link to `Плавание` inside the Telegram guide;
- swimming card: currently verified programme families, age/season/schedule/price
  only where fresh and internally consistent, link back to the pool;
- external links: only direct booking/registration/payment actions that cannot be
  represented inside Telegram;
- no public `operator`, `source`, `procurement`, or monitoring-method fields.

The research/ADR layer keeps the full evidence trail so maintainers can audit
why a fact is trusted without exposing that trail in the resident-facing
product.
