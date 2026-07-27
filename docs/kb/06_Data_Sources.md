# Data Sources

The implemented providers are AEMET, Guardamar's public SafeBeach page,
Agenda Guardamar, and the official Policía Local traffic page. Each morning
run requests current data directly; it does not read a source cache.

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
| Policía Local Guardamar | Explicit traffic restrictions | High for direct official notices; publication is irregular | One bounded official HTML page | Yes |
| Agenda Guardamar | Official ticketed events occurring today | High for listed Ayuntamiento events | Bounded HTML index plus Schema.org event details | Yes |
| Turismo Guardamar municipal agenda | Broader cultural program from the linked monthly Ayuntamiento poster | High; official but image-based | Daily link check plus change-triggered Gemini Vision extraction | Yes |
| Ayuntamiento Wednesday market page and official holiday calendar | Weekly market at parking La Redonda, including holiday moves | High; official recurring schedule and annual calendars | Small reviewed local calendar rule | Yes |
| `@AlcaldeGuardamar` public channel | Explicit market cancellations or exceptional moves | Operational municipal channel; text must be mechanically grounded | Market-day bounded HTML check with validated Gemini extraction | Yes, narrow role |
| Campo de Guardamar market website | Sunday market at Camino del Raso, 15 | Operator-published schedule; no authoritative cancellation feed found | Local Sunday rule, `07:00–16:00` | Yes, explicit product exception |
| Community or commercial sources | Gap filling only | Variable | Varies | No by default |

## Approved AEMET products

| Product | Selection | MVP use |
| --- | --- | --- |
| Municipal daily forecast | Guardamar municipality `03076` | Today's temperature range, most significant sky condition, and one later-day wind comparison |
| Conventional observation | Rojales station `7261X`, listed by AEMET as 5.3 km from Guardamar | Current temperature and wind, only when no more than three hours old |
| CAP warnings | Comunitat Valenciana area `77`, filtered to `Litoral sur de Alicante` | Warnings active now or beginning later today |
| Beach forecast | Centro / La Roqueta `0307605` | Today's forecast water temperature when SafeBeach has no current value |

The AEMET API returns a metadata response containing a separate product
download URL. Both requests are bounded by time and response size. The API key
is supplied through `AEMET_API_KEY` and must not be committed.

The four approved AEMET products are requested sequentially. This avoids a
burst of concurrent metadata requests and respects the service's observed rate
limits at negligible cost for one daily run. The mandatory daily forecast gets
one delayed retry after a transient failure; optional products remain
best-effort.

The CAP warning download may be an XML document, ZIP archive, or TAR archive.
All supported containers are parsed in memory with compressed and uncompressed
size bounds.

The nearby Rojales origin remains explicit in project documentation, but its
location label is omitted from the compact message. AEMET forecast wind may
provide one later-day comparison with current wind. No source footer or source
label is shown in the user-facing digest.

## Approved SafeBeach data

Guardamar municipality links to
`https://info.safebeach.es/guardamar-del-segura`. The public page embeds
structured records for Guardamar beaches. The adapter selects
`Platja Centre / Babilònia` and reads only its name, activity state,
service-ended state, flag color, water temperature, wind speed, and wind
direction.

Only its active, non-ended lifeguard record is eligible. SafeBeach supplies
the flag, water temperature, and current beach wind when present. The
user-facing digest renders both current and forecast wind in metres per
second. The AEMET daily wind remains the compact forecast after the arrow. If
SafeBeach water temperature is
missing, the digest may use today's AEMET forecast for Centro / La Roqueta.
AEMET never supplies or implies a flag. Unknown colors, ended service, missing
data, request failure, or schema failure leave the affected value as `—` and
never block the weather digest.

## Approved Agenda Guardamar data

`https://www.agendaguardamar.com/` identifies the Ayuntamiento as the site
operator and publishes event detail pages with Schema.org `name` and
`startDate`. The adapter reads a bounded programming page, follows at most
twelve same-host event links, and returns at most two events whose local date
is today. It performs no media processing and stores no event history.

Agenda failure or malformed event details omit the optional `📅 События`
section. Cultura Guardamar is not used because its current site has a
certificate mismatch and placeholder content.

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

## Approved Policía Local traffic data

`https://policiaguardamar.com/cortecallefiestas.html` is an official Policía
Local page with an explicit festival restriction: from 15 through 29 July the
remaining approaches are closed and access to Centro de Salud and the bus
terminal is via C/ San Francisco. During that calendar window, the adapter
shows one fixed Russian traffic line only when all those facts are still
present together on the freshly fetched page.

The source is optional and irregular, not a live traffic feed. Changed,
ambiguous, missing, or out-of-window content omits the section. The linked
historical PDF is not used as current data because it has no current year and
describes different routing. No PDF processing, Facebook scraping, cache, or
inference is used.

The Mayor channel uses Telegram's bounded public HTML preview and requires no
bot membership or user session. Its MVP role is limited to scheduled-market
exceptions. The MVP does not scrape Facebook.

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
