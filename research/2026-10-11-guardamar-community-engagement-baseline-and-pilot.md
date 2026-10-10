# Guardamar community engagement — historical baseline, guide gap audit and six-week pilot

- Status: **Research / proposed pilot — NOT an accepted ADR or an implementation authorization**
- Research date: **2026-10-11**, timezone Europe/Madrid
- Scope: Russian-/Ukrainian-language local Telegram community, «обЪявления Гуардамар» (public supergroup), compared with «НАШИ В ГУАРДАМАРЕ🙂».
- Repository baseline at research start: main **f6ac620a89cbf8cc54d7c9abbbbb81f0e044c01a**
- Production changes: **none**. No bot commands, Telegram sends, deployment, cron changes, rules edits, data collection or new infrastructure were executed as part of this research.

## 1. Question and executive decision

How can the relatively new, primarily announcement/information-oriented «обЪявления Гуардамар» gradually acquire useful **resident-to-resident conversations** without turning into a noisy chat, undermining advertising, duplicating its pinned guide or risking its low-cost Termux services?

**Recommendation:** a small, reversible six-week editorial pilot, provisionally 2026-10-12 through 2026-11-22, with separate tracks for (1) genuine resident questions and helpful answers, (2) emotional affiliation through already-working city imagery, and (3) **rare, manually triggered, consequential polls**. Keep advertising rules unchanged during the pilot. Prioritize real helpful answers, not nominal engagement or daily polls. Do not build a generic Engagement Engine before validating demand.

**Critical correction from the user's review:** the pinned guide ALREADY provides airport access, urban lines 1/2, and detailed recurring activities/children's sections. Earlier suggested first-poll choices such as “how to get to the airport without a car”, “city bus routes”, and “municipal clubs/children's sections” incorrectly proposed work that already exists. Do **not** ask residents which of these to add; instead test missing *practical experience/procedure* beyond existing reference cards. Source details: §3 below.

## 2. Sources, snapshot identity and reproducibility

### 2.1 Telegram exports supplied by the operator (not committed)

Both originals contain user identities, text, contacts and possibly sensitive contextual data; **do not commit raw exports, phone numbers, author names, user IDs or conversation copies** to this repository.

| Export file in working conversation | Group | Exported message date range | Message items | SHA-256 of JSON |
| --- | --- | --- | ---: | --- |
| result.json | НАШИ В ГУАРДАМАРЕ🙂 | 2024-01-02 10:34:57 to 2026-10-10 16:40:39 | 12,722 | bc5419d72de055cf8b2a9c173fb0d9732b1b8d6a4d9778085cdd733d3b830907 |
| result(1).json | обЪявления Гуардамар | 2026-01-01 12:03:48 to 2026-10-10 14:20:18 | 4,128 | db9502de1b2697e30e17282f785bb8fbd0fcc32fb24f9f46fabeb26c2d56569e |

“Message items” counts records with type=message (not Telegram service events). The exports are **snapshots**; deleted/unexported messages, off-group DMs, actual unique readers, live group population and views of every poll are unknown. Local export timestamps are used as given.

**Exact comparison window:** records whose date prefix is in **[2026-09-10, 2026-10-11)**. Data end during 10 October, so this is a partially observed last day; “31 calendar dates” is not a complete 31x24-hour window. Both groups use the same bounds.

### 2.2 Verified repository sources (main at stated baseline)

- AGENTS.md — mandatory KB reading, lightweight Termux, fail-closed and research-vs-ADR rules.
- docs/kb/00_Project_Overview.md; 01_Product_Vision.md; 02_Project_Principles.md; 03_System_Architecture.md; 04_Runtime_Constraints.md.
- docs/kb/11_Pinned_Message_Content.md — pinned-guide root, transport and activities structure.
- docs/kb/14_Activities_and_Programs.md — recurring activities, linked school/program cards.
- src/telegrambot/pinned.py, src/telegrambot/guide.py — implementation evidence for guide structure.
- src/telegrambot/telegram.py, src/telegrambot/__main__.py — implemented manual poll command.
- adr/0037-operator-poll-and-channel-engagement.md — **accepted** current scope for polls.
- adr/0041-linked-pinned-city-guide.md, 0042-automated-urban-timetable-media.md, 0067-linked-places-and-activities-pilot.md, 0071-music-activities-linked-school.md.
- research/2026-08-12-product-review-and-growth.md — older directional engagement ideas; superseded for this pilot wherever contradicted by guide inventory or accepted architecture.
- Adjacent private repository **vasenko1/tg-mod-bot**, README.md — separate moderation service has an existing Telegram long-poll and SQLite. This was reviewed as an architectural candidate only; no integration or deployment was tested.

