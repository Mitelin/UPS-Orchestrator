from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.state_manager import OrchestratorStateManager
from shared.models import OrchestratorState, UPSPowerEvent


class CommitLogicTests(unittest.TestCase):
    def test_lowbatt_commits_shutdown_and_writes_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "shutdown.commit"
            manager = OrchestratorStateManager(marker)

            result = manager.handle_event(UPSPowerEvent.LOWBATT)

            self.assertTrue(result.changed)
            self.assertTrue(marker.exists())
            self.assertEqual(OrchestratorState.CRITICAL_SHUTDOWN, manager.state)
            self.assertTrue(result.committed)

    def test_online_is_ignored_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "shutdown.commit"
            manager = OrchestratorStateManager(marker)
            manager.handle_event(UPSPowerEvent.LOWBATT)

            result = manager.handle_event(UPSPowerEvent.ONLINE)

            self.assertFalse(result.changed)
            self.assertEqual(OrchestratorState.CRITICAL_SHUTDOWN, manager.state)
            self.assertTrue(result.committed)

    def test_existing_marker_restores_committed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "shutdown.commit"
            marker.write_text("committed\n", encoding="utf-8")

            manager = OrchestratorStateManager(marker)

            self.assertEqual(OrchestratorState.CRITICAL_SHUTDOWN, manager.state)
            self.assertTrue(manager.committed)

    def test_clear_commit_resets_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "shutdown.commit"
            manager = OrchestratorStateManager(marker)
            manager.handle_event(UPSPowerEvent.LOWBATT)

            manager.clear_commit()

            self.assertEqual(OrchestratorState.NORMAL, manager.state)
            self.assertFalse(marker.exists())
            self.assertFalse(manager.committed)


if __name__ == "__main__":
    unittest.main()
