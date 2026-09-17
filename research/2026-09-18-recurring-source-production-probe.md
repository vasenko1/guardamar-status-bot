# Recurring activities source production probe — 2026-09-18

Status: **PENDING OPERATOR RUN ON PRODUCTION TERMUX**.

Purpose: verify transport shape from the actual Android/Termux production
network before recurring-card code is written. This probe is read-only with
respect to the project and Telegram. It creates only a temporary directory,
performs HTTP GETs, prints metadata/marker checks, then removes the temporary
files.

It does not load `.env`, does not send Telegram messages, does not modify
`state/`, and does not invoke bot code.

## Probe

```sh
set -u

TMP_ROOT="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"
WORK_DIR="$(mktemp -d "${TMP_ROOT%/}/guardamar-recurring-probe.XXXXXX")" || exit 1
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM

UA='guardamar-status-bot-source-probe/1.0'

probe() {
    name="$1"
    url="$2"
    shift 2
    body="$WORK_DIR/$name.body"

    printf '\n=== %s ===\n' "$name"

    meta="$(
        curl -sS -L --compressed             --connect-timeout 10             --max-time 30             -A "$UA"             -o "$body"             -w 'http=%{http_code}\nfinal=%{url_effective}\ncontent_type=%{content_type}\nbytes=%{size_download}\ntime=%{time_total}\n'             "$url"
    )"
    rc=$?

    printf 'curl_rc=%s\n%s' "$rc" "$meta"
    printf '\n'

    if [ "$rc" -ne 0 ]; then
        return
    fi

    for marker in "$@"; do
        if grep -Fqi -- "$marker" "$body"; then
            printf 'marker[%s]=YES\n' "$marker"
        else
            printf 'marker[%s]=NO\n' "$marker"
        fi
    done
}

probe ayto_rss   'https://www.guardamardelsegura.es/feed/'   'PROGRAMA DINAMIZACIÓN SOCIAL 2026 / 2027'

probe ayto_rest   'https://www.guardamardelsegura.es/wp-json/wp/v2/posts?per_page=10&_fields=id,date,modified,link,title'   'PROGRAMA DINAMIZACIÓN SOCIAL 2026 / 2027'

probe dinamizacion_detail   'https://www.guardamardelsegura.es/2026/09/07/programa-dinamizacion-social-2026-2027/'   'Inscripción online'

probe dinamizacion_form   'https://docs.google.com/forms/d/e/1FAIpQLSdG1kkxJhCHLSd-aZ7j55MFybZMfGHS6FytHgVrOTPo_66Oiw/viewform'   'PLAZO DE INSCRIPCIÓN'   'MOVIMIENTO CONSCIENTE'   'ESCUELA DE EMOCIONES'

probe turismo_agenda   'https://guardamarturismo.com/agenda-cultural/'   'TALLERES 2025/2026'   'Inscripciones del 21 al 25 de septiembre'

probe chess   'https://ajedrezdamadeguardamar.com/cuotas/'   'ESCUELA DE AJEDREZ'   'martes y jueves'   'INICIACIÓN'

probe tertulia   'https://www.bibliotecaspublicas.es/guardamardelsegura/actividades-programas/Tertulia-Literaria-de-Guardamar.html'   'todos los martes'   '11:00'   '13:00'

probe epa   'https://www.guardamardelsegura.es/2024/07/24/epa-escuela-de-personas-adultas-curso-2024-2025/'   'CURSO 2026 / 2027'   '2026-2027'

probe eoi_vacancies   'https://appweb1.edu.gva.es/CiudadanosWeb/public/vacadmisioneoi.do?metodo=generarInicio&tipo=EXS'   '2026-2027'   'Guardamar'
```

## Acceptance rules

- HTTP 200 is expected for candidate GET sources.
- Redirects are acceptable only when the final host/path is stable and belongs
  to the intended source.
- RSS and REST are compared by payload size and stability; choose the smaller
  deterministic Ayuntamiento discovery surface that actually exposes the
  target campaign.
- Dinamización Form must expose the expected text in a normal GET. No browser
  execution is allowed.
- Turismo, Chess and Tertulia must expose their expected markers in the body.
- EPA may pass transport while still remaining **not sufficient** as a dynamic
  language source because its public page/forms omit the current detailed
  Spanish timetable/vacancy/price contract.
- EOI vacancy entry is exploratory. Failure to expose `Guardamar` in the
  initial GET does not mean the official service is unusable; it means a
  filtered request contract still needs separate proof and the source remains
  deferred.

After the operator pastes the full output, record the measured results here and
make the final READY/DEFER decisions before production code changes.
