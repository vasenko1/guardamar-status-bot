# Recurring activities source production probe — 2026-09-18

Status: **COMPLETED ON PRODUCTION TERMUX**.

Production device: Android / Termux used by `guardamar-status-bot`.

The operator ran the read-only curl probe from the production network. The
probe did not load bot secrets, modify project state or send Telegram messages.

## Results

| Source | HTTP | Final URL | MIME | Bytes | Seconds | Marker result |
| --- | ---: | --- | --- | ---: | ---: | --- |
| Ayuntamiento RSS | 200 | unchanged | `application/rss+xml; charset=UTF-8` | 4,579 | 1.431302 | Dinamización 2026/27 **YES** |
| Ayuntamiento REST latest 10 | 200 | unchanged | `application/json; charset=UTF-8` | 1,057 | 0.923805 | Dinamización 2026/27 **NO** |
| Dinamización detail | 200 | unchanged | `text/html; charset=UTF-8` | 38,290 | 1.594606 | `Inscripción online` **YES** |
| Dinamización Google Form | 200 | unchanged | `text/html; charset=utf-8` | 35,307 | 0.723254 | registration + Movimiento + Emociones **YES** |
| Turismo agenda | 200 | unchanged | `text/html; charset=UTF-8` | 30,532 | 1.319692 | stale season label + September registration markers **YES** |
| Chess | 200 | unchanged | `text/html; charset=UTF-8` | 25,841 | 0.969265 | school + Tue/Thu + Iniciación **YES** |
| Tertulia | 200 | unchanged | `text/html;charset=UTF-8` | 6,484 | 0.604255 | Tuesday + 11:00 + 13:00 **YES** |
| EPA | 200 | unchanged | `text/html; charset=UTF-8` | 35,923 | 1.483431 | current 2026/27 markers **YES** |
| EOI vacancy entry | 200 | unchanged | `text/html;charset=ISO-8859-1` | 13,409 | 0.292422 | 2026/27 **YES**, Guardamar **NO** |

## Decisions

### Ayuntamiento discovery

Use the RSS feed:

`https://www.guardamardelsegura.es/feed/`

The generic REST latest-ten-posts request is about 3.5 KB smaller and roughly
0.5 seconds faster, but it does not contain the 7 September Dinamización
campaign on 18 September. It is therefore not a sufficient discovery contract
as tested.

Do not add REST search/pagination machinery just to save a few kilobytes per
day. One 4.6 KB RSS request in the existing daily guide sync is simpler and
operationally negligible.

### Dinamización

**ACCEPTED.**

Both the campaign detail and linked Google Form are reachable from production
with ordinary GETs and expose the expected markers. No browser, JavaScript
execution, OCR or LLM parser is required.

Contract:

- RSS discovery daily;
- detail only on a new/changed campaign, to discover the official Form URL;
- current Form direct refresh once daily so same-link semantic changes are visible;
- compact normalized last-good facts locally.

### Chess

**ACCEPTED.**

The production response is a small server-rendered HTML page and all expected
school/schedule/level markers are present.

Use a low-frequency automatic check from the existing guide sync rather than a
new cron or manual seasonal validation.

### Tertulia

**ACCEPTED.**

The production response is only about 6.5 KB and exposes the durable weekly
schedule directly. Use a low-frequency automatic check from the existing guide
sync.

### Creative workshops

**TRANSPORT ACCEPTED; PUBLICATION DEFERRED.**

The already-used Turismo agenda exposes the target workshop block, so parsing
it adds zero network requests. However the September 2026 page still labels the
block `TALLERES 2025/2026`. Do not publish a recurring card until this
publisher-side season ambiguity is resolved or there is an independent
explicit current-season official fact that safely disambiguates it.

### EPA

**TRANSPORT ACCEPTED; DYNAMIC LANGUAGE CARD DEFERRED.**

The official page is current for 2026/27, but the public machine surface still
does not expose the complete current Spanish timetable/vacancy/price contract.
Transport success does not make those missing facts safe to infer.

### EOI

**DEFERRED.**

The official vacancy entry surface is reachable and current-year, but its
initial response does not expose Guardamar. A Guardamar-specific machine query
contract would need separate proof before automation. No further work is needed
for the first recurring-card slice.

## Product rule added after the probe

Commercial language schools and private academies are excluded from the guide.
Do not use Educare, Kairós, private tutors or similar commercial providers to
fill public-language-source gaps.

## Final readiness for first implementation

Ready now:

- `♟️ Шахматы`;
- `✍️ Литературное творчество`;
- `🤝 Муниципальные занятия и мастерские`.

Not ready for public card now:

- `🎨 Творческие мастерские` — source season ambiguity;
- EPA / EOI / Cruz Roja language cards — current source contracts insufficient;
- PANGEA / INTEGRA — only when a current campaign/intake appears;
- commercial providers — excluded by product rule.

No further production transport probe is required before implementing the
first ready slice.
