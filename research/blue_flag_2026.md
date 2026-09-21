# Blue Flag 2026 — deferred research

Status: **DEFERRED / DO NOT IMPLEMENT**

Date: 2026-09-22

This note preserves the source investigation for a possible future Blue Flag
feature. It is intentionally not an approved product design. Do not add polling,
Telegram messages, cards, state, cron entries, or production behavior from this
document until the beach UX is decided.

## Product question still open

The unresolved question is how Blue Flag information should appear in the
product:

- dedicated beach cards;
- only change/award alerts;
- a compact attribute inside an existing beach/root/guide message;
- or no separate surface at all.

Until that is decided, keep this as research only.

## What is reliably known for Guardamar in 2026

ADEAC's official 2026 award dataset lists five Guardamar del Segura beaches:

- Centre
- Dels Vivers
- La Roqueta
- Del Moncaio
- Ortigues-Campo

The safe claim is:

> the beach is included in the official list of Blue Flag awardees for the
> 2026 season.

For a beach absent from that list, the safe claim is only:

> the beach is not included in the official list of Blue Flag awardees for
> 2026.

Do **not** turn absence from the list into "failed", "was denied", "lost the
flag", or "is not Blue Flag" without an explicit official source saying so.
The annual list alone does not tell us whether a beach applied, failed,
withdrew, or did not participate.

## Official ADEAC annual award source

Official 2026 map page:

https://www.banderaazul.org/sites/default/files/2026/Rueda-de-prensa-2026/BanderaAzul2026.html

Official 2026 award list PDF:

https://www.banderaazul.org/sites/default/files/2026/Rueda-de-prensa-2026/Relaci%C3%B3n%20Playas%20Galardonadas%202026.pdf

The map page exposes a public Mapbox vector tileset for beaches:

- tileset:
  `senderoazul.cmorcsai81b1r1nqidivznavn-999zb`
- layer:
  `PLAYAS_BANDERA_AZUL_2026`
- useful fields:
  `MUNICIPIO`, `PROVINCIA`, `ccaa`, `fid`, `galardonado`,
  `marker-symbol`, `nueva`, `recupera`, `title`

A Guardamar Tilequery test returned the five awardees above, all with
`galardonado: Sí`.

This source is cheap and structured, but it is an **annual award registry**, not
a proven current-status feed.

## Why ADEAC Mapbox must not be treated as live status

Control case: Playa Fluvial A Calzada, Ponte Caldelas.

A Calzada was publicly documented as renouncing its 2026 Blue Flag after the
award had already been granted. The current ADEAC 2026 Mapbox dataset still
returns:

- municipality: Ponte Caldelas
- title: Playa Fluvial A Calzada
- `galardonado: Sí`

Therefore, continued presence in the ADEAC award map is not proof that a Blue
Flag is currently flying or remains valid after a later renunciation or
withdrawal.

Use ADEAC Mapbox for "awarded for the season", not for "currently active".

## International FEE investigation

International map:

https://www.blueflag.global/site-map

The site map was traced to FEE's public site-profile system. The profile page
loads a legacy Angular client from:

https://feeglobalproxy.kindly.dk/js/Fee/SiteApp/showsite.js

That client requests:

`GET https://feeglobalproxy.kindly.dk/sites/getsite?siteId=<siteId>`

Known test profiles:

- Centre, Guardamar: `siteId=8524`
- Playa Fluvial A Calzada: `siteId=8824`

Public profile URLs:

- https://www.blueflag.global/show-site?siteId=8524
- https://www.blueflag.global/show-site?siteId=8824

The direct API returned HTTP 200 JSON for both.

For Centre it returned, among other profile fields:

- `siteName: Centre`
- season `2026-06-01` to `2026-09-30`
- type `Beach`

For A Calzada it still returned:

- `siteName: Playa Fluvial A Calzada`
- season `2026-07-01` to `2026-08-31`
- type `Beach`

The complete top-level profile did not expose a reliable award-state field such
as `currentAward`, `withdrawn`, `activeAward`, or equivalent.

Several nested fields contain `status: active`, but those statuses belong to
profile/select values such as beach type, sandy/rocky, disabled access, or
lifeguards. They are not Blue Flag award status.

Conclusion: the FEE profile API is useful as a site catalogue/profile source,
but it is **not a reliable live Blue Flag status source**.

## FEE ArcGIS / map path

The international map was also traced to FEE ArcGIS material, including Web Map
item:

`8c7e31ef77184d81bf19f425972525f3`

That investigation did not produce a trustworthy field that distinguishes an
active award from a later temporary/permanent withdrawal. Do not build runtime
logic on ArcGIS presence alone.

## ADEAC withdrawals / renunciations

Official ADEAC inspections page:

https://www.banderaazul.org/inspecciones

ADEAC documents that flags may be withdrawn temporarily or permanently when
requirements are not met. ADEAC has also published annual
`Renuncias / Retiradas` documents in some seasons.

Known official 2025 example:

https://www.banderaazul.org/sites/default/files/2025/Renuncias-Retiradas%20BA%20-%2015%20julio%202025-1.pdf

Important limitations found during the 2026 investigation:

1. The inspections page is not a dependable live feed; on 2026-09-22 it still
   referenced the summer-2024 published withdrawal list.
2. Annual withdrawal/renunciation PDF filenames are not stable between years.
3. A public 2026 equivalent was not found during this investigation.
4. Published `Renuncias / Retiradas` material may cover permanent withdrawals
   and voluntary renunciations, but does not establish a complete machine-
   readable lifecycle for short temporary withdrawal and later restoration.

Therefore these documents are valuable evidence when found, but they do not
justify a claimed real-time status monitor.

## Current source semantics

Treat the sources as follows:

| Source | Safe meaning | Not safe to claim |
| --- | --- | --- |
| ADEAC annual PDF / Mapbox | Awarded for that season | Flag is currently flying / still valid after later change |
| FEE site profile API | Site profile and stated season | Current award state |
| FEE map / ArcGIS presence | Site exists in international catalogue/map | Current award state |
| ADEAC Renuncias/Retiradas | Explicit listed withdrawal/renunciation when present | Complete temporary-withdrawal + restoration lifecycle |

## Possible future low-cost approach

If this feature is approved later, prefer a bounded annual workflow rather than
polling:

1. once per new award season, discover the official ADEAC annual list;
2. normalize Guardamar awardees;
3. compare with the previous season;
4. update the relevant user-facing surface only after the product UX is
   approved;
5. optionally watch for explicit official ADEAC renunciation/withdrawal
   documents or municipal notices, but do not call that a complete live-status
   monitor.

No hourly/daily Blue Flag polling is justified by the evidence found so far.

## Candidate user-facing semantics

Preferred wording for a positive annual award:

> 🟦 Blue Flag 2026

For a full reference list, an absent beach may be described as:

> not included in the official 2026 list of awarded beaches

Do not use "lost", "failed", "denied", or "withdrawn" unless an official source
states that event explicitly.

## Implementation guard

Before any implementation, decide first:

1. Are there dedicated beach cards at all?
2. If yes, is Blue Flag a static annual attribute of those cards?
3. If no cards, is an annual award-change alert useful enough to justify a
   message?
4. Should Blue Flag appear in the daily seasonal beach root, or would that add
   noise to an operational status message?
5. What exact event should trigger a notification: annual award publication,
   explicit withdrawal, restoration, or only a change versus the previous
   season?

Until those decisions are made, **do not implement this feature**.
