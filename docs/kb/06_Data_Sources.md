# Data Sources

The implemented providers are AEMET, Ministerio de Sanidad Meteosalud,
Copernicus CAMS through a normalized public data product, Guardamar's public SafeBeach page,
Agenda Guardamar, the public `@AlcaldeGuardamar` channel, the Biblioteca Pública Municipal de Guardamar,
Agrupación Musical Guardamar, SUMA Gestión Tributaria, and the Centro de Transfusión de la Comunitat Valenciana. The 07:30 run requests current morning data
directly and reads events from four pre-morning local catalogs. Operational
SafeBeach flags are intentionally excluded from the immutable Morning Digest
and use a separate seasonal daily beach root.

The remaining municipal and seasonal publisher roles are mapped in
`research/2026-07-27-guardamar-municipal-source-map.md`. Except for the
approved Agenda Guardamar adapter, they are not implemented until their exact
official endpoints and lightweight access methods are validated.

| Source category | Purpose | Expected reliability | Update style | MVP |
| --- | --- | --- | --- | --- |
| AEMET OpenData | Guardamar forecast, nearby observation, official weather warnings | High; responsible Spanish authority | Structured API; API key required | Yes, first slice |
| Ministerio de Sanidad Meteosalud | Today's heat- and cold-health risk for `Litoral sur de Alicante`, zone code `770303` | High; official national health source | Separate bounded morning reads of the official summer (`ISO_V`) and winter (`ISO_I`) technical TXT files; stale dates omitted | Yes, optional |
| CAMS European Air Quality Forecasts | Forecast pollutants, mineral dust, wildfire PM10 contribution and six pollen types | High for model forecast; not an observation or official measured ICA | Separate public producer makes bounded morning publication attempts; bot checks at 10:40 and then only through existing operational recovery until today's cycle is accepted | Yes, optional |
| ESIOS / Red Eléctrica | Next-day PVPC 2.0TD hourly active-energy term | High; official system operator publication | Indicator API `1001`; personal API key required | Yes, evening feature |
| Official marine service | Sea state and relevant marine warnings | High for its jurisdiction | API or published feed | Yes |
| SafeBeach public Guardamar page | Active beach flags and jellyfish operational status | High when municipal lifeguards actively maintain it | Small structured payload embedded in the public page | Yes |
| Generalitat Valenciana bathing-zone control via Guardamar publication index | Current-year control window, actual sample dates, and official weekly laboratory/visual beach ratings | High; control authority is Servicio de Calidad de Aguas, while Guardamar publishes the local report index | One bounded index read at 19:35 during the official 1 June–15 September season; PDF downloaded only for a new report identity and parsed fail-closed with existing Poppler | Yes, weekly public notice |
| Civil protection or emergency authority | Safety warnings | Highest priority | Alert feed or official publication | Yes |
| CCE — 112 Comunitat Valenciana | Active emergency and hydrological authority state relevant to Guardamar/Segura | Highest priority for authority decisions; complements rather than duplicates AEMET | Public `emergencias.jsf` plus current text-readable CCE PDF, checked by one bounded hourly watcher | Yes, narrow operational monitor |
| Previfoc / Generalitat Valenciana (VAERSA ArcGIS) | Official zone-6 forest-fire preemergency plus dry-thunderstorm risk for Guardamar | High; responsible regional fire-prevention/emergency source | Tiny structured ArcGIS query for the current operational day; same-day level may be readjusted | Yes, narrow operational monitor |
| SUMA Gestión Tributaria | Guardamar municipal tax periods, voluntary-payment deadline, direct-debit setup deadline and charge date | High; official Alicante provincial tax-management authority | Two bounded public HTML GETs once in the existing 07:30 daily lifecycle; municipal rows must match the general campaign dates exactly | Yes, four exact-date standalone reminders |
| Centro de Transfusión de la Comunitat Valenciana | Future Guardamar blood-donation sessions: date, venue and hours | High; official regional blood-donation programme | One bounded Alicante HTML discovery GET only when seven local days elapsed, plus one fresh 16:45 control GET only when the snapshot already knows a session is tomorrow | Yes, ADR 0078 |
| Instituto Geografico Nacional (IGN) GeoRSS | Nearby recorded earthquakes | High; official Spanish seismic authority | One bounded public XML feed request per hour; deterministic 20 km and magnitude 1.8 filter | Yes, narrow standalone notice |
| Policía Local Guardamar | Historical reviewed festival restriction only | The reviewed page did not provide a dependable current traffic feed in routine operation | Retired from runtime; no scheduled request and no AI fallback | No |
| Agenda Guardamar | Official ticketed events occurring today | High for listed Ayuntamiento events | 05:30 bounded HTML/Schema.org catalog refresh | Yes |
| Turismo Guardamar municipal agenda | Broader official monthly cultural text plus supplementary MUPI | High for text; image facts require agreement | 05:10 text-first catalog refresh; MUPI only after URL change | Yes |
| Turismo Guardamar public WordPress festival article | Full dated programme when the monthly MUPI contains only a small inset | High; primary municipal tourism publication | Bounded public REST posts search, then linked full-size poster; explicit dated article facts survive poster/model failure. The validated poster URL may be retained as optional next-day media metadata; image bytes are not archived. | Yes, narrow Campo programme |
| Biblioteca Pública Municipal de Guardamar agenda | Library exhibitions, films and other library activities | High; first-party library agenda | One bounded 05:10 list refresh; details only for new, visibly changed, or previously failed cards | Yes |
| Agrupación Musical Guardamar WordPress posts | Its future public musical events in Guardamar | High for its own published events | One bounded 05:10 REST list refresh of twelve recent posts; changed posts only are extracted. The same request may embed one validated official featured-media URL for optional next-day presentation; no image bytes are stored. | Yes, ADR 0058 / 0080 |
| BOE, DOGV, and official Guardamar holiday calendar | Official national, regional, and local days off applicable in Guardamar; Wednesday-market holiday moves | High; legally authoritative annual publications | Small reviewed annual in-code calendar; no morning request | Yes |
| `@AlcaldeGuardamar` public channel | Explicit market exceptions, bathing-status transitions, Fiestas de Barrio, and complete invited same-day municipal announcements | Operational municipal channel; text must be mechanically grounded | One bounded morning event check, market check when relevant, or one check after SafeBeach retries | Yes, narrow role |
| Colegio Oficial de Farmacéuticos de Alicante | Legally authoritative on-call pharmacy rota | High; the provincial college responsible for the service | One weekly bounded fetch of the linked annual XLSX with compressed and uncompressed size bounds; normalized 45-day catalog for Guardamar's complete published service zone `61`, including duties assigned in San Fulgencio; no morning request | Yes, ADR 0038 |
| Campo de Guardamar market website | Sunday market at Camino del Raso, 15 | Operator-published schedule; no authoritative cancellation feed found | Local Sunday rule, `07:00–16:00` | Yes, explicit product exception |
| Community or commercial sources | Gap filling only | Variable | Varies | No by default |

