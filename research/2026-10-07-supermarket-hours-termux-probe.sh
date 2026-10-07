#!/data/data/com.termux/files/usr/bin/bash
set -u
set -o pipefail
export LC_ALL=C

ROOT="${HOME}/bots/guardamar-status"
CACHE_BASE="${HOME}/.cache/guardamar-supermarket-hours-probe"
STAMP="$(date '+%Y%m%d-%H%M%S')"

for command_name in curl python mktemp tee grep wc tr; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'ERROR: required command is missing: %s\n' "$command_name" >&2
    exit 1
  fi
done

mkdir -p "$CACHE_BASE" || exit 1
WORK="$(mktemp -d "${CACHE_BASE}/run.XXXXXX")" || exit 1
REPORT="${CACHE_BASE}/report-${STAMP}.txt"

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

exec > >(tee "$REPORT") 2>&1

NETWORK_REQUESTS=0
TOTAL_BODY_BYTES=0

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
with path.open("rb") as source:
    for block in iter(lambda: source.read(131072), b""):
        digest.update(block)
print(digest.hexdigest())
PY
}

add_bytes() {
  local value="${1:-}"
  case "$value" in
    ''|*[!0-9]*) return 0 ;;
  esac
  TOTAL_BODY_BYTES=$((TOTAL_BODY_BYTES + value))
}

report_host_change() {
  local requested="$1"
  local effective="$2"
  python - "$requested" "$effective" <<'PY'
from urllib.parse import urlsplit
import sys

requested, effective = sys.argv[1:3]
a = (urlsplit(requested).hostname or "").casefold()
b = (urlsplit(effective).hostname or "").casefold()
print("requested_host:", a or "(none)")
print("effective_host:", b or "(none)")
if a != b:
    print("HOST-CHANGE: yes — production adapter must explicitly review/allow this host")
else:
    print("HOST-CHANGE: no")
PY
}

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
    while shown < 100:
        index = folded.find(keyword, start)
        if index < 0:
            break
        low = max(0, index - 180)
        high = min(len(flat), index + len(keyword) + 300)
        snippet = flat[low:high].strip()
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

text = (
    text
    .replace(r"\/", "/")
    .replace(r"\u002F", "/")
    .replace(r"\u002f", "/")
)

needles = (
    "api", "graphql", "store", "stores", "shop", "tienda", "tiendas",
    "supermerc", "horario", "opening", "hours", "schedule", "calendar",
    "holiday", "special", "closed", "closure", "festiv", "apertura",
    "cerrad", "domingo", "locator", "localizador", "location", "pointofsale",
)

patterns = (
    re.compile(r'''["']([^"'\\\n]{3,700})["']'''),
    re.compile(r'''https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{4,700}'''),
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
    print("(no endpoint/schedule-like strings found)")
PY
}

