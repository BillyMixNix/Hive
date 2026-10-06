# Nix Workshop v0.11.1

## v0.11.1 feature catalog

- Hive Build can preview a planned feature by ID from `FEATURES.md`.
- The UI shows the objective, scope, dependencies, acceptance criteria, and constraints and asks for confirmation before queueing.
- The server verifies the catalog section hash again when the build is submitted and stores the selected specification and original command in the run metadata.
- Unknown, non-planned, incomplete, or changed catalog entries fail closed. Ordinary free-form Hive requests keep the existing flow.
- Catalog selection does not grant file ownership or bypass planning, validation, verification, review, approval, apply, or rollback gates.

The feature backlog is included as a starter catalog. `NW-F002` through `NW-F004` are planned; Hive still has to inspect source and satisfy its normal checks when selected.

## v0.11.0 safety prerequisite

Hive verification now fails closed unless its disposable Docker verifier is available. Before running Hive Build:

1. Install and start Docker Desktop (Windows, Linux containers) or Docker Engine.
2. From the Workshop folder run `build_verifier.bat` on Windows or `./build_verifier.sh` on Linux.
3. Keep Workshop private; do not expose port 8765 or the Docker socket through RunPod global networking.

The verifier image has no network, receives no Workshop API keys, and sees only a sanitized read-only source copy. Tests execute in disposable memory-backed storage. A RunPod template that cannot run Docker will reject Hive verification rather than falling back to host execution.

External Gradle repositories use the pinned JVM profile in `nix-workshop-verifier:0.11.1-jvm21`. It invokes the checked-in Gradle Wrapper JAR (never a system Gradle), runs frozen targeted `test` cases, then a fixed full-gate task list, offline, with bounded time/output and read-only mounts for only the Gradle wrapper-distribution and dependency caches. If a bounded `VERIFICATION.md` documents its gate under `## Exact commands`, Hive extracts only Gradle task identifiers from the first wrapper invocation; free-form arguments, shell commands, and chaining are rejected. Otherwise the generic Gradle `check` lifecycle task is used. `GRADLE_USER_HOME` may identify the host cache; if unset, Workshop checks `%USERPROFILE%\\.gradle` on Windows or `$HOME/.gradle` elsewhere. No host variables, Java installation, credentials, or cache write access are passed into the container. External Gradle builds must submit frozen JUnit test source, project-relative class name, and expected case count; Hive hashes and preserves those inputs under run evidence and rejects edits to them. If the exact wrapper distribution or cached dependencies are unavailable, the offline verifier fails closed.

For JVM verification the wrapper version, wrapper properties, wrapper JAR, and (when present) `VERIFICATION.md` policy hashes are captured from the immutable external baseline before model execution, then required to match the candidate at verification time. Cache discovery consults only host `GRADLE_USER_HOME`, falling back to `USERPROFILE` on Windows or `HOME` elsewhere; those values are used only to locate read-only caches and are never forwarded. The verifier and Gradle child receive an explicit environment: `JAVA_HOME`, `GRADLE_USER_HOME`, `GRADLE_RO_DEP_CACHE`, `HOME`, `TMPDIR`, `PATH`, `LANG`, and `CI` (the container runner also receives `PYTHONDONTWRITEBYTECODE`). Build scripts run only inside a network-disabled container with a read-only root filesystem; writable space is limited to run-owned tmpfs candidate, Gradle-home, and temporary directories. The host supplies no task names or command-line arguments from model output.

Builds also record source/stage hashes and refuse to apply if a file changed after staging. Optional experiment identifiers and provenance are stored in `run.json` for controlled Hive comparisons.

A local-first AI workbench that keeps the **workspace, memory, tools and history independent from the model**.

## What works now

- **Chat workspace**
  - OpenAI Responses API: GPT-5.6 Luna / Terra / Sol / GPT-6 Astra
  - Local Ollama models
  - `AUTO` routing: local-first when possible, cloud-cheapest when cloud tools are required
  - manual model switch at any time without losing chat history
  - optional OpenAI web search
  - image input in chat
