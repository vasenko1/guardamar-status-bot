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

Render dates from the calculated period for the relevant year, but keep the
public wording centered on the current bathing-season state.

Do not call the spring period "правила Semana Santa" in user-facing copy.

Examples:

> 🗓 **Сегодня действует купальный сезон — до <calculated_end_date> включительно.**

or, outside the bathing period:

> 🗓 **Сегодня и до <calculated_last_unrestricted_date> сезонные ограничения
> на рыбалку на пляжах не действуют.**

### Deterministic transition events

Core annual transitions remain:

1. day before Semana Santa starts;
2. final day of Semana Santa;
3. 31 May -> summer regime starts 1 June;
4. 30 September -> summer regime ends 1 October.

The card should be reconciled by the existing daily guide sync when the regime
changes. On boundary days, copy must remain true across the midnight-to-09:02
window as defined in the later architecture review.

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

> 🗓 **На 23 сентября:** действуют летние ограничения
>
> Купальный сезон в Гуардамаре продолжается **до 30 сентября включительно**.

Then show the two active beach groups.

Finish the seasonal part with:

> 📅 **Следующее изменение — 1 октября**
>
> С 1 октября летние сезонные ограничения перестанут действовать.

### Outside the bathing-season regime

Do **not** keep the eight-beach summer list on the card.

Replace it with the universal current-state block:

> 🗓 **Сегодня и до <calculated_last_unrestricted_date> сезонные ограничения
> на рыбалку на пляжах не действуют.**

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

## Card: boat and kayak — reviewed automation boundary

Most boat/kayak rules are stable. After reviewing the actual guide and
SafeBeach lifecycles, **do not put live beach flags into this pinned card in
V1**.

### Why the earlier red-flag idea is rejected

The guide is reconciled at **09:02**. SafeBeach's approved lifecycle starts
later, at **10:10**, and the separate beach root is then updated through 10:40
and by later operational checks.

Therefore a "today's red flags" block inside the 09:02 fishing card cannot be
both fresh and source-free:

- at 09:02 today's SafeBeach status normally does not exist yet;
- reading yesterday's state would violate freshness rules;
- making the SafeBeach monitor edit the pinned fishing card later would couple
  two intentionally separate lifecycles;
- adding another guide sync after SafeBeach would add scheduling and Telegram
  churn only for this convenience feature;
- making a second SafeBeach request is explicitly unnecessary and violates the
  one-lifecycle principle.

Keep the operational boundary clean:

- the fishing card states the durable rule: **a red flag prohibits going to sea
  on kayaks / analogous floating craft**;
- the existing daily **Пляжи Гуардамара сегодня** lifecycle owns current flag
  publication;
- the pinned fishing guide does not copy, cache or mirror live flags.

This removes a race, a stale-data risk and cross-state coupling.

### 200 m / 50 m wording

Avoid the ambiguous phrase "200 m from the beach".

Explain direction explicitly:

> If there are no buoys, the bathing zone is a strip of water measured **from
> the shoreline out to sea**:
>
> - up to 200 m seaward opposite beaches;
> - up to 50 m seaward opposite other coastline.

The distances are seaward, not along the coast.

Do **not** turn these fallback distances into map circles or polygons.

The municipal 2023 buoying plan shows that marked central bathing zones can
have a physically buoyed outer edge at another distance (for example 150 m in
that plan). When a zone is marked, the physical buoys define the relevant
boundary; the ordinance's 200 m / 50 m rule is the fallback for unmarked
coast. A static map point cannot represent either boundary safely.

Official municipal buoying-plan source reviewed:

https://www.guardamardelsegura.es/wp-content/uploads/2023/10/20231004_13-PLANO-DE-BALIZAMIENTO-DE-LAS-PLAYAS-2023.pdf

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

Opening uses the same calculated bathing-season status as the shore card:

> 🗓 **Сегодня действует купальный сезон — до <calculated_end_date> включительно.**
>
> В этот период подводная рыбалка запрещена во всех зонах купания Гуардамара.

Then show permanent rules:

- no fishing sunset-to-sunrise;
- breath-hold only;
- buoy and current verified distance requirement;
- loaded speargun restrictions;
- licence/medical requirement.

On the final restricted day, the status line itself may say when the restriction
ends; do not add a second future-looking paragraph on ordinary days.

### Outside bathing season

Do not keep the inactive prohibition as a large block.

Render the same universal off-season status pattern:

> 🗓 **Сегодня и до <calculated_last_unrestricted_date> сезонный запрет в
> зонах купания не действует.**

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

User-facing rall status should also use current-state wording rather than a
calendar dump.

Before the closure:

> 🗓 **Сегодня сезонный запрет не действует — до 30 ноября включительно.**

During the closure:

> 🚫 **Сегодня действует сезонный запрет — до <last_february_day> включительно.**