## Approved SUMA tax-period source

Use only the official Guardamar municipal page with municipality id `76` and
the official SUMA voluntary-payment page. The municipal page supplies the local
tax rows and their exact collection period; the general page supplies that
campaign's direct-debit setup deadline and charge date. A campaign is accepted
only when at least one Guardamar row has the same start and end dates as the
general period. Source disagreement, ambiguous labels, malformed dates,
unexpected HTML, redirects outside the exact SUMA host, or unavailable pages
fail closed.

Collection is two sequential bounded HTML GETs once per existing daily run.
No login, cookie state, browser, PDF, OCR, AI, raw-page cache or source history
is required. The first successful run seeds only semantic trigger dates at or
before that local day. Future exact-date triggers remain eligible; a missed
trigger is never replayed from cached data. Campaign-specific dates and observed
tax rows belong in the dated SUMA research record rather than this stable KB.

## Approved morning health and atmosphere data

The two Meteosalud technical files are read separately during the 07:30 run:
`SANIDAD_NIVELES_ZONAS_ISO_V.txt` (heat) and
`SANIDAD_NIVELES_ZONAS_ISO_I.txt` (cold), both for `Litoral sur de Alicante`,
zone code `770303`. Only a level explicitly dated for today's `Europe/Madrid`
date is eligible. Level zero and stale data are silent. Each source fails
independently without blocking the digest; no season or temperature is inferred.

