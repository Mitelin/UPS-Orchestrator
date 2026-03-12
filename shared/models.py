from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class UPSPowerEvent(StrEnum):
    ONBATT = "ONBATT"
    ONLINE = "ONLINE"
    LOWBATT = "LOWBATT"
    SHUTDOWN_COMMIT = "SHUTDOWN_COMMIT"


class OrchestratorState(StrEnum):
    NORMAL = "NORMAL"
    ON_BATTERY = "ON_BATTERY"
    CRITICAL_SHUTDOWN = "CRITICAL_SHUTDOWN"


@dataclass(slots=True, frozen=True)
class EventEnvelope:
    event_id: str
    event_type: UPSPowerEvent
    source: str
    created_at: str
    sequence: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        required_fields = ("event_id", "event_type", "source", "created_at")
        missing_fields = [field_name for field_name in required_fields if field_name not in data]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(f"Missing required event fields: {missing}")

        payload = data.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("Event payload must be a JSON object.")

        sequence = data.get("sequence")
        if sequence is not None and not isinstance(sequence, int):
            raise ValueError("Event sequence must be an integer when provided.")

        return cls(
            event_id=str(data["event_id"]),
            event_type=UPSPowerEvent(str(data["event_type"])),
            source=str(data["source"]),
            created_at=str(data["created_at"]),
            sequence=sequence,
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "created_at": self.created_at,
            "sequence": self.sequence,
            "payload": self.payload,
        }

    @classmethod
    def create(
        cls,
        event_id: str,
        event_type: UPSPowerEvent,
        source: str,
        sequence: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "EventEnvelope":
        return cls(
            event_id=event_id,
            event_type=event_type,
            source=source,
            created_at=datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
            sequence=sequence,
            payload=payload or {},
        )
