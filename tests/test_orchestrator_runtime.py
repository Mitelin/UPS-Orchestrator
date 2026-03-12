from __future__ import annotations

import io
import logging
import tempfile
import unittest
from pathlib import Path

from server.actions import LocalActionRunner
from server.config import CriticalShutdownConfig, LocalServerActionConfig
from server.runtime import OrchestratorRuntime
from server.state_manager import OrchestratorStateManager
from server.ups_monitor import UPSObservedEvent, UPSStatusSnapshot
from shared.models import OrchestratorState, UPSPowerEvent


class FakeMonitor:
    def __init__(self, observations: list[tuple[UPSStatusSnapshot | None, list[UPSObservedEvent]]]) -> None:
        self._observations = observations
        self.calls = 0

    def observe(self) -> tuple[UPSStatusSnapshot | None, list[UPSObservedEvent]]:
        self.calls += 1
        if not self._observations:
            raise AssertionError("No fake observation configured.")
        return self._observations.pop(0)

    def poll_events(self) -> list[UPSObservedEvent]:
        return self.observe()[1]


class OrchestratorRuntimeTests(unittest.TestCase):
    def test_run_once_observe_only_does_not_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            runtime = OrchestratorRuntime(
                node_name="web-game-server",
                state_manager=state_manager,
                monitor=FakeMonitor(
                    [
                        (
                            UPSStatusSnapshot(status_tokens=("OB",), battery_charge_percent=90, runtime_seconds=1800),
                            [UPSObservedEvent(event=UPSPowerEvent.ONBATT, payload={"runtime_seconds": 1800})],
                        )
                    ]
                ),
                apply_policy=False,
            )

            result = runtime.run_once()

            self.assertEqual(1, len(result.observed_events))
            self.assertEqual([], result.decisions)
            self.assertEqual(OrchestratorState.NORMAL, state_manager.state)

    def test_run_once_apply_policy_transitions_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            runtime = OrchestratorRuntime(
                node_name="web-game-server",
                state_manager=state_manager,
                monitor=FakeMonitor(
                    [
                        (
                            UPSStatusSnapshot(status_tokens=("OB",), battery_charge_percent=90, runtime_seconds=1800),
                            [UPSObservedEvent(event=UPSPowerEvent.ONBATT, payload={"runtime_seconds": 1800})],
                        )
                    ]
                ),
                action_runner=LocalActionRunner(LocalServerActionConfig(), CriticalShutdownConfig()),
                apply_policy=True,
            )

            result = runtime.run_once()

            self.assertEqual(1, len(result.decisions))
            self.assertEqual(OrchestratorState.ON_BATTERY, state_manager.state)
            self.assertEqual(1, result.decisions[0].local_results[0].accepted)

    def test_serve_runs_multiple_iterations_and_sleeps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sleep_calls: list[float] = []
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            runtime = OrchestratorRuntime(
                node_name="web-game-server",
                state_manager=state_manager,
                monitor=FakeMonitor(
                    [
                        (UPSStatusSnapshot(status_tokens=("OL",), battery_charge_percent=99, runtime_seconds=3600), []),
                        (UPSStatusSnapshot(status_tokens=("OB",), battery_charge_percent=95, runtime_seconds=1800), []),
                    ]
                ),
                apply_policy=False,
                sleep_func=sleep_calls.append,
            )

            exit_code = runtime.serve(poll_interval_seconds=2.5, max_iterations=2)

            self.assertEqual(0, exit_code)
            self.assertEqual([2.5], sleep_calls)

    def test_runtime_logs_decision_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_manager = OrchestratorStateManager(Path(temp_dir) / "shutdown.commit")
            stream = io.StringIO()
            logger = logging.getLogger("server.runtime.test")
            handler = logging.StreamHandler(stream)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            try:
                runtime = OrchestratorRuntime(
                    node_name="web-game-server",
                    state_manager=state_manager,
                    monitor=FakeMonitor(
                        [
                            (
                                UPSStatusSnapshot(status_tokens=("OB", "LB"), battery_charge_percent=10, runtime_seconds=120),
                                [UPSObservedEvent(event=UPSPowerEvent.LOWBATT, payload={"runtime_seconds": 120})],
                            )
                        ]
                    ),
                    action_runner=LocalActionRunner(LocalServerActionConfig(), CriticalShutdownConfig()),
                    apply_policy=True,
                    logger=logger,
                )

                runtime.run_once()
            finally:
                logger.removeHandler(handler)

            output = stream.getvalue()
            self.assertIn("runtime normalized_event=LOWBATT", output)
            self.assertIn("runtime shutdown_step name=shutdown_orchestrator", output)


if __name__ == "__main__":
    unittest.main()