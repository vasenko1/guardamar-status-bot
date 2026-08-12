# Product review, phrase-engine assessment, and growth candidates

## Question

What does the bot deliver today, how healthy is the deterministic event
phrase engine, which official content sources could make the product more
attractive within the documented constraints, and which engagement practices
from other Telegram communities apply here — all while keeping Gemini inside
its free tier?

## Sources checked

- This repository: `docs/kb/00`–`09`, `adr/`, `src/telegrambot/`, accessed
  2026-08-12.
- Google Gemini free-tier rate limits, third-party summaries, accessed
  2026-08-12: flash-lite class models carry roughly 1,000–1,500 free
  requests/day
  (aipromptshub.co, pecollective.com, tokenmix.ai rate-limit guides).
- Telegram engagement guides, accessed 2026-08-12: mava.app community-building
  guide, boostifyfox and scrile growth posts, brandghost marketing framework.
  Commercial blogs, not authorities; used only for directional practice
  patterns, not factual claims.
- AEMET OpenData catalogue: municipal daily forecast and the dedicated UVI
  prediction product `/api/prediccion/especifica/uvi/{dia}`.
- Colegio Oficial de Farmacéuticos de Alicante,
  `https://cofalicante.com/farmacias-de-guardia/` — the legally authoritative
  on-call pharmacy rota for the province.

## Findings

### What the product delivers today

- 07:30 Morning Digest: weather with dynamic sky icon, rain only at ≥75%,
  wind with inline forecast, sea temperature and state, AEMET warnings for
  the Guardamar zone, all six verified beach flags with jellyfish rows in
  season, Policía Local traffic measures, official holidays, and every
  verified deduplicated event of the day with tickets, registration and
  Google-Maps venue links.
- 10:10–10:40 bounded replacement cycle that upgrades the morning message
  once when complete beach data or a Mayor-channel bathing notice appears.
- In-season operational replies when a flag, jellyfish status, or AEMET
  warning verifiably changes.
- Evening next-day PVPC table with a persistent explanation thread.
- Operator-only `/preview` listener and `refresh-current` in-place repair.

Strengths worth preserving: unbreakable schedule consistency, official-only
sourcing, silence over noise, fail-closed handling of every optional source,
and one current message per day instead of a feed.

Gaps: the product looks only at *today* (no forward-looking content), it is
one-way (no interaction surface), winter content is thin once the beach
season ends, and the reviewed-corrections mechanism creates a recurring
monthly maintenance cost (see phrase engine below).

### Event phrase engine

Resolution order for any event title: exact reviewed Russian translation
(`event_translations.REVIEWED_TRANSLATIONS`) → policy-versioned bounded cache
filled only by preparation commands → deterministic Spanish normalization
(`spanish_fallback`). Rendering is fully deterministic in `digest.py`
(direction/sea-state/warning vocabularies, event bullet composer), and
cross-source duplicates are merged in `morning._merge_events` using
normalized-word overlap with place corroboration and a small alias table.

Strengths: an LLM outage can never regress a reviewed title; cache entries
are keyed by policy version so a wording-policy change invalidates cleanly;
duplicates need either strong title overlap or moderate overlap plus place
agreement, which has held up well.

Weaknesses:

1. Reviewed corrections and translations are *code*. Every monthly poster
   needs a developer commit to `municipal_agenda._apply_reviewed_corrections`
   and friends, and expired entries need manual retirement (last done
   2026-08-12). This is the single largest recurring cost in the product.
2. `REVIEWED_TRANSLATIONS` matches exact casefolded titles, so punctuation
   variants historically required duplicate keys per title.
3. Two sources describing one event with different times stay duplicated by
   design; the correction layer absorbs the burden.

Recommendation (not implemented in this cycle): move reviewed corrections and
translations into a small reviewed JSON data file validated at load with the
same fail-closed rules, so monthly poster review becomes a data-only commit.
Record as a proposed ADR when scheduled.

### Gemini free-tier position

Current usage is single-digit requests per day in the worst case: municipal
extraction only when official text changes, two Vision reads only on a new
poster URL, title translation only on cache misses, market and traffic
fallbacks rarely. Free-tier flash-lite allowances are three orders of
magnitude above this. The weekend digest below adds at most two bounded
translation batches per week; nothing in this plan moves the bot off the
free tier, and the single OpenRouter fallback remains the only paid-risk
path (one request, only after a Gemini failure).

### Engagement practices observed elsewhere

Directional patterns from community-building guides, filtered through this
project's principles:

- Hybrid structure — a broadcast channel plus an attached discussion group —
  retains members better than broadcast alone. The bot's footer already
  points at the public group; attaching it as the channel's discussion group
  and enabling reactions costs nothing and adds an interaction surface.
- Native polls and quizzes are the highest-engagement Telegram formats.
  A sparse, operator-triggered poll (for example a monthly «что добавить?»)
  fits the product; anything scheduled or frequent would violate
  silence-over-noise.
- Short scannable posts and a reliable schedule drive retention. The bot
  already excels here; the lesson is to protect this property, not to post
  more.
- A pinned onboarding message explaining how to read the digest helps new
  members extract value immediately.

Draft pinned onboarding message (operator pins manually):

> 📌 Как читать этот канал
>
> Каждое утро в 07:30 — сводка на день: погода и море от AEMET, флаги на
> пляжах, предупреждения, перекрытия, праздники и события дня.
> Днём сообщение может обновиться, когда появляются проверенные данные о
> пляжах. Вечером — таблица цен на электричество (PVPC) на завтра.
> Если раздела нет — значит, сегодня по нему нет проверенных данных.
> Источники: только официальные (AEMET, Ayuntamiento, Policía Local,
> SafeBeach, ESIOS).

### Content-source candidates, ranked

| Candidate | Source and authority | Verdict |
| --- | --- | --- |
| Weekend events digest | The two existing local catalogs; no new source | **Accepted** — ADR 0034 |
| UV index | AEMET municipal payload `uvMax`, or the dedicated UVI product; same key | **Accepted** — ADR 0035 |
| Sunrise/sunset | Deterministic astronomy, no source at all | **Accepted** — ADR 0035 |
| Poll capability | Telegram Bot API `sendPoll`; operator-triggered only | **Accepted** — ADR 0036 |
| Pharmacy on duty | Colegio Oficial de Farmacéuticos de Alicante rota | **Accepted, feasibility-gated** — ADR 0037 |
| Bathing water quality | Generalitat Valenciana / EU bathing-water sampling | Deferred — seasonal, evaluate before summer 2027 |
| Tides | — | Rejected: Mediterranean tidal range at Guardamar is centimeters; no decision value |
| DGT road incidents | DGT open data | Rejected for now: mostly non-local noise; revisit only with a proven N-332 filter |
| Nearby-city events, general news | — | Rejected: violates the Guardamar-only product vision |

## Recommendation

Implement in order: weekend digest (highest attractiveness per line, no new
source), UV + sun rows (near-zero cost), poll capability plus the manual
channel checklist (reactions, discussion group, pinned onboarding), then the
pharmacy adapter only if its research note proves bounded server-rendered
HTML. Keep the data-driven corrections file as the next structural
investment. Confidence: high for the first three, medium for pharmacy
feasibility. Open question: whether `uvMax` is present in the live municipal
payload (decides parse-in-place vs one extra bounded product request).