On the final closure day, the same boundary-safe pattern may add:

> С **1 марта** этот сезонный запрет перестанет действовать.

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
| Boat/kayak | no live field in the pinned card; current flags remain in the existing beach lifecycle | static reviewed rules | no |
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
- boat/kayak: no calendar-wide summer fishing prohibition; current red flags
  remain exclusively in the existing daily beach lifecycle;
- internal waters: lower Segura prohibition remains permanent; no generic
  continental seasonal status.

After **1 October 2026**:

- shore card hides the summer beach-group restrictions and shows the next
  calculated seasonal period;
- underwater card hides the active summer-ban block and shows the next
  calculated seasonal period;
- boat/kayak behaviour is unchanged; operational beach flags remain outside
  the pinned fishing card;
- rall remains open under this seasonal rule until 30 November.

## Implementation implications

The implementation should create user value without adding source complexity.

Preferred approach:

- pure functions in a small fishing-rules module determine calendar regimes;
- the pinned renderer receives `local_day` and renders the active state;
- no separate fishing scheduler is necessary for card freshness if the existing
  daily guide sync updates the messages;
- seasonal transition alerts can reuse the existing guide-state notice pattern;
- do not read or mirror SafeBeach operational state from the fishing guide;
- do not make the SafeBeach lifecycle edit pinned fishing messages;
- keep current beach flags in the existing daily beach root and operational
  replies;
- no MAPA HTML/PDF monitor;
- no OCR;
- no browser;
- no AI;
- no new resident service.

## Remaining implementation-time decisions

Before coding:

1. Decide whether the two `rall/esparavel` transitions should also generate
   public alerts, or only update the card.
2. Verify every map target once before implementation, especially the legal
   boundary landmark at the CV-91 bridge and the Segura mouth.
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
- operational beach flags remain in their existing dedicated lifecycle rather
  than being mirrored into pinned fishing cards;
- it does **not** pretend to know changing species/quota law and sends users to
  official PescaREC/MAPA for that layer.

This is the current baseline for the next implementation/design step.

---

# 2026-09-23 review — maps, automation, UX and architecture

This review was performed against the current linked-guide, guide-sync and
SafeBeach architecture before implementation. It supersedes any earlier
research suggestion that would make the fishing guide mirror live SafeBeach
flags.

## Review result

The concept is viable **without a new source, dependency, daemon, scheduler or
map API** if the following boundaries are kept:

1. calendar-derived fishing status belongs to the existing 09:02 guide sync;
2. operational beach flags remain in the existing SafeBeach/beach-root
   lifecycle;
3. maps are static presentation links only;
4. legal facts continue to come from official legal/municipal sources;
5. no point marker is presented as a legal polygon or boundary.

This fits the repository's existing principles: one-shot processes, official
sources, deterministic rendering, compact atomic state, fail-closed source
handling and a self-healing Telegram guide graph.

## Automation review

### Approved dynamic cards

The following values can be computed locally with no I/O:

| Card | Locally computed value | Runtime source |
| --- | --- | --- |
| Shore | current Guardamar bathing-season regime, exact dates, next transition | local calendar |
| Underwater | whether the bathing-zone seasonal prohibition is active, exact dates, next transition | local calendar |
| Rall/esparavel | whether Dec-Feb seasonal closure is active, exact dates, next transition | local calendar |
| Boat/kayak | none | static rules only |
| Internal waters | none globally valid | static reviewed local rules + official links |

No separate monitor belongs to a card merely because the card exists.

### Easter / Semana Santa calculation

Implement one deterministic Gregorian Easter calculation with the Python
standard library only.

Derive:

- start = Easter Sunday - 9 days;
- end = Easter Sunday + 8 days.

Tests must cover multiple years, including the already reviewed examples:

- 2026: 27 March - 13 April;
- 2027: 19 March - 5 April;

and a wider multi-year range to catch month-boundary cases.

Do not store annual Easter dates in state.

### Rall closure

The Dec-Feb closure is also pure calendar logic.

Tests must include:

- 30 November -> next day closed;
- 1 December -> closed;
- 28 February in a normal year;
- 29 February in a leap year;
- 1 March -> open under this seasonal rule.

### Daily guide sync is enough for card rendering

The existing **09:02** guide sync already receives `local_day` and reconciles
the managed Telegram graph. Use it for fishing-card rendering.

Do not add:

- a fishing cron;
- an internal scheduler;
- a midnight job;
- a second daily guide lifecycle.

### Midnight / stale-card risk

A date-aware card edited only at 09:02 can otherwise become semantically wrong
between midnight and 09:02 on a transition day.

Use two protections instead of a new cron.

**1. Date the dynamic status visibly.**

Prefer:

> 🗓 **На 23 сентября:** действуют летние ограничения...

