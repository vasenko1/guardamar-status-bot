import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EarthquakeTermuxTests(unittest.TestCase):
    def _run_installer(self, initial, *, list_error=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            state = root / "crontab"
            state.write_text(initial, encoding="utf-8")
            crontab = commands / "crontab"
            crontab.write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -l ]; then\n"
                "  if [ -n \"${LIST_ERROR-}\" ]; then\n"
                "    echo \"$LIST_ERROR\" >&2\n"
                "    exit 2\n"
                "  fi\n"
                "  cat \"$FAKE_CRONTAB\"\n"
                "else\n"
                "  cat >\"$FAKE_CRONTAB\"\n"
                "fi\n",
                encoding="utf-8",
            )
            crontab.chmod(0o755)
            service = commands / "sv"
            service.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            service.chmod(0o755)
            environment = dict(os.environ)
            environment.update({
                "HOME": str(root / "home"),
                "PATH": f"{commands}:/usr/bin:/bin",
                "FAKE_CRONTAB": str(state),
                "LIST_ERROR": list_error or "",
            })
            result = subprocess.run(
                ["sh", str(ROOT / "termux" / "install-earthquake-cron.sh")],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            return result, state.read_text(encoding="utf-8")

    def test_cron_uses_nonconflicting_minute_and_owns_a_marked_block(self):
        script = (
            ROOT / "termux" / "install-earthquake-cron.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('"55 * * * * $MONITOR"', script)
        self.assertIn("# BEGIN guardamar-status earthquake monitor", script)
        self.assertIn("# END guardamar-status earthquake monitor", script)
        self.assertIn('crontab -l >"$CURRENT"', script)

    def test_monitor_skips_during_deployment_and_rotates_its_log(self):
        script = (
            ROOT / "termux" / "monitor-earthquakes.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'RUNTIME_LOCK="$PROJECT_DIR/state/code-runtime.lock"', script
        )
        self.assertIn('if ! acquire_runtime_lock "$RUNTIME_LOCK"', script)
        self.assertIn('"$(wc -c < "$LOG")" -gt 1048576', script)
        self.assertIn("python -m telegrambot monitor-earthquakes", script)

    def test_deploy_uses_the_same_runtime_lock(self):
        script = (ROOT / "termux" / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn(
            'RUNTIME_LOCK_DIR="$STATE_DIR/code-runtime.lock"', script
        )
        self.assertIn(
            'if ! acquire_runtime_lock "$RUNTIME_LOCK_DIR"', script
        )

    def test_runtime_lock_recovers_only_a_stale_pid_owner(self):
        script = (
            ROOT / "termux" / "runtime-lock.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('kill -0 "$runtime_lock_pid"', script)
        self.assertIn('rm -f "$runtime_lock_owner"', script)
        self.assertIn('rmdir "$runtime_lock_path"', script)

    def test_installer_is_idempotent_and_preserves_unrelated_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed = self._run_installer(unrelated)
        second, reinstalled = self._run_installer(installed)

        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(installed, reinstalled)
        self.assertIn(unrelated.strip(), installed)
        self.assertEqual(installed.count("55 * * * *"), 1)

    def test_installer_rejects_unbalanced_marker_without_rewrite(self):
        initial = (
            "12 3 * * * /other/bot.sh\n"
            "# BEGIN guardamar-status earthquake monitor\n"
            "18 4 * * * /must/not/disappear.sh\n"
        )

        result, after = self._run_installer(initial)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)

    def test_installer_rejects_crontab_read_error(self):
        initial = "12 3 * * * /other/bot.sh\n"

        result, after = self._run_installer(
            initial, list_error="permission denied"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)


if __name__ == "__main__":
    unittest.main()
