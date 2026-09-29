# 2026-09-29 — Avanza planner outage and GVA GTFS Guardamar gap

## Question

Why did the accepted Alicante, Elche and Zenia Boulevard timetable cards stop
refreshing after the successful 28 September morning transport sync, and can the
official Generalitat GTFS replace the Avanza/Costa Azul planner?

## Production Avanza evidence

The 05:00 transport sync on 28 September 2026 successfully accepted and stored
live Avanza/Costa Azul schedules. A later diagnostic on 29 September queried
Guardamar -> Alicante for 28, 29 and 30 September through the same public
planner flow:

- planner: `https://regular.autobusing.com/info?empresa=costa-azul&locale=es`;
- form action: `https://regular.autobusing.com/info/horarios`;
- every POST returned HTTP 200 and the same 7,183-byte HTML page;
- the page contained `ESTACION CERRADA TEMPORALMENTE`;
- the page contained none of the requested origin, destination or exact date;
- it contained no schedule table rows;
- the existing strict parser rejected every response as
  `Alicante planner result does not match requested route/date`.

This rules out a one-date calendar boundary, a route-specific Alicante failure,
HTTP 429 and a timeout as explanations for the observed response. It also means
the parser is currently behaving correctly: the returned HTML does not prove a
schedule and must not be accepted.

The same source failure affected the Avanza-backed Alicante, Elche and Zenia
adapters. Orihuela, which uses Bus Sigüenza, refreshed normally.

## Official GVA GTFS re-evaluation

The official Generalitat Valenciana interurban bus GTFS was downloaded again on
29 September 2026. The archive was structurally valid:

- size: 14,114,035 bytes;
- stops: 5,249;
- routes: 263;
- trips: 6,363;
- stop_times: 132,385;
- calendar_dates: 4,557.

The four matched Guardamar del Segura stops were:

- `5090010114` — Pinomar [Guardamar del Segura];
- `5090010115` — N-332 pk 67+300 ascendente - Urb. La Rosa;
- `5090010116` — Estació Autobusos Guardamar del Segura;
- `5090060103` — Guardamar – Restautant Xinés [Guardamar del Segura].

Every one of these stops had **zero linked trips**. No GTFS route name contained
`Guardamar`, no trip in the archive touched any matched Guardamar stop, and
there were zero active Guardamar trips on both 2026-09-29 and 2026-09-30 even
though 394 and 397 service IDs respectively were active.

This is not a matcher or service-calendar miss. The current published GTFS
contains the Guardamar stop records but does not contain usable Guardamar
service topology.

The gap conflicts with the current official CE-704 service description, which
states that the corridor is operational and includes, among others,
Alacant-Guardamar, Elx-Guardamar-Torrevieja and routes through La Zenia.
The GVA dataset itself says that it is generated daily and covers schedules up
to ten days ahead, while also warning that route information may not include
the latest changes.

Official references:

- https://dadesobertes.gva.es/va/dataset/tra-hyr-atmv-horaris-i-rutes
- https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096

## Source decision from this probe

Do **not** use the current GVA GTFS as primary or fallback timetable input for
Guardamar intercity cards. A source that is structurally healthy but silently
contains zero Guardamar trips could turn missing source data into a false
"no service" interpretation.

Keep the existing accepted-snapshot fail-closed behaviour. A rejected live
response must preserve the last verified schedule rather than converting source
absence into cancellation.

This rejection is time-sensitive, not permanent. The GVA GTFS may be
re-evaluated only after a future raw archive actually contains trips linked to
Guardamar del Segura stops.

## New official-host finding

The current official Costa Azul homepage still exposes the interurban timetable
planner, but its links are inconsistent:

- the navigation link `Horarios interurbanos` points to
  `regular.autobusing.com`;
- the main `INFORMACIÓN HORARIOS` call-to-action points to
  `regular.autobusing.es`.

Both GET planner pages currently render the Avanza Movilidad Levante timetable
form. The repository adapter is allowlisted only for `.com`.

This creates a narrow next hypothesis: the operator may have moved or partially
migrated the active planner to `.es`, while the old `.com` endpoint still
renders the form but returns the temporary-closure page on POST.

Official Costa Azul page:

- https://costazul.net/

## Next probe

Before changing application code, issue the same bounded
Guardamar -> Alicante POST for the same exact date against **both**
`regular.autobusing.com` and `regular.autobusing.es`, with independent
cookie jars and otherwise identical fields.

Interpretation:

