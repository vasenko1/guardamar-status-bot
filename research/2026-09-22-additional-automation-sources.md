# Additional automation sources for Guardamar

Reviewed 2026-09-22.

## Goal

Identify additional resident-facing information that can be automated cheaply on
the existing Android/Termux production runtime.

Source-selection priority:

1. JSON / XML / RSS / other structured public data.
2. Ordinary server-rendered HTML.
3. Only then anything heavier.

Avoid browser automation, headless Chromium, OCR, image parsing, PDF parsing,
large national feeds, new resident daemons, or expensive/high-frequency
polling unless there is no simpler source and the resident value clearly
justifies it.

## Recommended candidates

### 1. SUMA — municipal taxes and payment deadlines

Candidate product value:

- voluntary payment-window start/end;
- direct-debit charge date;
- last day to set up domiciliación where explicitly published;
- Guardamar-specific payment periods such as IBI, IAE and vados.

Verified 2026-09-24:

- Guardamar municipal page: `https://www.suma.es/cuerpo_infmunicipal.xhtml?m=76`;
- general voluntary-payment page: `https://www.suma.es/periodo-pago-voluntario`;
- the Guardamar page currently lists IBI urbana, IBI rústica, IAE and vados
  for 27/07/2026–08/10/2026;
- the general page publishes the same 27 July–8 October period, a 23 September
  direct-debit setup deadline and a 1 October charge date;
- both facts are available in ordinary public HTML; no browser, login, AI,
  OCR or PDF path is required.

Accepted product/lifecycle:

- two bounded sequential HTML GETs once inside the existing 07:30 process;
- the Guardamar tax rows must match the general period dates exactly;
- deterministic parsing and fail-closed disagreement;
- first successful run is a silent baseline;
- exact-date messages only: opening, seven days before domiciliación closes,
  charge date, and one day before voluntary payment ends;
- missed dates are never replayed retrospectively;
- state stores only bounded semantic trigger-date keys;
- no new cron, daemon, queue, database or notification framework.

For a production bootstrap on 24 September 2026, opening and domiciliación are
already past and are silently baselined. The next eligible messages are
1 October and 7 October.

Implementation: `src/telegrambot/suma.py`, ADR 0077.

Status: **accepted for production implementation**.

### 2. Ayuntamiento Noticias — actionable municipal opportunities

Candidate product value:

- ayudas / subvenciones;
- education-related aid;
- municipal programmes and registrations;
- Bono Comercio and similar schemes;
- bolsas de empleo / public recruitment notices;
- other resident-actionable announcements.

Technical shape:

- WordPress-style municipal news pages are available as ordinary HTML;
- investigate the public WordPress RSS/feed or REST list first;
- article pages should be fetched only for new/changed items;
- no browser is required.

Product rule:

Do **not** turn the bot into a general municipal-news aggregator. Publish only
items where a resident can actually do something: apply, register, pay, attend
a required procedure, or meet a deadline.

Source rule:

Do not introduce PDF parsing merely because a linked edict or full legal basis
is a PDF. If the HTML contains enough verified facts, publish those facts. If a
deadline or eligibility condition exists only in an attached PDF, omit that
unsupported detail or link the official article instead.

Status: **strong candidate**.

### 3. Sede Electrónica — public notice board / trámite supplement

Candidate product value:

- tablón de anuncios;
- public employment processes;
- ayudas/subvenciones;
- education/social-services procedures;
- important new municipal trámite notices not yet mirrored clearly in the main
  news feed.

Technical shape:

- public pages expose server-rendered HTML with dates, notice identifiers,
  titles and categories;
- no browser should be required if production Termux receives the same public
  HTML;
- the Gestiona platform has REST services, but no anonymous public API contract
  for the exact data we need has been accepted yet.

Recommended approach:

- first run a production probe for redirects, cookies, MIME type, response size
  and stable visible markers;
- if plain HTML is stable, use it as a secondary completeness source;
- keep Ayuntamiento Noticias as the primary municipal opportunity source;
- do not build around undocumented/private Gestiona integration APIs.

Status: **promising, requires production probe**.

### 4. Generalitat Valenciana — blood-donation calendar

Candidate product value:

- future blood-donation sessions in Guardamar;
- exact date, location and opening hours.

Verified 2026-09-24:

- the official Centro de Transfusión page embeds a direct Alicante schedule;
- stable direct endpoint:
  `https://oficina20.san.gva.es/gportal-ctcvcol-portlet/listaColectas.jsp?provincia=0007`;
- the endpoint is ordinary public HTML and does not require the outer Liferay
  page, `jsessionid`, browser automation, PDF parsing or AI;
