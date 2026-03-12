from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(slots=True)
class WindowsClientConfig:
    bind_host: str = "0.0.0.0"
    bind_port: int = 8765
    shared_token: str = "change-me"
    allowed_hosts: set[str] = field(default_factory=set)
    onbatt_warning_message: str = "UPS switched to battery power. Eco mode enabled."
    lowbatt_warning_message: str = "UPS battery is critical. Prepare for shutdown."
    online_info_message: str = "Utility power restored."
    lowbatt_shutdown_enabled: bool = False
    lowbatt_shutdown_delay_seconds: int = 120
    shutdown_command: str = "shutdown /s /t 120 /f"

    @classmethod
    def from_env(cls) -> "WindowsClientConfig":
        allowed_hosts_raw = os.getenv("UPS_ORCHESTRATOR_ALLOWED_HOSTS", "")
        allowed_hosts = {
            host.strip()
            for host in allowed_hosts_raw.split(",")
            if host.strip()
        }
        return cls(
            bind_host=os.getenv("UPS_ORCHESTRATOR_CLIENT_HOST", "0.0.0.0"),
            bind_port=int(os.getenv("UPS_ORCHESTRATOR_CLIENT_PORT", "8765")),
            shared_token=os.getenv("UPS_ORCHESTRATOR_SHARED_TOKEN", "change-me"),
            allowed_hosts=allowed_hosts,
            onbatt_warning_message=os.getenv(
                "UPS_ORCHESTRATOR_WINDOWS_ONBATT_WARNING_MESSAGE",
                "UPS switched to battery power. Eco mode enabled.",
            ),
            lowbatt_warning_message=os.getenv(
                "UPS_ORCHESTRATOR_WINDOWS_LOWBATT_WARNING_MESSAGE",
                "UPS battery is critical. Prepare for shutdown.",
            ),
            online_info_message=os.getenv(
                "UPS_ORCHESTRATOR_WINDOWS_ONLINE_INFO_MESSAGE",
                "Utility power restored.",
            ),
            lowbatt_shutdown_enabled=os.getenv(
                "UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_ENABLED",
                "false",
            ).lower() in {"1", "true", "yes"},
            lowbatt_shutdown_delay_seconds=max(
                0,
                int(os.getenv("UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_DELAY_SECONDS", "120")),
            ),
            shutdown_command=os.getenv(
                "UPS_ORCHESTRATOR_WINDOWS_SHUTDOWN_COMMAND",
                "shutdown /s /t 120 /f",
            ),
        )