- **Local persistent memory**
  - SQLite-backed pinned memories
  - simple relevance retrieval into every chat request
  - memory stays local and remains available when switching models
- **Image Studio**
  - OpenAI GPT-Image-2.5 Flare by default
  - generated files saved under `media/`
- **Video Studio**
  - adapter for the current OpenAI video endpoint
  - IMPORTANT: OpenAI currently marks that Sora API as deprecated with shutdown scheduled for 2026-09-24.
  - the Workshop provider abstraction is deliberately designed so a replacement video backend can be added without changing the UI.
- **Code Lab**
  - local project file browser/editor
  - run Python files with a timeout
  - stdout/stderr capture
- **Hive Build**
  - immutable intent obligations prevent explicit runtime/UI requirements from disappearing during planning
  - deterministic HTTP interface facts include literal response keys so planners can reuse existing endpoints
  - staged pytest verification uses a private writable temp directory
  - strict escalation preconditions: owned files cannot be requested, repository-information blockers require six observations, and multi-role plans require planner-owned interface contracts
  - deterministic repository-derived framework/API contracts and local route examples are supplied to the planner and workers
  - backend workers are explicitly grounded in the detected repository framework; FastAPI repositories receive FastAPI patterns and Flask substitutions are prohibited
  - boundary-aware Python/JavaScript symbol and HTML element insertions, lowered to existing exact edits
  - one originating-worker structural repair per role/run, with unchanged ownership and complete failure/repair history
  - repository-map-informed planner
  - each worker sees the overall objective, its own responsibility/files/acceptance criteria, and teammates' assignments
  - HTML/JavaScript context selects relevant sections, named handlers, and their local helpers within the existing context limits
  - explicit role/file constraints and one planner correction for invalid contracts
  - bounded owned-file context plus read-only integration examples across roles
  - prior worker proposals shared as sanitized structural metadata only; raw model text and code are never reused as worker instructions
  - implementation workers receive a final authoritative task contract after context, plus a conservative task-focus check before staging
  - owned-file context includes a deterministic structural target index for real HTML ids/headings and top-level Python/JavaScript symbols
  - missing or ambiguous literal anchors are treated as repairable structural failures and receive at most one originating-worker repair
  - repeated rejected proposals are detected and fail closed instead of consuming an unbounded repair loop
  - planner-mediated, one-shot scope replan when a worker reports an insufficient contract
  - worker and repair prompts teach both implementation and `plan_insufficient` responses
  - local Hive calls use role-specific JSON schemas and temperature 0.1; ordinary chat/cloud settings are unchanged
  - bounded actual prompt/response telemetry, hashes and rejected-plan attempts recorded in the run for diagnosis
  - repository-verified existing interfaces can satisfy provider obligations without unnecessary backend edits; redundant assignments receive the existing one-shot planner correction
  - test workers receive bounded read-only examples of the repository's real endpoint and static-UI testing patterns
  - byte-equivalent targeted corrections fail closed as `RepeatedFailedProposal`
  - truthful host-known Hive stages are exposed through job polling without exposing model reasoning

## v0.7.7 repository grounding

v0.7.7 adds a compact deterministic facts layer for repository-level coding. It reports the detected web framework, observed route declarations, and existing frontend API usage from application source. These are read-only prompt evidence; worker ownership, strict edit validation, approval, budget gates, verification, rollback, snapshots, and ledger behavior are unchanged.

## v0.7.8 bounded worker observation loop

v0.7.8 adds a bounded, deterministic, read-only observation protocol for Hive workers. Before proposing an edit, a worker may request up to six allowlisted observations: text search, symbol listing/reading, bounded file excerpts, or similar-code search. Observation results are recorded with bounded trajectory metadata and never grant write authority, scope expansion, shell access, or approval authority. Workers still return one final implementation or a validated `plan_insufficient` escalation through the existing planner, validator, structural-repair, verification, reviewer, and human-approval gates. Small planner-owned interface contracts make cross-role dependencies explicit without requiring workers to edit teammate files.

