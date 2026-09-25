# 112CV emergency and Previfoc source investigation

Date: 2026-09-20  
Status: implemented / retained source research

## Goal

Add only high-value official emergency information for Guardamar del Segura while
keeping the Termux runtime cheap, deterministic, and fail-closed.

The bot must not infer flood or fire danger from raw sensor values. It should
publish only official statuses or decisions and should remain silent when the
source does not support a useful claim.

Product-value rule: every scheduled source must have a direct path to an
actionable user-facing message or to suppress/update such a message. Do not
schedule a source merely because data is available, useful for historical
analysis, or interesting for diagnostics.

## Confirmed 112CV surfaces

### 1. Emergencias vigentes

Public URL:

`https://www.112cv.com/WebPublica-MapasOnLineV2/emergencias.jsf?idioma=es_es`

Production probe on 2026-09-20:

- HTTP 200
- server-rendered HTML
- about 2.7 KB
- no browser, token, API key, or authenticated session required for a simple GET
- current no-event text: `SIN EMERGENCIAS VIGENTES`
- only that explicit global no-event marker is a clear observation when no
  Segura hydrological status is parsed; a generic emergencies page with no
  matching Segura status is UNKNOWN rather than an inferred all-clear

Product use:

- poll continuously but cheaply;
- publish only when a relevant official emergency appears or changes;
- expected high-value examples include flood-plan states such as
  `SITUACIÓN 0/1/2`, not routine weather warnings.

Candidate user-facing message:

> 🚨 **Активирован план по наводнениям**  
> CCE — 112 Comunitat Valenciana объявил Situación 1 в связи с наводнением
> для официально указанной территории.  
>  
> Источник: CCE — 112 Comunitat Valenciana

A later official downgrade, escalation, or end is a separate state transition
and may produce one compact update.

### 2. Current CCE meteorological PDF

Public URL:

`https://wpr.112cv.gva.es/external/api/storage/descargar/pdf/avisosmeteorologicos/avisometeorologico.pdf`

Production probe on 2026-09-20:

- HTTP 200
- `application/pdf`
- about 157 KB
- about 0.24 s in the probe
- `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
- no browser, token, API key, or authenticated session required
- text layer is machine-readable; OCR is not required
- document contains its own `FECHA` / `HORA`
- current document includes a `PLANES DE EMERGENCIA ACTIVADOS` section
- the URL may legitimately keep the previous day's last bulletin when no new
  bulletin has been issued; runtime therefore validates the embedded local date
  and treats an older document as unavailable, never as an all-clear

This source must **not** duplicate ordinary AEMET warning messages.

Product use:

- AEMET remains primary for ordinary meteorological warnings;
- check this PDF once per hourly `check-112` run rather than gating it on a
  local Guardamar AEMET rain/thunderstorm warning;
- the lower Segura can deteriorate from upstream rainfall or basin/reservoir
  operations even when Guardamar itself has no active AEMET warning;
- search for operational/hydrological decisions not already supplied by AEMET,
  for example:
  - `PREEMERGENCIA HIDROLÓGICA`
  - `INUNDACIONES`
  - `SITUACIÓN 0`
  - `SITUACIÓN 1`
  - `SITUACIÓN 2`
  - `SEGURA`
  - corresponding `FIN` / deactivation text.

Candidate user-facing message for a hydrological decision:

> ⚠️ **Гидрологическая обстановка**  
> CCE — 112 Comunitat Valenciana объявил жёлтый уровень гидрологической
> preemergencia в бассейне Segura.  
>  
> Статус относится к бассейну Segura и сам по себе не означает подтопление
> Guardamar.  
>  
> Источник: CCE — 112 Comunitat Valenciana

Open validation item: confirm on a future real hydrological activation whether
the current `wpr` PDF actually carries the hydrological status, rather than
only publishing it through other CCE channels.

### 3. Meteorological preemergencias page

Public URL:

`https://www.112cv.com/WebPublica-MapasOnLineV2/municipiosMapaRiesgo.jsf?idioma=es_es`

Production probe:

- HTTP 200
- server-rendered HTML
- about 32 KB
- accessible without browser automation

Current role: fallback/cross-check only. Ordinary CCE meteorological warnings
largely overlap AEMET and should not create duplicate Telegram content.

