import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
import build_bits2


class FakeResponse:
    def json(self):
        return {
            "candidates": [{
                "content": {"parts": [{
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(b"fake-png").decode(),
                    }
                }]}
            }]
        }


class GoogleProviderTests(unittest.TestCase):
    def test_gemini_key_is_sent_in_header_and_image_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "scene.png"
            with patch.object(build_bits2, "get_env", side_effect=lambda name: "test-key" if name == "GEMINI_API_KEY" else None), \
                 patch.object(build_bits2.requests, "post", return_value=FakeResponse()) as post:
                build_bits2._google_generate_image("prompt", [], dst, "gemini")
            self.assertEqual(dst.read_bytes(), b"fake-png")
            self.assertIn("gemini-3.1-flash-image:generateContent", post.call_args.args[0])
            self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
            self.assertEqual(
                post.call_args.kwargs["json"]["generationConfig"]["imageConfig"]["aspectRatio"],
                "9:16",
            )


if __name__ == "__main__":
    unittest.main()
