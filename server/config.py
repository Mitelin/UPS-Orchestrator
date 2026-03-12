from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WindowsDispatchConfig:
    name: str = "main-pc"
    base_url: str = "http://127.0.0.1:8765"
    shared_token: str = "change-me"
    enabled: bool = False


@dataclass(slots=True)
class LinuxSSHDispatchConfig:
    name: str
    host: str
    user: str
    port: int = 22
    shutdown_command: str = "sudo /sbin/shutdown -h now"
    enabled: bool = False


@dataclass(slots=True)
class NUTMonitorConfig:
    enabled: bool = False
    device_name: str = "ups@localhost"
    command: str = "upsc"
    low_battery_charge_percent: int = 20
    low_battery_runtime_seconds: int = 300
    power_state_debounce_polls: int = 1
    low_battery_debounce_polls: int = 1


@dataclass(slots=True)
class LocalServerActionConfig:
    self_shutdown_enabled: bool = False
    self_shutdown_command: str = "sudo /sbin/shutdown -h now"


@dataclass(slots=True)
class CriticalShutdownConfig:
    include_windows_client_shutdown: bool = False
    warning_delay_seconds: int = 0
    nas_shutdown_delay_seconds: int = 5
    raspberry_shutdown_delay_seconds: int = 15
    windows_shutdown_delay_seconds: int = 30
    server_shutdown_delay_seconds: int = 45


@dataclass(slots=True)
class DispatchRuntimeConfig:
    timeout_seconds: float = 5.0
    retry_attempts: int = 1
    retry_delay_seconds: float = 0.0
    poll_interval_seconds: float = 5.0


@dataclass(slots=True)
class AuditJournalConfig:
    enabled: bool = False
    path: Path = Path(".runtime/audit-journal.jsonl")


