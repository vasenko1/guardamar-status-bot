    api_key: str,
    teasers: Sequence[str],
) -> List[str]:
    """Translate bounded source excerpts without summarizing them."""

    if not 1 <= len(teasers) <= 80:
        raise ValueError("between one and 80 event teasers are required")
    result = await asyncio.to_thread(
        _translate_event_teasers,
        api_key,
        teasers,
    )
    translated = result.get("teasers_ru")
    if (
        not isinstance(translated, list)
        or len(translated) != len(teasers)
        or not all(
            isinstance(teaser, str) and 1 <= len(teaser.strip()) <= 260
            for teaser in translated
        )
    ):
        raise GeminiError("Gemini returned invalid event teaser translations")
    return [teaser.strip() for teaser in translated]


def _compose_traffic_notice(
    api_key: str,
    facts: Dict[str, Any],
) -> Dict[str, Any]:
    source = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    if not 1 <= len(source) <= 6_000:
        raise GeminiError(
            "Traffic facts have an invalid size",
            code="SOURCE-SIZE",
            description="данные дорожного события имеют неверный размер",
        )
    prompt = (
        "Write one or two concise, natural Russian sentences for a local "
        "Guardamar del Segura Telegram traffic alert. The JSON FACTS below is "
        "the complete factual source and came from TomTom in Spanish. "
        "Use only facts explicitly present in FACTS. Never invent a reason, "
        "detour, duration, opening time, number of closed lanes, severity, "
        "event name, or consequence. Missing facts are intentionally omitted: "
        "do not mention that information is unknown, unavailable, or not "
        "specified. Keep Spanish/Valencian street and urbanization names "
        "exactly as supplied. Prefer to include known start/end timing when it "
        "helps a resident understand the restriction; never comment on omitted "
        "timing. If details_es merely repeats Cerrado/Carril cerrado, use it only "
        "as status, not as a cause. If details_es contains another meaningful "
        "fact beyond the closure status, include that fact neutrally when it is "
        "useful to a resident. For example, Obras may be mentioned as an "
        "additional reported fact, but do not turn it into a causal 'because of' "
        "statement unless the Spanish wording explicitly states causality. "
        "mode=new_present means the restriction is active now; mode=ongoing "
        "means it remains active on a later local day; mode=future_tomorrow "
        "means announce that it starts tomorrow; mode=category_change means "
        "describe only the practical change from previous_category. "
        "If end_local exists, describe it as an expected/planned end, never a "
        "guarantee. Do not add a heading, bullet, map link, source attribution, "
        "footer, emoji, Markdown, or HTML. Return only the JSON schema.\n\n"
        f"FACTS: {source}"
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        TRAFFIC_NOTICE_SCHEMA,
        500,
    )


async def compose_traffic_notice(
    api_key: str,
    facts: Dict[str, Any],
) -> str:
    """Turn verified Spanish TomTom facts into one bounded Russian paragraph."""

    result = await asyncio.to_thread(_compose_traffic_notice, api_key, facts)
    body = result.get("body_ru")
    if not isinstance(body, str):
        raise GeminiError("Gemini returned an invalid traffic notice")
    body = " ".join(body.split()).strip()
    if not 1 <= len(body) <= 900:
        raise GeminiError("Gemini returned an invalid traffic notice")
    folded = body.casefold()
    if any(token in folded for token in ("null", "undefined")):
        raise GeminiError("Gemini returned a null-like traffic notice")
    if any(
        phrase in folded
        for phrase in (
            "не указано",
            "не указана",
            "не указан",
            "нет информации",
            "информация отсутствует",
            "неизвестно",
        )
    ):
        raise GeminiError("Gemini described intentionally omitted traffic facts")
    return body


def _request_market_status(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    prompt = (
        "Check official municipal Telegram posts for an explicit cancellation "
        "or move of Guardamar's regular Wednesday market on TARGET_DATE. "
        "Do not treat unrelated markets, past dates, weather warnings, or mere "
        "schedule descriptions as cancellation. evidence_es must be one exact "
        "contiguous quotation from SOURCE. Set cancelled=false with empty "
        "evidence_es and null event_date unless the statement and exact date "
        "are explicit.\n\n"
        f"TARGET_DATE: {local_day.isoformat()}\n"
        f"SOURCE:\n{source_text[:MAX_SOURCE_CHARACTERS]}"
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        MARKET_STATUS_SCHEMA,
        300,
    )


async def extract_market_status(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    """Return a structured market cancellation candidate."""
