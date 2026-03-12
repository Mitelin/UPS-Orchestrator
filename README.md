# UPS-Orchestrator

Python project for a home-lab UPS power orchestration server and Windows client.

## What this project is

This repository implements a UPS orchestration system with one central Linux server and one Windows client.

- The Linux server is the single source of truth.
- The UPS is connected to the Linux server.
- The Windows Main PC runs a local HTTP client listener.
- Linux-side devices such as Raspberry and NAS are currently controlled directly from the server over SSH.
- `LOWBATT` is treated as an irreversible commit point for the current runtime.

## Current architecture

### Control plane

- `server/` contains the orchestrator runtime, UPS monitor, state machine, policy engine, dispatch layer, config loader, and audit journal.
- `client_windows/` contains the Windows listener, local state manager, notifications, and optional local shutdown scheduling.
- `shared/` contains the shared event and state models used by both sides.

### Node roles

- `Web & Game Server` = Linux orchestrator server. It reads UPS state, decides what to do, dispatches events, and shuts itself down last.
- `Main PC` = Windows client. It receives `ONBATT`, `ONLINE`, and `LOWBATT` events over HTTP and can enter eco mode or schedule local shutdown.
- `NAS` = Linux-side managed target. The server reaches it directly over SSH during critical shutdown.
- `Raspberry` = Linux-side managed target. The server reaches it directly over SSH during critical shutdown.

### Important design note: there is no separate Linux client yet

The current implementation does not run a dedicated Linux agent on Raspberry or NAS.

Instead:

- the Linux server dispatches directly to Linux targets over SSH
- the Windows machine is the only actual client daemon in v1
- NAS and Raspberry are modeled as managed shutdown targets, not as local always-running client services

This keeps the first deployment simpler and removes one whole moving part from the critical shutdown path.

## Functional status

## Current status
- protocol v1 draft exists in `docs/protocol.md`
- project skeleton exists for server, Windows client, and shared models
- state machine and commit logic are covered by unit tests
- Windows client has a real HTTP listener skeleton with `/healthz`, `/onbatt`, `/online`, and `/lowbatt`
- server simulate mode can optionally dispatch real HTTP events to the Windows client
- Linux-side LOWBATT shutdown dispatch is prepared through SSH targets for NAS and Raspberry
- NUT-compatible UPS polling exists in observe-only mode with normalized `ONBATT`, `ONLINE`, and `LOWBATT` events
- critical shutdown now produces an explicit ordered shutdown plan and schedules orchestrator self-shutdown as the final step
- dispatcher now supports retry attempts and structured per-attempt logging for HTTP and SSH transports
- NUT monitor now supports poll-based debounce to suppress brief UPS state flaps and duplicate event emission
- server now has a long-running `serve` mode that ties UPS polling, policy evaluation, local actions, and dispatch together
- configuration can now be loaded from TOML with environment variables overriding file values
- Windows client now supports a configurable LOWBATT shutdown countdown policy for the Main PC
- server now supports a persistent JSONL audit journal for snapshots, normalized events, and policy decisions
- server CLI can now print and filter persisted journal records for diagnostics

## Implemented behavior

### Server

- file-backed orchestrator state machine with `NORMAL`, `ON_BATTERY`, and `CRITICAL_SHUTDOWN`
- persistent shutdown commit marker so `LOWBATT` survives restarts as committed state
- NUT-compatible UPS polling through `upsc`
- debounce for noisy power-state and low-battery transitions
- policy engine for `ONBATT`, `ONLINE`, and `LOWBATT`
- ordered remote shutdown for NAS and Raspberry
- optional Windows dispatch during `ONBATT`, `ONLINE`, and `LOWBATT`
- structured dispatch retries for HTTP and SSH targets
- long-running `serve` mode for real runtime polling
- JSONL audit journal with CLI inspection

### Windows client

- authenticated HTTP listener with `/healthz`, `/onbatt`, `/online`, and `/lowbatt`
- local state tracking for eco mode and critical shutdown pending state
- placeholder notification actions
- optional LOWBATT shutdown countdown policy for the Main PC

### Linux-side targets

