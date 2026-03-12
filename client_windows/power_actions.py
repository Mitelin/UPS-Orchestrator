from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from client_windows.config import WindowsClientConfig


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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

class PowerActionRunner:
    def __init__(
        self,
        config: WindowsClientConfig | None = None,
        command_runner: WindowsCommandRunner | None = None,
    ) -> None:
        self._config = config or WindowsClientConfig()
        self._command_runner = command_runner or WindowsCommandRunner()

    def enter_eco_mode(self) -> PowerActionResult:
        if not self._config.eco_mode_enabled:
            return PowerActionResult(action="enter_eco_mode", accepted=True, message="Windows eco mode policy is disabled.")

        if not self._config.execute_platform_actions:
            return PowerActionResult(
                action="enter_eco_mode",
                accepted=True,
                message=f"Windows eco mode planned using power saver scheme {self._config.eco_mode_power_saver_guid}.",
            )

        active_scheme = self._get_active_scheme_guid()
        if active_scheme and active_scheme.lower() != self._config.eco_mode_power_saver_guid.lower():
            self._write_restore_scheme(active_scheme)

        return self._set_active_scheme(
            self._config.eco_mode_power_saver_guid,
            action="enter_eco_mode",
            success_message="Windows power saver plan activated.",
        )

    def exit_eco_mode(self) -> PowerActionResult:
        if not self._config.eco_mode_enabled:
            return PowerActionResult(action="exit_eco_mode", accepted=True, message="Windows eco mode policy is disabled.")

        restore_scheme = self._read_restore_scheme() or self._config.eco_mode_balanced_guid
        if not self._config.execute_platform_actions:
            return PowerActionResult(
                action="exit_eco_mode",
                accepted=True,
                message=f"Windows eco mode exit planned using scheme {restore_scheme}.",
            )

        result = self._set_active_scheme(
            restore_scheme,
            action="exit_eco_mode",
            success_message=f"Windows power plan restored to {restore_scheme}.",
        )
        if result.accepted:
            self._clear_restore_scheme()
        return result

    def schedule_shutdown(self, *, delay_seconds: int, command: str, execute: bool = False) -> PowerActionResult:
        if not execute:
            return PowerActionResult(
                action="schedule_shutdown",
                accepted=True,
                message=f"Windows shutdown planned for +{delay_seconds}s using command: {command}",
            )

        completed = self._command_runner.run(self._split_command(command), timeout_seconds=max(delay_seconds, 1))
        accepted = completed.returncode == 0
        message = completed.stdout.strip() or completed.stderr.strip() or "Windows shutdown command executed."
        return PowerActionResult(action="schedule_shutdown", accepted=accepted, message=message)

    def reconcile_startup_state(self) -> PowerActionResult:
        restore_scheme = self._read_restore_scheme()
        if restore_scheme is None:
            return PowerActionResult(
                action="startup_reconcile_eco_mode",
                accepted=True,
                message="No pending Windows eco mode restoration found.",
            )

        if not self._config.eco_mode_enabled:
            self._clear_restore_scheme()
            return PowerActionResult(
                action="startup_reconcile_eco_mode",
                accepted=True,
                message="Pending Windows eco mode restoration was discarded because eco mode is disabled.",
            )

        if not self._config.execute_platform_actions:
            return PowerActionResult(
                action="startup_reconcile_eco_mode",
                accepted=True,
                message=f"Windows startup restore planned using scheme {restore_scheme}.",
            )

        result = self._set_active_scheme(
            restore_scheme,
            action="startup_reconcile_eco_mode",
            success_message=f"Windows startup restored power plan to {restore_scheme}.",
        )
        if result.accepted:
            self._clear_restore_scheme()
        return result

    def _set_active_scheme(self, scheme_guid: str, *, action: str, success_message: str) -> PowerActionResult:
        completed = self._command_runner.run(
            ["powercfg", "/SETACTIVE", scheme_guid],
            timeout_seconds=10.0,
        )
        accepted = completed.returncode == 0
        message = completed.stdout.strip() or completed.stderr.strip() or success_message
        return PowerActionResult(action=action, accepted=accepted, message=message)

    def _get_active_scheme_guid(self) -> str | None:
        completed = self._command_runner.run(["powercfg", "/GETACTIVESCHEME"], timeout_seconds=10.0)
        if completed.returncode != 0:
            return None
        match = re.search(r"([0-9a-fA-F-]{36})", completed.stdout)
        return match.group(1) if match else None

    def _write_restore_scheme(self, scheme_guid: str) -> None:
        restore_path = self._config.eco_mode_restore_scheme_path
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        restore_path.write_text(scheme_guid + "\n", encoding="utf-8")

    def _read_restore_scheme(self) -> str | None:
        restore_path = self._config.eco_mode_restore_scheme_path
        if not restore_path.exists():
            return None
        value = restore_path.read_text(encoding="utf-8").strip()
        return value or None

    def _clear_restore_scheme(self) -> None:
        restore_path = self._config.eco_mode_restore_scheme_path
        if restore_path.exists():
            restore_path.unlink()

    @staticmethod
    def _split_command(command: str) -> list[str]:
        return shlex.split(command, posix=False)
