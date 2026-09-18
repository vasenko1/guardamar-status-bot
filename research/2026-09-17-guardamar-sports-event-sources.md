# Guardamar sports event source audit — 2026-09-17

> **Status update — 2026-09-18:** FACV and Federación Pesca CV are implemented, tested, merged via PR #109 and deployed to production. The source contracts and deferred-source analysis below remain useful, but any wording that describes FACV/Pesca integration as future work is superseded by this status.

## Goal

Find the smallest reliable set of official/responsible sources that adds useful
Guardamar sports events not already covered by the existing municipal event
catalogs.

This is a source audit plus the implementation contract for the first accepted
sources. Sports competitions are normal city events: they belong in the same
normalized `Event` stream used by the Morning Digest and the Friday weekend
digest. They do **not** get a separate sports-events guide card, navigation
branch, or parallel publication system.

Recurring classes and sections remain a different product surface under
`🎓 Занятия и секции`.

## Existing architecture to preserve

- Recurring activities stay in the existing `Занятия и секции` branch.
- Sports competitions reuse the existing normalized `Event` contract and the
  existing `_merge_events(...)` deduplication path.
- Morning and weekend output read local event catalogs; source network reads
  stay in the existing pre-publication catalog refresh flow.
- Source parsing stays in small source-specific modules.
- No provider registry, generic scraper engine, source YAML, database, browser,
  per-sport daemon, per-sport cron, or generic relation graph.
- Before adding a source, check whether the municipal/Turismo/Agenda catalogs
  already provide the same resident value.
- Federation sources are supplements. Absence from a federation page is never
  interpreted as cancellation of a municipal event.

## Source matrix

| Area | Responsible source | Technical shape | Guardamar value | Decision |
| --- | --- | --- | --- | --- |
| Chess | FACV official calendar | One server-rendered HTML annual calendar; explicit name/start/end/place/organizer | High. Multiple 2026 Guardamar events, including events not found in the municipal web search | **Implement as Event supplement** |
| Surfcasting / sport fishing | Federación de Pesca CV | Server-rendered HTML tables; date/organizer/level/modality/place/province/zone | High, but very noisy. Contains provincial/national Guardamar competitions and many low-value club qualifiers | **Implement as Event supplement with strict level filter** |
| Running / Cross / road races | ChipLevante / ChampionChip Levante when it is the event's actual registration/timing platform | Server-rendered calendar and event pages; event pages can carry registration window, price, races, rules | Medium-high. Strong registration facts, but Cross/Media Maratón are often also announced by Turismo | **Conditional candidate; wait for a live Guardamar future event** |
| Tennis | RFET Circuito Nacional | Server-rendered annual table plus official Fact Sheet PDF | Medium. 2026 Open Real Villa is well structured, but currently one annual event | **Defer adapter** |
| Basketball | FBCV | Federation competition/event pages | Low for current product: most data is routine league activity; occasional training events exist | **Defer** |
| Volleyball / beach volleyball | FVBCV | Federation competition and club pages | Low for current product: mostly league/circuit data, no current Guardamar special event found | **Defer** |
| Football / futsal | FFCV/iSquad and club site | Federation competition data / club match pages | Low for current product: mainly routine matches | **Defer** |
| Archery | FTACV | Official event calendar with registration/convocation links | Technically good, but no current/future Guardamar-hosted event found | **Watchlist** |
| Mountain / climbing | FEMECV | Official calendar + registered local club | Technically usable, but no current/future Guardamar-hosted event found | **Watchlist** |
| Road cycling | FCCV preferred; Peña Cicloturista site secondary only | Federation data preferred | Local club site is not suitable as an automated factual source because its pages contain unrelated spam/SEO contamination | **Federation discovery only** |
| MTB | Federation/municipal sources preferred | Club site exists but current public content is stale | No stable current event feed established | **Municipal/federation discovery only** |
| Nautical / regattas | Relevant federation + municipal source | Club/Marina pages are not a complete structured event calendar | No stable complete Guardamar event feed established | **Federation/municipal discovery only** |
| Roller skating | No confirmed Guardamar club/source | None | No current local `Patinafis/Patinafís` or Guardamar roller club verified | **Unresolved; no source** |
| Petanque | Municipal agenda | No current local club feed verified | Facilities exist, but a facility is not proof of a current club/program | **Event discovery only** |
| Skate | Ayuntamiento/Sporttia/municipal programme source | Existing municipal-source pattern | Activity/program exists independently of any old skate association | **Handle as activity/program, not sports-event source** |
| Nautilus camps / water courses | Operator's current programme pages | Programme-specific pages | Better fit for holiday/program research; not a sports competition source | **Keep out of sports-events slice** |

## Accepted source 1 — FACV chess calendar

Official calendar:
`https://www.facv.org/appwebfacv/public/staff/torneos/calendario_oficial.php`

Observed technical shape on 2026-09-17:

- `text/html`, server-rendered table;
- one annual page, no browser or JavaScript execution required;
- explicit `Nombre`, `Inicio`, `Final`, `Lugar`, `Organizador` fields;
- exact `Guardamar del Segura` location is available for filtering.

Examples present in 2026 include:

