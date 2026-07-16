import tempfile
import unittest
from pathlib import Path

import sys

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
import upload


class UploadGateTests(unittest.TestCase):
    def test_reviewed_package_is_the_metadata_source(self):
        body = upload._build_body({
            "title": "Reviewed title",
            "description": "Reviewed description",
            "hashtags": ["#Shorts"],
            "tags": ["history"],
        }, "private")
        self.assertEqual(body["snippet"]["title"], "Reviewed title")
        self.assertIn("Reviewed description", body["snippet"]["description"])
        self.assertEqual(body["status"]["privacyStatus"], "private")

    def test_upload_is_blocked_before_oauth_without_release_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = Path(tmp)
            (episode / "out").mkdir()
            (episode / "out/final.mp4").write_bytes(b"not-uploaded")
            with self.assertRaises(SystemExit):
                upload.upload(episode, "private")


if __name__ == "__main__":
    unittest.main()
