# Data Sources

The implemented providers are AEMET, Guardamar's public SafeBeach page,
Agenda Guardamar, the official Policía Local traffic page, and the public
`@AlcaldeGuardamar` channel. The 07:30 run requests current data directly. A
later verified beach update permits one fresh complete collection; no
source-response cache is used.

The remaining municipal, police, and seasonal publisher roles are mapped in
`research/2026-07-27-guardamar-municipal-source-map.md`. Except for the
approved Agenda Guardamar adapter, they are not implemented until their exact
official endpoints and lightweight access methods are validated.

| Source category | Purpose | Expected reliability | Update style | MVP |
| --- | --- | --- | --- | --- |
| AEMET OpenData | Guardamar forecast, nearby observation, official weather warnings | High; responsible Spanish authority | Structured API; API key required | Yes, first slice |
| Official marine service | Sea state and relevant marine warnings | High for its jurisdiction | API or published feed | Yes |
| SafeBeach public Guardamar page | Active beach flags and sea temperature | High when municipal lifeguards actively maintain it | Small structured payload embedded in the public page | Yes |
| Civil protection or emergency authority | Safety warnings | Highest priority | Alert feed or official publication | Yes |
| Policía Local Guardamar | Explicit mobility restrictions | High for direct official notices; publication is irregular | One bounded official HTML page and reviewed linked document | Yes |
| Agenda Guardamar | Official ticketed events occurring today | High for listed Ayuntamiento events | Bounded HTML index plus Schema.org event details | Yes |
| Turismo Guardamar municipal agenda | Broader cultural program from the linked monthly Ayuntamiento poster | High; official but image-based | Daily link check plus change-triggered Gemini Vision extraction | Yes |
| Ayuntamiento Wednesday market page and official holiday calendar | Weekly market at parking La Redonda, including holiday moves | High; official recurring schedule and annual calendars | Small reviewed local calendar rule | Yes |
| `@AlcaldeGuardamar` public channel | Explicit market exceptions and bathing-status transitions | Operational municipal channel; text must be mechanically grounded | Bounded market check or one check after SafeBeach retries | Yes, narrow role |
| Campo de Guardamar market website | Sunday market at Camino del Raso, 15 | Operator-published schedule; no authoritative cancellation feed found | Local Sunday rule, `07:00–16:00` | Yes, explicit product exception |
| Community or commercial sources | Gap filling only | Variable | Varies | No by default |

## Approved AEMET products

| Product | Selection | MVP use |
| --- | --- | --- |
| Municipal daily forecast | Guardamar municipality `03076` | Today's temperature range, most significant sky condition, one later-day wind comparison, and high-probability remaining rain |
| Conventional observation | Rojales station `7261X`, listed by AEMET as 5.3 km from Guardamar | Current temperature and wind, only when no more than three hours old |
| CAP warnings | Comunitat Valenciana area `77`, filtered to `Litoral sur de Alicante` | Warnings active now or beginning later today |
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

The CAP warning download may be an XML document, ZIP archive, or TAR archive.
All supported containers are parsed in memory with compressed and uncompressed
size bounds.

The nearby Rojales origin remains explicit in project documentation, but its
location label is omitted from the compact message. AEMET forecast wind may
provide one later-day comparison with current wind. No source footer or source
label is shown in the user-facing digest.

The municipality forecast supplies precipitation probabilities by period. At
collection time the adapter considers future periods, falling back to one that
still spans the current hour when no future period exists. The digest shows
only the highest eligible probability when it is at least 75%, together with
AEMET's period. Lower or malformed values are omitted.

## Approved SafeBeach data

Guardamar municipality links to
`https://info.safebeach.es/guardamar-del-segura`. The public page embeds
structured records for Guardamar beaches. The adapter selects
up to three active records. It prioritizes `Platja Centre / Babilònia`,
`Platja La Roqueta`, and `Platja dels Vivers`, then fills missing slots from
`Platja del Montcaio`, `Platja del Camp`, and `Platja de les Ortigues`.
Fallback records retain their own beach names and are never treated as
measurements for a missing preferred beach. The adapter reads only name,
activity state, service-ended state, update time, and flag color, plus
jellyfish presence, and Centre water temperature, sea state, wind speed, and
wind direction.

