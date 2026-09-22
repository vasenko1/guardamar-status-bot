# Guardamar fishing guide — product and rules research

Status: **RESEARCH COMPLETE ENOUGH FOR PRODUCT DESIGN / NOT IMPLEMENTED**

Date: 2026-09-22

This note preserves the fishing investigation and the product decisions reached
so far. It is intended to make a later implementation possible without
repeating the full research.

Do **not** treat this file as a substitute for the source laws. Before coding a
specific legal rule, re-open the cited official source and verify the exact
current wording. Fishing law is a higher-risk content area, and some rules can
change independently of this bot.

## Product direction agreed so far

The feature should be a mobile-first pinned guide, not a general-purpose legal
monitor.

The bot should:

- explain stable local rules that are directly relevant to Guardamar;
- split the guide by fishing method so each Telegram card is easy to read on a
  phone;
- provide official links for licences and for current species-specific rules;
- publish only deterministic calendar alerts for stable local seasonal changes;
- avoid pretending to know the current status of every species, quota, opening,
  closure, or special authorisation.

The bot should **not**:

- build a long-lived parser that tries to infer current species restrictions
  from MAPA HTML/PDF documents;
- automatically tell users that a species is currently open/closed unless a
  future design explicitly revisits that decision;
- scrape or reverse-engineer a hidden MAPA JSON/API just to avoid linking users
  to the official source;
- use AI/OCR/browser automation for fishing rules;
- turn the fishing guide into a large legal encyclopaedia;
- add a generic liability disclaimer to every card merely because fishing is a
  regulated activity.

The product stance is:

> Explain stable local rules; link the user to the official source for
> changeable rules.

Because the bot will not publish live species/quota status, the previously
suggested generic disclaimer such as "information may change; verify everything"
is **not part of the current design**. Instead, current-rule links should be
present exactly where they are useful.

## Mobile-first information architecture

Agreed direction:

```text
🎣 Рыбалка
│
├── 🌊 Морская рыбалка
│   ├── 🎣 С берега
│   ├── 🛶 С каяка / плавсредства
│   ├── 🚤 С зарегистрированного судна
│   ├── 🤿 Подводная рыбалка
│   └── 🕸 Rall / esparavel
│
└── 🏞 Внутренние воды
    ├── 🎣 С берега / удочкой
    ├── 🚤 С лодки
    └── 🛟 Pato / float-tube
```

Important terminology decision:

- do **not** use "small boat" as a legal category;
- distinguish a registered recreational vessel from a kayak/canoe or other
  `artefacto flotante`;
- for internal waters, "внутренние воды" is better than only "река", because the
  same licence/rules also cover reservoirs and other continental waters.

The root card should be short. Detailed rules belong in leaf cards.

## Stable local seasonal alerts

The municipal beach ordinance defines a bathing season that matters for
shore-fishing and underwater-fishing rules.

The two relevant bathing-season periods are:

1. **1 June through 30 September**.
2. **Semana Santa**, from the Friday before Palm Sunday through
   `Lunes de San Vicente` inclusive.

For product purposes, Semana Santa can be calculated from Easter:

- start: Easter Sunday - 9 days;
- end: Easter Sunday + 8 days.

The current alert concept is to notify users on the day **before** the rule
changes.

Core predictable events each year:

1. day before the Semana Santa restriction starts;
2. last day of the Semana Santa restriction, because the next day the temporary
   regime ends;
3. **31 May**, because the summer regime starts on 1 June;
4. **30 September**, because the summer regime ends on 1 October.

These alerts should be about the affected methods, not "fishing in general":

> changes to shore fishing on Guardamar beaches and underwater fishing in
> bathing zones.

Do not imply that 1 June changes the general rules for registered boats or
kayaks in open water.

### Possible additional fixed seasonal alerts

Marine `rall / esparavel` has its own seasonal closure in **December, January,
and February** according to the GVA recreational maritime licensing/rules
material checked during this investigation.

This creates a potential additional pair of deterministic events:

- 30 November -> seasonal closure starts 1 December;
- last day of February -> season reopens 1 March.

This has **not yet been approved as a Telegram alert**. Preserve it as a product
decision still to make.

Internal-water seasons are more complex and depend on water body, species,
classification, and management plan. Do not create one generic "continental
fishing season" alert.

