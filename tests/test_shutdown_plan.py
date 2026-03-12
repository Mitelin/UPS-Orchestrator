from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.actions import LocalActionRunner, LocalCommandRunner, LocalActionResult
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
            self.assertEqual("run_pre_shutdown_script", decision.local_results[0].action)
            self.assertEqual("schedule_local_shutdown", decision.local_results[1].action)

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

    def test_onbatt_and_online_do_not_emit_server_eco_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            action_runner = LocalActionRunner(
                local_config=LocalServerActionConfig(self_shutdown_enabled=False),
                shutdown_config=CriticalShutdownConfig(),
            )
            engine = PowerPolicyEngine(state_manager, action_runner=action_runner)

            onbatt_decision = engine.evaluate_event(UPSPowerEvent.ONBATT)
            online_decision = engine.evaluate_event(UPSPowerEvent.ONLINE)

            self.assertEqual([], onbatt_decision.local_results)
            self.assertEqual([], online_decision.local_results)

    def test_lowbatt_plans_pre_shutdown_script_when_enabled(self) -> None:
        action_runner = LocalActionRunner(
            local_config=LocalServerActionConfig(
                self_shutdown_enabled=False,
                pre_shutdown_script_enabled=True,
                pre_shutdown_script_path="./scripts/pre-shutdown.sh",
            ),
            shutdown_config=CriticalShutdownConfig(),
        )

        result = action_runner.run_pre_shutdown_script()

        self.assertEqual("run_pre_shutdown_script", result.action)
        self.assertTrue(result.accepted)
        self.assertIn("planned", result.message)

    def test_pre_shutdown_script_executes_before_server_shutdown(self) -> None:
        class FakeCommandRunner(LocalCommandRunner):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], timeout_seconds: float):
                self.commands.append(command)
                return type("Completed", (), {"returncode": 0, "stdout": "saved", "stderr": ""})()

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "pre-shutdown.sh"
            script_path.write_text("#!/bin/sh\necho saved\n", encoding="utf-8")
            fake_runner = FakeCommandRunner()
            action_runner = LocalActionRunner(
                local_config=LocalServerActionConfig(
                    self_shutdown_enabled=True,
                    pre_shutdown_script_enabled=True,
                    pre_shutdown_script_path=str(script_path),
                ),
                shutdown_config=CriticalShutdownConfig(),
                command_runner=fake_runner,
            )

            result = action_runner.run_pre_shutdown_script(execute=True)

            self.assertTrue(result.accepted)
            self.assertEqual(["/bin/sh", str(script_path)], fake_runner.commands[0])


if __name__ == "__main__":
    unittest.main()