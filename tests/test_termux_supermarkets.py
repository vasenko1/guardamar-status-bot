import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class TermuxTests(unittest.TestCase):
    def test_runner_is_independent_one_shot(self):
        script=(ROOT/'termux/run-supermarket-closures.sh').read_text()
        self.assertIn('state/supermarket-closures.log',script)
        self.assertIn('python -m telegrambot.supermarket_closures',script)
        self.assertNotIn('run-daily.sh',script)
    def test_installer_owns_only_0815_row(self):
        script=(ROOT/'termux/install-supermarket-closures-cron.sh').read_text()
        self.assertIn('JOB="15 8 * * * $SH_BIN $RUNNER"',script)
        self.assertIn('mktemp "$BACKUP_DIR/supermarket-current.XXXXXX"',script)
        self.assertNotIn('CURRENT=$(mktemp)\n',script)
        self.assertIn('# BEGIN guardamar-status supermarket closures',script)
        self.assertIn('crontab.before-supermarket-closures',script)
        self.assertNotIn('sv up crond',script)
if __name__=='__main__': unittest.main()
