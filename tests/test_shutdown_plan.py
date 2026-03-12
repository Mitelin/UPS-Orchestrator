from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.actions import LocalActionRunner
from server.config import CriticalShutdownConfig, LocalServerActionConfig
from server.policy_engine import PowerPolicyEngine
from server.state_manager import OrchestratorStateManager
from shared.models import UPSPowerEvent


class ShutdownPlanTests(unittest.TestCase):
    def test_lowbatt_builds_ordered_shutdown_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            action_runner = LocalActionRunner(
                local_config=LocalServerActionConfig(self_shutdown_enabled=False),
                shutdown_config=CriticalShutdownConfig(
                    include_windows_client_shutdown=True,
                    warning_delay_seconds=0,
                    nas_shutdown_delay_seconds=5,
                    raspberry_shutdown_delay_seconds=15,
                    windows_shutdown_delay_seconds=30,
                    server_shutdown_delay_seconds=45,
                ),
            )

            decision = PowerPolicyEngine(state_manager, action_runner=action_runner).evaluate_event(UPSPowerEvent.LOWBATT)

            self.assertIsNotNone(decision.shutdown_plan)
            self.assertEqual(
                ["critical_warning", "shutdown_nas", "shutdown_raspberry", "shutdown_main_pc", "shutdown_orchestrator"],
                [step.step_name for step in decision.shutdown_plan.steps],
            )
            self.assertEqual("web-game-server", decision.shutdown_plan.steps[-1].target)
            self.assertEqual("schedule_local_shutdown", decision.local_results[0].action)

    def test_lowbatt_plan_omits_windows_shutdown_when_disabled(self) -> None:
        action_runner = LocalActionRunner(
            local_config=LocalServerActionConfig(self_shutdown_enabled=False),
            shutdown_config=CriticalShutdownConfig(include_windows_client_shutdown=False),
        )

        plan = action_runner.build_critical_shutdown_plan()

        self.assertEqual(
            ["critical_warning", "shutdown_nas", "shutdown_raspberry", "shutdown_orchestrator"],
            [step.step_name for step in plan.steps],
        )

    def test_onbatt_and_online_emit_local_eco_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            action_runner = LocalActionRunner(
                local_config=LocalServerActionConfig(self_shutdown_enabled=False),
                shutdown_config=CriticalShutdownConfig(),
            )
            engine = PowerPolicyEngine(state_manager, action_runner=action_runner)

            onbatt_decision = engine.evaluate_event(UPSPowerEvent.ONBATT)
            online_decision = engine.evaluate_event(UPSPowerEvent.ONLINE)

            self.assertEqual("enter_local_eco_mode", onbatt_decision.local_results[0].action)
            self.assertEqual("exit_local_eco_mode", online_decision.local_results[0].action)


if __name__ == "__main__":
    unittest.main()