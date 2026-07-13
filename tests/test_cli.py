import json
import tempfile
import unittest
from pathlib import Path

import shorts


class ProductionCliTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(shorts.slugify("One Real Short!"), "one-real-short")

    def test_approval_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            (ep / "storyboard").mkdir()
            board = ep / "storyboard/board_raw.png"
            board.write_bytes(b"v1")
            shorts.write_json(ep / "bits.json", {"bits": [{"n": 1}]})
            shorts.write_json(ep / "storyboard/approved.json", {
                "board_raw_sha256": shorts.sha256(board), "scene_count": 1,
            })
            self.assertTrue(shorts.approval_valid(ep))
            board.write_bytes(b"v2")
            self.assertFalse(shorts.approval_valid(ep))

    def test_status_routes_to_human_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "one"
            (ep / "storyboard").mkdir(parents=True)
            shorts.write_json(ep / "bits.json", {"meta": {}, "bits": [{"n": 1}]})
            (ep / "storyboard/contact-sheet.png").write_bytes(b"sheet")
            self.assertEqual(shorts.status_for(ep)["next_action"], "human_review_then_approve")


if __name__ == "__main__":
    unittest.main()