extract_script_inventory() {
  local html_file="$1"
  local base_url="$2"
  local first_party_root="$3"
  local first_party_file="$4"
  local external_file="$5"

  python - "$html_file" "$base_url" "$first_party_root" "$first_party_file" "$external_file" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import sys

html_path, base_url, root, first_path, external_path = sys.argv[1:6]
root = root.casefold().lstrip(".")
items = []

class Parser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "script":
            return
        values = {str(key).casefold(): value for key, value in attrs if value is not None}
        src = values.get("src")
        if not src:
            return
        absolute = urljoin(base_url, src)
        if absolute not in items:
            items.append(absolute)

try:
    Parser().feed(Path(html_path).read_text(encoding="utf-8", errors="replace"))
except Exception as exc:
    print(f"script extraction error: {exc}", file=sys.stderr)

def first_party(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    return (
        parsed.scheme == "https"
        and (host == root or host.endswith("." + root))
        and parsed.username is None
        and parsed.password is None
    )

def score(url):
    value = url.casefold()
    score_value = 0
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
            score_value += points
    return score_value

first = [(index, url) for index, url in enumerate(items) if first_party(url)]
external = [url for url in items if not first_party(url)]
first.sort(key=lambda item: (-score(item[1]), item[0]))

Path(first_path).write_text(
    "\n".join(url for _, url in first) + ("\n" if first else ""),
    encoding="utf-8",
)
Path(external_path).write_text(
    "\n".join(external) + ("\n" if external else ""),
    encoding="utf-8",
)

print(f"script_count_total={len(items)}")
print(f"script_count_first_party={len(first)}")
print(f"script_count_external={len(external)}")
print("first-party scripts, prioritized:")
for _, url in first[:20]:
    print(url)
if external:
    print("external scripts (listed only; not fetched):")
    for url in external[:20]:
        print(url)
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

path, base_url = sys.argv[1:3]

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.select = None
        self.count = 0
        self.limit = 100

    def emit(self, *parts):
        if self.count >= self.limit:
            return
        print(*parts)
        self.count += 1

    def handle_starttag(self, tag, attrs):
        values = {str(key).casefold(): value for key, value in attrs if value is not None}
        tag = tag.casefold()
        if tag == "form":
            action = values.get("action", "")
            method = values.get("method", "GET")
            self.emit("FORM", method.upper(), urljoin(base_url, action))
        elif tag == "input":
            self.emit("INPUT", values.get("name"), values.get("type"), values.get("value"))
        elif tag == "select":
            self.select = values.get("name")
            self.emit("SELECT", self.select)
        elif tag == "option" and self.select:
            self.emit("OPTION", self.select, values.get("value"))

    def handle_endtag(self, tag):
        if tag.casefold() == "select":
            self.select = None

try:
    parser = Parser()
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    if parser.count >= parser.limit:
        print("(form output capped at 100 records)")
except Exception as exc:
    print("form parse error:", exc)
PY
}

LAST_BODY=""
LAST_HEADERS=""
LAST_META=""
LAST_HTTP=""
LAST_EFFECTIVE=""
LAST_TYPE=""
LAST_SIZE=""

fetch_page() {
  local label="$1"
  local url="$2"
  local accept="$3"
  local limit="$4"

  LAST_BODY="${WORK}/${label}.body"
  LAST_HEADERS="${WORK}/${label}.headers"
  LAST_META="${WORK}/${label}.meta"
  : > "$LAST_BODY"
  : > "$LAST_HEADERS"
  : > "$LAST_META"

  printf '\n--- %s ---\nURL: %s\n' "$label" "$url"
  NETWORK_REQUESTS=$((NETWORK_REQUESTS + 1))

  curl \
    --proto '=https' \
    --proto-redir '=https' \
    --tlsv1.2 \
    --location \
    --max-redirs 3 \
    --connect-timeout 10 \
    --max-time 25 \
    --retry 0 \
    --compressed \
    --silent \
    --show-error \
    --max-filesize "$limit" \
    -H 'User-Agent: Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36' \
    -H 'Accept-Language: es-ES,es;q=0.9,en;q=0.5' \
    -H "Accept: ${accept}" \
    -D "$LAST_HEADERS" \
    -o "$LAST_BODY" \
    -w '%{http_code}\t%{url_effective}\t%{content_type}\t%{size_download}\n' \
    "$url" > "$LAST_META"
  local rc=$?

  IFS=$'\t' read -r LAST_HTTP LAST_EFFECTIVE LAST_TYPE LAST_SIZE < "$LAST_META" || true

  printf 'curl_rc: %s\nhttp: %s\ncontent_type: %s\nsize_download: %s\neffective_url: %s\n' \
    "$rc" "${LAST_HTTP:-}" "${LAST_TYPE:-}" "${LAST_SIZE:-}" "${LAST_EFFECTIVE:-}"

  if [ -n "${LAST_EFFECTIVE:-}" ]; then
    report_host_change "$url" "$LAST_EFFECTIVE"
  fi

  local body_size=0
  if [ -s "$LAST_BODY" ]; then
    body_size="$(wc -c < "$LAST_BODY" | tr -d ' ')"
    printf 'body_bytes: %s\n' "$body_size"
    printf 'sha256: %s\n' "$(sha256_file "$LAST_BODY")"
    add_bytes "$body_size"
  else
    printf 'body_bytes: 0\nsha256: (empty body)\n'
  fi

  printf 'response headers (selected):\n'
  grep -iE '^(HTTP/|content-type:|content-length:|location:|cache-control:|etag:|last-modified:|server:|x-|cf-)' \
    "$LAST_HEADERS" | tail -n 50 || true

  return 0
}

inspect_scripts() {
  local label="$1"
  local html_file="$2"
  local base_url="$3"
  local first_party_root="$4"

  local first_party="${WORK}/${label}.scripts.first-party"
  local external="${WORK}/${label}.scripts.external"

  printf '\nScript inventory:\n'
  extract_script_inventory \
    "$html_file" \
    "$base_url" \
    "$first_party_root" \
    "$first_party" \
    "$external"

  if [ ! -s "$first_party" ]; then
    printf '(no fetchable first-party scripts)\n'
    return 0
  fi

  local count=0
  while IFS= read -r url; do
    [ -n "$url" ] || continue
    count=$((count + 1))
    [ "$count" -le 8 ] || break

    local asset="${WORK}/${label}.asset.${count}.js"
    local meta="${WORK}/${label}.asset.${count}.meta"

    printf '\nJS[%s]: %s\n' "$count" "$url"
    NETWORK_REQUESTS=$((NETWORK_REQUESTS + 1))

    curl \
      --proto '=https' \
      --proto-redir '=https' \
      --tlsv1.2 \
      --location \
      --max-redirs 2 \
      --connect-timeout 10 \
      --max-time 20 \
      --retry 0 \
      --compressed \
      --silent \
      --show-error \
      --range 0-524287 \
      --max-filesize 600000 \
      -H 'User-Agent: Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36' \
      -H 'Accept: application/javascript,text/javascript' \
      -o "$asset" \
      -w '%{http_code}\t%{url_effective}\t%{content_type}\t%{size_download}\n' \
      "$url" > "$meta"
    local rc=$?

    local status=""
    local effective=""
    local content_type=""
    local size_download=""
    IFS=$'\t' read -r status effective content_type size_download < "$meta" || true

    local body_size=0
    if [ -s "$asset" ]; then
      body_size="$(wc -c < "$asset" | tr -d ' ')"
      add_bytes "$body_size"
    fi

    printf 'asset_rc: %s http: %s type: %s body_bytes: %s\n' \
      "$rc" "${status:-}" "${content_type:-}" "$body_size"

    if [ -n "${effective:-}" ]; then
      report_host_change "$url" "$effective"
    fi

    if [ -s "$asset" ]; then
      scan_endpoint_strings "$asset"
    fi
  done < "$first_party"
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
        values = {str(key).casefold(): value for key, value in attrs if value is not None}
        if values.get("id") == "__NEXT_DATA__":
            self.capture = True

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self.capture:
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

parser = Parser()
parser.feed(Path(html_path).read_text(encoding="utf-8", errors="replace"))
raw = "".join(parser.parts).strip()

if not raw:
    print("__NEXT_DATA__: absent (app-router or another contract may still be present)")
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

needles = (
    "36111", "guardamar", "redonda", "hour", "opening", "schedule",
    "horario", "store", "special", "holiday", "closed", "festiv",
)
seen = set()

def walk(value, path="$"):
    if len(seen) >= 160:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if any(needle in key_text.casefold() for needle in needles):
                out = f"{child_path} = {child!r}"[:1000]
                if out not in seen:
                    seen.add(out)
                    print(out)
            walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value[:800]):
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
    local data_url="https://www.dia.es/_next/data/${build_id}/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111.json"

    fetch_page \
      "dia-next-data" \
      "$data_url" \
      'application/json,text/plain' \
      1048576

    printf 'DIA _next/data marker scan:\n'
    scan_text \
      "$LAST_BODY" \
      36111 guardamar redonda horario opening hours schedule special holiday closed festivo
  fi
}

