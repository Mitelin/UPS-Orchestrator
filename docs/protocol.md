# UPS Orchestrator Protocol v1

## Purpose
This document defines the initial contract between the Linux orchestrator server and the Windows client.

## Scope
Included in v1:
- event names and payload format
- Windows client HTTP endpoints
- authentication requirements
- response format

Not included in v1:
- bidirectional streaming
- message queues
- remote commit rollback

## Event model

### Server-internal events
- `ONBATT`
- `ONLINE`
- `LOWBATT`
- `SHUTDOWN_COMMIT`

### Windows client remote commands in v1
- `ONBATT`
- `ONLINE`
- `LOWBATT`

`SHUTDOWN_COMMIT` remains internal to the server in v1.

## Transport
- protocol: HTTP/1.1
- network scope: LAN only
- content type: `application/json`
- request method: `POST`

## Authentication
Each request must include:
- header `X-Orchestrator-Token: <shared-secret>`
- source IP matching the configured allowlist on the Windows client

If either check fails, the request must be rejected with `401` or `403`.

## Endpoints
- `POST /onbatt`
- `POST /online`
- `POST /lowbatt`
- `GET /healthz`

## Request body
All event endpoints accept the same JSON envelope.

```json
{
  "event_id": "evt-20260312-0001",
  "event_type": "ONBATT",
  "source": "web-game-server",
  "created_at": "2026-03-12T08:15:30Z",
  "sequence": 17,
  "payload": {
    "battery_charge_percent": 82,
    "runtime_seconds": 2640,
    "grace_period_seconds": 120,
    "message": "UPS switched to battery power"
  }
}
```

## Envelope fields
- `event_id`: unique identifier for deduplication and logs
- `event_type`: one of `ONBATT`, `ONLINE`, `LOWBATT`
- `source`: orchestrator hostname or logical node name
- `created_at`: UTC ISO-8601 timestamp
- `sequence`: monotonically increasing number per orchestrator runtime
- `payload`: free-form event details

## Endpoint semantics

### `POST /onbatt`
Expected behavior:
- enable local eco mode when enabled by local Windows client policy
- show user warning
- mark client state as on battery

### `POST /online`
Expected behavior:
- restore the previously active Windows power plan only if critical shutdown is not pending
- clear warning state where possible

### `POST /lowbatt`
Expected behavior:
- set `critical_shutdown_pending = true`
- show critical warning
- optionally start local shutdown countdown according to policy

## Response body
Successful responses should use `200 OK` with this format:

```json
{
  "status": "accepted",
  "state": {
    "eco_mode_active": true,
    "critical_shutdown_pending": false
  },
  "message": "ONBATT handled"
}
```

Rejected or ignored events may still return `200 OK` when they are valid but intentionally ignored, for example a late `ONLINE` after `LOWBATT` commit.

Example ignored response:

```json
{
  "status": "ignored",
  "state": {
    "eco_mode_active": true,
    "critical_shutdown_pending": true
  },
  "message": "ONLINE ignored because critical shutdown is pending"
}
```

## Error handling
- `400 Bad Request`: invalid JSON or missing fields
- `401 Unauthorized`: missing or invalid token
- `403 Forbidden`: source host not allowed
- `405 Method Not Allowed`: unsupported method
- `500 Internal Server Error`: unexpected local failure

## Ordering and idempotency
- the orchestrator must send events in order
- the Windows client should log repeated `event_id` values
- repeated `ONBATT` should be safe to ignore
- `ONLINE` after local critical shutdown pending must be ignored

## Client recovery note

The Windows client may persist the previously active Windows power plan when entering eco mode.

If the machine restarts before `ONLINE` is received, the client may restore that saved plan during its next startup before continuing normal listener operation.

## Logging requirements
Both sides must log:
- request receipt time
- event id and type
- authentication result
- local state before and after handling
- final outcome: accepted, ignored, or rejected
