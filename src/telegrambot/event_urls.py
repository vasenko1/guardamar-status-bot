"""Shared strict URL policy for normalized event ticket facts."""

import urllib.parse
from typing import Optional


TICKET_HOSTS = frozenset({
    "agendaguardamar.com",
    "www.agendaguardamar.com",
    "giglon.com",
    "www.giglon.com",
})


def normalize_ticket_url(candidate: str) -> Optional[str]:
    """Return one canonical ticket URL only when its authority is exact."""

    if candidate != candidate.strip() or any(ord(char) < 32 for char in candidate):
        return None
    try:
        parsed = urllib.parse.urlparse(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in TICKET_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.netloc.casefold() != (parsed.hostname or "").casefold()
    ):
        return None
    return urllib.parse.urlunparse(parsed._replace(fragment=""))