## Marine fishing — common framework

Official GVA procedure:

https://sede.gva.es/es/detall-tramit?id_proc=647

MAPA PescaREC:

https://www.mapa.gob.es/es/pesca/temas/pesca-maritima-de-recreo/pesca-rec

MAPA openings/closures:

https://www.mapa.gob.es/es/pesca/temas/control-inspeccion-lucha-pesca-ilegal/aperturasycierres

Stable/common product facts found:

- maritime recreational fishing requires the appropriate GVA licence for the
  method;
- catch is recreational and cannot be sold/commercialised;
- current species, minimum sizes, special authorisations, catches/releases and
  closures should be checked through PescaREC/MAPA rather than copied into our
  permanent card;
- from 20 March 2026 PescaREC is part of the current national recreational
  maritime fishing regime and is directly relevant to shore, vessel,
  underwater, and floating-artifact fishing;
- current species-specific openings/closures are explicitly **not** something
  this bot will monitor automatically at this stage.

### Why the MAPA auto-monitor was rejected for now

The MAPA "Aperturas y cierres de pesquerías" page is technically easy to
discover from server-rendered HTML and links to official PDFs. Historical
research on 2024-2026 showed repeatable recreational cases such as:

- BFT / bluefin tuna precautionary and definitive closures;
- ALB-MED / Mediterranean albacore closures and reopenings.

However:

- the date in the HTML title can be the document/listing date, not the effective
  legal date;
- a definitive closure can confirm an already-existing precautionary closure;
- wording changes between years;
- one year's reopening can explicitly mention recreational fishing while a
  later year's document may not repeat the same phrase;
- a future site/document wording change could cause either a false publication
  or a missed publication.

The user explicitly preferred to avoid this long-lived liability/risk surface.
Therefore the current design is to **link to MAPA/PescaREC instead of parsing
their live legal state**.

## 🎣 Marine shore fishing

Primary local source:

Guardamar municipal beach/littoral ordinance:

https://www.guardamardelsegura.es/wp-content/uploads/2023/10/20231004_3-ORDENANZA-DE-USO-SEGURIDAD-Y-CONSERVACION-DE-LAS-PLAYAS-Y-LITORAL-MUNICIPAL.pdf

During the bathing season:

### 24-hour restriction in bathing zones

The ordinance prohibits shore fishing in the bathing zones of:

- Centre
- La Roqueta
- Babilònia
- El Moncaio

The wording is about the **bathing zones**, so do not rewrite it as an absolute
claim about every centimetre of coastline belonging to those beach names.

### 09:00-21:00 restriction

For:

- Els Tossals
- Dels Vivers
- El Camp
- Les Ortigues

shore fishing is prohibited from **09:00 to 21:00** during the bathing season.

### Additional stable conditions

Even outside the seasonal/time restriction, the ordinance gives bathers/users
priority and requires fishing to be conducted in the absence of beach users and
at more than **100 m** from people/users as specified by the ordinance.

Fishing in marked boat-access/navigation corridors is prohibited.

Product wording should avoid an absolute "fishing is allowed". Prefer wording
such as:

> the seasonal prohibition does not apply at this time; other rules and current
> restrictions still apply.

## 🛶 Kayak / canoe / floating artefact

A key legal distinction found in the 2025 amendment is that certain
non-motorised floating/beach artefacts, including the relevant kayak/canoe class,
are covered by the shore-fishing licence regime rather than by the registered
vessel licence.

Source to re-check before implementation of exact wording:

https://www.boe.es/buscar/doc.php?id=BOE-A-2025-11959

Product implications:

- kayak/canoe should have its own card;
- do not group it with a registered motor boat merely because both are on the
  water;
- do not call the category "small boat".

Guardamar's municipal ordinance also regulates navigation/use of vessels and
floating artefacts in bathing zones.

Research finding:

- in a marked bathing zone, navigation/anchoring/use of recreational craft and
  floating artefacts is restricted/prohibited under the beach rules;
- where the bathing zone is not physically marked, the ordinance defines a
  bathing-water area extending roughly **200 m from a beach** and **50 m from
  other coast**, with access/exit rules;
- access to/from shore is through marked channels or according to the
  perpendicular/safety rules in the ordinance;
