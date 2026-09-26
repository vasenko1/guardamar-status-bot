"""Shared strict URL policies for normalized event links."""

import urllib.parse
from typing import Optional


TICKET_HOSTS = frozenset({
    "agendaguardamar.com",
    "www.agendaguardamar.com",
    "giglon.com",
    "www.giglon.com",
})
REGISTRATION_HOSTS = frozenset({
    "docs.google.com",
    "forms.gle",
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


def normalize_registration_url(candidate: str) -> Optional[str]:
    """Return a canonical explicit registration form URL from approved hosts."""

    if candidate != candidate.strip() or any(ord(char) < 32 for char in candidate):
        return None
    try:
        parsed = urllib.parse.urlparse(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in REGISTRATION_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.netloc.casefold() != (parsed.hostname or "").casefold()
    ):
        return None
    if parsed.hostname == "docs.google.com":
        if not parsed.path.startswith("/forms/"):
            return None
    elif not parsed.path or parsed.path == "/":
        return None
    return urllib.parse.urlunparse(parsed._replace(fragment=""))