section "1. Safety / environment"
printf 'Madrid: '
TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z'
printf 'Device: '
uname -a
printf 'Bash: %s\n' "${BASH_VERSION:-unknown}"
printf 'curl: '
curl --version | head -n 1
printf 'Python: '
python --version

python - <<'PY'
import ssl
print("OpenSSL:", ssl.OPENSSL_VERSION)
print("verify paths:", ssl.get_default_verify_paths())
PY

printf 'Report: %s\n' "$REPORT"

BEFORE_BRANCH=""
BEFORE_HEAD=""
BEFORE_STATUS=""

if [ -d "$ROOT/.git" ] && command -v git >/dev/null 2>&1; then
  BEFORE_BRANCH="$(git -C "$ROOT" branch --show-current || true)"
  BEFORE_HEAD="$(git -C "$ROOT" rev-parse HEAD || true)"
  BEFORE_STATUS="$(git -C "$ROOT" status --porcelain=v1 || true)"

  printf 'Repo: %s\n' "$ROOT"
  printf 'Branch: %s\n' "$BEFORE_BRANCH"
  printf 'HEAD: %s\n' "$BEFORE_HEAD"
  printf 'Git status before:\n%s\n' "${BEFORE_STATUS:-"(clean)"}"
else
  printf 'Repo not available at %s; network probe can still continue.\n' "$ROOT"
