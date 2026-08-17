import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EarthquakeTermuxTests(unittest.TestCase):
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

        self.assertIn('DEPLOY_LOCK="$PROJECT_DIR/state/deploy.lock"', script)
        self.assertIn('if [ -d "$DEPLOY_LOCK" ]', script)
        self.assertIn('"$(wc -c < "$LOG")" -gt 1048576', script)
        self.assertIn("python -m telegrambot monitor-earthquakes", script)


if __name__ == "__main__":
    unittest.main()