## GeoServer and open incidents

The public frontend references layers such as:

- `gis112cv:V_INCIDENTES_CURSO`
- `gis112cv:V_INCIDENTES_EN_CURSO`
- `gis112cv:V_ZONAS_PREVIFOC`
- `gis112cv:V_ZONAS_EMERGENCIA_METEO`
- `gis112cv:V_ZONAS_PRE_EMERGENCIA_METEO`

The current frontend JavaScript uses OpenLayers `ImageWMS` directly and calls
`GetFeatureInfo` on click. It parses fields including:

- `TITULO_ES`
- `CREATED`
- `DESCRIPCION_ES`
- `DESCRIPCION_VA`
- `MUNICIPIO`
- `ASOCIADAS`
- `DIRECCION`

However, direct production probes confirm:

- WFS -> `Service WFS is disabled`
- WMS -> `Service WMS is disabled`
- the same result occurs with a normal JSF session and Referer.

Therefore open incidents are **not a usable production datasource now**.
Do not work around the disabled GeoServer with image recognition, map scanning,
private mobile APIs, or browser automation.

## Previfoc

### Guardamar zone

The 112CV municipal form confirms:

`Guardamar del Segura -> zona 6 de risc per incendis forestals`

The same response exposes INE `3076`. Internal JSF field
`valorZona=66` must not be interpreted as the public zone number; the
user-facing zone is 6.

### Operational ArcGIS source — confirmed

The official Previfoc home page uses an ArcGIS FeatureLayer service directly:

`https://vaersa.org/arcgis/rest/services/Nivel_preemergencia_Alerta3_112/MapServer/`

The page JavaScript explicitly selects:

- layer `0` for `Dia 1` (current operational day);
- layer `1` for `Dia 2` (next-day forecast).

Both layers support `Query` and expose one polygon per Previfoc zone with fields:

- `ZonaID`
- `RiesgoId`
- `TormentaID`
- `Dia`
- `AlertaDiaID`

Guardamar del Segura belongs to `ZonaID=6`, so the minimal machine-readable
request can query only that row and omit geometry, for example:

`/0/query?where=ZonaID%3D6&outFields=ZonaID,RiesgoId,TormentaID,Dia,AlertaDiaID&returnGeometry=false&f=json`

and the same against layer `1` for tomorrow.

Confirmed 2026-09-20 probe:

- layer 0 / zone 6: `RiesgoId=1`, `TormentaID=1`, `Dia=1`;
- layer 1 / zone 6: `RiesgoId=1`, `TormentaID=1`, `Dia=2`.

Official Previfoc semantics:

- `RiesgoId=1`: low-medium forest-fire risk;
- `RiesgoId=2`: high forest-fire risk;
- `RiesgoId=3`: extreme forest-fire risk.

Dry-thunderstorm semantics are separate:

- `TormentaID=1`: no dry-thunderstorm risk is reported;
- `TormentaID=2`: possibility of dry thunderstorm;
- `TormentaID=3`: high dry-thunderstorm risk.

This ArcGIS service is now the preferred Previfoc source. It is superior to the
PDF and historical Excel for runtime use because it is current/next-day,
structured, tiny, and directly queryable for Guardamar's zone without map
rendering, PDF parsing, OCR, or historical-table latency.

Product consequence: do not schedule the Previfoc PDF or historical Excel for
routine runtime collection while this ArcGIS endpoint remains available and
stable. Keep the PDF only as an operator/research cross-check if needed.

### Current official PDF

URL:

`https://wpr.112cv.gva.es/external/api/storage/descargar/pdf/previfoc/previfoc.pdf`

Production probe on 2026-09-20:

- HTTP 200
- `application/pdf`
- about 138 KB
- about 0.21 s
- no browser/authentication required
- contains target date, e.g. `NIVEL PARA EL DÍA / NIVELL PER AL DIA : 20/09/2026`
- text layer contains legend/comments but does not expose the zone numbers
  drawn on the map in a reliable text form.

Do not add OCR merely to read zone 6 from the PDF.

### Historical table / Excel export

Official page:

`https://prevencionincendiosgva.es/Meteorologia/NivelPreemergenciaList`

The HTML contains a normal table with explicit zone columns, including
`Z.6`, and an Excel button.

