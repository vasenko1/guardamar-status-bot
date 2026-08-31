"""Small deterministic cleanup and map-safety rules for event venues."""

import re


_CONTEXT_WORDS = re.compile(
    r"\b(?:actividad|actuaci[oó]n|campa[nñ]a|clase|concierto|evento|feria|"
    r"festival|mercado|taller)\b",
    re.IGNORECASE,
)
_EMBEDDED_STREET = re.compile(
    r"\b(avenida|avda\.?|av\.?|calle|carrer|plaza|pla[cç]a|parque|"
    r"paseo|passeig)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_NON_MAP_INSTRUCTIONS = re.compile(
    r"\b(?:lugar|punto)\s+(?:de\s+)?(?:inicio|salida)\b|"
    r"\b(?:por\s+confirmar|por\s+determinar)\b|"
    r"\b(?:comunicar[aá]|indicar[aá])\b",
    re.IGNORECASE,
)
_TYPE_LABELS = {
    "avenida": "Avenida",
    "avda": "Avenida",
    "av": "Avenida",
    "calle": "Calle",
    "carrer": "Carrer",
    "plaza": "Plaza",
    "plaça": "Plaça",
    "placa": "Plaça",
    "parque": "Parque",
    "paseo": "Paseo",
    "passeig": "Passeig",
}
_LIBRARY_HALL = re.compile(
    r"^(?:hall\s+(?:de\s+la\s+)?biblioteca(?:\s+p[uú]blica)?\s+municipal|"
    r"biblioteca(?:\s+p[uú]blica)?\s+municipal\s*\(?hall\)?)$",
    re.IGNORECASE,
)


def canonical_event_place(value: str) -> str:
    """Return a compact venue without treating event prose as an address."""

    compact = " ".join(value.split()).strip(" ,.;")
    if _LIBRARY_HALL.fullmatch(compact):
        return "Biblioteca Municipal (Hall)"
    match = _EMBEDDED_STREET.search(compact)
    if match is None or not _CONTEXT_WORDS.search(compact[:match.start()]):
        return compact
    name = match.group(2).strip(" ,.;")
    if not name or len(name) > 80 or _CONTEXT_WORDS.search(name):
        return compact
    place_type = match.group(1).casefold().rstrip(".")
    return f"{_TYPE_LABELS[place_type]} {name}"


def event_place_is_map_safe(value: str) -> bool:
    """Allow a map search only for a compact venue, never an instruction."""

    compact = " ".join(value.split())
    return bool(
        compact
        and len(compact) <= 100
        and not _CONTEXT_WORDS.search(compact)
        and not _NON_MAP_INSTRUCTIONS.search(compact)
    )