## v0.7.9 bounded worker coding correction

v0.7.9 adds a per-worker candidate loop after observation: strict edit preflight, private staging, small role-scoped deterministic checks, and at most one correction by the originating worker when those checks fail. Failed candidates are reverted before correction; the correction keeps the same exact files, role, budgets and approval gates. Python compilation, JavaScript parsing, and changed test-file pytest runs are the only targeted checks; the final full verification and reviewer remain authoritative.

## v0.8.1 escalation gates

v0.8.1 makes worker replanning explicit and fail-closed. Every `plan_insufficient` response declares whether the blocker is repository information, a missing contract, or a scope change; all blocker types require the complete bounded observation history before escalation. A worker may never request a file already in its exact plan. Plans with multiple active roles must contain a non-empty interface contract linking active roles, and invalid plans are corrected before any worker runs. The existing planner-only scope changes, validator, repair/replan budgets, verification, review, approval and rollback gates remain authoritative.
- **Cost telemetry**
  - tracks reported OpenAI text token usage
  - estimates text-model spend from current configured rates
- **Persistent chat history**
  - SQLite local database
- **Portable architecture**
  - model/provider layer is separated from the product UX

## v0.7.6 focused worker repair boundary

Structural repair prompts now state concrete, format-specific recovery rules and explicitly reject repeating the same edit proposal. If a model repeats the rejected edit, Workshop records that as a bounded repair failure and stops. Workers are also told that requesting files already in their exact scope is not a valid plan escalation.

## v0.7.5 focused worker coding path

This release keeps Hive orchestration and the strict validator unchanged while improving the worker coding substrate. Owned files now provide a deterministic target index so workers can select existing HTML ids, direct headings and top-level Python/JavaScript symbols instead of inventing placeholder anchors. A missing or ambiguous literal replacement/anchor is a structural diagnostic eligible for one bounded repair by the same originating worker; ownership failures remain non-repairable. Each provider call records bounded prompt and response text in addition to lengths and hashes, making the actual model contract inspectable in `run.json`.

The release adds a cross-file worker-path regression covering planner → owned context → symbol/element edits → originating-worker repair → unchanged validator → review, with no automatic apply.

## v0.7.4 worker-context isolation and structural editing

New functions, endpoints, tests and cards can target complete structures instead of literal headers:

| Operation | Target fields | Placement |
| --- | --- | --- |
| `insert_before_symbol` | `path`, `symbol`, `insert` | Before a unique top-level definition, including its Python decorators |
| `insert_after_symbol` | `path`, `symbol`, `insert` | After the complete definition/body |
| `insert_after_element` | `path`, `insert`, and either `element_id` or `heading` | After the complete HTML element; a heading identifies its direct container |

`symbol` must be an exact name from source, not a function header or a guessed/nested name. Python functions, async functions and classes are supported. JavaScript supports top-level definitions and single function-valued declarations in JS files or inline scripts. HTML targets must be unique and markup explicitly balanced. For a Settings card, the existing card's heading selects the whole card, not just its heading tag.

The existing ownership validator is unchanged. New operations are preflighted against it, resolved to ordinary exact replacements, then checked by it again. The entire worker proposal is prepared and structurally validated in memory before any file is written. Legacy `replace`, `create` and `insert_after_anchor` remain available, with structural checks added for Python and HTML/JavaScript.

On a repairable structural failure, the same worker receives the diagnostic, rejected proposal and unchanged role/files/criteria/team contract. It may return one complete replacement proposal. Every replacement goes through all checks again. Scope violations do not trigger structural repair. A genuine scope escalation still needs planner approval, and replanning does not reset the structural repair allowance. Unparseable repair output or another structural failure stops safely. Attempts and outcomes are saved in `run.edit_repairs` and the originating agent's `edit_repairs`.

