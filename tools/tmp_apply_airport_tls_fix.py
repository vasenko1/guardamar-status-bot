from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label} anchor changed")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label} anchor changed")
    return updated


source_path = Path("src/telegrambot/airport_schedule.py")
source = source_path.read_text(encoding="utf-8")
source = replace_once(
    source,
    'TLS_INTERMEDIATE_HOST = re.compile(r"^[a-z0-9-]+\\.i\\.lencr\\.org$")\n',
    '''TLS_AIA_HOST = re.compile(
    r"^(?P<label>(?:e[5-9]|r1[0-4]|ye[1-3]|yr[1-3]))\\.i\\.lencr\\.org$"
)
TLS_CERT_HOST = "letsencrypt.org"
TLS_CERT_CONTENT_TYPES = frozenset({
    "application/pkix-cert",
    "application/x-x509-cert",
})
TLS_CHAIN_PATHS = {
    "ye1": (
        "/certs/gen-y/int-ye1.der",
        "/certs/gen-y/root-ye-by-x2.der",
    ),
    "ye2": (
        "/certs/gen-y/int-ye2.der",
        "/certs/gen-y/root-ye-by-x2.der",
    ),
    "ye3": (
        "/certs/gen-y/int-ye3.der",
        "/certs/gen-y/root-ye-by-x2.der",
    ),
    "yr1": (
        "/certs/gen-y/int-yr1.der",
        "/certs/gen-y/root-yr-by-x1.der",
    ),
    "yr2": (
        "/certs/gen-y/int-yr2.der",
        "/certs/gen-y/root-yr-by-x1.der",
    ),
    "yr3": (
        "/certs/gen-y/int-yr3.der",
        "/certs/gen-y/root-yr-by-x1.der",
    ),
    "e5": ("/certs/2024/e5.der",),
    "e6": ("/certs/2024/e6.der",),
    "e7": ("/certs/2024/e7.der",),
    "e8": ("/certs/2024/e8.der",),
    "e9": ("/certs/2024/e9.der",),
    "r10": ("/certs/2024/r10.der",),
    "r11": ("/certs/2024/r11.der",),
    "r12": ("/certs/2024/r12.der",),
    "r13": ("/certs/2024/r13.der",),
    "r14": ("/certs/2024/r14.der",),
}
TLS_ALLOWED_CERT_PATHS = frozenset(
    path for chain in TLS_CHAIN_PATHS.values() for path in chain
)
''',
    "TLS constant",
)

source = replace_regex_once(
    source,
    r'def _allowed_intermediate_url\(url: str\) -> bool:\n.*?\n\ndef _missing_issuer',
    '''def _allowed_intermediate_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == TLS_CERT_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in TLS_ALLOWED_CERT_PATHS
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _missing_issuer''',
    "allowed intermediate function",
)

source = replace_regex_once(
    source,
    r'def _intermediate_url\(certificate: bytes\) -> str:\n.*?\n\ndef _download_intermediate',
    '''def _intermediate_urls(certificate: bytes) -> tuple[str, ...]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "leaf.der"
        path.write_bytes(certificate)
        try:
            result = subprocess.run(
                [
                    "openssl", "x509", "-inform", "DER", "-in", str(path),
                    "-noout", "-ext", "authorityInfoAccess",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise AirportScheduleError(
                "required TLS tool is missing: openssl"
            ) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise AirportScheduleError(
                "airport TLS certificate could not be inspected"
            ) from exc
    urls = re.findall(
        r"CA Issuers\\s*-\\s*URI:(https?://[^\\s]+)",
        result.stdout.decode("ascii", "replace"),
        flags=re.I,
    )
    if len(urls) != 1:
        raise AirportScheduleError("airport TLS issuer is ambiguous")
    parsed = urllib.parse.urlparse(urls[0])
    try:
        port = parsed.port
    except ValueError as exc:
        raise AirportScheduleError("airport TLS issuer is not allowed") from exc
    match = TLS_AIA_HOST.fullmatch(parsed.hostname or "")
    if (
        parsed.scheme not in {"http", "https"}
        or match is None
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise AirportScheduleError("airport TLS issuer is not allowed")
    paths = TLS_CHAIN_PATHS.get(match.group("label"))
    if paths is None:
        raise AirportScheduleError("airport TLS issuer is not supported")
    return tuple(
        urllib.parse.urlunparse(("https", TLS_CERT_HOST, path, "", "", ""))
        for path in paths
    )


def _intermediate_url(certificate: bytes) -> str:
    return _intermediate_urls(certificate)[0]


def _download_intermediate''',
    "intermediate URL function",
)

