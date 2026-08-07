"""Small persistent cache for reviewed event-title translations."""

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

from .gemini import translate_event_titles

CACHE_VERSION = 1
POLICY_VERSION = 1
MAX_ENTRIES = 500
RETENTION_DAYS = 90

REVIEWED_TRANSLATIONS = {
    "spanish brass": "Концерт духового квинтета Spanish Brass «Top Secret»",
    "spanish brass. top secret": (
        "Концерт духового квинтета Spanish Brass «Top Secret»"
    ),
    (
        "torneo de tenis 24.º open real villa de guardamar, "
        "memorial pepe y juan tendero 2026"
    ): (
        "24-й открытый теннисный турнир «Real Villa de Guardamar» "
        "памяти Пепе и Хуана Тендеро"
    ),
    (
        "exposición de pintura y escultura: "
        "mediterráneo, el lenguaje del agua"
    ): (
        "Выставка живописи и скульптуры "
        "«Средиземноморье, язык воды»"
    ),
    (
        "exposición de pintura con el título "
        "‘mediterráneo, el lenguaje del agua’"
    ): (
        "Выставка живописи и скульптуры "
        "«Средиземноморье, язык воды»"
    ),
    (
        "exposición de pintura «luz a pesar del dolor» "
        "de vira degliarenko"
    ): "Выставка живописи «Свет вопреки боли» — Вира Дегляренко",
    (
        "explorador de emociones: “la alegría que hay en ti”, "
        "de cat deeley"
    ): (
        "Детское занятие «Исследователь эмоций»: "
        "«Радость, которая в тебе» — Кэт Дили"
    ),
    (
        "labores a la fresca: ‘yo te enseño, tú me enseñas’"
    ): "Встреча по рукоделию «На свежем воздухе»",
    (
        "dixi project: viaje por la música de los años 20"
    ): (
        "Джазовый концерт Dixie Project "
        "«Путешествие по музыке 1920-х»"
    ),
    "ball d’estiu": "Летний танцевальный вечер Ball d’Estiu",
    (
        "kiki morente en concierto. estival al castell"
    ): "Концерт фламенко Кики Моренте · VI Estival al Castell",
    "alice wonder": "Концерт Alice Wonder «Soulost» · VI Estival al Castell",
    (
        "alice wonder en concierto. estival al castell"
    ): "Концерт Alice Wonder «Soulost» · VI Estival al Castell",
    (
        "rutas nocturnas: senderismo y dinámica grupal"
    ): "Ночной поход (8 км) для молодёжи 12–30 лет",
}


def _key(source: str, title: str) -> str:
    return f"{POLICY_VERSION}\0{source.strip()}\0{title.strip()}"


def reviewed_translation(title: str) -> Optional[str]:
    """Return an exact operator-reviewed translation for a known title."""

    normalized = " ".join(title.split()).strip().casefold()
    return REVIEWED_TRANSLATIONS.get(normalized)


def spanish_fallback(title: str) -> str:
    """Normalize whitespace/casing without translating or inventing facts."""

    value = " ".join(title.split()).strip()
    if not value or not value.isupper():
        return value
    value = value.title()
    particles = (" De ", " Del ", " La ", " Las ", " El ", " Los ", " Y ")
    for particle in particles:
        value = value.replace(particle, particle.casefold())
    value = re.sub(
        r"\b(I|Ii|Iii|Iv|V|Vi|Vii|Viii|Ix|X|Xi|Xii|Xiii|Xiv|Xv)\b",
        lambda match: match.group(0).upper(),
        value,
    )
    return value


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"version": CACHE_VERSION, "entries": {}}
    if (
        not isinstance(data, dict)
        or data.get("version") != CACHE_VERSION
        or not isinstance(data.get("entries"), dict)
    ):
        return {"version": CACHE_VERSION, "entries": {}}
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def _exclusive(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def cached_title(path: Path, source: str, title: str) -> str:
    reviewed = reviewed_translation(title)
    if reviewed is not None:
        return reviewed
    entry = _read(path)["entries"].get(_key(source, title))
    if isinstance(entry, dict):
        translated = entry.get("translation")
        if isinstance(translated, str) and translated.strip():
            return translated.strip()
    return spanish_fallback(title)


async def prepare_translations(
    api_key: str,
    items: Iterable[Tuple[str, str]],
    path: Path,
    now: datetime,
) -> int:
    """Translate only cache misses and atomically merge the bounded result."""

    unique = []
    seen = set()
    for source, title in items:
        normalized = (source.strip(), title.strip())
        if normalized[0] and normalized[1] and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    current = _read(path)
    missing = [
        item for item in unique
        if _key(*item) not in current["entries"]
    ]
    translations = (
        await translate_event_titles(api_key, [title for _, title in missing])
        if missing else []
    )
    timestamp = now.isoformat()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    with _exclusive(path):
        data = _read(path)
        entries = data["entries"]
        for (source, title), translated in zip(missing, translations):
            entries[_key(source, title)] = {
                "source": source,
                "title": title,
                "translation": translated,
                "policy_version": POLICY_VERSION,
                "last_seen": timestamp,
            }
        for source, title in unique:
            entry = entries.get(_key(source, title))
            if isinstance(entry, dict):
                entry["last_seen"] = timestamp
        valid = []
        for key, entry in entries.items():
            try:
                last_seen = datetime.fromisoformat(entry["last_seen"])
            except (KeyError, TypeError, ValueError):
                continue
            if last_seen >= cutoff:
                valid.append((key, entry, last_seen))
        valid.sort(key=lambda item: item[2], reverse=True)
        data["entries"] = {
            key: entry for key, entry, _ in valid[:MAX_ENTRIES]
        }
        _write(path, data)
    return len(missing)
