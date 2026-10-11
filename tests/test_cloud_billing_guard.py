"""Cloud API guard must stop accidental provider billing before any I/O."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langtalks import bench


class CloudBillingGuardTests(unittest.TestCase):
    def test_cloud_asr_does_not_fetch_or_bill_without_opt_in(self):
        with patch.object(bench, "fetch_episodes") as feed, patch.object(
            bench.providers_mod, "available"
        ) as available, patch.object(
            bench.providers_mod, "get_provider"
        ) as provider:
            with self.assertRaisesRegex(SystemExit, "No requests sent"):
                bench.cmd_transcribe(SimpleNamespace(episodes=["71"], provider=None))
            feed.assert_not_called()
            available.assert_not_called()
            provider.assert_not_called()

    def test_cli_requires_explicit_opt_in(self):
        with patch.object(bench, "fetch_episodes") as feed:
            with self.assertRaisesRegex(SystemExit, "allow-cloud-api"):
                bench.main(["transcribe", "71", "--provider", "groq_v3"])
            feed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
