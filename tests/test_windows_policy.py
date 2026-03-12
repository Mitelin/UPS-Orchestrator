from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from client_windows.config import WindowsClientConfig
from client_windows.listener import WindowsClientListener
from client_windows.power_actions import PowerActionResult, PowerActionRunner, WindowsCommandRunner
from client_windows.state_manager import WindowsClientStateManager
from shared.models import UPSPowerEvent


class FakePowerActionRunner(PowerActionRunner):
    def __init__(self) -> None:
        super().__init__(WindowsClientConfig())
        self.scheduled_shutdowns: list[tuple[int, str]] = []

    def schedule_shutdown(self, *, delay_seconds: int, command: str, execute: bool = False) -> PowerActionResult:
        self.scheduled_shutdowns.append((delay_seconds, command))
        return PowerActionResult(
            action="schedule_shutdown",
            accepted=True,
            message=f"Windows shutdown planned for +{delay_seconds}s using command: {command}",
        )


class WindowsPolicyTests(unittest.TestCase):
    def test_lowbatt_can_schedule_shutdown_when_enabled(self) -> None:
        power_actions = FakePowerActionRunner()
        listener = WindowsClientListener(
            config=WindowsClientConfig(
                shared_token="secret-token",
                allowed_hosts={"127.0.0.1"},
                lowbatt_shutdown_enabled=True,
                lowbatt_shutdown_delay_seconds=90,
                shutdown_command="shutdown /s /t 90 /f",
            ),
            state_manager=WindowsClientStateManager(),
            power_actions=power_actions,
        )

        response = listener.handle_event(UPSPowerEvent.LOWBATT, token="secret-token", source_host="127.0.0.1")

        self.assertEqual("accepted", response.status)
        self.assertTrue(response.state["critical_shutdown_pending"])
        self.assertTrue(response.state["shutdown_scheduled"])
        self.assertEqual(90, response.state["shutdown_delay_seconds"])
        self.assertEqual([(90, "shutdown /s /t 90 /f")], power_actions.scheduled_shutdowns)

    def test_lowbatt_without_shutdown_policy_does_not_schedule_shutdown(self) -> None:
        power_actions = FakePowerActionRunner()
        listener = WindowsClientListener(
            config=WindowsClientConfig(shared_token="secret-token", allowed_hosts={"127.0.0.1"}),
            state_manager=WindowsClientStateManager(),
            power_actions=power_actions,
        )

        response = listener.handle_event(UPSPowerEvent.LOWBATT, token="secret-token", source_host="127.0.0.1")

        self.assertFalse(response.state["shutdown_scheduled"])
        self.assertIsNone(response.state["shutdown_delay_seconds"])
        self.assertEqual([], power_actions.scheduled_shutdowns)

    def test_online_clears_shutdown_schedule_before_critical_pending(self) -> None:
        state_manager = WindowsClientStateManager()
        state_manager.on_onbatt()
        state_manager.state.shutdown_scheduled = True
        state_manager.state.shutdown_delay_seconds = 45

        status, state = state_manager.on_online()

        self.assertEqual("accepted", status)
        self.assertFalse(state["shutdown_scheduled"])
        self.assertIsNone(state["shutdown_delay_seconds"])

    def test_enter_eco_mode_plans_power_saver_when_execution_is_disabled(self) -> None:
        runner = PowerActionRunner(
            WindowsClientConfig(
                execute_platform_actions=False,
                eco_mode_enabled=True,
            )
        )

        result = runner.enter_eco_mode()

        self.assertTrue(result.accepted)
        self.assertIn("power saver scheme", result.message)

    def test_exit_eco_mode_restores_previous_scheme_when_execution_is_enabled(self) -> None:
        class FakeCommandRunner(WindowsCommandRunner):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], timeout_seconds: float):
                self.commands.append(command)
                if command[:2] == ["powercfg", "/GETACTIVESCHEME"]:
                    return type("Completed", (), {"returncode": 0, "stdout": "Power Scheme GUID: 11111111-1111-1111-1111-111111111111  (Balanced)", "stderr": ""})()
                return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as temp_dir:
            restore_path = Path(temp_dir) / "scheme.txt"
            config = WindowsClientConfig(
                execute_platform_actions=True,
                eco_mode_restore_scheme_path=restore_path,
            )
            fake_runner = FakeCommandRunner()
            runner = PowerActionRunner(config=config, command_runner=fake_runner)

            enter_result = runner.enter_eco_mode()
            exit_result = runner.exit_eco_mode()

            self.assertTrue(enter_result.accepted)
            self.assertTrue(exit_result.accepted)
            self.assertIn(["powercfg", "/SETACTIVE", config.eco_mode_power_saver_guid], fake_runner.commands)
            self.assertIn(["powercfg", "/SETACTIVE", "11111111-1111-1111-1111-111111111111"], fake_runner.commands)
            self.assertFalse(restore_path.exists())

    def test_startup_reconcile_restores_previous_scheme(self) -> None:
        class FakeCommandRunner(WindowsCommandRunner):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], timeout_seconds: float):
                self.commands.append(command)
                return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as temp_dir:
            restore_path = Path(temp_dir) / "scheme.txt"
            restore_path.write_text("11111111-1111-1111-1111-111111111111\n", encoding="utf-8")
            config = WindowsClientConfig(
                execute_platform_actions=True,
                eco_mode_restore_scheme_path=restore_path,
            )
            fake_runner = FakeCommandRunner()
            runner = PowerActionRunner(config=config, command_runner=fake_runner)

            result = runner.reconcile_startup_state()

            self.assertTrue(result.accepted)
            self.assertIn(["powercfg", "/SETACTIVE", "11111111-1111-1111-1111-111111111111"], fake_runner.commands)
            self.assertFalse(restore_path.exists())


if __name__ == "__main__":
    unittest.main()