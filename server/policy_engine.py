from __future__ import annotations

from dataclasses import dataclass

from server.actions import CriticalShutdownPlan, LocalActionResult, LocalActionRunner
from server.event_dispatcher import DispatchResult, EventDispatcher
from server.state_manager import OrchestratorStateManager, TransitionResult
from shared.models import EventEnvelope, UPSPowerEvent


@dataclass(slots=True)
class PolicyDecision:
    transition: TransitionResult
    actions: list[str]
    dispatch_results: list[DispatchResult]
    local_results: list[LocalActionResult]
    shutdown_plan: CriticalShutdownPlan | None


class PowerPolicyEngine:
    def __init__(
        self,
        state_manager: OrchestratorStateManager,
        dispatcher: EventDispatcher | None = None,
        action_runner: LocalActionRunner | None = None,
    ) -> None:
        self._state_manager = state_manager
        self._dispatcher = dispatcher
        self._action_runner = action_runner

    def evaluate_event(
        self,
        event: UPSPowerEvent,
        *,
        source: str = "web-game-server",
        sequence: int | None = None,
        payload: dict[str, object] | None = None,
    ) -> PolicyDecision:
        transition = self._state_manager.handle_event(event)
        actions: list[str] = []
        dispatch_results: list[DispatchResult] = []
        local_results: list[LocalActionResult] = []
        shutdown_plan: CriticalShutdownPlan | None = None

        if transition.changed and transition.current_state.value == "ON_BATTERY":
            actions.extend(["notify_clients_onbatt", "enter_local_eco_mode"])
            if self._action_runner:
                local_results.append(self._action_runner.enter_eco_mode())
        elif transition.current_state.value == "CRITICAL_SHUTDOWN":
            actions.extend(["notify_clients_lowbatt", "start_ordered_shutdown"])
            if self._action_runner:
                shutdown_plan = self._action_runner.build_critical_shutdown_plan()
                local_results.append(
                    self._action_runner.schedule_shutdown(
                        delay_seconds=shutdown_plan.steps[-1].delay_seconds,
                    )
                )
        elif transition.changed and transition.current_state.value == "NORMAL":
            actions.extend(["notify_clients_online", "exit_local_eco_mode"])
            if self._action_runner:
                local_results.append(self._action_runner.exit_eco_mode())

        if self._dispatcher and (
            any(action.startswith("notify_clients_") for action in actions)
            or "start_ordered_shutdown" in actions
        ):
            dispatch_results = self._dispatcher.dispatch(
                EventEnvelope.create(
                    event_id=self._build_event_id(event, sequence),
                    event_type=event,
                    source=source,
                    sequence=sequence,
                    payload=payload,
                )
            )

        return PolicyDecision(
            transition=transition,
            actions=actions,
            dispatch_results=dispatch_results,
            local_results=local_results,
            shutdown_plan=shutdown_plan,
        )

    def _build_event_id(self, event: UPSPowerEvent, sequence: int | None) -> str:
        suffix = str(sequence) if sequence is not None else "runtime"
        return f"evt-{event.value.lower()}-{suffix}"
