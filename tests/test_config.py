"""Configuration tests for source-only, reproducible scraper runs."""

import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ConfigTests(unittest.TestCase):
    def test_data_dir_environment_variable_places_output_under_named_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {"PODCASTSCRAPER_DATA_DIR": temporary_directory},
                clear=True,
            ):
                import config

                importlib.reload(config)

                self.assertEqual(
                    config.OUTPUT_DIR,
                    Path(temporary_directory) / "AI Thinkers podcast data",
                )
                self.assertEqual(
                    config.MANIFEST_PATH,
                    config.OUTPUT_DIR / "manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