- `Campeonato de España Escolar Equipos`, 24–26 April;
- several IPCA World competitions, 2–12 June;
- `S2000 Playas de Guardamar`, 26–28 June;
- `S1800 Esphouses`, `Esphouses S2400`, and `Open Dama Guardamar`, 1–6 September.

The September Esphouses programme was also present in municipal/Todo Cultura
coverage, so the federation source must pass through the same event merge path
and must not create a second resident-facing event surface.

Implementation contract:

- one bounded annual-calendar GET;
- exact-place filter `Guardamar del Segura`;
- retain current/future rows only in the local catalog;
- no event-detail fetches;
- source failure preserves the last valid local snapshot;
- Morning Digest/weekend selection reads the local snapshot with zero FACV
  network requests.

## Accepted source 2 — Federación de Pesca CV

Primary page:
`https://federacionpescacv.com/competiciones-de-nuestros-clubes/`

Observed technical shape:

- `text/html`, server-rendered tables;
- fields include date, organization, level/type, modality, location, province,
  and fishing zone;
- exact `GUARDAMAR` location can be filtered deterministically.

The page is intentionally too broad to publish wholesale. It contains many
`SOCIAL CLASIF.` club events on Guardamar beaches. Those are not automatically
resident-relevant merely because the venue is local.

Initial inclusion allowlist:

- `MUNDIAL`
- `NACIONAL`
- `AUTONOMICO` / `AUTONÓMICO`
- `PROVINCIAL`

Do **not** include `SOCIAL CLASIF.`, ordinary club qualifiers, or `ESPECIAL`
without a separate product reason. Multiple consecutive rows describing the
same competition normalize into one date range.

The production parser confirmed a `PROVINCIAL — MAR COSTA` event on 17 October
2026 and a `NACIONAL — MAR COSTA DÚOS` event on 23–29 November 2026.

Implementation contract:

- one bounded table GET;
- exact `GUARDAMAR` filter plus the explicit level allowlist;
- collapse consecutive identical competition rows into a date range;
- no detail crawling;
- source failure preserves the last valid local snapshot;
- Morning Digest/weekend selection reads the local snapshot with zero Pesca CV
  network requests.

## Deferred candidates

### ChipLevante

Calendar:
`https://www.chiplevante.com/recomendadas.asp`

The public calendar/event pages are technically usable and can expose race
date/place, races, prices, organiser, regulations and registration windows.
There was no current future Guardamar row on 2026-09-17. Use it only when it is
the actual timing/registration platform chosen for a real future Guardamar
event. Do not infer annual recurrence from history.

### RFET

Calendar:
`https://www.rfet.es/es/circuito-nacional-rfet-torneos.html`

The 2026 table contains `24º OPEN REAL VILLA DE GUARDAMAR`, Club de Tenis
Guardamar, 1–8 August, with an official Fact Sheet. Technical quality is good,
but one annual event does not justify another adapter yet. Re-evaluate if
Guardamar coverage becomes recurrent or the municipal sources are repeatedly
late/incomplete.

## Production probe — completed 2026-09-17

The candidate pages were fetched directly from the production Android/Termux
runtime with the same simple network path expected by the bot:

| Source | HTTP | MIME | Bytes | Seconds | Redirect | Guardamar matches |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| FACV | 200 | `text/html` | 637691 | 0.514 | none | 37 |
| Federación Pesca CV | 200 | `text/html` | 1037513 | 3.402 | none | 50 |
| ChipLevante | 200 | `text/html` | 169756 | 1.034 | none | 0 |
| RFET | 200 | `text/html` | 96847 | 1.768 | none | 6 |

A second production run executed the actual source adapters. FACV correctly
returned no current/future Guardamar event on 2026-09-17. Pesca CV returned the
future provincial 17 October event and the national 23–29 November event.

This accepts the FACV/Pesca transport and parser contracts. No further
production source probe is required before integrating them into the normal
event catalog flow.

Pesca CV is intentionally bounded at roughly 1.5 MiB because the observed page
is already about 1.04 MiB. Both sources should be refreshed once in the
existing pre-publication event-catalog sync. No separate cron or more frequent
polling is justified.

## Implementation status — completed 2026-09-18

FACV and Federación Pesca CV are no longer future work.

Production/main contains both source-specific adapters and their integration
into the existing local event-catalog path. The fully tested research tree was
squash-merged through PR #109 as commit
`2d1ec861c07a264f11dbf5e0c5689e420a6b4c37` (`Add FACV and Pesca CV event
sources`), then deployed to the Android/Termux production checkout.

Production validation after deploy confirmed:

- FACV accepted snapshot: valid, zero current/future Guardamar facts at the
  observation time;
- Pesca CV accepted snapshot: two eligible future facts;
- provincial Mar Costa on 17 October 2026;
- national Mar Costa Dúos on 23–29 November 2026;
- Morning/Weekend consume local snapshots and do not issue federation network
  requests.

Do not re-merge or redeploy the historical sports research branch. Further
sports source adapters (ChipLevante, RFET, etc.) remain deferred until a real
Guardamar coverage gap justifies them.

## Explicit non-goals

- no `sports_events.py` aggregate catalog;
- no `🏆 Спортивные мероприятия` pinned guide card;
- no permanent per-event Telegram cards;
- no separate sports-event notification system;
- no provider registry or generic sports scraper;
- no new daemon, browser automation, database, or cron schedule.
