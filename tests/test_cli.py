import json
import tempfile
import unittest
from pathlib import Path

import shorts
from product import approval_payload


def write_valid_episode(ep: Path) -> None:
    narration = "This complete narration is split into one exact visual beat."
    shorts.write_json(ep / "bits.json", {
        "meta": {"slug": ep.name, "title": "A Valid Short", "scene_count": 1,
                 "target_duration_seconds": 10, "bits_dirname": "generated"},
        "world": "One recurring character in a consistent blue room with no visible text or logos.",
        "bits": [{"n": 1, "vo": narration, "desc": "The character reveals the surprising result."}],
    })
    shorts.write_json(ep / "episode.json", {
        "topic": "A valid story", "title": "A Valid Short", "narration": narration,
        "description": "A complete description.", "tags": ["history"],
        "hashtags": ["#Shorts"], "scenes": ["The character reveals the surprising result."],
    })


class ProductionCliTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(shorts.slugify("One Real Short!"), "one-real-short")

    def test_approval_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            (ep / "storyboard").mkdir()
            board = ep / "storyboard/board_raw.png"
            board.write_bytes(b"v1")
            write_valid_episode(ep)
            shorts.write_json(ep / "storyboard/approved.json", approval_payload(ep, board, 1))
            self.assertTrue(shorts.approval_valid(ep))
            board.write_bytes(b"v2")
            self.assertFalse(shorts.approval_valid(ep))

    def test_approval_is_invalidated_by_plan_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            (ep / "storyboard").mkdir()
            board = ep / "storyboard/board_raw.png"
            board.write_bytes(b"v1")
            write_valid_episode(ep)
            shorts.write_json(ep / "storyboard/approved.json", approval_payload(ep, board, 1))
            bits = shorts.read_json(ep / "bits.json")
            bits["bits"][0]["desc"] = "A different visual after approval."
            shorts.write_json(ep / "bits.json", bits)
            self.assertFalse(shorts.approval_valid(ep))

    def test_status_routes_to_human_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "one"
            (ep / "storyboard").mkdir(parents=True)
            write_valid_episode(ep)
            (ep / "storyboard/contact-sheet.png").write_bytes(b"sheet")
            self.assertEqual(shorts.status_for(ep)["next_action"], "human_review_then_approve")


if __name__ == "__main__":
    unittest.main()
