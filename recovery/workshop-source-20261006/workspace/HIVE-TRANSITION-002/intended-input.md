# HIVE-TRANSITION-002 — intended planning input

This study starts from the final TRANSITION-001 source in `../HIVE-TRANSITION-001/repaired-workshop`, including exclusive ownership validation. That source and all prior evidence are inventoried in `evidence/prior-study-before.json`. The primary historical run is `75280298dd02`, in `../HIVE-TRANSITION-001/evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/`.

## Construction path

`diagnostic_runner.task_specs()` reads frozen TASKS.md; `run_one()` copies the sealed baseline to a separate external candidate and invokes `factorial_runner_adapter.run_condition()`. Hive's `run_build()` establishes exact host scope and external roles in ContextVars. `_run_build_impl()` constructs `_repository_map(source_root)`, `repository_facts.build(source_root)`, and `_intent_envelope(request, source_root)`, then `_planner_prompt()`. After rejection, `_plan_correction_prompt()` repeats the original prompt and appends the rejection and prior response. `observed_call()` records telemetry and forwards the unchanged string to the runner's agent callback.

The callback calls `providers.ollama_chat()` with one user message, a separate system instruction, `response_schema_for_prompt()` as `response_format`, temperature 0.1, and maximum output 2,048. The provider constructs `messages=[system,user]`, `stream=true`, `format=<schema>`, `options={temperature:0.1,num_predict:2048}`. `_ollama_chat_once()` uses `httpx.AsyncClient.stream('POST', OLLAMA_BASE+'/api/chat', json=body)`. No context option, stop override, or truncation policy was supplied. The diagnostic aggregate budget is not a context-window budget.

## Exact task and scope

> In `SnapshotFormatter.boundLine`, preserve complete UTF-16 surrogate pairs when truncating a line to `MAX_LINE_CHARS`. Keep the existing control-character and section-sign sanitization, the `...` suffix when truncation is necessary, and unchanged behavior for ordinary ASCII lines. Truncation must never introduce an unpaired surrogate or return a string longer than the bound.
>
> Write scope: `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

The same single exact path is carried independently in host authorization. `_host_write_scope_text()` explicitly prohibits unauthorized test files, requires one worker owner per file, and specifies the inactive-role convention: exact goal `no change needed`, empty worker_files, empty worker_acceptance. `_planner_response_schema()` constrains each role's file items to the host/role intersection. External roles have broad read/assignment prefixes, so the one production path appears in each role's item enum; semantic role suitability and exclusive ownership remain validator responsibilities.

## Role and output contract

System text: `You are the bounded planner agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.`

`_planner_prompt()` asks for planning only, no code. `hive_protocol.role_constraints(..., external=True)` distinguishes frontend, application, and test responsibilities, exact ownership, scope, per-worker acceptance, multi-role interface requirements, and bounded worker observations. It warns against assuming Workshop filenames/frameworks. The text still includes generic Python/web examples and three active roles. These examples are observable representation concerns, not proven transport defects.

`hive_protocol.PLAN_SCHEMA` requires summary, ui_goal, backend_goal, tests_goal, worker_files, acceptance, worker_acceptance, interface_contracts; provider_changes is optional. Objects disallow extra properties. Interface entries require name, owner, nonempty consumer_roles, contract. The schema is supplied separately in the HTTP `format` field through `AgentPrompt.response_schema`; a JSON example and semantic rules also appear in text. Exact historical schemas are in the preserved model-boundary requests and reconstructed wire bodies.

`_normalize_plan()`, `_validate_host_write_scope()`, and `_validate_intent_coverage()` remain authoritative. Invalid output is not authorization. Two rejected attempts exhaust `MAX_PLAN_CORRECTIONS=1`; dispatch occurs only after successful validation.

## Source and acceptance information actually supplied

The planner gets a 10,870-character map section: filenames/directories, including many historical evidence filenames. Python files get limited symbol names. Java files get filenames only. No Java source excerpt, `boundLine` body, or numeric `MAX_LINE_CHARS=240` is supplied to this planner. `repository_facts.build()` examines app.py and static/index.html for web interfaces; for this Java repository it says web framework unknown, no local route examples, no existing HTTP interfaces. The immutable intent envelope is `{"version":1,"requirements":[]}`. These are omissions in the intended representation, not losses during HTTP serialization.

The entire user behavior specification is present. Generic global/per-role acceptance instructions and the statement that host-owned frozen verification grants no write authority are present. Frozen JUnit source, detailed hidden assertions, and Gradle gate commands are not included in the planner prompt; the host enforces them independently. This study preserves that separation. Workers would receive owned source via `_worker_context()` and may use bounded observations; the planner itself has no observation response action.

## Correction and budgets

Correction includes the full original prompt, combined HostWriteScopeError, rejected active roles, required roles (empty), interface schema/example, prior response (bounded to 12,000 characters), and one-attempt instruction. The actual 1,246-character prior response is below that bound. The TRANSITION-001 scope correction does not force a nonempty contract if the corrected plan deactivates a role. Initial prompt: 17,413 characters; correction: 21,147 characters. Exact text is preserved under `evidence/measurements/historical-planner-{1,2}/` and in the prior model-boundary files.

Map generation has no aggregate token bound. Repository facts have a separate character limit. Telemetry's 40,000-character prompt bound affects recorded telemetry, not sent prompt; neither historical planner prompt hits it. Workers have separate source character bounds (90,000 owned, 6,000 supporting). The runner reserves `len(prompt.encode('utf-8'))+1000+output_limit` against a 250,000 aggregate ceiling; the added 1,000 is a conservative accounting allowance, not sent text. Wall ceiling is 3,600 seconds; per-call maximum 900 seconds. These do not reserve KV context space.

Historical model/provider: qwen2.5-coder:14b, Q4_K_M, native training context 32,768; Ollama 0.34.0; actual `/api/ps` context 4,096. Native capacity is not active runtime capacity. `num_ctx` was omitted; model `/api/show` has no parameter override. The runtime default is therefore material. See `context-budget.md` and `fidelity.md` for measured rather than inferred token counts.
