from __future__ import annotations

import tempfile
import threading
import unittest

from client_windows.config import WindowsClientConfig
from client_windows.listener import WindowsClientListener
from client_windows.state_manager import WindowsClientStateManager
from server.device_registry import DeviceRegistry, DeviceTarget, DeviceTransport
from server.event_dispatcher import EventDispatcher
from server.policy_engine import PowerPolicyEngine
from server.state_manager import OrchestratorStateManager
from shared.models import EventEnvelope, OrchestratorState, UPSPowerEvent


class EventDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.listener = WindowsClientListener(
            WindowsClientConfig(
                bind_host="127.0.0.1",
                bind_port=0,
                shared_token="secret-token",
                allowed_hosts={"127.0.0.1"},
            ),
            WindowsClientStateManager(),
        )
        self.server = self.listener.create_http_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_dispatch_sends_event_to_windows_client(self) -> None:
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="main-pc",
                    transport=DeviceTransport.WINDOWS_HTTP,
                    enabled=True,
                    address=f"http://{self.server.server_address[0]}:{self.server.server_address[1]}",
                    shared_token="secret-token",
                )
            ]
        )

        results = dispatcher.dispatch(
            EventEnvelope.create(
                event_id="evt-1",
                event_type=UPSPowerEvent.ONBATT,
                source="web-game-server",
                sequence=1,
            )
        )

        self.assertEqual(1, len(results))
        self.assertTrue(results[0].accepted)
        self.assertEqual(200, results[0].status_code)

    def test_dispatch_reports_unauthorized_when_token_is_wrong(self) -> None:
        dispatcher = EventDispatcher(
            targets=[
                DeviceTarget(
                    name="main-pc",
                    transport=DeviceTransport.WINDOWS_HTTP,
                    enabled=True,
                    address=f"http://{self.server.server_address[0]}:{self.server.server_address[1]}",
                    shared_token="wrong-token",
                )
            ]
        )

        results = dispatcher.dispatch(
            EventEnvelope.create(
                event_id="evt-2",
                event_type=UPSPowerEvent.ONBATT,
                source="web-game-server",
                sequence=2,
            )
        )

        self.assertFalse(results[0].accepted)
        self.assertEqual(401, results[0].status_code)

    def test_policy_engine_dispatches_onbatt_event(self) -> None:
        dispatcher = EventDispatcher.from_registry(
            DeviceRegistry(
                devices=[
                    DeviceTarget(
                        name="main-pc",
                        transport=DeviceTransport.WINDOWS_HTTP,
                        enabled=True,
                        address=f"http://{self.server.server_address[0]}:{self.server.server_address[1]}",
                        shared_token="secret-token",
                    )
                ]
            )
        )
        state_manager = OrchestratorStateManager(f"{self.temp_dir.name}/shutdown.commit")
        state_manager.clear_commit()

        decision = PowerPolicyEngine(state_manager, dispatcher=dispatcher).evaluate_event(
            UPSPowerEvent.ONBATT,
            source="web-game-server",
            sequence=10,
            payload={"runtime_seconds": 300},
        )

        self.assertEqual(OrchestratorState.ON_BATTERY, decision.transition.current_state)
        self.assertEqual(1, len(decision.dispatch_results))
        self.assertTrue(decision.dispatch_results[0].accepted)


if __name__ == "__main__":
    unittest.main()