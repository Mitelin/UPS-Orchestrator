from __future__ import annotations

import http.client
import json
import threading
import unittest

from client_windows.config import WindowsClientConfig
from client_windows.listener import WindowsClientListener
from client_windows.state_manager import WindowsClientStateManager
from shared.models import EventEnvelope, UPSPowerEvent


class WindowsListenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = WindowsClientConfig(
            bind_host="127.0.0.1",
            bind_port=0,
            shared_token="secret-token",
            allowed_hosts={"127.0.0.1"},
        )
        self.listener = WindowsClientListener(self.config, WindowsClientStateManager())
        self.server = self.listener.create_http_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_healthz_endpoint(self) -> None:
        status, payload = self._request("GET", "/healthz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, payload)

    def test_onbatt_endpoint_accepts_valid_event(self) -> None:
        status, payload = self._request(
            "POST",
            "/onbatt",
            body=self._event_body(UPSPowerEvent.ONBATT),
            headers={"X-Orchestrator-Token": "secret-token"},
        )

        self.assertEqual(200, status)
        self.assertEqual("accepted", payload["status"])
        self.assertTrue(payload["state"]["eco_mode_active"])
        self.assertEqual(2, len(payload["actions"]))

    def test_online_is_ignored_after_lowbatt(self) -> None:
        self._request(
            "POST",
            "/lowbatt",
            body=self._event_body(UPSPowerEvent.LOWBATT, event_id="evt-lowbatt"),
            headers={"X-Orchestrator-Token": "secret-token"},
        )

        status, payload = self._request(
            "POST",
            "/online",
            body=self._event_body(UPSPowerEvent.ONLINE, event_id="evt-online"),
            headers={"X-Orchestrator-Token": "secret-token"},
        )

        self.assertEqual(200, status)
        self.assertEqual("ignored", payload["status"])
        self.assertTrue(payload["state"]["critical_shutdown_pending"])
        self.assertEqual([], payload["actions"])

    def test_invalid_token_returns_unauthorized(self) -> None:
        status, payload = self._request(
            "POST",
            "/onbatt",
            body=self._event_body(UPSPowerEvent.ONBATT),
            headers={"X-Orchestrator-Token": "wrong-token"},
        )

        self.assertEqual(401, status)
        self.assertEqual("error", payload["status"])

    def test_event_type_mismatch_returns_bad_request(self) -> None:
        status, payload = self._request(
            "POST",
            "/onbatt",
            body=self._event_body(UPSPowerEvent.ONLINE),
            headers={"X-Orchestrator-Token": "secret-token"},
        )

        self.assertEqual(400, status)
        self.assertEqual("error", payload["status"])

    def test_lowbatt_can_return_scheduled_shutdown_details(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        self.config = WindowsClientConfig(
            bind_host="127.0.0.1",
            bind_port=0,
            shared_token="secret-token",
            allowed_hosts={"127.0.0.1"},
            lowbatt_shutdown_enabled=True,
            lowbatt_shutdown_delay_seconds=60,
            shutdown_command="shutdown /s /t 60 /f",
        )
        self.listener = WindowsClientListener(self.config, WindowsClientStateManager())
        self.server = self.listener.create_http_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        status, payload = self._request(
            "POST",
            "/lowbatt",
            body=self._event_body(UPSPowerEvent.LOWBATT),
            headers={"X-Orchestrator-Token": "secret-token"},
        )

        self.assertEqual(200, status)
        self.assertTrue(payload["state"]["shutdown_scheduled"])
        self.assertEqual(60, payload["state"]["shutdown_delay_seconds"])
        self.assertIn("shutdown scheduled in 60s", payload["message"])

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(self.server.server_address[0], self.server.server_address[1], timeout=5)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = dict(headers or {})
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(payload))
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        raw_body = response.read()
        connection.close()
        return response.status, json.loads(raw_body.decode("utf-8"))

    def _event_body(self, event: UPSPowerEvent, event_id: str = "evt-1") -> dict[str, object]:
        return EventEnvelope.create(
            event_id=event_id,
            event_type=event,
            source="web-game-server",
            sequence=1,
            payload={"message": f"{event.value} test"},
        ).to_dict()


if __name__ == "__main__":
    unittest.main()