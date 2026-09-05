"""Regression tests for feed data handling without network access."""

import importlib
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import patch


def load_scraper_module():
    """Import the scraper with optional runtime integrations replaced by placeholders."""
    if "rss_feed" in sys.modules:
        return sys.modules["rss_feed"]

    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = object()
    async_api.Browser = object
    async_api.Route = object

    playwright = ModuleType("playwright")
    transcript_api = ModuleType("youtube_transcript_api")
    transcript_api.YouTubeTranscriptApi = object
    proxies = ModuleType("youtube_transcript_api.proxies")
    proxies.WebshareProxyConfig = object
    formatters = ModuleType("youtube_transcript_api.formatters")
    formatters.TextFormatter = object

    replacements = {
        "playwright": playwright,
        "playwright.async_api": async_api,
        "youtube_transcript_api": transcript_api,
        "youtube_transcript_api.proxies": proxies,
        "youtube_transcript_api.formatters": formatters,
    }
    with patch.dict(sys.modules, replacements), patch(
        "logging.FileHandler", return_value=logging.NullHandler()
    ), warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="feedparser")
        return importlib.import_module("rss_feed")


class FeedDataTests(unittest.TestCase):
    def test_rss_entry_conversion_preserves_video_metadata_and_summary(self):
        rss_feed = load_scraper_module()
        scraper = rss_feed.PodcastScraper()
        feed = SimpleNamespace(
            entries=[
                SimpleNamespace(
                    id="yt:video-123",
                    title="Episode title",
                    link="https://www.youtube.com/watch?v=video-123",
                    published="2026-09-05T08:00:00+00:00",
                    get=lambda key, default=None: "RSS description" if key == "summary" else default,
                )
            ]
        )

        entries = scraper._entries_from_rss(feed)

        self.assertEqual(entries[0].id, "video-123")
        self.assertEqual(entries[0].description, "RSS description")

    def test_legacy_manifest_marks_long_existing_descriptions_as_spotify(self):
        rss_feed = load_scraper_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            manifest_path = output_directory / "manifest.json"
            title = "Full episode"
            (output_directory / "Full episode.md").write_text(
                "# Full episode\n\n## Description\n" + "x" * 400 + "\n",
                encoding="utf-8",
            )
            manifest = {"episodes": {"video-1": {"title": title, "has_description": True}}}

            with patch.object(rss_feed.config, "OUTPUT_DIR", output_directory), patch.object(
                rss_feed.config, "MANIFEST_PATH", manifest_path
            ):
                scraper = rss_feed.PodcastScraper()
                scraper._backfill_description_source(manifest)

            self.assertEqual(manifest["episodes"]["video-1"]["description_source"], "spotify")
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["episodes"]["video-1"]["description_source"], "spotify")

    def test_legacy_short_is_requeued_for_youtube_description(self):
        rss_feed = load_scraper_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "manifest.json"
            manifest = {
                "episodes": {
                    "short-1": {
                        "title": "A short #substack #shorts",
                        "has_description": True,
                        "description_source": "spotify",
                    }
                }
            }

            with patch.object(rss_feed.config, "OUTPUT_DIR", Path(temporary_directory)), patch.object(
                rss_feed.config, "MANIFEST_PATH", manifest_path
            ):
                scraper = rss_feed.PodcastScraper()
                scraper._backfill_description_source(manifest)

            entry = manifest["episodes"]["short-1"]
            self.assertEqual(entry["description_source"], "youtube_rss")
            self.assertFalse(entry["has_description"])

    def test_transcript_cleaning_removes_boilerplate_and_avoided_speakers(self):
        rss_feed = load_scraper_module()
        scraper = rss_feed.PodcastScraper()

        cleaned = scraper._clean_transcript(
            "Before\nThis transcript was generated automatically. Its accuracy may vary.\n"
            "Useful transcript\nדובר או דוברת מס 1\nMore episodes like this\nAfter"
        )

        self.assertEqual(cleaned, "Useful transcript")


class ResourceBlockingTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_blocker_aborts_images_and_continues_documents(self):
        rss_feed = load_scraper_module()
        scraper = rss_feed.PodcastScraper()

        image_route = SimpleNamespace(
            request=SimpleNamespace(resource_type="image"),
            abort=__import__("unittest").mock.AsyncMock(),
            continue_=__import__("unittest").mock.AsyncMock(),
        )
        document_route = SimpleNamespace(
            request=SimpleNamespace(resource_type="document"),
            abort=__import__("unittest").mock.AsyncMock(),
            continue_=__import__("unittest").mock.AsyncMock(),
        )

        await scraper._block_resources(image_route)
        await scraper._block_resources(document_route)

        image_route.abort.assert_awaited_once()
        image_route.continue_.assert_not_awaited()
        document_route.continue_.assert_awaited_once()
        document_route.abort.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