**Node.js is required for structural JavaScript checks.** Acorn is bundled for offline syntax inspection; no npm install or network call is made during editing, and proposed scripts are never executed by the parser. Missing parser infrastructure fails closed without a model repair call. Python-only edits do not require Node.

Limits: top-level symbol editing, JavaScript through ECMAScript 2022 (not TypeScript/JSX), explicitly closed HTML, and a one-million-character source-analysis ceiling. These checks catch structure, not arbitrary semantic bugs. Full tests, reviewer approval, and explicit user apply approval remain required. The new protocol does not guarantee that a local model will produce a successful feature implementation.

## Run on Windows

1. Extract the ZIP.
2. Run `setup_windows.bat`.
3. Run `start_windows.bat`.
4. Open **Settings**.
5. Either:
   - paste an OpenAI API key for the current process, or set `OPENAI_API_KEY` before launch; and/or
   - install Ollama and pull a local model such as `qwen3.5:9b`.

The pasted API key is kept in server memory only and is not written to disk by Workshop.

## Routing philosophy

`AUTO` is intentionally conservative in v0.1:

- If a local Ollama model is available and the task does not require an OpenAI-hosted tool, use local inference first.
- Web-search requests use GPT-5.6 Luna.
- If local inference fails at the transport/model level and an OpenAI key is configured, fall back to Luna.
- You can manually force Luna, Terra, Sol, Astra, or Local at any time.

The longer-term step is the full Hive router:
**decompose -> dispatch cheap/local bounded nodes -> verify -> escalate only failed nodes -> compile**.

## Security

- This is a **local development build**, not a hardened multi-user service.
- The Code Lab executes Python with the permissions of the user running Workshop. It is not an OS sandbox.
- Do not expose port 8765 to the public internet.
- Memory/chat data are stored in `data/workshop.db`.
- API keys are not persisted by the app.

## Current OpenAI defaults (checked 2026-09-13)