source = replace_regex_once(
    source,
    r'def _download_intermediate\(url: str\) -> bytes:\n.*?\n\ndef _repaired_tls_context',
    '''def _download_intermediate(url: str) -> bytes:
    if not _allowed_intermediate_url(url):
        raise AirportScheduleError("TLS intermediate URL is not allowed")
    opener = urllib.request.build_opener(_IntermediateRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={
            "Accept": ", ".join(sorted(TLS_CERT_CONTENT_TYPES)),
            "User-Agent": USER_AGENT,
        },
    )
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise AirportScheduleError(
            "TLS intermediate is unavailable"
        ) from exc
    with response:
        final_url = response.geturl()
        payload = response.read(TLS_CERT_LIMIT_BYTES + 1)
        if (
            response.status != 200
            or final_url != url
            or not _allowed_intermediate_url(final_url)
            or response.headers.get_content_type() not in TLS_CERT_CONTENT_TYPES
            or not 1 <= len(payload) <= TLS_CERT_LIMIT_BYTES
        ):
            raise AirportScheduleError("TLS intermediate is invalid")
        return payload


def _repaired_tls_context''',
    "download intermediate function",
)

source = replace_regex_once(
    source,
    r'def _repaired_tls_context\(\) -> ssl\.SSLContext:\n.*?\n\ndef _normalized_url',
    '''def _repaired_tls_context() -> ssl.SSLContext:
    global _BUS_TLS_CONTEXT
    with _BUS_TLS_LOCK:
        if _BUS_TLS_CONTEXT is not None:
            return _BUS_TLS_CONTEXT
        certificate = _leaf_certificate()
        chain = [
            _download_intermediate(url)
            for url in _intermediate_urls(certificate)
        ]
        try:
            cadata = "".join(
                ssl.DER_cert_to_PEM_cert(item) for item in chain
            )
            context = ssl.create_default_context()
            context.load_verify_locations(cadata=cadata)
        except (ValueError, ssl.SSLError) as exc:
            raise AirportScheduleError(
                "TLS intermediate could not be loaded"
            ) from exc
        _BUS_TLS_CONTEXT = context
        return context


def _normalized_url''',
    "TLS context function",
)
source_path.write_text(source, encoding="utf-8")


