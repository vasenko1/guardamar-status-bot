#!/data/data/com.termux/files/usr/bin/bash
set -u
set -o pipefail
export LC_ALL=C
ROOT="\${HOME}/bots/guardamar-status"
CACHE="\${HOME}/.cache/guardamar-supermarket-hours-exact"
STAMP="$(date '+%Y%m%d-%H%M%S')"
PY="\${CACHE}/probe-\${STAMP}.py"
REPORT="\${CACHE}/report-\${STAMP}.txt"
mkdir -p "$CACHE"
trap 'rm -f "$PY"' EXIT INT TERM
exec > >(tee "$REPORT") 2>&1

HEAD0="$(git -C "$ROOT" rev-parse HEAD)" || exit 1
BRANCH0="$(git -C "$ROOT" branch --show-current)" || exit 1
STATUS0="$(git -C "$ROOT" status --porcelain=v1)" || exit 1
printf 'Madrid: '; TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z'
printf 'Branch: %s\nHEAD: %s\nStatus before:\n%s\n' "$BRANCH0" "$HEAD0" "$STATUS0"

cat > "$PY" <<'PY'
from __future__ import annotations
import gzip, html, io, json, re, ssl, urllib.parse
from telegrambot._transport import BoundedFetchError, fetch_bounded

UA={"User-Agent":"GuardamarMorningDigest/0.14","Accept-Language":"es-ES,es;q=0.9"}
HTML=frozenset({"text/html","application/xhtml+xml"})
JS=frozenset({"application/javascript","text/javascript","text/plain","application/json","application/octet-stream"})
GZ=frozenset({"application/gzip","application/x-gzip","application/octet-stream","binary/octet-stream","application/json","text/plain"})

def allow(host, prefix=None):
    def f(url):
        try:p=urllib.parse.urlsplit(url)
        except ValueError:return False
        return p.scheme=="https" and p.hostname==host and p.port in (None,443) and p.username is None and p.password is None and (prefix is None or p.path.startswith(prefix))
    return f

def get(label,url,host,types,limit,prefix=None,method="GET",data=None,extra=None):
    h=dict(UA); h.update(extra or {})
    print(f"\n--- {label} ---\nURL: {url}\nMETHOD: {method}\nLIMIT: {limit}")
    try:
        body,final,ctype=fetch_bounded(url,is_allowed_url=allow(host,prefix),limit_bytes=limit,timeout_seconds=20,headers=h,accepted_types=types,method=method,data=data)
    except BoundedFetchError as e:
        print("FAIL",e.code,e.status); return None
    print("OK",ctype,len(body),final)
    return body

def txt(b): return b.decode("utf-8",errors="replace")
def clean(s): return re.sub(r"\s+"," ",html.unescape(s)).strip()
def window(s,needle,r=1800):
    i=s.casefold().find(needle.casefold())
    print(f"[{needle}]", clean(s[max(0,i-r):i+len(needle)+r]) if i>=0 else "NOT FOUND")
def url1(s,pat):
    m=re.search(pat,s,re.I); return html.unescape(m.group(1)).replace(r"\/","/") if m else None

def bounded_gunzip(b,limit=32*1024*1024):
    if not b.startswith(b"\x1f\x8b"): return b
    with gzip.GzipFile(fileobj=io.BytesIO(b)) as f: out=f.read(limit+1)
    if len(out)>limit: raise ValueError("gunzip too large")
    return out

print("\n=== TLS ===")
print(ssl.OPENSSL_VERSION); print(ssl.get_default_verify_paths())

print("\n=== MERCADONA ===")
loc=get("locator","https://info.mercadona.es/es/supermercados","info.mercadona.es",HTML,512*1024)
if loc:
    h=txt(loc)
    u=url1(h,r'''(https://storage\.googleapis\.com/pro-bucket-wcorp-files/json/data\.js\?[^"'\s<]+)''')
    print("data_url:",u)
    if u:
        d=get("data.js",u,"storage.googleapis.com",JS,12*1024*1024,"/pro-bucket-wcorp-files/json/data.js")
        if d:
            s=txt(d); print("guardamar_count:",s.casefold().count("guardamar"))
            for n in ("Guardamar","03140","Mediterrani","07/10/2026","2026-10-07","09/10/2026","12/10/2026"):
                window(s,n,2200)

