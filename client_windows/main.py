from __future__ import annotations

import argparse
import logging
from typing import Any

from client_windows.config import WindowsClientConfig
from client_windows.listener import WindowsClientListener
from client_windows.state_manager import WindowsClientStateManager
from shared.models import EventEnvelope
from shared.models import UPSPowerEvent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UPS Orchestrator Windows client entrypoint")
    parser.add_argument(
        "command",
        choices=["serve", "simulate"],
        help="Action to run",
    )
    parser.add_argument(
        "--event",
        choices=[UPSPowerEvent.ONBATT.value, UPSPowerEvent.ONLINE.value, UPSPowerEvent.LOWBATT.value],
        help="Event name to simulate",
    )
    parser.add_argument("--token", help="Shared token override")
    parser.add_argument("--source-host", default="127.0.0.1", help="Source host for local simulation")
    parser.add_argument("--host", help="Bind host override for serve mode")
    parser.add_argument("--port", type=int, help="Bind port override for serve mode")
    return parser


def build_config(args: argparse.Namespace) -> WindowsClientConfig:
    config = WindowsClientConfig.from_env()
    if args.token:
        config.shared_token = args.token
    if args.host:
        config.bind_host = args.host
    if args.port is not None:
        config.bind_port = args.port
    return config


def build_simulated_body(event: UPSPowerEvent) -> dict[str, Any]:
    return EventEnvelope.create(
        event_id=f"sim-{event.value.lower()}",
        event_type=event,
        source="local-simulator",
        sequence=1,
        payload={"message": f"Simulated {event.value} event"},
    ).to_dict()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = build_config(args)
    listener = WindowsClientListener(config=config, state_manager=WindowsClientStateManager())

    if args.command == "serve":
        server = listener.create_http_server()
        logging.info("listening on %s:%s", config.bind_host, config.bind_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("shutting down listener")
        finally:
            server.server_close()
        return 0

    if not args.event:
        parser.error("--event is required for simulate")

    event = UPSPowerEvent(args.event)
    simulation_config = WindowsClientConfig(
        bind_host=config.bind_host,
        bind_port=config.bind_port,
        shared_token=config.shared_token,
        allowed_hosts={args.source_host},
        onbatt_warning_message=config.onbatt_warning_message,
        lowbatt_warning_message=config.lowbatt_warning_message,
        online_info_message=config.online_info_message,
        lowbatt_shutdown_enabled=config.lowbatt_shutdown_enabled,
        lowbatt_shutdown_delay_seconds=config.lowbatt_shutdown_delay_seconds,
        shutdown_command=config.shutdown_command,
    )
    simulation_listener = WindowsClientListener(simulation_config, WindowsClientStateManager())
    endpoint_map = {
        UPSPowerEvent.ONBATT: "/onbatt",
        UPSPowerEvent.ONLINE: "/online",
        UPSPowerEvent.LOWBATT: "/lowbatt",
    }
    http_response = simulation_listener.process_http_request(
        method="POST",
        path=endpoint_map[event],
        headers={"X-Orchestrator-Token": simulation_config.shared_token},
        body=__import__("json").dumps(build_simulated_body(event)).encode("utf-8"),
        source_host=args.source_host,
    )
    logging.info("status_code=%s body=%s", http_response.status_code, http_response.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