The page JavaScript confirms a server-side export route:

`/Meteorologia/ExportarHistoricoAExcel`

The exact export query construction still needs one final probe. The page and
pagination expose the likely filter fields:

- `desde`
- `hasta`
- `riesgoID`
- `provinciaID`
- `zonaID`

Important freshness observations:

- the historical table is daily (one row per calendar date), not hourly;
- on 2026-09-20 around 02:00 Europe/Madrid it still ended at 19/09/2026;
- at the same time the operational Previfoc surface already exposed 20/09/2026
  and 21/09/2026, i.e. current day plus next-day forecast;
- official/administrative material states that the level is set daily, a
  next-day Previfoc forecast is also issued, and the daily level may be
  readjusted if conditions change;
- multiple Previfoc/municipal fire-prevention documents state that the public
  112 level is updated daily at approximately 17:00.

Therefore the historical Excel/table is not the same freshness tier as the
operational current/next-day Previfoc surface and must not be used as the
primary current alert source unless future probing proves otherwise.

Product decision: a historical-only Excel/table is **not needed** by the bot.
It must not receive a cron job or network budget merely for analytics. Continue
investigating that export only if it can prove that it exposes the current or
next operational Previfoc value early enough to drive a user-facing message.
Otherwise close this branch and use another current operational source.

### AEMET versus Previfoc dry thunderstorms

AEMET can forecast and discuss dry thunderstorms meteorologically, but
Meteoalerta has no separate operational dry-thunderstorm warning type. Its
`Tormentas` warning is a general adverse-thunderstorm product. AEMET's separate
forest-fire danger product is also a national meteorological danger model, not
the Generalitat's Previfoc preemergency decision.

Previfoc therefore adds unique operational value. For Guardamar zone 6 it
publishes forest-fire preemergency and dry-thunderstorm risk as separate
official fields. Do not derive one from the other and do not replace Previfoc
with ordinary AEMET thunderstorm warnings.

### Previfoc desired behavior

Previfoc is primarily a daily value, but the authority can readjust the
same-day level. Folding its tiny zone-6 query into the already hourly
`check-112` watcher is accepted because it avoids another scheduler and makes
official revisions observable at negligible network cost.

Runtime model:

1. Use the operational current-day layer 0 for Guardamar zone 6. Layer 1
   remains a confirmed official next-day surface, but the bot does not poll or
   store it until a concrete user-facing next-day product needs that value.
2. Fold the tiny layer-0 query into the existing hourly `check-112` run at
   minute `:19`. This keeps same-day official readjustments observable
   without a second scheduler or material network cost.
3. Validate the explicit zone, `Dia=1`, bounded field values and response
   shape. A failed observation preserves the previous normalized state and
   cannot create an all-clear.

Public-message policy is finalized:

- keep the hourly `:19` observation cadence so same-day official readjustments
  remain observable;
- before 07:00 Europe/Madrid, store Previfoc observations but do not render or
  acknowledge a Previfoc transition as public;
- on the first run at or after 07:00, compare the current observation with the
  resident-facing baseline and publish only changed active levels 2/3;
- level 1 is the ordinary baseline: transitions to it are stored silently and
  never create a standalone clearance message;
- if an overnight transition reverses before morning, publish nothing about
  that intermediate state;
- after 07:00, later same-day changes between active levels remain eligible, but
  the message describes the current state rather than the transition history;
- this quieter policy applies only to Previfoc; CCE/hydrological
  downgrade/clearance behavior remains unchanged;
- fire level 2 uses `🌲 Пожарная опасность сегодня`;
- `TormentaID=2` uses `⚡ Сегодня возможны сухие грозы`;
- user-facing source attribution is `Generalitat Valenciana`; the internal
  product name `Previfoc` is not needed in resident copy.

This policy requires no second scheduler, resident worker, queue or additional
pending-state schema. The observed state itself is the pending candidate; the
existing `published` fields remain the resident-facing comparison baseline and
may advance silently on level 1 so a later return to level 2/3 is detectable.

## Hydrology source closure

The hydrology search was extended beyond 112CV:

- CHS public SAIH/iVisor and public ArcGIS expose river/reservoir measurements,
  stations and related GIS data, but no suitable ready current
  yellow/orange/red alert-state for lower Segura;
