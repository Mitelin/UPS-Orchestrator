from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shared.models import UPSPowerEvent

from server.config import LinuxSSHDispatchConfig, ServerConfig


class DeviceTransport(StrEnum):
    WINDOWS_HTTP = "windows_http"
    SSH = "ssh"
    VENDOR_API = "vendor_api"


@dataclass(slots=True, frozen=True)
class DeviceTarget:
    name: str
    transport: DeviceTransport
    enabled: bool
    address: str
    shared_token: str | None = None
    supported_events: tuple[UPSPowerEvent, ...] = ()
    ssh_user: str | None = None
    ssh_port: int | None = None
    shutdown_command: str | None = None
    shutdown_priority: int = 100


class DeviceRegistry:
    def __init__(self, devices: list[DeviceTarget]) -> None:
        self._devices = devices

    @classmethod
    def from_config(cls, config: ServerConfig) -> "DeviceRegistry":
        return cls(
            devices=[
                DeviceTarget(
                    name=config.windows_client.name,
                    transport=DeviceTransport.WINDOWS_HTTP,
                    enabled=config.windows_client.enabled,
                    address=config.windows_client.base_url,
                    shared_token=config.windows_client.shared_token,
                    supported_events=(UPSPowerEvent.ONBATT, UPSPowerEvent.ONLINE, UPSPowerEvent.LOWBATT),
                    shutdown_priority=30,
                ),
                cls._linux_target_from_config(config.nas),
                cls._linux_target_from_config(config.raspberry),
            ]
        )

    def enabled_targets(self) -> list[DeviceTarget]:
        return [device for device in self._devices if device.enabled]

    def targets_for_event(self, event: UPSPowerEvent) -> list[DeviceTarget]:
        return [device for device in self.enabled_targets() if event in device.supported_events]

    @staticmethod
    def _linux_target_from_config(config: LinuxSSHDispatchConfig) -> DeviceTarget:
        return DeviceTarget(
            name=config.name,
            transport=DeviceTransport.SSH,
            enabled=config.enabled,
            address=config.host,
            supported_events=(UPSPowerEvent.LOWBATT,),
            ssh_user=config.user,
            ssh_port=config.port,
            shutdown_command=config.shutdown_command,
            shutdown_priority=10 if config.name == "nas" else 20,
        )