fi

section "2. Existing local Guardamar holiday calendar — zero network"
if [ -f "$ROOT/src/telegrambot/holidays.py" ]; then
  PYTHONPATH="$ROOT/src" python - <<'PY'
from datetime import date
from telegrambot.holidays import official_holidays_on

for value in (
    date(2026, 10, 7),
    date(2026, 10, 9),
    date(2026, 10, 12),
    date(2026, 12, 8),
    date(2026, 12, 25),
):
    holidays = official_holidays_on(value)
    print(value.isoformat(), [(item.name, item.kind) for item in holidays])
PY
else
  printf 'holidays.py not found; skip local-calendar check.\n'
fi

section "3. Mercadona official locator — Guardamar only"

fetch_page \
  "mercadona-base" \
  'https://info.mercadona.es/es/supermercados' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152

MERC_BASE_BODY="$LAST_BODY"
MERC_BASE_HTTP="$LAST_HTTP"

printf '\nBase HTML schedule/endpoint scan:\n'
scan_text \
  "$MERC_BASE_BODY" \
  guardamar 03140 mediterrani mediterraneo horario opening hours schedule special holiday closed festivo api supermercado
printf '\nBase HTML endpoint-like strings:\n'
scan_endpoint_strings "$MERC_BASE_BODY"
printf '\nBase forms:\n'
inspect_forms "$MERC_BASE_BODY" 'https://info.mercadona.es/es/supermercados'

if [ "${MERC_BASE_HTTP:-}" = "200" ]; then
  inspect_scripts \
    "mercadona" \
    "$MERC_BASE_BODY" \
    'https://info.mercadona.es/es/supermercados' \
    'mercadona.es'
else
  printf '\nMercadona base locator is not HTTP 200; JS discovery skipped.\n'
fi

printf '\nExploratory postal-code URL. This query syntax is NOT assumed to be a production contract.\n'
fetch_page \
  "mercadona-03140-exploratory" \
  'https://info.mercadona.es/es/supermercados?s=03140' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152

printf 'Guardamar exploratory marker scan:\n'
scan_text \
  "$LAST_BODY" \
  guardamar 03140 mediterrani mediterraneo horario opening hours schedule special holiday closed festivo supermercado

