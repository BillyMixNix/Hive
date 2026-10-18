# Hive Jarvis v0.3

Jarvis is a persistent, approval-gated worker supervisor. Python, SQLite, and the standard library provide the durable runtime, while the bundled adapter connects agent tasks to an installed [Codex CLI](https://learn.chatgpt.com/docs/non-interactive-mode). `JARVIS_AGENT_COMMAND` remains available as the provider-neutral override.

## What works now

- Durable SQLite task queue and checkpoints
- Automatic recovery of interrupted read-only tasks after restart
- Fail-closed recovery: interrupted mutations require fresh approval because prior side effects are uncertain
- Retry limits and terminal failure states
- Mandatory human approval before tasks marked as mutating can run
- A single-worker lock, lease/attempt fencing, and worker health reporting
- Direct command, project inspection, and external agent tasks
- First-class Codex coding tasks with read-only or workspace-write sandboxing
- Schema-validated agent outcomes; blocked or incomplete model runs fail the task even when the CLI exits cleanly
- Agent edits require approval by default; failed mutations require fresh approval before retry
- Hash-chained evidence events with a durable head/count anchor, task-state digests, and approval-to-request binding
- Human pass/fail outcomes cryptographically linked to candidate or retired lessons before they can guide an agent
- Cockpit served whenever Jarvis runs and opened by default, with supervisor heartbeat, current work, checkpoints, verification, recovery, failures, and evidence
- Responsive local Cockpit and loopback-only JSON HTTP API with optional bearer-token authentication; phone access uses the authenticated tunnel described below
- Core runtime uses only Python 3.10+ standard-library modules; Codex CLI is required for agent tasks using the default adapter

## Start on Windows

Requirements: Python 3.10+ and [Codex CLI](https://learn.chatgpt.com/docs/codex/cli), signed in by running `codex` once (or `codex login`).

```powershell
Expand-Archive .\Hive-Jarvis-v0.3.zip -DestinationPath .
Set-Location .\Hive-Jarvis-v0.3
python -m jarvis agent-check
.\start-jarvis.ps1
```

`agent-check` reports the exact native Codex executable, CLI version, and authentication status without printing credentials. When the default adapter is selected, the PowerShell launcher refuses to start if that check fails; a configured custom connector skips the Codex-specific preflight.
If Windows blocks a downloaded script, use `powershell -ExecutionPolicy Bypass -File .\start-jarvis.ps1`; the equivalent direct command is `python -m jarvis start --open`.
The launcher opens the local Jarvis Cockpit at `http://127.0.0.1:8765/`. It answers whether Jarvis is alive, what it is doing, whether its state recovered, and what needs human attention. Pass `-NoCockpit` to keep the browser closed.

## Start on macOS or Linux

```bash
unzip Hive-Jarvis-v0.3.zip
cd Hive-Jarvis-v0.3
sh ./demo.sh
sh ./start-jarvis.sh
```

The launcher opens `http://127.0.0.1:8765/` on the same machine. Set `JARVIS_NO_COCKPIT=1` to keep the browser closed. By default, durable state lives under `%LOCALAPPDATA%\HiveJarvis` on Windows or `${XDG_STATE_HOME:-$HOME/.local/state}/hive-jarvis` on macOS/Linux, outside writable project trees. Set `JARVIS_DATA` to choose another location.

In a second terminal:

```bash
python3 -m jarvis add \
  "Inspect this project" --workspace /path/to/project --kind inspect

python3 -m jarvis list
```

Queue a mutating task; it will not execute until approved:

```bash
python3 -m jarvis add \
  "Run the formatter" --workspace /path/to/project --kind command --mutating \
  --command python3 -m black .

python3 -m jarvis approve TASK_ID
```

## Run a coding task

Codex is the default agent adapter; no `JARVIS_AGENT_COMMAND` is needed. An agent task is considered mutating unless you explicitly choose `--read-only`, so coding work waits for approval:

```powershell
$task = python -m jarvis add "Fix the failing build and run its tests" `
  --workspace C:\path\to\project --kind agent | ConvertFrom-Json
python -m jarvis approve $task.id
python -m jarvis show $task.id
```

For analysis that must not edit files:

```powershell
python -m jarvis add "Review the error-handling design" `
  --workspace C:\path\to\project --kind agent --read-only
```

The running supervisor executes ready tasks automatically. If you intentionally use Jarvis without the daemon, stop it first and run `python -m jarvis once` to process one task. A process lock prevents two workers from consuming the same queue.

Jarvis launches Codex non-interactively with saved CLI authentication, an ephemeral session, no interactive approvals, and a sandbox derived from the task: `read-only` or approved `workspace-write`. Personal configuration, login shells, and user/project execution-rule files are ignored for deterministic isolation, but saved authentication is still used; strict configuration parsing makes unknown security settings fail closed. Structured-output control files live beside Jarvis state, outside both the task workspace and system temporary directories. Approved Windows processes are assigned to kill-on-close Job Objects before they are resumed. On POSIX systems, process groups are terminated after every run and on normal timeout cleanup; hard-crash descendant containment is currently a Windows guarantee. The Windows preflight adds an inheritable Modify entry for the current user's SID to an approved workspace so files created by the elevated sandbox account remain usable by that user. Run Jarvis from a dedicated Python installation or virtual environment outside every task workspace; mutating tasks that overlap the active Python executable or its runtime prefixes are rejected. Set `JARVIS_CODEX_MODEL` or `JARVIS_CODEX_REASONING_EFFORT` before starting Jarvis if you want explicit overrides. Set `JARVIS_CODEX_BIN` to an absolute native executable when auto-discovery is unsuitable.

Useful environment controls:

- `JARVIS_WORKSPACE_ROOTS`: JSON string array or OS path-separated list of allowed workspace roots. Resolved task paths outside them are rejected.
- `JARVIS_CODEX_BIN`: absolute path to the native Codex executable. A workspace-local executable is always rejected.
- `JARVIS_CODEX_MODEL` and `JARVIS_CODEX_REASONING_EFFORT`: optional model and reasoning overrides. When unset, Codex selects its current default.
- `JARVIS_CODEX_WINDOWS_SANDBOX`: `elevated` (the default and preferred native Windows backend) or `unelevated` when local policy prevents elevated sandbox setup.
- `JARVIS_CODEX_ALLOW_ENV`: comma-separated environment-variable names to pass through in addition to a small OS/runtime allowlist. Tokens, keys, credentialed proxy URLs, language injection variables, and unrelated daemon secrets are absent by default. Saved Codex login is safer; only opt a value back in when you understand that repository code can read it.
- `JARVIS_API_TOKEN`: optional bearer token for local API/Cockpit data; recommended on shared machines.

## Attach another coding agent

Set `JARVIS_AGENT_COMMAND_JSON` in the supervisor's environment *before it starts* to a JSON argv array for a program that accepts one JSON request on stdin. Restart the supervisor after changing it. The request contains a contract version, task metadata, `goal`, `workspace`, mutation/approval state, timeout, and relevant `lessons`. The process should perform its work inside the supplied workspace, emit its report on stdout, and exit nonzero on failure. The older `JARVIS_AGENT_COMMAND` shell-like string remains supported for compatibility, but JSON argv avoids Windows quoting ambiguity. A custom connector is trusted executable code, is never accepted for a read-only task, and always requires mutation approval; use `JARVIS_AGENT_ALLOW_ENV` to explicitly pass any environment variables it needs.

```bash
export JARVIS_AGENT_COMMAND_JSON='["/path/to/your-agent-wrapper"]'
sh ./start-jarvis.sh

# In a second terminal, copy the id printed by `add` into TASK_ID:
python3 -m jarvis add \
  "Fix the failing build" --workspace /path/to/project --kind agent
python3 -m jarvis approve TASK_ID
python3 -m jarvis show TASK_ID
```

This boundary works with Codex CLI, another agent harness, or an Ollama-backed wrapper without tying persistence to one provider.

## HTTP API

- `GET /` local Jarvis Cockpit
- `GET /health`
- `GET /overview` (complete status counts and every nonterminal task)
- `GET /tasks`
- `POST /tasks`
- `GET /tasks/{id}`
- `GET /tasks/{id}/events`
- `POST /tasks/{id}/approve`
- `POST /tasks/{id}/reject`
- `POST /tasks/{id}/cancel`
- `POST /tasks/{id}/outcome` with `{ "passed": true, "summary": "..." }`
- `GET /lessons`

POST requests require `Content-Type: application/json`. Command tasks submitted through every storage/API path always require approval, regardless of a caller-provided mutation flag. The approval event is bound to the exact goal, workspace, payload, task kind, and retry limit that can execute; a changed or legacy-unbound request cannot be claimed. Cancellation is supported only before a task starts; a running process is allowed to reach a recorded terminal state rather than pretending it was stopped. `/health` returns an unhealthy status when the ledger fails verification, its durable anchor or bound task state disagrees, the worker heartbeat is stale, or the worker loop is stopped/repeatedly erroring.

On first open of a pre-v0.3 database, Jarvis validates the existing hash chain and lesson evidence, records neutral state-binding events for legacy tasks and lessons, and initializes the durable ledger anchor. The migration and its completion marker commit atomically and retry safely after interruption. Its task digest lets unchanged legacy read-only work resume without inventing an approval; legacy ready mutations still require a fresh v0.3 approval event before execution.

Jarvis refuses non-loopback binds, validates the HTTP `Host` header, and serves plain HTTP only on the local machine. The Cockpit requests `JARVIS_API_TOKEN` when configured and retains it in browser-tab session storage. Remote access requires a private TLS tunnel or authenticated reverse proxy that terminates locally and rewrites `Host` to `localhost` or a loopback address; never expose an unauthenticated instance to a network.

## Run verification

```bash
python3 -m unittest discover -s tests -v
python3 -m jarvis --data /tmp/jarvis-check.db verify
```

On Windows:

```powershell
python -m unittest discover -s tests -v
python -m jarvis --data (Join-Path $env:TEMP "jarvis-check.db") verify
```

## Honest boundary

This release provides execution continuity, persistence, approvals, evidence, and a bridge to Codex CLI. It does not bundle model weights, create an account, or bypass Codex or operating-system permissions. The adapter passes only a small allowlist of OS/runtime environment values to model execution; saved Codex login is the recommended authentication method. Mutating agent workspaces that contain Jarvis's database or runtime are rejected. Evidence hashes, the local anchor, and state/request digests detect corruption and unsynchronized edits, but they are not an external signature: an administrator who can rewrite the database and every anchor can manufacture a new internally consistent history. Keep the API on loopback and use an authenticated TLS tunnel for any remote access.

The `legacy-hive/` directory preserves the supplied Hive memory, state, prompt, bridge, and lesson components as integration references. The daemon itself deliberately avoids their PyTorch/Transformers dependency chain; verified lessons are injected into every external agent request through the small stable JSON boundary.

The source ZIP includes `legacy-hive/`; Python wheels contain only the lightweight `jarvis` runtime and its two console entry points.
