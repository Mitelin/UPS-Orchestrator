from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.config import ServerConfig


class ServerConfigTests(unittest.TestCase):
    def test_load_from_toml_reads_nested_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "[server]\n"
                "node_name = \"lab-server\"\n"
                "observe_only = false\n"
                "[dispatch_runtime]\n"
                "retry_attempts = 4\n"
                "poll_interval_seconds = 2.5\n"
                "[audit_journal]\n"
                "enabled = true\n"
                "path = \"logs/audit.jsonl\"\n"
                "[windows_client]\n"
                "enabled = true\n"
                "base_url = \"http://main-pc.local:8765\"\n"
                "[nut_monitor]\n"
                "enabled = true\n"
                "power_state_debounce_polls = 2\n"
                "[nas]\n"
                "enabled = true\n"
                "host = \"nas.local\"\n",
                encoding="utf-8",
            )

            config = ServerConfig.from_toml(config_path)

            self.assertEqual("lab-server", config.node_name)
            self.assertFalse(config.observe_only)
            self.assertEqual(4, config.dispatch_runtime.retry_attempts)
            self.assertEqual(2.5, config.dispatch_runtime.poll_interval_seconds)
            self.assertTrue(config.audit_journal.enabled)
            self.assertEqual(Path("logs/audit.jsonl"), config.audit_journal.path)
            self.assertTrue(config.windows_client.enabled)
            self.assertEqual("http://main-pc.local:8765", config.windows_client.base_url)
            self.assertTrue(config.nut_monitor.enabled)
            self.assertEqual(2, config.nut_monitor.power_state_debounce_polls)
            self.assertTrue(config.nas.enabled)
            self.assertEqual("nas.local", config.nas.host)

    def test_load_applies_env_overrides_over_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "[server]\n"
                "node_name = \"from-file\"\n"
                "[dispatch_runtime]\n"
                "retry_attempts = 1\n"
                "[windows_client]\n"
                "enabled = false\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "UPS_ORCHESTRATOR_NODE_NAME": "from-env",
                    "UPS_ORCHESTRATOR_DISPATCH_RETRY_ATTEMPTS": "3",
                    "UPS_ORCHESTRATOR_WINDOWS_CLIENT_ENABLED": "true",
                    "UPS_ORCHESTRATOR_AUDIT_JOURNAL_ENABLED": "true",
                },
                clear=False,
            ):
                config = ServerConfig.load(config_path)

            self.assertEqual("from-env", config.node_name)
            self.assertEqual(3, config.dispatch_runtime.retry_attempts)
            self.assertTrue(config.windows_client.enabled)
            self.assertTrue(config.audit_journal.enabled)

    def test_load_without_file_uses_defaults_and_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPS_ORCHESTRATOR_RASPBERRY_ENABLED": "true",
                "UPS_ORCHESTRATOR_POLL_INTERVAL_SECONDS": "2",
            },
            clear=False,
        ):
            config = ServerConfig.load()

        self.assertTrue(config.raspberry.enabled)
        self.assertEqual(2.0, config.dispatch_runtime.poll_interval_seconds)


if __name__ == "__main__":
    unittest.main()