import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HidraquaTermuxTests(unittest.TestCase):
    def _install(self, initial):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            crontab_state = root / "crontab"
            crontab_state.write_text(initial, encoding="utf-8")
            (commands / "crontab").write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -l ]; then cat \"$FAKE_CRONTAB\"; "
                "else cat >\"$FAKE_CRONTAB\"; fi\n",
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
                ["sh", str(ROOT / "termux" / "install-hidraqua-cron.sh")],
                text=True, capture_output=True, env=environment, check=False,
            )
            return result, crontab_state.read_text(encoding="utf-8")

    def test_installer_is_idempotent_and_preserves_other_jobs(self):
        unrelated = "12 3 * * * /other/bot.sh\n"
        first, installed = self._install(unrelated)
        second, reinstalled = self._install(installed)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(installed, reinstalled)
        self.assertIn(unrelated.strip(), installed)
        self.assertEqual(installed.count("*/30 * * * *"), 1)
        self.assertIn("# BEGIN guardamar-status hidraqua monitor", installed)


if __name__ == "__main__":
    unittest.main()