- `.es` returns a validated route/date/table while `.com` returns
  `ESTACION CERRADA TEMPORALMENTE`: change only the approved planner host and
  add regression coverage;
- both hosts return the temporary-closure page: treat this as an operator-side
  planner outage/configuration state; do not weaken validation or add retries;
- both return valid schedules: the earlier outage was transient; decide whether
  one bounded later attempt is justified only from repeated production
  evidence;
- either host changes form/action/field shape: inspect that exact contract
  before implementation.

No production timetable code should change until this comparison is observed.

## Dual-host production comparison

A production probe then repeated the same bounded Guardamar -> Alicante POST
for 28, 29 and 30 September against both official planner hosts,
`regular.autobusing.com` and `regular.autobusing.es`, using independent cookie
jars and otherwise identical form data.

The result was identical on all six requests:

- initial planner HTML: 6,919 bytes;
- form action: `/info/horarios` on the same host;
- POST result: 7,183 bytes;
- `ESTACION CERRADA TEMPORALMENTE`: present;
- requested origin, destination and exact date: absent;
- schedule table rows: zero;
- strict parser: rejected as route/date mismatch.

Therefore the `.es` hostname is **not** a working replacement for `.com`.
Do not change `PLANNER_HOST` or add a second-host fallback. Both public planner
front doors currently expose the same unavailable backend state.

The temporary-closure wording is also historically known to appear on the
Autobusing family when the online sales/planner backend is unavailable even
while services continue. That evidence is contextual only; the current
production conclusion remains based on the six direct probes above.

## Official app backend candidate

Costa Azul's current official Android/iOS app is a separate candidate source.
The current Android package is `com.embarcadero.costazul`; the public store
listing says it contains urban and interurban lines, stop maps and real-time
arrival predictions. Version 3.2.0 was updated in October 2025.

Official/first-party references:

- https://costazul.net/app-ios-android/
- https://play.google.com/store/apps/details?id=com.embarcadero.costazul
- https://apps.apple.com/es/app/costa-azul/id1156441547

This is useful evidence that Costa Azul/Avanza operates another machine-readable
transport backend independently of the broken Autobusing timetable form.
However, no app endpoint has yet been accepted for runtime. The next research
step is to identify the app's public backend host and request contract, then
probe it read-only for Guardamar interurban data before any architecture or code
change.

The app binary itself must not become a runtime dependency. APK inspection, if
used, is research-only to discover public host/URL strings that the official app
already calls.


## Costa Azul APK first static-analysis probe

The exact Android 3.2.0 arm64 XAPK was downloaded and verified before
inspection:

- file: `Costa+Azul_3.2.0_APKPure.xapk`;
- size: 58,602,125 bytes;
- SHA-256:
  `0bf5a10d8dfdb73b732e407bab5571753f2609c23f1fa862706f2872d2e3414f`;
- split set: base APK plus `config.arm64_v8a.apk` and
  `config.xxhdpi.apk`.

A first broad ASCII `strings` pass did **not** reveal an application-specific
HTTP(S) backend. The explicit URL list contained Android/Google/AdMob/Firebase
SDK endpoints and placeholders only.

The same binary scan did reveal application-specific Delphi/FireMonkey-era
transport/database strings:

- `nombreparada`;
- `lineainterurbana`;
- `Database=C:\\proyectos\\costazul2\\datos.s3db`.

This first-pass interpretation was tentative. Deeper inspection below proved
that `datos.s3db` is shipped inside the APK but is **not** the transport data
model; it is unrelated legacy/demo data. The useful transport contract lives in
the native library's UTF-16LE strings.

The first probe is therefore insufficient to reject the app-backend candidate:
Delphi native code commonly stores Unicode strings outside the simple ASCII
surface, and the probe also truncated its broad relevant-string output after
700 sorted lines.

Next static-analysis step:

1. inspect the actual XAPK/APK entries for SQLite/database/config assets;
2. detect embedded `SQLite format 3` payloads and inspect schema read-only;
3. extract UTF-16LE as well as ASCII strings from native libraries;
4. search the complete, untruncated string set for host/URL/request fragments
   around transport-specific identifiers;
5. only after a concrete host/request contract is found, perform a bounded
   read-only network probe.

No APK-derived source should enter runtime until the remote endpoint is shown
to be public, stable enough, and able to prove current Guardamar interurban
data.


## Costa Azul APK deep static-analysis result