- red-flag conditions create additional safety/navigation restrictions,
  including for kayaks/floating artefacts.

Important seasonality conclusion:

The navigation article checked during the investigation is **not written simply
as a "1 June-30 September fishing closure"**. Therefore do not code an automatic
claim that kayak navigation/fishing near the beach becomes unrestricted on
1 October.

Kayak rules should be presented as a separate, mostly static navigation +
licensing card, not as another copy of the shore-fishing season.

## 🚤 Fishing from a registered vessel

For a registered recreational vessel, the maritime fishing licence is issued for
the vessel rather than using the kayak/shore licence model.

Official procedure:

https://sede.gva.es/es/detall-tramit?id_proc=647

Research conclusions:

- there is no general Guardamar rule found saying "fishing from a boat is banned
  for the whole summer";
- the 1 June / Semana Santa shore-fishing calendar should therefore **not** be
  applied to open-sea vessel fishing;
- coastal bathing-zone/navigation restrictions still matter near the beach;
- safety/flag conditions still matter;
- species-specific quotas, closures, special permits and protected areas remain
  independent of the beach season and should be checked in PescaREC/MAPA.

The permanent card should link to:

- GVA maritime licence;
- PescaREC;
- MAPA openings/closures;
- marine reserve information where useful.

### Tabarca

A Guardamar/Santa Pola boat user can easily reach the marine reserve around
Tabarca, which has a special regulatory regime.

Official MAPA reserve page:

https://www.mapa.gob.es/es/pesca/temas/proteccion-recursos-pesqueros/reservas-marinas-de-espana/isla-de-tabarca/caracteristicas/

Product decision:

- do not copy the full Tabarca legal regime into the Guardamar card;
- provide a short "marine reserves / Tabarca" official link in the vessel card.

## 🤿 Underwater fishing

Underwater recreational fishing is a separate regulated method and should have
its own card.

Official GVA maritime licence procedure:

https://sede.gva.es/es/detall-tramit?id_proc=647

Stable findings from the investigation:

- it uses a distinct underwater-fishing licence/regime;
- the applicant/licence has additional health/medical requirements compared
  with ordinary shore fishing;
- fishing is on breath-hold rather than with underwater breathing equipment;
- a visible surface buoy/marker is required;
- the diver must remain within the prescribed distance of the buoy (research
  found **25 m**; re-check exact current wording before implementation);
- a loaded speargun must not be carried outside the water;
- underwater fishing is prohibited from sunset to sunrise;
- there are additional restrictions around artificial reefs and incompatible
  simultaneous possession/use of underwater breathing equipment.

### Guardamar-specific seasonality

The municipal ordinance prohibits underwater fishing in bathing zones during
the bathing season.

Therefore the four core local seasonal alerts should mention **both**:

- shore fishing on the affected beaches;
- underwater fishing in bathing zones.

The night prohibition is not seasonal and belongs in the permanent underwater
card.

## 🕸 Marine rall / esparavel

The user explicitly wants net fishing represented in the guide.

Important distinction:

- recreational use of arbitrary professional fishing nets is **not** the
  product category;
- the relevant Valencian recreational method is specifically `rall /
  esparavel`, with its own licence/rules.

Official GVA maritime procedure/source:

https://sede.gva.es/es/detall-tramit?id_proc=647

Research findings:

- this is a separately regulated recreational method;
- it has its own licence/conditions;
- there is a seasonal closure during **December, January and February**.

Before implementation, re-check the exact current gear dimensions, operational
conditions, distances and licence language in the current GVA source instead of
copying historical numbers from memory.

As noted above, whether to send December/March Telegram alerts is still an open
product decision.

## 🏞 Continental / internal-water fishing

Official licence procedure:

https://sede.gva.es/es/detall-tramit?id_proc=681

The internal-water section should not be modelled as one generic "river fishing"
card. The useful practical split is:

```text
🏞 Внутренние воды
├── 🎣 С берега / удочкой
├── 🚤 С лодки
└── 🛟 Pato / float-tube
```

### 🎣 Shore / rod fishing

This is the ordinary continental recreational mode.

Research conclusions:

- a continental fishing licence is required;
- legal methods, number of rods, baits, species, catch-and-release requirements
  and seasons can vary by water type and management plan;
