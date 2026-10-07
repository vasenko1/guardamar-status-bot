#!/data/data/com.termux/files/usr/bin/bash
set -u
set -o pipefail
export LC_ALL=C

ROOT="${HOME}/bots/guardamar-status"
CACHE_BASE="${HOME}/.cache/guardamar-supermarket-hours-probe"
STAMP="$(date '+%Y%m%d-%H%M%S')"
REPORT="${CACHE_BASE}/report-${STAMP}.txt"

for command_name in python git tee date; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'ERROR: required command is missing: %s\n' "$command_name" >&2
    exit 1
  fi
done
if [ ! -d "$ROOT/.git" ]; then
  echo "ERROR: production repository not found at $ROOT" >&2
  exit 1
fi

mkdir -p "$CACHE_BASE" || exit 1

BEFORE_BRANCH="$(git -C "$ROOT" branch --show-current || true)"
BEFORE_HEAD="$(git -C "$ROOT" rev-parse HEAD || true)"
BEFORE_STATUS="$(git -C "$ROOT" status --porcelain=v1 || true)"

exec > >(tee "$REPORT") 2>&1

printf '============================================================\n'
printf '1. Safety / production identity\n'
printf '============================================================\n'
printf 'Madrid: '
TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z'
printf 'Repo: %s\n' "$ROOT"
printf 'Branch: %s\n' "$BEFORE_BRANCH"
printf 'HEAD: %s\n' "$BEFORE_HEAD"
printf 'Git status before:\n%s\n' "${BEFORE_STATUS:-(clean)}"
printf 'Python: '
python --version
printf 'Report: %s\n' "$REPORT"

PYTHONPATH="$ROOT/src" python - <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import ssl
import time
import urllib.parse
from datetime import date
from html.parser import HTMLParser
from typing import Optional

from telegrambot._transport import BoundedFetchError, fetch_bounded
from telegrambot.holidays import official_holidays_on


SERVICE_HEADERS = {
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "User-Agent": "GuardamarMorningDigest/0.14",
}
NAVIGATION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml"})
JSON_TYPES = frozenset({"application/json", "text/plain"})
SCRIPT_TYPES = frozenset({
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/plain",
})

