# TRANSITION-002 context-complete failure reconstruction

Primary run: **6b87294fdc72**. Original: `../HIVE-TRANSITION-002/evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive/`. Exact copies for this study: `evidence/transition-002/{run,calls,result}.json` and `wire/{01,02,03}/` (body, transport metadata, raw response, NDJSON, rendered input, tokenizer IDs). No historical artifact is altered.

## Task, roles and authority

> In `SnapshotFormatter.boundLine`, preserve complete UTF-16 surrogate pairs when truncating a line to `MAX_LINE_CHARS`. Keep the existing control-character and section-sign sanitization, the `...` suffix when truncation is necessary, and unchanged behavior for ordinary ASCII lines. Truncation must never introduce an unpaired surrogate or return a string longer than the bound.
>
> Write scope: `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

Only that production file is authorized. Planner output has ui, backend and tests roles. Planner and reviewer are read-only controller participants, not owners in worker_files; there is no integration worker. `hive_protocol.role_constraints` says backend implements application behavior and tests implements regression coverage. External role scopes all use `**`; the host exact-file allowlist is independently enforced.

`hive._host_write_scope_text` says each file has exactly one owner; unauthorized test files must not be invented. An inactive role uses exact goal `no change needed`, worker_files `[]` and worker_acceptance `[]`. The schema requires goals for all three roles and all three file/acceptance arrays. Each role's path enum contains the same single host-authorized file. Cross-array exclusivity is not encoded. Exact initial/correction schemas are `wire/02/wire-request.json` and `wire/03/wire-request.json` under `format`; standalone initial schema is `evidence/planner-schema-before.json`.

## Requests, responses, normalization and termination

`hive._run_build_impl` calls `_planner_prompt`, then the diagnostic provider callback calls `providers.ollama_chat`, which posts to `http://127.0.0.1:11434/api/chat`. Body: qwen2.5-coder:14b, separate bounded-planner system message and complete user prompt, stream=true, format=<planner schema>, temperature=.1, num_predict=2048, num_ctx=12288, truncate=false. Exact bodies are preserved, not reconstituted from summaries.

HTTP attempt 01 failed CUDA initialization with 500. Attempt 02 retried identical body bytes under the existing provider policy, then returned the first plan. Attempt 03 is the one correction. Successful requests have rendered/provider input counts **3834/3834** and **4652/4652**; outputs 259 and 331; runtime context 12288; done_reason=stop. First prompt hash `7ea130b272dc13aa728dabf58309babc66fc399f77826a779079ba74a9c41958`; correction hash `964b61e8d8e313000dded9a7040e6816f0605feb4597e91e57a47cdad6521214`. Full accounting is `evidence/transition-002/input-measurements.json`. This is provider-accounted completeness, not direct tensor visibility.

Both raw responses are JSON objects. Exact text: `wire/02/raw-response.txt` and `wire/03/raw-response.txt`. First plan makes UI inactive, backend implement boundLine, tests add regression tests. Both backend and tests list `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`. The first interface_contracts array is empty. Correction retains the same two claims and adds a backend-to-tests interface contract.

`_extract_json` succeeds. `_normalize_plan` normalizes both identical path strings into its local worker_files, then `_host_write_scope_issues` detects them in two role arrays. **No normalized plan is returned**, because normalization raises; `evidence/historical-plans-before.json` records that as null rather than inventing an accepted normalized artifact. The candidate path spellings are already normalized and neither is outside the host boundary. Conflict means two distinct workers would be authorized to modify the same whole file, regardless of intended symbols or separate test/implementation responsibilities.

First diagnostic: `file 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java' is assigned to both backend and tests; keep exactly one owner and deactivate roles without authorized work; multi-role plan requires at least one interface contract`.

`_plan_correction_prompt` repeats the original prompt, that combined error, rejected active roles backend/tests, no immutable required roles, interface schema, an example using the rejected backend/tests pair, the rejected response, and the one-correction instruction. Its generation schema does not require a contract for this HostWriteScopeError, preserving TRANSITION-001. The textual example nevertheless gives extensive guidance about retaining coordination between those roles. It does not identify tests as the claim to remove; that decision is left to the planner. There is no contradictory requirement to keep tests active.

Corrected diagnostic: `file 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java' is assigned to both backend and tests; keep exactly one owner and deactivate roles without authorized work`.

`MAX_PLAN_CORRECTIONS=1` is exhausted. Final PlanValidationError prepends `Planner correction budget exhausted;`. Dispatch never begins. Run has no plan field, changed_files=[], verification=null, review=null, applied=false. Candidate remains baseline hash `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`. This is a plan/ownership failure, not an edit or software verification failure.