Only active, non-ended lifeguard records are eligible. A replacement requires
at least one flag with a plausible update time. A missing timestamp omits only
that beach and does not block another valid one. Missing beaches are omitted;
their colors are never inferred. Optional sea, wind, and jellyfish fields
never block publication. SafeBeach supplies
individual nearby flags and current beach wind when present. Its Centre water
temperature and sea state are fallbacks when the AEMET beach forecast omits
those values. Flags are never averaged or generalized; they are grouped by
color on separate compact lines in the message. Jellyfish are shown only for
beaches with an explicit positive SafeBeach value, never as a daily
reassurance. The
user-facing digest renders both current and forecast wind in metres per
second. The AEMET daily wind remains the compact forecast after the arrow.
Today's AEMET Centro / La Roqueta forecast is the primary representative water
temperature and sea state. Its two sea-state periods are shown once when equal
or as one compact transition when they differ. AEMET never supplies or implies
a flag. Unknown colors, ended service, missing data, request failure, or schema
failure omit the affected optional value and never block the weather digest.

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

SafeBeach is requested only inside the conservative local season from 20 June
through 14 September, inclusive. Outside this window all operational
SafeBeach values are omitted, preventing a stale active record from exposing a
winter flag. This is an operator-selected safety window, not a claim that the
municipality uses immutable annual service dates. AEMET sea temperature and
wave forecast remain available year-round.

## Approved Agenda Guardamar data

`https://www.agendaguardamar.com/` identifies the Ayuntamiento as the site
operator and publishes event detail pages with Schema.org `name` and
`startDate`, optional `endDate`, and `location`. The adapter reads a bounded
programming page, follows at most twelve same-host event links, and returns at
most two events whose local date is today. It performs no media processing and
stores no event history.

Agenda failure or malformed event details omit the optional `📅 События`
section. Cultura Guardamar is not used because its current site has a
certificate mismatch and placeholder content.

The official monthly municipal poster may additionally supply explicit event
type or medium, time range, and place through the bounded snapshot defined in
ADR 0012. Missing time does not exclude an otherwise valid event; it is simply
not rendered. Missing facts are never inferred.

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
Guardamar page. Its linked Ayuntamiento monthly poster can contain activities
missing from the HTML text. ADR 0012 defines the implemented bounded poster
snapshot.

The morning run checks for a changed official poster URL. A new image is downloaded with
strict size bounds, hashed, and processed once through Gemini Vision into
structured source-language event facts. The bot stores a bounded snapshot for
the current month and explicit next-month previews. It merges those events
with the separate official Agenda Guardamar result and removes duplicates.

During a temporary source outage, the last valid snapshot remains eligible
until its covered period ends. Generated Russian translations are not stored.
Routine facility hours and municipal services, including the mobile ecopark,
are not eligible for the event section.

For the July 2026 poster, the accompanying official text agenda is the
reviewed authority for the exhibition `Entropía`: painting by Conchi Montes,
3–29 July, `08:00–14:00` on weekdays, at Biblioteca Pública Municipal. A
small poster-specific correction repairs an incomplete or inaccurate stored
OCR record at read time without repeating OCR or changing unrelated events.
The same reviewed record remains eligible through 29 July if the agenda page
switches its poster link to August before the July exhibition ends.

## Approved Policía Local traffic data

`https://policiaguardamar.com/cortecallefiestas.html` is an official Policía
Local page linking the reviewed festival traffic PDF. The supported 22–29 July
measure closes Molivent, routes access to Centro de Salud and the bus terminal
through La Redonda, and also permits light vehicles through San Francisco
until 23:30.

The adapter downloads the small linked PDF and accepts this known rule only
when its SHA-256 matches the reviewed document. It does not run PDF extraction
or OCR. A changed document is omitted pending review. Unknown official HTML
notices may use ADR 0011's fail-closed structured Gemini fallback. Documents
normalize into independent active measures; at most two compact lines reach
the digest. The source remains optional and irregular, not a live feed, and no
traffic cache is kept.

The Mayor channel uses Telegram's bounded public HTML preview and requires no
bot membership or user session. Besides scheduled-market exceptions, one
post-07:30 check recognizes only explicit red/prohibited or yellow/permitted
bathing transitions. Known causes use a fixed Russian vocabulary; no AI
inference is used. The MVP does not scrape Facebook.

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
