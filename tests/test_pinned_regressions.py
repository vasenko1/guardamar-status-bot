import json
import tempfile
import unittest
from pathlib import Path

from telegrambot.pinned import LEAF_MESSAGES, PinnedGuideState
from telegrambot.state import StateError


class PinnedRegressionTests(unittest.TestCase):
    def test_hospital_card_keeps_direction_heading(self):
        self.assertIn("<b>В больницу</b>", LEAF_MESSAGES["hospital"])
        self.assertIn("<b>Обратно</b>", LEAF_MESSAGES["hospital"])

    def test_uncertain_messages_must_remain_a_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pinned.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "chat_id": "-100123",
                        "messages": {},
                        "lines": {},
                        "obsolete_messages": [],
                        "uncertain_messages": "not-a-list",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StateError):
                PinnedGuideState(path).read_payload("-100123")


if __name__ == "__main__":
    unittest.main()
