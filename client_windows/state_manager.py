from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class WindowsClientState:
    eco_mode_active: bool = False
    critical_shutdown_pending: bool = False
    shutdown_scheduled: bool = False
    shutdown_delay_seconds: int | None = None


class WindowsClientStateManager:
    def __init__(self) -> None:
        self._state = WindowsClientState()

    @property
    def state(self) -> WindowsClientState:
        return self._state

    def on_onbatt(self) -> tuple[str, dict[str, bool | int | None]]:
        self._state.eco_mode_active = True
        return "accepted", asdict(self._state)

    def on_online(self) -> tuple[str, dict[str, bool | int | None]]:
        if self._state.critical_shutdown_pending:
            return "ignored", asdict(self._state)
        self._state.eco_mode_active = False
        self._state.shutdown_scheduled = False
        self._state.shutdown_delay_seconds = None
        return "accepted", asdict(self._state)

    def on_lowbatt(self, shutdown_delay_seconds: int | None = None) -> tuple[str, dict[str, bool | int | None]]:
        self._state.eco_mode_active = True
        self._state.critical_shutdown_pending = True
        if shutdown_delay_seconds is not None:
            self._state.shutdown_scheduled = True
            self._state.shutdown_delay_seconds = shutdown_delay_seconds
        return "accepted", asdict(self._state)
