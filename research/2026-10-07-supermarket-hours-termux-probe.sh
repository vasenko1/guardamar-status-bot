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
import hashlib, pathlib, sys
p = pathlib.Path(sys.argv[1])
h = hashlib.sha256()
with p.open("rb") as f:
    for block in iter(lambda: f.read(131072), b""):
        h.update(block)
print(h.hexdigest())
PY
}

scan_text() {
  local file="$1"
  shift
  python - "$file" "$@" <<'PY'
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
keywords = [x.casefold() for x in sys.argv[2:]]
try:
    text = path.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    print(f"scan error: {exc}")
    raise SystemExit(0)

flat = re.sub(r"\s+", " ", text)
fold = flat.casefold()
seen = set()
shown = 0
for keyword in keywords:
    start = 0
    while shown < 80:
        idx = fold.find(keyword, start)
        if idx < 0:
            break
        lo = max(0, idx - 180)
        hi = min(len(flat), idx + len(keyword) + 260)
        snippet = flat[lo:hi].strip()
        key = snippet.casefold()
        if key not in seen:
            seen.add(key)
            print(f"[{keyword}] {snippet}")
            shown += 1
        start = idx + max(1, len(keyword))
if shown == 0:
    print("(no requested markers found)")
PY
}

scan_endpoint_strings() {
  local file="$1"
  python - "$file" <<'PY'
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
try:
    text = path.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    print(f"scan error: {exc}")
    raise SystemExit(0)

needles = (
    "api", "store", "stores", "tienda", "tiendas", "supermerc",
    "horario", "opening", "hours", "schedule", "locator", "localizador",
)
patterns = [
    re.compile(r'''["']([^"'\\]{3,500})["']'''),
    re.compile(r'''https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{4,500}'''),
]
seen = set()
for pattern in patterns:
    for match in pattern.finditer(text):
        value = match.group(1) if match.lastindex else match.group(0)
        folded = value.casefold()
        if not any(n in folded for n in needles):
            continue
        value = re.sub(r"\s+", " ", value).strip()
        if value in seen:
            continue
        seen.add(value)
        print(value[:700])
        if len(seen) >= 120:
            raise SystemExit
if not seen:
    print("(no endpoint-like strings found)")
PY
}

extract_same_host_scripts() {
  local html_file="$1"
  local base_url="$2"
  local output_file="$3"
  python - "$html_file" "$base_url" "$output_file" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import sys

html_path, base_url, output_path = sys.argv[1:4]
base = urlsplit(base_url)
urls = []

class Parser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "script":
            return
        values = {str(k).casefold(): v for k, v in attrs if v is not None}
        src = values.get("src")
        if not src:
            return
        absolute = urljoin(base_url, src)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or parsed.hostname != base.hostname:
            return
        if absolute not in urls:
            urls.append(absolute)

try:
    Parser().feed(Path(html_path).read_text(encoding="utf-8", errors="replace"))
except Exception as exc:
    print(f"script extraction error: {exc}", file=sys.stderr)

Path(output_path).write_text("\n".join(urls[:12]) + ("\n" if urls else ""), encoding="utf-8")
for url in urls[:12]:
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

path, base = sys.argv[1:3]

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.select = None

    def handle_starttag(self, tag, attrs):
        values = {str(k).casefold(): v for k, v in attrs if v is not None}
        t = tag.casefold()
        if t == "form":
            action = values.get("action", "")
            method = values.get("method", "GET")
            print("FORM", method.upper(), urljoin(base, action))
        elif t == "input":
            print("INPUT", values.get("name"), values.get("type"), values.get("value"))
        elif t == "select":
            self.select = values.get("name")
            print("SELECT", self.select)
        elif t == "option" and self.select:
            print("OPTION", self.select, values.get("value"))

    def handle_endtag(self, tag):
        if tag.casefold() == "select":
            self.select = None

try:
    Parser().feed(Path(path).read_text(encoding="utf-8", errors="replace"))
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
  curl \
    --proto '=https' \
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
  printf 'curl_rc: %s\nhttp: %s\ncontent_type: %s\nsize: %s\neffective_url: %s\n' \
    "$rc" "${LAST_HTTP:-}" "${LAST_TYPE:-}" "${LAST_SIZE:-}" "${LAST_EFFECTIVE:-}"
  if [ -s "$LAST_BODY" ]; then
    printf 'sha256: %s\n' "$(sha256_file "$LAST_BODY")"
  else
    printf 'sha256: (empty body)\n'
  fi
  printf 'response headers (selected):\n'
  grep -iE '^(HTTP/|content-type:|content-length:|location:|cache-control:|etag:|last-modified:|server:|x-|cf-)' \
    "$LAST_HEADERS" | tail -n 40 || true
  return 0
}