test_path = Path("tests/test_airport_schedule.py")
tests = test_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    "    _allowed_intermediate_url,\n    _intermediate_url,\n",
    "    _allowed_intermediate_url,\n    _download_intermediate,\n    _intermediate_url,\n    _intermediate_urls,\n    _repaired_tls_context,\n",
    "TLS test imports",
)
tests = replace_regex_once(
    tests,
    r'    def test_tls_repair_accepts_only_official_https_intermediate\(self\):\n.*?\n    def test_only_missing_issuer_error_can_trigger_tls_repair',
    '''    def test_tls_repair_accepts_only_official_certificate_repository(self):
        for url in (
            "https://letsencrypt.org/certs/gen-y/int-yr1.der",
            "https://letsencrypt.org/certs/gen-y/root-yr-by-x1.der",
            "https://letsencrypt.org/certs/2024/e7.der",
        ):
            self.assertTrue(_allowed_intermediate_url(url))
        for url in (
            "http://letsencrypt.org/certs/gen-y/int-yr1.der",
            "https://yr1.i.lencr.org/",
            "https://letsencrypt.org/certs/gen-y/int-yr1.der?next=evil",
            "https://letsencrypt.org/certs/gen-y/unknown.der",
            "https://letsencrypt.org.evil.example/certs/gen-y/int-yr1.der",
            "https://user@letsencrypt.org/certs/gen-y/int-yr1.der",
        ):
            self.assertFalse(_allowed_intermediate_url(url))

    def test_tls_aia_maps_current_y_issuer_to_verified_repository_chain(self):
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                b"Authority Information Access:\\n"
                b" CA Issuers - URI:http://yr1.i.lencr.org/\\n"
            ),
        )
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            return_value=completed,
        ):
            urls = _intermediate_urls(b"leaf")
            first = _intermediate_url(b"leaf")

        self.assertEqual(
            urls,
            (
                "https://letsencrypt.org/certs/gen-y/int-yr1.der",
                "https://letsencrypt.org/certs/gen-y/root-yr-by-x1.der",
            ),
        )
        self.assertEqual(first, urls[0])

    def test_tls_aia_maps_legacy_issuer_to_verified_repository_certificate(self):
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                b"Authority Information Access:\\n"
                b" CA Issuers - URI:http://e7.i.lencr.org/\\n"
            ),
        )
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            return_value=completed,
        ):
            urls = _intermediate_urls(b"leaf")

        self.assertEqual(
            urls,
            ("https://letsencrypt.org/certs/2024/e7.der",),
        )

    def test_tls_aia_rejects_unknown_issuer_label(self):
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                b"Authority Information Access:\\n"
                b" CA Issuers - URI:http://yr4.i.lencr.org/\\n"
            ),
        )
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaises(AirportScheduleError):
                _intermediate_urls(b"leaf")

    def test_tls_certificate_download_requires_exact_official_der_response(self):
        url = "https://letsencrypt.org/certs/gen-y/int-yr1.der"
        response = MagicMock()
        response.geturl.return_value = url
        response.read.return_value = b"der-certificate"
        response.status = 200
        response.headers.get_content_type.return_value = "application/x-x509-cert"
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "telegrambot.airport_schedule.urllib.request.build_opener",
            return_value=opener,
        ):
            self.assertEqual(_download_intermediate(url), b"der-certificate")

        response.headers.get_content_type.return_value = "application/octet-stream"
        with patch(
            "telegrambot.airport_schedule.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(AirportScheduleError):
                _download_intermediate(url)

        response.headers.get_content_type.return_value = "application/x-x509-cert"
        response.geturl.return_value = (
            "https://letsencrypt.org/certs/gen-y/int-yr2.der"
        )
        with patch(
            "telegrambot.airport_schedule.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(AirportScheduleError):
                _download_intermediate(url)

    def test_tls_context_loads_the_whole_verified_chain(self):
        context = MagicMock(spec=ssl.SSLContext)
        with (
            patch("telegrambot.airport_schedule._BUS_TLS_CONTEXT", None),
            patch(
                "telegrambot.airport_schedule._leaf_certificate",
                return_value=b"leaf",
            ),
            patch(
                "telegrambot.airport_schedule._intermediate_urls",
                return_value=(
                    "https://letsencrypt.org/certs/gen-y/int-yr1.der",
                    "https://letsencrypt.org/certs/gen-y/root-yr-by-x1.der",
                ),
            ),
            patch(
                "telegrambot.airport_schedule._download_intermediate",
                side_effect=(b"one", b"two"),
            ) as download,
            patch(
                "telegrambot.airport_schedule.ssl.DER_cert_to_PEM_cert",
                side_effect=("PEM-ONE\\n", "PEM-TWO\\n"),
            ),
            patch(
                "telegrambot.airport_schedule.ssl.create_default_context",
                return_value=context,
            ),
        ):
            repaired = _repaired_tls_context()

        self.assertIs(repaired, context)
        self.assertEqual(download.call_count, 2)
        context.load_verify_locations.assert_called_once_with(
            cadata="PEM-ONE\\nPEM-TWO\\n"
        )

    def test_only_missing_issuer_error_can_trigger_tls_repair''',
    "TLS tests",
)
test_path.write_text(tests, encoding="utf-8")


