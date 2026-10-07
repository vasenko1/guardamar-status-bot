#!/data/data/com.termux/files/usr/bin/bash
set -u
set -o pipefail
export LC_ALL=C

ROOT="${HOME}/bots/guardamar-status"
CACHE_BASE="${HOME}/.cache/guardamar-supermarket-hours-probe"
STAMP="$(date '+%Y%m%d-%H%M%S')"
REPORT="${CACHE_BASE}/report-${STAMP}.txt"
PYPROBE="${CACHE_BASE}/probe-${STAMP}.py"

mkdir -p "$CACHE_BASE"

cleanup() {
  rm -f "$PYPROBE"
}
trap cleanup EXIT INT TERM

exec > >(tee "$REPORT") 2>&1

section() {
  printf '\n============================================================\n%s\n============================================================\n' "$1"
}

section "1. Safety / environment"

printf 'Madrid: '
TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z'
printf 'Device: '
uname -a
printf 'Bash: %s\n' "${BASH_VERSION:-unknown}"
printf 'Python: '
python --version
printf 'Report: %s\n' "$REPORT"

if [ ! -d "$ROOT/.git" ]; then
  echo "STOP: repository not found at $ROOT"
  exit 1
fi

PRODUCTION_HEAD="$(git -C "$ROOT" rev-parse HEAD)" || exit 1
PRODUCTION_BRANCH="$(git -C "$ROOT" branch --show-current)" || exit 1

printf 'Repo: %s\n' "$ROOT"
printf 'Branch: %s\n' "$PRODUCTION_BRANCH"
printf 'HEAD: %s\n' "$PRODUCTION_HEAD"
STATUS_BEFORE="$(git -C "$ROOT" status --porcelain=v1)" || exit 1
printf 'Git status before:\n%s\n' "$STATUS_BEFORE"

cat > "$PYPROBE" <<'PY'
from __future__ import annotations

import html
import json
import re
import ssl
import sys
import urllib.parse
from datetime import date
from html.parser import HTMLParser

from telegrambot._transport import BoundedFetchError, fetch_bounded
from telegrambot.holidays import official_holidays_on


SERVICE_HEADERS = {
    "User-Agent": "GuardamarMorningDigest/0.14",
    "Accept": (
        "text/html,application/xhtml+xml,application/json,"
        "application/javascript,text/javascript,text/plain"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
}
NAV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": SERVICE_HEADERS["Accept"],
    "Accept-Language": SERVICE_HEADERS["Accept-Language"],
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}
ASSET_HEADERS = {
    "User-Agent": SERVICE_HEADERS["User-Agent"],
    "Accept": (
        "application/json,application/javascript,text/javascript,"
        "text/plain,text/html"
    ),
    "Accept-Language": SERVICE_HEADERS["Accept-Language"],
}

PAGE_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "application/json",
})
ASSET_TYPES = frozenset({
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "text/javascript",
    "text/plain",
    "text/html",
    "application/xhtml+xml",
})

PAGE_LIMIT = 2 * 1024 * 1024
ASSET_LIMIT = 768 * 1024
MAX_ASSETS_PER_RETAILER = 8
MAX_ASSET_BYTES_PER_RETAILER = 4 * 1024 * 1024

ENDPOINT_NEEDLES = (
    "api",
    "store",
    "stores",
    "tienda",
    "tiendas",
    "supermerc",
    "horario",
    "opening",
    "hours",
    "schedule",
    "locator",
    "localizador",
    "propiedad",
)


SECRET_VALUE_RE = re.compile(
    r"""(?ix)
    (
        (?:api[_-]?key|token|secret|authorization|client[_-]?secret)
        \s*[:=]\s*
        [\"']?
    )
    ([A-Za-z0-9._~+\/-]{8,})
    """
)
QUERY_SECRET_RE = re.compile(
    r"""(?ix)
    ([?&](?:api[_-]?key|token|secret|access[_-]?token)=)
    ([^&#\s]+)
    """
)


def safe_output(value: object) -> str:
    text = str(value)
    text = SECRET_VALUE_RE.sub(r"\1<redacted>", text)
    text = QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    return text


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def url_policy(*hosts: str):
    allowed_hosts = {host.casefold() for host in hosts}

    def allowed(url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.casefold() in allowed_hosts
            and parsed.username is None
            and parsed.password is None
            and port in (None, 443)
        )

    return allowed


