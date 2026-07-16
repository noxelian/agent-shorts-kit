import tempfile
import unittest
from pathlib import Path

import shorts
from product import (
    approval_payload,
    approve_release,
    release_approval_valid,
    sha256_file,
    validate_episode,
    write_build_manifest,
    write_json,
    write_release_package,
)

from test_cli import write_valid_episode


class ProductValidationTests(unittest.TestCase):
    def test_valid_plan_covers_narration_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            write_valid_episode(ep)
            report = validate_episode(ep)
            self.assertTrue(report["valid"], report["errors"])

    def test_placeholders_and_partial_voice_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            write_valid_episode(ep)
            episode = shorts.read_json(ep / "episode.json")
            episode["narration"] = "Replace with the reviewed final narration."
            shorts.write_json(ep / "episode.json", episode)
            report = validate_episode(ep)
            self.assertFalse(report["valid"])
            self.assertTrue(any("placeholder" in item for item in report["errors"]))
            self.assertTrue(any("verbatim" in item for item in report["errors"]))

    def test_release_approval_is_invalidated_when_final_changes(self):
        shorts.EPISODES.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=shorts.EPISODES) as tmp:
            ep = Path(tmp)
            write_valid_episode(ep)
            storyboard = ep / "storyboard"
            storyboard.mkdir()
            board = storyboard / "board_raw.png"
            board.write_bytes(b"board")
            (storyboard / "contact-sheet.png").write_bytes(b"sheet")
            write_json(storyboard / "approved.json", approval_payload(ep, board, 1))
            (ep / "generated").mkdir()
            (ep / "generated/bit_01.png").write_bytes(b"generated")
            (ep / "scenes").mkdir()
            (ep / "scenes/scene_1.png").write_bytes(b"scene")
            (ep / "out").mkdir()
            (ep / "voice.mp3").write_bytes(b"voice")
            write_json(ep / "words.json", {"words": [{"text": "This", "start": 0, "end": 1}]})
            write_json(ep / "out/props.json", {"episode": ep.name})
            final = ep / "out/final.mp4"
            final.write_bytes(b"final-v1")
            write_build_manifest(ep)
            write_json(ep / "qa/qa-report.json", {
                "passed": True, "metrics": {"final_sha256": sha256_file(final)},
            })
            write_release_package(ep, "tomorrow 17:30", "UTC", "English", "Education", "not made for kids")
            approve_release(ep, "private")
            self.assertTrue(release_approval_valid(ep, "private")[0])
            final.write_bytes(b"final-v2")
            self.assertFalse(release_approval_valid(ep, "private")[0])


if __name__ == "__main__":
    unittest.main()
