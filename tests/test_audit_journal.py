from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.actions import LocalActionRunner
from server.config import AuditJournalConfig, CriticalShutdownConfig, LocalServerActionConfig
from server.journal import AuditJournal
from server.main import main as server_main
from server.policy_engine import PowerPolicyEngine
from server.runtime import OrchestratorRuntime
from server.state_manager import OrchestratorStateManager
from server.ups_monitor import UPSObservedEvent, UPSStatusSnapshot
from shared.models import UPSPowerEvent


class FakeMonitor:
    def __init__(self, observations):
        self._observations = list(observations)

    def observe(self):
        return self._observations.pop(0)

    def poll_events(self):
        return self.observe()[1]


class AuditJournalTests(unittest.TestCase):
    def test_policy_decision_is_written_as_jsonl_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "audit.jsonl"
            journal = AuditJournal(AuditJournalConfig(enabled=True, path=journal_path))
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            action_runner = LocalActionRunner(LocalServerActionConfig(), CriticalShutdownConfig())

            decision = PowerPolicyEngine(state_manager, action_runner=action_runner).evaluate_event(UPSPowerEvent.ONBATT)
            journal.record_policy_decision(decision)

            lines = journal_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            record = json.loads(lines[0])
            self.assertEqual("policy_decision", record["type"])
            self.assertEqual("ON_BATTERY", record["payload"]["transition"]["current_state"])

    def test_runtime_writes_snapshot_and_event_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "audit.jsonl"
            journal = AuditJournal(AuditJournalConfig(enabled=True, path=journal_path))
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            runtime = OrchestratorRuntime(
                node_name="web-game-server",
                state_manager=state_manager,
                monitor=FakeMonitor(
                    [
                        (
                            UPSStatusSnapshot(status_tokens=("OB",), battery_charge_percent=90, runtime_seconds=1800),
                            [UPSObservedEvent(event=UPSPowerEvent.ONBATT, payload={"runtime_seconds": 1800})],
                        )
                    ]
                ),
                action_runner=LocalActionRunner(LocalServerActionConfig(), CriticalShutdownConfig()),
                apply_policy=True,
                journal=journal,
            )

            runtime.run_once()

            records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(["ups_snapshot", "observed_event", "policy_decision"], [record["type"] for record in records])

    def test_read_records_supports_type_filter_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "audit.jsonl"
            journal = AuditJournal(AuditJournalConfig(enabled=True, path=journal_path))

            journal.record_runtime_event("status", state="NORMAL", committed=False)
            journal.record_runtime_event("runtime_idle")
            journal.record_runtime_event("status", state="ON_BATTERY", committed=False)

            filtered = journal.read_records(record_type="status", limit=1)

            self.assertEqual(1, len(filtered))
            self.assertEqual("status", filtered[0]["type"])
            self.assertEqual("ON_BATTERY", filtered[0]["payload"]["state"])

    def test_journal_cli_prints_filtered_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "audit.jsonl"
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "[audit_journal]\n"
                f"enabled = true\npath = \"{journal_path.as_posix()}\"\n",
                encoding="utf-8",
            )
            journal = AuditJournal(AuditJournalConfig(enabled=True, path=journal_path))
            journal.record_runtime_event("status", state="NORMAL", committed=False)
            journal.record_runtime_event("runtime_idle")

            stdout = io.StringIO()
            with patch.object(sys, "argv", ["server.main", "--config", str(config_path), "journal", "--journal-type", "status", "--limit", "1"]):
                with patch("sys.stdout", stdout):
                    exit_code = server_main()

            self.assertEqual(0, exit_code)
            lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
            self.assertEqual(1, len(lines))
            record = json.loads(lines[0])
            self.assertEqual("status", record["type"])


if __name__ == "__main__":
    unittest.main()