The uploaded XAPK was unpacked directly. Its base APK contains
`assets/internal/datos.s3db` (73,728 bytes), and the arm64 split contains one
53.5 MB native library, `lib/arm64-v8a/libcostazul.so`.

### Embedded SQLite asset is unrelated

The shipped `datos.s3db` is a valid SQLite database, but its schema is not
transport-related. Its tables are `Emocion`, `Enfermedad`, `Paciente`,
`Sintomas` and `Usuario`, with old sample/legacy records. Treat the
`Database=C:\\proyectos\\costazul2\\datos.s3db` string as a leftover
development asset/connection, not as evidence of a usable timetable database.

### Native library exposes the actual transport HTTP contract

A complete native-string pass found only 19 full HTTP(S) URLs in
`libcostazul.so`. Apart from framework/site links, **all application transport
endpoints use the same clear-text host**:

`http://informedia.com.es/costazul/`

No second/new transport API host, Avanza API host, Azure endpoint, Firebase
transport endpoint or HTTPS replacement is embedded in the current 3.2.0
native library.

The interurban endpoints and nearby request/response strings are:

- `json_interurbanas2.php?origen=`
  + `&destino=` + `&fecha=`; response keys nearby:
  `hora`, `hora_llegada`, `numero`.
- `json_paradasinterurbanas2.php?servicio=`
  + `&origen=` + `&destino=`; response keys:
  `codigo`, `hora`.
- `json_proximointer.php?parada=`; response keys:
  `Linea`, `Minutos`, `LineaDescripcion`.
- `json_paradasinter2.php` and
  `json_paradasinter2_v.php?origen=`; nearby stop-record keys:
  `abreviado`, `nombre`, `codigo`, `latitud`, `longitud`, `maquina`.
- `json_paradasinter_prox.php?latitud=`
  + `&longitud=` + `&pos=`; nearby keys:
  `abrev`, `parada`.

The same binary also contains urban-route endpoints such as
`json_proximo.php`, `json_paradas.php`,
`json_correspondencias.php` and `json_comollegar.php`, confirming that this
host was the application's general transport backend rather than an incidental
URL.

### Current-source assessment

The official Google Play listing still describes the app as providing urban
and interurban lines plus real-time stop predictions, and its October 2025
release note says the update added support for newer Android devices. The
official Costa Azul app page makes the same route/stop/arrival claim.

However, the current 3.2.0 binary still hardcodes only the legacy
`informedia.com.es` HTTP backend. Public search does not expose a replacement
endpoint, while recent App Store user reports from late 2025 say that lines fail
to load. Those reviews are corroborative only, not authoritative source status.

Direct current probing of the exact Informedia endpoints could not be completed
from the research environment because the web tool does not expose these raw
HTTP JSON URLs and the local analysis container has no external DNS. Therefore
the app backend is **not accepted** as a runtime source yet.

The next and only useful probe is a tiny direct network check from a normal
internet connection (Mac or production device) against the discovered
`json_paradasinter2.php` and, if alive, one exact
`json_interurbanas2.php` request. If the host is dead or responses are stale,
reject the app backend and stop this branch of research. If it returns current
Guardamar interurban data, then inspect freshness/date semantics before any code
change.

No runtime source, retry, dependency or scheduler change follows from APK static
analysis alone.


## Informedia backend liveness probe

A direct internet probe from macOS resolved `informedia.com.es` to
`82.223.26.19`.

The two interurban-stop requests:

- `http://informedia.com.es/costazul/json_paradasinter2.php`;
- the same endpoint with `?search=GUARDAMAR`;

both returned HTTP 200 with `text/html`, exactly 1,384 bytes, and an
Avanza-branded server-error page whose visible message is:

`ERROR 502 SERVICIO TEMPORALMENTE NO DISPONIBLE`.

By contrast, `json_noticias.php` still returned JSON successfully, but the
visible records were archival notices from 2020 and 2019, including the March
2020 COVID state-of-alarm notice and a December 2019 maintenance notice.

Conclusion: the host itself is alive, but the interurban transport API required
by the app is unavailable and the remaining live content is legacy/stale.
Reject the Informedia/app backend as a current Guardamar timetable source. Do
not add it as primary, fallback, health-check or retry target.

This also closes further APK reverse-engineering for runtime purposes unless a
future official Costa Azul app release embeds a materially different backend.

## Next official timetable candidates

Current public evidence points to two separate official layers that are more
promising than the failed planner/app backends.

