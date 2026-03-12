from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from urllib import error, request

from server.device_registry import DeviceRegistry, DeviceTarget, DeviceTransport
from shared.models import EventEnvelope, UPSPowerEvent


@dataclass(slots=True)
class DispatchResult:
    target: str
    accepted: bool
    message: str
    status_code: int | None = None
    attempts: int = 1
    transport: str = "unknown"


@dataclass(slots=True)
class CommandExecutionResult:
    return_code: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, command: list[str], timeout_seconds: float) -> CommandExecutionResult:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandExecutionResult(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class HTTPClient:
    def open(self, http_request: request.Request, timeout_seconds: float):
        return request.urlopen(http_request, timeout=timeout_seconds)


@dataclass(slots=True)
class EventDispatcher:
    targets: list[DeviceTarget] = field(default_factory=list)
    request_timeout_seconds: float = 5.0
    retry_attempts: int = 1
    retry_delay_seconds: float = 0.0
    command_runner: CommandRunner = field(default_factory=CommandRunner)
    http_client: HTTPClient = field(default_factory=HTTPClient)
    sleep_func: callable = time.sleep
    _logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def dispatch(self, envelope: EventEnvelope) -> list[DispatchResult]:
        eligible_targets = [target for target in self.targets if self._target_supports_event(target, envelope.event_type)]
        if envelope.event_type is UPSPowerEvent.LOWBATT:
            eligible_targets.sort(key=lambda target: target.shutdown_priority)
        return [self._dispatch_to_target(target, envelope) for target in eligible_targets]

    @classmethod
    def from_registry(
        cls,
        registry: DeviceRegistry,
        request_timeout_seconds: float = 5.0,
        retry_attempts: int = 1,
        retry_delay_seconds: float = 0.0,
    ) -> "EventDispatcher":
        return cls(
            targets=registry.enabled_targets(),
            request_timeout_seconds=request_timeout_seconds,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )

    def _dispatch_to_target(self, target: DeviceTarget, envelope: EventEnvelope) -> DispatchResult:
        if target.transport is DeviceTransport.WINDOWS_HTTP:
            return self._dispatch_windows_http_with_retry(target, envelope)
        if target.transport is DeviceTransport.SSH:
            return self._dispatch_ssh_with_retry(target, envelope)
        return DispatchResult(
            target=target.name,
            accepted=False,
            message=f"Transport {target.transport.value} is not implemented yet.",
            transport=target.transport.value,
        )

    def _target_supports_event(self, target: DeviceTarget, event: UPSPowerEvent) -> bool:
        if target.supported_events:
            return event in target.supported_events
        if target.transport is DeviceTransport.WINDOWS_HTTP:
            return event in {UPSPowerEvent.ONBATT, UPSPowerEvent.ONLINE, UPSPowerEvent.LOWBATT}
        if target.transport is DeviceTransport.SSH:
            return event is UPSPowerEvent.LOWBATT
        return False

    def _dispatch_ssh_with_retry(self, target: DeviceTarget, envelope: EventEnvelope) -> DispatchResult:
        last_result: DispatchResult | None = None
        for attempt in range(1, self.retry_attempts + 1):
            last_result = self._dispatch_ssh(target, envelope, attempt)
            if last_result.accepted or attempt >= self.retry_attempts or not self._should_retry_ssh(last_result):
                return last_result
            self._sleep_before_retry(target, envelope, attempt, last_result)
        return last_result or DispatchResult(target=target.name, accepted=False, message="SSH dispatch failed.", transport=target.transport.value)

    def _dispatch_ssh(self, target: DeviceTarget, envelope: EventEnvelope, attempt: int) -> DispatchResult:
        if envelope.event_type is not UPSPowerEvent.LOWBATT:
            return DispatchResult(
                target=target.name,
                accepted=False,
                message=f"Event {envelope.event_type.value} is not dispatchable to SSH target.",
                attempts=attempt,
                transport=target.transport.value,
            )
        if not target.ssh_user or not target.ssh_port or not target.shutdown_command:
            return DispatchResult(
                target=target.name,
                accepted=False,
                message="SSH target configuration is incomplete.",
                attempts=attempt,
                transport=target.transport.value,
            )

        command = [
            "ssh",
            "-p",
            str(target.ssh_port),
            f"{target.ssh_user}@{target.address}",
            target.shutdown_command,
        ]
        try:
            execution_result = self.command_runner.run(command, timeout_seconds=self.request_timeout_seconds)
        except subprocess.TimeoutExpired:
            result = DispatchResult(
                target=target.name,
                accepted=False,
                message="SSH dispatch timed out.",
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result
        except OSError as error_info:
            result = DispatchResult(
                target=target.name,
                accepted=False,
                message=f"SSH dispatch failed to start: {error_info}",
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result

        if execution_result.return_code == 0:
            stdout = execution_result.stdout.strip()
            result = DispatchResult(
                target=target.name,
                accepted=True,
                message=stdout or "Remote shutdown command executed successfully.",
                status_code=0,
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result

        stderr = execution_result.stderr.strip() or execution_result.stdout.strip() or "Remote shutdown command failed."
        result = DispatchResult(
            target=target.name,
            accepted=False,
            message=stderr,
            status_code=execution_result.return_code,
            attempts=attempt,
            transport=target.transport.value,
        )
        self._log_dispatch_attempt(target, envelope, result, attempt)
        return result

    def _dispatch_windows_http_with_retry(self, target: DeviceTarget, envelope: EventEnvelope) -> DispatchResult:
        last_result: DispatchResult | None = None
        for attempt in range(1, self.retry_attempts + 1):
            last_result = self._dispatch_windows_http(target, envelope, attempt)
            if last_result.accepted or attempt >= self.retry_attempts or not self._should_retry_http(last_result):
                return last_result
            self._sleep_before_retry(target, envelope, attempt, last_result)
        return last_result or DispatchResult(target=target.name, accepted=False, message="HTTP dispatch failed.", transport=target.transport.value)

    def _dispatch_windows_http(self, target: DeviceTarget, envelope: EventEnvelope, attempt: int) -> DispatchResult:
        endpoint_map = {
            "ONBATT": "/onbatt",
            "ONLINE": "/online",
            "LOWBATT": "/lowbatt",
        }
        path = endpoint_map.get(envelope.event_type.value)
        if path is None:
            result = DispatchResult(
                target=target.name,
                accepted=False,
                message=f"Event {envelope.event_type.value} is not dispatchable to Windows client.",
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result

        payload = json.dumps(envelope.to_dict()).encode("utf-8")
        http_request = request.Request(
            url=f"{target.address.rstrip('/')}{path}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Orchestrator-Token": target.shared_token or "",
            },
            method="POST",
        )

        try:
            with self.http_client.open(http_request, timeout_seconds=self.request_timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
                body = json.loads(raw_body)
                accepted = body.get("status") in {"accepted", "ignored"}
                message = str(body.get("message", "No message returned."))
                result = DispatchResult(
                    target=target.name,
                    accepted=accepted,
                    message=message,
                    status_code=response.status,
                    attempts=attempt,
                    transport=target.transport.value,
                )
                self._log_dispatch_attempt(target, envelope, result, attempt)
                return result
        except error.HTTPError as http_error:
            try:
                raw_error = http_error.read().decode("utf-8")
                error_body = json.loads(raw_error)
                message = str(error_body.get("message", http_error.reason))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(http_error.reason)
            finally:
                http_error.close()
            result = DispatchResult(
                target=target.name,
                accepted=False,
                message=message,
                status_code=http_error.code,
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result
        except error.URLError as url_error:
            result = DispatchResult(
                target=target.name,
                accepted=False,
                message=f"Dispatch failed: {url_error.reason}",
                attempts=attempt,
                transport=target.transport.value,
            )
            self._log_dispatch_attempt(target, envelope, result, attempt)
            return result

    def _should_retry_http(self, result: DispatchResult) -> bool:
        return result.status_code is None or (result.status_code >= 500)

    def _should_retry_ssh(self, result: DispatchResult) -> bool:
        return result.status_code is None or result.status_code == 255

    def _sleep_before_retry(
        self,
        target: DeviceTarget,
        envelope: EventEnvelope,
        attempt: int,
        result: DispatchResult,
    ) -> None:
        if self.retry_delay_seconds <= 0:
            return
        self._logger.warning(
            "dispatch_retry transport=%s target=%s event=%s attempt=%s next_attempt=%s status_code=%s message=%s",
            target.transport.value,
            target.name,
            envelope.event_type.value,
            attempt,
            attempt + 1,
            result.status_code,
            result.message,
        )
        self.sleep_func(self.retry_delay_seconds)

    def _log_dispatch_attempt(
        self,
        target: DeviceTarget,
        envelope: EventEnvelope,
        result: DispatchResult,
        attempt: int,
    ) -> None:
        outcome = "accepted" if result.accepted else "rejected"
        self._logger.info(
            "dispatch transport=%s target=%s event=%s attempt=%s outcome=%s status_code=%s message=%s",
            target.transport.value,
            target.name,
            envelope.event_type.value,
            attempt,
            outcome,
            result.status_code,
            result.message,
        )