- some older/base rules use limits such as two rods in ordinary waters and
  stricter limits in trout waters, but exact current values must be verified
  from the current official rule before putting them in a permanent card.

The product should therefore emphasise:

- licence;
- status of the specific water/section;
- official GVA rules for that water.

### 🚤 Fishing from a boat in internal waters

This is a real practical mode, but it is not universally allowed.

Research conclusions:

- the angler needs the normal continental fishing licence;
- the vessel/boat has its own registration/administrative requirements for
  continental fishing;
- fishing from a boat is only possible on waters where navigation itself is
  permitted;
- therefore "I have a fishing licence" does not imply "I can fish from a boat on
  this reservoir/river".

Before implementation, re-check the exact current boat-registration procedure
and whether the intended official user link should go to a separate GVA
procedure from the general fishing-licence page.

### 🛟 Pato / float-tube

Research found a distinct practical regime for `pato` / float-tube use.

Working conclusion:

- it is usable only in waters/reservoirs where navigation is allowed;
- it is not generally allowed in marshes or flowing waters such as rivers and
  streams without special authorisation;
- for licensing/registration purposes it is not treated exactly like a normal
  boat.

This point should be re-verified against the current official wording of Orden
30/2016 (and any later amendment) before implementation.

### 🕸 Nets in internal waters

For ordinary recreational continental fishing, **nets are prohibited**.

This is an important contrast with marine `rall/esparavel`.

Possible exceptional use would require a specific administrative authorisation;
it is not a normal recreational method that deserves its own navigation card.

Recommended card wording:

> 🕸 Сети — для обычной любительской рыбалки во внутренних водах запрещены.

Re-check the exact current official wording before shipping.

## Río Segura near Guardamar

Key official source:

DOGV 2024 modification table / Orden 30/2016 Annex I:

https://dogv.gva.es/datos/2024/10/21/pdf/2024_10842_es.pdf

Research conclusion:

- Segura from entry into Comunitat Valenciana to **Puente CV-91**: recreational
  fishing section / ZPL in the reviewed table;
- from **Puente CV-91 to the sea**: `No pescable` / `VP` (Vedado de Pesca);
- the mouth / coastal-front row is also listed as non-fishable / VP in the
  reviewed table.

Product consequence:

The Guardamar internal-waters card should lead with the local prohibition:

> 🚫 Río Segura: from the CV-91 bridge to the sea, including the mouth area
> covered by the official table, fishing is prohibited.

Do not imply that obtaining a continental licence makes the lower Segura legal
to fish.

Before implementation, re-open the current DOGV table and verify the exact row
wording and whether any newer resolution has replaced it.

## Internal-water area/status matters more than one global season

Continental recreational fishing in Comunitat Valenciana is organised by
specific water/section status and management rules. During the research we
encountered categories such as:

- ZPL — Zona de Pesca Libre;
- controlled/managed fishing areas;
- cotos / water-specific plans;
- VP — Vedado de Pesca.

Therefore:

- a licence alone is not proof a location is fishable;
- seasons can be species- and water-specific;
- some waters can impose catch-and-release, bait or method restrictions;
- there is no safe single "continental fishing season" for our bot.

Current product recommendation:

Provide the stable local Segura prohibition + official GVA links, and do not
generate generic continental-season alerts.

## Useful official links to expose in the guide

### Marine

PescaREC:

https://www.mapa.gob.es/es/pesca/temas/pesca-maritima-de-recreo/pesca-rec

GVA maritime recreational licence:

https://sede.gva.es/es/detall-tramit?id_proc=647

MAPA openings/closures:

https://www.mapa.gob.es/es/pesca/temas/control-inspeccion-lucha-pesca-ilegal/aperturasycierres

MAPA species/minimum-size search investigated during this work:

https://www.mapa.gob.es/es/pesca/temas/control-inspeccion-lucha-pesca-ilegal/informacion-sobre-actividad-pesquera/buscador_especies

Tabarca marine reserve:

https://www.mapa.gob.es/es/pesca/temas/proteccion-recursos-pesqueros/reservas-marinas-de-espana/isla-de-tabarca/caracteristicas/

### Continental

GVA continental fishing licence:

https://sede.gva.es/es/detall-tramit?id_proc=681

