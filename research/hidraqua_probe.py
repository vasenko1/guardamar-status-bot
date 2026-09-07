#!/usr/bin/env python3
"""Small manual probe for Hidraqua's public Guardamar ArcGIS layer.

This is deliberately not a TelegramBot module and performs no persistence
unless --save-raw is explicitly requested.
"""

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

import requests


LAYER_URL = (
    "https://services3.arcgis.com/5VitVYyVLQYnzXCo/arcgis/rest/services/"
    "Cierres_webPublicas_v/FeatureServer/0"
)
QUERY_URL = f"{LAYER_URL}/query"
GUARDAMAR_CODE = "03076"
ACTIVE_STATUSES = ("4AP", "5EC")
OUT_FIELDS = (
    "CI_ID,CI_FH_INI_PREV,CI_FH_FIN_PREV,CI_DIRECCION,CI_CALLES,"
    "CI_ESTADO,CI_MOTIVO,COD_MUNI"
)
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 512 * 1024
MADRID = ZoneInfo("Europe/Madrid")


class ProbeError(RuntimeError):
    """A transport, decoding, or ArcGIS-level failure."""


def _request_json(url: str, parameters: Dict[str, str]) -> Dict[str, Any]:
    """Fetch one bounded ArcGIS JSON response and reject API errors."""
    query = urllib.parse.urlencode(parameters)
    try:
        response = requests.get(
            f"{url}?{query}",
            headers={"Accept": "application/json", "User-Agent": "HidraquaProbe/1.0"},
            timeout=TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ProbeError(f"HTTP {response.status_code}")
        response.raise_for_status()
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            chunks.extend(chunk)
            if len(chunks) > MAX_RESPONSE_BYTES:
                raise ProbeError("Response exceeds 512 KiB limit")
        payload = bytes(chunks)
    except requests.RequestException as exc:
        raise ProbeError(f"Network error: {exc}") from exc
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProbeError("Response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProbeError("Response JSON is not an object")
    if "error" in decoded:
        error = decoded["error"]
        if isinstance(error, dict):
            raise ProbeError(
                f"ArcGIS error {error.get('code', '?')}: {error.get('message', '?')}"
            )
        raise ProbeError("ArcGIS returned an error")
    return decoded


def _format_epoch_millis(value: Any) -> str:
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return f"invalid ({value!r})"
    try:
        instant = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return f"invalid ({value!r})"
    return instant.astimezone(MADRID).strftime("%Y-%m-%d %H:%M:%S %Z")


def _show_features(features: Iterable[Dict[str, Any]]) -> int:
    count = 0
    for count, feature in enumerate(features, start=1):
        attributes = feature.get("attributes", {})
        if not isinstance(attributes, dict):
            print(f"{count}. invalid attributes")
            continue
        print(f"{count}. CI_ID: {attributes.get('CI_ID', '—')}")
        print(f"   status/motive: {attributes.get('CI_ESTADO', '—')} / {attributes.get('CI_MOTIVO', '—')}")
        print(f"   start: {_format_epoch_millis(attributes.get('CI_FH_INI_PREV'))}")
        print(f"   expected restoration: {_format_epoch_millis(attributes.get('CI_FH_FIN_PREV'))}")
        print(f"   address: {attributes.get('CI_DIRECCION') or '—'}")
        print(f"   other streets: {attributes.get('CI_CALLES') or '—'}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-guardamar", action="store_true", help="do not limit results to active status codes")
    parser.add_argument("--raw", action="store_true", help="print the returned JSON")
    parser.add_argument("--save-raw", type=Path, metavar="PATH", help="explicitly save returned JSON for debugging")
    args = parser.parse_args()

    if args.all_guardamar:
        where = f"COD_MUNI='{GUARDAMAR_CODE}'"
    else:
        statuses = ",".join(f"'{status}'" for status in ACTIVE_STATUSES)
        where = f"COD_MUNI='{GUARDAMAR_CODE}' AND CI_ESTADO IN ({statuses})"
    try:
        result = _request_json(
            QUERY_URL,
            {"where": where, "outFields": OUT_FIELDS, "returnGeometry": "false", "f": "json"},
        )
    except ProbeError as exc:
        print(f"Hidraqua probe failed: {exc}", file=sys.stderr)
        return 1

    if args.save_raw is not None:
        args.save_raw.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Raw JSON saved to {args.save_raw}")
    if args.raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    features = result.get("features")
    if not isinstance(features, list):
        print("Hidraqua probe failed: JSON has no features list", file=sys.stderr)
        return 1
    scope = "all visible Guardamar rows" if args.all_guardamar else "active Guardamar rows"
    print(f"{scope}: {len(features)}")
    _show_features(features)
    if result.get("exceededTransferLimit"):
        print("WARNING: ArcGIS truncated this result; use pagination before treating it as exhaustive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
