import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeekendTermuxTests(unittest.TestCase):
    def _install(
        self,
        initial,
        *,
        crond_running=True,
        service_available=True,
        crontab_read_ok=True,
        sv_start_ok=True,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            crontab_state = root / "crontab"
            crontab_state.write_text(initial, encoding="utf-8")
            crond_state = root / "crond-running"
            crond_state.write_text(
                "1" if crond_running else "0",
                encoding="utf-8",
            )
            prefix = root / "prefix"
            if service_available:
                (prefix / "var" / "service" / "crond").mkdir(
                    parents=True,
                    exist_ok=True,
                )
            (commands / "crontab").write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -l ]; then\n"
                "  if [ \"$FAKE_CRONTAB_READ_OK\" != 1 ]; then\n"
                "    echo 'permission denied' >&2\n"
                "    exit 1\n"
                "  fi\n"
                "  cat \"$FAKE_CRONTAB\"\n"
                "elif [ -n \"${1-}\" ] && [ \"$1\" != - ]; then\n"
                "  cat \"$1\" >\"$FAKE_CRONTAB\"\n"
                "else\n"
                "  cat >\"$FAKE_CRONTAB\"\n"
                "fi\n",
                encoding="utf-8",
            )
            (commands / "pgrep").write_text(
                "#!/bin/sh\n"
                "[ \"${1-}\" = -x ] || exit 2\n"
                "[ \"${2-}\" = crond ] || exit 2\n"
                "[ \"$(cat \"$FAKE_CROND_STATE\")\" = 1 ]\n",
                encoding="utf-8",
            )
            (commands / "sv").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"SVDIR=$SVDIR $*\" >>\"$FAKE_SV_LOG\"\n"
                "if [ \"$FAKE_SV_START_OK\" != 1 ]; then\n"
                "  exit 1\n"
                "fi\n"
                "echo 1 >\"$FAKE_CROND_STATE\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            for command in commands.iterdir():
                command.chmod(0o755)
            environment = dict(os.environ)
            environment.pop("SVDIR", None)
            environment.update({
                "HOME": str(root / "home"),
                "PATH": f"{commands}:/usr/bin:/bin",
                "FAKE_CRONTAB": str(crontab_state),
                "FAKE_CROND_STATE": str(crond_state),
                "FAKE_SV_LOG": str(root / "sv.log"),
                "FAKE_CRONTAB_READ_OK": "1" if crontab_read_ok else "0",
                "FAKE_SV_START_OK": "1" if sv_start_ok else "0",
                "PREFIX": str(prefix),
            })
            result = subprocess.run(
                ["sh", str(ROOT / "termux" / "install-weekend-cron.sh")],
                text=True, capture_output=True, env=environment, check=False,
            )
            sv_log = root / "sv.log"
            return (
                result,
                crontab_state.read_text(encoding="utf-8"),
                sv_log.read_text(encoding="utf-8") if sv_log.exists() else "",
            )

    def test_installer_removes_legacy_unmanaged_weekend_jobs(self):
        weekend = ROOT / "termux" / "run-weekend.sh"
        legacy = (
            f"0,20 18 * * 5 {weekend}\n"
            f"0 19 * * 5 {weekend}\n"
        )

        result, installed, _ = self._install(legacy)

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("0,20 18 * * 5", installed)
        self.assertNotIn("0 19 * * 5", installed)
        self.assertIn("15 19 * * 5", installed)
        self.assertIn("15 20 * * 5", installed)
        self.assertIn("25 19 * * 0-4", installed)
        self.assertIn("25 20 * * 0-4", installed)
        self.assertEqual(installed.count("run-tomorrow-events.sh"), 2)
        self.assertEqual(installed.count("run-event-registration.sh"), 2)
        self.assertIn("47 12 * * *", installed)
        self.assertIn("47 13 * * *", installed)

    def test_installer_upgrades_existing_managed_tomorrow_job(self):
        weekend = ROOT / "termux" / "run-weekend.sh"
        tomorrow = ROOT / "termux" / "run-tomorrow-events.sh"
        initial = (
            "# BEGIN guardamar-status weekend digest\n"
            "CRON_TZ=Europe/Madrid\n"
            f"15 19 * * 5 {weekend} --fresh\n"
            f"15 20 * * 5 {weekend}\n"
            f"25 19 * * 0-4 /bin/sh {tomorrow}\n"
            "# END guardamar-status weekend digest\n"
        )

        result, installed, _ = self._install(initial)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(installed.count("25 19 * * 0-4"), 1)
        self.assertEqual(installed.count("25 20 * * 0-4"), 1)
        self.assertEqual(installed.count("run-tomorrow-events.sh"), 2)
        self.assertEqual(installed.count("run-event-registration.sh"), 2)
        self.assertIn("47 12 * * *", installed)
        self.assertIn("47 13 * * *", installed)

    def test_installer_is_idempotent_and_preserves_other_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed, _ = self._install(unrelated)
        second, reinstalled, _ = self._install(installed)

        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(installed, reinstalled)
        self.assertIn(unrelated.strip(), installed)
        self.assertEqual(installed.count("15 19 * * 5"), 1)
        self.assertIn("run-weekend.sh --fresh", installed)
        self.assertEqual(installed.count("15 20 * * 5"), 1)
        self.assertEqual(installed.count("25 19 * * 0-4"), 1)
        self.assertEqual(installed.count("25 20 * * 0-4"), 1)
        self.assertEqual(installed.count("run-tomorrow-events.sh"), 2)
        self.assertEqual(installed.count("run-event-registration.sh"), 2)
        self.assertIn("47 12 * * *", installed)
        self.assertIn("47 13 * * *", installed)
        self.assertNotIn("0,20 18 * * 5", installed)
        self.assertIn("# BEGIN guardamar-status weekend digest", installed)

    def test_installer_sets_explicit_svdir_in_noninteractive_shell(self):
        result, installed, sv_log = self._install(
            "",
            crond_running=False,
            service_available=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("47 12 * * *", installed)
        self.assertIn("up crond", sv_log)
        self.assertIn("/var/service", sv_log)

    def test_installer_does_not_change_crontab_when_service_start_fails(self):
        initial = "12 3 * * * /other/bot.sh\n"
        result, installed, sv_log = self._install(
            initial,
            crond_running=False,
            service_available=True,
            sv_start_ok=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(installed, initial)
        self.assertIn("up crond", sv_log)
        self.assertIn("crontab не изменён", result.stderr)

    def test_installer_fails_closed_on_real_crontab_read_error(self):
        initial = "12 3 * * * /other/bot.sh\n"
        result, installed, sv_log = self._install(
            initial,
            crond_running=True,
            service_available=True,
            crontab_read_ok=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(installed, initial)
        self.assertEqual(sv_log, "")
        self.assertIn("безопасно прочитать", result.stderr)

    def test_installer_does_not_require_service_directory_when_crond_is_already_running(self):
        result, installed, sv_log = self._install(
            "",
            crond_running=True,
            service_available=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("47 12 * * *", installed)
        self.assertEqual(sv_log, "")
        self.assertIn("crond: running", result.stdout)

    def test_installer_fails_before_crontab_change_when_crond_is_unavailable(self):
        initial = "12 3 * * * /other/bot.sh\n"
        result, installed, sv_log = self._install(
            initial,
            crond_running=False,
            service_available=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(installed, initial)
        self.assertEqual(sv_log, "")
        self.assertIn("service directory", result.stderr)

    def test_fresh_weekend_refreshes_convega_source(self):
        content = (ROOT / "termux" / "run-weekend.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('sh "$SCRIPT_DIR/sync-convega.sh"', content)
        self.assertIn("WARNING CONVEGA refresh failed", content)

    def test_registration_wrapper_checks_freshness_before_source_sync(self):
        content = (ROOT / "termux" / "run-event-registration.sh").read_text(
            encoding="utf-8"
        )

        freshness = content.index(
            "python -m telegrambot.convega fresh-access"
        )
        source_sync = content.index('sh "$SCRIPT_DIR/sync-convega.sh"')
        lifecycle = content.index(
            "python -m telegrambot.event_registration_notifications"
        )
        self.assertLess(freshness, source_sync)
        self.assertLess(source_sync, lifecycle)

