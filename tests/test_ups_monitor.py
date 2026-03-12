from __future__ import annotations

import unittest

from server.config import NUTMonitorConfig
from server.ups_monitor import CommandExecutionResult, NUTUPSMonitor, UPSCommandRunner
from shared.models import UPSPowerEvent


class FakeUPSCommandRunner(UPSCommandRunner):
    def __init__(self, responses: list[CommandExecutionResult]) -> None:
        self._responses = responses
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout_seconds: float) -> CommandExecutionResult:
        self.commands.append(command)
        if not self._responses:
            raise AssertionError("No fake UPS command response configured.")
        return self._responses.pop(0)


class UPSMonitorTests(unittest.TestCase):
    def test_parse_upsc_output_reads_status_and_battery_metrics(self) -> None:
        monitor = NUTUPSMonitor(NUTMonitorConfig())

        snapshot = monitor.parse_upsc_output(
            "ups.status: OB\n"
            "battery.charge: 77\n"
            "battery.runtime: 1280\n"
        )

        self.assertEqual(("OB",), snapshot.status_tokens)
        self.assertEqual(77, snapshot.battery_charge_percent)
        self.assertEqual(1280, snapshot.runtime_seconds)

    def test_poll_emits_onbatt_when_ups_switches_to_battery(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OL\nbattery.charge: 99\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 95\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(NUTMonitorConfig(), command_runner=runner)

        first_events = monitor.poll_events()
        second_events = monitor.poll_events()

        self.assertEqual([], first_events)
        self.assertEqual([UPSPowerEvent.ONBATT], [event.event for event in second_events])

    def test_poll_emits_online_when_power_returns(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 95\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OL\nbattery.charge: 96\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(NUTMonitorConfig(), command_runner=runner)

        monitor.poll_events()
        events = monitor.poll_events()

        self.assertEqual([UPSPowerEvent.ONLINE], [event.event for event in events])

    def test_thresholds_can_force_lowbatt_without_lb_token(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 10\nbattery.runtime: 120\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(
            NUTMonitorConfig(low_battery_charge_percent=20, low_battery_runtime_seconds=300),
            command_runner=runner,
        )

        events = monitor.poll_events()

        self.assertEqual([UPSPowerEvent.ONBATT, UPSPowerEvent.LOWBATT], [event.event for event in events])

    def test_read_snapshot_raises_when_nut_command_fails(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=1, stdout="", stderr="Error: Data stale\n"),
            ]
        )
        monitor = NUTUPSMonitor(NUTMonitorConfig(), command_runner=runner)

        with self.assertRaises(RuntimeError):
            monitor.read_snapshot()

    def test_power_state_debounce_requires_stable_transition(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OL\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(
            NUTMonitorConfig(power_state_debounce_polls=2),
            command_runner=runner,
        )

        first_events = monitor.poll_events()
        second_events = monitor.poll_events()
        third_events = monitor.poll_events()

        self.assertEqual([], first_events)
        self.assertEqual([], second_events)
        self.assertEqual([UPSPowerEvent.ONBATT], [event.event for event in third_events])

    def test_power_state_noise_does_not_emit_transition(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OL\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OL\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(
            NUTMonitorConfig(power_state_debounce_polls=2),
            command_runner=runner,
        )

        first_events = monitor.poll_events()
        second_events = monitor.poll_events()
        third_events = monitor.poll_events()

        self.assertEqual([], first_events)
        self.assertEqual([], second_events)
        self.assertEqual([], third_events)

    def test_lowbatt_debounce_requires_stable_low_battery(self) -> None:
        runner = FakeUPSCommandRunner(
            responses=[
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 50\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 10\n", stderr=""),
                CommandExecutionResult(return_code=0, stdout="ups.status: OB\nbattery.charge: 10\n", stderr=""),
            ]
        )
        monitor = NUTUPSMonitor(
            NUTMonitorConfig(
                low_battery_charge_percent=20,
                low_battery_runtime_seconds=300,
                low_battery_debounce_polls=2,
            ),
            command_runner=runner,
        )

        first_events = monitor.poll_events()
        second_events = monitor.poll_events()
        third_events = monitor.poll_events()

        self.assertEqual([UPSPowerEvent.ONBATT], [event.event for event in first_events])
        self.assertEqual([], second_events)
        self.assertEqual([UPSPowerEvent.LOWBATT], [event.event for event in third_events])


if __name__ == "__main__":
    unittest.main()