import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeekendTermuxTests(unittest.TestCase):
    def _install(self, initial):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            crontab_state = root / "crontab"
            crontab_state.write_text(initial, encoding="utf-8")
            (commands / "crontab").write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -l ]; then\n"
                "  cat \"$FAKE_CRONTAB\"\n"
                "elif [ -n \"${1-}\" ] && [ \"$1\" != - ]; then\n"
                "  cat \"$1\" >\"$FAKE_CRONTAB\"\n"
                "else\n"
                "  cat >\"$FAKE_CRONTAB\"\n"
                "fi\n",
                encoding="utf-8",
            )
            (commands / "sv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            for command in commands.iterdir():
                command.chmod(0o755)
            environment = dict(os.environ)
            environment.update({
                "HOME": str(root / "home"),
                "PATH": f"{commands}:/usr/bin:/bin",
                "FAKE_CRONTAB": str(crontab_state),
            })
            result = subprocess.run(
                ["sh", str(ROOT / "termux" / "install-weekend-cron.sh")],
                text=True, capture_output=True, env=environment, check=False,
            )
            return result, crontab_state.read_text(encoding="utf-8")

    def test_installer_removes_legacy_unmanaged_weekend_jobs(self):
        weekend = ROOT / "termux" / "run-weekend.sh"
        legacy = (
            f"0,20 18 * * 5 {weekend}\n"
            f"0 19 * * 5 {weekend}\n"
        )

        result, installed = self._install(legacy)

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

        result, installed = self._install(initial)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(installed.count("25 19 * * 0-4"), 1)
        self.assertEqual(installed.count("25 20 * * 0-4"), 1)
        self.assertEqual(installed.count("run-tomorrow-events.sh"), 2)
        self.assertEqual(installed.count("run-event-registration.sh"), 2)
        self.assertIn("47 12 * * *", installed)
        self.assertIn("47 13 * * *", installed)

    def test_installer_is_idempotent_and_preserves_other_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed = self._install(unrelated)
        second, reinstalled = self._install(installed)

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
            "python -m telegrambot.convega fresh-today"
        )
        source_sync = content.index('sh "$SCRIPT_DIR/sync-convega.sh"')
        lifecycle = content.index(
            "python -m telegrambot.event_registration_notifications"
        )
        self.assertLess(freshness, source_sync)
        self.assertLess(source_sync, lifecycle)