- SSH-based shutdown execution for NAS and Raspberry
- per-target enable/disable and addressing from TOML or environment variables
- ordered execution during `LOWBATT`

## Project layout

```text
server/            Linux orchestrator server
client_windows/    Windows client listener and local policy
shared/            Shared event and state models
tests/             Unit and integration tests
config/            Example TOML configuration
docs/              Protocol and supporting documents
```

## Runtime model

### Event flow

1. The Linux server reads UPS status.
2. UPS state is normalized into internal events such as `ONBATT`, `ONLINE`, or `LOWBATT`.
3. The server state machine evaluates the event.
4. The policy engine produces local actions, remote dispatches, and shutdown plans.
5. Results are logged and optionally persisted to the audit journal.

### Shutdown semantics

- `ONBATT` means the system is on battery, but shutdown is still reversible.
- `ONLINE` returns the system to normal only if critical shutdown is not already committed.
- `LOWBATT` commits critical shutdown and becomes a point of no return for the current runtime.

### Ordered critical shutdown

The current shutdown order is:

1. final critical warning
2. NAS shutdown
3. Raspberry shutdown
4. optional Main PC shutdown
5. Linux orchestrator self-shutdown

## Configuration model

Configuration can be loaded from TOML and then overridden by environment variables.

- starter config: `config/example.toml`
- server config loader: `server/config.py`
- Windows client config loader: `client_windows/config.py`

The intended precedence is:

1. built-in defaults
2. TOML file
3. environment variables

## Deploy testing readiness

The codebase is ready for a first controlled deploy test in a home-lab environment.

What is already ready:

- automated test coverage for server state transitions, UPS normalization, dispatching, runtime loop, config loading, Windows policy, and audit journal
- bounded runtime mode for safe testing
- `simulate` command for non-UPS-triggered event testing
- `observe_only` support for non-destructive real UPS observation

What is still intentionally lightweight:

- no `systemd` unit files yet
- no Windows service wrapper yet
- no log rotation yet for the JSONL journal
- no dedicated Linux client daemon yet

## Recommended first deploy test plan

### Step 1: run only in observe-only mode

- configure the real UPS in `config/example.toml` or a local copy
- keep `observe_only = true`
- run the server with `serve`
- confirm that snapshots and normalized events appear in logs and audit journal

### Step 2: test simulated policy decisions

- run `simulate --event ONBATT`
- run `simulate --event ONLINE`
- run `simulate --event LOWBATT`
- confirm state transitions, dispatch logs, and audit journal entries

### Step 3: test remote dispatch without destructive server self-shutdown

- enable Windows client and SSH targets
- keep server self-shutdown disabled
- test `simulate --event LOWBATT --dispatch`
- verify NAS and Raspberry receive the expected SSH shutdown command in a controlled environment

### Step 4: test real UPS polling with policy application

- switch from observe-only to applied policy only after previous steps are verified
- keep careful journal output from the first real battery event
- only then consider enabling server self-shutdown

## Operational commands