### 2.3 Measurement definitions (repeatable)

- Cross-author Reply: a message in comparison window with reply_to_message_id that resolves to an exported message from a different from_id; does **not** establish helpfulness. Replies between humans additionally exclude the known bot-as-author identifiers in the user's export. A reply to an exported message may refer to a root outside the comparison window.
- Different authors are compared by their export from_id; “same author in both groups” means an identical from_id in both exports, **not** proof of identical audience reach.
- Repeated long text: extract plain text from Telegram text string or rich-text array by concatenating text fragments; lowercase, collapse whitespace, strip; include strings **longer than 50 characters**; count a message repeated when its normalized content occurs at least twice **within that group and window**. Exclude publication identities of the info bot in the user's group. This is **not** a verified advertising classifier.
- A discussion tree follows reply_to_message_id to the root when exported; descendants authored by anyone other than the root author are counted as participant replies. A non-Reply adjacent message may be a real response but is invisible to this method.
- Poll total_voters is the Telegram-exported number, not the sum of option voters (multiple-selection polls can have several choices per participant).

## 3. The existing pinned guide: what we MUST NOT propose again

Read the code and product architecture before inventing “new” information services.

| Previously proposed poll choice / supposed gap | Finding in main | Pilot implication |
| --- | --- | --- |
| “Как добраться в аэропорт без машины” | **Already exists:** dedicated Guardamar ↔ Alicante-Elche airport card; src/telegrambot/pinned.py airport card says direct Bus Sigüenza and links station ↔ terminal. Transport guide menu links airport explicitly. Dynamic dated operator transport updates are separately documented. | Do not offer to create an airport route card. Only consider genuinely **uncaptured real-world experience**, e.g. luggage, boarding problems, accessibility, and only when a real question makes it useful. |
| “Местные автобусные маршруты” | **Already exists:** distinct municipal lines 1 and 2, official timetable media, linked route navigator; other intercity directions too. | Do not re-propose lines 1/2 or an ordinary timetable. A confirmed missing neighborhood/stop or resident experience is a different problem and needs its own gap check. |
| “Муниципальные кружки и секции для детей” | **Already exists:** linked “Занятия и секции” index; sports, swimming, psychomotor and music, plus linked place cards; music has Jardín/Lenguaje, vocal and instruments, Escuela de Música contact/venue. | Do not offer to “add sections” broadly. Valid potential gap is **first-hand user experience, first visit, concrete certificate requirements**, and only after confirming the exact activity is already represented and the answer is not in its card. |
| “Прописка и Ayuntamiento” | The guide does link a city camera called “Площадь Ayuntamiento”, but that is **not evidence** of an empadronamiento procedure guide. No dedicated administrative procedure card was confirmed in the inspected guide inventory. | Treat as **possible, unverified gap**, not an assertion of missing or wrong official information. Audit latest guide and official current procedure first. |
| Generic product awards | Product Awards already exist and offer awarded-product evidence. | A poll must ask for actual consumer experience not already asserted by awards; no mandatory poll for every product. |

**Runtime qualification:** the GitHub code and documents establish implemented/defined cards, **not a live inspection of current Telegram pinned message IDs or rendered cards**. Before editing any card or posting a public claim, inspect actual production guide state / operator preview via the existing safe workflow.

### 3.1 Existing poll facility — correction to earlier advice

The project **already implements** manual operator-triggered polls:

- ADR 0037: accepted **manual only**, anonymous, stateless, no vote collection, no schedule; **suggested at most one poll per month** for relevant editorial/product-direction decisions.
- src/telegrambot/__main__.py handles the operator CLI command “poll” and calls send_poll.
- src/telegrambot/telegram.py sends Telegram “sendPoll”, validates question length 1–300, 2–10 options of 1–100 characters and sets is_anonymous=true.
- Current send_poll parameters are **chat_id, question, options, is_anonymous**. They do **not** set reply_to_message_id, disable_notification, open_period/close_date, or implement collecting poll updates or automatic follow-up.
- The user's export contains **zero** native poll messages through 2026-10-10. This does not negate the existing CLI support.

**Do not claim** that an attached, silent, time-limited Product Awards poll, persistent analytics, or automatic question scheduling is currently implemented. These would need independent acceptance, design, tests and potentially a **new ADR superseding/expanding 0037**. The current pilot can reuse the existing CLI under existing policy rather than building a new module.

### 3.2 Runtime / moderator separation

The information bot's product/KB contracts: official factual sources; short-lived one-shot jobs; fail closed; minimal state; no general user-content collector, conversational AI, arbitrary classification, new daemon, or competing listener. The moderation bot is a separate service already consuming group updates via long polling and has local SQLite; it is a potential source for **minimal and explicitly approved** question/Reply telemetry. Its README does not establish that engagement tracking is already implemented.

**No new getUpdates consumer for the same bot token.** No production change is authorized by this research. A telemetry extension needs an actual code audit, privacy/data-minimization design, tests, failure isolation (moderation must keep working if analytics fails), a specific ADR and independent deployment review. The operator's preview listener must not be repurposed into a general group collector.

## 4. Audited quantitative baseline

### 4.1 Identical 2026-09-10 through 2026-10-10 snapshot window

| Metric | Competitor | User group |
| --- | ---: | ---: |
| Type=message items | **1,047** | **743** |
| Distinct from_id values | **278** | **106** |
| Messages carrying reply_to_message_id | **247** | **56** |
| Reply to an exported message by different author | **233** | **15** |
| Cross-author replies excluding user's bot as respondent/origin | Not applicable to same role | **12** |
| Distinct authors of cross-author replies | **103** | **9** (before role filtering) |
| Long human-authored text records >50 characters used in duplicate comparison | **475** | **262** |
| Of those, text identical to at least one other within window | **25** | **149** |
| Duplicate long-text record share | **5.26%** | **56.87%** |

**Note correction:** earlier chat iterations gave denominator variants “478/269”, “265” and “5.2%/56.2%”, reflecting inconsistent length/exclusion filters. **Use the fixed definitions and verified 475/262, 25/149 above** for future reproducibility; do not preserve the old ratios as an authoritative benchmark.

The user's 12 human-to-human Reply messages include many responses to commercial solicitations (“+”, questions about lessons, request to move to DM). One **confirmed** explicit resident-help reply in this window concerns the 2026-10-07 inquiry about loud noises in town. This narrow count **must not** be read as “only one conversation occurred”: Telegram users can answer without Reply, and DMs are invisible.

Potential commercial-repeat saturation is supported by the repeat rates, but **causality is not established**: audiences, reach, history, rules and author mix differ. Do not change advertising policy as a prerequisite to the pilot.

### 4.2 Shared writers and their behavior

- Across the 2026 slices of both files: **148** common from_id values.
- In the exact September–October comparison window: **49** common from_id values.
- These 49 authors account for **31** cross-author Replies in the competitor group and **3** in the user's group in the window. Earlier discussion incorrectly reported 33; corrected after rerun.
- This indicates context-dependent posting, but it is **not** a controlled conversion experiment. Cross-group exposure, message opportunities, group sizes and member tenure are unknown.

### 4.3 Identical city-evening photo

On 2026-09-23, the same exporter author posted an image with the same recorded photo file size (**125108 bytes**) around five minutes apart:

- Competitor message **36170**, at 20:49:18 — **48** hearts.
- User group message **7750**, at 20:53:53 — **15** hearts.

The matching author/attachment metadata and near-identical posting time support the comparison, but the actual photo bytes are not in JSON and exposure/view denominators are unknown. **Do not claim a 3.2× engagement rate**. It shows that the user's group can generate meaningful positive reactions even in its current state.

### 4.4 Polls in the competitor export

Exactly **three** native poll messages are present in the available competitor export:

| Message ID, date | Topic | Telegram total_voters |
| --- | --- | ---: |
| 26129, 2026-02-05 | Preferred advertising schedule | **136** |
| 26491, 2026-02-15 | Should the group be divided into categories? | **117** |
| 26492, 2026-02-15 | Which information should the group publish? | **98** |

In poll 26492 (multi-answer), choices include: **local events 79**, **city events 78**, **goods/services 67**, **legislative news 63**, **province events 42**, **emergency alerts 42**. These are option choices from 98 respondents, **not a representative city survey**. Critically, the user's bot and pinned guide already cover much of this demand. An obvious “which of our already-existing services to add?” poll is misguided.

The competitor's questions were about the community's rules and editorial direction; the archive does **not** support claiming that it drives everyday conversation through frequent product polls.

### 4.5 Rules differ, and that matters

- Competitor's published rules, 2026-08-16 message **34302**: group explicitly framed as mutual help/support/communication; ordinary free commercial advertising **once per month** on the first, with separate exceptions for personal sales, jobs, owner housing and current activities, subject to category limits.
- User group's rules, 2026-10-03 message **8048**: one repeat commercial advertisement per author/business/project **per 24 hours**, other anti-spam rules; contact with admins via **@WowTalkBot**. They do **not explicitly** tell members that *resident-to-resident everyday questions* are welcome (admin questions are not the same).
- Do **not** copy the competitor's pricing/frequency model without a separate business/community assessment. Advertising is a legitimate primary use of “обЪявления”.

## 5. Verified conversations: structure, not anecdotal invented prompts

The following are identifiable by message IDs in the non-committed competitor export. Counts refer to descendants in the Reply tree authored by someone **other than the original question author**; the time is minutes from root to earliest such reply. This deliberately excludes messages without a Reply link.

| Root message ID / date | Anonymized real topic | Participant replies | Different respondents | Time to first |
| --- | --- | ---: | ---: | ---: |
| 36699 / 2026-10-06 | Where to do driver-license exchange medical check | 10 | 6 | 1.0 min |
| 35334 / 2026-09-07 | Medical certificate for a child's sport section | 10 | 5 | 1.1 min |
| 35875 / 2026-09-16 | Petrol-station 150-euro temporary card hold | 6 | 6 | 2.8 min |
| 30253 / 2026-05-14 | Local music-school enrollment/real experience | 7 | 4 | 3.5 min |
| 35453 / 2026-09-08 | How/where Casa de Cultura class payments work | 5 | 5 | 0.6 min |
| 35601 / 2026-09-11 | Books for Casa de Cultura language courses | 7 | 3 | 116.3 min |
| 30856 / 2026-05-31 | BBQ park practical restrictions | 5 | 4 | 1.8 min |
| 34055 / 2026-08-11 | Where to buy cherries locally | 7 | 6 | 1.0 min |
| 36734 / 2026-10-06 | Whether infant school works during local festival days | 1 | 1 | 2.8 min |
| 36269 / 2026-09-27 | A concrete proposal for a local group outdoor activity | 4 | 4 | 1.5 min |
| 35217 / 2026-09-04 | Experience with adult-school placement tests | 0 linked | 0 linked | n/a |
| 2534 / 2024-01-02 | Where local empadronamiento is handled | 1 | 1 | 4.7 min |

One false “unanswered” interpretation is exposed by **35217**: a subsequent message appears to engage with the topic **without Reply**, so a zero linked-reply count does not imply silence.

