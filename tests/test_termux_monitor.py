import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OperationalMonitorTermuxTests(unittest.TestCase):
    def _install(
        self,
        initial,
        *,
        list_error=None,
        no_crontab=False,
        crond_running=True,
        service_dir=True,
        sv_fail=False,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            crontab_state = root / "crontab"
            crontab_state.write_text(initial, encoding="utf-8")

            crontab = commands / "crontab"
            crontab.write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -l ]; then\n"
                "  if [ -n \"${LIST_ERROR-}\" ]; then\n"
                "    echo \"$LIST_ERROR\" >&2\n"
                "    exit 2\n"
                "  fi\n"
                "  if [ \"${NO_CRONTAB-}\" = 1 ]; then\n"
                "    echo \"no crontab for test\" >&2\n"
                "    exit 1\n"
                "  fi\n"
                "  cat \"$FAKE_CRONTAB\"\n"
                "elif [ \"$#\" -eq 1 ]; then\n"
                "  cat \"$1\" >\"$FAKE_CRONTAB\"\n"
                "else\n"
                "  cat >\"$FAKE_CRONTAB\"\n"
                "fi\n",
                encoding="utf-8",
            )
            crontab.chmod(0o755)

            crond_state = root / "crond-running"
            if crond_running:
                crond_state.write_text("1\n", encoding="utf-8")

            pgrep = commands / "pgrep"
            pgrep.write_text(
                "#!/bin/sh\n"
                "if [ -f \"$CROND_STATE\" ]; then exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            pgrep.chmod(0o755)

            sv = commands / "sv"
            sv.write_text(
                "#!/bin/sh\n"
                "if [ \"${SV_FAIL-}\" = 1 ]; then exit 1; fi\n"
                "touch \"$CROND_STATE\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            sv.chmod(0o755)

            prefix = root / "prefix"
            if service_dir:
                (prefix / "var" / "service" / "crond").mkdir(parents=True)

            environment = dict(os.environ)
            environment.update({
                "HOME": str(root / "home"),
                "PREFIX": str(prefix),
                "PATH": f"{commands}:/usr/bin:/bin",
                "FAKE_CRONTAB": str(crontab_state),
                "LIST_ERROR": list_error or "",
                "NO_CRONTAB": "1" if no_crontab else "",
                "CROND_STATE": str(crond_state),
                "SV_FAIL": "1" if sv_fail else "",
            })
            result = subprocess.run(
                ["sh", str(ROOT / "termux" / "install-monitor-cron.sh")],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            return result, crontab_state.read_text(encoding="utf-8")

    def test_installer_is_idempotent_and_preserves_unrelated_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed = self._install(unrelated)
        second, reinstalled = self._install(installed)

        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(installed, reinstalled)
        self.assertIn(unrelated.strip(), installed)
        self.assertEqual(installed.count("51 7-23 * * *"), 1)
        self.assertEqual(
            installed.count("# BEGIN guardamar-status operational monitor"), 1
        )
        self.assertEqual(
            installed.count("# END guardamar-status operational monitor"), 1
        )

    def test_installer_keeps_existing_beach_and_environment_rows(self):
        result, installed = self._install("")

        self.assertEqual(result.returncode, 0)
        self.assertIn("51 7-23 * * *", installed)
        self.assertIn("0,5,10 11,13,15,17,19 * 7,8 *", installed)
        self.assertIn("0,5,10 12,14,16,18 * 6,9 *", installed)
        self.assertIn("0,5,10 12,14,16,18 1-15 10 *", installed)
        self.assertIn("0 20 * 6,9 *", installed)
        self.assertIn("0 11,15,19 * 1-5,10-12 *", installed)

    def test_installer_accepts_normal_missing_crontab(self):
        result, installed = self._install("", no_crontab=True)

        self.assertEqual(result.returncode, 0)
        self.assertIn("51 7-23 * * *", installed)

    def test_installer_rejects_unbalanced_marker_without_rewrite(self):
        initial = (
            "12 3 * * * /other/bot.sh\n"
            "# BEGIN guardamar-status operational monitor\n"
            "18 4 * * * /must/not/disappear.sh\n"
        )

        result, after = self._install(initial)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)

    def test_installer_rejects_crontab_read_error(self):
        initial = "12 3 * * * /other/bot.sh\n"

        result, after = self._install(
            initial, list_error="permission denied"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)

    def test_installer_rejects_missing_service_when_crond_is_down(self):
        initial = "12 3 * * * /other/bot.sh\n"

        result, after = self._install(
            initial,
            crond_running=False,
            service_dir=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)

    def test_installer_can_start_crond_before_rewriting(self):
        initial = "12 3 * * * /other/bot.sh\n"

        result, installed = self._install(
            initial,
            crond_running=False,
            service_dir=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(initial.strip(), installed)
        self.assertIn("51 7-23 * * *", installed)

    def test_service_start_failure_leaves_crontab_unchanged(self):
        initial = "12 3 * * * /other/bot.sh\n"

        result, after = self._install(
            initial,
            crond_running=False,
            service_dir=True,
            sv_fail=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)

    def test_installer_uses_explicit_termux_service_root(self):
        script = (
            ROOT / "termux" / "install-monitor-cron.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('CROND_SVDIR="${SVDIR:-$TERMUX_PREFIX/var/service}"', script)
        self.assertIn('SVDIR="$CROND_SVDIR" sv up crond', script)


if __name__ == "__main__":
    unittest.main()