DOGV Segura/current Annex-I source used in this research:

https://dogv.gva.es/datos/2024/10/21/pdf/2024_10842_es.pdf

## Current implementation recommendation

When implementation is resumed, prefer this minimal architecture:

1. Add a mobile-first pinned fishing subtree to the existing guide graph.
2. Keep all permanent content static/deterministic.
3. Add pure calendar logic for the four core local seasonal transitions.
4. Do not add a MAPA polling service.
5. Do not add PDF parsing.
6. Do not add a new resident process.
7. Do not add a new dependency.
8. Reuse the existing daily guide lifecycle for the calendar transition check if
   that remains architecturally appropriate at implementation time.
9. Link alerts directly to the affected leaf card, especially shore fishing /
   underwater fishing rather than to the generic root.
10. Keep all user-facing cards short enough for mobile reading.

Possible module naming discussed:

- `fishing_rules.py` for pure local/date rules if implementation proceeds.

Do **not** reuse `pesca_cv.py` for these rules. That existing module is for
Federación de Pesca CV competition/event data and has a different source
contract.

## What should be re-checked immediately before implementation

Because this research is time-sensitive, do a final official-source verification
for:

1. the current Guardamar beach ordinance and whether it has been superseded;
2. the exact Semana Santa / Lunes de San Vicente wording;
3. current GVA maritime licence categories after the 2025 amendment;
4. exact kayak/`artefacto flotante` wording;
5. exact underwater-fishing medical, buoy-distance and equipment rules;
6. exact current `rall/esparavel` licence and seasonal closure wording;
7. current Orden 30/2016 / later amendments for:
   - continental nets,
   - boat fishing,
   - `pato`,
   - rod limits,
   - night fishing,
   - water classifications;
8. current Segura Annex I rows and whether a newer resolution supersedes the
   2024 table;
9. whether GVA has completed the 2026 regulatory reform/public consultation that
   was noted during this investigation.

## Open product decisions

Before coding, explicitly decide:

1. Should `rall/esparavel` get its own fixed December/March alerts, or only a
   permanent card?
2. How much detail belongs in the kayak card versus a navigation/safety link?
3. Should the vessel card include a dedicated Tabarca link or a generic marine
   reserves link?
4. Which official GVA page is best for checking the fishability/status of a
   specific continental water?
5. Whether internal-water boat registration deserves its own linked leaf or only
   a short note inside the boat card.
6. Final Russian wording and emoji density for all mobile cards.

## Summary

The resulting product concept is intentionally conservative:

- **stable Guardamar rules are explained;**
- **fixed local seasonal changes may generate alerts;**
- **current species/quota law is delegated to PescaREC/MAPA;**
- **marine methods are separated by their actual legal/licensing regime;**
- **continental fishing is separated by shore/boat/float-tube, while nets are
  explicitly called out as prohibited for ordinary recreational use;**
- **no fragile legal monitor is introduced.**

This is the baseline to resume from.

---

# 2026-09-23 update — dynamic, current-state fishing cards

This section supersedes the earlier assumption that the fishing cards should be
mostly static reference text.

## Updated product principle

The cards should create value by telling the user **what applies now**, not by
copying every possible rule from source websites.

The rendering rule is now:

> current status -> what applies now -> next change -> required licence/actions
> -> official links.

Rules that are not currently active should normally be hidden rather than shown
as historical/future clutter.

Stable permanent constraints remain visible only where they are necessary to
understand what the user may do now.

The feature remains conservative about live species/quota law:

- do not parse MAPA openings/closures automatically;
- do not infer current species status;
- link to PescaREC/MAPA for changeable species-specific rules.

## Final compact navigation concept

The current preferred guide tree is:

```text
📌 Полезное о Гуардамаре
└── 🎣 Рыбалка
    ├── 🏖 С берега
    ├── 🚤 С лодки и каяка
    ├── 🤿 Подводная рыбалка
    ├── 🕸 Забрасываемая сеть
    └── 🏞 Реки и водоёмы
```

The navigation card should contain **labels only**. Do not add explanatory
sentences below each item; the user already knows the topic is fishing.

Use the Russian label:

> 🕸 Забрасываемая сеть

The leaf itself may explain that the Valencian legal names are
`rall / esparavel`.

