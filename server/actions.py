from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from server.config import CriticalShutdownConfig, LocalServerActionConfig


@dataclass(slots=True, frozen=True)
class ShutdownStep:
    step_name: str
    target: str
    delay_seconds: int
    description: str


@dataclass(slots=True, frozen=True)
class CriticalShutdownPlan:
    steps: tuple[ShutdownStep, ...]


@dataclass(slots=True, frozen=True)
class LocalActionResult:
    action: str
    accepted: bool
    message: str


class LocalCommandRunner:
    def run(self, command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )


class LocalActionRunner:
    def __init__(
        self,
        local_config: LocalServerActionConfig,
        shutdown_config: CriticalShutdownConfig,
        command_runner: LocalCommandRunner | None = None,
    ) -> None:
        self._local_config = local_config
        self._shutdown_config = shutdown_config
        self._command_runner = command_runner or LocalCommandRunner()

    def should_execute_shutdown(self) -> bool:
        return self._local_config.self_shutdown_enabled

    def build_critical_shutdown_plan(self) -> CriticalShutdownPlan:
        steps = [
            ShutdownStep(
                step_name="critical_warning",
                target="all-clients",
                delay_seconds=self._shutdown_config.warning_delay_seconds,
                description="Send final critical warning to all reachable clients.",
            ),
            ShutdownStep(
                step_name="shutdown_nas",
                target="nas",
                delay_seconds=self._shutdown_config.nas_shutdown_delay_seconds,
                description="Initiate NAS shutdown before other remote systems.",
            ),
            ShutdownStep(
                step_name="shutdown_raspberry",
                target="raspberry",
                delay_seconds=self._shutdown_config.raspberry_shutdown_delay_seconds,
                description="Initiate Raspberry shutdown after storage target is committed.",
            ),
        ]

        if self._shutdown_config.include_windows_client_shutdown:
            steps.append(
                ShutdownStep(
                    step_name="shutdown_main_pc",
                    target="main-pc",
                    delay_seconds=self._shutdown_config.windows_shutdown_delay_seconds,
                    description="Optionally instruct the Windows client to perform local shutdown.",
                )
            )

        steps.append(
            ShutdownStep(
                step_name="shutdown_orchestrator",
                target="web-game-server",
                delay_seconds=self._shutdown_config.server_shutdown_delay_seconds,
                description="Shut down the orchestrator last after remote commands were issued.",
            )
        )

        return CriticalShutdownPlan(steps=tuple(steps))

    def schedule_shutdown(self, delay_seconds: int, execute: bool = False) -> LocalActionResult:
        if not execute or not self._local_config.self_shutdown_enabled:
            return LocalActionResult(
                action="schedule_local_shutdown",
                accepted=True,
                message=(
                    f"Server shutdown planned for +{delay_seconds}s using command: "
                    f"{self._local_config.self_shutdown_command}"
                ),
            )

        completed = self._command_runner.run(
            shlex.split(self._local_config.self_shutdown_command),
            timeout_seconds=max(delay_seconds, 1),
        )
        accepted = completed.returncode == 0
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message = stdout or stderr or "Server self-shutdown command executed."
        return LocalActionResult(
            action="schedule_local_shutdown",
            accepted=accepted,
            message=message,
        )

    def run_pre_shutdown_script(self, execute: bool = False) -> LocalActionResult:
        if not self._local_config.pre_shutdown_script_enabled:
            return LocalActionResult(
                action="run_pre_shutdown_script",
                accepted=True,
                message="Server pre-shutdown script is disabled.",
            )

        script_path = Path(self._local_config.pre_shutdown_script_path)
        if not execute:
            return LocalActionResult(
                action="run_pre_shutdown_script",
                accepted=True,
                message=f"Server pre-shutdown script planned: {script_path}",
            )

        if not script_path.exists():
            return LocalActionResult(
                action="run_pre_shutdown_script",
                accepted=False,
                message=f"Server pre-shutdown script not found: {script_path}",
            )

        completed = self._command_runner.run(
            ["/bin/sh", str(script_path)],
            timeout_seconds=self._local_config.pre_shutdown_script_timeout_seconds,
        )
        accepted = completed.returncode == 0
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message = stdout or stderr or "Server pre-shutdown script executed."
        return LocalActionResult(
            action="run_pre_shutdown_script",
            accepted=accepted,
            message=message,
        )
