from pathlib import Path

path = Path("tools/tmp_apply_airport_tls_fix.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)",
    "updated, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)",
)
text = text.replace(
    '    "A narrowly allowlisted Let\'s Encrypt AIA recovery preserves full TLS and hostname verification when the operator omits its issuing intermediate.\\n",',
    '    "A narrowly allowlisted Let\'s Encrypt AIA recovery preserves full TLS\\nand hostname verification when the operator omits its issuing intermediate.\\n",',
)
text = text.replace(
    '    "One bounded in-memory HTTPS intermediate-certificate recovery is allowed only for the documented Bus Sigüenza missing-issuer fault; it must not disable TLS verification or persist certificates. No browser, OCR, resident collector, or background process is allowed.\\n",',
    '    "One bounded in-memory HTTPS intermediate-certificate recovery is allowed\\nonly for the documented Bus Sigüenza missing-issuer fault; it must not disable\\nTLS verification or persist certificates. No browser, OCR, resident collector,\\nor background process is allowed.\\n",',
)
path.write_text(text, encoding="utf-8")
