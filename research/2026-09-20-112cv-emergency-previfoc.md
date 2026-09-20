# 112CV emergency and Previfoc source investigation

Date: 2026-09-20  
Status: research / product direction, not yet implemented

## Goal

Add only high-value official emergency information for Guardamar del Segura while
keeping the Termux runtime cheap, deterministic, and fail-closed.

The bot must not infer flood or fire danger from raw sensor values. It should
publish only official statuses or decisions and should remain silent when the
source does not support a useful claim.

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

This source must **not** duplicate ordinary AEMET warning messages.

Product use:

- AEMET remains primary for meteorological warnings;
- consult this PDF only during an active AEMET Guardamar warning for
  `lluvias` or `tormentas`, plus a short post-warning tail;
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

Important freshness observation:

- the historical table may lag the current day's operational Previfoc;
- on 2026-09-20 the current 112 PDF was dated 20/09/2026 while the historical
  table exposed data only through 19/09/2026.

Therefore the historical Excel/table must not be assumed to be the current-day
operational source until this behavior is verified.

### Previfoc desired behavior

Previfoc is a daily value, so hourly polling is unnecessary.

Preferred model:

1. Try once in the evening to acquire the next day's level for Guardamar zone 6.
2. Validate the source's internal target date.
3. If tomorrow is already available, store the normalized value and stop.
4. If not, retry once early the next morning.
5. After one valid value for the target date is stored, do not request it again
   that day unless a future source contract explicitly supports revisions.

Candidate schedule under the current repository cron layout:

- primary: 22:36 Europe/Madrid
- fallback: 04:36 Europe/Madrid

These times avoid current major scheduled jobs.

Public-message policy is not finalized. Current product direction:

- level 1: normally no standalone message;
- level 2: candidate for compact visibility in the morning briefing;
- level 3: candidate for a standalone official-risk notice.

No public message wording should be finalized until the current zone-6
machine-readable source is confirmed.

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

Candidate single 112 cron slot:

`:19` every hour.

At each invocation:

1. GET `emergencias.jsf` always. It is only about 2.7 KB.
2. Read the existing normalized AEMET snapshot; do **not** make another AEMET
   network request.
3. If current local time is inside an active Guardamar AEMET `lluvias` or
   `tormentas` warning, fetch `avisometeorologico.pdf`.
4. Continue conditional PDF checks for roughly 3 hours after the warning ends.
5. If an official hydrological/emergency state has already been observed,
   continue until the authority publishes its end/deactivation.

The existing AEMET snapshot already preserves warning `starts_at` and
`ends_at`, so the watcher can use the actual active interval instead of the
earlier publication time.

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

1. Exact direct URL and response format of
   `/Meteorologia/ExportarHistoricoAExcel`.
2. Whether the Excel/table can expose today's or tomorrow's operational
   Previfoc early enough to replace the PDF.
3. Whether a real future Segura hydrological preemergencia appears in
   `avisometeorologico.pdf`, `emergencias.jsf`, both, or neither.
4. Exact normalized state schema and final message copy.
5. Whether Previfoc level 2 deserves public output or only inclusion in the
   morning briefing.
