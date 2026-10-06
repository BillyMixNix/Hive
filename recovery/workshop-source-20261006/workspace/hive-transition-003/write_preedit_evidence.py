"""Seal the pre-edit diagnosis and its source identity before production changes."""
import hashlib,json,shutil
from pathlib import Path
from setup_study import save,sha
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'HIVE-TRANSITION-002'
EVAL=Path(r'C:\Users\billy\Documents\Codex\2026-09-22\atm10-ai-companion-autonomous-build-mega\local-model-trial')
source_before=json.loads((HERE/'evidence/source-before.json').read_text())
assert all(sha(HERE/'repaired-workshop'/p)==h for p,h in source_before.items())
assert json.loads((HERE/'evidence/expressibility-dispatch.json').read_text())['worker_reached']
selected=[EVAL/'hive-eval-009'/p for p in ('EVALUATION.md','plan.json','activity-reset-service-contract.txt','activity-reset-command-contract.txt')]
selected += [EVAL/'orchestrated-runs/20260924-073647-a040db65/result.json',EVAL/'hive_orchestrator.py',EVAL/'hive_pipeline.py']
selected += [EVAL/f'runs/{r}/{n}' for r in ('20260924-073647','20260924-073944') for n in ('result.json','boundary.json','gradle-0.log')]
manifest=[]
for path in selected:
    if not path.exists():continue
    rel=path.relative_to(EVAL)
    out=HERE/'evidence/eval009'/rel;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,out)
    manifest.append({'source':str(path),'copy':str(out.relative_to(HERE)),'sha256':sha(path)})
save(HERE/'evidence/eval009-source-manifest.json',manifest)

