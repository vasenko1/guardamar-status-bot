import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GuideTermuxTests(unittest.TestCase):
    def _install(self, initial):
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
                "FAKE_CRONTAB": str(crontab_state),
            })
            result = subprocess.run(
                ["sh", str(ROOT / "termux" / "install-guide-cron.sh")],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            return result, crontab_state.read_text(encoding="utf-8")

    def test_bathing_water_one_shot_is_small_and_source_specific(self):
        script = (
            ROOT / "termux" / "sync-bathing-water.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('LOG="$STATE_DIR/bathing-water.log"', script)
        self.assertIn("python -m telegrambot.guide bathing-water", script)
        self.assertNotIn("sync-guide.sh", script)

    def test_installer_has_one_evening_bathing_check_during_season_and_grace(self):
        script = (
            ROOT / "termux" / "install-guide-cron.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('"35 19 * 6-8 * $SH_BIN $BATHING"', script)
        self.assertIn('"35 19 1-30 9 * $SH_BIN $BATHING"', script)
        self.assertNotIn('"35 19 21-30 9 * $SH_BIN $BATHING"', script)

    def test_installer_is_idempotent_and_preserves_unrelated_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed = self._install(unrelated)
        second, reinstalled = self._install(installed)

        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(installed, reinstalled)
        self.assertIn(unrelated.strip(), installed)
        self.assertEqual(installed.count("sync-bathing-water.sh"), 2)
        self.assertEqual(installed.count("35 19 * 6-8 *"), 1)
        self.assertEqual(installed.count("35 19 1-30 9 *"), 1)
        self.assertEqual(installed.count("35 19 1-20 9 *"), 0)
        self.assertEqual(installed.count("2 9 * * *"), 1)

    def test_installer_rejects_unbalanced_managed_block(self):
        initial = (
            "12 3 * * * /other/bot.sh\n"
            "# BEGIN guardamar-status guide sync\n"
            "18 4 * * * /must/not/disappear.sh\n"
        )

        result, after = self._install(initial)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(after, initial)


if __name__ == "__main__":
    unittest.main()
