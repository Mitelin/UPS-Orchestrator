from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PowerActionResult:
    action: str
    accepted: bool
    message: str


class WindowsCommandRunner:
    def run(self, command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

class PowerActionRunner:
    def __init__(self, command_runner: WindowsCommandRunner | None = None) -> None:
        self._command_runner = command_runner or WindowsCommandRunner()

    def enter_eco_mode(self) -> PowerActionResult:
        return PowerActionResult(action="enter_eco_mode", accepted=True, message="Windows eco mode placeholder executed.")

    def exit_eco_mode(self) -> PowerActionResult:
        return PowerActionResult(action="exit_eco_mode", accepted=True, message="Windows eco mode exit placeholder executed.")

    def schedule_shutdown(self, *, delay_seconds: int, command: str, execute: bool = False) -> PowerActionResult:
        if not execute:
            return PowerActionResult(
                action="schedule_shutdown",
                accepted=True,
                message=f"Windows shutdown planned for +{delay_seconds}s using command: {command}",
            )

        completed = self._command_runner.run(shlex.split(command), timeout_seconds=max(delay_seconds, 1))
        accepted = completed.returncode == 0
        message = completed.stdout.strip() or completed.stderr.strip() or "Windows shutdown command executed."
        return PowerActionResult(action="schedule_shutdown", accepted=accepted, message=message)
