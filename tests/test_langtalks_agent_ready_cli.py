"""Offline agent-ready export has no provider API or feed side effects."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langtalks import bench


class AgentReadyCLITests(unittest.TestCase):
    def test_offline_export_writes_sync_json_markdown_no_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "test.asr.json"
            source.write_text(json.dumps({
                "episode_guid": "sample-guid", "episode_title": "Hebrew code",
                "provider": "offline_test", "source": "excerpt", "time_offset": 480,
                "text": "מריצים code review",
                "tokens": [{"text": "מריצים code review",
                            "start": 488.1, "end": 490.2}],
            }, ensure_ascii=False), encoding="utf-8")
            target = root / "ready"
            with patch.object(bench, "fetch_episodes") as feed, patch.object(
                bench.providers_mod, "get_provider"
            ) as api:
                bench.main([
                    "agent-ready", "--offline", "--asr-file", str(source),
                    "--output-dir", str(target),
                ])
                feed.assert_not_called()
                api.assert_not_called()
            item = json.loads(next(target.glob("*.transcript.json")).read_text())
            md = next(target.glob("*.transcript.md")).read_text()
            self.assertEqual(item["status"], "machine_draft")
            self.assertIn("code review", md)
            self.assertEqual(item["turns"][0]["speaker_id"], None)

    def test_offline_requires_input(self):
        with self.assertRaisesRegex(SystemExit, "asr-file"):
            bench.main(["agent-ready", "--offline"])


if __name__ == "__main__":
    unittest.main()
