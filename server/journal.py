from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.config import AuditJournalConfig
from server.policy_engine import PolicyDecision
from server.ups_monitor import UPSObservedEvent, UPSStatusSnapshot


class AuditJournal:
    def __init__(self, config: AuditJournalConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def append(self, record_type: str, payload: dict[str, Any]) -> None:
        if not self._config.enabled:
            return
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
            "type": record_type,
            "payload": payload,
        }
        with self._config.path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def read_records(
        self,
        *,
        record_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._config.path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self._config.path.open("r", encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record_type is not None and record.get("type") != record_type:
                    continue
                records.append(record)

        if limit is not None and limit >= 0:
            return records[-limit:] if limit else []
        return records

    def record_snapshot(self, snapshot: UPSStatusSnapshot | None) -> None:
        if snapshot is None:
            self.append("ups_snapshot", {"available": False})
            return
        self.append(
            "ups_snapshot",
            {
                "available": True,
                "status_tokens": list(snapshot.status_tokens),
                "battery_charge_percent": snapshot.battery_charge_percent,
                "runtime_seconds": snapshot.runtime_seconds,
                "raw_fields": snapshot.raw_fields,
            },
        )

    def record_observed_event(self, observed_event: UPSObservedEvent) -> None:
        self.append(
            "observed_event",
            {
                "event": observed_event.event.value,
                "payload": observed_event.payload,
            },
        )

    def record_policy_decision(self, decision: PolicyDecision) -> None:
        shutdown_plan = None
        if decision.shutdown_plan is not None:
            shutdown_plan = [asdict(step) for step in decision.shutdown_plan.steps]
        self.append(
            "policy_decision",
            {
                "transition": {
                    "previous_state": decision.transition.previous_state.value,
                    "current_state": decision.transition.current_state.value,
                    "changed": decision.transition.changed,
                    "committed": decision.transition.committed,
                    "message": decision.transition.message,
                },
                "actions": decision.actions,
                "dispatch_results": [asdict(result) for result in decision.dispatch_results],
                "local_results": [asdict(result) for result in decision.local_results],
                "shutdown_plan": shutdown_plan,
            },
        )

    def record_runtime_event(self, event_type: str, **payload: Any) -> None:
        self.append(event_type, payload)