from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.state_manager import OrchestratorStateManager
from shared.models import OrchestratorState, UPSPowerEvent


class StateMachineTests(unittest.TestCase):
    def test_onbatt_transitions_normal_to_on_battery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")

            result = manager.handle_event(UPSPowerEvent.ONBATT)

            self.assertTrue(result.changed)
            self.assertEqual(OrchestratorState.ON_BATTERY, manager.state)
            self.assertFalse(result.committed)

    def test_online_returns_to_normal_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            manager.handle_event(UPSPowerEvent.ONBATT)

            result = manager.handle_event(UPSPowerEvent.ONLINE)

            self.assertTrue(result.changed)
            self.assertEqual(OrchestratorState.NORMAL, manager.state)
            self.assertFalse(result.committed)

    def test_duplicate_onbatt_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            manager.handle_event(UPSPowerEvent.ONBATT)

            result = manager.handle_event(UPSPowerEvent.ONBATT)

            self.assertFalse(result.changed)
            self.assertEqual(OrchestratorState.ON_BATTERY, manager.state)


if __name__ == "__main__":
    unittest.main()