Patterns with strongest support:
1. A concrete local task rather than “What do you think generally?”
2. Short, feasible, first-hand answer (location, procedure, cost, condition, actual experience).
3. Actual practical value for the asker, not engagement for engagement's sake.
4. Different residents can add independent details or correct one another.
5. Timely and geographically relevant context.

This table is a **purposefully selected example set, not a ranked statistically representative sample**. Medical/administrative statements by users are not accepted as authoritative factual guidance.

### 5.1 Prior exploratory topic model — retain, but DO NOT operationalize as verified data

Earlier conversational work estimated **2,566** request-like posts over the full competitor history, **969** in 2026, **474** with linked answers (~49%), and **139/65** request/reply pairs in the latest month, plus a rough topical breakdown (transport **165**, shopping **103**, services **93**, health **58**, housing **55**, local leisure **55**, children **49**, documents **48**, work **39**, banking/connectivity **14**, mutual assistance **12**, pets **10**, uncertain/other **268**). Earlier exploratory median first-response times of roughly **11–16 minutes** were also stated.

**Evidence tier: exploratory ONLY.** The exact historical heuristic/source code that produced this request classifier was not available for a reproducible rerun in this documentation pass. Advertising copy containing a question mark and unlinked adjacent replies can create both false positives and false negatives. These estimates **must not be presented as audited facts, KPI baselines or a causal topic ranking**. They are retained only as prior working hypotheses for a future explicitly reproducible, manually sampled thematic audit. Prefer verified thread examples in §5.

## 6. Interpretation and anti-conclusions

- **Supported:** competitor has many more visible human replies; same identified writers engage differently; concrete local practical questions often yield multi-author exchanges; the user's information/announcement mix is different; duplicates are a potential attention cost; users can react to city imagery.
- **Likely hypothesis:** group identity and social norms matter. The competitor explicitly establishes reciprocal-help expectations; the user's group is perceived as an announcement and automated-information feed.
- **NOT proven:** advertising repetition causes low conversation; all users who see an informational post are inactive; changing rules will boost peer-to-peer messages; polls are causally necessary before comments; three voters represent town opinion; the groups have equal reachable active readership.
- **Important business constraint:** maintain legitimate commercial and classifieds use; do not equate an inquiry about an offer with pointless noise. Track commercial contacts separately rather than deleting them to inflate a “help” ratio.
- **No copying of competitor text or personal contact lists.** These exports are research evidence, not a data source for automatic publication.

## 7. Revised pilot: six weeks, adaptive stage gates

Dates are planning windows, not an unconditional editorial calendar. Existing safety/official posts take precedence. Public engagement is optional and skipped if the topic is not good enough.

| Stage and approximate window | Concrete action | Public output and eligibility | Evidence / decision gate |
| --- | --- | --- | --- |
| **0: 2026-10-12–18** | Read-only review of existing group rules, pinned guide, current moderation update flow and permissions. Preserve this baseline. Distinguish service/revenue-related inquiries from resident-help questions. | **No required new post.** A small one-line amendment to existing rules can clarify that everyday city questions and experience-based help are welcome; edit only after operator review, avoid a separate announcement. | Existing features/gaps verified against guide; no interference with running services. |
| **1: Week 1–2** | Choose **one** resident-interest poll that asks about a REAL unmet need **not already covered by the pinned graph**. Use existing manual CLI under ADR 0037. | **At most one anonymous native poll** in the initial pilot, manually triggered. No invented silent reply, auto-close, follow-up collector or results bot. Do not poll if all choices duplicate implemented cards. | Telegram's displayed total_voters; record counts manually. Publish only a verified useful guide improvement afterward, not a celebratory results post. |
| **2: Week 2–3** | Provide **at most one** narrow experience question embedded in an existing relevant, non-emergency information message after checking that the answer is missing from the official guide. | Example: a source-confirmed municipal course notice might contain “Если уже посещали занятия: что оказалось важным при первом визите?” Not every guide/card; never imply an invented neighbor asked. | At least one answer with concrete helpful information; zero replies is an observation, not reason to post more questions. |
| **3: Weeks 2–5** | Watch for genuine resident questions; when no one responds, the operator may provide **verified information** or a real clarifying follow-up. Do not fabricate testimonials. | **No mandatory extra engagement post.** Help happens in the existing group threads as opportunities occur. | Number of unique human peer-help threads; whether participants start replying without admin involvement. |
| **4: Weeks 4–5** | If real helpful resident experience accumulates, verify any official factual claims and derive one lightweight update / “Проверено жителями” draft, with consent/context where appropriate. | Prefer improving an existing guide card over creating a separate publication; distinguish personal experience from verified facts. Do not launch a weekly ritual before repeat evidence. | Genuine reusable contribution, no user privacy leakage or inaccurate official claim. |
| **5: 2026-11-16–22** | Review last 28 days and compare narrowly to export baseline; include reach limitations, topic/traffic shifts and moderation quality. | No extra public message required. | Go/adjust/stop: pursue useful human interactions if present; otherwise do not scale poll volume or questions. |