rather than an undated:

> Сейчас действуют летние ограничения.

If a scheduled guide sync is missed, the visible date makes stale content
detectable instead of presenting it as timeless current fact.

**2. Use transition-safe copy on the day before a boundary.**

For example on 30 September:

> До **30 сентября включительно** действуют летние ограничения.  
> С **1 октября** этот сезонный режим не действует.

This remains factually true after midnight until the next 09:02 reconciliation.

The same pattern applies to Semana Santa start/end and the rall 1 Dec / 1 Mar
boundaries.

This is preferable to adding a 00:01 cron solely to keep three guide messages
perfectly synchronized with midnight.

### Seasonal alerts — final product model

Fishing transition alerts are approved as a product concept, but they must be
specific, grouped and linked back into the pinned fishing guide.

The alert is not a generic "season changed" message. It must say **which kind of
fishing is affected and what changes**.

#### Source of dates

All dates come from the same deterministic calendar functions used by the
cards.

For Guardamar bathing-season restrictions:

- summer starts 1 June and ends 30 September;
- the Semana Santa bathing period is calculated every year from Gregorian
  Easter;
- Semana Santa start = Easter Sunday - 9 days;
- Semana Santa end = Easter Sunday + 8 days;
- the final unrestricted day before that period is therefore one day before
  the calculated start;
- the first unrestricted day after the period is one day after the calculated
  end.

Do not hardcode user-facing dates such as "18 March" or "5 April" in annual
tables. Compute them from the year.

For `rall / esparavel`:

- seasonal closure starts 1 December;
- seasonal closure ends on the last day of February;
- leap years must naturally use 29 February.

#### One transition -> one alert

Do not send one message per card.

If the **same date and same transition** affects several fishing methods, send
one grouped alert and list every affected method explicitly.

For the Guardamar bathing-season transition, both of these are affected:

- 🏖 **Морская рыбалка с берега**;
- 🤿 **Подводная рыбалка**.

They should therefore normally share one alert.

Do not merge unrelated transitions just because they happen near each other.

Examples:

- shore + underwater bathing-season change -> one grouped alert;
- `rall / esparavel` closure -> its own alert;
- SafeBeach red flag -> not a seasonal alert; it stays in the existing beach
  lifecycle and may update the kayak card projection.

#### Alert links

Every affected fishing method named in an alert must link directly to its
managed pinned guide card.

For example:

- 🏖 **Морская рыбалка с берега** -> `fishing_shore`;
- 🤿 **Подводная рыбалка** -> `fishing_underwater`;
- 🕸 **Рыбалка забрасываемой сетью** -> `fishing_rall`.

If several methods are grouped in one alert, include all corresponding card
links in the same message.

Do not link only to the generic fishing navigator when a more specific affected
card exists.

The alert renderer should build these URLs from the actual managed Telegram
message IDs through the existing `telegram_message_link(...)` mechanism.
Never hardcode Telegram message URLs.

#### Footer

Every fishing alert must use the shared project footer through
`with_footer(...)`:

> 📣 **обЪявления Гуардамар**

No fishing alert is exempt from branding.

#### When to alert

For a new restriction that starts tomorrow, the most useful notification is
**the day before**.

Example structure:

> 🏖🤿 **Рыбалка на пляжах — с завтра меняются правила**
>
> С **19 марта** начинается купальный сезон.
>
> 🏖 **Морская рыбалка с берега:** на Centre, La Roqueta, Babilònia и
> El Moncaio в зонах купания рыбалка будет запрещена круглосуточно; на
> Els Tossals, Dels Vivers, El Camp и Les Ortigues — разрешена только
> с 21:00 до 09:00.
>
> 🤿 **Подводная рыбалка:** в зонах купания будет запрещена.
>
> Ограничения будут действовать до **5 апреля включительно**.
>
> 🏖 **Морская рыбалка с берега** · 🤿 **Подводная рыбалка**
>
> 📣 **обЪявления Гуардамар**

The dates in that example are computed for the relevant year, not static copy.

For the end of a restriction, the most useful notification is **on the final
restricted day**, because it can say exactly when fishing becomes less
restricted.

Example structure:

> 🏖🤿 **Рыбалка на пляжах — сегодня последний день ограничений**
>
> Сегодня заканчивается купальный сезон.
>
> С **6 апреля** сезонные ограничения перестанут действовать.
>
> Общие правила безопасности и другие ограничения сохраняются.
>
> 🏖 **Морская рыбалка с берега** · 🤿 **Подводная рыбалка**
>
> 📣 **обЪявления Гуардамар**

The same template is used for the 30 September -> 1 October transition.

For `rall / esparavel`:

**30 November:**

