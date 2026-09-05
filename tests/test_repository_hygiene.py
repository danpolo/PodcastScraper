"""Repository-level safeguards for publishing the scraper source."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_generated_episode_data_is_ignored(self):
        ignored_paths = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("AI Thinkers podcast data/", ignored_paths.splitlines())

    def test_workflow_does_not_commit_the_generated_dataset(self):
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "weekly_scrape.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn('git add "AI Thinkers podcast data/*"', workflow)
        self.assertNotIn("contents: write", workflow)


if __name__ == "__main__":
    unittest.main()
