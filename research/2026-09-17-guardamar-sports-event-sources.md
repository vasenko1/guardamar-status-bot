# Guardamar sports event source audit — 2026-09-17

## Goal

Find the smallest reliable set of official/responsible sources that adds useful
Guardamar sports events not already covered by the existing municipal event
catalogs. This is a source audit, not permission to implement every source.

Public information architecture remains activity/event-first. Club/operator
names are provenance, not guide navigation.

## Existing architecture to preserve

- Recurring activities stay in the existing `Занятия и секции` branch.
- Sports events should reuse the existing normalized `Event` contract.
- Source parsing stays in small source-specific modules; `guide.py` / morning
  orchestration must not become parsers.
- No provider registry, generic scraper engine, source YAML, database, browser,
  per-sport daemon, per-sport cron, or generic relation graph.
- Before adding a source, check whether the municipal/Turismo/Agenda catalogs
  already provide the same resident value.

## Source matrix

| Area | Responsible source | Technical shape | Guardamar value | Decision |
| --- | --- | --- | --- | --- |
| Chess | FACV official calendar | One server-rendered HTML annual calendar; explicit name/start/end/place/organizer | High. Multiple 2026 Guardamar events, including events not found in the municipal web search | **Candidate** |
| Surfcasting / sport fishing | Federación de Pesca CV | Server-rendered HTML tables; date/organizer/level/modality/place/province/zone | High, but very noisy. Contains a Nov 23–28 national Mar Costa Dúos event in Guardamar and many low-value club qualifiers | **Candidate with strict level filter** |
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
| Roller skating | No confirmed Guardamar club/source | None | No current local `Patinafis/Patinafís` or Guardamar roller club verified. A Guardamar athlete competing elsewhere does not establish a local activity source | **Unresolved; no card/source** |
| Petanque | Municipal agenda | No current local club feed verified | Facilities exist, but a facility is not proof of a current club/program | **Event discovery only** |
| Skate | Ayuntamiento/Sporttia/municipal programme source | Existing municipal-source pattern | Activity/program exists independently of any old skate association | **Handle as activity/program, not sports-event source** |
| Nautilus camps / water courses | Operator's current programme pages | Structured enough for programme-specific extraction | Better fit for `Программы на каникулы` / recurring activities than the sports-event catalog | **Keep out of sports-events slice** |

## Evidence of coverage gaps

### FACV

Official calendar:
`https://www.facv.org/appwebfacv/public/staff/torneos/calendario_oficial.php`

Observed technical shape on 2026-09-17:

- `text/html`, server-rendered table;
- one annual page, no browser or JavaScript execution required for the facts;
- explicit `Nombre`, `Inicio`, `Final`, `Lugar`, `Organizador` fields;
- exact `Guardamar del Segura` location is available for filtering.

Examples present in 2026 include:

- `Campeonato de España Escolar Equipos`, 24–26 April;
- several IPCA World competitions, 2–12 June;
- `S2000 Playas de Guardamar`, 26–28 June;
- `S1800 Esphouses`, `Esphouses S2400`, and `Open Dama Guardamar`, 1–6 September.

The September Esphouses programme was also present in municipal/Todo Cultura
coverage, so the source must not create duplicate resident messages. However,
web searches of the current municipal sources did not find the April/June FACV
Guardamar rows, which demonstrates useful federation-only coverage.

### Federación de Pesca CV

Primary audit page:
`https://federacionpescacv.com/competiciones-de-nuestros-clubes/`

Also useful for federation-level competitions:
`https://federacionpescacv.com/convocatorias-clasificaciones-2026/`

Observed technical shape:

- `text/html`, server-rendered tables;
- fields include date, organization, level/type, modality, location, province,
  and fishing zone;
- exact `GUARDAMAR` location can be filtered deterministically.

The page is intentionally too broad to publish wholesale. It contains many
`SOCIAL CLASIF.` club events on Guardamar beaches. Those are not automatically
resident-relevant merely because the venue is local.