- Observatorio GOTA has a real anonymous `/publico/` API and public GIS/OGC
  services, but the public surfaces found expose catalogues, stations and
  measurement layers rather than an operational hydrological alert feed;
- GOTA's `config-avisos-umbrales-por-incumplimiento` endpoints are protected
  by authentication and are not a runtime source for this bot;
- the national RAN hydrological alert system is documented in 2026 material as
  still under development.

Decision: do not infer danger from raw H/Q values and do not continue private
API/authentication reverse engineering. CCE/112 remains the operational
hydrology authority source for the bot; CHS/GOTA remain manual/research context.

## 112 watcher scheduling

Current repository schedule includes:

- Hidraqua at `:00` and `:30`
- earthquake monitor at `:55`
- operational monitor at `:00/:05/:10` in its bounded windows
- optional capacity backstop at `:12/:27/:42/:57`
- guide at 16:30
- transport at 05:00 / notification at 12:30
- electricity attempts at 20:30, 20:35, 20:45, 21:00, 21:20
- Friday weekend jobs at 18:00, 18:20, 19:00

Current 112 cron slot:

`:19` every hour.

At each invocation, run **one orchestrator process**. Individual source
adapters never publish Telegram messages independently.

1. Do not make another AEMET network request; AEMET remains an independent
   weather-warning source.
2. GET `emergencias.jsf` every run. It is only about 2.7 KB.
3. Fetch the current CCE `avisometeorologico.pdf` every run. Do not gate this
   hydrology check on a local Guardamar AEMET warning.
4. Query the tiny current-day Previfoc ArcGIS state for Guardamar zone 6 so
   same-day readjustments are observable without a second scheduler. The
   confirmed next-day layer is not polled until a product action needs it.
5. Parse all source results into normalized candidate states.
6. Merge/deduplicate candidates with explicit precedence; an official active
   emergency state is stronger than a hydrological preemergency observation.
7. Compare the final merged state with the small persisted prior state.
8. Publish at most one coherent Telegram transition for the run, or remain
   silent when there is no actionable change.

The fact that the HTML and PDF requests complete at different speeds is
irrelevant to public output because neither source publishes on completion.
The process waits for the bounded source set required for that run, merges the
results, and only then reaches the Telegram boundary. If an optional source
fails, its failure must not erase a stronger valid state from another source.

The existing AEMET snapshot already preserves warning `starts_at` and
`ends_at`, so the watcher can use the actual active interval instead of the
earlier publication time.

## PDF lifecycle on the phone

The CCE PDF must not accumulate on Android storage.

Preferred implementation:

- download only bounded PDF bytes into process memory;
- pipe those bytes directly to Poppler `pdftotext` through stdin and capture
  text from stdout (for example, `pdftotext -layout - -`);
- parse the text in memory;
- discard both PDF bytes and extracted text when the short-lived process exits;
- persist only the small normalized authority state/hash/timestamps required
  for deduplication.

No dated PDF archive, raw response cache, or permanent download directory is
needed. If a future platform limitation ever requires a temporary file, create
it only in the runtime temp directory and unlink it in a guaranteed cleanup
path; this is fallback behavior, not the preferred design.

## Deduplication and attribution

The CCE PDF and `emergencias.jsf` are two observations of the same official
state, not two independent notification streams.

Normalize to one compact state and publish only transitions. If the PDF detects
`SITUACIÓN 1` first and `emergencias.jsf` shows the same state later, the
second observation must not create another Telegram message.

For public messages, use attribution such as:

`Источник: CCE — 112 Comunitat Valenciana`

The bot remains a convenience layer and must not claim to replace official
emergency channels.

## Guardrails

- official sources only;
- no Selenium/Playwright/browser runtime;
- no private mobile-app reverse engineering;
- no OCR for routine Previfoc extraction;
- no interpretation of raw river levels into self-invented alert levels;
- fail closed when parsing is ambiguous;
- source failure is not an all-clear;
- keep state small and atomic;
- no resident process;
- no duplicate AEMET/CCE weather messages.

## Open questions

1. Whether a real future Segura hydrological preemergencia appears in
   `avisometeorologico.pdf`, `emergencias.jsf`, both, or neither.