> 🕸 **Рыбалка забрасываемой сетью — с завтра начинается сезонный запрет**
>
> С **1 декабря** рыбалка с rall / esparavel запрещена.
>
> Запрет действует до **последнего дня февраля включительно**.
>
> 🕸 **Рыбалка забрасываемой сетью**
>
> 📣 **обЪявления Гуардамар**

The actual last-February date should be rendered explicitly for the year
(28 or 29 February).

**Last day of February:**

> 🕸 **Рыбалка забрасываемой сетью — сегодня последний день запрета**
>
> С **1 марта** этот сезонный запрет перестанет действовать.
>
> 🕸 **Рыбалка забрасываемой сетью**
>
> 📣 **обЪявления Гуардамар**

#### Alert volume

Expected planned fishing alerts in a normal year:

- one before the calculated Semana Santa bathing period starts;
- one on its calculated final day;
- one on 31 May;
- one on 30 September;
- one on 30 November for `rall`;
- one on the final day of February for `rall`.

That is normally **six planned alerts per year**.

The alert count must not grow merely because two cards share the same
transition.

#### State and delivery

Reuse the existing guide seasonal-notice delivery pattern:

- deterministic transition key;
- one confirmed message per key;
- explicit ambiguous-delivery state;
- no deliberate resend after an uncertain Telegram send;
- links resolved from managed pinned message IDs;
- footer applied before delivery.

A single bathing-season transition key may represent both shore and underwater
cards because the date/reason is shared.

Do not overload the existing pool `season_notice` state. Fishing should have
its own narrow state fields.

## SafeBeach / red-flag projection — revised decision

The earlier V1 rejection of live red flags inside the boat/kayak card was too
strict.

The important distinction is:

- **do not add another SafeBeach source request or scheduler**;
- **do allow an already accepted normalized SafeBeach fact to update a dependent
  guide card**.

This is a derived presentation of an existing verified fact, not a second
source lifecycle.

### Trigger point

The existing SafeBeach workflow remains the sole owner of source collection,
freshness validation and confirmation.

After a SafeBeach status has already been accepted by the existing lifecycle:

- during the 10:10-10:40 initial beach-root cycle; or
- after a later confirmed operational flag change,

the same accepted data may trigger a best-effort edit of the managed
`fishing_boat` card.

There is:

- no new SafeBeach HTTP request;
- no new cron;
- no second polling loop;
- no browser;
- no new service.

The only additional external operation is a Telegram `editMessageText` on an
already managed guide message when the red-flag projection needs refreshing.

### Why this is architecturally acceptable

The dependency is one-way:

```text
SafeBeach -> validated BeachStatus -> public beach lifecycle
                              \-> derived kayak red-flag projection
```

The fishing guide must never fetch, parse or validate SafeBeach itself.

It consumes only the already-normalized domain fact after the existing
SafeBeach policy has accepted it.

This preserves the repository layering: source-specific parsing stays in the
adapter/lifecycle, while a second renderer may use the normalized model.

### Conservative red-flag projection

The fishing card should be **warning-only**.

If a current accepted status explicitly contains a red flag, show it.

Do not show:

- "all clear";
- "no red flags";
- green reassurance;
- a global permission claim.

A partial SafeBeach response must never clear a previously confirmed same-day
red flag merely because that beach is absent.

For the small daily derived projection, update only beaches explicitly present
in the accepted observation:

- observed `red` -> add/keep that beach in the projection;
- observed `yellow` or `green` -> remove that beach from the projection;
- beach absent from this observation -> preserve its previous same-day
  projection state.

This conservative merge is **only for the derived kayak-warning projection**.
It must not alter the existing ADR 0064 rule that the public beach root itself
represents each whole SafeBeach response and does not synthetically merge
missing beaches.

The derived projection resets on the next local day.

### State ownership

Store only the minimal daily derived red set in the existing publication
lifecycle state, not in `PinnedGuideState`.

Reason:

- `PublicationState` already owns the current day's accepted beach facts;
- `PinnedGuideState` should remain about guide-message IDs/recovery rather than
  operational beach semantics.

A minimal field such as a sorted list of internal beach keys is sufficient.
No raw SafeBeach payload, history or timestamps need be duplicated.

### Card refresh behaviour

At 09:02 the normal guide reconciliation renders `fishing_boat` without any
previous-day live red block.

When the first accepted SafeBeach observation arrives later:

- merge its explicitly observed flag states into the daily derived red set;
- edit only `fishing_boat`;
- if the rendered text is unchanged, Telegram `MESSAGE-NOT-MODIFIED` is
  idempotent success.

Later accepted observations repeat the same local projection.

Later operational changes should update the projection only after the existing
confirmation policy accepts them.

### Failure isolation

A dependent fishing-card edit is **best effort** and must not make the primary
SafeBeach publication fail.

If:

- the pinned-guide lock is busy;
- the fishing message is temporarily missing;
- Telegram edit fails;