def fetch(
    label: str,
    url: str,
    hosts: tuple[str, ...],
    *,
    limit: int,
    types: frozenset[str],
    headers: dict[str, str],
    navigation_fallback: bool = False,
) -> tuple[bytes, str, str] | None:
    print()
    print(f"--- {label} ---")
    print("url:", safe_output(url))
    print("allowed_hosts:", ",".join(hosts))
    print("limit_bytes:", limit)

    try:
        payload, final_url, content_type = fetch_bounded(
            url,
            is_allowed_url=url_policy(*hosts),
            accepted_types=types,
            limit_bytes=limit,
            timeout_seconds=15,
            headers=headers,
        )
    except BoundedFetchError as exc:
        print("result: FAIL")
        print("code:", exc.code)
        print("status:", exc.status)
        if (
            navigation_fallback
            and headers is SERVICE_HEADERS
            and exc.status in {403, 406}
        ):
            print(
                "navigation_fallback: one reviewed retry after explicit "
                f"HTTP {exc.status}"
            )
            return fetch(
                label + " navigation fallback",
                url,
                hosts,
                limit=limit,
                types=types,
                headers=NAV_HEADERS,
                navigation_fallback=False,
            )
        return None

    print("result: OK")
    print("final_url:", safe_output(final_url))
    print("content_type:", content_type)
    print("size_bytes:", len(payload))
    print("redirected:", final_url != url)
    return payload, final_url, content_type