NETWORK_REQUESTS = 0
TOTAL_BYTES = 0


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def allowed_root(root: str):
    root = root.casefold().lstrip(".")

    def check(url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        host = parsed.hostname.casefold() if parsed.hostname else None
        return (
            parsed.scheme == "https"
            and host is not None
            and (host == root or host.endswith("." + root))
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
        )

    return check


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def redact(value: str) -> str:
    value = re.sub(
        r"(?i)((?:api[_-]?key|apikey|token|access[_-]?token|authorization|client[_-]?secret|secret|password)\s*[:=]\s*['\"]?)(?!\[REDACTED\])[^'\"&\s,}\]]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|token|access[_-]?token|auth|authorization|client[_-]?secret|secret|password)=)(?!\[REDACTED\])[^&#\s]+",
        r"\1[REDACTED]",
        value,
    )
    return value


def fetch(
    label: str,
    url: str,
    *,
    root: str,
    accepted_types: frozenset[str],
    limit: int,
    accept: str,
    navigation: bool = False,
    navigation_fallback: bool = False,
) -> Optional[dict]:
    global NETWORK_REQUESTS, TOTAL_BYTES

    profiles: list[tuple[str, dict[str, str]]] = []
    base = NAVIGATION_HEADERS if navigation else SERVICE_HEADERS
    first = dict(base)
    first["Accept"] = accept
    profiles.append(("navigation" if navigation else "service", first))

    if navigation_fallback and not navigation:
        fallback = dict(NAVIGATION_HEADERS)
        fallback["Accept"] = accept
        profiles.append(("navigation-fallback", fallback))

    for index, (profile_name, headers) in enumerate(profiles):
        NETWORK_REQUESTS += 1
        started = time.monotonic()
        print(f"\n--- {label} [{profile_name}] ---")
        print("URL:", redact(url))
        try:
            payload, final_url, content_type = fetch_bounded(
                url,
                is_allowed_url=allowed_root(root),
                accepted_types=accepted_types,
                limit_bytes=limit,
                timeout_seconds=15,
                headers=headers,
            )
        except BoundedFetchError as exc:
            elapsed = time.monotonic() - started
            print(
                "RESULT: ERROR",
                f"code={exc.code}",
                f"status={exc.status}",
                f"elapsed={elapsed:.3f}s",
            )
            retry_with_navigation = (
                index + 1 < len(profiles)
                and exc.code in {"HTTP-403", "HTTP-406"}
            )
            if retry_with_navigation:
                print("ACCESS-NOTE: retrying once with the already-reviewed navigation header profile")
                continue
            return None

        elapsed = time.monotonic() - started
        TOTAL_BYTES += len(payload)
        requested_host = (urllib.parse.urlsplit(url).hostname or "").casefold()
        final_host = (urllib.parse.urlsplit(final_url).hostname or "").casefold()

        print("RESULT: OK")
        print("profile:", profile_name)
        print("final_url:", redact(final_url))
        print("content_type:", content_type)
        print("bytes:", len(payload))
        print("sha256:", sha256(payload))
        print(f"elapsed: {elapsed:.3f}s")
        print("requested_host:", requested_host)
        print("final_host:", final_host)
        print("host_changed:", requested_host != final_host)
        print("cookie_session: none (production fetch_bounded has no cookie jar)")

        return {
            "payload": payload,
            "final_url": final_url,
            "content_type": content_type,
            "profile": profile_name,
        }

    return None


def decode_text(observation: Optional[dict]) -> Optional[str]:
    if observation is None:
        return None
    payload = observation["payload"]
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        print("TEXT-DECODE: failed:", exc)
        return None


def snippets(text: str, *keywords: str, cap: int = 80) -> None:
    flat = re.sub(r"\s+", " ", text)
    folded = flat.casefold()
    seen: set[str] = set()
    shown = 0

    for raw_keyword in keywords:
        keyword = raw_keyword.casefold()
        start = 0
        while shown < cap:
            index = folded.find(keyword, start)
            if index < 0:
                break
            low = max(0, index - 180)
            high = min(len(flat), index + len(keyword) + 300)
            value = flat[low:high].strip()
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                print(f"[{raw_keyword}] {redact(value)}")
                shown += 1
            start = index + max(1, len(keyword))

    if shown == 0:
        print("(no requested markers found)")


def endpoint_strings(text: str, *, cap: int = 140) -> list[str]:
    normalized = (
        text
        .replace(r"\/", "/")
        .replace(r"\u002F", "/")
        .replace(r"\u002f", "/")
        .replace(r"\x2F", "/")
        .replace(r"\x2f", "/")
    )
    needles = (
        "api", "graphql", "store", "stores", "shop", "tienda", "tiendas",
        "supermerc", "horario", "opening", "hours", "schedule", "calendar",
        "holiday", "special", "closed", "closure", "festiv", "apertura",
        "cerrad", "domingo", "verano", "temporada", "locator", "localizador",
        "location", "pointofsale",
    )
    patterns = (
        re.compile(r'''["']([^"'\\\n]{3,700})["']'''),
        re.compile(r'''https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{4,700}'''),
    )

    values: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        for match in pattern.finditer(normalized):
            value = match.group(1) if match.lastindex else match.group(0)
            if not any(needle in value.casefold() for needle in needles):
                continue
            value = re.sub(r"\s+", " ", value).strip()
            if value in seen:
                continue
            seen.add(value)
            values.append(redact(value[:900]))
            if len(values) >= cap:
                return values
    return values


def print_endpoint_strings(text: str) -> int:
    values = endpoint_strings(text)
    if not values:
        print("(no endpoint/schedule-like strings found)")
        return 0
    for value in values:
        print(value)
    return len(values)


class ScriptParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "script":
            return
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        src = values.get("src")
        if not src:
            return
        absolute = urllib.parse.urljoin(self.base_url, src)
        if absolute not in self.urls:
            self.urls.append(absolute)


def script_score(url: str) -> int:
    value = url.casefold()
    score = 0
    for marker, points in (
        ("buscador", 30),
        ("localiz", 30),
        ("supermerc", 30),
        ("tienda", 25),
        ("store", 25),
        ("/app/", 18),
        ("page-", 18),
        ("pages/", 18),
        ("main", 8),
        ("chunk", 3),
    ):
        if marker in value:
            score += points
    return score


def inspect_scripts(
    label: str,
    html_text: str,
    base_url: str,
    root: str,
    *,
    max_assets: int = 6,
) -> None:
    parser = ScriptParser(base_url)
    try:
        parser.feed(html_text)
    except Exception as exc:
        print("SCRIPT-INVENTORY: parser failed:", exc)
        return

    allowed = allowed_root(root)
    first_party = [
        (index, url)
        for index, url in enumerate(parser.urls)
        if allowed(url)
    ]
    external = [
        url
        for url in parser.urls
        if not allowed(url)
    ]
    first_party.sort(key=lambda item: (-script_score(item[1]), item[0]))

    print(
        "script inventory:",
        f"total={len(parser.urls)}",
        f"first_party={len(first_party)}",
        f"external={len(external)}",
    )
    print("prioritized first-party scripts:")
    for _, url in first_party[:20]:
        print(redact(url))
    if external:
        print("external scripts (listed only, never fetched automatically):")
        for url in external[:20]:
            print(redact(url))

    for number, (_, url) in enumerate(first_party[:max_assets], start=1):
        observation = fetch(
            f"{label}-js-{number}",
            url,
            root=root,
            accepted_types=SCRIPT_TYPES,
            limit=1_000_000,
            accept="application/javascript,text/javascript",
            navigation_fallback=True,
        )
        text = decode_text(observation)
        if text is None:
            continue
        print("endpoint/schedule-like strings:")
        print_endpoint_strings(text)


class FormParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.records: list[str] = []
        self.current_select: Optional[str] = None
        self.option_value: Optional[str] = None
        self.option_parts: list[str] = []

    def emit(self, value: str) -> None:
        if len(self.records) < 100:
            self.records.append(value)

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        tag = tag.casefold()
        if tag == "form":
            method = str(values.get("method") or "GET").upper()
            action = urllib.parse.urljoin(
                self.base_url,
                str(values.get("action") or ""),
            )
            self.emit(f"FORM {method} {redact(action)}")
        elif tag == "input":
            input_type = str(values.get("type") or "").casefold()
            input_value = values.get("value")
            if input_type in {"hidden", "password"}:
                input_value = "[OMITTED]"
            elif isinstance(input_value, str):
                input_value = redact(input_value)
            self.emit(
                "INPUT "
                + repr((
                    values.get("name"),
                    values.get("type"),
                    input_value,
                ))
            )
        elif tag == "select":
            self.current_select = str(values.get("name") or "")
            self.emit(f"SELECT {self.current_select!r}")
        elif tag == "option" and self.current_select is not None:
            self.option_value = str(values.get("value") or "")
            self.option_parts = []

    def handle_data(self, data: str) -> None:
        if self.option_value is not None:
            self.option_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "option" and self.option_value is not None:
            label = " ".join(" ".join(self.option_parts).split())
            option_value = redact(self.option_value)
            label = redact(label)
            self.emit(
                f"OPTION select={self.current_select!r} "
                f"value={option_value!r} label={label!r}"
            )
            self.option_value = None
            self.option_parts = []
        elif tag == "select":
            self.current_select = None


def print_forms(text: str, base_url: str) -> None:
    parser = FormParser(base_url)
    try:
        parser.feed(text)
    except Exception as exc:
        print("FORM-PARSER: failed:", exc)
        return
    if not parser.records:
        print("(no forms/select records)")
        return
    for record in parser.records:
        print(record)
    if len(parser.records) >= 100:
        print("(form output capped at 100 records)")


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "script":
            return
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        if values.get("id") == "__NEXT_DATA__":
            self.capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self.capture:
            self.capture = False

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)


