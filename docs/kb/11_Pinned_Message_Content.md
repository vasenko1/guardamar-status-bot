# Pinned Message Content

## Status

This page stores the approved copy and editorial rules for the linked pinned
city guide implemented by ADR 0041. Publication is an explicit operator action;
it is not scheduled and does not interact with the Morning Digest.

## Live cameras

Use the following Russian copy as the approved camera section:

```markdown
📹 **Гуардамар в прямом эфире**

🏙 **Город**

• [**Вид с Castillo**](https://www.guardamardelsegura.es/2024/11/21/vista-desde-el-castillo/)
Панорама Гуардамара с крепостного холма.

• [**Площадь Ayuntamiento**](https://www.guardamardelsegura.es/2024/11/21/plaza-del-ayuntamiento/)
Главная площадь города и церковь Sant Jaume.

• [**Проспект Los Pinos**](https://www.guardamardelsegura.es/2025/06/27/avda-los-pinos-en-directo/)
Одна из центральных пешеходных улиц Гуардамара.

🌊 **Море**

• [**Пляжи Centro и La Roqueta**](https://www.comunitatvalenciana.com/es/alacant-alicante/guardamar-del-segura/webcams/guardamar-del-segura-1)
Официальная камера Comunitat Valenciana.

• [**Пляж La Roqueta**](https://www.skylinewebcams.com/es/webcam/espana/comunidad-valenciana/alicante/guardamar-del-segura.html)
Панорамный вид на пляж и море.

📣 [**обЪявления Гуардамар**](https://t.me/MarketGuardamar)
```

### Editorial rules

- Keep proper names such as `Castillo`, `Ayuntamiento`, `Los Pinos`, `Centro`,
  `La Roqueta`, and `Sant Jaume` unchanged.
- Translate generic place types into Russian, including `Plaza` as `Площадь`,
  `Avenida` as `Проспект`, and `Playa` as `Пляж` or `Пляжи`.
- Do not add an introductory invitation or a closing sentence about checking
  weather, waves, or current conditions.
- Do not include 360-degree virtual tours.
- Do not list duplicate feeds or old municipal pages whose embedded streams
  are unavailable.
- Preserve the standard public-message footer exactly as shown above.

### Verified scope

The municipality's `Guardamar en directo` menu confirms the three city cameras
and the official Comunitat Valenciana beach camera. Skyline provides a separate
La Roqueta view. No additional working public live cameras have been confirmed
for Guardamar urbanizations, parks, the marina, or the lighthouse. Camaramar is
not listed because it republishes the Comunitat Valenciana feed.

## Transport

### Status

The transport structure and leaf-message style below are approved for the
linked guide. Time-sensitive route and stop claims remain grounded in the dated
investigation at `research/2026-08-14-transport-pinned-message.md` and must be
reviewed before later copy changes.

### Information design

- Put city routes first in the transport index.
- Use `Автобусы Гуардамара` for the overall heading and
  `Междугородние направления` for services leaving the municipality.
- Keep hospitals outside the list of cities. Show `Hospital de Torrevieja`
  under a separate `Больница` heading.
- Lead with the place a resident recognizes, such as an urbanization or beach,
  and show route numbers second.
- For every residential area, show all confirmed routes, not only the municipal
  route whose diagram was investigated first.
- Give each physical stop a map link and a plain-language direction. Stops on
  opposite sides of a road must be listed separately.
- Do not imply that nearby stop poles with different operator codes are the
  same physical stop.
- A route number without a prefix is not globally unique. Keep municipal
  `Линия 1` distinct from interurban `I1` and operator route `L02`.
- Keep the official route diagram as supporting evidence, but do not make
  residents read the diagram to discover whether their area is served.

### Preliminary route 2 view

The municipal route 2 is the only one of Guardamar's two city routes confirmed
for Pórtico Mediterráneo, El Raso, Campico, El Edén, Los Estaños, La Rosa, and
Pinomar. This does not mean it is the only public bus service at every area.

- Pinomar and La Rosa are also listed on the current interurban I1, I2, I5,
  and I8 views. Final copy must map those product labels back to the current
  official operator route names and schedules.
- Only route 2 is currently confirmed for Pórtico Mediterráneo, El Raso,
  Campico, El Edén, and Los Estaños. Treat this as incomplete until the nearby
  CV-895 interurban stops are audited.
- The official route 2 diagram lists the two El Raso stops as
  `Av. El Ras Gran, 4` and `Av. El Ras Gran, 47`. Their user-facing direction
  labels still require a final map check.

### Preliminary route 1 view

Municipal route 1 connects Puerto Deportivo, the town center, the bus-station
area, the beach corridor, Hotel Playas de Guardamar, and Campomar. Selected
starred departures also pass Los Secanos and the cemetery.

- Puerto Deportivo is listed at `C/ Juan García, 82` in the official route
  diagram. No additional public route to the port has yet been confirmed.
- Campomar is listed at `C/ Austria, s/n`. No additional public route to
  Campomar or Hotel Playas de Guardamar has yet been confirmed.
- The bus-station area is an interchange, not a route-1-only destination.
  Current operator material confirms multiple nearby urban and interurban stop
  poles. The final message must group them as one useful area while preserving
  the exact map point for each service.
- Operator route L07, Torrevieja to Universidad de Alicante, uses
  `C/ Pintor Sorolla, 2` in one direction and `C/ Pintor Sorolla, 1` in the
  other. These correspond to stops on the route 1 corridor and should be shown
  as an additional service once the stop pairing is rechecked on the map.
- No additional routes have yet been confirmed for the route 1 stops at Playa
  La Roqueta, the cemetery, or the remaining beach corridor. This is an open
  source-audit item, not a claim that no such service exists.

### Approved leaf-message presentation rules

- End every transport detail with `⬅️ К списку транспорта`, linked to the
  transport navigator. End the navigator and camera list with
  `⬅️ К главному закрепу`, linked to the compact root.
- Treat those links as one managed graph. If a managed message is deleted, the
  next explicit publication recreates it and rewrites every affected link;
  operators must not edit message IDs in state manually.
- Do not add a `Проверено` line or a separate `Официальное расписание` link to
  a public transport message.
- When a timetable changes by travel date, show times only when the bot has
  validated the operator result for the explicitly displayed date. Keep one
  short functional link for another date.
- For municipal lines 1 and 2, attach the bounded PNG rendered from the exact
  official one-page PDF under ADR 0042 and keep a direct PDF link for full
  quality. Show only the currently applicable reviewed calendar period. An
  unknown revision receives a generic caption without old notes or seasonal
  claims. Do not turn a date-specific search result into a pinned image.
- Make the names of useful stops clickable map links. Do not repeat the map-pin
  icon on every timetable row.
- Link an airport terminal stop directly rather than describing it only as an
  `остановка у терминала`.
- Stops on opposite sides of a road require separate direction-specific map
  points. Until both points are verified, a search link must not be presented
  as an exact boarding point.
- Preserve the standard public-message footer.

The airport message is refreshed by ADR 0043 at 05:00 from the operator result
for the current date. It shows both directions, exact operator endpoint maps,
the standard fare only after independent tariff validation, and a link for
another date. A cached result always retains its explicit date and is never
presented as current on a later day. Hospital de Torrevieja is shown as line 6
with the all-year weekday and weekend/holiday departures defined by the signed
CE-704 service project. Its source link points to the current Generalitat
concession notice, not to the retired Autobusing search page. Keep the verified
direction-specific stop links.