def decode(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def normalize_discovery_text(text: str) -> str:
    return (
        text
        .replace(r"\/", "/")
        .replace(r"\u002F", "/")
        .replace(r"\u002f", "/")
        .replace(r"\x2F", "/")
        .replace(r"\x2f", "/")
    )


def marker_scan(text: str, *needles: str, limit: int = 40) -> None:
    compact = re.sub(
        r"\s+",
        " ",
        html.unescape(normalize_discovery_text(text)),
    )
    folded = compact.casefold()
    seen: set[str] = set()

    for needle in needles:
        target = needle.casefold()
        start = 0
        while len(seen) < limit:
            index = folded.find(target, start)
            if index < 0:
                break
            lo = max(0, index - 140)
            hi = min(len(compact), index + len(target) + 220)
            snippet = compact[lo:hi].strip()
            key = snippet.casefold()
            if key not in seen:
                seen.add(key)
                print(f"[{needle}] {safe_output(snippet)}")
            start = index + max(1, len(target))

    if not seen:
        print("(no requested markers found)")


def endpoint_scan(text: str, limit: int = 100) -> None:
    text = text.replace(r"\/", "/")
    text = re.sub(r"(?i)\\u002f", "/", text)
    patterns = (
        re.compile(r'''["']([^"'\\]{3,700})["']'''),
        re.compile(
            r'''https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{4,700}'''
        ),
    )
    seen: set[str] = set()

    for pattern in patterns:
        for match in pattern.finditer(text):
            value = match.group(1) if match.lastindex else match.group(0)
            folded = value.casefold()
            if not any(needle in folded for needle in ENDPOINT_NEEDLES):
                continue
            value = re.sub(r"\s+", " ", value).strip()
            if value in seen:
                continue
            seen.add(value)
            print(safe_output(value[:900]))
            if len(seen) >= limit:
                return

    if not seen:
        print("(no endpoint-like strings found)")


class ScriptParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_host = urllib.parse.urlsplit(base_url).hostname
        self.same: list[str] = []
        self.external: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "script":
            return
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        src = values.get("src")
        if not isinstance(src, str) or not src:
            return
        absolute = urllib.parse.urljoin(self.base_url, src)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme != "https" or parsed.hostname is None:
            return
        target = (
            self.same
            if parsed.hostname == self.base_host
            else self.external
        )
        if absolute not in target:
            target.append(absolute)


def script_score(url: str) -> int:
    folded = url.casefold()
    score = 0
    for marker in (
        "tienda",
        "store",
        "supermerc",
        "buscador",
        "localiz",
        "horario",
        "opening",
    ):
        if marker in folded:
            score += 100
    if "/pages/" in folded or "/app/" in folded:
        score += 40
    if "_next/static/chunks" in folded:
        score += 10
    return score


def inspect_scripts(
    label: str,
    html_text: str,
    base_url: str,
    host: str,
) -> None:
    parser = ScriptParser(base_url)
    parser.feed(html_text)
    same = sorted(
        parser.same,
        key=lambda value: (-script_score(value), parser.same.index(value)),
    )

    print("same_host_script_count:", len(same))
    print("external_script_count:", len(parser.external))
    for url in parser.external[:12]:
        print("external_script_not_fetched:", safe_output(url))

    total = 0
    fetched = 0
    for url in same:
        if fetched >= MAX_ASSETS_PER_RETAILER:
            break
        if total >= MAX_ASSET_BYTES_PER_RETAILER:
            break

        remaining = MAX_ASSET_BYTES_PER_RETAILER - total
        if remaining <= 0:
            break
        request_limit = min(ASSET_LIMIT, remaining)

        result = fetch(
            f"{label} asset {fetched + 1}",
            url,
            (host,),
            limit=request_limit,
            types=ASSET_TYPES,
            headers=ASSET_HEADERS,
        )
        fetched += 1
        if result is None:
            continue
        payload, _, _ = result
        total += len(payload)
        endpoint_scan(decode(payload), limit=50)

    print(
        f"{label}_asset_summary:",
        f"attempted={fetched}",
        f"accepted_bytes={total}",
    )


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


def dia_manifest_asset_urls(text: str) -> tuple[str, ...]:
    normalized = normalize_discovery_text(text)
    candidates: list[str] = []
    positions = [
        match.start()
        for match in re.finditer(
            r"buscador-tiendas|tiendas/buscador",
            normalized,
            flags=re.IGNORECASE,
        )
    ]
    for position in positions[:12]:
        window = normalized[
            max(0, position - 6000): position + 6000
        ]
        for raw in re.findall(
            r"""(?i)
            ["'](
                (?:_next/)?static/
                [^"'\s]{1,500}?
                \.js
            )["']
            """,
            window,
            flags=re.VERBOSE,
        ):
            absolute = urllib.parse.urljoin(
                "https://www.dia.es/",
                raw.lstrip("/"),
            )
            if absolute not in candidates:
                candidates.append(absolute)
            if len(candidates) >= 4:
                return tuple(candidates)
    return tuple(candidates)


def inspect_dia_next_data(html_text: str) -> None:
    parser = NextDataParser()
    parser.feed(html_text)
    raw = "".join(parser.parts).strip()
    if not raw:
        print("__NEXT_DATA__: absent")
        return

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("__NEXT_DATA__: invalid", exc)
        return

    print("__NEXT_DATA__: present")
    build_id = value.get("buildId")
    print("build_id:", build_id)
    print("page:", value.get("page"))

    serialized = json.dumps(value, ensure_ascii=False)
    marker_scan(
        serialized,
        "36111",
        "Guardamar",
        "Redonda",
        "horario",
        "opening",
        "hours",
        "schedule",
        "store",
        limit=60,
    )

    if not isinstance(build_id, str) or not build_id:
        return

    data_url = (
        "https://www.dia.es/_next/data/"
        f"{build_id}/tiendas/buscador-tiendas/alicante/"
        "guardamar-del-segura/03140/36111.json"
    )
    result = fetch(
        "DIA _next/data exact store",
        data_url,
        ("www.dia.es",),
        limit=1024 * 1024,
        types=ASSET_TYPES,
        headers=ASSET_HEADERS,
    )
    if result is not None:
        payload, _, _ = result
        text = decode(payload)
        marker_scan(
            text,
            "36111",
            "Guardamar",
            "Redonda",
            "horario",
            "opening",
            "hours",
            "schedule",
            "store",
            limit=60,
        )
        endpoint_scan(text)

    manifest_url = (
        "https://www.dia.es/_next/static/"
        f"{build_id}/_buildManifest.js"
    )
    result = fetch(
        "DIA build manifest",
        manifest_url,
        ("www.dia.es",),
        limit=1024 * 1024,
        types=ASSET_TYPES,
        headers=ASSET_HEADERS,
    )
    if result is not None:
        payload, _, _ = result
        text = decode(payload)
        marker_scan(
            text,
            "buscador-tiendas",
            "tiendas",
            "store",
            "36111",
            limit=40,
        )
        endpoint_scan(text)

        manifest_assets = dia_manifest_asset_urls(text)
        print(
            "DIA manifest route asset candidates:",
            len(manifest_assets),
        )
        route_total = 0
        for index, asset_url in enumerate(manifest_assets, start=1):
            remaining = (2 * 1024 * 1024) - route_total
            if remaining <= 0:
                break
            route_result = fetch(
                f"DIA manifest route asset {index}",
                asset_url,
                ("www.dia.es",),
                limit=min(512 * 1024, remaining),
                types=ASSET_TYPES,
                headers=ASSET_HEADERS,
            )
            if route_result is None:
                continue
            route_payload, _, _ = route_result
            route_total += len(route_payload)
            endpoint_scan(decode(route_payload), limit=80)
        print(
            "DIA manifest route assets accepted bytes:",
            route_total,
        )


def masymas_guardamar_candidates(text: str) -> None:
    compact = re.sub(r"\s+", " ", html.unescape(text))
    folded = compact.casefold()
    start = 0
    found = False

    option_pattern = re.compile(
        r"<option\\b([^>]*)>(.*?)</option>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for attrs, body in option_pattern.findall(text):
        visible = re.sub(r"<[^>]+>", " ", html.unescape(body))
        visible = re.sub(r"\\s+", " ", visible).strip()
        if "guardamar" not in visible.casefold():
            continue
        value_match = re.search(
            r"""(?i)\\bvalue\\s*=\\s*["']?([^"' >]+)""",
            attrs,
        )
        option_value = value_match.group(1) if value_match else "(missing)"
        print(
            "Guardamar locator option:",
            safe_output(visible),
            "value=",
            safe_output(option_value),
        )
        found = True

    while True:
        index = folded.find("guardamar", start)
        if index < 0:
            break
        window = compact[max(0, index - 700): index + 900]
        ids = sorted(set(re.findall(
            r"(?:Id=|id[\"'=:\s]+)(\d{1,6})",
            window,
            flags=re.IGNORECASE,
        )))
        print(
            "Guardamar nearby locator fragment:",
            safe_output(window[:1500]),
        )
        if ids:
            print("candidate_store_ids_near_Guardamar:", ids)
            found = True
        start = index + len("guardamar")
        if found:
            break

    if not found:
        print("candidate_store_ids_near_Guardamar: none in main HTML")


section("2. Production TLS and reviewed Guardamar calendar")
print("OpenSSL:", ssl.OPENSSL_VERSION)
print("verify_paths:", ssl.get_default_verify_paths())

for day in (
    date(2026, 10, 7),
    date(2026, 10, 8),
    date(2026, 10, 9),
    date(2026, 10, 12),
):
    holidays = official_holidays_on(day)
    print(
        day.isoformat(),
        [f"{item.name} ({item.scope})" for item in holidays],
    )


section("3. Mercadona Guardamar")

mercadona_url = "https://info.mercadona.es/es/supermercados"
result = fetch(
    "Mercadona official locator",
    mercadona_url,
    ("info.mercadona.es",),
    limit=PAGE_LIMIT,
    types=PAGE_TYPES,
    headers=SERVICE_HEADERS,
    navigation_fallback=True,
)
if result is not None:
    payload, final_url, _ = result
    text = decode(payload)
    marker_scan(
        text,
        "Guardamar",
        "03140",
        "Mediterrani",
        "Mediterraneo",
        "horario",
        "opening",
        "hours",
        "schedule",
        "supermercado",
        "api",
    )
    print("endpoint-like strings:")
    endpoint_scan(text)
    inspect_scripts(
        "mercadona",
        text,
        final_url,
        "info.mercadona.es",
    )

mercadona_search_url = (
    "https://info.mercadona.es/es/supermercados?s=03140"
)
search_result = fetch(
    "Mercadona exploratory first-party search 03140",
    mercadona_search_url,
    ("info.mercadona.es",),
    limit=PAGE_LIMIT,
    types=PAGE_TYPES,
    headers=SERVICE_HEADERS,
    navigation_fallback=True,
)
if search_result is not None:
    payload, _, _ = search_result
    text = decode(payload)
    marker_scan(
        text,
        "Guardamar",
        "03140",
        "Mediterrani",
        "Mediterraneo",
        "horario",
        "opening",
        "hours",
        "schedule",
        "supermercado",
        "api",
        limit=60,
    )
    print("exploratory search endpoint-like strings:")
    endpoint_scan(text)


section("4. masymas Guardamar")

masymas_url = (
    "https://www.masymas.com/localizadordetiendas/localizador.php"
)
result = fetch(
    "masymas official locator",
    masymas_url,
    ("www.masymas.com",),
    limit=PAGE_LIMIT,
    types=PAGE_TYPES,
    headers=SERVICE_HEADERS,
    navigation_fallback=True,
)
if result is not None:
    payload, final_url, _ = result
    text = decode(payload)
    marker_scan(
        text,
        "Guardamar",
        "03140",
        "Puerto",
        "localizador",
        "propiedadestienda",
        "horario",
        "ajax",
        "json",
        "api",
    )
    masymas_guardamar_candidates(text)
    print("endpoint-like strings:")
    endpoint_scan(text)
    inspect_scripts(
        "masymas",
        text,
        final_url,
        "www.masymas.com",
    )


section("5. DIA Guardamar 36111")

dia_url = (
    "https://www.dia.es/tiendas/buscador-tiendas/alicante/"
    "guardamar-del-segura/03140/36111"
)
result = fetch(
    "DIA exact official store 36111",
    dia_url,
    ("www.dia.es",),
    limit=PAGE_LIMIT,
    types=PAGE_TYPES,
    headers=SERVICE_HEADERS,
    navigation_fallback=True,
)
if result is not None:
    payload, final_url, _ = result
    text = decode(payload)
    marker_scan(
        text,
        "36111",
        "Guardamar",
        "Redonda",
        "horario",
        "opening",
        "hours",
        "schedule",
        "__NEXT_DATA__",
        "api",
        "store",
    )
    print("endpoint-like strings:")
    endpoint_scan(text)
    inspect_dia_next_data(text)
    inspect_scripts(
        "dia",
        text,
        final_url,
        "www.dia.es",
    )


section("6. Probe conclusion")
print(
    "The probe performed only bounded first-party GETs and local reads. "
    "It did not write project state or call Telegram."
)
PY

section "2. Probe syntax preflight"

python - "$PYPROBE" <<'PY'
import ast
from pathlib import Path
import sys

ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("OK: embedded Python probe parses.")
PY

section "3. Run source audit"

(
  cd "$ROOT" || exit 1
  PYTHONPATH=src python "$PYPROBE"
)
PROBE_RC=$?

section "4. Read-only integrity check"

HEAD_AFTER="$(git -C "$ROOT" rev-parse HEAD)" || exit 1
BRANCH_AFTER="$(git -C "$ROOT" branch --show-current)" || exit 1

printf 'Branch before: %s\n' "$PRODUCTION_BRANCH"
printf 'Branch after:  %s\n' "$BRANCH_AFTER"
printf 'HEAD before:   %s\n' "$PRODUCTION_HEAD"
printf 'HEAD after:    %s\n' "$HEAD_AFTER"
STATUS_AFTER="$(git -C "$ROOT" status --porcelain=v1)" || exit 1
printf 'Git status after:\n%s\n' "$STATUS_AFTER"

if [ "$HEAD_AFTER" != "$PRODUCTION_HEAD" ]; then
  echo "ERROR: production HEAD changed during read-only probe."
  exit 2
fi

if [ "$BRANCH_AFTER" != "$PRODUCTION_BRANCH" ]; then
  echo "ERROR: production branch changed during read-only probe."
  exit 2
fi

if [ "$STATUS_AFTER" != "$STATUS_BEFORE" ]; then
  echo "ERROR: production working tree changed during read-only probe."
  exit 2
fi

printf '\nProbe exit code: %s\n' "$PROBE_RC"
printf 'Report saved outside project state: %s\n' "$REPORT"
printf 'Please send the complete report output back for endpoint analysis.\n'

exit "$PROBE_RC"
