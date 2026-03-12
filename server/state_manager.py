from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.models import OrchestratorState, UPSPowerEvent


@dataclass(slots=True, frozen=True)
class TransitionResult:
    previous_state: OrchestratorState
    current_state: OrchestratorState
    changed: bool
    committed: bool
    message: str


class OrchestratorStateManager:
    def __init__(self, commit_marker_path: Path | str) -> None:
        self._commit_marker_path = Path(commit_marker_path)
        self._state = (
            OrchestratorState.CRITICAL_SHUTDOWN
            if self._commit_marker_path.exists()
            else OrchestratorState.NORMAL
        )

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def committed(self) -> bool:
        return self._commit_marker_path.exists()

    def handle_event(self, event: UPSPowerEvent) -> TransitionResult:
        previous_state = self._state

        if self._state is OrchestratorState.CRITICAL_SHUTDOWN:
            return TransitionResult(
                previous_state=previous_state,
                current_state=self._state,
                changed=False,
                committed=True,
                message=f"Ignored {event.value} because shutdown is already committed.",
            )

        if self._state is OrchestratorState.NORMAL:
            if event is UPSPowerEvent.ONBATT:
                self._state = OrchestratorState.ON_BATTERY
                return self._result(previous_state, True, "Transitioned to ON_BATTERY.")
            if event in (UPSPowerEvent.LOWBATT, UPSPowerEvent.SHUTDOWN_COMMIT):
                return self._commit_shutdown(previous_state, f"Received {event.value}; committed critical shutdown.")
            return self._result(previous_state, False, f"Ignored {event.value} while already in NORMAL.")

        if event is UPSPowerEvent.ONLINE:
            self._state = OrchestratorState.NORMAL
            return self._result(previous_state, True, "Utility power restored; transitioned to NORMAL.")
        if event is UPSPowerEvent.ONBATT:
            return self._result(previous_state, False, "Ignored duplicate ONBATT event.")
        if event in (UPSPowerEvent.LOWBATT, UPSPowerEvent.SHUTDOWN_COMMIT):
            return self._commit_shutdown(previous_state, f"Received {event.value}; committed critical shutdown.")

        return self._result(previous_state, False, f"Ignored {event.value}.")

    def clear_commit(self) -> None:
        if self._commit_marker_path.exists():
            self._commit_marker_path.unlink()
        self._state = OrchestratorState.NORMAL

    def _commit_shutdown(self, previous_state: OrchestratorState, message: str) -> TransitionResult:
        self._commit_marker_path.parent.mkdir(parents=True, exist_ok=True)
        self._commit_marker_path.write_text("committed\n", encoding="utf-8")
        self._state = OrchestratorState.CRITICAL_SHUTDOWN
        return self._result(previous_state, True, message)

    def _result(
        self,
        previous_state: OrchestratorState,
        changed: bool,
        message: str,
    ) -> TransitionResult:
        return TransitionResult(
            previous_state=previous_state,
            current_state=self._state,
            changed=changed,
            committed=self.committed,
            message=message,
        )