- the current programme includes Guardamar on 14/10/2026 at Centro Sanitario
  Integrado, Zona de Pediatría, 16:45–20:30.

Accepted product/lifecycle:

- discovery polling is limited to one bounded GET when seven local calendar
  days have elapsed since the last successful snapshot;
- store only normalized current/future Guardamar sessions in a tiny local
  snapshot; never cache the province-wide HTML;
- exact municipality filter and fail closed on malformed rows;
- rows explicitly marked `SUSPENDIDA` are omitted;
- at 16:45, no source request is made unless the weekly snapshot already knows
  that a Guardamar session is scheduled for tomorrow;
- for a known tomorrow session, perform one fresh control GET immediately before
  publication; cancellation/date disappearance suppresses the alert and changed
  hours/venue replace the old facts;
- the successful control response becomes the snapshot used by the next Morning
  Digest and resets the seven-day discovery timer; a previous-day snapshot is
  accepted by the digest only when it was observed at/after 16:45;
- no daemon, browser, PDF, AI, database or generic notification framework.

Implementation: `src/telegrambot/blood_donation.py`, ADR 0078.

Status: **accepted for production implementation**.

### 5. CHS SAIH — Río Segura at Guardamar

Candidate product value:

- current river level H;
- current flow Q;
- potentially a useful linked/static river-status card.

Technical shape:

- Confederación Hidrográfica del Segura publishes a plain HTML table;
- a row for A.Guardamar is available directly;
- H and Q can be extracted without browser, PDF, authentication or AI.

Important product constraint:

Do not invent resident alert thresholds. The source is technically excellent,
but alerts such as "dangerous level" require an official threshold or official
authority state. CCE/112 remains authoritative for emergency/hydrological
warnings.

Recommended first use:

- research exact official threshold semantics;
- otherwise expose the latest H/Q only as neutral information.

Status: **technically excellent; alert semantics not yet approved**.

## Sources to defer

### i-DE planned power cuts

The official Alicante planned-work publication currently resolves to a PDF.

Although the project can technically parse PDFs, that is not justified while
the goal is to prefer cheap lightweight sources. No simple stable public
JSON/CSV endpoint for the same Guardamar-filterable data has yet been accepted.

Decision: **defer**. Revisit only if a small stable structured endpoint is
found.

### Ecomóvil / Consorcio Vega Baja Sostenible

The official Ecomóvil calendar is currently presented visually and through a
Google My Maps embed rather than as simple structured timetable data in the
page HTML.

Possible future paths such as parsing My Maps or reverse-engineering the mobile
app are not justified for the current runtime/product.

Decision: **defer automation**. Static guide content may still be useful.

### PLACSP / beach lifeguard service

PLACSP provides machine-processable Atom/XML procurement data, but the exact
resident-facing details we care about — real service dates, hours, beach
coverage, Semana Santa transition periods, etc. — may still live inside
contract/pliego documents.

Reading a broad procurement feed and then opening contract PDFs is too heavy
for this product when a simpler operational source may eventually appear.

Decision: **keep the existing socorrismo research, but do not add a production
PLACSP monitor now**.

## Municipal works and road closures

Do **not** create a separate "municipal works / road closures" automation
product from Ayuntamiento Noticias.

Reason:

- official closure notices do sometimes appear;
- useful examples can contain exact street, date/time and reason;
- publication is incomplete and not reliable enough to claim broad coverage of
  Guardamar road closures;
- previous investigation also found no dependable general live Policía Local
  traffic feed.

Product rule:

If an explicit operational closure or works notice appears in an already-read
municipal source such as Ayuntamiento/AlcaldeGuardamar and contains concrete
location + validity + effect, it may be surfaced opportunistically.

Do not add a separate watcher, separate source family or resident promise that
the bot covers all road closures.

## Minimal implementation direction

Prefer small source-specific adapters rather than a generic provider framework:

- suma.py
- municipal-news adapter/module
- blood-donation adapter
- Segura/CHS adapter

Reuse existing orchestration and notification/event pipelines wherever
possible.

Do not add:

- browser automation;
- OCR;
- PDF parsing for these new candidates;
- a database;
- a message broker;
- a provider registry;
- a generic notification framework;
- a new always-on process.

## Suggested next step

Before accepting implementation, run a production Termux probe for the five
preferred sources and record:

- HTTP status;
- redirect chain;
- MIME type;
- compressed/uncompressed response size;
- latency;
- required cookies;
- stable marker for the needed Guardamar data;
- whether one request is sufficient on a no-change day.

The preferred end state is that each source costs roughly one small bounded GET
per scheduled check, and new/detail requests occur only when a list/feed
actually changes.