def write(name,text):(HERE/name).write_bytes(text.encode())
write('reconstruction.md','''# TRANSITION-002 context-complete failure reconstruction

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
''')
write('expressibility.md','''# Existing-interface expressibility

**A valid J001 plan is easily expressible without changing production Hive.** The manually constructed plan is `evidence/manual-valid-plan.json`; it has backend as sole owner, UI/tests canonically inactive, behavior-preserving acceptance, and no interface contract. It contains no implementation or patch. It is used only in deterministic interface tests, never as a live model answer or example.

`interface_probes.py` runs JSON Schema Draft 2020-12 validation using jsonschema 4.25.1 in an isolated tooling directory; validates the schema itself; calls `_normalize_plan`, `_validate_host_write_scope`, `_validate_intent_coverage`; and checks the exact dispatch predicate. It then runs the real isolated Hive orchestration against a copy of the frozen baseline with a synthetic planner callback returning that plan. The backend callback is reached and deliberately raises before any model generation/edit. Reviewer is subsequently invoked by normal orchestration and also stopped by the sentinel. The resulting run is rejected with a skipped full-gate prerequisite, not accepted software.

Evidence: `evidence/expressibility-dispatch.json`, `evidence/expressibility-runs/e00300000001/`, `evidence/counterfactual-probes-before.json`. Normalized minimal plan is recorded in probe 01. Model calls: zero; worker callback: reached; files changed: none; executable verification: none. The first script launch had a diagnostic-only incorrect baseline dictionary key and stopped before dispatch; the key was corrected and the isolated dispatch probe completed. Production files were unchanged.

## Counterfactual results before repair

| Probe | Schema | Controller | Reason / dispatch |
|---|---|---|---|
| 01 one active owner | Accept | Accept | backend |
| 02 two active owners, valid contract | Accept | Reject | duplicate backend/tests ownership |
| 03 second active role requests read-only work, no files | Accept | Reject | active goal requires write files |
| 04 one active plus canonical inactive | Accept | Accept | backend |
| 05 two inactive roles | Accept | Accept | backend active; UI/tests inactive |
| 06 unauthorized path | Reject | Reject | outside host scope |
| 07 duplicate plus missing contract | Accept | Reject | reports both defects |
| 08 two disjoint writers with contract | Accept | Accept | backend/tests; explicitly synthetic two-file scope |
| 09 single owner, no contract | Accept | Accept | no contract necessary |
| 10 inactive goal with write claim | Accept | Reject | ownership and inactive/files contradiction |
| 11 disjoint writers, missing required contract | Accept | Reject | multi-role contract required |
| 12 all inactive | Accept | Accept | no workers eligible; not task success |

Enumerating each role's membership in the one-file assignment gives eight subsets. All eight satisfy the existing generation schema; four satisfy ownership validation (none or exactly one). The four multiple-writer subsets fail. This is a count of permitted structural states, **not a probability distribution**. Both historical TRANSITION-002 responses satisfy their generation schema but fail the normal validator. The tests-only/UI-only generic plans in that enumeration demonstrate syntactic ownership expressibility, not task-semantic suitability for changing Java application behavior.

The read-only probe uses `hive_context.observe(..., read_file_excerpt, ...)` to read application source without assigning it as a write. `validate_edit` still denies the tests role an edit to that context file when its assignment is a different test file. Evidence: `evidence/read-versus-write.json`. Separate context access works for an existing worker; the planner does not represent a standalone active read-only worker. Inactive roles are skipped, not dispatched as observers. Host verification and reviewer are separate from worker write ownership.
''')
write('eval009-contrast.md','''# EVAL-009 observable contrast

Evidence was found at `C:/Users/billy/Documents/Codex/2026-09-22/atm10-ai-companion-autonomous-build-mega/local-model-trial/`. Copies of relevant artifacts, with original paths and SHA-256, are under `evidence/eval009/` and `evidence/eval009-source-manifest.json`. Originals are read-only. Current orchestrator/pipeline source corroborates execution mechanics, but its historical byte identity is not independently established.

Stored `hive-eval-009/plan.json` contains an explicit `decompose_into` pair: activity-reset-service writes ActivityCommandService.java and reads LiveActivityService.java; activity-reset-command writes CompanionCommands.java and reads ActivityCommandService.java. Child contracts already specify the required API/command behavior, prohibit editing tests, and identify frozen acceptance. This is predetermined task-specific decomposition, not an observed model-generated role-ownership plan.

`orchestrated-runs/20260924-073647-a040db65/result.json` records routing from a 54,096-character parent to those two children under a 35,000-character limit. Both children are accepted at attempt 0 with Gradle exit 0; accepted service output is overlaid into the dependent command child. Final status ready_for_promotion, frozenTestsChanged=[], acceptanceExitCode=0, promoted=false. The recorded final command is **Gradle test**; do not equate that historical gate with the present frozen multi-task full gate merely because EVALUATION.md calls it a full Gradle suite. The earlier failed launches disclosed in EVALUATION.md remain failures.

| Dimension | EVAL-009 | Generalized planner in TRANSITION-002 |
|---|---|---|
| Ownership author | Stored explicit child plan | Local planner generates role file arrays |
| Write representation | Named child `writable` list | `worker_files` for UI/backend/tests |
| Read representation | Separate `read_only` list | Bounded source/observations; no standalone read-only worker goal |
| Shared file | Service child writes; command child reads | Role arrays all permit the same allowed path as a write |
| Inactive roles | No unused fixed roles to populate | Three required goal/file/acceptance records |
| Dependencies | Named accepted-child overlay | Planner generates interface contracts |
| Worker task | Prewritten narrow API/command contract | Planner-generated goal and criteria |
| Tests | Host-frozen, explicitly not editable | Host-frozen; planner must avoid inventing a tests writer |

This comparison shows a new ownership/decomposition burden absent from EVAL-009's successful execution path. It does not prove the generalized representation caused a particular token choice: task, harness, gates, prompts and execution protocol differ. It does not justify copying the old task-specific contracts into J001 or bypassing the current planner.
''')
write('ownership-semantics.md','''# Ownership semantics and role necessity

Authority is **whole-file write ownership assigned to worker roles**, not symbol or operation ownership. `_normalize_plan` checks exact safe relative paths and role scopes; `_host_write_scope_issues` compares every role's normalized paths for cross-role overlap and host membership; `_validate_host_write_scope` repeats that boundary check. `_prepare_agent_edits` and `validate_edit` enforce the actual worker assignment. Different symbols/operations do not authorize two writers to one file.

`worker_files` means may modify/responsible for implementation. Read-only map and facts explicitly confer no authorization. `hive_context.worker_context` and `observe` can supply another worker's source as evidence; no assignment is needed merely to read it. The roles are not instructed to list inspected files in worker_files. The worker prompt labels exact write files separately from shared/context information. Existing read/write semantics are substantially clear in prose.

There is nevertheless a representational burden: each active worker requires a nonempty write list and own acceptance. A tests goal that only wants to inspect or verify application code cannot be active with empty files. The clean representation for this task is one application owner, two inactive workers, and independent host verification/reviewer. J001 does not require an editable test artifact and cannot legally have two active writers under its one-file scope. UI/integration are not required; integration is not a worker role. Fewer roles are not generally better: disjoint multi-file application/test work remains valid and requires a coordinating interface contract.

Interface contracts do not grant files or force consumers to claim the provider's file in code. No dependency routine automatically duplicates assignments. Inactive roles remain included in ownership validation: any paths they claim can conflict, and inactive goals with nonempty files are independently invalid. The problem is not an executor interpreting read access as write access. The historical model explicitly chose an active test implementation goal and listed the production path.

`_planner_response_schema` independently intersects each role's global scope with host paths. External scopes are `**` for every role. Thus the J001 production path is advertised in all three write-array item enums. PLAN_SCHEMA permits active goals with empty files, inactive goals with nonempty files, and duplicate paths across roles. Normal validation rejects those combinations; there is no schema linkage between goal activity and file availability. General schema consistency beyond these directly relevant facts is out of scope.

`_planner_prompt` gives a three-active-role generic example but also explicitly permits inactivity and prohibits ownership overlap. `_plan_correction_prompt` includes the duplicate diagnostic, then substantial interface-contract schema/example guidance based on the rejected active roles. It says deactivate roles without authorized work but does not nominate which claim disappears. A human can resolve this: backend changes the application source; no test file is authorized. The instructions are expressive and not logically unsatisfiable, but correction continues to present the rejected multi-role structure as an example. Whether this is statistically influential remains unmeasured.

Relevant implementation: `workshop/hive.py` `_no_change_goal`, `_normalize_plan`, `_host_write_scope_issues`, `_planner_response_schema`, `_planner_prompt`, `_plan_correction_prompt`, `_run_build_impl.run_worker`, `validate_edit`, `_prepare_agent_edits`; `workshop/hive_protocol.py` PLAN_SCHEMA and role_constraints; `workshop/hive_context.py` worker_context and observe.
''')
write('diagnosis.md','''# Pre-edit diagnosis — HIVE-TRANSITION-003

**Classification: MIXED_INTERFACE_MODEL_FAILURE**

This artifact is written before any production edits. `evidence/pre-edit-seal.json` records its hash and verifies the copied production source still matches TRANSITION-002. It is not revised to fit the live result.

## Supported evidence

H1 in its strong form (no valid plan expressible) is falsified: a backend-only plan passes schema, normalization, ownership/host scope and reaches the real worker callback with zero model calls. Required facts and inactive-role instructions reached the historical model, yet both responses ignore exclusive ownership. That supports a model-compliance component.

A narrower H1 is supported: the generation schema admits all eight one-file ownership subsets, including four conflicting subsets that deterministic validation rejects. Both actual historical outputs pass their generation schema. Active/inactive consistency is left to prose. The three-role example and correction's rejected-role interface example plausibly reinforce unnecessary test work, but their probability effect is not established. EVAL-009 avoided this burden through predetermined children and explicit read/write separation; it is a contrast, not a controlled ablation.

The mixed diagnosis states an avoidable interface burden plus observed noncompliance. It does not assert that model quality is the general cause, that read access itself grants ownership, or that representation alone explains the behavior.

## Smallest justified repair selected before editing

For an exact host scope containing **one distinct writable file**, the normal ownership rules already imply at most one active writing role. Encode this implication in the planner generation schema with complete alternative branches: each eligible role can be the sole writer while others have canonical inactive goals and empty file/acceptance arrays; include an all-inactive branch for the existing no-change representation. The model still selects the owner and supplies its goal/criteria; the host does not pick backend or resolve conflicts by role priority. Scope/path type/filename never determines a hardcoded J001 solution.

Preserve multi-file schemas and valid multi-role execution. Preserve normal validators unchanged; duplicate or contradictory outputs supplied through any path still fail. Preserve one correction, measured 12,288 context, truncate=false, output caps, baseline/candidate isolation and all gates. Keep initial/correction text unchanged to isolate the structural intervention. Correction minimum-contract constraints, when independently required by immutable intent, must apply to every alternative rather than be dropped.

Why bounded to one-file scope: that capacity constraint is logically fixed from authority alone and directly covers the observed failure. A general per-file owner-map redesign would alter every plan/worker contract and require migration. Per-role filename heuristics would invent authority/role policy. Large ownership partitions for arbitrary multi-file scopes would expand schema exponentially. None is needed for this experiment. The remaining multi-file overlap checks stay in validation.

## Competing explanation and falsification

Pure H2 remains plausible for why this particular response failed: the original prose is clear, and a valid plan is simple. The schema language mismatch alone does not prove a statistical cause. If the fresh constrained request still yields overlap, or merely changes to another contradictory/no-work plan, record that as no verified dispatch improvement and inspect actual schema/runtime support before declaring stronger H2. If a valid owner reaches a worker, that supports this narrow structural repair but not a software-task success or reliability claim.

The exact affected transition is **planner structured generation → ownership-consistent plan validation → dispatch eligibility**. Historical invalid outputs must remain rejected; any repair that accepts them or silently drops a writer falsifies the intended containment claim. Any loss of T001 scope or T002 context protections also invalidates the repair.
''')
save(HERE/'evidence/pre-edit-seal.json',{'diagnosis_sha256':sha(HERE/'diagnosis.md'),
   'production_unchanged_from_transition_002':True,'source_manifest_sha256':sha(HERE/'evidence/source-before.json'),
   'expressibility_dispatch_sha256':sha(HERE/'evidence/expressibility-dispatch.json'),
   'counterfactuals_sha256':sha(HERE/'evidence/counterfactual-probes-before.json')})
print('Pre-edit diagnosis sealed; production is still unchanged.')
