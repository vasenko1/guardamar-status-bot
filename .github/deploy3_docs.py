from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


LEDGER = "docs/kb/14_Activities_and_Programs.md"
DECISIONS = "docs/kb/10_Decision_Log.md"
PINNED = "docs/kb/11_Pinned_Message_Content.md"

replace_once(
    LEDGER,
    "Status: implementation ledger — Deploy 2 completed 2026-09-17",
    "Status: implementation ledger — Deploy 3 completed 2026-09-17",
)
replace_once(
    LEDGER,
    "🎵 Музыка\n🎼 Школа музыки",
    "🎵 Музыка\n🎶 Музыкальное развитие и грамота\n🎤 Вокал и хор\n🎷 Музыкальные инструменты",
)
replace_once(
    LEDGER,
    "- `Школа музыки` may contain Jardín Musical and the school’s related enrolment facts/offer inside one card initially.",
    "- Music is activity-first: Jardín/Lenguaje Musical share `Музыкальное развитие и грамота`, while vocal and instruments have their own compact cards; the provider/place is linked separately.",
)
replace_once(
    LEDGER,
    "- Centro Social Juvenil.\n\nFuture places such as CEIP Reyes Católicos or the music school should receive cards only when their actual guide value justifies one, not merely because a source mentions the venue.",
    "- Centro Social Juvenil;\n- Escuela de Música (shared place/contact card for several music activities).\n\nFuture places such as CEIP Reyes Católicos should receive cards only when their actual guide value justifies one, not merely because a source mentions the venue.",
)
old_deploy3 = '''### Deploy 3 — music school

Add `🎼 Школа музыки` under recurring activities.

The project already has a bounded Agrupación Musical Guardamar WordPress REST adapter reading twelve recently modified posts. Its event path deliberately rejects `matrícula`, `curso`, `horarios`, `plazas`, etc. For the program feature, prefer a small deterministic program extractor over broadening event semantics.

One additional bounded daily GET to the same endpoint is acceptable if that keeps event and programme logic isolated. Refactor shared fetching only later if measured cost justifies it.

Track only explicit current facts: Jardín Musical/other school offer, enrollment window, audience/age, schedule facts, contact and registration URL.
'''
new_deploy3 = '''### Deploy 3 — music activities and linked school — completed 2026-09-17

Implemented as an activity-first extension of the existing linked guide:

- one visual `🎵 Музыка` group inside the existing `🎓 Занятия и секции` message;
- three resident-facing cards: `🎶 Музыкальное развитие и грамота`, `🎤 Вокал и хор`, and `🎷 Музыкальные инструменты`;
- one durable `🎼 Escuela de Música` place card under `📍 Места`, owning map/address, phone/email, website and reverse links to the music cards;
- music activity cards keep only programme/audience/schedule facts, a programme-specific registration action when explicitly open, the internal `📍 Escuela de Música` link, the standard upward navigation link and shared footer; contacts are not duplicated;
- Jardín Musical uses its explicit dated form/window only. The general Escuela form is not presented as if it were a group-specific CTA;
- published schedule actions link to the official AM Guardamar schedule post, never directly to Google Drive documents that can also contain enrolled-student lists;
- `music_school.py` is a deterministic programme adapter separate from the existing `am_guardamar.py` event semantics;
- the existing 16:30 guide sync performs at most one additional bounded REST GET per Europe/Madrid local day for twelve recently modified AM Guardamar posts, with a 300 KiB response cap and 15-second timeout;
- `state/guide.json` stores only the accepted normalized season/schedule/registration snapshot plus `music_school_last_attempt_day`; raw posts are not persisted;
- same-season last-good schedule/registration facts survive when older posts leave the twelve-post window, while a new season never inherits old links;
- only programme-shaped posts can establish a season, preventing unrelated future-season concert/news text from rolling the school snapshot forward;
- source failure preserves accepted last-good state and linked cards; manual reruns do not repeat a same-day failed/finished source attempt;
- no public music-change notifications are introduced in this deploy.

This contract is recorded in ADR 0071. No new cron row, daemon, database, browser, LLM extraction, PDF/Drive parser, provider framework, or generic navigation layer was added.
'''
replace_once(LEDGER, old_deploy3, new_deploy3)

replace_once(
    DECISIONS,
    "| --- | --- | --- | --- |\n| 2026-09-17 | Publish semantic sports changes",
    "| --- | --- | --- | --- |\n| 2026-09-17 | Model music as activities linked to one school place card | Keep the existing single activities index, add three compact music cards and one shared Escuela de Música place/contact card; use one bounded daily WordPress programme read with explicit registration dates, safe official schedule-post links, and no Drive/PDF parsing or new scheduler. | `adr/0071-music-activities-linked-school.md`, `docs/kb/14_Activities_and_Programs.md` |\n| 2026-09-17 | Publish semantic sports changes",
)

replace_once(
    PINNED,
    "implemented by ADR 0041 and extended by ADR 0067/0069.",
    "implemented by ADR 0041 and extended by ADR 0067/0069/0071.",
)
replace_once(
    PINNED,
    "Complejo Deportivo Les Raboses, CEIP Molivent, and Centro Social Juvenil.\nDo not flatten every Sporttia room/field into a place card.",
    "Complejo Deportivo Les Raboses, CEIP Molivent, Centro Social Juvenil, and\nEscuela de Música. Do not flatten every source room/field into a place card.",
)
replace_once(
    PINNED,
    "`🏃 Спорт и движение`; this is presentation only and does not create another\nTelegram navigation layer. Source-managed Sporttia cards and durable static\nactivities such as Guardamar Soccer C.D. football share this index but retain\ntheir different source/recovery semantics.",
    "`🏃 Спорт и движение`; music is visually grouped under `🎵 Музыка`. These are\npresentation only and do not create another Telegram navigation layer. The music\ngroup contains `Музыкальное развитие и грамота`, `Вокал и хор`, and\n`Музыкальные инструменты`. Source-managed and durable static activities share\nthe same index while retaining their different source/recovery semantics.",
)
replace_once(
    PINNED,
    "Palau Sant Jaume, Complejo Deportivo\nLes Raboses, and CEIP Molivent are the current explicit venue mappings.",
    "Palau Sant Jaume, Complejo Deportivo\nLes Raboses, CEIP Molivent, and Escuela de Música are the current explicit\nlinked-place mappings.",
)

print("Deploy 3 documentation patched")