arch_path = Path("docs/kb/03_System_Architecture.md")
arch = arch_path.read_text(encoding="utf-8")
arch = replace_once(
    arch,
    "A narrowly allowlisted Let's Encrypt AIA recovery preserves full TLS and hostname verification when the operator omits its issuing intermediate.\n",
    "A narrowly allowlisted Let's Encrypt recovery reads only the leaf AIA issuer label, downloads the corresponding certificate chain from the official `https://letsencrypt.org/certs/` repository, and preserves full TLS and hostname verification when the operator omits its issuing chain.\n",
    "architecture TLS wording",
)
arch_path.write_text(arch, encoding="utf-8")

runtime_path = Path("docs/kb/04_Runtime_Constraints.md")
runtime = runtime_path.read_text(encoding="utf-8")
runtime = replace_once(
    runtime,
    "One bounded in-memory HTTPS intermediate-certificate recovery is allowed only for the documented Bus Sigüenza missing-issuer fault; it must not disable TLS verification or persist certificates. No browser, OCR, resident collector, or background process is allowed.\n",
    "One bounded in-memory HTTPS issuer-chain recovery is allowed only for the documented Bus Sigüenza missing-issuer fault. It may read at most two allowlisted DER certificates from the official Let's Encrypt certificate repository, must not disable TLS verification, and must not persist certificates. No browser, OCR, resident collector, or background process is allowed.\n",
    "runtime TLS wording",
)
runtime_path.write_text(runtime, encoding="utf-8")

adr43_path = Path("adr/0043-date-specific-airport-timetable.md")
adr43 = adr43_path.read_text(encoding="utf-8")
adr43 = replace_once(
    adr43,
    "- Extends ADRs 0041 and 0042\n",
    "- Extends ADRs 0041 and 0042\n- TLS recovery details superseded by ADR 0066\n",
    "ADR 0043 header",
)
adr43_path.write_text(adr43, encoding="utf-8")

Path("adr/0066-bus-siguenza-tls-recovery.md").write_text(
    '''# 0066: Recover Bus Sigüenza TLS from the official Let's Encrypt repository

- Status: Accepted
- Date: 2026-09-15
- Supersedes: the TLS-recovery portion of ADR 0043

## Context

Bus Sigüenza still omits the issuing chain on the production host. The original
recovery read the leaf AIA and changed its `http://<issuer>.i.lencr.org/` URL to
HTTPS. In September 2026 that path fails on Termux with `TLS intermediate is
unavailable`. Let's Encrypt's current Chains of Trust page publishes the active
Generation Y intermediates (YE1/YE2 and YR1/YR2), their backup YE3/YR3
intermediates, the cross-signed Generation Y roots, and the still-valid 2024
E5-E9/R10-R14 intermediates through its official HTTPS certificate repository.
The repository serves DER files as `application/x-x509-cert`.

## Decision

For the existing missing-issuer-only recovery on exactly
`www.bus-siguenza.com`:

1. Read the unverified leaf only to obtain its single CA Issuers AIA label.
2. Accept only the known Let's Encrypt labels YE1-YE3, YR1-YR3, E5-E9 and
   R10-R14 on the exact `*.i.lencr.org/` AIA form. The AIA URL itself is never
   fetched and never becomes a trust source.
3. Map that label to fixed paths under `https://letsencrypt.org/certs/`.
4. For Generation Y, also load the corresponding official cross-signed Root YE
   or Root YR certificate so the chain reaches the system-trusted ISRG root.
5. Accept only exact allowlisted HTTPS paths, no credentials/query/fragment, a
   200 response, the exact requested final URL, DER certificate MIME
   (`application/x-x509-cert` or `application/pkix-cert`), and the existing
   16 KiB certificate size bound.
6. Build a fresh default SSL context, add the one- or two-certificate recovery
   chain in memory, and retry the original Bus Sigüenza request with normal
   hostname and certificate verification still enabled.
7. Cache that verified context only in memory for the one-shot process. Store no
   certificate bytes and do not enter this path for any TLS error except a
   missing issuer.

## Consequences

- The recovery no longer depends on HTTPS support at `*.i.lencr.org`.
- Current Generation Y issuance is supported without trusting the new Y roots
  directly: the official cross-signed root connects to ISRG Root X1 or X2 in
  the normal system trust store.
- A future unknown intermediate fails closed until its official repository path
  is reviewed and allowlisted.
- Normal successful TLS requests make no additional request. A broken-chain
  process makes at most two small official certificate reads and reuses the
  repaired context for the remaining one-shot work.
- No dependency, daemon, persisted certificate, disabled verification, or
  generic certificate downloader is added.
''',
    encoding="utf-8",
)

