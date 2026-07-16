import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import shorts
from product import approval_payload, qa_episode, write_build_manifest, write_json
from test_cli import write_valid_episode


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class QaIntegrationTests(unittest.TestCase):
    def test_synthetic_vertical_video_passes_automated_qa(self):
        shorts.EPISODES.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=shorts.EPISODES) as tmp:
            ep = Path(tmp)
            write_valid_episode(ep)
            storyboard = ep / "storyboard"
            storyboard.mkdir()
            board = storyboard / "board_raw.png"
            Image.new("RGB", (160, 90), "navy").save(board)
            Image.new("RGB", (160, 90), "navy").save(storyboard / "contact-sheet.png")
            write_json(storyboard / "approved.json", approval_payload(ep, board, 1))

            (ep / "generated").mkdir()
            (ep / "scenes").mkdir()
            Image.new("RGB", (1080, 1920), "navy").save(ep / "generated/bit_01.png")
            Image.new("RGB", (1080, 1920), "navy").save(ep / "scenes/scene_1.png")
            (ep / "voice.mp3").write_bytes(b"sealed-test-voice")
            write_json(ep / "words.json", {
                "audio_duration": 2.0,
                "words": [{"text": "This", "start": 0.1, "end": 0.5}],
            })
            (ep / "out").mkdir()
            write_json(ep / "out/props.json", {"episode": ep.name})
            final = ep / "out/final.mp4"
            result = subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=60",
                "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
                "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(final),
            ], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            write_build_manifest(ep)

            report = qa_episode(ep)
            self.assertTrue(report["passed"], report["errors"])
            self.assertTrue((ep / "qa/midpoints-contact-sheet.jpg").exists())


if __name__ == "__main__":
    unittest.main()
