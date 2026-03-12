from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from server.config import NUTMonitorConfig
from shared.models import UPSPowerEvent


@dataclass(slots=True, frozen=True)
class UPSStatusSnapshot:
    status_tokens: tuple[str, ...]
    battery_charge_percent: int | None = None
    runtime_seconds: int | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)

    @property
    def on_battery(self) -> bool:
        return "OB" in self.status_tokens

    @property
    def online(self) -> bool:
        return "OL" in self.status_tokens

    @property
    def low_battery(self) -> bool:
        return "LB" in self.status_tokens


@dataclass(slots=True, frozen=True)
class UPSObservedEvent:
    event: UPSPowerEvent
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CommandExecutionResult:
    return_code: int
    stdout: str
    stderr: str


class UPSCommandRunner:
    def run(self, command: list[str], timeout_seconds: float) -> CommandExecutionResult:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandExecutionResult(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class UPSMonitorBackend(Protocol):
    def observe(self) -> tuple[UPSStatusSnapshot | None, list[UPSObservedEvent]]:
        """Return the latest UPS snapshot and any normalized events."""

    def poll_events(self) -> list[UPSObservedEvent]:
        """Return normalized UPS events from the active backend."""


class NoopUPSMonitor:
    def observe(self) -> tuple[UPSStatusSnapshot | None, list[UPSObservedEvent]]:
        return None, []

    def poll_events(self) -> list[UPSObservedEvent]:
        return []


class NUTUPSMonitor:
    def __init__(
        self,
        config: NUTMonitorConfig,
        command_runner: UPSCommandRunner | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._config = config
        self._command_runner = command_runner or UPSCommandRunner()
        self._timeout_seconds = timeout_seconds
        self._previous_snapshot: UPSStatusSnapshot | None = None
        self._stable_power_source: str | None = None
        self._pending_power_source: str | None = None
        self._pending_power_count = 0
        self._stable_low_battery: bool | None = None
        self._pending_low_battery: bool | None = None
        self._pending_low_battery_count = 0

    def poll_events(self) -> list[UPSObservedEvent]:
        return self.observe()[1]

    def observe(self) -> tuple[UPSStatusSnapshot, list[UPSObservedEvent]]:
        snapshot = self.read_snapshot()
        events = self._normalize_events(snapshot)
        self._previous_snapshot = snapshot
        return snapshot, events

    def read_snapshot(self) -> UPSStatusSnapshot:
        command = [self._config.command, self._config.device_name]
        result = self._command_runner.run(command, timeout_seconds=self._timeout_seconds)
        if result.return_code != 0:
            error_message = result.stderr.strip() or result.stdout.strip() or "NUT command failed."
            raise RuntimeError(error_message)
        return self.parse_upsc_output(result.stdout)

    def parse_upsc_output(self, output: str) -> UPSStatusSnapshot:
        fields: dict[str, str] = {}
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()

        status_value = fields.get("ups.status", "")
        status_tokens = tuple(token for token in status_value.split() if token)
        battery_charge_percent = self._parse_int(fields.get("battery.charge"))
        runtime_seconds = self._parse_int(fields.get("battery.runtime"))

        if self._is_low_battery_by_threshold(battery_charge_percent, runtime_seconds) and "LB" not in status_tokens:
            status_tokens = (*status_tokens, "LB")

        return UPSStatusSnapshot(
            status_tokens=status_tokens,
            battery_charge_percent=battery_charge_percent,
            runtime_seconds=runtime_seconds,
            raw_fields=fields,
        )

    def _normalize_events(self, snapshot: UPSStatusSnapshot) -> list[UPSObservedEvent]:
        payload = self._payload_from_snapshot(snapshot)
        observed_events: list[UPSObservedEvent] = []
        current_power_source = self._power_source(snapshot)
        current_low_battery = snapshot.low_battery

        if self._stable_power_source is None or self._stable_low_battery is None:
            self._stable_power_source = current_power_source
            self._stable_low_battery = current_low_battery
            if current_power_source == "battery":
                observed_events.append(UPSObservedEvent(event=UPSPowerEvent.ONBATT, payload=payload))
            if current_low_battery:
                observed_events.append(UPSObservedEvent(event=UPSPowerEvent.LOWBATT, payload=payload))
            return observed_events

        power_event = self._process_power_source_transition(current_power_source, payload)
        if power_event is not None:
            observed_events.append(power_event)

        low_battery_event = self._process_low_battery_transition(current_low_battery, payload)
        if low_battery_event is not None:
            observed_events.append(low_battery_event)

        return observed_events

    def _process_power_source_transition(
        self,
        current_power_source: str,
        payload: dict[str, object],
    ) -> UPSObservedEvent | None:
        if current_power_source == self._stable_power_source or current_power_source == "unknown":
            self._pending_power_source = None
            self._pending_power_count = 0
            return None

        if self._pending_power_source == current_power_source:
            self._pending_power_count += 1
        else:
            self._pending_power_source = current_power_source
            self._pending_power_count = 1

        if self._pending_power_count < self._config.power_state_debounce_polls:
            return None

        self._stable_power_source = current_power_source
        self._pending_power_source = None
        self._pending_power_count = 0

        if current_power_source == "battery":
            return UPSObservedEvent(event=UPSPowerEvent.ONBATT, payload=payload)
        if current_power_source == "online":
            return UPSObservedEvent(event=UPSPowerEvent.ONLINE, payload=payload)
        return None

    def _process_low_battery_transition(
        self,
        current_low_battery: bool,
        payload: dict[str, object],
    ) -> UPSObservedEvent | None:
        if current_low_battery == self._stable_low_battery:
            self._pending_low_battery = None
            self._pending_low_battery_count = 0
            return None

        if self._pending_low_battery == current_low_battery:
            self._pending_low_battery_count += 1
        else:
            self._pending_low_battery = current_low_battery
            self._pending_low_battery_count = 1

        if self._pending_low_battery_count < self._config.low_battery_debounce_polls:
            return None

        self._stable_low_battery = current_low_battery
        self._pending_low_battery = None
        self._pending_low_battery_count = 0

        if current_low_battery:
            return UPSObservedEvent(event=UPSPowerEvent.LOWBATT, payload=payload)
        return None

    def _payload_from_snapshot(self, snapshot: UPSStatusSnapshot) -> dict[str, object]:
        return {
            "ups_status": " ".join(snapshot.status_tokens),
            "battery_charge_percent": snapshot.battery_charge_percent,
            "runtime_seconds": snapshot.runtime_seconds,
        }

    def _is_low_battery_by_threshold(
        self,
        battery_charge_percent: int | None,
        runtime_seconds: int | None,
    ) -> bool:
        charge_is_low = (
            battery_charge_percent is not None
            and battery_charge_percent <= self._config.low_battery_charge_percent
        )
        runtime_is_low = (
            runtime_seconds is not None
            and runtime_seconds <= self._config.low_battery_runtime_seconds
        )
        return charge_is_low or runtime_is_low

    @staticmethod
    def _power_source(snapshot: UPSStatusSnapshot) -> str:
        if snapshot.on_battery:
            return "battery"
        if snapshot.online:
            return "online"
        return "unknown"

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None
