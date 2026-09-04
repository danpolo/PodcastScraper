"""Repository-level safeguards for publishing the scraper source."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_generated_episode_data_is_ignored(self):
        ignored_paths = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("AI Thinkers podcast data/", ignored_paths.splitlines())


if __name__ == "__main__":
    unittest.main()
