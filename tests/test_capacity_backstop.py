import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock


SCRIPT = Path(__file__).parents[1] / "termux/dispatch-guardamar-capacity.py"
SPEC = importlib.util.spec_from_file_location("capacity_backstop", SCRIPT)
backstop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backstop)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
WORKFLOW_ID = 356000904


def encoded(value):
    return json.dumps(value).encode("utf-8")


def workflow(state="active"):
    return (200, encoded({
        "id": WORKFLOW_ID,
        "path": ".github/workflows/guardamar-capacity.yml",
        "state": state,
    }))


def runs(status="completed", created_at="2026-09-13T11:40:00Z"):
    return (200, encoded({
        "total_count": 1,
        "workflow_runs": [{
            "id": 123,
            "workflow_id": WORKFLOW_ID,
            "head_branch": "main",
            "status": status,
            "created_at": created_at,
        }],
    }))


def no_runs():
    return (200, encoded({"total_count": 0, "workflow_runs": []}))


def accepted(run_id=456):
    return (200, encoded({"workflow_run_id": run_id}))


class CapacityBackstopTests(unittest.TestCase):
    def dispatch(self, responses):
        request = Mock(side_effect=responses)
        outcome = backstop.dispatch_once("test-token", request=request, now=NOW)
        return outcome, request

    def test_active_without_recent_run_posts_once_with_exact_inputs(self):
        outcome, request = self.dispatch([workflow(), no_runs(), accepted()])

        self.assertEqual(outcome, "DISPATCHED run_id=456")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].args[:2], ("GET", backstop.WORKFLOW_PATH))
        self.assertEqual(request.call_args_list[1].args[:2], ("GET", backstop.RUNS_PATH))
        self.assertEqual(request.call_args_list[2].args, (
            "POST", backstop.DISPATCH_PATH, "test-token",
            {"ref": "main", "inputs": {"action": "launch"}},
        ))

    def test_inactive_workflow_skips_without_post(self):
        outcome, request = self.dispatch([workflow("disabled_manually")])
        self.assertEqual(outcome, "SKIP workflow_state=disabled_manually")
        self.assertEqual(request.call_count, 1)

    def test_recent_completed_run_skips(self):
        outcome, request = self.dispatch([
            workflow(), runs(created_at="2026-09-13T11:55:00Z")
        ])
        self.assertEqual(outcome, "SKIP recent_run run_id=123 status=completed")
        self.assertEqual(request.call_count, 2)

    def test_queued_and_in_progress_runs_skip_even_when_old(self):
        for status in ("queued", "requested", "waiting", "pending", "in_progress"):
            with self.subTest(status=status):
                outcome, request = self.dispatch([workflow(), runs(status=status)])
                self.assertEqual(outcome, f"SKIP recent_run run_id=123 status={status}")
                self.assertEqual(request.call_count, 2)

    def test_old_completed_run_allows_dispatch(self):
        outcome, request = self.dispatch([workflow(), runs(), accepted()])
        self.assertEqual(outcome, "DISPATCHED run_id=456")
        self.assertEqual(request.call_count, 3)

    def test_updated_at_does_not_replace_created_at_freshness(self):
        old = json.loads(runs()[1])
        old["workflow_runs"][0]["updated_at"] = "2026-09-13T11:59:00Z"
        outcome, request = self.dispatch([workflow(), (200, encoded(old)), accepted()])
        self.assertEqual(outcome, "DISPATCHED run_id=456")
        self.assertEqual(request.call_count, 3)

    def test_workflow_metadata_failures_never_post(self):
        for first in ((503, b""), (200, b"not json"), (200, None),
                      RuntimeError("secret")):
            with self.subTest(first=type(first).__name__):
                outcome, request = self.dispatch([first])
                self.assertTrue(outcome.startswith("SKIP workflow_"))
                self.assertEqual(request.call_count, 1)

    def test_recent_runs_failures_never_post(self):
        for second in ((503, b""), (200, b"not json"), (200, None),
                       (200, encoded({"workflow_runs": []})), RuntimeError("secret")):
            with self.subTest(second=type(second).__name__):
                outcome, request = self.dispatch([workflow(), second])
                self.assertTrue(outcome.startswith("SKIP recent_runs_"))
                self.assertEqual(request.call_count, 2)

    def test_dispatch_transport_failure_is_not_retried(self):
        outcome, request = self.dispatch([
            workflow(), no_runs(), ConnectionResetError("secret response")
        ])
        self.assertEqual(outcome, "DISPATCH_UNCERTAIN")
        self.assertEqual(request.call_count, 3)

    def test_dispatch_http_errors_and_legacy_204_are_not_retried(self):
        for status in (429, 503, 204):
            with self.subTest(status=status):
                outcome, request = self.dispatch([
                    workflow(), no_runs(), (status, b"")
                ])
                self.assertEqual(outcome, "DISPATCH_NOT_CONFIRMED")
                self.assertEqual(request.call_count, 3)

    def test_accepted_invalid_response_is_not_retried(self):
        for last in ((200, b"not json"), (200, None), (200, encoded({})),
                     (200, encoded({"workflow_run_id": True}))):
            with self.subTest(last=last):
                outcome, request = self.dispatch([workflow(), no_runs(), last])
                self.assertEqual(outcome, "DISPATCH_ACCEPTED_RESPONSE_INVALID")
                self.assertEqual(request.call_count, 3)

    def test_token_and_error_text_never_appear_in_output(self):
        secret = "ghp-secret-private-value"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-token"
            path.write_text(secret + "\n", encoding="ascii")
            os.chmod(path, 0o600)
            request = Mock(side_effect=[workflow(), no_runs(), OSError(secret)])
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = backstop.main([], request=request, token_path=path, now=NOW)
            self.assertEqual(result, 0)
            self.assertIn("DISPATCH_UNCERTAIN", stdout.getvalue())
            self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(request.call_count, 3)

    def test_token_file_must_be_regular_nonempty_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-token"
            path.write_text("test-token\n", encoding="ascii")
            os.chmod(path, 0o644)
            with self.assertRaises(backstop.BackstopError):
                backstop.read_token(path)
            for mode in (0o600, 0o400):
                with self.subTest(mode=mode):
                    os.chmod(path, mode)
                    self.assertEqual(backstop.read_token(path), "test-token")
            os.chmod(path, 0o600)
            path.write_text("", encoding="ascii")
            with self.assertRaises(backstop.BackstopError):
                backstop.read_token(path)
            path.write_text("test-token", encoding="ascii")
            link = Path(directory) / "token-link"
            link.symlink_to(path)
            with self.assertRaises(backstop.BackstopError):
                backstop.read_token(link)

    def test_github_headers_and_exact_host_are_pinned(self):
        headers = backstop._headers("test-token")
        self.assertEqual(backstop.API_HOST, "api.github.com")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2026-03-10")
        self.assertEqual(headers["User-Agent"], "guardamar-capacity-termux")
        self.assertEqual(headers["Authorization"], "Bearer test-token")


if __name__ == "__main__":
    unittest.main()