inspect_scripts() {
  local label="$1"
  local html_file="$2"
  local base_url="$3"
  local list="${WORK}/${label}.scripts"
  printf '\nReferenced same-host scripts:\n'
  extract_same_host_scripts "$html_file" "$base_url" "$list"
  if [ ! -s "$list" ]; then
    printf '(none)\n'
    return 0
  fi

  local count=0
  while IFS= read -r url; do
    [ -n "$url" ] || continue
    count=$((count + 1))
    [ "$count" -le 6 ] || break
    local asset="${WORK}/${label}.asset.${count}.js"
    printf '\nJS[%s]: %s\n' "$count" "$url"
    curl \
      --proto '=https' \
      --tlsv1.2 \
      --connect-timeout 10 \
      --max-time 20 \
      --retry 0 \
      --compressed \
      --silent \
      --show-error \
      --range 0-524287 \
      --max-filesize 1048576 \
      -H 'User-Agent: Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36' \
      -H 'Accept: application/javascript,text/javascript' \
      -o "$asset" \
      "$url"
    local rc=$?
    printf 'asset_rc: %s size: %s\n' "$rc" "$(wc -c < "$asset" 2>/dev/null || printf 0)"
    if [ -s "$asset" ]; then
      scan_endpoint_strings "$asset"
    fi
  done < "$list"
}