def inspect_dia_next_data(html_text: str) -> Optional[str]:
    parser = NextDataParser()
    parser.feed(html_text)
    raw = "".join(parser.parts).strip()
    if not raw:
        print("__NEXT_DATA__: absent (app-router or another contract may still be present)")
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("__NEXT_DATA__: invalid JSON:", exc)
        return None

    print("__NEXT_DATA__: present")
    build_id = payload.get("buildId")
    print("buildId:", build_id)

    needles = (
        "36111", "guardamar", "redonda", "hour", "opening", "schedule",
        "horario", "store", "special", "holiday", "closed", "festiv",
    )
    seen: set[str] = set()

    def walk(value, path="$"):
        if len(seen) >= 160:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}"
                if any(needle in key_text.casefold() for needle in needles):
                    output = f"{child_path} = {child!r}"[:1000]
                    if output not in seen:
                        seen.add(output)
                        print(output)
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value[:800]):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            if any(needle in value.casefold() for needle in needles):
                output = f"{path} = {value!r}"[:1000]
                if output not in seen:
                    seen.add(output)
                    print(output)

    walk(payload)
    return build_id if isinstance(build_id, str) and build_id else None


section("2. Production Python/TLS contract")
print("OpenSSL:", ssl.OPENSSL_VERSION)
print("verify paths:", ssl.get_default_verify_paths())
print("HTTP implementation: telegrambot._transport.fetch_bounded / urllib")
print("browser runtime: none")
print("cookie jar: none")

