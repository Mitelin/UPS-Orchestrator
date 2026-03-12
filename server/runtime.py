from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from server.actions import LocalActionRunner
from server.event_dispatcher import EventDispatcher
from server.journal import AuditJournal
from server.policy_engine import PolicyDecision, PowerPolicyEngine
from server.state_manager import OrchestratorStateManager
from server.ups_monitor import UPSMonitorBackend, UPSObservedEvent, UPSStatusSnapshot


@dataclass(slots=True)
class RuntimeIterationResult:
    snapshot: UPSStatusSnapshot | None
    observed_events: list[UPSObservedEvent] = field(default_factory=list)
    decisions: list[PolicyDecision] = field(default_factory=list)


class OrchestratorRuntime:
    def __init__(
        self,
        *,
        node_name: str,
        state_manager: OrchestratorStateManager,
        monitor: UPSMonitorBackend,
        dispatcher: EventDispatcher | None = None,
        action_runner: LocalActionRunner | None = None,
        apply_policy: bool = False,
        journal: AuditJournal | None = None,
        logger: logging.Logger | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._node_name = node_name
        self._state_manager = state_manager
        self._monitor = monitor
        self._dispatcher = dispatcher
        self._action_runner = action_runner
        self._apply_policy = apply_policy
        self._journal = journal
        self._logger = logger or logging.getLogger(__name__)
        self._sleep_func = sleep_func
        self._event_sequence = 0

    def run_once(self) -> RuntimeIterationResult:
        snapshot, observed_events = self._monitor.observe()
        self._log_snapshot(snapshot)
        if self._journal:
            self._journal.record_snapshot(snapshot)

        if not observed_events:
            self._logger.info("runtime no normalized events emitted")
            if self._journal:
                self._journal.record_runtime_event("runtime_idle")
            return RuntimeIterationResult(snapshot=snapshot)

        decisions: list[PolicyDecision] = []
        for observed_event in observed_events:
            self._logger.info("runtime normalized_event=%s payload=%s", observed_event.event.value, observed_event.payload)
            if self._journal:
                self._journal.record_observed_event(observed_event)
            if not self._apply_policy:
                continue
            decision = PowerPolicyEngine(
                self._state_manager,
                dispatcher=self._dispatcher,
                action_runner=self._action_runner,
            ).evaluate_event(
                observed_event.event,
                source=self._node_name,
                sequence=self._next_sequence(),
                payload=observed_event.payload,
            )
            decisions.append(decision)
            self._log_decision(decision)
            if self._journal:
                self._journal.record_policy_decision(decision)

        return RuntimeIterationResult(snapshot=snapshot, observed_events=observed_events, decisions=decisions)

    def serve(self, poll_interval_seconds: float, max_iterations: int | None = None) -> int:
        completed_iterations = 0
        while max_iterations is None or completed_iterations < max_iterations:
            try:
                self.run_once()
            except RuntimeError as error:
                self._logger.error("runtime monitor_error=%s", error)
                if self._journal:
                    self._journal.record_runtime_event("runtime_error", message=str(error))
            completed_iterations += 1
            if max_iterations is not None and completed_iterations >= max_iterations:
                break
            self._sleep_func(poll_interval_seconds)
        return 0

    def _next_sequence(self) -> int:
        self._event_sequence += 1
        return self._event_sequence

    def _log_snapshot(self, snapshot: UPSStatusSnapshot | None) -> None:
        if snapshot is None:
            self._logger.info("runtime ups_status=unavailable")
            return
        self._logger.info(
            "runtime ups_status=%s battery_charge_percent=%s runtime_seconds=%s",
            " ".join(snapshot.status_tokens) or "unknown",
            snapshot.battery_charge_percent,
            snapshot.runtime_seconds,
        )

    def _log_decision(self, decision: PolicyDecision) -> None:
        self._logger.info(
            "runtime state=%s committed=%s message=%s actions=%s",
            decision.transition.current_state.value,
            decision.transition.committed,
            decision.transition.message,
            ", ".join(decision.actions) if decision.actions else "none",
        )
        for dispatch_result in decision.dispatch_results:
            self._logger.info(
                "runtime dispatch target=%s accepted=%s status_code=%s attempts=%s message=%s",
                dispatch_result.target,
                dispatch_result.accepted,
                dispatch_result.status_code,
                dispatch_result.attempts,
                dispatch_result.message,
            )
        for local_result in decision.local_results:
            self._logger.info(
                "runtime local_action action=%s accepted=%s message=%s",
                local_result.action,
                local_result.accepted,
                local_result.message,
            )
        if decision.shutdown_plan is not None:
            for step in decision.shutdown_plan.steps:
                self._logger.info(
                    "runtime shutdown_step name=%s target=%s delay_seconds=%s description=%s",
                    step.step_name,
                    step.target,
                    step.delay_seconds,
                    step.description,
                )