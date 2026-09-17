from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, got {count}: {old[:100]!r}"
        )
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


SOURCE = "src/telegrambot/music_school.py"
PINNED = "src/telegrambot/pinned.py"

replace_once(
    SOURCE,
    '''        start_year, label = season
        bucket = seasons.setdefault(start_year, {
            "season": label,
            "schedule_url": None,
            "jardin_registration": None,
            "school_registration": None,
        })
        folded = post["text"].casefold()
''',
    '''        start_year, label = season
        folded = post["text"].casefold()
        if not any(marker in folded for marker in (
            "matrícula",
            "matricula",
            "jardín musical",
            "jardin musical",
            "lenguaje musical",
            "asignaturas conjuntas",
        )):
            continue
        bucket = seasons.setdefault(start_year, {
            "season": label,
            "schedule_url": None,
            "jardin_registration": None,
            "school_registration": None,
        })
''',
)

replace_once(
    SOURCE,
    '''    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    return hosts is None or parsed.hostname in hosts
''',
    '''    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    return hosts is None or parsed.hostname in hosts
''',
)

replace_once(
    SOURCE,
    '''    try:
        published_day = date.fromisoformat(published[:10])
        parsed_link = urllib.parse.urlsplit(link)
    except (ValueError, TypeError):
        return None
    if parsed_link.scheme != "https" or parsed_link.hostname != API_HOST:
        return None
''',
    '''    try:
        published_day = date.fromisoformat(published[:10])
        parsed_link = urllib.parse.urlsplit(link)
        link_port = parsed_link.port
    except (ValueError, TypeError):
        return None
    if (
        parsed_link.scheme != "https"
        or parsed_link.hostname != API_HOST
        or link_port not in {None, 443}
        or parsed_link.username is not None
        or parsed_link.password is not None
    ):
        return None
''',
)

replace_once(
    PINNED,
    "  ударные · виолончель · дульсайна · гитара · фортепиано",
    "  ударные · виолончель · дульсайна · гитара · Piano Complementario",
)

print("Deploy 3 review fixes applied")
