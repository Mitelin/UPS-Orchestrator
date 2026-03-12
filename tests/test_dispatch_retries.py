from __future__ import annotations

import io
import logging
import unittest
from urllib import error, request

from server.device_registry import DeviceTarget, DeviceTransport
from server.event_dispatcher import CommandExecutionResult, CommandRunner, EventDispatcher, HTTPClient
from shared.models import EventEnvelope, UPSPowerEvent


class SequencedCommandRunner(CommandRunner):
    def __init__(self, results: list[CommandExecutionResult]) -> None:
        self._results = results
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout_seconds: float) -> CommandExecutionResult:
        self.commands.append(command)
        if not self._results:
            raise AssertionError("No fake command result configured.")
        return self._results.pop(0)


class FakeHTTPResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class SequencedHTTPClient(HTTPClient):
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.requests: list[request.Request] = []

    def open(self, http_request: request.Request, timeout_seconds: float):
        self.requests.append(http_request)
        if not self._responses:
            raise AssertionError("No fake HTTP response configured.")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


class DispatchRetryTests(unittest.TestCase):
    def test_ssh_dispatch_retries_after_transient_failure(self) -> None:
        runner = SequencedCommandRunner(
            [
                CommandExecutionResult(return_code=255, stdout="", stderr="temporary ssh failure\n"),
                CommandExecutionResult(return_code=0, stdout="shutdown scheduled\n", stderr=""),
            ]
        )
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="nas",
                    transport=DeviceTransport.SSH,
                    enabled=True,
                    address="nas.local",
                    supported_events=(UPSPowerEvent.LOWBATT,),
                    ssh_user="admin",
                    ssh_port=22,
                    shutdown_command="sudo /sbin/shutdown -h now",
                )
            ],
            command_runner=runner,
            retry_attempts=2,
            retry_delay_seconds=0,
        )

        results = dispatcher.dispatch(
            EventEnvelope.create("evt-lowbatt-retry", UPSPowerEvent.LOWBATT, "web-game-server", sequence=1)
        )

        self.assertTrue(results[0].accepted)
        self.assertEqual(2, results[0].attempts)
        self.assertEqual(2, len(runner.commands))

    def test_http_dispatch_retries_after_url_error_then_succeeds(self) -> None:
        http_client = SequencedHTTPClient(
            [
                error.URLError("temporary outage"),
                FakeHTTPResponse(200, b'{"status":"accepted","message":"ONBATT handled"}'),
            ]
        )
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="main-pc",
                    transport=DeviceTransport.WINDOWS_HTTP,
                    enabled=True,
                    address="http://main-pc.local:8765",
                    shared_token="secret-token",
                )
            ],
            http_client=http_client,
            retry_attempts=2,
            retry_delay_seconds=0,
        )

        results = dispatcher.dispatch(
            EventEnvelope.create("evt-onbatt-retry", UPSPowerEvent.ONBATT, "web-game-server", sequence=1)
        )

        self.assertTrue(results[0].accepted)
        self.assertEqual(2, results[0].attempts)
        self.assertEqual(2, len(http_client.requests))

    def test_dispatch_logs_structured_attempt_fields(self) -> None:
        logger = logging.getLogger("server.event_dispatcher")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            dispatcher = EventDispatcher(
                targets=[
                    DeviceTarget(
                        name="main-pc",
                        transport=DeviceTransport.WINDOWS_HTTP,
                        enabled=True,
                        address="http://main-pc.local:8765",
                        shared_token="secret-token",
                    )
                ],
                http_client=SequencedHTTPClient(
                    [FakeHTTPResponse(200, b'{"status":"accepted","message":"ONLINE handled"}')]
                ),
            )

            dispatcher.dispatch(
                EventEnvelope.create("evt-online-1", UPSPowerEvent.ONLINE, "web-game-server", sequence=1)
            )
        finally:
            logger.removeHandler(handler)

        log_output = stream.getvalue()
        self.assertIn("dispatch transport=windows_http", log_output)
        self.assertIn("target=main-pc", log_output)
        self.assertIn("event=ONLINE", log_output)


if __name__ == "__main__":
    unittest.main()