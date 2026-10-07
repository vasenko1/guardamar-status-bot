#!/data/data/com.termux/files/usr/bin/bash
set -u
set -o pipefail
export LC_ALL=C

ROOT="${HOME}/bots/guardamar-status"
CACHE_BASE="${HOME}/.cache/guardamar-supermarket-hours-probe"
STAMP="$(date '+%Y%m%d-%H%M%S')"
mkdir -p "$CACHE_BASE"
WORK="$(mktemp -d "${CACHE_BASE}/run.XXXXXX")"
REPORT="${CACHE_BASE}/report-${STAMP}.txt"

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

exec > >(tee "$REPORT") 2>&1

section() {
  printf '\n============================================================\n%s\n============================================================\n' "$1"
}

sha256_file() {
  python - "$1" <<'PY'
import hashlib
from pathlib import Path
import sys

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for block in iter(lambda: handle.read(131072), b""):
        digest.update(block)
print(digest.hexdigest())
PY
}

cat > "${WORK}/fetch_https.py" <<'PY'
from __future__ import annotations

import http.client
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if len(sys.argv) != 7:
    raise SystemExit(
        "usage: fetch_https.py URL HOSTS LIMIT BODY HEADERS META"
    )

url, hosts_csv, raw_limit, body_path, headers_path, meta_path = sys.argv[1:]
allowed_hosts = {
    value.strip().casefold()
    for value in hosts_csv.split(",")
    if value.strip()
}
limit = int(raw_limit)


def allowed(candidate: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(candidate)
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


class RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        absolute = urllib.parse.urljoin(request.full_url, newurl)
        if not allowed(absolute):
            raise RuntimeError(f"redirect-outside-allowlist:{absolute}")
        return super().redirect_request(
            request,
            fp,
            code,
            msg,
            headers,
            absolute,
        )


body_file = Path(body_path)
headers_file = Path(headers_path)
meta_file = Path(meta_path)
body_file.write_bytes(b"")
headers_file.write_text("", encoding="utf-8")

if not allowed(url):
    meta_file.write_text(
        "1\t0\t\t\t0\turl-policy\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

request = urllib.request.Request(
    url,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14; Mobile) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": (
            "application/json,text/html,application/xhtml+xml,"
            "application/javascript,text/javascript,text/plain"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    },
    method="GET",
)
opener = urllib.request.build_opener(RedirectHandler())

try:
    with opener.open(request, timeout=25) as response:
        final_url = response.geturl()
        if not allowed(final_url):
            raise RuntimeError("final-url-outside-allowlist")
        status = int(getattr(response, "status", 200))
        content_type = response.headers.get_content_type()
        headers_file.write_text(
            "".join(
                f"{key}: {value}\n"
                for key, value in response.headers.items()
            ),
            encoding="utf-8",
        )
        payload = response.read(limit + 1)
        if len(payload) > limit:
            meta_file.write_text(
                f"1\t{status}\t{final_url}\t{content_type}\t"
                f"{len(payload)}\ttoo-large\n",
                encoding="utf-8",
            )
            raise SystemExit(0)
        body_file.write_bytes(payload)
        meta_file.write_text(
            f"0\t{status}\t{final_url}\t{content_type}\t"
            f"{len(payload)}\tok\n",
            encoding="utf-8",
        )
except urllib.error.HTTPError as exc:
    content_type = (
        exc.headers.get_content_type()
        if exc.headers is not None
        else ""
    )
    if exc.headers is not None:
        headers_file.write_text(
            "".join(
                f"{key}: {value}\n"
                for key, value in exc.headers.items()
            ),
            encoding="utf-8",
        )
    meta_file.write_text(
        f"1\t{exc.code}\t{exc.geturl()}\t{content_type}\t0\thttp-error\n",
        encoding="utf-8",
    )
except (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
    OSError,
    http.client.HTTPException,
    RuntimeError,
) as exc:
    reason = str(exc).replace("\t", " ").replace("\n", " ")
    meta_file.write_text(
        f"1\t0\t\t\t0\t{reason[:240]}\n",
        encoding="utf-8",
    )
PY

