import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import shorts


class CliTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(shorts.slugify("Hello, AI Shorts!"), "hello-ai-shorts")

    def test_approval_is_bound_to_board_and_scene_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            (ep / "storyboard").mkdir()
            (ep / "storyboard" / "contact-sheet.png").write_bytes(b"board-v1")
            (ep / "episode.json").write_text(json.dumps({"scenes": ["a", "b"]}))
            shorts.write_json(
                ep / "storyboard" / "approved.json",
                {
                    "contact_sheet_sha256": shorts.sha256(ep / "storyboard" / "contact-sheet.png"),
                    "scene_count": 2,
                },
            )
            self.assertTrue(shorts._approval_valid(ep))
            (ep / "storyboard" / "contact-sheet.png").write_bytes(b"board-v2")
            self.assertFalse(shorts._approval_valid(ep))

    def test_status_requests_human_review_after_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "one"
            (ep / "storyboard").mkdir(parents=True)
            (ep / "storyboard" / "contact-sheet.png").write_bytes(b"board")
            result = shorts.status_for(ep)
            self.assertEqual(result["next_action"], "human_review_then_approve")


if __name__ == "__main__":
    unittest.main()