section "4. masymas official locator"

fetch_page \
  "masymas-locator" \
  'https://www.masymas.com/localizadordetiendas/localizador.php' \
  'text/html,application/xhtml+xml' \
  1572864

MASYMAS_BODY="$LAST_BODY"

printf '\nLocator marker scan:\n'
scan_text \
  "$MASYMAS_BODY" \
  guardamar 03140 puerto localizador propiedadestienda horario festivo especial cerrado ajax json api
printf '\nLocator endpoint-like strings:\n'
scan_endpoint_strings "$MASYMAS_BODY"
printf '\nLocator forms/selects:\n'
inspect_forms "$MASYMAS_BODY" 'https://www.masymas.com/localizadordetiendas/localizador.php'

inspect_scripts \
  "masymas" \
  "$MASYMAS_BODY" \
  'https://www.masymas.com/localizadordetiendas/localizador.php' \
  'masymas.com'

printf '\nKnown official per-store endpoint control (Id=13; Alcora, NOT Guardamar):\n'
fetch_page \
  "masymas-control-id13" \
  'https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=13' \
  'text/html,application/xhtml+xml' \
  524288

scan_text \
  "$LAST_BODY" \
  alcora horario festivo especial cerrado apertura domingo coordenadas telefono propiedadestienda

section "5. DIA official Guardamar store 36111"

fetch_page \
  "dia-store-36111" \
  'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152

DIA_BODY="$LAST_BODY"

printf '\nDIA HTML marker scan:\n'
scan_text \
  "$DIA_BODY" \
  36111 guardamar redonda horario opening hours schedule special holiday closed festivo __NEXT_DATA__ api tienda store
printf '\nDIA HTML endpoint-like strings:\n'
scan_endpoint_strings "$DIA_BODY"
printf '\nDIA Next.js embedded-data inspection:\n'
inspect_dia_next_data "$DIA_BODY"

inspect_scripts \
  "dia" \
  "$DIA_BODY" \
  'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111' \
  'dia.es'

section "6. Probe cost and integrity"

printf 'Approximate network request count: %s\n' "$NETWORK_REQUESTS"
printf 'Stored response/body bytes inspected: %s\n' "$TOTAL_BODY_BYTES"
printf 'Note: stored body bytes are an upper-bound diagnostic, not exact on-wire compressed traffic.\n'

if [ -d "$ROOT/.git" ] && command -v git >/dev/null 2>&1; then
  AFTER_BRANCH="$(git -C "$ROOT" branch --show-current || true)"
  AFTER_HEAD="$(git -C "$ROOT" rev-parse HEAD || true)"
  AFTER_STATUS="$(git -C "$ROOT" status --porcelain=v1 || true)"

  printf '\nBranch before: %s\nBranch after:  %s\n' "$BEFORE_BRANCH" "$AFTER_BRANCH"
  printf 'HEAD before:   %s\nHEAD after:    %s\n' "$BEFORE_HEAD" "$AFTER_HEAD"
  printf 'Git status after:\n%s\n' "${AFTER_STATUS:-"(clean)"}"

  if [ "$AFTER_BRANCH" != "$BEFORE_BRANCH" ]; then
    printf 'INTEGRITY-FAIL: branch changed during read-only probe.\n'
    exit 2
  fi
  if [ "$AFTER_HEAD" != "$BEFORE_HEAD" ]; then
    printf 'INTEGRITY-FAIL: HEAD changed during read-only probe.\n'
    exit 2
  fi
  if [ "$AFTER_STATUS" != "$BEFORE_STATUS" ]; then
    printf 'INTEGRITY-FAIL: worktree status changed during read-only probe.\n'
    exit 2
  fi
fi

printf '\nProbe complete.\n'
printf 'Report saved outside project state: %s\n' "$REPORT"
printf 'Please send the complete report output back for endpoint analysis.\n'