section("3. Existing Guardamar holiday calendar — zero network")
for value in (
    date(2026, 10, 7),
    date(2026, 10, 9),
    date(2026, 10, 12),
    date(2026, 12, 8),
    date(2026, 12, 25),
):
    holidays = official_holidays_on(value)
    print(value.isoformat(), [(item.name, item.kind) for item in holidays])

section("4. Mercadona official locator — Guardamar only")

mercadona_base_url = "https://info.mercadona.es/es/supermercados"
mercadona_base = fetch(
    "mercadona-base",
    mercadona_base_url,
    root="mercadona.es",
    accepted_types=PAGE_TYPES,
    limit=2_000_000,
    accept="text/html,application/xhtml+xml",
    navigation_fallback=True,
)
mercadona_html = decode_text(mercadona_base)

if mercadona_html is not None:
    print("\nMercadona base marker scan:")
    snippets(
        mercadona_html,
        "Guardamar", "03140", "Mediterrani", "Mediterraneo",
        "horario", "opening", "hours", "schedule", "special",
        "holiday", "closed", "festivo", "domingo", "verano",
        "api", "supermercado",
    )
    print("\nMercadona base endpoint/schedule-like strings:")
    print_endpoint_strings(mercadona_html)
    print("\nMercadona forms:")
    print_forms(mercadona_html, mercadona_base_url)
    inspect_scripts(
        "mercadona",
        mercadona_html,
        mercadona_base_url,
        "mercadona.es",
    )

print(
    "\nExploratory postcode URL follows. "
    "The ?s=03140 syntax is NOT accepted as a production contract unless "
    "the locator itself proves it."
)
mercadona_search = fetch(
    "mercadona-03140-exploratory",
    "https://info.mercadona.es/es/supermercados?s=03140",
    root="mercadona.es",
    accepted_types=PAGE_TYPES,
    limit=2_000_000,
    accept="text/html,application/xhtml+xml",
    navigation_fallback=True,
)
mercadona_search_html = decode_text(mercadona_search)
if mercadona_search_html is not None:
    snippets(
        mercadona_search_html,
        "Guardamar", "03140", "Mediterrani", "Mediterraneo",
        "horario", "opening", "hours", "schedule", "special",
        "holiday", "closed", "festivo", "domingo", "verano",
    )

section("5. masymas official locator")

masymas_url = "https://www.masymas.com/localizadordetiendas/localizador.php"
masymas = fetch(
    "masymas-locator",
    masymas_url,
    root="masymas.com",
    accepted_types=PAGE_TYPES,
    limit=1_500_000,
    accept="text/html,application/xhtml+xml",
)
masymas_html = decode_text(masymas)

if masymas_html is not None:
    print("\nmasymas marker scan:")
    snippets(
        masymas_html,
        "Guardamar", "03140", "Puerto", "localizador",
        "propiedadestienda", "horario", "festivo", "especial",
        "cerrado", "domingo", "verano", "ajax", "json", "api",
    )
    print("\nmasymas endpoint/schedule-like strings:")
    print_endpoint_strings(masymas_html)
    print("\nmasymas forms/selects:")
    print_forms(masymas_html, masymas_url)
    inspect_scripts(
        "masymas",
        masymas_html,
        masymas_url,
        "masymas.com",
    )