The bot does not call ADS or decode scientific files. The separate public
[`vasenko1/guardamar-cams-data`](https://github.com/vasenko1/guardamar-cams-data)
repository runs its producer workflow at 07:17 and 08:17 UTC. Each run makes
two small official ADS retrieves: two UTC days of ensemble analysis for the
five ICA pollutants and the current 00 UTC ensemble forecast at lead hours
0–48 for those pollutants, mineral dust, PM10 wildfire contribution, and
alder, birch, grass, mugwort, olive, and ragweed pollen. It selects the nearest
CAMS cell to Guardamar and publishes only validated UTC hourly values in a
versioned JSON. Producer failure preserves the previous file.

At 07:30 the bot reads the newest valid JSON available at that moment. The
Morning Digest is immutable after publication. Production keeps a mutable
last-good CAMS cache separate from the accepted lifecycle snapshot used to
reconstruct the previous semantic baseline. Fetched production candidates are
written atomically and are promoted only by the lifecycle that accepts that
forecast cycle. Operator previews use a disposable cache copied from the
last-good file, so a preview cannot overwrite the production cache or candidate.

One early late-cycle check runs at 10:40. If today's UTC forecast base is still
unavailable, only the first invocation of already scheduled operational windows
provides recovery until that daily cycle is accepted. A newer cycle is summarized
only for the remaining local day
and compared with the previously accepted remaining-day state. A material
user-facing worsening, improvement, appearance, or clearance may produce one
standalone Telegram update, normally as a reply to the Morning Digest. A
technical cycle change or a numeric change that does not alter the displayed
meaning stays silent. Late CAMS data never rebuilds, edits, deletes, or replaces
the Morning Digest. A stale, malformed, non-covering, or unavailable response
cannot be treated as an improvement or remove a previously valid warning.
AEMET `Polvo en suspensión` remains an independent CAP warning; CAMS dust may
affect only conservative explanatory wording.

The bot applies the MITECO 2020 ICA bands locally: latest hour for NO2/SO2,
trailing eight-hour mean for O3, and trailing 24-hour mean for PM10/PM2.5. It
shows only `Desfavorable` or worse and identifies the worst pollutant(s). CAMS
is a forecast, not a measured official ICA. Pollen is shown only above the
documented high thresholds (>50 grains/m³ for alder, birch, grass, mugwort;
>200 for olive), while ragweed uses presence-only `>=3 grains/m³` wording.

Visible CAMS-derived Telegram content carries a compact modified-data
attribution and responsibility disclaimer. The public producer also records
the full attribution and licence context. Neither project claims endorsement
by the European Commission, ECMWF, or Copernicus.

## Approved IGN earthquake feed

Use the official public GeoRSS document at
`https://www.ign.es/ign/RssTools/sismologia.xml`. This is a machine-readable
public feed, not a separately documented REST API. The adapter permits only
that exact HTTPS host and path, accepts XML/RSS content, limits the response to
256 KiB, times out after ten seconds, and makes no internal retry. It parses at
most 128 items and cross-checks the coordinates repeated in the official item
description and GeoRSS fields. Malformed or ambiguous records are omitted; a
non-empty feed with no valid records is rejected.

The monitor uses Guardamar coordinates `38.0896, -0.6553` as its stable local
reference. It publishes only a new event with magnitude at least 1.8 and an
unrounded great-circle distance no greater than 20 km. Event time supplied by
IGN in UTC is converted to `Europe/Madrid`. The user-facing map link points to
the exact decimal coordinates through Google Maps; Google Maps is presentation
only and supplies no earthquake fact. IGN's interactive maps and later
intensity products are not downloaded or screenshotted.

The feed is checked once per hour at minute 55, away from the known project
schedule. The first valid read seeds qualifying events silently. Fresh records
below the threshold remain eligible for a later IGN revision. State holds only
the latest normalized event parameters, delivery status, and current-series
message reference, with a 14-day and 256-record cap. Raw XML, map tiles,
screenshots, and unbounded event histories are not retained.

## Approved ESIOS product

Use official indicator `1001`, `Término de facturación de energía activa del
PVPC 2.0TD`, and only values whose `geo_name` is `Península`. API values are
€/MWh and are divided by 1000 for the user-facing €/kWh value. The request uses
`ESIOS_API_KEY` only in the header.

Red Eléctrica states that the next-day set is normally published around
20:15–20:20. Independent attempts run at 20:30, 20:35, 20:45, 21:00 and 21:20.
The same schedule covers an empty, incomplete or temporarily unavailable
response; the client itself makes one bounded request and never sleeps between
attempts. Exactly one value for every local hour 00–23 is required; incomplete,
duplicate, malformed, wrong-date, or non-Península data causes that invocation
to publish nothing. The first complete response is atomically stored as one
private normalized target-day snapshot containing indicator `1001`,
`Península`, the date, and 24 €/kWh values. Public output is built from this
snapshot. It contains neither the personal token nor the raw API response and
is replaced for the next target date. Confirmed publication is checked before
source access, so later scheduled attempts make no ESIOS request.

Color is presentation metadata, not source data from ESIOS. Rank the complete
24-hour local day by price: the cheapest eight hours are green, the middle
eight yellow, and the most expensive eight red. A price level tied across a
third boundary is never split between colors, so tie-heavy days may contain
unequal group sizes. If both boundaries collapse to one value, that shared
price level is yellow.

## Approved CCE and Previfoc risk sources

AEMET and Previfoc have different product roles. AEMET Meteoalerta has a
general `Tormentas` warning whose criteria cover strong electrical activity,
heavy rain, strong wind and hail. It does **not** expose a separate operational
`dry thunderstorm` warning state. AEMET also publishes its own meteorological
forest-fire danger model, but that six-class model is not the Generalitat's
official fire-preemergency state.

For Guardamar, use Previfoc zone 6 as the operational fire source. The official
VAERSA ArcGIS service exposes separate normalized fields for forest-fire risk
(levels 1 low/medium, 2 high, 3 extreme) and dry-thunderstorm risk. Therefore a
normal AEMET thunderstorm warning must never be treated as proof of a dry
thunderstorm, and the Previfoc dry-thunderstorm field must never be inferred
from AEMET rain/lightning data.

Use CCE — 112 Comunitat Valenciana for official emergency/hydrological state.
The small public `emergencias.jsf` page and the current CCE meteorological PDF
are observations of one authority state and must be normalized/deduplicated
before Telegram delivery. Ordinary CCE meteorological warning text must not
duplicate AEMET.

The CCE PDF check is independent of local AEMET rain/thunderstorm warnings.
Hydrological deterioration in the lower Segura can originate upstream or from
basin/reservoir operations, so absence of a local Guardamar AEMET warning is
not a safe gate. One bounded hourly `check-112` invocation at minute `:19`
may fetch the small HTML, the current PDF and the tiny Previfoc zone query.
CCE/hydrological transitions remain immediately eligible. Previfoc observations
before 07:00 Europe/Madrid are stored silently; the first run at or after 07:00
may publish only a still-current delta, so a midnight day-boundary change that
reverts overnight never becomes a stale public notice. No extra cron or queue
is required. Parse the PDF in memory through `pdftotext`; do not archive raw
PDFs.

Do not derive public flood danger from raw river height or flow. The public CHS
and GOTA surfaces found in the 2026-09-20 investigation expose measurements,
stations and GIS layers but no suitable ready current alert-state for the lower
Segura. GOTA's threshold-rule configuration is authenticated. The national RAN
hydrological alert system is documented as still under development. These
sources remain research/manual context, not bot alert inputs.

## Approved AEMET products

| Product | Selection | MVP use |
| --- | --- | --- |
| Municipal daily forecast | Guardamar municipality `03076` | Today's temperature range, up to two remaining sky conditions, one later-day wind comparison, and high-probability remaining rain |
| Conventional observation | Rojales station `7261X`, listed by AEMET as 5.3 km from Guardamar | Current temperature and wind, only when no more than three hours old |
| CAP warnings | Comunitat Valenciana area `77`, filtered to `Litoral sur de Alicante` | Active, today, and tomorrow hazardous warnings; render validity, probability, and recognized official hazard details |
| Beach forecast | Centro / La Roqueta `0307605` | Today's representative water temperature and two sea-state periods |

The AEMET API returns a metadata response containing a temporary product
download URL. Both requests are bounded by time and response size. The API key
is sent only to the metadata endpoint through `AEMET_API_KEY`; it is never
sent to the temporary product URL or committed.

The four approved AEMET products are requested sequentially. This avoids a
burst of concurrent metadata requests and respects the service's observed rate
limits at negligible cost for one daily run. A complete two-step request is
repeated only for timeouts, network failures, HTTP/API `429`, `5xx`, or an
expired temporary URL. The mandatory forecast has at most three attempts;
optional products have at most two. `401`, ordinary `404`, schema, date,
archive, size, and validation failures are not retried. `Retry-After` is
honored only when it fits the bounded process budget.

AEMET forecast periods of six hours or more are expressed in UTC. User-facing
rain intervals are converted to `Europe/Madrid`, including daylight-saving
time.
For sky conditions, periods that have already ended are ignored. Equal
adjacent states are collapsed and at most the first and last distinct
remaining states are retained for one compact transition.

The CAP warning download may be an XML document, ZIP archive, or TAR archive.
All supported containers are parsed in memory with compressed and uncompressed
size bounds. Warnings starting after tomorrow's Madrid date are deferred.
Matching daily CAP records may share one user-facing hazard block, but
different severity, probability, source description, or validity hours are
never merged.
The CAP `event` value must identify a known hazard before it is rendered.
Source-only labels such as `Aviso AEMET`, unknown labels, and future
unrecognized hazard names are omitted and logged; deterministic Spanish
aliases are normalized through the renderer allowlist rather than replaced by
a generic hazard name.

The nearby Rojales origin remains explicit in project documentation, but its
location label is omitted from the compact message. AEMET forecast wind may
provide one later-day comparison with current wind. The user-facing weather
heading attributes the data as `Погода от AEMET`; no separate source footer is
shown.

The municipality forecast supplies precipitation probabilities by period. At
collection time the adapter considers future periods, falling back to one that
still spans the current hour when no future period exists. The digest shows
only the highest eligible probability when it is at least 75%, together with
AEMET's period. Lower or malformed values are omitted.

## Approved SafeBeach data

Guardamar municipality links to
`https://info.safebeach.es/guardamar-del-segura`. The public page embeds
structured records for Guardamar beaches. The adapter selects
every valid active record among `Platja Centre / Babilònia`, `Platja La
Roqueta`, `Platja dels Vivers`, `Platja del Montcaio`, `Platja del Camp`, and
`Platja de les Ortigues`. Records retain their own beach names and are never
treated as measurements for a missing beach. The adapter reads only name,
activity state, service-ended state, update time, and flag color, plus
jellyfish presence, and Centre water temperature, sea state, wind speed, and
wind direction.

EULEN Sport is the current operational lifeguard contractor for Guardamar's
beaches, but no separate official public EULEN endpoint for Guardamar beach
conditions has been verified. The operator and the public data interface are
therefore distinct concepts: the implemented and approved source remains the
municipality-linked SafeBeach page. Current records appearing there may be
entered by the operating lifeguard service, but the public page does not expose
provenance that allows the bot to attribute an individual update to EULEN.
Do not describe EULEN as a second provider, combine SafeBeach with an assumed
EULEN feed, or use third-party beach aggregators as a fallback. Re-evaluate
only if EULEN or the Ayuntamiento publishes a Guardamar-specific official
endpoint with adequate freshness and source guarantees. See
`research/2026-08-14-eulen-sport-beach-status-source.md`.

Only active, non-ended lifeguard records are eligible. Before the final 10:40
attempt, the initial daily beach root requires plausible current flags for all
six known zones. At 10:40, one or more valid current flags are sufficient.
A missing timestamp omits only that beach; it delays an early complete root but
does not block the final partial root. Missing beaches are omitted and their
colors are never inferred. Optional sea, wind, and jellyfish fields never block
collection.

SafeBeach operational flags are never injected into the immutable 07:30
Morning Digest. The separate daily beach root uses verified flag colors and
explicit positive jellyfish state. AEMET remains the morning source for sea
temperature, sea state, and forecast wind. Missing SafeBeach records cannot
remove previously confirmed beaches from an existing daily root.

After the daily root exists, later seasonal monitoring uses bounded scheduled
checks and confirms candidate changes before publication. The root is edited
from the accumulated confirmed baseline, so a partial response cannot narrow a
previously fuller snapshot. A confirmed later change may also produce one reply
to the daily beach root; the initial root is not duplicated by a second reply.
If the root disappears between edit and reply, the bot recreates the complete
confirmed root first and retries the reply against that root. A change message
is never promoted into the beach-root slot.
The public `@AlcaldeGuardamar` page is also checked for a newer explicit bathing
transition during the initial root window and on the first invocation of each
already scheduled operational window. The check is bounded by the last stored
Mayor notice timestamp (or morning publication time when none exists), so an
old notice is not replayed. A newer prohibition or caution refreshes the same
beach root; source failure preserves the previous verified root facts.

The adapter makes one bounded HTTPS request to the exact public SafeBeach host,
accepts HTML only, and validates the page's calendar date against
`Europe/Madrid`. That rejects an old complete response but does not prove when
each beach record synchronized. It
extracts the embedded JSON from its fixed assignment with the standard JSON
decoder rather than executing JavaScript or matching the complete array with a
regular expression. Same-color duplicate records use the newest valid update
time. Conflicting timestamped flag colors or disagreements between a known
flag label and known flag color omit that beach. There is no internal retry,
cookie state, raw-response cache, or status history. A page with no eligible
record is a valid empty result, not a source error.

SafeBeach is currently requested only inside the local safety window from
15 June through 15 September, inclusive. Outside this window all operational
SafeBeach values are omitted, preventing a stale active record from exposing a
winter flag. This boundary is an internal guard rail only: it is not presented
to users as an official beach season and it does not control Zona Azul or any
other municipal service. SafeBeach's current-date, `hasActividad`, and
`serviceEnded` checks remain mandatory inside the window. Removing the guard
rail entirely requires a reviewed off-season observation proving that those
source flags reliably switch inactive when lifeguard service stops. AEMET sea
temperature and wave forecast remain available year-round.

## Approved municipal bathing-water programme

`https://www.guardamardelsegura.es/programa-de-control-de-las-zonas-de-bano/`
is the Ayuntamiento's publication index for Guardamar's annual bathing-zone
control programme. The control itself belongs to the Generalitat Valenciana's
`Servicio de Calidad de Aguas`, which is responsible for continuous
bath­ing-water quality control and surveillance during the season.

A dedicated short-lived one-shot checks the small index once per local day at
19:35 from 1 June through 15 September, inclusive. The normal
09:02 guide sync does not read this source.

The programme state stores the current-year control window and newest weekly
report period/URL. A PDF is downloaded only when that report identity changes.
The adapter reuses `pdftotext -layout` and accepts only reviewed Spanish or
Valencian first-page structures with exactly seven known Guardamar beach rows.
It requires official qualitative fields equivalent to `Análisis Agua`,
`Aspecto Agua`, and `Aspecto Arena`; recognized ratings normalize only from
the source's `EXCELENTE/EXCEL·LENT`, `BUENA/BONA`,
`SUFICIENTE/SUFICIENT`, and `INSUFICIENTE/INSUFICIENT` labels.

The parser also extracts actual per-row sample dates
(`Fecha/Data desc. punto1/punt1`) and requires every date to fall inside the
weekly report period. Public copy shows those actual sample dates, never labels
the report's covered week as the sample date.

The bot does not calculate its own public quality class from Enterococci or
E. coli counts. Laboratory water quality remains separate from visual water and
sand control. The first parsed report is public only if still fresh
(`report_end + 5 days`); an older first observation becomes a silent baseline.
Later weekly report identities produce at most one 🧪 public group notice using
the shared conservative Telegram-delivery contract. No PDF URL is shown to
residents; attribution names `Servicio de Calidad de Aguas · Generalitat
Valenciana`.


## Approved Agenda Guardamar data

`https://www.agendaguardamar.com/` identifies the Ayuntamiento as the site
operator and publishes event detail pages with Schema.org `name` and
`startDate`, optional `endDate`, and `location`. The adapter reads a bounded
programming page, follows at most twelve same-host event links with three
concurrent reads, parses only complete `application/ld+json` documents, and
stores every valid event in the next 45 days from those bounded pages. The
morning run selects records whose local date is today. It
recovers the title, start time and venue from the page's official calendar link
when broken JSON-LD contains an unescaped quoted stage name, or only recovers
the venue when JSON-LD contains the publisher identifier, and translates the bounded daily title
set into Russian. It accepts only bounded HTML from the official HTTPS hosts,
performs no media processing, and stores one small atomic normalized catalog,
not a history. A narrow repair
handles the site's observed extra property quote and trailing JSON commas. The
same-page calendar fallback is accepted only when it contains a bounded title
and exact local start timestamp; any other malformed structured data is omitted.
Only Schema.org event types are accepted, and the site's technical publisher
identifier is never rendered as a venue.
For `Sand Memories`, the recovered `Castell` venue is rendered as the
confirmed meeting point `Castillo de Guardamar`; the organizer contact address
is not treated as the event venue.

Agenda failure or malformed event details omit the optional `📅 События`
section. Cultura Guardamar is not used because its current site has a
certificate mismatch and placeholder content.

The official monthly municipal poster may additionally supply explicit event
type or medium, time range, and place through the bounded snapshot defined in
ADR 0012. Missing time does not exclude an otherwise valid event; it is simply
not rendered. Missing facts are never inferred.

## Approved official holiday calendar

BOE supplies the annual national and autonomous-community classification;
DOGV supplies the final Comunitat Valenciana calendar and the two Guardamar
local holidays proposed by the municipality. The bot stores only the final
published dates, concise reviewed Russian names, and legal scope. It does not
derive transfers, use commercial calendar sites, or carry local dates into an
unreviewed year. The same calendar powers both the holiday section and the
Wednesday-market move. No runtime request, cache, or recurring synchronization
is needed.

## Approved Wednesday market

The official Ayuntamiento markets page identifies `Mercadillo de los
Miércoles`, and the official Turismo Guardamar page states that it occurs
every Wednesday at parking La Redonda and adjacent streets. The digest uses
this stable weekly rule locally. The 2023 municipal ordinance defines customer
hours as `07:00–13:30` from June through September and `08:00–13:30` during
the rest of the year. It also states that a market falling on a holiday
Wednesday moves to the preceding Tuesday. The bot applies that rule using a
small annually reviewed official Guardamar holiday calendar; it makes no
runtime calendar request. Unsupported years omit the market rather than guess.
On the resulting Tuesday or Wednesday market date, the bot checks only fresh
timestamped text from `@AlcaldeGuardamar`. The market is
hidden only for an explicit, exactly dated cancellation or move whose source
quotation passes deterministic validation. If this check is unavailable, the
market is omitted for that day.

## Campo de Guardamar Sunday market

The market operator's published page identifies the location as
`Camino del Raso, 15` and the Sunday hours as `07:00–16:00`. The digest names
it `Рынок Campo de Guardamar`. This is an explicit product exception to the
public-authority-only preference: the schedule comes from the market itself,
not a municipal listing. No trustworthy cancellation feed was found, so the
bot does not infer holiday moves, weather closures, or cancellations and does
not apply the `@AlcaldeGuardamar` check to this market.

## Municipal monthly agenda

`https://guardamarturismo.com/agenda-cultural/` is an official Turismo
Guardamar page. Its monthly HTML program is the primary record. The linked
Ayuntamiento MUPI may contain additional activities. ADRs 0012 and 0028 define
the bounded text-first municipal catalog.

At 05:10, one bounded request checks the official monthly text and poster URL.
Changed text is converted once through Gemini into structured source-language
facts; unchanged text uses the existing facts. A new poster URL downloads the
image once and performs two independent structured Vision readings. Only
facts agreeing on key fields survive, and HTML text wins any duplicate or
conflict. The image is not downloaded daily. The poster-declared month must
match the month in its official filename. The bot stores a bounded catalog containing the
poster month, explicit next-month previews, and still-relevant facts from the
previous snapshot whose dates fall within the current day plus seven days.
This prevents an early next-month poster from erasing the final days of the
current program. The digest merges these facts with the separate local Agenda
Guardamar catalog and removes duplicates.

The monthly page is not assumed to contain complete patronal or festival
programmes. A separate bounded first-party Turismo WordPress adapter reads one
recent-post metadata index and considers at most three current-year
programme-shaped Spanish articles whose title/excerpt contains a relevant
explicit date. The dedicated Fiestas del Campo article remains on its existing
narrow deterministic/poster path and is excluded from the generic adapter.
For every other candidate, unchanged version-3 `modified` state reuses the
last verified facts; a changed/new article fetches one bounded detail page and
runs the existing evidence-bound official-text extractor. The raw WordPress
body is also scanned deterministically for dates that lead semantic content
blocks. Each date section includes its date-leading block and following
paragraph/list/heading text until the next explicit date. Every such date from
today through the next 44 days must have an extracted event starting exactly on
that date. If the first extraction misses one or more required dates, one
targeted bounded recovery sends only the missing date sections through the same
official-programme text extractor. Recovery facts outside the requested missing
dates are discarded. An article that is still incomplete is rejected. A broad
date-range event cannot satisfy multiple explicit occurrence dates. Version-1
and version-2 generic programme facts are not trusted after this recovery
upgrade and are revalidated once. The article must still yield at least two
validated programme events overall. The adapter is text-first: it does not OCR
arbitrary article images. Temporary source/model failures retain only
compatible last-good version-3 facts.

Dated Monday library film rows in the same official Turismo `CINE` text are
also read deterministically on every existing page refresh, including when the
text hash is unchanged. A row may contribute its concrete film title, duration,
age guidance, short genre, venue, and explicit admission/capacity without a
new request or model call. The separate official Biblioteca catalog supplies
its concrete title and short source-grounded synopsis. Both catalogs merge
into one ordinary Event; explicit duration suppresses a potentially rounded
library calendar end time in the shared renderer. Optional fact fields are
additive in the existing normalized snapshot, so older snapshots remain valid.
The source's `Entrada libre hasta completar aforo` retains its precise access
meaning as `Бесплатно · до заполнения зала`; a generic capacity label is only
a fallback. Legacy official-cinema snapshots with the deterministic source
marker, free price and limited-capacity flag recover that same exact condition
on read. Venue labels and source-confirmed physical addresses may be
stored separately, so an address can power the map link without replacing a
recognizable venue name. Distinct meeting points and supplementary schedule
notes are optional independent facts. Grouped programme children use the same
detail rendering as other events, with no new provider or morning request.

Operator-reviewed corrections — exact Russian titles, per-poster reviewed
occurrences with their known-bad-OCR drop filter, and bounded day-of
schedule rules — live in the validated packaged data file described by ADR
0039. Monthly poster review edits that file only; a defective file is
rejected whole at load and the digest falls back to uncorrected source
facts, while the test suite validates the committed file on every run.

During a temporary source outage, the last valid snapshot remains eligible
until its covered period ends. Generated title-only Russian translations are
kept only in the bounded separate cache defined by ADR 0029; the catalog keeps
the exact source-language fact. Exact operator-reviewed translations for a
small bounded set of independently verified programme titles take precedence
over generated cache entries, so an LLM outage cannot restore an untranslated
or editorially incomplete heading.
If the snapshot is corrupt, it is never used; the bot rebuilds it from a valid
official HTML page and JPEG, PNG, or WebP poster when possible.
If a newly validated poster cannot be written to local storage, its events
remain usable for the current run, the operator receives a diagnostic, and
the next run retries the refresh.
Routine facility hours and municipal services, including the mobile ecopark,
are not eligible for the event section.

For the July 2026 poster, the accompanying official text agenda is the
reviewed authority for the exhibition `Entropía`: painting by Conchi Montes,
3–29 July, `08:00–14:00` on weekdays, at Biblioteca Pública Municipal. A
small poster-specific correction repairs an incomplete or inaccurate stored
OCR record at read time without repeating OCR or changing unrelated events.
The same reviewed record remains eligible through 29 July if the agenda page
switches its poster link to August before the July exhibition ends.

For `Mediterráneo, el lenguaje del agua`, the August 2026 official text agenda
is the reviewed authority: paintings and sculptures by Humberto Valencia
Giraldo, 19 June–14 August, in Sala de exposiciones Casa de Cultura. The
current official August programme gives visits as `09:00–20:00` Monday through
Friday and `10:00–14:00` Saturday; the event is
omitted on Sunday because no Sunday visiting time is published. The comma in
the official title is preserved. These are event-specific hours, not inferred
Casa de Cultura opening hours.

The same reviewed programme identifies the 6 August `DIXI PROJECT` item as a
journey through 1920s music at Plaça dels Llauradors, and `KIKI MORENTE` as a
22:00 flamenco concert within `VI Estival al Castell`, regular price `25 €`.
The digest preserves the Google Maps label `Plaça dels Llauradors`. Because
Google Maps resolves a text search for the square to a similarly named dental
clinic, this venue alone links to the verified square coordinates
`38.0921948,-0.6552320` instead of a name search.
It also identifies `BALL D’ESTIU` as a free `21:30–23:30` summer dance session
inside Parque Reina Sofía at Auditorio Orquesta GÚMAR. The digest uses exact
reviewed Russian titles for these bounded occurrences, renders the park before
the auditorium in the venue label, and does not infer free admission for DIXI
PROJECT because the official programme publishes no price or admission claim.
The lower-priority dated municipal-programme reproduction supplies `Labores a
la fresca` as a free handicraft gathering, not a generic work activity.

The reviewed August 2026 youth-workshop cards are separate occurrences, not a
continuous date range: K-Pop/TikTok on 1 August and music workshops on 8, 15,
22 and 29 August, each `19:00–21:00` at Centro Social Juvenil. A correction
tied to the exact August poster prevents a finished workshop from remaining
active on later dates. Todo Cultura Vega Baja's dated reproduction of the
Ayuntamiento programme corroborates the four music-workshop times; it is a
secondary review source, not an automated cancellation authority. Its dated
8 August record explicitly limits the drums workshop to ages 12–30 and gives
registration at Centro Social Juvenil or WhatsApp `609 00 67 54`. It does not
state a price, so the digest makes no free-admission claim.

Todo Cultura is queried through its bounded public WordPress REST API during
the municipal refresh. One metadata page advances a five-minute-overlap cursor
and maintains a rolling window from today through six days ahead. Up to six
dated detail candidates are downloaded in at most two size-bounded batches of
four records, while at most three programme inputs reach structured extraction.
The event card's own title/permalink classifies locality before detail: cards
whose identity names only another municipality are discarded even when their
article body mentions Guardamar; an explicit multi-city card remains eligible
only when Guardamar is one of its primary localities. Unknown standalone cards
fail closed.

Attributed `Ayuntamiento de Guardamar` / `agenda municipal` reproductions keep
the existing dated-section extractor and participation/admission enrichment.
A local standalone card uses a separate Guardamar-scoped structured extractor
so another city's occurrence cannot be promoted merely from campaign text.
Within the same rolling date, explicit local and more date-specific cards are
considered before broad programme copies, while the existing usefulness score
still favors actionable participation/admission detail. Already covered dates
are shared across duplicate programme reproductions, while a later
`modified_gmt` reopens the affected date. Metadata without a discoverable date
does not trigger a full download. Supplemental results have lower merge
priority than official municipal HTML and Agenda Guardamar; absence from Todo
Cultura never means cancellation.

A nonempty model response is no longer sufficient to mark a programme date
covered: each independent timed row must have a normalized occurrence. A
strict quoted-activity fallback covers plainly dated youth cards. When a
source row itself names later same-weekday dates, those dates are expanded
within the 44-day catalog horizon after validating month and weekday. This
preserves the 19/26 September Punto Geodésico routes even though the ordinary
collection window is only seven days. The row-level evidence is retained
without advancing a failed programme cursor.

The September 2026 Campo festival exposed a separate gap: the monthly poster
only gave a tiny inset, while the official Turismo WordPress article and its
full-size poster gave the exact 12–13 September programme. The bounded public
article reader records the explicitly dated items; its text wins over a vision
candidate that conflates the 19:00 parade with untimed fireworks. A model or
poster failure may omit supplementary venue detail but cannot remove the
complete article-stated programme.

Multi-day library exhibitions are eligible only on weekdays when the official
library opening-hours page says the venue is open. A date span alone is not
evidence of Saturday or Sunday access. See the dated source audit in
`research/2026-09-12-guardamar-event-coverage.md`.

The cursor, at most 100 lightweight candidates and at most 45 covered dates
are stored inside the existing atomic municipal catalog. They advance only
after successful structured normalization and catalog replacement. During the
10:10–10:40 beach window each event catalog gets at most one independent late
refresh attempt, allowing new facts to be retained without making event-only
changes trigger a second public digest.

An explicit regular admission price or `entrada libre` in that same bounded
programme may enrich only the event named by the preceding event row. Matching
needs either two shared meaningful words or one shared non-generic word, so a
bare `Concierto` cannot borrow another occurrence's price. Explicit dates and
session time further restrict the match; a timeless admission is withheld
when more than one matching session exists. An HTTPS purchase
link in the same admission paragraph is retained only for the reviewed Agenda
Guardamar and Giglon hosts, with user information and explicit ports rejected
by the same validator before write and after read. The existing Agenda Guardamar occurrence remains
the authority for its dated purchase link.
The primary Turismo HTML uses the same deterministic event-local rules for its
own explicit `Precio`, `Entrada libre`, `Acceso libre`, and ticket links. A link without a
published price is rendered simply as `Билеты`; no price is inferred.
An explicit `Inscripciones:` or `Reservas:` row with a valid phone number may
similarly enrich only a title-matched occurrence on the requested date. A
generic information contact is not registration, and missing price is not
interpreted as free admission. Registration, participation, capacity and
bounded admission-evidence facts are stored in the small normalized catalog so
reviewed occurrence corrections and month transitions do not discard them.
Routine Centro Social Juvenil opening sessions remain excluded. Dated
multi-day campaigns and public service activities are retained as active
entries through their verified end date, even without a daily start time; an
undated or placeless record is still omitted. Ticket-sale windows are retained
when the source supplies their dates, hours, venue, price, or purchase details.

Text extraction also returns one exact source quotation for every event. The
quotation must occur in the bounded input and support every meaningful title
word plus each returned date, time and place. This permits a self-contained
title to retain an explicit event kind, tribute or benefit purpose without
accepting unsupported editorial details. A corroborating lower-priority title
may replace a sparse title only as an identity-preserving superset; conflicts
still keep the higher-priority title. The raw article is not stored; only
bounded normalized admission evidence survives. Poster OCR continues to
require two blind agreeing readings instead.

Agenda Guardamar detail pages are the authoritative source for their own
sessions and ticket links. One page may contain several dated sessions; each
is stored separately. Only an HTTPS purchase URL on the Agenda Guardamar host
whose date and time match that occurrence is retained. The regular price or
explicit free admission may be shown; the parser accepts the site's observed
`Regular`, `Precio`, and Valencian `Preu` labels, while discounts remain on the official
purchase page. A detail page that
publishes `Duración 2 horas aprox` may supply the displayed end time for that
session, following the approved compact product wording.

For 7 August 2026, the official municipal programme and Agenda Guardamar are
two records of the same `22:00` Alice Wonder concert. Exact reviewed title and
date matching keeps one digest item with `Castell de Guardamar`, the `Soulost`
tour and VI Estival al Castell context, regular price `25 €`, and the official
occurrence-specific ticket URL. The ticket platform's technical venue label
`Estival Al Castell Aforo Ampliado` is not rendered as a public place.

The reviewed August poster schedules the youth night walks at
`22:15–00:15` on 7, 14, 21 and 28 August. The dated programme corroborates an
8 km route for participants aged 12–30, free participation, and a start point
communicated by the instructor. It also explicitly publishes required sports
shoes, water and a flashlight, limited capacity, and registration phone
`633 14 57 75`. The phone is independently consistent with the official
Turismo Guardamar youth-programme contact; the malformed email printed by the
secondary reproduction is not used. The departure instruction is rendered as
plain text, not as an invented Google Maps destination. For the independently
reviewed children's library workshop, the published reservation phone and
WhatsApp may be shown with its limited capacity. A generic `Más información`
contact for Centro Social Juvenil is not relabelled as registration for a
workshop. The tennis tournament retains its
verified 1–8 August period and Polideportivo venue without an invented daily
time because none is published by the accepted sources.

## Retired Policía Local traffic source

The reviewed Policía Local festival page remains useful historical evidence,
but repeated production use showed that it is not a dependable current traffic
feed. The only deterministic resident-facing value came from one reviewed
festival document; later road closures were not maintained there consistently.

The bot therefore makes no scheduled Policía Local request, no longer carries
traffic-specific Morning Digest models/rendering, and no longer sends unknown
traffic pages through Gemini/OpenRouter. Historical source research and
superseded ADRs are retained so the source is not accidentally reintroduced
without new evidence of a stable, current machine-readable publication path.

The Mayor channel uses Telegram's bounded public HTML preview and requires no
bot membership or user session. Besides scheduled-market exceptions, one
post-07:30 check recognizes only explicit red/prohibited or yellow/permitted
bathing transitions. A morning check also recognizes explicitly dated
`Fiestas de Barrio` clauses with a published time, named participating
urbanizations and `Ubicación`, including the 31 July 2026 event at
`parque C/ Berlín`, independently confirmed by the municipal poster and the
official Turismo Guardamar text agenda. The user-facing location expands `C/`
to `улица` and retains `парк`.

The same bounded morning read may accept a late general municipal event only
when one fresh post has an invitation, a quoted title, an explicit day and
month matching today, a valid start time, an explicit place and a consistent
weekday or year when either is published. The independently reviewed
11 August 2026 post for `SERES FASCINANTES DEL MEDITERRÁNEO` supplies the
12 August `09:00–13:00` environmental workshop at Playa Centro / Paseo
Marítimo. Its exact reviewed Russian title is `Удивительные обитатели
Средиземного моря`. Posts about completed activities and announcements with
missing fields remain ineligible. Other Mayor posts are not treated as events.
Known causes use a fixed
Russian vocabulary; no AI inference is used. The Mayor adapter accepts only
bounded HTML from its exact official HTTPS host. A valid HTML page without
recognizable timestamped channel messages is a source failure, not proof that
there are no updates. The MVP does not scrape Facebook.

## Selection criteria

- Prefer the responsible public authority.
- Confirm geographic coverage and update frequency.
- Prefer stable structured feeds over scraping.
- Check attribution, usage limits, and terms.
- Reject sources that require heavy processing or frequent polling.
- Define stale-data behavior before relying on a source.

## Source record template

For each evaluated source, record:

- owner and URL;
- information supplied;
- geographic scope;
- authority and reliability;
- format and update pattern;
- access or attribution constraints;
- failure and stale-data behavior;
- MVP decision and rationale.
