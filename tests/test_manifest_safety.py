"""Manifest safety: corrupted prior data is never overwritten by recovery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_rss_feed import load_scraper_module


class ManifestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.rss_feed = load_scraper_module()

    def test_invalid_json_fails_closed_without_replacing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            path.write_text('{"episodes":', encoding="utf-8")
            before = path.read_bytes()
            with patch.object(self.rss_feed.config, "OUTPUT_DIR", Path(folder)), patch.object(
                self.rss_feed.config, "MANIFEST_PATH", path
            ):
                with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                    self.rss_feed.PodcastScraper()
            self.assertEqual(path.read_bytes(), before)

    def test_wrong_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            path.write_text('{"episodes":[]}', encoding="utf-8")
            with patch.object(self.rss_feed.config, "OUTPUT_DIR", Path(folder)), patch.object(
                self.rss_feed.config, "MANIFEST_PATH", path
            ):
                with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                    self.rss_feed.PodcastScraper()
            self.assertEqual(path.read_text(), '{"episodes":[]}')

    def test_successful_atomic_save_preserves_unicode_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            with patch.object(self.rss_feed.config, "OUTPUT_DIR", Path(folder)), patch.object(
                self.rss_feed.config, "MANIFEST_PATH", path
            ):
                scraper = self.rss_feed.PodcastScraper()
                content = {"episodes": {"yt-01": {
                    "title": "איך בונים agent",
                    "has_transcript": True,
                }}}
                scraper._save_manifest_raw(content)
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8")), content
                )
                self.assertFalse(list(Path(folder).glob(".manifest-*.tmp")))

    def test_failed_atomic_replace_keeps_previous_valid_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            original = {"episodes": {"yt-old": {
                "title": "Old episode", "has_description": True,
                "description_source": "spotify",
            }}}
            path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(self.rss_feed.config, "OUTPUT_DIR", Path(folder)), patch.object(
                self.rss_feed.config, "MANIFEST_PATH", path
            ):
                scraper = self.rss_feed.PodcastScraper()
                with patch.object(
                    self.rss_feed.os, "replace", side_effect=OSError("simulated disk error")
                ):
                    with self.assertRaisesRegex(OSError, "simulated disk error"):
                        scraper._save_manifest_raw({"episodes": {}})
                self.assertEqual(json.loads(path.read_text()), original)
                self.assertFalse(list(Path(folder).glob(".manifest-*.tmp")))

    def test_empty_manifest_only_on_first_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            with patch.object(self.rss_feed.config, "OUTPUT_DIR", Path(folder)), patch.object(
                self.rss_feed.config, "MANIFEST_PATH", path
            ):
                scraper = self.rss_feed.PodcastScraper()
                self.assertEqual(scraper.manifest, {"episodes": {}})
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