print("\nKnown official per-store control: Id=13 is Alcora, NOT Guardamar.")
masymas_control = fetch(
    "masymas-control-id13",
    "https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=13",
    root="masymas.com",
    accepted_types=PAGE_TYPES,
    limit=512_000,
    accept="text/html,application/xhtml+xml",
)
masymas_control_html = decode_text(masymas_control)
if masymas_control_html is not None:
    snippets(
        masymas_control_html,
        "Alcora", "horario", "festivo", "especial", "cerrado",
        "apertura", "domingo", "coordenadas", "telefono",
        "propiedadestienda",
    )

section("6. DIA official Guardamar store 36111")

dia_url = (
    "https://www.dia.es/tiendas/buscador-tiendas/"
    "alicante/guardamar-del-segura/03140/36111"
)
dia = fetch(
    "dia-store-36111",
    dia_url,
    root="dia.es",
    accepted_types=PAGE_TYPES,
    limit=2_000_000,
    accept="text/html,application/xhtml+xml",
    navigation=True,
)
dia_html = decode_text(dia)

if dia_html is not None:
    print("\nDIA marker scan:")
    snippets(
        dia_html,
        "36111", "Guardamar", "Redonda", "horario", "opening",
        "hours", "schedule", "special", "holiday", "closed",
        "festivo", "domingo", "verano", "__NEXT_DATA__", "api",
        "tienda", "store",
    )
    print("\nDIA endpoint/schedule-like strings:")
    print_endpoint_strings(dia_html)
    print("\nDIA Next.js embedded-data inspection:")
    build_id = inspect_dia_next_data(dia_html)

    if build_id:
        data_url = (
            f"https://www.dia.es/_next/data/{build_id}/"
            "tiendas/buscador-tiendas/alicante/"
            "guardamar-del-segura/03140/36111.json"
        )
        dia_data = fetch(
            "dia-next-data",
            data_url,
            root="dia.es",
            accepted_types=JSON_TYPES,
            limit=1_000_000,
            accept="application/json,text/plain",
            navigation=True,
        )
        dia_data_text = decode_text(dia_data)
        if dia_data_text is not None:
            print("\nDIA _next/data marker scan:")
            snippets(
                dia_data_text,
                "36111", "Guardamar", "Redonda", "horario", "opening",
                "hours", "schedule", "special", "holiday", "closed",
                "festivo", "domingo",
            )

    inspect_scripts(
        "dia",
        dia_html,
        dia_url,
        "dia.es",
    )

section("7. Probe cost summary")
print("network_requests:", NETWORK_REQUESTS)
print("accepted_body_bytes:", TOTAL_BYTES)
print("raw_response_persistence: none")
print("browser_or_javascript_execution: none")
print("authentication_or_cookie_state: none")
print(
    "NOTE: JavaScript downloads above are discovery-only. "
    "Production must call only the final exact store endpoints."
)
PY
PROBE_RC=$?

printf '\n============================================================\n'
printf '8. Read-only integrity check\n'
printf '============================================================\n'

AFTER_BRANCH="$(git -C "$ROOT" branch --show-current || true)"
AFTER_HEAD="$(git -C "$ROOT" rev-parse HEAD || true)"
AFTER_STATUS="$(git -C "$ROOT" status --porcelain=v1 || true)"

printf 'Branch before: %s\n' "$BEFORE_BRANCH"
printf 'Branch after:  %s\n' "$AFTER_BRANCH"
printf 'HEAD before:   %s\n' "$BEFORE_HEAD"
printf 'HEAD after:    %s\n' "$AFTER_HEAD"
printf 'Git status after:\n%s\n' "${AFTER_STATUS:-(clean)}"
printf 'Probe exit code: %s\n' "$PROBE_RC"

if [ "$AFTER_BRANCH" != "$BEFORE_BRANCH" ]; then
  echo "INTEGRITY-FAIL: branch changed during read-only probe."
  exit 2
fi
if [ "$AFTER_HEAD" != "$BEFORE_HEAD" ]; then
  echo "INTEGRITY-FAIL: HEAD changed during read-only probe."
  exit 2
fi
if [ "$AFTER_STATUS" != "$BEFORE_STATUS" ]; then
  echo "INTEGRITY-FAIL: worktree status changed during read-only probe."
  exit 2
fi

if [ "$PROBE_RC" -ne 0 ]; then
  echo "Probe failed before completing all checks."
  exit "$PROBE_RC"
fi

printf '\nProbe complete.\n'
printf 'Report saved outside project state: %s\n' "$REPORT"
printf 'Please send the complete output back for endpoint analysis.\n'