1. The official Costa Azul interurban page still publishes the current route
   structure. Its June 2026 PDFs include updated route thermometers for L02,
   L39 and L139. L02 contains Guardamar, Alicante and Zenia Boulevard stops;
   L39 contains the direct coastal Guardamar/Elche corridor stops. These files
   prove current route topology, not departure times.

2. Generalitat's emergency CE-704 contract
   `CMAYOR/2025/24Y07/0012`, awarded to Avanza Movilidad Levante in March
   2026, includes an official technical document named
   `20260108_PROYECTO SIMPLIFICADO.pdf`. Generalitat's public summary confirms
   the corridor is operating and enumerates the new lines/frequencies,
   including Alacant-Guardamar, the weekend CC La Zenia variant and
   Elx-Guardamar-Torrevieja direct service.

The contract technical project is therefore the next source to inspect for
exact departure tables and seasonal/calendar rules. If it contains deterministic
schedules, a stable architecture may be possible without a fragile daily web
planner: keep reviewed timetable tables locally and use a lightweight official
change/version check, rather than parsing a booking frontend every morning.

A separate current official Bus BAM VAC-228/250 HTML timetable also includes
Guardamar <-> Alicante departures. It is a real additional operator/service,
but it is not a complete replacement for CE-704/Avanza and must not be used as
if it represented all Guardamar-Alicante service.

No runtime change follows yet. The next decision depends on the exact timetable
content of the CE-704 technical project.


## CV-214 technical project assessment

The official technical package `PSP CV-214_CV-301.zip` was obtained and the
CV-214 PDF was inspected directly. The document is a 105-page service project
for `CV-214 Torrevieja-Alacant`. It contains:

- a three-day-type calendar;
- winter/summer definitions;
- daily expedition counts by line;
- `Anejo 4. HORARIOS` with exact terminal-departure tables;
- `Anejo 5. PARADAS` with initial and final stop layouts.

The general calendar defines:

- winter: 22 September through 20 June;
- summer: 21 June through 21 September;
- Monday-Friday working days;
- working Saturdays;
- Sundays and public holidays.

Relevant proposed routes include:

- L1A Alacant-Guardamar-Torrevieja-Pilar;
- L1B the same corridor via CC La Zenia;
- L2 Alacant-Torrevieja, semi-direct via Guardamar;
- L4B Elx-Torrevieja via Catral/Dolores and Guardamar;
- L4C Elx-Guardamar-Torrevieja direct;
- L5 Torrevieja-Guardamar-Universitat d'Alacant;
- L6 Guardamar-Hospital-Pilar.

### Why this PDF is not the current timetable source

The May 2026 procurement `CMAYOR/2024/14Y07/0101` is still shown by current
public procurement trackers as published/in evaluation, with no award or
formalisation recorded. Its bid deadline was 3 July 2026. Therefore the PDF is
a tender service project, not proof that its timetable is already the operating
September 2026 schedule.

The timetable itself also materially disagrees with the last accepted live
Avanza snapshot from 28 September 2026:

- Alicante: the proposed weekday L1 + L2 terminal schedule provides 9 + 12 =
  21 departures per direction before intermediate-stop timing is considered,
  while the live accepted Guardamar-Alicante snapshot had 26 departures per
  direction.
- Elche: proposed L4B + L4C supply differs from the accepted 8/8 live snapshot;
  L4C alone is 4 one way and 3 the other on weekdays.
- CC La Zenia: L1B departures are marked only for Saturdays/Sundays/holidays
  in Anejo 4, whereas the live planner accepted 13/13 Guardamar-Zenia trips on
  Monday 28 September 2026. This is a decisive mismatch.

In addition, Anejo 4 gives departure times at route terminals (for example
Alacant/Pilar, Alacant/Torrevieja, Elx/Torrevieja). It does **not** provide the
exact intermediate Guardamar pass/departure time for those trips. The stop
annex proves that Guardamar is served, but cannot by itself generate an exact
Guardamar departure card without another authoritative timing source.

### Source decision

Do not use the CV-214 tender PDF to replace the current Avanza planner or to
overwrite accepted September 2026 timetable state.

Keep it as a future reference for the planned concession structure and as a
high-value validation source for route topology, seasonal definitions and line
design. Re-evaluate it only after the CV-214 concession is awarded/formalised
and there is evidence that the project schedule has entered service.

Even after that point, exact Guardamar departure cards will still require an
authoritative stop-level timetable or machine-readable source unless the final
operating documents publish intermediate times.

No runtime change follows from this PDF assessment.
