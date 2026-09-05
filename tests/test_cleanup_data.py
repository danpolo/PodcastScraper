"""Safety tests for the one-off local data cleanup command."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cleanup_data


class CleanupDataTests(unittest.TestCase):
    def test_cleanup_removes_orphans_but_preserves_manifest_files_and_trailer(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            manifest_path = data_directory / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "episodes": {
                            "video-1": {
                                "title": "Kept episode",
                                "has_description": True,
                                "has_transcript": True,
                                "last_updated": "2026-09-05T00:00:00+00:00",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            kept = data_directory / "Kept episode.md"
            stale = data_directory / "Stale episode.md"
            trailer = data_directory / "מה יש פה בעצם.md"
            for path in (kept, stale, trailer):
                path.write_text("content", encoding="utf-8")

            with patch.object(cleanup_data, "DATA_DIR", data_directory), patch.object(
                cleanup_data, "MANIFEST_PATH", manifest_path
            ):
                cleanup_data.cleanup()

            self.assertTrue(kept.exists())
            self.assertFalse(stale.exists())
            self.assertTrue(trailer.exists())

    def test_cleanup_returns_without_deleting_when_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            episode = data_directory / "Episode.md"
            episode.write_text("content", encoding="utf-8")

            output = io.StringIO()
            with patch.object(cleanup_data, "DATA_DIR", data_directory), patch.object(
                cleanup_data, "MANIFEST_PATH", data_directory / "manifest.json"
            ), contextlib.redirect_stdout(output):
                cleanup_data.cleanup()

            self.assertIn("Manifest not found.", output.getvalue())
            self.assertTrue(episode.exists())


if __name__ == "__main__":
    unittest.main()