Path("research/2026-09-15-bus-siguenza-tls-recovery.md").write_text(
    '''# Bus Sigüenza TLS recovery check — 2026-09-15

## Production symptom

On the Termux host, the transport-notification baseline repeatedly logged:

`Tomorrow airport timetable unavailable; exact airport change detection will skip the next day rather than guess: TLS intermediate is unavailable`

The accepted current airport snapshot and fare remained usable, but the
next-day baseline could not be collected.

## Cause

ADR 0043's recovery derived the leaf CA Issuers AIA and rewrote the official
HTTP `*.i.lencr.org` address to HTTPS. The current recovery request itself is
therefore the failing step. The AIA host is useful as an issuer identifier, but
it is not necessary to use it as the certificate download endpoint.

Let's Encrypt documents `i.lencr.org` as its issuer-certificate namespace and,
as of its Chains of Trust page updated 2026-07-08, lists YE1, YE2, YR1 and YR2
as the active intermediates, YE3/YR3 as backups, and E5-E9/R10-R14 as retired
but still-valid prior intermediates. The same official page links DER copies
under `https://letsencrypt.org/certs/`; current DER responses use
`application/x-x509-cert`.

## Recovery boundary

Use the leaf AIA only to select one reviewed issuer label, fetch only the
corresponding fixed official HTTPS certificate path(s), keep normal system
trust and hostname verification, and fail closed for every unknown label or
unexpected response. Generation Y needs the intermediate plus its official
cross-signed Root YE/Root YR certificate; the earlier 2024 intermediates need
only their intermediate because ISRG Root X1/X2 is already the system trust
anchor.

Official references reviewed:

- https://letsencrypt.org/docs/lencr.org/
- https://letsencrypt.org/certificates/
- https://letsencrypt.org/2025/11/24/gen-y-hierarchy/
''',
    encoding="utf-8",
)

log_path = Path("docs/kb/10_Decision_Log.md")
log = log_path.read_text(encoding="utf-8")
anchor = "| 2026-09-15 | Publish evidence-bounded transport changes at 12:30 |"
index = log.find(anchor)
if index < 0:
    raise SystemExit("decision log anchor changed")
line_end = log.find("\n", index)
row = (
    "| 2026-09-15 | Recover Bus Sigüenza TLS from the official Let's Encrypt certificate repository | "
    "The operator still omits its issuer chain and the old HTTPS-upgraded AIA fetch fails on Termux. "
    "Use the leaf AIA only as a reviewed issuer label, fetch one or two exact DER certificates from "
    "`letsencrypt.org/certs`, retain normal TLS/hostname verification, and fail closed on unknown issuers. | "
    "`adr/0066-bus-siguenza-tls-recovery.md`, `research/2026-09-15-bus-siguenza-tls-recovery.md` |\n"
)
log = log[:line_end + 1] + row + log[line_end + 1:]
log_path.write_text(log, encoding="utf-8")