**Suggested initial poll AFTER a real content-gap audit**, with options about gaps in *experience* rather than existing timetables:

> Чего вам не хватает в наших справочных карточках о Гуардамаре?
>
> - Проверенного практического опыта обращения в городские учреждения
> - Где решают небольшие бытовые задачи (печать документов, мелкий ремонт и т.п.)
> - Что нужно знать при первом посещении детских занятий, помимо расписания
> - Отзывов о конкретных товарах и услугах
> - Пока нужную информацию нахожу без проблем

This is **candidate copy**, not an already approved publication: before use check that each option is distinct, relevant, not already delivered elsewhere, and that the group can act on the winner. If the guide/audience check fails, revise the choices or **skip**. No question about “adding airport route / city buses / municipal sections” survives.

**Product Awards:** remain eligible for a later **manual editorial experiment** with an “already tried / would buy again?” question. Current ADR 0037 recommends <=1 poll per month; a second poll during the same short window is **not assumed approved**. No mandatory poll per product and no automated reply-to-product thread.

**Cadence / stop:** no daily calls to like/comment; no mandatory Friday engagement post; no incidental polls on emergencies, AEMET, Previfoc, SUMA, incidents, outages or personal medical decisions; pause optional activity when urgent city content competes for attention.

**Do not change commercial advertising frequency** during this experiment. Its impact would be confounded with the engagement changes; evaluate in a later separate study. No forum migration, channel conversion, synthetic dialogs, bot “thanks for comment” replies or fake neighbor submissions.

## 8. Outcome metrics and explicit definitions

**Primary**: a resident-help thread is a question or request about everyday Guardamar life that receives a **substantive** response from an unrelated human participant. Count **distinct root questions**, not every Reply. Exclude bot answers, trivial “+”, identical sales copy, admin-only interactions, and mere “DM sent”; optionally track replies between seller/buyer in a separate commercial category.

Secondary:
- Unique people who helped at least once during each 28-day period.
- Repeat helpers who answered in >=2 separate threads.
- Resident-originated practical questions, whether answered or not.
- First human reply latency **conditional on having a reply**, never represented as latency for all questions.
- Human-to-human follow-up after first help, excluding routine seller-to-buyer messages.
- Poll total_voters from Telegram UI (manual at this stage), **not vote / assumed 90 readers**.
- Resident reactions to authentic city/cultural content (secondary emotional signal only).
- Total advertisements and duplicate long-text share, diagnostic only.
- Complaint or moderation signals; any material increase is a reason to pause.

**Small-sample pilot heuristic, NOT a universal benchmark:** >=3 substantive resident-help threads from >=2 independent root questions during a rolling 28 days is a worthwhile early signal relative to current sparse visible help, especially with >=1 repeat helper. Zero is not proof the community can never change; check visibility, timing, real need and question quality rather than sending more polls.

Do not infer causality from before/after changes: local events, competing group behavior, organic growth, varying post exposure and seasonal changes remain uncontrolled.

## 9. Technical sequencing / safety contract

No code is approved by this research note. Before implementing:

1. Pin the expected main commit, check Termux production HEAD, clean worktree, cron/service state, exact moderation listener(s), the live pinned guide and user permissions. Do **read-only** probes first.
2. Reuse the moderation bot's existing update stream if, and only if, a code audit and permissions/privacy review prove an analytics hook can be isolated after moderation. No second getUpdates with the same token; no outbound LLM per chat message, third-party publication or broad history retention.
3. Prefer operator-reviewed/manual labeling of a very small sample before authorizing automatic “question detector”. Treat ads, rhetorical questions, quotes, polls, and sensitive personal requests as potential false positives.
4. An analytics failure must never affect deletion decisions, restriction rules, uptime or moderation availability.
5. Limit state and log retention explicitly; no raw user exports in the repository; no public listing of authors/helpfulness scores. Aggregation should not identify people.
6. Pilot polls use the **existing** anonymous manual CLI. If features require silence, threaded reply, timing, scheduled polls or reading results, first write a focused ADR replacing/extending 0037; test in a **private test chat** with correct target, NOT the public group.
7. Do not alter the info bot's official-only provenance rules. Practical resident experience must be labeled separately and never promoted to official city fact without authoritative checking.
8. Follow AGENTS.md KB/ADR/test/release practice for any subsequent implementation. Review commits/PRs independently and deploy deliberately. This document's creation is a **docs-only action** and requires no production deployment.

## 10. Decision log and open verification tasks

### Corrections consolidated for future sessions

- **Reject** proposing already-implemented airport/bus/activity cards as first-poll options. Verify actual guide state before new proposals.
- **Correct** “polls need to be implemented”: manual sendPoll already exists by ADR 0037; **not** scheduled/anonymous vote collector/quiet product thread.
- **Correct** earlier “49 common authors: 33 vs 3 Reply” to **31 vs 3** for the audited window/method.
- **Correct** unstable repeated-text denominators to **475/262**, repeated items **25/149**, shares **5.26%/56.87%** under explicit >50-char rule.
- **Reject** inference that a ~57% duplicate-message share *caused* lack of conversation.
- **Reject** claiming 969 “true questions” and 474 “answered questions” as fully validated; preserve only as exploratory, §5.1.
- **Reject** immediately shipping a generic EngagementPollEngine, user-message listener in the info bot, or automated comments buttons.
- **Keep** native group Replies rather than forcing Telegram forum topics or a channel conversion.
- **Keep** commercial classifieds as a valid purpose; focus added measurement on distinct peer-help interactions.

### Open items (must be verified, not presumed complete)

- Actual production pinned guide state, the linked message graph and exact revisions of airport, municipal lines, activity cards and any administrative help card.
- Whether present group rules and welcome/onboarding surface visibly permit resident questions, beyond “contact administration”.
- Current moderation bot update handler ordering, permissions, Privacy Mode and safe feasibility of coarse nonintrusive metrics.
- Whether the actual local audience needs the specific proposed first poll (sample or editorial check).
- Whether distinct additional guide or experience information can be verified and published safely following the poll.
- Whether historical Telegram observations accurately reflect current activity as audience grows.

## 11. Recommended next action (not performed here)

**No new feature/deployment first.** Do a narrow read-only audit of the existing pinned guide and the moderation listener; select one demonstrably **missing** resident-service information/experience gap. Then, after checking the copy and public value, conduct **one** manual anonymous poll through the already-approved command and record its result. Maintain human attention to real questions while leaving advertising policy and official daily publications untouched.

## 12. Links for cross-session retrieval

- GitHub source-of-truth for existing features: docs/kb/11_Pinned_Message_Content.md and docs/kb/14_Activities_and_Programs.md.
- Current poll architecture: adr/0037-operator-poll-and-channel-engagement.md; src/telegrambot/telegram.py; src/telegrambot/__main__.py.
- Bot vs moderation separation: docs/kb/00_Project_Overview.md through 04_Runtime_Constraints.md, plus the separate moderation repository README.
- This research document is a **historical record and pilot proposal**. It does not silently modify 09_Roadmap.md, 10_Decision_Log.md, stable rules, or accepted ADRs.
