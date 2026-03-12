from __future__ import annotations

import argparse
import json
import logging

from server.actions import LocalActionRunner
from server.config import ServerConfig
from server.device_registry import DeviceRegistry
from server.event_dispatcher import EventDispatcher
from server.journal import AuditJournal
from server.policy_engine import PowerPolicyEngine
from server.runtime import OrchestratorRuntime
from server.state_manager import OrchestratorStateManager
from server.ups_monitor import NUTUPSMonitor, UPSStatusSnapshot
from shared.models import UPSPowerEvent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UPS Orchestrator server entrypoint")
    parser.add_argument(
        "--config",
        help="Optional TOML config file path. Environment variables override file values.",
    )
    parser.add_argument(
        "command",
        choices=["status", "simulate", "clear-commit", "poll-ups", "serve", "journal"],
        help="Action to run",
    )
    parser.add_argument(
        "--event",
        choices=[event.value for event in UPSPowerEvent],
        help="Event name for simulate command",
    )
    parser.add_argument(
        "--commit-marker",
        help="Path to commit marker file",
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Dispatch supported client notifications during simulate.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply normalized UPS events through the policy engine for poll-ups.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Limit loop iterations for serve mode or repeated testing.",
    )
    parser.add_argument(
        "--journal-type",
        choices=["ups_snapshot", "observed_event", "policy_decision", "runtime_idle", "runtime_error", "status", "clear_commit"],
        help="Optional journal record type filter for the journal command.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of journal records to print.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = ServerConfig.load(args.config)
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    commit_marker_path = args.commit_marker or str(config.commit_marker_path)
    state_manager = OrchestratorStateManager(commit_marker_path)
    action_runner = LocalActionRunner(config.local_server_actions, config.critical_shutdown)
    journal = AuditJournal(config.audit_journal)

    _reconcile_startup_commit_state(config, state_manager, journal)

    if args.command == "status":
        logging.info("state=%s committed=%s", state_manager.state.value, state_manager.committed)
        journal.record_runtime_event("status", state=state_manager.state.value, committed=state_manager.committed)
        return 0

    if args.command == "clear-commit":
        state_manager.clear_commit()
        logging.info("state=%s committed=%s", state_manager.state.value, state_manager.committed)
        journal.record_runtime_event("clear_commit", state=state_manager.state.value, committed=state_manager.committed)
        return 0

    if args.command == "journal":
        records = journal.read_records(record_type=args.journal_type, limit=args.limit)
        if not records:
            logging.error("No audit journal records found at %s", config.audit_journal.path)
            return 1
        for record in records:
            print(json.dumps(record, ensure_ascii=True))
        return 0

    if args.command == "poll-ups":
        if not config.nut_monitor.enabled:
            logging.error("NUT monitor is disabled. Set UPS_ORCHESTRATOR_NUT_ENABLED=true to use poll-ups.")
            return 1

        monitor = NUTUPSMonitor(config.nut_monitor, timeout_seconds=config.dispatch_runtime.timeout_seconds)
        snapshot, observed_events = monitor.observe()
        journal.record_snapshot(snapshot)
        logging.info(
            "ups_status=%s battery_charge_percent=%s runtime_seconds=%s",
            " ".join(snapshot.status_tokens) or "unknown",
            snapshot.battery_charge_percent,
            snapshot.runtime_seconds,
        )

        if not observed_events:
            logging.info("No normalized UPS events emitted from current snapshot.")
            return 0

        dispatcher = None
        if args.dispatch:
            registry = DeviceRegistry.from_config(config)
            dispatcher = EventDispatcher.from_registry(
                registry,
                request_timeout_seconds=config.dispatch_runtime.timeout_seconds,
                retry_attempts=config.dispatch_runtime.retry_attempts,
                retry_delay_seconds=config.dispatch_runtime.retry_delay_seconds,
            )

        for index, observed_event in enumerate(observed_events, start=1):
            logging.info("normalized_event=%s payload=%s", observed_event.event.value, observed_event.payload)
            journal.record_observed_event(observed_event)
            if args.apply:
                decision = PowerPolicyEngine(
                    state_manager,
                    dispatcher=dispatcher,
                    action_runner=action_runner,
                ).evaluate_event(
                    observed_event.event,
                    source=config.node_name,
                    sequence=index,
                    payload=observed_event.payload,
                )
                logging.info(
                    "state=%s committed=%s message=%s actions=%s",
                    decision.transition.current_state.value,
                    decision.transition.committed,
                    decision.transition.message,
                    ", ".join(decision.actions) if decision.actions else "none",
                )
                for dispatch_result in decision.dispatch_results:
                    logging.info(
                        "dispatch target=%s accepted=%s status_code=%s message=%s",
                        dispatch_result.target,
                        dispatch_result.accepted,
                        dispatch_result.status_code,
                        dispatch_result.message,
                    )
                for local_result in decision.local_results:
                    logging.info(
                        "local_action action=%s accepted=%s message=%s",
                        local_result.action,
                        local_result.accepted,
                        local_result.message,
                    )
                if decision.shutdown_plan is not None:
                    for step in decision.shutdown_plan.steps:
                        logging.info(
                            "shutdown_step name=%s target=%s delay_seconds=%s description=%s",
                            step.step_name,
                            step.target,
                            step.delay_seconds,
                            step.description,
                        )
                journal.record_policy_decision(decision)
        return 0

    if args.command == "serve":
        if not config.nut_monitor.enabled:
            logging.error("NUT monitor is disabled. Set UPS_ORCHESTRATOR_NUT_ENABLED=true to use serve.")
            return 1

        monitor = NUTUPSMonitor(config.nut_monitor, timeout_seconds=config.dispatch_runtime.timeout_seconds)
        registry = DeviceRegistry.from_config(config)
        dispatcher = EventDispatcher.from_registry(
            registry,
            request_timeout_seconds=config.dispatch_runtime.timeout_seconds,
            retry_attempts=config.dispatch_runtime.retry_attempts,
            retry_delay_seconds=config.dispatch_runtime.retry_delay_seconds,
        )
        runtime = OrchestratorRuntime(
            node_name=config.node_name,
            state_manager=state_manager,
            monitor=monitor,
            dispatcher=dispatcher,
            action_runner=action_runner,
            apply_policy=not config.observe_only,
            journal=journal,
        )
        logging.info(
            "runtime starting observe_only=%s poll_interval_seconds=%s",
            config.observe_only,
            config.dispatch_runtime.poll_interval_seconds,
        )
        return runtime.serve(
            poll_interval_seconds=config.dispatch_runtime.poll_interval_seconds,
            max_iterations=args.max_iterations,
        )

    if not args.event:
        parser.error("--event is required for simulate")

    dispatcher = None
    if args.dispatch:
        registry = DeviceRegistry.from_config(config)
        dispatcher = EventDispatcher.from_registry(
            registry,
            request_timeout_seconds=config.dispatch_runtime.timeout_seconds,
            retry_attempts=config.dispatch_runtime.retry_attempts,
            retry_delay_seconds=config.dispatch_runtime.retry_delay_seconds,
        )

    decision = PowerPolicyEngine(state_manager, dispatcher=dispatcher, action_runner=action_runner).evaluate_event(
        UPSPowerEvent(args.event),
        source=config.node_name,
        sequence=1,
        payload={"grace_period_seconds": config.grace_period_seconds},
    )
    journal.record_policy_decision(decision)
    logging.info("state=%s committed=%s", decision.transition.current_state.value, decision.transition.committed)
    logging.info("message=%s", decision.transition.message)
    logging.info("actions=%s", ", ".join(decision.actions) if decision.actions else "none")
    for dispatch_result in decision.dispatch_results:
        logging.info(
            "dispatch target=%s accepted=%s status_code=%s message=%s",
            dispatch_result.target,
            dispatch_result.accepted,
            dispatch_result.status_code,
            dispatch_result.message,
        )
    for local_result in decision.local_results:
        logging.info(
            "local_action action=%s accepted=%s message=%s",
            local_result.action,
            local_result.accepted,
            local_result.message,
        )
    if decision.shutdown_plan is not None:
        for step in decision.shutdown_plan.steps:
            logging.info(
                "shutdown_step name=%s target=%s delay_seconds=%s description=%s",
                step.step_name,
                step.target,
                step.delay_seconds,
                step.description,
            )
    return 0


def _reconcile_startup_commit_state(
    config: ServerConfig,
    state_manager: OrchestratorStateManager,
    journal: AuditJournal,
) -> None:
    if not state_manager.committed:
        return
    if not config.nut_monitor.enabled:
        return

    try:
        snapshot = NUTUPSMonitor(config.nut_monitor, timeout_seconds=config.dispatch_runtime.timeout_seconds).read_snapshot()
    except RuntimeError as error:
        logging.warning("startup_reconcile committed_state_retained reason=%s", error)
        journal.record_runtime_event("startup_reconcile_retained", reason=str(error), committed=True)
        return

    if _snapshot_is_all_clear(snapshot):
        state_manager.clear_commit()
        logging.info("startup_reconcile committed_state_cleared ups_status=%s", " ".join(snapshot.status_tokens) or "unknown")
        journal.record_runtime_event(
            "startup_reconcile_cleared",
            committed=False,
            ups_status=" ".join(snapshot.status_tokens),
            battery_charge_percent=snapshot.battery_charge_percent,
            runtime_seconds=snapshot.runtime_seconds,
        )
        return

    logging.info("startup_reconcile committed_state_retained ups_status=%s", " ".join(snapshot.status_tokens) or "unknown")
    journal.record_runtime_event(
        "startup_reconcile_retained",
        committed=True,
        ups_status=" ".join(snapshot.status_tokens),
        battery_charge_percent=snapshot.battery_charge_percent,
        runtime_seconds=snapshot.runtime_seconds,
    )


def _snapshot_is_all_clear(snapshot: UPSStatusSnapshot) -> bool:
    return snapshot.online and not snapshot.on_battery and not snapshot.low_battery


if __name__ == "__main__":
    raise SystemExit(main())