High-value confirmed gap: `FED. ESPAÑOLA PESCA Y C.` lists a `NACIONAL — MAR
COSTA DÚOS` event in `GUARDAMAR`, `PLAYA`, on 23, 24, 25, 26, 27 and 28 November
2026. This is exactly the kind of event a narrow source can discover before or
without the monthly municipal agenda.

Proposed initial inclusion allowlist if implemented:

- `MUNDIAL`
- `NACIONAL`
- `AUTONOMICO` / `AUTONÓMICO`
- `PROVINCIAL`

Do **not** include `SOCIAL CLASIF.`, ordinary club qualifiers, or `ESPECIAL`
without a separate product reason. Multiple consecutive rows describing the
same competition must normalize into one date range, not six events.

### ChipLevante

Calendar:
`https://www.chiplevante.com/recomendadas.asp`

Observed technical shape:

- `text/html`, server-rendered calendar;
- public event pages can expose race date/place, races, prices, organiser,
  regulations and registration links/windows;
- no Guardamar event is present in the currently visible future calendar on
  2026-09-17.

The source is not a general public authority. It is suitable only when it is
the actual timing/registration platform chosen by the organiser for that
specific event. Turismo Guardamar has historically linked to ChipLevante for
the Cross, so this can be a responsible event-specific source, not a generic
fallback aggregator.

Do not implement a permanent Guardamar race claim from historical recurrence.
Wait until the 2026 Cross (or another future Guardamar event) actually appears
on the responsible platform or an official municipal source.

### RFET

Calendar:
`https://www.rfet.es/es/circuito-nacional-rfet-torneos.html`

The 2026 table contains `24º OPEN REAL VILLA DE GUARDAMAR`, Club de Tenis
Guardamar, 1–8 August, and links an official Fact Sheet. The Fact Sheet gives
Guardamar venue, registration price and closing date.

Technical quality is good, but current observed value is one annual event. A
new dedicated adapter is not justified yet. Keep RFET in the source register
and re-evaluate if more Guardamar events appear or municipal coverage proves
repeatedly late/incomplete.

## Existing-source overlap

The municipal stack already catches many locally promoted sports events:

- September 2026 Esphouses chess festival;
- September 2026 Club Tenis de Mesa presentation tournament;
- Cross Urbano in previous seasons through Turismo/municipal publication.

Therefore the sports work should be a **gap-filling supplement**, not a second
parallel event system.

## Minimal implementation direction

Do not implement code until the production Termux network probe below confirms
the candidate pages are reachable with the same simple bounded HTTP assumptions.

If probes pass, the first useful implementation slice should be deliberately
small:

1. `facv.py`: one bounded annual-calendar GET, parse only future rows whose
   exact place is `Guardamar del Segura`, normalize to the existing `Event`
   shape (or an equally small source snapshot consumed by the guide).
2. `pesca_cv.py`: one bounded GET, exact `GUARDAMAR` filter, strict competition
   level allowlist, collapse consecutive identical competition rows into one
   event/date range.
3. Do **not** add ChipLevante yet while it has no future Guardamar row. Keep it
   as a validated source candidate and add it when a real future event proves
   the contract.
4. Do not add RFET, FBCV, FVBCV, FFCV, FTACV, FEMECV adapters yet.

The first resident-facing sports-event surface should be one aggregate durable
`🏆 Спортивные мероприятия` guide card, created only when current/future
eligible events exist. No permanent per-event Telegram messages and no
cross-link graph are needed for the first slice.

## Production probe still required

Web inspection proves current page content and HTML structure, but not exact
behaviour from the production Android/Termux network path. Before accepting an
adapter contract, verify response status, MIME, redirects, size and latency on
the phone for:

- FACV calendar;
- Federación Pesca CV club-competition page;
- ChipLevante calendar (candidate only);
- RFET calendar (comparison only).

No code/source contract should claim those production transport properties
until that probe is recorded.