inspect_dia_next_data() {
  local html_file="$1"
  local build_file="${WORK}/dia-build-id.txt"
  : > "$build_file"
  python - "$html_file" "$build_file" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import json, sys

html_path, build_path = sys.argv[1:3]

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "script":
            return
        values = {str(k).casefold(): v for k, v in attrs if v is not None}
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
    print("__NEXT_DATA__: absent")
    raise SystemExit(0)

try:
    payload = json.loads(raw)
except json.JSONDecodeError as exc:
    print("__NEXT_DATA__: invalid JSON:", exc)
    raise SystemExit(0)

print("__NEXT_DATA__: present")
build_id = payload.get("buildId")
if isinstance(build_id, str):
    Path(build_path).write_text(build_id, encoding="utf-8")
    print("buildId:", build_id)

needles = ("36111", "guardamar", "redonda", "hour", "opening", "schedule", "horario", "store")
seen = set()

def walk(value, path="$"):
    if len(seen) >= 120:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            candidate = f"{path}.{key_text}"
            if any(n in key_text.casefold() for n in needles):
                out = f"{candidate} = {child!r}"[:900]
                if out not in seen:
                    seen.add(out)
                    print(out)
            walk(child, candidate)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:500]):
            walk(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        folded = value.casefold()
        if any(n in folded for n in needles):
            out = f"{path} = {value!r}"[:900]
            if out not in seen:
                seen.add(out)
                print(out)

walk(payload)
PY

  if [ -s "$build_file" ]; then
    local build_id
    build_id="$(cat "$build_file")"
    local data_url="https://www.dia.es/_next/data/${build_id}/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111.json"
    fetch_page "dia-next-data" "$data_url" 'application/json,text/plain' 1048576
    printf 'DIA _next/data marker scan:\n'
    scan_text "$LAST_BODY" 36111 guardamar redonda horario opening hours schedule store
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

if [ -d "$ROOT/.git" ]; then
  printf 'Repo: %s\n' "$ROOT"
  printf 'Branch: '
  git -C "$ROOT" branch --show-current || true
  printf 'HEAD: '
  git -C "$ROOT" rev-parse HEAD || true
  printf 'Git status before:\n'
  git -C "$ROOT" status --short || true
else
  printf 'Repo not found at %s (network probe can still continue).\n' "$ROOT"
fi

section "2. Mercadona official locator"
fetch_page \
  "mercadona-03140" \
  'https://info.mercadona.es/es/supermercados?s=03140' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152
MERC_G_BODY="$LAST_BODY"
MERC_G_HTTP="$LAST_HTTP"
printf 'Guardamar marker scan:\n'
scan_text "$MERC_G_BODY" guardamar 03140 mediterrani mediterraneo horario opening hours schedule supermercado api

fetch_page \
  "mercadona-03177" \
  'https://info.mercadona.es/es/supermercados?s=03177' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152
MERC_S_BODY="$LAST_BODY"
MERC_S_HTTP="$LAST_HTTP"
printf 'San Fulgencio marker scan:\n'
scan_text "$MERC_S_BODY" 'san fulgencio' 03177 'mar adriatico' horario opening hours schedule supermercado api

if [ "${MERC_G_HTTP:-}" = "200" ]; then
  inspect_scripts "mercadona" "$MERC_G_BODY" 'https://info.mercadona.es/es/supermercados?s=03140'
elif [ "${MERC_S_HTTP:-}" = "200" ]; then
  inspect_scripts "mercadona" "$MERC_S_BODY" 'https://info.mercadona.es/es/supermercados?s=03177'
else
  printf '\nMercadona locator did not return HTTP 200; no JS crawling attempted.\n'
fi

section "3. masymas official locator"
fetch_page \
  "masymas-locator" \
  'https://www.masymas.com/localizadordetiendas/localizador.php' \
  'text/html,application/xhtml+xml' \
  1572864
MASYMAS_BODY="$LAST_BODY"
printf 'Locator marker scan:\n'
scan_text "$MASYMAS_BODY" guardamar 03140 puerto localizador propiedadestienda horario ajax json api
printf '\nLocator forms/selects:\n'
inspect_forms "$MASYMAS_BODY" 'https://www.masymas.com/localizadordetiendas/localizador.php'
inspect_scripts "masymas" "$MASYMAS_BODY" 'https://www.masymas.com/localizadordetiendas/localizador.php'

printf '\nKnown official per-store endpoint control (Id=13; NOT Guardamar):\n'
fetch_page \
  "masymas-control-id13" \
  'https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id=13' \
  'text/html,application/xhtml+xml' \
  524288
scan_text "$LAST_BODY" alcora horario coordenadas telefono propiedadestienda

section "4. DIA official store 36111"
fetch_page \
  "dia-store-36111" \
  'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111' \
  'text/html,application/xhtml+xml,application/json;q=0.9' \
  2097152
DIA_BODY="$LAST_BODY"
printf 'DIA marker scan:\n'
scan_text "$DIA_BODY" 36111 guardamar redonda horario opening hours schedule __NEXT_DATA__ api tienda store
printf '\nDIA Next.js embedded-data inspection:\n'
inspect_dia_next_data "$DIA_BODY"
inspect_scripts "dia" "$DIA_BODY" 'https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111'

section "5. Official calendar controls"
fetch_page \
  "alicante-local-holidays" \
  'https://documentacion.diputacionalicante.es/fiestas.asp' \
  'text/html,application/xhtml+xml' \
  1048576
printf 'Local-holiday marker scan:\n'
scan_text "$LAST_BODY" guardamar 'san fulgencio' '7 de octubre' '8 de octubre' 2026

fetch_page \
  "gva-commercial-2026" \
  'https://www.gva.es/es/inicio/procedimientos?id_proc=G107327' \
  'text/html,application/xhtml+xml' \
  1572864
printf 'GVA commercial-calendar marker scan:\n'
scan_text "$LAST_BODY" 2026 domingos festivos apertura comercial calendario

section "6. Read-only integrity check"
if [ -d "$ROOT/.git" ]; then
  printf 'HEAD after: '
  git -C "$ROOT" rev-parse HEAD || true
  printf 'Git status after:\n'
  git -C "$ROOT" status --short || true
fi

printf '\nProbe complete.\n'
printf 'Report saved outside project state: %s\n' "$REPORT"
printf 'Please send the complete report output back for endpoint analysis.\n'
