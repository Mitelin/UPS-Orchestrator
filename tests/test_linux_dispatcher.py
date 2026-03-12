from __future__ import annotations

import unittest

from server.device_registry import DeviceTarget, DeviceTransport
from server.event_dispatcher import CommandExecutionResult, CommandRunner, EventDispatcher
from shared.models import EventEnvelope, UPSPowerEvent


class FakeCommandRunner(CommandRunner):
    def __init__(self, result: CommandExecutionResult) -> None:
        self.result = result
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout_seconds: float) -> CommandExecutionResult:
        self.commands.append(command)
        return self.result


class LinuxDispatcherTests(unittest.TestCase):
    def test_lowbatt_dispatch_executes_shutdown_command_for_ssh_target(self) -> None:
        runner = FakeCommandRunner(CommandExecutionResult(return_code=0, stdout="shutdown scheduled\n", stderr=""))
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="nas",
                    transport=DeviceTransport.SSH,
                    enabled=True,
                    address="nas.local",
                    supported_events=(UPSPowerEvent.LOWBATT,),
                    ssh_user="admin",
                    ssh_port=22,
                    shutdown_command="sudo /sbin/shutdown -h now",
                )
            ],
            command_runner=runner,
        )

        results = dispatcher.dispatch(
            EventEnvelope.create(
                event_id="evt-lowbatt-1",
                event_type=UPSPowerEvent.LOWBATT,
                source="web-game-server",
                sequence=1,
            )
        )

        self.assertEqual(1, len(results))
        self.assertTrue(results[0].accepted)
        self.assertEqual(
            ["ssh", "-p", "22", "admin@nas.local", "sudo /sbin/shutdown -h now"],
            runner.commands[0],
        )

    def test_non_lowbatt_event_skips_ssh_target(self) -> None:
        runner = FakeCommandRunner(CommandExecutionResult(return_code=0, stdout="ok\n", stderr=""))
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="raspberry",
                    transport=DeviceTransport.SSH,
                    enabled=True,
                    address="raspberry.local",
                    supported_events=(UPSPowerEvent.LOWBATT,),
                    ssh_user="pi",
                    ssh_port=22,
                    shutdown_command="sudo /sbin/shutdown -h now",
                )
            ],
            command_runner=runner,
        )

        results = dispatcher.dispatch(
            EventEnvelope.create(
                event_id="evt-onbatt-1",
                event_type=UPSPowerEvent.ONBATT,
                source="web-game-server",
                sequence=1,
            )
        )

        self.assertEqual([], results)
        self.assertEqual([], runner.commands)

    def test_failed_ssh_command_returns_rejected_result(self) -> None:
        runner = FakeCommandRunner(CommandExecutionResult(return_code=255, stdout="", stderr="host unreachable\n"))
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="raspberry",
                    transport=DeviceTransport.SSH,
                    enabled=True,
                    address="raspberry.local",
                    supported_events=(UPSPowerEvent.LOWBATT,),
                    ssh_user="pi",
                    ssh_port=22,
                    shutdown_command="sudo /sbin/shutdown -h now",
                )
            ],
            command_runner=runner,
        )

        results = dispatcher.dispatch(
            EventEnvelope.create(
                event_id="evt-lowbatt-2",
                event_type=UPSPowerEvent.LOWBATT,
                source="web-game-server",
                sequence=2,
            )
        )

        self.assertFalse(results[0].accepted)
        self.assertEqual(255, results[0].status_code)
        self.assertIn("host unreachable", results[0].message)


if __name__ == "__main__":
    unittest.main()