## Local commands
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m server.main status
.\.venv\Scripts\python.exe -m server.main simulate --event ONBATT
.\.venv\Scripts\python.exe -m server.main poll-ups
.\.venv\Scripts\python.exe -m server.main serve
.\.venv\Scripts\python.exe -m server.main journal --limit 10
.\.venv\Scripts\python.exe -m client_windows.main serve --host 127.0.0.1 --port 8765 --token change-me
```

## Useful command patterns

### Inspect current state

```powershell
.\.venv\Scripts\python.exe -m server.main status
```

### Clear committed shutdown marker

```powershell
.\.venv\Scripts\python.exe -m server.main clear-commit
```

### Print the latest journal records

```powershell
.\.venv\Scripts\python.exe -m server.main journal --limit 20
```

### Print only policy decisions from the journal

```powershell
.\.venv\Scripts\python.exe -m server.main journal --journal-type policy_decision --limit 10
```

## Example Windows LOWBATT shutdown policy
```powershell
$env:UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_DELAY_SECONDS="90"
$env:UPS_ORCHESTRATOR_WINDOWS_SHUTDOWN_COMMAND="shutdown /s /t 90 /f"
.\.venv\Scripts\python.exe -m client_windows.main serve --host 127.0.0.1 --port 8765 --token change-me
```

## Example dispatch flow
```powershell
$env:UPS_ORCHESTRATOR_WINDOWS_CLIENT_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_CLIENT_URL="http://127.0.0.1:8765"
$env:UPS_ORCHESTRATOR_SHARED_TOKEN="change-me"
$env:UPS_ORCHESTRATOR_DISPATCH_RETRY_ATTEMPTS="3"
$env:UPS_ORCHESTRATOR_DISPATCH_RETRY_DELAY_SECONDS="1"
.\.venv\Scripts\python.exe -m server.main simulate --event ONBATT --dispatch
```

## Example Linux target configuration
```powershell
$env:UPS_ORCHESTRATOR_NAS_ENABLED="true"
$env:UPS_ORCHESTRATOR_NAS_HOST="nas.local"
$env:UPS_ORCHESTRATOR_NAS_USER="admin"
$env:UPS_ORCHESTRATOR_RASPBERRY_ENABLED="true"
.\.venv\Scripts\python.exe -m server.main serve
```

## Example TOML config usage
```powershell
.\.venv\Scripts\python.exe -m server.main --config .\config\example.toml status
.\.venv\Scripts\python.exe -m server.main --config .\config\example.toml serve --max-iterations 3
```

The repository includes a starter config at `config/example.toml`.

## Example audit journal override
```powershell
$env:UPS_ORCHESTRATOR_AUDIT_JOURNAL_ENABLED="true"
$env:UPS_ORCHESTRATOR_AUDIT_JOURNAL_PATH=".runtime\audit-journal.jsonl"
.\.venv\Scripts\python.exe -m server.main --config .\config\example.toml simulate --event ONBATT
.\.venv\Scripts\python.exe -m server.main --config .\config\example.toml journal --journal-type policy_decision --limit 5
```

## Example bounded runtime loop for testing
```powershell
$env:UPS_ORCHESTRATOR_NUT_ENABLED="true"
$env:UPS_ORCHESTRATOR_RASPBERRY_HOST="raspberry.local"
$env:UPS_ORCHESTRATOR_OBSERVE_ONLY="false"
$env:UPS_ORCHESTRATOR_POLL_INTERVAL_SECONDS="2"
.\.venv\Scripts\python.exe -m server.main serve --max-iterations 3
.\.venv\Scripts\python.exe -m server.main simulate --event LOWBATT --dispatch
```

## Example critical shutdown timing configuration
```powershell
$env:UPS_ORCHESTRATOR_INCLUDE_WINDOWS_CLIENT_SHUTDOWN="true"
$env:UPS_ORCHESTRATOR_NAS_SHUTDOWN_DELAY_SECONDS="5"
$env:UPS_ORCHESTRATOR_RASPBERRY_SHUTDOWN_DELAY_SECONDS="15"
$env:UPS_ORCHESTRATOR_WINDOWS_SHUTDOWN_DELAY_SECONDS="30"
$env:UPS_ORCHESTRATOR_SERVER_SHUTDOWN_DELAY_SECONDS="45"
.\.venv\Scripts\python.exe -m server.main simulate --event LOWBATT --dispatch
```

## Example NUT observe-only polling
```powershell
$env:UPS_ORCHESTRATOR_NUT_ENABLED="true"
$env:UPS_ORCHESTRATOR_NUT_DEVICE="ups@localhost"
$env:UPS_ORCHESTRATOR_NUT_POWER_STATE_DEBOUNCE_POLLS="2"
$env:UPS_ORCHESTRATOR_NUT_LOW_BATTERY_DEBOUNCE_POLLS="2"
.\.venv\Scripts\python.exe -m server.main poll-ups
```

## Example NUT polling with policy application
```powershell
$env:UPS_ORCHESTRATOR_NUT_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_CLIENT_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_CLIENT_URL="http://127.0.0.1:8765"
$env:UPS_ORCHESTRATOR_SHARED_TOKEN="change-me"
.\.venv\Scripts\python.exe -m server.main poll-ups --apply --dispatch
```