Text:
- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol`
- `gpt-6-astra`

Images:
- `gpt-image-2.5-flare`

Video:
- `sora-2` adapter exists only as a temporary compatibility path because the current OpenAI video API is scheduled to shut down 2026-09-24.


## v0.2 hardening

This version directly addresses the first red-team pass.

### Fixed
- Empty/directory/reserved/hidden file paths return clean 400 errors.
- SQLite foreign keys are enabled.
- `/api/chat` validates chat IDs before writing messages, preventing orphan messages.
- Provider/runtime failures are logged locally and return bounded user-facing errors instead of raw bodies.
- Provider-controlled image output uses DOM node creation rather than interpolating URLs into HTML.
- Workspace is snapshotted before Code Lab writes.
- Code execution is disabled outside **Personal Lab** mode.

### Safety modes
- **Personal Lab** — full Code Lab, including local Python execution.
- **Client Cleanup** — approved diagnostic actions only; arbitrary Python blocked.
- **Locked Demo** — diagnostics and arbitrary code blocked.

### Audited Operations Cockpit
Approved actions include:
- system information
- startup audit
- Windows Defender status
- installed-app inventory
- disk usage
- browser extension paths
- bounded running-process review

Each action records:
- what ran
- why
- risk level
- whether approval was present
- return metadata

### Reports and snapshots
- one-click workspace snapshots
- one-click HTML client report from the run ledger

The code runner is still not an OS sandbox. Personal Lab means exactly that: use it on a machine you trust.


## v0.3 — Portability, preflight, rollback, workflow

Addresses the second red-team pass:

- clean-run DB tests initialize schema
- app version is `0.3.0`
- dotfiles are hidden from the file list
- absolute file paths are rejected
- diagnostics are OS-aware
- video job UI no longer places provider IDs inside inline handlers
- Preflight panel: OS, Python, PowerShell, Ollama, OpenAI key, writable workspace
- built-in pytest command
- snapshot listing and approved restore, with automatic backup before restore
- client cleanup workflow scaffold: Intake -> Scan -> Review -> Approve Fixes -> Report
- cloud escalation budget gate with explicit approval option

The code runner remains intentionally restricted to Personal Lab mode.


## v0.3.1 — Candidate hardening

- fixed the Video Studio JavaScript parse failure
- cloud approval now happens before user-message persistence
- local-to-cloud AUTO fallback uses the same approval gate
- release package excludes the mutable runtime SQLite DB
- added a frontend JavaScript syntax smoke test using `node --check`
- added regression coverage for cloud-gate persistence and fallback escalation


## v0.3.2 — Budget truthfulness and persistence safety

- chat turns remain ephemeral until the provider returns successfully
- missing API keys no longer leave user messages behind
- cloud admission uses a conservative pre-call cost estimate
- the configured output-token ceiling is included in that estimate
- requests estimated above the per-task cap are blocked before spending
- actual usage is checked after completion and any overrun is surfaced and logged
- local-to-cloud fallback uses the same key, budget, and approval checks
- chat, chat-list, memory, and file-list rendering now use DOM construction instead of interpolated HTML
- release notes now describe the current build rather than v0.1

The spend cap is admission control based on an estimate, not a provider-side billing guarantee. Exact cost is only known after the provider reports usage.


## v0.3.3 — Enforced cloud output cap

The configured cloud output-token ceiling is now sent directly to the OpenAI Responses API as `max_output_tokens`.

This closes the gap between:
- pre-call spend admission,
- user approval,
- and actual generation constraints.

For OpenAI Responses, `max_output_tokens` is an upper bound across the response output budget, including visible output and reasoning tokens. Workshop still records actual usage after completion and keeps the overrun warning as a defense-in-depth check.

The local Ollama path is unchanged in this patch.


## v0.4.0 — Hive Build Mode / self-hosted development

Workshop can now use bounded agents to propose edits to Workshop itself.

Pipeline:

1. **Planner** — read-only; decomposes the requested change.
2. **UI agent** — may write only `static/index.html`.
3. **Backend agent** — may write only `app.py` and `workshop/*.py`.
4. **Test agent** — may write only `tests/*.py`.
5. Worker agents execute concurrently against a staged copy.
6. Exact replacements are scope-checked and must match exactly once.
7. **Deterministic verifier** runs:
   - Python compilation
   - `pytest -q`
   - `node --check` for the inline frontend script when Node is available.
8. **Reviewer** — read-only; sees the diff and verification results.
9. Human approval is required before any self-edit is applied.
10. A self-snapshot is written before apply.
11. Post-apply verification runs again.
12. Any failed apply or post-apply verification automatically rolls back.

### Model routing for Hive Build

Hive Build defaults to an installed Ollama model. `qwen2.5-coder:14b` is preferred when detected.

Cloud escalation is off by default. If explicitly enabled, the existing Workshop API-key and spend-cap controls apply, and the user chooses a maximum cloud tier.

### Local model selector

The Local Model setting is now populated from `/api/tags` instead of relying on a free-text default. A custom Ollama tag can still be entered intentionally.

### Important v0.4 boundary

This is a **bounded self-editing candidate**, not an unrestricted autonomous coding agent. Agents cannot directly execute arbitrary shell commands, cannot write outside their scope, and cannot apply their own changes. The human approval boundary remains mandatory.


## v0.4.1 — Local model discovery hardening

Ollama discovery is now explicit and diagnosable:

- 5-second HTTP discovery at the configured `/api/tags`
- native `ollama list` fallback when the HTTP probe fails
- editable Ollama endpoint in Settings
- Connect + Refresh controls
- visible discovery error details instead of silently showing an empty dropdown
- detected models repopulate both Chat and Hive Build selectors

Default endpoint remains `http://127.0.0.1:11434`.


## v0.4.2 — Stubborn local discovery

Local Ollama HTTP discovery now uses `trust_env=False` so proxy environment variables do not hijack requests to `127.0.0.1`.

This prevents SOCKS/HTTP proxy settings from breaking `/api/tags` discovery for a local daemon.

The Settings UI also explains that manual custom-model entry can still work even when discovery fails, as long as the exact Ollama model tag is known.