the beach lifecycle remains successful.

A later accepted SafeBeach observation may retry the same projection. The normal
09:02 guide reconciliation remains the structural recovery path for a missing
managed card.

Do not invoke a full pinned-guide reconciliation from the SafeBeach path merely
to repair this optional live block.

### Locking

Do not hold unrelated state locks while waiting on Telegram if avoidable.

Recommended sequence:

1. accept/persist the SafeBeach/publication result;
2. compute/persist the tiny derived red projection;
3. release the beach/publication critical section;
4. acquire `PinnedGuideState.exclusive_run()`;
5. read the known `fishing_boat` message ID;
6. edit that one card;
7. release the pinned-guide lock.

This avoids a new lock-order dependency.

### User-facing block

Only when the derived red set is non-empty:

> ⛔ **Красный флаг сегодня**
>
> **Centre / Babilònia · La Roqueta**
>
> При красном флаге выход в море на каяках и аналогичных плавсредствах
> запрещён.

Use the same public beach naming already used by the bot
(`Centre / Babilònia`, `Roqueta`, `Vivers`, `Montcaio`, `Camp`,
`Ortigues`), rather than inventing a second SafeBeach label system.

If the red set is empty, omit the live block entirely.

The durable rule still remains in the card even when no live block is shown:

> При красном флаге выход в море на каяках и аналогичных плавсредствах
> запрещён.

## Map-link design

### Maps are presentation, never evidence

Follow the precedent already used by the earthquake workflow and pinned guide:
Google Maps is only a way for the user to locate a verified place.

Never use Google Maps to establish:

- whether fishing is legal;
- the name or legal extent of a beach;
- a bathing-zone boundary;
- the CV-91 legal boundary;
- a marine-reserve boundary.

Those facts come from the ordinance, DOGV, GVA or MAPA.

### No runtime map/geocoding source

Do not add:

- Google Maps API;
- geocoding API;
- Nominatim requests;
- browser automation;
- map scraping;
- map tiles;
- a map cache.

Map URLs are static constants or deterministic URLs built from reviewed
coordinates/search terms.

### Preferred link form

For boundary-sensitive landmarks such as:

- Puente de la CV-91;
- the Segura mouth;

prefer a once-verified decimal coordinate and a transparent Google Maps URL:

`https://www.google.com/maps/search/?api=1&query=<lat>,<lon>`

rather than a vague text search.

For named beaches, either:

- use once-verified representative coordinates; or
- use an explicit disambiguated search query containing the full beach name and
  `Guardamar del Segura`.

Coordinates are preferred when the search name is ambiguous.

Avoid introducing a URL-shortening step purely to save characters. Existing
`maps.app.goo.gl` links may remain where already reviewed, but new fishing
locations should favour transparent URLs that are easy to audit in source.

### Legal name and map name are separate concerns

Do not derive user-facing legal labels from Google Maps or SafeBeach.

The ordinance uses the legal/local beach names, while other systems may use
different spelling or grouping. In particular:

- SafeBeach combines Centre / Babilònia operationally;
- source spellings vary around Moncaio / Montcaio / Moncayo.

The fishing card should use the wording chosen from the authoritative fishing
source. The map target is allowed to use a different search spelling internally
if necessary to land on the correct place.

Store display label and map target separately.

### Which places should be clickable

Useful map targets:

**Shore card**
- Centre;
- La Roqueta;
- Babilònia;
- El Moncaio;
- Els Tossals;
- Dels Vivers;
- El Camp;
- Les Ortigues.

**Boat/kayak**
- Tabarca may be a location link when mentioned;
- the separate MAPA reserve link remains the legal-information action.

**Internal waters**
- Puente de la CV-91 — particularly important because it is the reviewed
  transition point between ZPL and VP;
- Desembocadura del Río Segura — useful orientation for the closed lower
  section.

Do not add a map link merely because a geographic noun appears. For example,
linking every occurrence of "Guardamar", "Mediterranean", or "Río Segura" adds
noise without improving a decision.

### A point is not a zone

Never label a location point as:

- "запрещённая зона";
- "граница зоны купания";
- "граница заповедника";

unless the linked resource actually represents that geometry.

Correct semantics:

- **Playa Centre** -> representative point for the beach;
- **Puente CV-91** -> the bridge used as the legal textual boundary;
- **Устье Segura** -> representative point for the mouth;
- **Tabarca** -> island/location.

The legal extent remains in text and the official source.

### 200 m / 50 m must not become a static map overlay

The ordinance fallback for an unmarked coast is measured from shoreline
seaward: 200 m opposite beaches, 50 m opposite other coast.

However, a marked bathing zone is governed by its buoys. The reviewed municipal
2023 buoying plan shows central marked zones with an outer buoy line at 150 m.

Therefore:

- do not draw a universal 200 m beach buffer;
- do not hardcode a 150 m universal buffer either;
- do not generate polygons;
- say "use the buoys where the zone is marked";
- explain 200/50 m only as the ordinance fallback when it is not marked.

### Mobile link density

Do not turn every repeated occurrence of a place into a link.

Rule:

> link the first actionable occurrence of a concrete place in the relevant
> card.

For a list of beaches, use no more than **two linked beach names per visual
line**, matching the project's existing phone-width guide style.

Example:

```text
🚫 Centre · La Roqueta
   Babilònia · El Moncaio
```

Each name may be its own map link.

Avoid adding a second separate `📍` line with the same eight beaches if the
names themselves are already linked.

For CV-91 / Segura mouth, a compact dedicated line is clearer:

> 📍 **Мост CV-91** · **Устье Segura**

### Message-length risk

Eight HTML map links plus official GVA/MAPA URLs can materially increase the
raw Telegram message string.

Every rendered fishing state must have a regression test asserting:

- raw rendered message length <= 4096;
- exactly one shared footer on cards that require it;
- expected back-navigation link exists;
- no duplicate map link for repeated place mentions.

If full query URLs make the shore card too large, prefer verified coordinate
URLs or shorten copy before considering opaque short links.

Do not split one user scenario into extra cards only to solve an avoidable URL
length problem unless the rendered card actually exceeds the limit.

## Navigation / footer architecture review

The existing pinned guide already owns:

- message IDs;
- parent/child Telegram links;
- recreation after `MESSAGE-NOT-FOUND`;
- bounded reconciliation;
- atomic pinned-guide state.

Fishing should be another subtree of this graph, not a separate publication
system.

Recommended keys:

- `fishing`;
- `fishing_shore`;
- `fishing_boat`;
- `fishing_underwater`;
- `fishing_rall`;
- `fishing_inland`.

Parent relationships:

```text
fishing -> root
all fishing leaves -> fishing
```

User-approved UX for this subtree:

- the fishing navigator itself has a visible **⬅️ Полезное о Гуардамаре** link
  and shared footer;
- every leaf has **⬅️ Рыбалка** and shared footer.

This is compatible with the existing guide even though some older compact
navigators omit the footer; the activities/places-style cards already show that
a linked category card may be a normal branded guide message.

Do not create inline Telegram keyboard state; the existing product uses linked
messages in message text.

## Module-boundary review

Avoid adding all legal/calendar copy directly to the already large
`pinned.py`.

A minimal clean split is preferable:

- one small pure fishing module owns calendar calculations, reviewed constants,
  map targets and fishing body rendering;
- `pinned.py` continues to own the Telegram message graph, parent links,
  footer/back-link wrapping and reconciliation;
- `guide.py` passes `local_day` as it already does and owns only due-notice
  delivery/state.

The fishing module must have:

- no HTTP;
- no filesystem state;
- no Telegram calls;
- no background work;
- no AI;
- no third-party dependency.

Do not create classes, repositories, generic rule engines or a map service.
Plain constants + pure functions are sufficient.

An acceptable pattern is for the fishing module to return card bodies, while
`pinned.py` applies the existing navigation/footer wrapper. This keeps one
owner for guide navigation semantics and avoids duplicating recovery logic.

## Failure and recovery review

### Calendar rendering

Pure date calculations do not fail due to network.

If the whole 09:02 guide job fails for an unrelated reason, the next invocation
uses existing guide recovery semantics. The visible "На <date>" status line is
important because it prevents an old legal-status card from masquerading as an
undated current fact.

### Map links

A broken external map link must not affect guide publication.

No runtime validation of Google Maps should be added. Verify targets in tests
and review them manually before release.

### Telegram ambiguity

Fishing cards automatically inherit the existing pinned-guide rule:

- ambiguous send -> mark uncertain / fail closed;
- exact message-not-found -> recreate and reconcile links;
- message-not-modified -> idempotent success.

Do not add fishing-specific delivery state for cards.

### Seasonal alert ambiguity

If fishing transition alerts are implemented, use the same explicit uncertain
marker shape as current guide seasonal notices. Do not retry an ambiguous send
as if it definitely failed.

## UX review

The final UX should optimize for the question:

> "I want to fish this way today. What applies to me?"

Each dynamic leaf should therefore use this order:

1. dated current regime;
2. concrete consequence for this fishing method;
3. permanent local safety/legal constraints that still matter;
4. next known calendar change;
5. exact licence name;
6. one or two official actions/links;
7. back navigation;
8. footer.

Maps support "where is that place?" and should not interrupt the legal
explanation.

Do not:

- show inactive seasonal beach lists off-season;
- repeat the full PescaREC explanation on every card;
- repeat the same map link multiple times;
- show a green/no-red flag as reassurance in the fishing card;
- make "no seasonal restriction" read as "fishing is allowed";
- expose internal terms such as `VP`, `ZPL`, `artefacto flotante` without
  explaining them in normal Russian.

## Overengineering review

Rejected as unnecessary:

- one monitor/source per fishing card;
- a fishing daemon;
- another SafeBeach fetch;
- mirroring raw/whole operational state into pinned guide state;
- midnight cron;
- map/geocoding API;
- generated map polygons;
- generic legal-rule engine;
- generic notification framework;
- database;
- new dependency;
- AI-generated legal copy;
- automatic MAPA PDF interpretation.

The remaining implementation is small:

- six managed guide messages;
- pure calendar calculations;
- reviewed static map targets;
- one tiny daily derived red-flag projection in publication state;
- a targeted best-effort edit of `fishing_boat` after accepted SafeBeach facts;
- a few additional guide-state fields only if public transition alerts are
  approved;
- tests.

## Required tests before implementation is accepted

### Calendar

- Easter/Semana Santa dates across a multi-year table;
- exact first/last day inclusion;
- day-before and day-after states;
- 1 Jun / 30 Sep boundaries;
- Dec-Feb rall closure;
- leap-year Feb 29;
- next-transition calculation.

### Transition-safe UX

Render at least:

- ordinary summer day;
- 30 September;
- 1 October;
- day before Semana Santa;
- first and last Semana Santa days;
- off-season winter day;
- 30 November;
- 1 December;
- last day of February;
- 1 March.

Verify that boundary-day text stays true across the midnight-to-09:02 stale
window.

### Maps

- every approved location has exactly one reviewed map target;
- CV-91 bridge and Segura mouth use exact verified targets;
- legal display names are independent of map-provider labels;
- no URL claims to represent a legal zone/polygon;
- map links are static and do not require network in tests.

### Guide graph

- fishing root linked from main root;
- all five leaves linked from fishing root;
- every leaf returns to fishing;
- fishing root returns to main root;
- deleted fishing leaf is recreated and all dependent links converge;
- each branded fishing card has exactly one footer;
- all rendered seasonal variants remain <= 4096 raw characters.

### Live kayak red-flag projection

- first current partial response with one red beach adds the warning;
- another partial response omitting that beach does **not** clear it;
- an explicit newer green/yellow observation for that beach clears it;
- a second red beach is added without losing the first;
- next local day starts with no inherited red projection;
- no green/all-clear block is rendered;
- the projection uses public `BEACH_NAMES` labels;
- Telegram `MESSAGE-NOT-MODIFIED` is success;
- pinned-guide lock contention does not fail the primary beach lifecycle;
- missing `fishing_boat` message does not trigger a full guide rebuild from the
  SafeBeach workflow;
- no additional SafeBeach fetch is made for the projection.

### Alert state, if approved

- one notice per transition key;
- shore + underwater share the same bathing-season transition alert;
- ambiguous send does not deliberately duplicate;
- missed run does not create a misleading retroactive "tomorrow" alert.

## Final reviewed baseline

The recommended V1 is:

- **calendar-dynamic:** shore, underwater, rall;
- **event-driven live projection:** boat/kayak may show confirmed same-day red flags from the existing SafeBeach lifecycle;
- **static where no safe global live state exists:** internal waters;
- **maps are reviewed static location links, not data sources or legal
  boundaries;**
- **no new scheduler, network source, dependency or service;**
- **existing pinned-guide recovery/navigation owns all six messages;**
- **every dynamic status is visibly dated and boundary-safe.**

This is the architecture/UX baseline to implement from.



---

# 2026-09-23 follow-up — accepted event-driven synchronization

After reviewing the user's proposed "extra trigger" idea against the actual
code, the final recommendation is to **synchronize the kayak card from the
existing accepted SafeBeach lifecycle**, not from the 09:02 schedule alone.

This supersedes the previous statement that live flags must remain completely
outside the pinned guide.

The key reason is that the extra work is not source collection. The SafeBeach
request has already happened. The bot can project that verified normalized fact
into one additional managed Telegram message at negligible runtime cost.

Preferred V1:

```text
09:02 guide sync
  -> renders boat/kayak card with no stale live block

10:10-10:40 SafeBeach accepted current observations
  -> existing beach-root lifecycle
  -> merge explicit observed flags into tiny same-day red projection
  -> best-effort edit fishing_boat

later confirmed SafeBeach changes
  -> existing operational confirmation
  -> update same projection
  -> best-effort edit fishing_boat
```

No new cron or command is required.

The live block is additive safety information only. Absence of the block is
never rendered as an all-clear claim.

This preserves user value while keeping the source architecture single-owner
and lightweight.

---

# 2026-09-23 final editorial and calendar consolidation