@dataclass(slots=True)
class ServerConfig:
    node_name: str = "web-game-server"
    observe_only: bool = True
    grace_period_seconds: int = 120
    commit_marker_path: Path = Path(".runtime/shutdown.commit")
    log_level: str = "INFO"
    dispatch_runtime: DispatchRuntimeConfig = field(default_factory=DispatchRuntimeConfig)
    audit_journal: AuditJournalConfig = field(default_factory=AuditJournalConfig)
    windows_client: WindowsDispatchConfig = field(default_factory=WindowsDispatchConfig)
    nut_monitor: NUTMonitorConfig = field(default_factory=NUTMonitorConfig)
    local_server_actions: LocalServerActionConfig = field(default_factory=LocalServerActionConfig)
    critical_shutdown: CriticalShutdownConfig = field(default_factory=CriticalShutdownConfig)
    raspberry: LinuxSSHDispatchConfig = field(
        default_factory=lambda: LinuxSSHDispatchConfig(name="raspberry", host="raspberry", user="pi")
    )
    nas: LinuxSSHDispatchConfig = field(
        default_factory=lambda: LinuxSSHDispatchConfig(name="nas", host="nas", user="admin")
    )

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "ServerConfig":
        config = cls()
        if config_path is not None:
            config = cls.from_toml(config_path)
        return cls._apply_env_overrides(config)

    @classmethod
    def from_toml(cls, config_path: str | Path) -> "ServerConfig":
        path = Path(config_path)
        with path.open("rb") as file_handle:
            raw_config = tomllib.load(file_handle)
        return cls.from_mapping(raw_config)

    @classmethod
    def from_mapping(cls, raw_config: dict[str, Any]) -> "ServerConfig":
        config = cls()

        server_section = cls._get_section(raw_config, "server")
        dispatch_section = cls._get_section(raw_config, "dispatch_runtime")
        journal_section = cls._get_section(raw_config, "audit_journal")
        windows_section = cls._get_section(raw_config, "windows_client")
        nut_section = cls._get_section(raw_config, "nut_monitor")
        local_section = cls._get_section(raw_config, "local_server_actions")
        critical_section = cls._get_section(raw_config, "critical_shutdown")
        raspberry_section = cls._get_section(raw_config, "raspberry")
        nas_section = cls._get_section(raw_config, "nas")

        return cls(
            node_name=str(server_section.get("node_name", config.node_name)),
            observe_only=bool(server_section.get("observe_only", config.observe_only)),
            grace_period_seconds=int(server_section.get("grace_period_seconds", config.grace_period_seconds)),
            commit_marker_path=Path(server_section.get("commit_marker_path", str(config.commit_marker_path))),
            log_level=str(server_section.get("log_level", config.log_level)),
            dispatch_runtime=DispatchRuntimeConfig(
                timeout_seconds=float(dispatch_section.get("timeout_seconds", config.dispatch_runtime.timeout_seconds)),
                retry_attempts=max(1, int(dispatch_section.get("retry_attempts", config.dispatch_runtime.retry_attempts))),
                retry_delay_seconds=max(
                    0.0,
                    float(dispatch_section.get("retry_delay_seconds", config.dispatch_runtime.retry_delay_seconds)),
                ),
                poll_interval_seconds=max(
                    0.1,
                    float(dispatch_section.get("poll_interval_seconds", config.dispatch_runtime.poll_interval_seconds)),
                ),
            ),
            audit_journal=AuditJournalConfig(
                enabled=bool(journal_section.get("enabled", config.audit_journal.enabled)),
                path=Path(journal_section.get("path", str(config.audit_journal.path))),
            ),
            windows_client=WindowsDispatchConfig(
                name=str(windows_section.get("name", config.windows_client.name)),
                base_url=str(windows_section.get("base_url", config.windows_client.base_url)),
                shared_token=str(windows_section.get("shared_token", config.windows_client.shared_token)),
                enabled=bool(windows_section.get("enabled", config.windows_client.enabled)),
            ),
            nut_monitor=NUTMonitorConfig(
                enabled=bool(nut_section.get("enabled", config.nut_monitor.enabled)),
                device_name=str(nut_section.get("device_name", config.nut_monitor.device_name)),
                command=str(nut_section.get("command", config.nut_monitor.command)),
                low_battery_charge_percent=int(
                    nut_section.get("low_battery_charge_percent", config.nut_monitor.low_battery_charge_percent)
                ),
                low_battery_runtime_seconds=int(
                    nut_section.get("low_battery_runtime_seconds", config.nut_monitor.low_battery_runtime_seconds)
                ),
                power_state_debounce_polls=max(
                    1,
                    int(nut_section.get("power_state_debounce_polls", config.nut_monitor.power_state_debounce_polls)),
                ),
                low_battery_debounce_polls=max(
                    1,
                    int(nut_section.get("low_battery_debounce_polls", config.nut_monitor.low_battery_debounce_polls)),
                ),
            ),
            local_server_actions=LocalServerActionConfig(
                self_shutdown_enabled=bool(
                    local_section.get("self_shutdown_enabled", config.local_server_actions.self_shutdown_enabled)
                ),
                self_shutdown_command=str(
                    local_section.get("self_shutdown_command", config.local_server_actions.self_shutdown_command)
                ),
            ),
            critical_shutdown=CriticalShutdownConfig(
                include_windows_client_shutdown=bool(
                    critical_section.get(
                        "include_windows_client_shutdown",
                        config.critical_shutdown.include_windows_client_shutdown,
                    )
                ),
                warning_delay_seconds=int(
                    critical_section.get("warning_delay_seconds", config.critical_shutdown.warning_delay_seconds)
                ),
                nas_shutdown_delay_seconds=int(
                    critical_section.get(
                        "nas_shutdown_delay_seconds",
                        config.critical_shutdown.nas_shutdown_delay_seconds,
                    )
                ),
                raspberry_shutdown_delay_seconds=int(
                    critical_section.get(
                        "raspberry_shutdown_delay_seconds",
                        config.critical_shutdown.raspberry_shutdown_delay_seconds,
                    )
                ),
                windows_shutdown_delay_seconds=int(
                    critical_section.get(
                        "windows_shutdown_delay_seconds",
                        config.critical_shutdown.windows_shutdown_delay_seconds,
                    )
                ),
                server_shutdown_delay_seconds=int(
                    critical_section.get(
                        "server_shutdown_delay_seconds",
                        config.critical_shutdown.server_shutdown_delay_seconds,
                    )
                ),
            ),
            raspberry=LinuxSSHDispatchConfig(
                name=str(raspberry_section.get("name", config.raspberry.name)),
                host=str(raspberry_section.get("host", config.raspberry.host)),
                user=str(raspberry_section.get("user", config.raspberry.user)),
                port=int(raspberry_section.get("port", config.raspberry.port)),
                shutdown_command=str(
                    raspberry_section.get("shutdown_command", config.raspberry.shutdown_command)
                ),
                enabled=bool(raspberry_section.get("enabled", config.raspberry.enabled)),
            ),
            nas=LinuxSSHDispatchConfig(
                name=str(nas_section.get("name", config.nas.name)),
                host=str(nas_section.get("host", config.nas.host)),
                user=str(nas_section.get("user", config.nas.user)),
                port=int(nas_section.get("port", config.nas.port)),
                shutdown_command=str(nas_section.get("shutdown_command", config.nas.shutdown_command)),
                enabled=bool(nas_section.get("enabled", config.nas.enabled)),
            ),
        )

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls.load()

    @staticmethod
    def _get_section(raw_config: dict[str, Any], section_name: str) -> dict[str, Any]:
        section = raw_config.get(section_name, {})
        if not isinstance(section, dict):
            raise ValueError(f"Config section '{section_name}' must be a table.")
        return section

    @classmethod
    def _apply_env_overrides(cls, config: "ServerConfig") -> "ServerConfig":
        node_name = os.getenv("UPS_ORCHESTRATOR_NODE_NAME")
        if node_name is not None:
            config.node_name = node_name

        observe_only = cls._env_bool("UPS_ORCHESTRATOR_OBSERVE_ONLY")
        if observe_only is not None:
            config.observe_only = observe_only

        grace_period_seconds = cls._env_int("UPS_ORCHESTRATOR_GRACE_PERIOD_SECONDS")
        if grace_period_seconds is not None:
            config.grace_period_seconds = grace_period_seconds

        commit_marker = os.getenv("UPS_ORCHESTRATOR_COMMIT_MARKER")
        if commit_marker is not None:
            config.commit_marker_path = Path(commit_marker)

        log_level = os.getenv("UPS_ORCHESTRATOR_LOG_LEVEL")
        if log_level is not None:
            config.log_level = log_level

        audit_journal_enabled = cls._env_bool("UPS_ORCHESTRATOR_AUDIT_JOURNAL_ENABLED")
        if audit_journal_enabled is not None:
            config.audit_journal.enabled = audit_journal_enabled
        audit_journal_path = os.getenv("UPS_ORCHESTRATOR_AUDIT_JOURNAL_PATH")
        if audit_journal_path is not None:
            config.audit_journal.path = Path(audit_journal_path)

        timeout_seconds = cls._env_float("UPS_ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS")
        if timeout_seconds is not None:
            config.dispatch_runtime.timeout_seconds = timeout_seconds

        retry_attempts = cls._env_int("UPS_ORCHESTRATOR_DISPATCH_RETRY_ATTEMPTS")
        if retry_attempts is not None:
            config.dispatch_runtime.retry_attempts = max(1, retry_attempts)

        retry_delay_seconds = cls._env_float("UPS_ORCHESTRATOR_DISPATCH_RETRY_DELAY_SECONDS")
        if retry_delay_seconds is not None:
            config.dispatch_runtime.retry_delay_seconds = max(0.0, retry_delay_seconds)

        poll_interval_seconds = cls._env_float("UPS_ORCHESTRATOR_POLL_INTERVAL_SECONDS")
        if poll_interval_seconds is not None:
            config.dispatch_runtime.poll_interval_seconds = max(0.1, poll_interval_seconds)

        windows_client_name = os.getenv("UPS_ORCHESTRATOR_WINDOWS_CLIENT_NAME")
        if windows_client_name is not None:
            config.windows_client.name = windows_client_name
        windows_client_url = os.getenv("UPS_ORCHESTRATOR_WINDOWS_CLIENT_URL")
        if windows_client_url is not None:
            config.windows_client.base_url = windows_client_url
        shared_token = os.getenv("UPS_ORCHESTRATOR_SHARED_TOKEN")
        if shared_token is not None:
            config.windows_client.shared_token = shared_token
        windows_enabled = cls._env_bool("UPS_ORCHESTRATOR_WINDOWS_CLIENT_ENABLED")
        if windows_enabled is not None:
            config.windows_client.enabled = windows_enabled

        nut_enabled = cls._env_bool("UPS_ORCHESTRATOR_NUT_ENABLED")
        if nut_enabled is not None:
            config.nut_monitor.enabled = nut_enabled
        nut_device = os.getenv("UPS_ORCHESTRATOR_NUT_DEVICE")
        if nut_device is not None:
            config.nut_monitor.device_name = nut_device
        nut_command = os.getenv("UPS_ORCHESTRATOR_NUT_COMMAND")
        if nut_command is not None:
            config.nut_monitor.command = nut_command
        low_battery_charge_percent = cls._env_int("UPS_ORCHESTRATOR_NUT_LOW_BATTERY_CHARGE_PERCENT")
        if low_battery_charge_percent is not None:
            config.nut_monitor.low_battery_charge_percent = low_battery_charge_percent
        low_battery_runtime_seconds = cls._env_int("UPS_ORCHESTRATOR_NUT_LOW_BATTERY_RUNTIME_SECONDS")
        if low_battery_runtime_seconds is not None:
            config.nut_monitor.low_battery_runtime_seconds = low_battery_runtime_seconds
        power_state_debounce_polls = cls._env_int("UPS_ORCHESTRATOR_NUT_POWER_STATE_DEBOUNCE_POLLS")
        if power_state_debounce_polls is not None:
            config.nut_monitor.power_state_debounce_polls = max(1, power_state_debounce_polls)
        low_battery_debounce_polls = cls._env_int("UPS_ORCHESTRATOR_NUT_LOW_BATTERY_DEBOUNCE_POLLS")
        if low_battery_debounce_polls is not None:
            config.nut_monitor.low_battery_debounce_polls = max(1, low_battery_debounce_polls)

        self_shutdown_enabled = cls._env_bool("UPS_ORCHESTRATOR_SERVER_SELF_SHUTDOWN_ENABLED")
        if self_shutdown_enabled is not None:
            config.local_server_actions.self_shutdown_enabled = self_shutdown_enabled
        self_shutdown_command = os.getenv("UPS_ORCHESTRATOR_SERVER_SELF_SHUTDOWN_COMMAND")
        if self_shutdown_command is not None:
            config.local_server_actions.self_shutdown_command = self_shutdown_command

        include_windows_client_shutdown = cls._env_bool("UPS_ORCHESTRATOR_INCLUDE_WINDOWS_CLIENT_SHUTDOWN")
        if include_windows_client_shutdown is not None:
            config.critical_shutdown.include_windows_client_shutdown = include_windows_client_shutdown
        warning_delay_seconds = cls._env_int("UPS_ORCHESTRATOR_WARNING_DELAY_SECONDS")
        if warning_delay_seconds is not None:
            config.critical_shutdown.warning_delay_seconds = warning_delay_seconds
        nas_shutdown_delay_seconds = cls._env_int("UPS_ORCHESTRATOR_NAS_SHUTDOWN_DELAY_SECONDS")
        if nas_shutdown_delay_seconds is not None:
            config.critical_shutdown.nas_shutdown_delay_seconds = nas_shutdown_delay_seconds
        raspberry_shutdown_delay_seconds = cls._env_int("UPS_ORCHESTRATOR_RASPBERRY_SHUTDOWN_DELAY_SECONDS")
        if raspberry_shutdown_delay_seconds is not None:
            config.critical_shutdown.raspberry_shutdown_delay_seconds = raspberry_shutdown_delay_seconds
        windows_shutdown_delay_seconds = cls._env_int("UPS_ORCHESTRATOR_WINDOWS_SHUTDOWN_DELAY_SECONDS")
        if windows_shutdown_delay_seconds is not None:
            config.critical_shutdown.windows_shutdown_delay_seconds = windows_shutdown_delay_seconds
        server_shutdown_delay_seconds = cls._env_int("UPS_ORCHESTRATOR_SERVER_SHUTDOWN_DELAY_SECONDS")
        if server_shutdown_delay_seconds is not None:
            config.critical_shutdown.server_shutdown_delay_seconds = server_shutdown_delay_seconds

        cls._apply_linux_env_overrides(config.raspberry, "RASPBERRY")
        cls._apply_linux_env_overrides(config.nas, "NAS")
        return config

    @staticmethod
    def _apply_linux_env_overrides(config: LinuxSSHDispatchConfig, prefix: str) -> None:
        name = os.getenv(f"UPS_ORCHESTRATOR_{prefix}_NAME")
        if name is not None:
            config.name = name
        host = os.getenv(f"UPS_ORCHESTRATOR_{prefix}_HOST")
        if host is not None:
            config.host = host
        user = os.getenv(f"UPS_ORCHESTRATOR_{prefix}_USER")
        if user is not None:
            config.user = user
        port = os.getenv(f"UPS_ORCHESTRATOR_{prefix}_PORT")
        if port is not None:
            config.port = int(port)
        shutdown_command = os.getenv(f"UPS_ORCHESTRATOR_{prefix}_SHUTDOWN_COMMAND")
        if shutdown_command is not None:
            config.shutdown_command = shutdown_command
        enabled = ServerConfig._env_bool(f"UPS_ORCHESTRATOR_{prefix}_ENABLED")
        if enabled is not None:
            config.enabled = enabled

    @staticmethod
    def _env_bool(name: str) -> bool | None:
        value = os.getenv(name)
        if value is None:
            return None
        return value.lower() in {"1", "true", "yes"}

    @staticmethod
    def _env_int(name: str) -> int | None:
        value = os.getenv(name)
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _env_float(name: str) -> float | None:
        value = os.getenv(name)
        if value is None:
            return None
        return float(value)
