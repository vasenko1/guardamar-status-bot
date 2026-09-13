#!/usr/bin/env python3
"""One bounded GitHub Actions backstop check; OCI runs only on GitHub."""

import http.client
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_HOST = "api.github.com"
WORKFLOW_PATH = (
    "/repos/vasenko1/guardamar-status-bot/actions/workflows/"
    "guardamar-capacity.yml"
)
RUNS_PATH = WORKFLOW_PATH + "/runs?branch=main&per_page=1"
DISPATCH_PATH = WORKFLOW_PATH + "/dispatches"
TOKEN_PATH = Path.home() / ".config/guardamar-capacity/github-token"
RESPONSE_LIMIT = 128 * 1024
NETWORK_TIMEOUT = 15
RECENT_WINDOW = timedelta(minutes=10)
ACTIVE_RUN_STATUSES = frozenset(
    {"queued", "requested", "waiting", "pending", "in_progress"}
)
WORKFLOW_STATES = frozenset(
    {
        "active", "disabled_manually", "disabled_inactivity", "disabled_fork",
        "deleted",
    }
)


class BackstopError(Exception):
    """Safe, fixed-code failure; never includes credentials or response data."""


def read_token(path=TOKEN_PATH):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise BackstopError("token_unavailable") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o077
            or not 0 < metadata.st_size <= 4096
        ):
            raise BackstopError("token_unsafe")
        raw = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        raise BackstopError("token_invalid")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise BackstopError("token_invalid") from None
    if not token or any(not 33 <= ord(character) <= 126 for character in token):
        raise BackstopError("token_invalid")
    return token


def _headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "guardamar-capacity-termux",
        "Authorization": "Bearer " + token,
    }


def request_api(method, path, token, body=None):
    """Make one exact-host request without redirects or network retries."""

    headers = _headers(token)
    payload = None
    if body is not None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPSConnection(API_HOST, timeout=NETWORK_TIMEOUT)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        content = response.read(RESPONSE_LIMIT + 1)
        if len(content) > RESPONSE_LIMIT:
            return response.status, None
        return response.status, content
    finally:
        connection.close()


def _json_object(payload):
    if not isinstance(payload, bytes):
        raise BackstopError("invalid_json")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BackstopError("invalid_json") from None
    if not isinstance(value, dict):
        raise BackstopError("invalid_json")
    return value


def dispatch_once(token, request=request_api, now=None):
    """Return a safe outcome after at most two GETs and one POST."""

    observed_at = datetime.now(timezone.utc) if now is None else now
    try:
        status, payload = request("GET", WORKFLOW_PATH, token)
        if status != 200:
            return "SKIP workflow_check_failed"
        workflow = _json_object(payload)
        workflow_id = workflow.get("id")
        workflow_state = workflow.get("state")
        if (
            type(workflow_id) is not int
            or workflow_id <= 0
            or workflow.get("path") != ".github/workflows/guardamar-capacity.yml"
            or workflow_state not in WORKFLOW_STATES
        ):
            return "SKIP workflow_metadata_invalid"
    except Exception:
        return "SKIP workflow_check_failed"
    if workflow_state != "active":
        return "SKIP workflow_state=" + workflow_state

    try:
        status, payload = request("GET", RUNS_PATH, token)
        if status != 200:
            return "SKIP recent_runs_unavailable"
        runs = _json_object(payload)
        total = runs.get("total_count")
        items = runs.get("workflow_runs")
        if type(total) is not int or total < 0 or not isinstance(items, list):
            return "SKIP recent_runs_invalid"
        if (total == 0 and items) or (total > 0 and len(items) != 1):
            return "SKIP recent_runs_invalid"
        if items:
            latest = items[0]
            if not isinstance(latest, dict):
                return "SKIP recent_runs_invalid"
            run_id = latest.get("id")
            run_status = latest.get("status")
            created_text = latest.get("created_at")
            if (
                type(run_id) is not int
                or run_id <= 0
                or latest.get("workflow_id") != workflow_id
                or latest.get("head_branch") != "main"
                or run_status not in ACTIVE_RUN_STATUSES | {"completed"}
                or not isinstance(created_text, str)
            ):
                return "SKIP recent_runs_invalid"
            try:
                created_at = datetime.fromisoformat(
                    created_text.replace("Z", "+00:00")
                )
                age = observed_at - created_at
            except (TypeError, ValueError):
                return "SKIP recent_runs_invalid"
            if run_status in ACTIVE_RUN_STATUSES or age < RECENT_WINDOW:
                return f"SKIP recent_run run_id={run_id} status={run_status}"
    except Exception:
        return "SKIP recent_runs_unavailable"

    try:
        status, payload = request(
            "POST", DISPATCH_PATH, token, {"ref": "main", "inputs": {"action": "launch"}}
        )
    except Exception:
        # The POST may have been accepted before its response was lost.
        return "DISPATCH_UNCERTAIN"
    if status != 200:
        return "DISPATCH_NOT_CONFIRMED"
    try:
        run_id = _json_object(payload).get("workflow_run_id")
    except BackstopError:
        return "DISPATCH_ACCEPTED_RESPONSE_INVALID"
    if type(run_id) is not int or run_id <= 0:
        return "DISPATCH_ACCEPTED_RESPONSE_INVALID"
    return f"DISPATCHED run_id={run_id}"


def main(argv=None, request=request_api, token_path=TOKEN_PATH, now=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments not in ([], ["--check-token"]):
        print("SKIP invalid_arguments")
        return 2
    try:
        token = read_token(token_path)
    except BackstopError as exc:
        print("SKIP " + str(exc))
        return 2
    if arguments == ["--check-token"]:
        return 0
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(timestamp + " " + dispatch_once(token, request=request, now=now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
