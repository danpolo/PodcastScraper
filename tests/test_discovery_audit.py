"""Pure offline tests of the coverage audit and RSS failure behavior."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from io import BytesIO

import discovery_audit as audit
from test_rss_feed import load_scraper_module


def row(ident, title, description_chars=50):
    return {"id": ident, "title": title, "description_chars": description_chars,
            "links": [], "url": "", "published": "", "audio_url": ""}


class CoverageTests(unittest.TestCase):
    def test_matches_identical_titles_not_source_order(self):
        sources = {
            "rss": [row("rss1", "איך בונים Agent"), row("rss2", "What is RAG?")],
            "youtube": [row("yt2", "What is RAG?"), row("yt1", "איך בונים Agent")],
            "spotify": [row("sp1", "איך בונים Agent")],
        }
        report = audit.build_report(sources)
        self.assertEqual(report["union_count_conservative"], 2)
        grouped = {
            tuple(sorted((e["source"], e["id"]) for e in g["entries"]))
            for g in report["groups"]
        }
        self.assertIn((("rss", "rss1"), ("spotify", "sp1"), ("youtube", "yt1")), grouped)
        self.assertIn((("rss", "rss2"), ("youtube", "yt2")), grouped)

    def test_ambiguous_or_missing_titles_are_not_guessed(self):
        sources = {"rss": [row("one", "LLM"), row("two", "LLM")],
                   "youtube": [row("yt", "LLM")],
                   "spotify": [row("s", "")]}
        report = audit.build_report(sources)
        self.assertEqual(report["union_count_conservative"], 4)
        self.assertTrue(any(x["reason"] == "multiple similar titles"
                            for x in report["ambiguous"]))
        self.assertTrue(any(x["reason"] == "empty title"
                            for x in report["ambiguous"]))

    def test_no_merge_across_unrelated_episodes(self):
        groups, _ = audit.match_sources({
            "rss": [row("r", "איך בונים agents בעברית")],
            "spotify": [row("s", "איך מנצחים בכדורגל")],
        })
        self.assertEqual(len(groups), 2)

    def test_failed_source_kept_as_explicit_error(self):
        report = audit.build_report(
            {"rss": [row("r", "Episode")], "youtube": [], "spotify": []},
            {"youtube": "403", "spotify": "timeout"})
        self.assertEqual(report["source_counts"]["rss"], 1)
        self.assertEqual(report["source_errors"]["youtube"], "403")


class Response:
    status = 200
    def __init__(self, content):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.content


class YouTubeRSSFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_rss_fails_run_instead_of_silent_success(self):
        rss_feed = load_scraper_module()
        html = b'{"externalId":"UCtest"}'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(rss_feed.config, "OUTPUT_DIR", root), patch.object(
                rss_feed.config, "MANIFEST_PATH", root / "manifest.json"
            ), patch.object(
                rss_feed.urllib.request, "urlopen",
                side_effect=[Response(html), RuntimeError("HTTP 403"),
                             RuntimeError("HTTP 403"), RuntimeError("HTTP 403")]
            ), patch.object(rss_feed.asyncio, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                    await rss_feed.PodcastScraper().run()

    async def test_empty_rss_fails_run_instead_of_silent_success(self):
        rss_feed = load_scraper_module()
        html = b'{"externalId":"UCtest"}'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(rss_feed.config, "OUTPUT_DIR", root), patch.object(
                rss_feed.config, "MANIFEST_PATH", root / "manifest.json"
            ), patch.object(
                rss_feed.urllib.request, "urlopen",
                side_effect=[Response(html), Response(b"<rss></rss>"),
                             Response(b"<rss></rss>"), Response(b"<rss></rss>")]
            ), patch.object(rss_feed.asyncio, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "no entries"):
                    await rss_feed.PodcastScraper().run()


if __name__ == "__main__":
    unittest.main()