## Navigation and footer requirements

Every fishing message must use the existing linked-guide conventions:

- the fishing root returns to **Полезное о Гуардамаре**;
- every fishing leaf returns to **Рыбалка**;
- the back link appears immediately before the shared footer;
- every card includes the existing project footer:
  `📣 обЪявления Гуардамар`;
- back links and child links are Telegram message links from the existing
  recoverable guide graph, not ad-hoc URLs.

Expected hierarchy:

```text
root
  -> fishing
       -> fishing_shore
       -> fishing_boat
       -> fishing_underwater
       -> fishing_rall
       -> fishing_inland
```

## Calendar engine

No external source is needed for the main seasonal logic.

The bot can calculate the current regime from the local date in
`Europe/Madrid`.

### Guardamar bathing-season regime

The municipal ordinance defines:

- summer: **1 June through 30 September**;
- Semana Santa: Friday before Palm Sunday through Lunes de San Vicente
  inclusive.

For the agreed calculation:

- Semana Santa start = Easter Sunday - 9 days;
- Semana Santa end = Easter Sunday + 8 days.

Examples:

- **2026:** 27 March through 13 April;
- **2027:** 19 March through 5 April.

Do not display a generic phrase such as:

> Semana Santa dates change every year and the bot will notify you.

Instead render the actual dates for the relevant year.

Example outside the Easter period:

> Следующий сезонный период — Semana Santa 2027: 19 марта – 5 апреля.

Example during the period:

> Сейчас действует режим Semana Santa до 5 апреля включительно.

### Deterministic transition events

Core annual transitions remain:

1. day before Semana Santa starts;
2. final day of Semana Santa;
3. 31 May -> summer regime starts 1 June;
4. 30 September -> summer regime ends 1 October.

The card itself should also change immediately when the regime changes, so the
alert and the guide always agree.

## Dynamic card: shore fishing

This is the strongest dynamic card.

### During summer / Semana Santa

Show only the restrictions that currently apply:

- current regime name and exact end date;
- Centre, La Roqueta, Babilònia, El Moncaio:
  24-hour prohibition in bathing zones;
- Els Tossals, Dels Vivers, El Camp, Les Ortigues:
  09:00-21:00 prohibition;
- permanent/common constraints that still matter:
  user/bather priority, >100 m distance, boat-access corridors;
- next transition date;
- licence and official links.

Example opening on 23 September 2026:

> 🗓 **Сейчас действуют летние ограничения**
>
> Купальный сезон в Гуардамаре продолжается **до 30 сентября включительно**.

Then show the two active beach groups.

Finish the seasonal part with:

> 📅 **Следующее изменение — 1 октября**
>
> С 1 октября летние сезонные ограничения перестанут действовать.

### Outside the bathing-season regime

Do **not** keep the eight-beach summer list on the card.

Replace it with a concise current-state block, for example:

> 🗓 **Сейчас сезонные ограничения купального сезона не действуют**
>
> Следующий сезонный период — **Semana Santa 2027: 19 марта – 5 апреля**.

Then show only permanent/common constraints:

- distance and beach-user priority;
- boat-access corridors;
- licence;
- PescaREC/MAPA links.

This is the core value proposition: the user sees the rule that matters today,
not an encyclopaedia of inactive summer rules.

### Licence wording

Use the exact Spanish licence name alongside the Russian explanation:

> **Licencia de pesca marítima de recreo desde tierra**

Do not merely say "морская лицензия".

### PescaREC wording

When fully introduced in the shore card, describe it clearly:

> **PescaREC** — официальное мобильное приложение MAPA для любительской
> морской рыбалки: виды рыб, минимальные размеры, уловы, специальные
> разрешения и актуальные ограничения.

Other cards may use a shorter link label to avoid repeating the full
description.

### MAPA link wording

Do **not** use the Russian word `промыслы` in user-facing copy.

The page contains mixed fishery-opening/closure decisions and "промысел" sounds
commercial/industrial to an ordinary Russian-speaking recreational angler.

Preferred user-facing label:

> **Актуальные ограничения по отдельным видам рыб — MAPA**

or:

> **Актуальные открытия и закрытия ловли отдельных видов — MAPA**

## Dynamic card: boat and kayak

