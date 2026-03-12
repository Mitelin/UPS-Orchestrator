from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from client_windows.config import WindowsClientConfig
from client_windows.notifications import NotificationService
from client_windows.power_actions import PowerActionResult, PowerActionRunner
from client_windows.state_manager import WindowsClientStateManager
from shared.models import EventEnvelope, UPSPowerEvent


@dataclass(slots=True)
class ListenerResponse:
    status: str
    state: dict[str, bool | int | None]
    message: str
    actions: list[dict[str, object]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "state": self.state,
            "message": self.message,
            "actions": self.actions,
        }


@dataclass(slots=True)
class HTTPResponse:
    status_code: int
    body: dict[str, Any]


class RequestHandlingError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class WindowsClientListener:
    def __init__(
        self,
        config: WindowsClientConfig,
        state_manager: WindowsClientStateManager,
        power_actions: PowerActionRunner | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self._config = config
        self._state_manager = state_manager
        self._power_actions = power_actions or PowerActionRunner()
        self._notifications = notifications or NotificationService()
        self._logger = logging.getLogger(__name__)

    def handle_event(self, event: UPSPowerEvent, token: str, source_host: str) -> ListenerResponse:
        self._authenticate(token=token, source_host=source_host)

        if event is UPSPowerEvent.ONBATT:
            status, state = self._state_manager.on_onbatt()
            actions = [
                self._action_to_dict(self._notifications.show_warning(self._config.onbatt_warning_message), "show_warning"),
                self._result_to_dict(self._power_actions.enter_eco_mode()),
            ]
            return ListenerResponse(status=status, state=state, message="ONBATT handled", actions=actions)
        if event is UPSPowerEvent.ONLINE:
            status, state = self._state_manager.on_online()
            message = "ONLINE handled" if status == "accepted" else "ONLINE ignored because critical shutdown is pending"
            actions: list[dict[str, object]] = []
            if status == "accepted":
                actions.append(self._action_to_dict(self._config.online_info_message, "info"))
                actions.append(self._result_to_dict(self._power_actions.exit_eco_mode()))
            return ListenerResponse(status=status, state=state, message=message, actions=actions)
        if event is UPSPowerEvent.LOWBATT:
            shutdown_delay = self._config.lowbatt_shutdown_delay_seconds if self._config.lowbatt_shutdown_enabled else None
            status, state = self._state_manager.on_lowbatt(shutdown_delay_seconds=shutdown_delay)
            actions = [
                self._action_to_dict(
                    self._notifications.show_critical_warning(self._config.lowbatt_warning_message),
                    "show_critical_warning",
                )
            ]
            if self._config.lowbatt_shutdown_enabled:
                actions.append(
                    self._result_to_dict(
                        self._power_actions.schedule_shutdown(
                            delay_seconds=self._config.lowbatt_shutdown_delay_seconds,
                            command=self._config.shutdown_command,
                        )
                    )
                )
                message = f"LOWBATT handled; shutdown scheduled in {self._config.lowbatt_shutdown_delay_seconds}s"
            else:
                message = "LOWBATT handled"
            return ListenerResponse(status=status, state=state, message=message, actions=actions)

        raise ValueError(f"Unsupported event for Windows client: {event.value}")

    @staticmethod
    def _result_to_dict(result: PowerActionResult) -> dict[str, object]:
        return {
            "action": result.action,
            "accepted": result.accepted,
            "message": result.message,
        }

    @staticmethod
    def _action_to_dict(message: str, action: str) -> dict[str, object]:
        return {
            "action": action,
            "accepted": True,
            "message": message,
        }

    def process_http_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        source_host: str,
    ) -> HTTPResponse:
        normalized_headers = {key.lower(): value for key, value in headers.items()}

        if path == "/healthz":
            if method != "GET":
                raise RequestHandlingError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")
            return HTTPResponse(status_code=HTTPStatus.OK, body={"status": "ok"})

        endpoint_map = {
            "/onbatt": UPSPowerEvent.ONBATT,
            "/online": UPSPowerEvent.ONLINE,
            "/lowbatt": UPSPowerEvent.LOWBATT,
        }
        event = endpoint_map.get(path)
        if event is None:
            raise RequestHandlingError(HTTPStatus.NOT_FOUND, "Not found.")
        if method != "POST":
            raise RequestHandlingError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")

        token = normalized_headers.get("x-orchestrator-token", "")
        try:
            envelope_data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestHandlingError(HTTPStatus.BAD_REQUEST, f"Invalid JSON body: {error}") from error

        try:
            envelope = EventEnvelope.from_dict(envelope_data)
        except ValueError as error:
            raise RequestHandlingError(HTTPStatus.BAD_REQUEST, str(error)) from error

        if envelope.event_type is not event:
            raise RequestHandlingError(
                HTTPStatus.BAD_REQUEST,
                f"Event type {envelope.event_type.value} does not match endpoint {path}.",
            )

        self._logger.info("received event_id=%s event_type=%s from=%s", envelope.event_id, envelope.event_type.value, source_host)

        try:
            response = self.handle_event(event=envelope.event_type, token=token, source_host=source_host)
        except PermissionError as error:
            status_code = HTTPStatus.UNAUTHORIZED
            if str(error) == "Source host is not allowed.":
                status_code = HTTPStatus.FORBIDDEN
            raise RequestHandlingError(status_code, str(error)) from error

        return HTTPResponse(status_code=HTTPStatus.OK, body=response.to_dict())

    def create_http_server(self) -> ThreadingHTTPServer:
        listener = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._handle_request()

            def do_POST(self) -> None:
                self._handle_request()

            def log_message(self, format: str, *args: object) -> None:
                listener._logger.info("http %s", format % args)

            def _handle_request(self) -> None:
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length)
                headers = {key: value for key, value in self.headers.items()}

                try:
                    response = listener.process_http_request(
                        method=self.command,
                        path=self.path,
                        headers=headers,
                        body=body,
                        source_host=self.client_address[0],
                    )
                except RequestHandlingError as error:
                    response = HTTPResponse(
                        status_code=error.status_code,
                        body={"status": "error", "message": error.message},
                    )

                encoded = json.dumps(response.body).encode("utf-8")
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        return ThreadingHTTPServer((self._config.bind_host, self._config.bind_port), RequestHandler)

    def _authenticate(self, token: str, source_host: str) -> None:
        if token != self._config.shared_token:
            raise PermissionError("Invalid shared token.")
        if self._config.allowed_hosts and source_host not in self._config.allowed_hosts:
            raise PermissionError("Source host is not allowed.")
