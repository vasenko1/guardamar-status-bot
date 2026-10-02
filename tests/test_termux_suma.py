import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SumaTermuxTests(unittest.TestCase):
    def test_suma_launcher_is_standalone_and_has_own_log(self):
        script = (ROOT / "termux" / "run-suma.sh").read_text(encoding="utf-8")

        self.assertIn('LOG="$PROJECT_DIR/state/suma.log"', script)
        self.assertIn("python -m telegrambot suma", script)
        self.assertNotIn("runtime-lock", script)
        self.assertNotIn("run-daily.sh", script)

    def test_installer_uses_0805_managed_cron_block(self):
        script = (
            ROOT / "termux" / "install-suma-cron.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('JOB="5 8 * * * $SH_BIN $RUNNER"', script)
        self.assertIn("# BEGIN guardamar-status suma", script)
        self.assertIn("# END guardamar-status suma", script)
        self.assertIn('crontab -l >"$CURRENT"', script)
        self.assertIn('crontab.before-suma', script)
        self.assertIn('sv up crond', script)
        self.assertNotIn("runtime-lock", script)

    def test_morning_lifecycle_no_longer_runs_suma(self):
        source = (
            ROOT / "src" / "telegrambot" / "__main__.py"
        ).read_text(encoding="utf-8")

        start = source.index('if command in {"run", "morning"}:')
        end = source.index(
            "existing = state.morning_record(now.date())",
            start,
        )
        morning_block = source[start:end]

        self.assertNotIn("run_suma", morning_block)
        self.assertIn(
            'if command == "suma":\n'
            '        return await run_suma(best_effort=False)',
            source,
        )


if __name__ == "__main__":
    unittest.main()