Most rules are static, but one useful live block can be added by reusing
existing beach-flag data.

### No new polling

The bot already fetches and confirms Guardamar beach flags through the existing
SafeBeach/operational-update pipeline.

Do **not** create another SafeBeach request for fishing.

Reuse only the existing **confirmed same-day** status.

### Red-flag live block

If one or more beaches have a confirmed red flag for the current local day,
prepend a compact block such as:

> ⛔ **Сегодня красный флаг:** Centre, La Roqueta
>
> Выход на каяках и аналогичных плавсредствах запрещён.

If:

- no red flag exists -> omit the block;
- no fresh confirmed same-day status exists -> omit the block;
- source data is stale/uncertain -> omit the block.

Never show yesterday's flag status as current.

This feature should not trigger any extra network request.

### 200 m / 50 m wording

Avoid the ambiguous phrase "200 m from the beach".

Explain direction explicitly:

> If there are no buoys, the bathing zone is a strip of water measured **from
> the shoreline out to sea**:
>
> - up to 200 m seaward opposite beaches;
> - up to 50 m seaward opposite other coastline.

The distances are seaward, not along the coast.

### Kayak vs registered vessel

Keep the legal distinction visible:

- non-motorised kayak/canoe / relevant floating artefact:
  `Licencia de pesca marítima de recreo desde tierra`;
- registered recreational vessel:
  `Licencia de pesca marítima de recreo desde embarcación`.

Do not use "small boat" as the legal category.

## Dynamic card: underwater fishing

This card should also render current seasonal state.

### During bathing season

Opening example:

> 🗓 **Сейчас действует сезонный запрет в зонах купания**
>
> До **30 сентября включительно** подводная рыбалка запрещена во всех
> зонах купания Гуардамара.

Then show permanent rules:

- no fishing sunset-to-sunrise;
- breath-hold only;
- buoy and current verified distance requirement;
- loaded speargun restrictions;
- licence/medical requirement.

Show next transition:

> 📅 **С 1 октября этот сезонный запрет закончится.**

### Outside bathing season

Do not keep the summer prohibition as a large inactive block.

Render instead:

> 🗓 **Сейчас сезонный запрет в зонах купания не действует**
>
> Следующий период — **Semana Santa 2027: 19 марта – 5 апреля**.

Then show only permanent underwater rules.

This preserves useful context without implying that no other restrictions apply.

## Dynamic card: rall / esparavel

The user-facing title should be:

> 🕸 **Рыбалка забрасываемой сетью**

The card should explain once that the Valencian method is called
`rall / esparavel`.

### Calendar status

This is also deterministic and requires no external source.

Seasonal closure:

- December;
- January;
- February.

Example on 23 September 2026:

> 🗓 **Сейчас сезонный запрет не действует**
>
> Следующий запрет: **1 декабря 2026 – 28 февраля 2027**.

On 1 December 2026:

> 🚫 **Сейчас действует сезонный запрет**
>
> Рыбалка с rall/esparavel запрещена до **28 февраля 2027 включительно**.
>
> С **1 марта 2027** сезонный запрет закончится.

Leap years must naturally render 29 February where applicable.

### Technical/legal details

The earlier question "what does association / mesh size mean?" was resolved:

- association = a registered association whose main purpose concerns
  conservation/development of the traditional `rall` method; it is not merely
  any fishing club;
- mesh-size requirement = minimum side of the square mesh opening when wet;
  the investigated current value was 20 mm;
- investigated maximum opened net diameter was 6 m.

For UX, either:

1. explain these details in plain language; or
2. keep the card shorter and link to the full GVA conditions.

Do not write an unexplained phrase such as "association and mesh requirements".

## Card: internal waters

Do **not** manufacture dynamic behaviour where no single valid current state
exists.

There is no one Comunitat-wide "continental fishing season" that can safely be
shown as allowed/not allowed.

Keep the card focused on:

- permanent lower-Segura prohibition near Guardamar;
- distinction between licence and permission for a specific water;
- boat navigation dependency;
- `pato / float-tube`;
- recreational net prohibition;
- official GVA map/licence links.

### Lower Segura

The high-value local statement is permanent rather than seasonal:

> From CV-91 bridge to the sea, fishing is prohibited year-round; the mouth /
> coastal-front section is also non-fishable under the reviewed table.

