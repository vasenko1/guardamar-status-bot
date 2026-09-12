# Guardamar public-event coverage, 12–13 September 2026

Investigation date: 12 September 2026 (Europe/Madrid). The attached posters
were regression clues, **not** the definition of a complete calendar. This
inventory was built from source pages and source programmes before comparison
with the bot's 11 September weekend publication. It records publicly announced
events, not a guarantee that an event actually took place; the Campo organisers
warned that weather or participation could change the programme.

## Source inventory and end-to-end finding

| Source/channel | Public facts for 12–13 September | In the old collector? | Where coverage was lost |
| --- | --- | --- | --- |
| [Turismo cultural agenda](https://guardamarturismo.com/agenda-cultural/) and [September MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) | Exhibition, route, tour, sports, youth and Campo collage | Yes: HTML + MUPI | Small collage/OCR omitted details; generic festival range was not the individual programme. |
| [Turismo Fiestas article](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) and its [full-size official poster](https://guardamarturismo.com/wp-content/uploads/2026/08/CARTEL-OK-fiestas-del-campo-2026.jpg-1-scaled.jpeg) | The complete timed 12–13 September finale, including no exact time for fireworks or chocolate | No | Primary programme was not fetched; the MUPI only showed an inset. Public WordPress REST posts endpoint exposes the article without credentials. |
| [Generalitat Valenciana 2026 Fiestas PDF](https://multimedia.comunitatvalenciana.com/F996A8ADF9B041269103F5A1C0B240D0/doc/B985AD14B71E49F2A99B1F9EB3CFEB73/2026_CAST.pdf), linked from its [official event page](https://www.comunitatvalenciana.com/es/alacant-alicante/guardamar-del-segura/eventos/fiestas-del-campo-de-guardamar) | Independent official confirmation of every 12–13 September Campo programme item; page 2 explicitly places fireworks after the parade | No | Cross-check only; not a separately needed runtime source. |
| [Agenda Guardamar](https://www.agendaguardamar.com/) | Paid 10:00 Castillo–Molino guided tour | Yes | Persisted and selected correctly. No separately confirmed missing event. |
| [Todo Cultura's copy of the municipal September programme](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) | Route, tennis, Disney, drawing, heritage, routine opening, Fiestas link; explicitly says route repeats 19/26 September | Yes, as a *secondary* source | A date was marked processed after a merely nonempty model response. The long duplicated programme and bounded detail/LLM budgets lost individual rows; later syncs did not revisit them. Rolling seven-day collection also discarded explicitly named distant repeats. |
| [Municipal library agenda](https://www.bibliotecaspublicas.es/guardamardelsegura/actividades-programas/Agenda-de-actividades.html) and [hours](https://www.bibliotecaspublicas.es/guardamardelsegura/Localizacion-Horarios.html) | Narbaiza exhibition runs to 23 September, but library is closed on this weekend | Yes (agenda), no (hours) | A date range was treated as daily access, yielding a false positive on both days. |
| AM Guardamar WordPress events | No additional 12–13 September event found in the current public REST catalogue | Yes | No gap established. |
| Ayuntamiento and Cultura public posts | Youth, sports and Campo posters; no separately confirmed additional event | Partially: public Facebook text, not every image | Image-only posts could be missed; the relevant originals are corroborated by the municipal MUPI and Turismo full-size poster. |
| Juventud/CSJ and Patrimonio | Drawing workshop and Disney; heritage guided tour | No separate feed | Their published programmes are represented via municipal/Todo and Agenda sources. Ordinary venue opening hours are not event items. |
| Deportes/club organiser | Table-tennis presentation tournament | No separate feed | The municipal MUPI and detailed programme confirm it. |
| Campo market operator's [where-is-the-market page](https://lemon-tree-market.jimdosite.com/where-is-the-market/) | Sunday Campo/Lemon Tree market, Camino del Raso 15 | Yes, as a reviewed recurring rule | Correctly selected; other names for the same market are not distinct events. |

No useful public ICS/calendar endpoint for these municipal programmes was found.
The WordPress REST posts endpoint was the useful newly integrated primary-source
surface. Search results and third-party calendar pages were used only to discover
or cross-check candidates. In particular, a third-party claim that the Paseo
Ingeniero Mira artisan market runs this weekend conflicts with the
[municipality's 2026 decree](https://www.guardamardelsegura.es/wp-content/uploads/2026/04/DECRETO_20HORARIOS_20PASEO_20INGENIERO_20MIRA_202026.pdf): the summer market ended 6 September and 7–20 September is dismantling. It is **excluded**.
The [official Turismo September agenda](https://guardamarturismo.com/en/cultural-agenda/)
also independently confirms the route dates 5/12/19/26 and the exhibition's
Saturday hours 10:00–14:00 (the secondary Todo text gives different hours).
Claims for the El Fogón antiques market are also **not promoted**: directories
generate a 13 September occurrence, but no current operator/municipal primary
confirmation was located, and reporting documents repeated municipal closures.
This is unresolved public-source uncertainty, not a silently missing bot event.

## Independent event calendar and coverage matrix

`Old` means the 11 September published weekend digest. `New` means the
post-fix normalized catalog and selector preview. “Morning” refers to a
production-equivalent 12 September morning *event-section* preview, not a
second Telegram publication. The last column is the pre-fix failure point;
`—` means the event already reached the selector. `P` = primary source,
`S` = secondary confirmation. All times are local.

| Date/time | Event | Venue | Primary source | Secondary confirmation | Already integrated? | Bot catalog old→new | Weekend old→new | Morning old→new | Failure point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sat 08:30 | Free Punto Geodésico route | Guardamar route | [Official Turismo September agenda](https://guardamarturismo.com/en/cultural-agenda/) (P) | [Municipal programme copy](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | yes→yes | yes→yes | yes→yes | Future 19/26 repeats were not persisted. |
| Sat 10:00–14:00 | Jaime Aniorte, *Imborrable* | Casa de Cultura | [Turismo agenda/MUPI](https://guardamarturismo.com/agenda-cultural/) (P) | [Todo programme](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | yes→yes | yes→yes | yes→yes | Exact Saturday hours needed correction. |
| Sat 10:00–12:00 | Guided Castillo–Molino tour | Meet at Castillo | [Agenda Guardamar](https://www.agendaguardamar.com/) (P) | [Municipal programme copy](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | yes→yes | yes→yes | yes→yes | — |
| Sat 10:00–14:30 | Club Tenis de Mesa presentation tournament | Pabellón Sant Jaume | [Municipal MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | [Full municipal-programme copy](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | no→yes | no→yes | later untimed→timed | Row extraction, then incomplete merge. |
| Sat 10:30–12:30 | Disney youth activity | Reina Sofía auditorium | [Municipal MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | [Municipal-programme copy](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | no→yes | no→yes | later yes→yes | Poster/detail missed before 12 Sep sync. |
| Sat 11:00–13:00 | Drawing from zero to realistic | Centro Social Juvenil | Municipal Juventud poster in [MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | [Municipal-programme copy](https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-free-tour-guiada-y-gratuita-al-punto-geodesico-con-recorrido-natural-e-historico-dentro-de-la-agenda-municipal-de-septiembre-del-ayuntamiento-2/?occurrence=2026-09-12) (S) | Yes | no→yes | no→yes | no→yes | One 11:00 row repeatedly failed model extraction; strict quote/time fallback added. |
| Sat 13:00 | Campo rockets | Campo de Guardamar | [Turismo article and full-size poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [Todo Fiestas item](https://todoculturavegabaja.es/eventos/campo-de-guardamar-del-segura-evento-disparo-de-cohetes-dentro-de-las-fiestas-en-honor-a-la-patrona-virgen-de-fatima-9/) (S) | No | no→yes | no→yes | no→yes | Full programme absent. |
| Sat 18:30 | Bands enter | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [Todo Fiestas item](https://todoculturavegabaja.es/eventos/campo-de-guardamar-del-segura-evento-disparo-de-cohetes-dentro-de-las-fiestas-en-honor-a-la-patrona-virgen-de-fatima-9/) (S) | No | no→yes | no→yes | no→yes | Full programme absent. |
| Sat 19:00 | Desfile Multicolor | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [Todo Fiestas item](https://todoculturavegabaja.es/eventos/campo-de-guardamar-del-segura-evento-disparo-de-cohetes-dentro-de-las-fiestas-en-honor-a-la-patrona-virgen-de-fatima-9/) (S; contradictory 19:30) | No | no→yes | no→yes | no→yes | Full programme absent; primary time wins. |
| Sat after parade, untimed | Fireworks | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | No | no→yes | no→yes | no→yes | Do not invent 19:00; separate from parade. |
| Sat 21:00 | Fiesta del Vino | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [Todo Fiestas item](https://todoculturavegabaja.es/eventos/campo-de-guardamar-del-segura-evento-disparo-de-cohetes-dentro-de-las-fiestas-en-honor-a-la-patrona-virgen-de-fatima-9/) (S) | No | no→yes | no→yes | no→yes | Full programme absent. |
| Sat from 23:00 | Night programme: Chari Candela, Retropop, DJ/Hora Loca, Gamburrino adult and youth | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [Todo Fiestas item](https://todoculturavegabaja.es/eventos/campo-de-guardamar-del-segura-evento-disparo-de-cohetes-dentro-de-las-fiestas-en-honor-a-la-patrona-virgen-de-fatima-9/) (S) | No | no→yes | no→yes | no→yes | One parent performance with complete roster; full programme absent. |
| Sun night/early morning, untimed | Chocolate con mona | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | No | no→yes | no→yes | n/a | Full programme absent; do not invent a clock time. |
| Sun 06:00 | Despertà | Campo de Guardamar | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | No | no→yes | no→yes | n/a | Full programme absent. |
| Sun 07:00–16:00 | Campo/Lemon Tree market | Camino del Raso 15 | [Market operator](https://lemon-tree-market.jimdosite.com/where-is-the-market/) (P) | [Turismo/market directories](https://guardamarturismo.com/) (S) | Yes | yes→yes | yes→yes | n/a | — |
| Sun 10:00 | Charanga finale | Auditorio del Campo | [Turismo article/poster](https://guardamarturismo.com/este-es-el-programa-de-fiestas-del-campo-de-guardamar-2026/) (P) | [MUPI](https://www.guardamardelsegura.es/wp-content/uploads/2026/09/MUPI-SEPTIEMBRE-2026-scaled.jpg) (P) | No | no→yes | no→yes | n/a | Full programme absent. |

The old digest also **falsely included** the Narbaiza exhibition on both
weekend days. The [library hours](https://www.bibliotecaspublicas.es/guardamardelsegura/Localizacion-Horarios.html)
do not permit weekend access; the new library selector removes it. Routine
opening (Molino, Castillo, museums, CSJ) and the disputed El Fogón and artisan
markets are not separately listed as events. The disputed “free guided Molino
visit” line in Todo conflicts with the municipality's reserved guided-tour
hour and has no independent primary confirmation, so it is not a separate
free guided event.

## Repair and verification contract

Both weekend and morning selectors read the same persisted normalized event
catalogues. The Todo collector now checks every independent timed row before
advancing its cursor; a small strict parser recovers explicitly quoted youth
activities when model extraction fails. Explicitly listed future repeats are
persisted even when an unrelated row fails. Turismo's public WordPress article
and linked poster supply the festival's dated items, with source text
authoritative over combined/incorrect vision candidates. Library opening days
constrain multi-day exhibition selection. Existing source facts are retained
when a transient upstream failure prevents a complete refresh.

Post-fix acceptance requires a fresh source read, normalized catalog check,
weekend and morning previews, plus 19/26 September route selection. Production
rollout and actual Telegram message verification are tracked separately in the
operational hand-off; this research note does not treat a test or local preview
as a production deployment.