print("\n=== MASYMAS ===")
mu="https://www.masymas.com/localizadordetiendas/localizador.php"
form={"Content-Type":"application/x-www-form-urlencoded"}
p=get("POST Alicante",mu,"www.masymas.com",HTML,1024*1024,method="POST",data=urllib.parse.urlencode({"IdProvincia":"ALICANTE"}).encode(),extra=form)
selected=None
if p:
    s=txt(p); window(s,"Guardamar",2600)
    gm=None
    for name,body in re.findall(r'''(?is)<select\b[^>]*name=["']?([^"' >]+)[^>]*>(.*?)</select>''',s):
        for attrs,label in re.findall(r'''(?is)<option\b([^>]*)>(.*?)</option>''',body):
            label=clean(re.sub(r"<[^>]+>"," ",label))
            if "guardamar" in label.casefold():
                m=re.search(r'''(?i)\bvalue\s*=\s*["']?([^"' >]+)''',attrs)
                if m: gm=(name,m.group(1)); print("Guardamar option:",gm,label)
    if gm:
        q={"IdProvincia":"ALICANTE",gm[0]:gm[1]}
        r=get("POST Guardamar",mu,"www.masymas.com",HTML,1024*1024,method="POST",data=urllib.parse.urlencode(q).encode(),extra=form)
        if r: selected=txt(r); window(selected,"Guardamar",3200)
    for source in (selected,s):
        if not source: continue
        for row in re.findall(r'''(?is)<tr\b.*?</tr>''',source):
            plain=clean(re.sub(r"<[^>]+>"," ",row))
            if "guardamar" not in plain.casefold() and "966727946" not in plain: continue
            print("ROW:",plain)
            ids=sorted(set(re.findall(r'''propiedadestienda\.php\?Id=(\d+)''',row,re.I)))
            print("DETAIL_IDS:",ids)
            for sid in ids[:2]:
                du=f"https://www.masymas.com/localizadordetiendas/propiedadestienda.php?Id={sid}"
                b=get("detail "+sid,du,"www.masymas.com",HTML,512*1024,"/localizadordetiendas/propiedadestienda.php")
                if b:
                    ds=txt(b)
                    for n in ("Guardamar","Horario","festiv","domingo","octubre","cerrad","abiert"): window(ds,n,1600)
            break
        else: continue
        break

print("\n=== DIA ===")
du="https://www.dia.es/tiendas/buscador-tiendas/alicante/guardamar-del-segura/03140/36111"
dp=get("store page",du,"www.dia.es",HTML,512*1024)
if dp:
    h=txt(dp)
    gz=url1(h,r'''(https://www\.dia\.es/clubdia/ES/tiendas\.v\d+\.json\.gz)''')
    js=url1(h,r'''src=["'](/tiendas/js/shopFinder\.js\?[^"']+)["']''')
    if js: js=urllib.parse.urljoin("https://www.dia.es",js)
    print("gzip_url:",gz); print("shopfinder_url:",js)
    if js:
        b=get("shopFinder.js",js,"www.dia.es",JS,1024*1024,"/tiendas/js/shopFinder.js")
        if b:
            s=txt(b)
            for n in ("tiendas.v","horariosTienda2","festivosTienda","horariosAperturaFestivo","fechaApertura","inicioCierreTemp","finCierreTemp"): window(s,n,2200)
    if gz:
        b=get("tiendas gzip",gz,"www.dia.es",GZ,8*1024*1024,"/clubdia/ES/tiendas.v")
        if b:
            try: data=json.loads(bounded_gunzip(b).decode("utf-8"))
            except Exception as e: print("PARSE FAIL",type(e).__name__,str(e)[:240])
            else:
                hits=[]
                def walk(x,path="$",depth=0):
                    if depth>12 or len(hits)>=12:return
                    if isinstance(x,dict):
                        vals=[v for v in x.values() if isinstance(v,(str,int,float,bool)) or v is None]
                        direct=" ".join(map(str,vals)).casefold()
                        if any(str(v)=="36111" for v in vals) or "guardamar" in direct: hits.append((path,x))
                        for k,v in x.items(): walk(v,f"{path}.{k}",depth+1)
                    elif isinstance(x,list):
                        for i,v in enumerate(x[:10000]): walk(v,f"{path}[{i}]",depth+1)
                walk(data); print("MATCHES:",len(hits))
                for path,obj in hits[:6]:
                    print("PATH:",path); print(json.dumps(obj,ensure_ascii=False,sort_keys=True)[:16000])

print("\nExact-source probe complete; no Telegram/project-state writes.")
PY

python - "$PY" <<'PY'
import ast,sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text())
print("Embedded Python syntax: OK")
PY
(
  cd "$ROOT" || exit 1
  PYTHONPATH=src python "$PY"
)
RC=$?
HEAD1="$(git -C "$ROOT" rev-parse HEAD)" || exit 1
BRANCH1="$(git -C "$ROOT" branch --show-current)" || exit 1
STATUS1="$(git -C "$ROOT" status --porcelain=v1)" || exit 1
if [ "$HEAD1" != "$HEAD0" ] || [ "$BRANCH1" != "$BRANCH0" ] || [ "$STATUS1" != "$STATUS0" ]; then
  echo "ERROR: production checkout changed"; exit 2
fi
echo "Integrity: OK"
echo "Probe exit code: $RC"
echo "Report: $REPORT"
exit "$RC"