Do not imply that a continental licence overrides this prohibition.

### Human wording for pato

If retained in Russian copy, explain the term on first use:

> **Pato / float-tube** — небольшое надувное рыболовное кресло/плавсредство,
> в котором рыбак находится в воде и передвигается ногами.

Do not assume Russian readers know the Spanish term `pato`.

## Dynamic-data matrix

Current recommended automation boundary:

| Card | Dynamic value | Source | New network work? |
| --- | --- | --- | --- |
| Fishing root | none | static guide graph | no |
| Shore | active seasonal regime, exact dates, next transition | local calendar | no |
| Boat/kayak | confirmed current red flags, only when present | existing SafeBeach/operational state | **no new request** |
| Underwater | active seasonal regime, exact dates, next transition | local calendar | no |
| Rall/esparavel | active closure status, exact dates, next transition | local calendar | no |
| Internal waters | no generic live status | static reviewed rules + links | no |

This is preferable to attaching a separate source/monitor to every card.

## Rendering philosophy

For each leaf:

1. **What applies now?**
2. **What does that mean for me?**
3. **What permanent conditions still matter?**
4. **When does this change next?**
5. **What licence/action do I need?**
6. **Where do I check changing species-specific rules?**
7. Back link.
8. Shared footer.

Avoid:

- listing inactive seasonal restrictions merely because they exist in law;
- raw legal fragments without explanation;
- unexplained Spanish terminology;
- broad "allowed" wording when only one layer of restrictions has expired;
- duplicating full PescaREC explanations on every card.

## Example status on 23 September 2026

For design/regression fixtures, the expected high-level state on
**2026-09-23 Europe/Madrid** is:

- shore: summer restrictions active through 30 September;
- underwater: bathing-zone seasonal prohibition active through 30 September;
- rall/esparavel: seasonal closure not active; next closure starts 1 December;
- boat/kayak: no calendar-wide summer fishing prohibition; optionally show only
  confirmed same-day red flags from existing state;
- internal waters: lower Segura prohibition remains permanent; no generic
  continental seasonal status.

After **1 October 2026**:

- shore card hides the summer beach-group restrictions and shows the next
  calculated seasonal period;
- underwater card hides the active summer-ban block and shows the next
  calculated seasonal period;
- boat/kayak behaviour is unchanged except for same-day flag data;
- rall remains open under this seasonal rule until 30 November.

## Implementation implications

The implementation should create user value without adding source complexity.

Preferred approach:

- pure functions in a small fishing-rules module determine calendar regimes;
- the pinned renderer receives `local_day` and renders the active state;
- no separate fishing scheduler is necessary for card freshness if the existing
  daily guide sync updates the messages;
- seasonal transition alerts can reuse the existing guide-state notice pattern;
- SafeBeach flag data should be reused only if a clean, non-coupled way to read
  the already-confirmed same-day snapshot exists; do not make the fishing guide
  own or duplicate the operational monitor;
- if sharing flag state would introduce ugly coupling or a second source fetch,
  omit the live flag block in V1 rather than overengineer it;
- no MAPA HTML/PDF monitor;
- no OCR;
- no browser;
- no AI;
- no new resident service.

## Remaining implementation-time decisions

Before coding:

1. Decide whether the two `rall/esparavel` transitions should also generate
   public alerts, or only update the card.
2. Decide whether the same-day red-flag block can be reused cleanly from current
   confirmed state without coupling pinned guide to operational-update internals.
3. Re-check exact official wording/values for all high-risk legal constants.
4. Decide whether to display the next seasonal transition only, or also the
   duration of the next regime.
5. Finalise the concise off-season versions of shore and underwater cards.
6. Confirm the official current GVA link for internal-water boat registration.

## Updated product summary

The fishing feature should no longer be thought of as a static mini-wiki.

It should behave as a **date-aware local assistant**:

- it knows which Guardamar seasonal regime is active today;
- it calculates Easter/Semana Santa itself;
- it hides irrelevant inactive rules;
- it tells the user the next known change;
- where possible, it reuses already-confirmed operational data such as red
  flags;
- it does **not** pretend to know changing species/quota law and sends users to
  official PescaREC/MAPA for that layer.

This is the current baseline for the next implementation/design step.