scan_text() {
  local file="$1"
  shift
  python - "$file" "$@" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
keywords = [value.casefold() for value in sys.argv[2:]]
try:
    text = path.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    print(f"scan error: {exc}")
    raise SystemExit(0)

flat = re.sub(r"\s+", " ", text)
folded = flat.casefold()
seen = set()
shown = 0

for keyword in keywords:
    start = 0
    while shown < 80:
        index = folded.find(keyword, start)
        if index < 0:
            break
        lo = max(0, index - 180)
        hi = min(len(flat), index + len(keyword) + 280)
        snippet = flat[lo:hi].strip()
        key = snippet.casefold()
        if key not in seen:
            seen.add(key)
            print(f"[{keyword}] {snippet}")
            shown += 1
        start = index + max(1, len(keyword))

if shown == 0:
    print("(no requested markers found)")
PY
}

scan_endpoint_strings() {
  local file="$1"
  python - "$file" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
try:
    text = path.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    print(f"scan error: {exc}")
    raise SystemExit(0)

needles = (
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
patterns = (
    re.compile(r'''["']([^"'\\]{3,700})["']'''),
    re.compile(
        r'''https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{4,700}'''
    ),
)
seen = set()

for pattern in patterns:
    for match in pattern.finditer(text):
        value = match.group(1) if match.lastindex else match.group(0)
        folded = value.casefold()
        if not any(needle in folded for needle in needles):
            continue
        value = re.sub(r"\s+", " ", value).strip()
        if value in seen:
            continue
        seen.add(value)
        print(value[:900])
        if len(seen) >= 160:
            raise SystemExit

if not seen:
    print("(no endpoint-like strings found)")
PY
}

extract_scripts() {
  local html_file="$1"
  local base_url="$2"
  local same_file="$3"
  local external_file="$4"

  python - "$html_file" "$base_url" "$same_file" "$external_file" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import sys

html_path, base_url, same_path, external_path = sys.argv[1:5]
base = urlsplit(base_url)
same = []
external = []

class Parser(HTMLParser):
    def handle_starttag(self, tag, attrs):
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
        absolute = urljoin(base_url, src)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or parsed.hostname is None:
            return
        target = same if parsed.hostname == base.hostname else external
        if absolute not in target:
            target.append(absolute)

def score(url: str) -> tuple[int, int]:
    folded = url.casefold()
    value = 0
    for marker in (
        "tienda", "store", "supermerc", "buscador",
        "localiz", "horario", "opening",
    ):
        if marker in folded:
            value += 100
    if "/pages/" in folded or "/app/" in folded:
        value += 40
    if "_next/static/chunks" in folded:
        value += 10
    return (-value, same.index(url))

try:
    Parser().feed(
        Path(html_path).read_text(encoding="utf-8", errors="replace")
    )
except Exception as exc:
    print(f"script extraction error: {exc}", file=sys.stderr)

ranked = sorted(same, key=score)
Path(same_path).write_text(
    "\n".join(ranked) + ("\n" if ranked else ""),
    encoding="utf-8",
)
Path(external_path).write_text(
    "\n".join(external) + ("\n" if external else ""),
    encoding="utf-8",
)

print(f"same-host scripts: {len(ranked)}")
for url in ranked[:20]:
    print(url)
print(f"external scripts: {len(external)}")
for url in external[:20]:
    print("EXTERNAL", url)
PY
}

inspect_forms() {
  local html_file="$1"
  local base_url="$2"

  python - "$html_file" "$base_url" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
import sys

path, base = sys.argv[1:3]

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.select = None

    def handle_starttag(self, tag, attrs):
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        lowered = tag.casefold()
        if lowered == "form":
            print(
                "FORM",
                str(values.get("method", "GET")).upper(),
                urljoin(base, str(values.get("action", ""))),
            )
        elif lowered == "input":
            print(
                "INPUT",
                values.get("name"),
                values.get("type"),
                values.get("value"),
            )
        elif lowered == "select":
            self.select = values.get("name")
            print("SELECT", self.select)
        elif lowered == "option" and self.select:
            print("OPTION", self.select, values.get("value"))

    def handle_endtag(self, tag):
        if tag.casefold() == "select":
            self.select = None

try:
    Parser().feed(
        Path(path).read_text(encoding="utf-8", errors="replace")
    )
except Exception as exc:
    print("form parse error:", exc)
PY
}

LAST_BODY=""
LAST_HEADERS=""
LAST_META=""
LAST_RC=""
LAST_HTTP=""
LAST_EFFECTIVE=""
LAST_TYPE=""
LAST_SIZE=""
LAST_REASON=""

fetch_page() {
  local label="$1"
  local url="$2"
  local hosts="$3"
  local limit="$4"

  LAST_BODY="${WORK}/${label}.body"
  LAST_HEADERS="${WORK}/${label}.headers"
  LAST_META="${WORK}/${label}.meta"
  : > "$LAST_BODY"
  : > "$LAST_HEADERS"
  : > "$LAST_META"

  printf '\n--- %s ---\nURL: %s\nAllowed hosts: %s\nLimit: %s bytes\n' \
    "$label" "$url" "$hosts" "$limit"

  python "${WORK}/fetch_https.py" \
    "$url" "$hosts" "$limit" \
    "$LAST_BODY" "$LAST_HEADERS" "$LAST_META"

  IFS=$'\t' read -r \
    LAST_RC LAST_HTTP LAST_EFFECTIVE LAST_TYPE LAST_SIZE LAST_REASON \
    < "$LAST_META" || true

  printf 'fetch_rc: %s\nhttp: %s\ncontent_type: %s\nsize: %s\n' \
    "${LAST_RC:-}" "${LAST_HTTP:-}" "${LAST_TYPE:-}" "${LAST_SIZE:-}"
  printf 'effective_url: %s\nreason: %s\n' \
    "${LAST_EFFECTIVE:-}" "${LAST_REASON:-}"

  if [ "${LAST_RC:-1}" = "0" ] && [ -s "$LAST_BODY" ]; then
    printf 'sha256: %s\n' "$(sha256_file "$LAST_BODY")"
  else
    printf 'sha256: (no accepted body)\n'
  fi

  printf 'response headers (selected):\n'
  grep -iE \
    '^(content-type:|content-length:|location:|cache-control:|etag:|last-modified:|server:|x-|cf-)' \
    "$LAST_HEADERS" | tail -n 40 || true

  return 0
}

inspect_scripts() {
  local label="$1"
  local html_file="$2"
  local base_url="$3"
  local host="$4"

  local same="${WORK}/${label}.scripts.same"
  local external="${WORK}/${label}.scripts.external"

  printf '\nReferenced scripts:\n'
  extract_scripts "$html_file" "$base_url" "$same" "$external"

  if [ ! -s "$same" ]; then
    printf '(no same-host scripts to inspect)\n'
    return 0
  fi

  local count=0
  local total=0
  local max_assets=10
  local per_asset_limit=786432
  local total_limit=4194304

  while IFS= read -r url; do
    [ -n "$url" ] || continue
    [ "$count" -lt "$max_assets" ] || break
    [ "$total" -lt "$total_limit" ] || break

    count=$((count + 1))

    fetch_page \
      "${label}-asset-${count}" \
      "$url" \
      "$host" \
      "$per_asset_limit"

    if [ "${LAST_RC:-1}" != "0" ]; then
      continue
    fi

    total=$((total + LAST_SIZE))
    printf 'asset cumulative accepted bytes: %s\n' "$total"
    scan_endpoint_strings "$LAST_BODY"
  done < "$same"

  printf '\nScript inspection summary: assets=%s accepted_bytes=%s\n' \
    "$count" "$total"
}

inspect_dia_next_data() {
  local html_file="$1"
  local build_file="${WORK}/dia-build-id.txt"
  : > "$build_file"

  python - "$html_file" "$build_file" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import json
import sys

html_path, build_path = sys.argv[1:3]

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "script":
            return
        values = {
            str(key).casefold(): value
            for key, value in attrs
            if value is not None
        }
        if values.get("id") == "__NEXT_DATA__":
            self.capture = True

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self.capture:
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

parser = Parser()
parser.feed(
    Path(html_path).read_text(encoding="utf-8", errors="replace")
)
raw = "".join(parser.parts).strip()

if not raw:
    print("__NEXT_DATA__: absent")
    raise SystemExit(0)

try:
    payload = json.loads(raw)
except json.JSONDecodeError as exc:
    print("__NEXT_DATA__: invalid JSON:", exc)
    raise SystemExit(0)

print("__NEXT_DATA__: present")

build_id = payload.get("buildId")
if isinstance(build_id, str) and build_id:
    Path(build_path).write_text(build_id, encoding="utf-8")
    print("buildId:", build_id)

page = payload.get("page")
if isinstance(page, str):
    print("page:", page)

needles = (
    "36111",
    "guardamar",
    "redonda",
    "hour",
    "opening",
    "schedule",
    "horario",
    "store",
)
seen = set()

def walk(value, path="$"):
    if len(seen) >= 160:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            candidate = f"{path}.{key_text}"
            if any(needle in key_text.casefold() for needle in needles):
                out = f"{candidate} = {child!r}"[:1000]
                if out not in seen:
                    seen.add(out)
                    print(out)
            walk(child, candidate)
    elif isinstance(value, list):
        for index, child in enumerate(value[:500]):
            walk(child, f"{path}[{index}]")
    elif isinstance(value, str):
        folded = value.casefold()
        if any(needle in folded for needle in needles):
            out = f"{path} = {value!r}"[:1000]
            if out not in seen:
                seen.add(out)
                print(out)

walk(payload)
PY

  if [ -s "$build_file" ]; then
    local build_id
    build_id="$(cat "$build_file")"

    local data_url
    data_url="https://www.dia.es/_next/data/${build_id}/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111.json"

    fetch_page \
      "dia-next-data" \
      "$data_url" \
      "www.dia.es" \
      1048576

    if [ "${LAST_RC:-1}" = "0" ]; then
      printf 'DIA _next/data marker scan:\n'
      scan_text \
        "$LAST_BODY" \
        36111 guardamar redonda horario opening hours schedule store
      printf 'DIA _next/data endpoint-like strings:\n'
      scan_endpoint_strings "$LAST_BODY"
    fi

    local manifest_url
    manifest_url="https://www.dia.es/_next/static/${build_id}/_buildManifest.js"

    fetch_page \
      "dia-build-manifest" \
      "$manifest_url" \
      "www.dia.es" \
      1048576

    if [ "${LAST_RC:-1}" = "0" ]; then
      printf 'DIA build manifest relevant strings:\n'
      scan_text \
        "$LAST_BODY" \
        buscador-tiendas tiendas store guardamar 36111
      scan_endpoint_strings "$LAST_BODY"
    fi
  fi
}

section "1. Safety / environment"

printf 'Madrid: '
TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z'
printf 'Device: '
uname -a
printf 'Bash: %s\n' "${BASH_VERSION:-unknown}"
printf 'Python: '
python --version
python - <<'PY'
import ssl
print("OpenSSL:", ssl.OPENSSL_VERSION)
print("verify paths:", ssl.get_default_verify_paths())
PY
printf 'Report: %s\n' "$REPORT"

PRODUCTION_HEAD=""
PRODUCTION_BRANCH=""

if [ -d "$ROOT/.git" ]; then
  PRODUCTION_HEAD="$(git -C "$ROOT" rev-parse HEAD)"
  PRODUCTION_BRANCH="$(git -C "$ROOT" branch --show-current)"
  printf 'Repo: %s\n' "$ROOT"
  printf 'Branch: %s\n' "$PRODUCTION_BRANCH"
  printf 'HEAD: %s\n' "$PRODUCTION_HEAD"
  printf 'Git status before:\n'
  git -C "$ROOT" status --short || true
else
  printf 'Repo not found at %s; network probe can still continue.\n' "$ROOT"
fi

section "2. Reuse reviewed Guardamar holiday calendar"

if [ -f "$ROOT/src/telegrambot/holidays.py" ]; then
  (
    cd "$ROOT" || exit 1
    PYTHONPATH=src python - <<'PY'
from datetime import date
from telegrambot.holidays import official_holidays_on

for day in (
    date(2026, 10, 7),
    date(2026, 10, 8),
    date(2026, 10, 9),
    date(2026, 10, 12),
):
    values = official_holidays_on(day)
    print(
        day.isoformat(),
        [f"{item.name} ({item.scope})" for item in values],
    )
PY
  )
else
  printf 'holidays.py unavailable; skipping local calendar verification.\n'
fi

section "3. Mercadona Guardamar official locator"

fetch_page \
  "mercadona-guardamar" \
  'https://info.mercadona.es/es/supermercados?s=03140' \
  'info.mercadona.es' \
  2097152

MERC_BODY="$LAST_BODY"
MERC_OK="$LAST_RC"

if [ "${MERC_OK:-1}" = "0" ]; then
  printf 'Mercadona identity/schedule marker scan:\n'
  scan_text \
    "$MERC_BODY" \
    guardamar 03140 mediterrani mediterraneo horario opening hours \
    schedule supermercado api

  printf 'Mercadona endpoint-like strings in main response:\n'
  scan_endpoint_strings "$MERC_BODY"

  inspect_scripts \
    "mercadona" \
    "$MERC_BODY" \
    'https://info.mercadona.es/es/supermercados?s=03140' \
    'info.mercadona.es'
else
  printf 'Mercadona locator unavailable; no asset inspection attempted.\n'
fi

section "4. masymas Guardamar official locator"

fetch_page \
  "masymas-locator" \
  'https://www.masymas.com/localizadordetiendas/localizador.php' \
  'www.masymas.com' \
  1572864

MASYMAS_BODY="$LAST_BODY"

if [ "${LAST_RC:-1}" = "0" ]; then
  printf 'masymas identity/schedule marker scan:\n'
  scan_text \
    "$MASYMAS_BODY" \
    guardamar 03140 puerto localizador propiedadestienda horario ajax json api

  printf 'masymas endpoint-like strings in main response:\n'
  scan_endpoint_strings "$MASYMAS_BODY"

  printf 'masymas locator forms/selects:\n'
  inspect_forms \
    "$MASYMAS_BODY" \
    'https://www.masymas.com/localizadordetiendas/localizador.php'

  inspect_scripts \
    "masymas" \
    "$MASYMAS_BODY" \
    'https://www.masymas.com/localizadordetiendas/localizador.php' \
    'www.masymas.com'
else
  printf 'masymas locator unavailable; no asset inspection attempted.\n'
fi

section "5. DIA Guardamar official store 36111"

fetch_page \
  "dia-store-36111" \
  'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111' \
  'www.dia.es' \
  2097152

DIA_BODY="$LAST_BODY"

if [ "${LAST_RC:-1}" = "0" ]; then
  printf 'DIA identity/schedule marker scan:\n'
  scan_text \
    "$DIA_BODY" \
    36111 guardamar redonda horario opening hours schedule \
    __NEXT_DATA__ api tienda store

  printf 'DIA endpoint-like strings in main response:\n'
  scan_endpoint_strings "$DIA_BODY"

  printf 'DIA embedded Next.js inspection:\n'
  inspect_dia_next_data "$DIA_BODY"

  inspect_scripts \
    "dia" \
    "$DIA_BODY" \
    'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111' \
    'www.dia.es'
else
  printf 'DIA store page unavailable; no asset inspection attempted.\n'
fi

section "6. Read-only integrity check"

INTEGRITY_FAIL=0

if [ -d "$ROOT/.git" ]; then
  HEAD_AFTER="$(git -C "$ROOT" rev-parse HEAD)"
  BRANCH_AFTER="$(git -C "$ROOT" branch --show-current)"

  printf 'Branch before: %s\n' "$PRODUCTION_BRANCH"
  printf 'Branch after:  %s\n' "$BRANCH_AFTER"
  printf 'HEAD before:   %s\n' "$PRODUCTION_HEAD"
  printf 'HEAD after:    %s\n' "$HEAD_AFTER"
  printf 'Git status after:\n'
  git -C "$ROOT" status --short || true

  if [ "$HEAD_AFTER" != "$PRODUCTION_HEAD" ]; then
    printf 'ERROR: production HEAD changed during read-only probe.\n'
    INTEGRITY_FAIL=1
  fi

  if [ "$BRANCH_AFTER" != "$PRODUCTION_BRANCH" ]; then
    printf 'ERROR: production branch changed during read-only probe.\n'
    INTEGRITY_FAIL=1
  fi
fi

printf '\nProbe complete.\n'
printf 'Report saved outside project state: %s\n' "$REPORT"
printf 'Please send the complete report output back for endpoint analysis.\n'

exit "$INTEGRITY_FAIL"
