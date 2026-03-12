# UPS-Orchestrator

Python project for a home-lab UPS power orchestration server and Windows client.

## What this project is

This repository implements a UPS orchestration system with one central Linux server and one Windows client.

- The Linux server is the single source of truth.
- The UPS is connected to the Linux server.
- The Windows Main PC runs a local HTTP client listener.
- Linux-side devices such as Raspberry and NAS are currently controlled directly from the server over SSH.
- The Linux server does not use a local eco mode anymore.
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
- startup reconciliation clears the committed shutdown marker automatically after reboot only when the UPS is truly back `ONLINE`
- NUT-compatible UPS polling through `upsc`
- debounce for noisy power-state and low-battery transitions
- policy engine for `ONBATT`, `ONLINE`, and `LOWBATT`
- ordered remote shutdown for NAS and Raspberry
- optional Windows dispatch during `ONBATT`, `ONLINE`, and `LOWBATT`
- configurable pre-shutdown shell hook for custom app save/stop commands before server shutdown
- structured dispatch retries for HTTP and SSH targets
- long-running `serve` mode for real runtime polling
- JSONL audit journal with CLI inspection

### Windows client

- authenticated HTTP listener with `/healthz`, `/onbatt`, `/online`, and `/lowbatt`
- local state tracking for eco mode and critical shutdown pending state
- real Windows notification execution via toast with `msg.exe` fallback when platform actions are enabled
- eco mode support through `powercfg` power plan switching when platform actions are enabled
- startup reconciliation restores the previously active Windows power plan after reboot if eco mode had been left active
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

### Windows eco mode lifecycle

The Windows client handles eco mode locally.

1. `ONBATT` triggers a warning and can switch the active Windows power plan to the configured power saver scheme.
2. The previously active power plan GUID is stored locally for later restoration.
3. `ONLINE` restores the saved power plan if critical shutdown is not already pending.
4. If the machine reboots while eco mode is still active, the client reconciles startup state and restores the saved plan on next start.

This behavior is gated by `UPS_ORCHESTRATOR_WINDOWS_EXECUTE_PLATFORM_ACTIONS=true` so development and dry-run use stays safe by default.

### Server custom pre-shutdown hook

The Linux server can run a custom shell script just before its own shutdown.

This is meant for application-specific cleanup that a normal OS shutdown might not handle in the right order, for example:

- `save-all` for a game server
- graceful stop of a custom daemon
- database flush or snapshot trigger
- vendor-specific service drain logic

The hook is configured independently from the standard OS shutdown command and is intended to give the user full customization control.

### Ordered critical shutdown

The current shutdown order is:

1. final critical warning
2. NAS shutdown
3. Raspberry shutdown
4. optional Main PC shutdown
5. server pre-shutdown custom script
6. Linux orchestrator self-shutdown

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
- automated coverage for Windows eco mode restore and server startup recovery after committed shutdown
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
- verify the optional pre-shutdown script would run the expected custom save/stop commands

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

## Windows eco mode configuration

Important defaults:

- Windows eco mode is optional.
- Real platform actions are disabled unless explicitly enabled.
- The client stores the previously active Windows power scheme in `.runtime/windows-client-power-scheme.txt` by default.

Main environment variables:

- `UPS_ORCHESTRATOR_WINDOWS_EXECUTE_PLATFORM_ACTIONS=true` enables real notifications, power plan switching, and shutdown command execution.
- `UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_ENABLED=true` enables power plan switching logic.
- `UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_POWER_SAVER_GUID` sets the target eco mode power scheme.
- `UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_BALANCED_GUID` sets the default restore scheme if no previous plan was saved.
- `UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_RESTORE_PATH` sets where the previous power scheme GUID is stored.

## Server pre-shutdown hook configuration

Main environment variables:

- `UPS_ORCHESTRATOR_SERVER_PRE_SHUTDOWN_SCRIPT_ENABLED=true` enables the custom hook.
- `UPS_ORCHESTRATOR_SERVER_PRE_SHUTDOWN_SCRIPT_PATH=./scripts/pre-shutdown.sh` sets the script location.
- `UPS_ORCHESTRATOR_SERVER_PRE_SHUTDOWN_SCRIPT_TIMEOUT_SECONDS=30` sets the execution timeout.

The script runs before the server executes its final OS shutdown command.

If `UPS_ORCHESTRATOR_SERVER_SELF_SHUTDOWN_ENABLED=false`, the hook is only planned and logged, not executed.

## Example Windows LOWBATT shutdown policy
```powershell
$env:UPS_ORCHESTRATOR_WINDOWS_EXECUTE_PLATFORM_ACTIONS="true"
$env:UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_LOWBATT_SHUTDOWN_DELAY_SECONDS="90"
$env:UPS_ORCHESTRATOR_WINDOWS_SHUTDOWN_COMMAND="shutdown /s /t 90 /f"
.\.venv\Scripts\python.exe -m client_windows.main serve --host 127.0.0.1 --port 8765 --token change-me
```

## Example Windows warning and eco mode activation
```powershell
$env:UPS_ORCHESTRATOR_WINDOWS_EXECUTE_PLATFORM_ACTIONS="true"
$env:UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_ENABLED="true"
$env:UPS_ORCHESTRATOR_WINDOWS_NOTIFICATION_TITLE="UPS Orchestrator"
.\.venv\Scripts\python.exe -m client_windows.main serve --host 127.0.0.1 --port 8765 --token change-me
```

## Example Windows eco mode recovery after reboot
```powershell
$env:UPS_ORCHESTRATOR_WINDOWS_EXECUTE_PLATFORM_ACTIONS="true"
$env:UPS_ORCHESTRATOR_WINDOWS_ECO_MODE_ENABLED="true"
.\.venv\Scripts\python.exe -m client_windows.main serve --host 127.0.0.1 --port 8765 --token change-me
```

When the client starts, it checks whether a saved power scheme restore file exists and, if it does, restores that scheme before serving requests.

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

## Example pre-shutdown custom app hook
```powershell
$env:UPS_ORCHESTRATOR_SERVER_PRE_SHUTDOWN_SCRIPT_ENABLED="true"
$env:UPS_ORCHESTRATOR_SERVER_PRE_SHUTDOWN_SCRIPT_PATH="./scripts/pre-shutdown.sh"
.\.venv\Scripts\python.exe -m server.main simulate --event LOWBATT
```

Example use cases for the script:

- send `save-all` to a game server console
- flush a database or stop an app service in custom order
- call vendor-specific cleanup commands before the normal OS shutdown

See `scripts/pre-shutdown.sh.example` for a starter template.

## Suggested validation commands

### Targeted Windows eco mode tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_windows_policy
```

### Full regression suite

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
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