This section records the final discussion about card wording, date calculation
and alerts. It supersedes earlier examples where the text was split into
separate "summer", "Semana Santa" and "winter" card templates.

## One natural card template, small dynamic status block

The shore card should be mostly one stable human-written message.

Only the short status block at the top and the visibility of the
bathing-season beach restrictions change through the year.

Do not create three independently maintained full copies of the card.

### Status variants

#### Active bathing period

Generic template:

> 🗓 **Сегодня действует купальный сезон — до <end_date> включительно.**

The `end_date` is computed:

- 30 September for the summer period;
- calculated Semana Santa end for the spring period.

Do not call the spring state "правила Semana Santa". Semana Santa is not a
separate fishing-rule type in the user experience; it is another period in
which Guardamar treats the coast as being in the bathing season.

#### Outside bathing period

Generic template:

> 🗓 **Сегодня и до <last_unrestricted_date> сезонные ограничения на рыбалку
> на пляжах не действуют.**

The date is always computed from the next bathing-period start:

`last_unrestricted_date = next_bathing_start - 1 day`.

Examples such as 18 March must never be hardcoded because the Easter-derived
period moves every year.

#### Final unrestricted day before restrictions start

Generic template:

> 🗓 **Сегодня последний день без сезонных ограничений. С <start_date>
> начинается купальный сезон.**

#### Final restricted day

Generic template:

> 🗓 **Сегодня последний день купального сезона. С <first_unrestricted_date>
> сезонные ограничения на рыбалку на пляжах перестанут действовать.**

This special boundary copy remains true across the midnight-to-09:02 stale-card
window.

## Seasonal beach details

When the bathing season is active, show the beach-specific restrictions:

> 🚫 На пляжах **Centre, La Roqueta, Babilònia, El Moncaio** в пределах
> **зон купания** рыбалка с берега запрещена **круглосуточно**.
>
> 🌙 На пляжах **Els Tossals, Dels Vivers, El Camp, Les Ortigues** рыбалка с
> берега разрешена только **с 21:00 до 09:00** при соблюдении общих правил.

Do not add the word "сейчас" inside the 24-hour sentence. The status block above
already tells the user why the restriction currently applies and until when.

When the bathing season is not active, hide both beach-group paragraphs. The
user does not need a long list of inactive seasonal rules.

## General shore-safety block

Keep the common beach rules in one visually distinct quoted block:

> 👥 Рыбачить можно только при отсутствии людей поблизости и на расстоянии
> более **100 м от них**. Если появляются отдыхающие или купающиеся, удочки и
> снасти нужно убрать.
>
> 🚤 Нельзя рыбачить в обозначенных коридорах, через которые лодки и другие
> плавсредства выходят в море и возвращаются на берег.

This block is useful both in and outside the bathing season.

## Plain-language editorial rules

User-facing Russian should use basic everyday words.

Avoid bureaucratic/canonical wording when a simpler word is accurate.

In particular:

- do not say `ординанса` in public copy;
- prefer `правила Гуардамара`, `городские правила`, or omit the legal-source
  label entirely when it does not help the user;
- avoid repeated roots/phrases in adjacent sentences;
- prefer direct statements such as `рыбалка запрещена` / `рыбалка разрешена
  только с 21:00 до 09:00`;
- future dates are shown only when they directly explain when the current
  restriction starts or ends;
- do not mention the next distant Semana Santa merely as trivia.

The legal source remains attached as an official link/evidence; the Telegram
copy itself should read like normal Russian.

## Stable shore-fishing facts worth keeping

The card may retain stable high-value rules that do not require daily
monitoring, provided they are re-verified before implementation:

- exact GVA licence name for shore marine fishing;
- maximum two rods per licence;
- general recreational catch limit and its qualification for species-specific
  rules;
- undersized fish must be returned immediately;
- recreational catch may not be sold.

Do not copy a static species/minimum-size table into the card. Species-specific
limits, closures and permissions belong to PescaREC/MAPA because that layer can
change.

## PescaREC copy

Preferred plain-language form:

> С **20 марта 2026 года использование PescaREC обязательно** для морской
> любительской рыбалки. PescaREC показывает виды рыб, минимальные размеры для
> вылова, обязательные декларации уловов, специальные разрешения и сообщения о
> действующих ограничениях.

Preferred MAPA action label:

> 🚦 **Список актуальных разрешений и запретов на вылов отдельных видов рыбы**

## Alert/product relationship

Cards answer:

> **Что действует сегодня?**

Alerts answer:

> **Что существенно меняется с завтра / после сегодняшнего дня?**

The same deterministic date engine must feed both. Card and alert dates must
never be calculated independently.

When several fishing methods share the same date and legal transition, one
alert groups them and links every affected pinned card.

Every alert includes the shared footer.

This is the current editorial/product baseline for implementation.

