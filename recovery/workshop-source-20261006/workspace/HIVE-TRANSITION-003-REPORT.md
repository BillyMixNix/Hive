# HIVE-TRANSITION-003 — Planner Ownership Representation

Classification: **OWNERSHIP_REPRESENTATION_DEFECT_IDENTIFIED_AND_REPAIRED**

The interface could express a valid plan, but its generation schema permitted two writers for a scope that could support only one. A bounded structural repair now expresses that existing capacity constraint during generation. The normal validator still rejects every previously invalid plan. The pre-edit causal diagnosis is **mixed interface/model failure**: complete prose was ignored, and the interface unnecessarily allowed the contradictory state. The schema mismatch does not establish a statistical cause for every failed response.

## 1. Prior experimental state

FACTORIAL-002 remains frozen: Hive 0/16 verified successes, control 0/16, 14 Hive planning failures, two reaching workers, none reaching frozen acceptance or the full gate. TRANSITION-001 repaired scope feedback and ownership validation but its final live trial still failed planning. TRANSITION-002 repaired independently demonstrated silent truncation; its one context-complete J001 trial still failed ownership validation. Neither repair was undone.

[Integrity evidence](HIVE-TRANSITION-003/evidence/prior-integrity-after.json) checks 18,002 factorial files, 2,986 TRANSITION-001 files, 844 TRANSITION-002 files, and 13 inspected EVAL-009 artifacts: unchanged. New source and evidence reside only in TRANSITION-003. The frozen baseline and candidate remain isolated; no promotion is authorized.

## 2. Exact TRANSITION-002 reconstruction

[Full reconstruction](HIVE-TRANSITION-003/reconstruction.md), [preserved run](HIVE-TRANSITION-003/evidence/transition-002/run.json), and exact [first completed request](HIVE-TRANSITION-003/evidence/transition-002/wire/02/wire-request.json)/[correction request](HIVE-TRANSITION-003/evidence/transition-002/wire/03/wire-request.json) preserve the trace for **6b87294fdc72**. HTTP attempt 01 failed CUDA initialization; 02 retried the identical request; 03 was the normal correction.

The task was to preserve UTF-16 surrogate pairs in `SnapshotFormatter.boundLine`, retain sanitization, the truncation suffix and ordinary ASCII behavior, and never exceed the bound. Exactly one file was writable: `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

Both responses assigned that file to **backend and tests**. Backend proposed the implementation; tests proposed regression coverage. UI was inactive. Separate intended responsibilities do not change whole-file write ownership. The first response had no interface contract; the correction added one while retaining both writers. JSON parsing succeeded. `_normalize_plan` raised during ownership validation, so **no normalized plan was returned**; the local candidate file lists are preserved without mislabeling them an accepted normalized plan.

First rejection: `file 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java' is assigned to both backend and tests; keep exactly one owner and deactivate roles without authorized work; multi-role plan requires at least one interface contract`. Corrected rejection repeats the duplicate-ownership clause. One correction was exhausted. No worker, edit or executable verification followed.

Requests used qwen2.5-coder:14b, `/api/chat`, separate system/user messages, `num_ctx=12288`, `truncate=false`, output cap 2048 and temperature 0.1. Rendered-token/provider counts matched **3834/3834** and **4652/4652**. This is provider-accounted completeness, not direct observation of model tensors. Exact schemas, raw responses, correction feedback, transport and tokenizer evidence are linked from the reconstruction.

## 3. Valid-plan expressibility

A minimal backend-only plan with UI/tests canonically inactive and no interface contract passes schema validation, normalization, host scope, ownership and dispatch eligibility **before repair**. A model-free invocation of the real Hive pipeline reaches the backend callback, which deliberately stops before an edit. This falsifies the strong H1 claim that valid J001 planning is impossible. It does not establish H2 alone.

[Expressibility](HIVE-TRANSITION-003/expressibility.md), [manual test plan](HIVE-TRANSITION-003/evidence/manual-valid-plan.json), and [actual dispatch sentinel](HIVE-TRANSITION-003/evidence/expressibility-dispatch.json). The manually constructed plan contains no implementation and was never supplied as an answer/example to live generation. Synthetic verifier fixtures are not frozen acceptance evidence.

## 4. Ownership semantics

`worker_files` grants **whole-file write authority**. It is not a list of inspected files, symbols or operations. `hive_context.worker_context`/`observe` provide read context independently; `validate_edit` enforces assigned writes. Interface contracts and dependencies do not implicitly add ownership. Inactive roles still undergo validation and cannot retain files.

An active worker must own at least one file and have acceptance criteria. There is no standalone active read-only worker representation. A worker may read another owner's file without claiming it, but a tests role that only inspects this one application file must remain inactive. Host verification and reviewer are separate. [Implementation trace and role analysis](HIVE-TRANSITION-003/ownership-semantics.md); [read-versus-write probe](HIVE-TRANSITION-003/evidence/read-versus-write.json).

## 5. Generation versus validation

Before repair, each external role independently receives the same one-path enum because each role's external scope is `**`. All eight subsets of UI/backend/tests ownership satisfy the generation schema; four violate exclusive ownership and are rejected downstream. Both actual TRANSITION-002 responses are schema-valid and controller-invalid. These are counts of structural states, **not probabilities**.

The prose clearly prohibits overlap and describes inactivity. However, the generic example has three active roles, and correction supplies a contract example using the rejected backend/tests pair. That could reinforce unnecessary decomposition; its influence is not measured. There is no logically contradictory instruction requiring tests to stay active. The demonstrated defect is the avoidable generation/validation mismatch, not an executor confusing reads with writes.

## 6. Deterministic counterfactual probes

[Before](HIVE-TRANSITION-003/evidence/counterfactual-probes-before.json) and [after](HIVE-TRANSITION-003/evidence/counterfactual-probes-after.json) record exact errors and normalized accepted plans.

| Case | Controller before/after | Relevant generation change |
|---|---|---|
| One active owner | Accept / accept | Still expressible |
| Two active owners, contract present | Reject / reject | Now schema-excluded for one-file scope |
| Second active role only needs read context | Reject / reject if represented with no writes | Now schema-excluded; independent read access still works |
| One active plus canonical inactive | Accept / accept | Still expressible |
| Two inactive roles, backend active | Accept / accept | Still expressible |
| Unauthorized path | Reject / reject | Still schema-excluded |
| Duplicate plus missing contract | Reject both defects / same | Duplicate now schema-excluded |
| Two disjoint writers with required contract | Accept / accept | Multi-file schema unchanged |
| Single owner, no contract necessary | Accept / accept | No new contract requirement |
| Inactive goal with file claim | Reject / reject | Overlapping inactive claim excluded; selected-owner goal contradiction still rejected semantically |
| Disjoint writers without required contract | Reject / reject | Independent multi-role requirement unchanged |
| All inactive | Accept structurally / accept structurally | No workers; never a task success |

After repair, exactly the four no-overlap ownership subsets remain schema-valid. Controller decisions are unchanged.

## 7. J001 role necessity

The authorized change is one bounded method in one writable file. It can have only one active writing owner under existing rules. Backend is a semantically natural choice, but the repair does not select it. No editable tests artifact is authorized. One implementation role plus inactive UI/tests and independent verification is already a clean representation. More roles remain valid for genuinely disjoint multi-file work; reducing role count universally is neither necessary nor implemented.

## 8. EVAL-009 contrast

[Detailed contrast](HIVE-TRANSITION-003/eval009-contrast.md) and [source manifest](HIVE-TRANSITION-003/evidence/eval009-source-manifest.json) preserve the available historical evidence. EVAL-009 used a stored, predetermined two-child decomposition with separate `writable` and `read_only` lists, narrow child contracts and a dependency overlay. Both child results were accepted at attempt 0; final orchestration was ready for promotion and unpromoted, with unchanged frozen tests and Gradle `test` exit 0.

That path did not ask a local planner to populate unused role records or distribute exclusive ownership. The generalized planner introduced that burden. Tasks and harnesses differ, so this is a behavioral contrast, not a controlled causal comparison. The recorded historical Gradle `test` must not be equated with the current multi-task full gate. Current source corroborates mechanics but its byte identity with the historical executable is not independently established.

## 9. Diagnosis recorded before editing

[Sealed diagnosis](HIVE-TRANSITION-003/diagnosis.md): **MIXED_INTERFACE_MODEL_FAILURE**. [Pre-edit seal](HIVE-TRANSITION-003/evidence/pre-edit-seal.json) proves it preceded production edits and records the unchanged prior source. A valid plan is easy to express; complete clear instructions were ignored, supporting a compliance component. At the same time, the generation schema explicitly permits all overlapping states, supporting a bounded interface defect.

Pure H2 remains a competing explanation for this particular token sequence. The final repair classification concerns the demonstrated interface mismatch and its removal, not proof that representation alone caused historical failures.

## 10. Production change

Only two functions in [workshop/hive.py](HIVE-TRANSITION-003/repaired-workshop/workshop/hive.py) change: `_planner_response_schema` and the correction schema update in `_plan_correction_prompt`. For one distinct host-authorized path, complete `anyOf` branches allow each scope-eligible role to be sole owner, with all other roles canonically inactive, plus the existing all-inactive state. The planner chooses the owner and supplies its goal/criteria. Independently required correction contract minimums apply to every branch.

No task ID, filename, language heuristic, role priority, implementation or Astra patch selects the owner. Nothing silently discards conflicting claims. Initial/correction prompt text, normal validators, scopes, provider, retry counts, context controls, edit execution, gates and baseline isolation remain unchanged. Multi-file schemas remain unchanged. The selected owner's freeform goal can still contradict its files; the unchanged validator rejects that. This bounded repair does not solve every possible schema/semantic mismatch.

[Repair explanation](HIVE-TRANSITION-003/repair.md), [applyable patch](HIVE-TRANSITION-003/repair.patch), [file hashes](HIVE-TRANSITION-003/repair-manifest.json), [function comparison](HIVE-TRANSITION-003/evidence/production-function-diff.json). The isolated repaired source is the delivered implementation; prior experiment source trees were not updated in place.

## 11. Regression results

The **complete available repository suite passed: 447 passed, 6 skipped**. All skips are Windows symlink-privilege limitations. [Log](HIVE-TRANSITION-003/evidence/regression.log), [command/result](HIVE-TRANSITION-003/evidence/regression.json), [runner](HIVE-TRANSITION-003/run_regression.py).

Twenty new ownership cases cover exclusive subsets, different paths/eligible owners, unauthorized writes, read versus write authority, inactivity/goal contradictions, correction constraints, multi-role expressibility, dispatch containment, schema-copy isolation and historical rejection. Existing TRANSITION-001 scope and TRANSITION-002 context-fidelity tests remain. Three existing test files adapt schema-shape assertions to all alternatives while retaining exact historical correction text checks. The schema oracle uses locally isolated jsonschema 4.25.1; [test dependency](HIVE-TRANSITION-003/test-requirements.txt) and downloaded wheels are preserved. No production dependency is added.

## 12. Historical replay

[Replay report](HIVE-TRANSITION-003/historical-replay.md) and [36-plan results](HIVE-TRANSITION-003/evidence/historical-replay.json): all 30 factorial planner responses, four TRANSITION-001 responses and two TRANSITION-002 responses were replayed without model calls against the prior and repaired controllers. **34 remain rejected; the same two already-valid factorial plans remain accepted.** No new dispatch eligibility, changed rejection message or changed correction-text hash occurs.

The initial generation schema now excludes eight preserved invalid outputs previously permitted; overall schema-valid responses fall from 11 to 3. Correction schemas carry the new exclusive alternatives. This changes what may be generated next, not how history is scored. The original revision-1 TRANSITION-001 dispatch with conflicting ownership remains invalid evidence, not a retroactive success.

## 13. Exactly one live diagnostic

Run **45ad10e6dd49**, final **MODEL_TASK_FAILURE / rejected**. It used the same frozen baseline, model, exact scope, deterministic gates and complete measured context. Four calls occurred: planner, backend, its one normal targeted correction, reviewer. There were zero planner corrections, zero structural repairs, zero observations and no extra trial. [Live trace](HIVE-TRANSITION-003/live-diagnostic.md), [machine summary](HIVE-TRANSITION-003/evidence/live-summary.json), [raw result](HIVE-TRANSITION-003/evidence/live-diagnostic/raw_results.json).

The first planner response passed with backend as sole owner and UI/tests inactive. Its request was identical to TRANSITION-002's first completed request in **every body field except `format`**. The worker's scoped exact replacement passed edit preflight and was applied in the private stage. The targeted verifier then timed out after the unchanged 240-second limit. Hive rolled the edit back and issued its one normal targeted correction. The worker repeated the response byte-for-byte; `RepeatedFailedProposal` rejected it before a second verification attempt. Full gate was explicitly skipped; reviewer rejected.

Rendered/provider input counts match for all four calls: **3834, 5512, 6007, 280**. Context stayed 12288 with truncate=false; full output-cap headroom was 6406, 776, 281 and 10472 tokens respectively. All returned objects satisfy their sent schemas. Both worker prompts include the entire owned baseline source. [Token evidence](HIVE-TRANSITION-003/evidence/live-input-measurements.json) was obtained afterward with render-only/tokenization, without additional generation.

The coarse legacy failure label does not distinguish infrastructure from model behavior. The actual post-edit obstacle was a **local verifier timeout**, followed by an identical correction. No retained report identifies the stalled internal verifier phase or proves individual frozen JUnit cases ran. No timeout or gate was altered to obtain a pass.

## 14. Furthest transition reached

**TASK → PLAN → OWNERSHIP VALID → WORKER DISPATCH → WORKER OUTPUT → EXECUTABLE EDIT → TARGETED VERIFICATION ATTEMPT**.

| Measurement | Result |
|---|---|
| Planner first-attempt validity | Accepted |
| Ownership | One backend writer; UI/tests skipped |
| Source grounding | Entire owned file present in initial/correction worker input |
| Scoped executable edit | Applied transiently; preserved diff/file and observation hashes |
| Targeted verification | Invoked; timed out at 240 seconds |
| Frozen acceptance | No result; individual case execution unknown |
| Full gate | Skipped after failed prerequisite |
| Final retained edit | None; rollback verified |
| Baseline/candidate | Candidate hash equals frozen baseline; applied=false |

The final changed_files=[] does not erase the observed temporary edit and verifier attempt. [Applied-stage evidence](HIVE-TRANSITION-003/evidence/live-stage-observation/observation.json) and [diff](HIVE-TRANSITION-003/evidence/live-stage-observation/first-applied.patch) distinguish transient execution from final retention. No J001 success is claimed.

## 15. Failure-frontier comparison

| Experiment | Furthest verified transition |
|---|---|
| FACTORIAL-002 | Worker output / edit preflight rejection in 2/16 Hive trials; other 14 stop in planning |
| TRANSITION-001 | Ownership validation, rejected in the final repaired live diagnostic |
| TRANSITION-002 | Ownership validation, rejected with complete input |
| TRANSITION-003 | Scoped executable edit and targeted verifier invocation; timeout, repeated correction, rollback |

The earlier revision-1 TRANSITION-001 worker dispatch occurred under defective ownership validation and is not evidence of a valid ownership transition. This fresh trial shows movement of the specific frontier with strict validation intact. It supports a narrow behavioral improvement, not a general success-rate claim or proof that ownership representation was the only cause of prior failures.

## 16. Falsification criteria

The containment claim fails if duplicate historical outputs become accepted, an unauthorized/inactive writer acquires authority, required verification is bypassed, or prior scope/context protections regress. Deterministic tests and replay found none of these. Strong H1 was already falsified by pre-edit expressibility.

The behavioral prediction is narrow: this schema should allow a complete-input one-file plan to progress beyond ownership conflict. Continued overlap would require checking actual provider schema support before attributing it solely to model reasoning. A valid worker dispatch supports that prediction for this one trial; it cannot establish a success rate. Repeated controlled paired trials would be needed to estimate reliability or isolate sampling variation and schema-grammar effects.

## 17. Remaining uncertainties

The causal contribution of generic role examples versus schema freedom was not separately ablated. No probability distribution follows from counting schema states. Native grammar enforcement is not byte-attested by inspection of the installed binary; actual sent schema, provider metadata and returned-object validation are the runtime evidence. Token accounting and rendered-template equality do not expose model tensors or prove attention to every fact.

The repair deliberately handles one-file write capacity; multi-file overlap and other semantic contradictions still rely on the normal validator. Active read-only workers remain unsupported. The all-inactive representation remains possible and is not software-task success. Historical EVAL-009 and current gates are not equivalent. One new J001 trial cannot establish general model or system performance.

The new runtime timeout is unresolved; partial container output was not retained by the unchanged timeout path, so setup, compilation and test execution cannot be distinguished. The repeated correction received a timeout diagnostic, not a failing behavioral assertion. Separately, the original ASCII-preservation requirement reached the planner but is absent from its derived worker contract. Complete source access does not prove complete task-semantic preservation. These are recorded next-frontier observations; neither prompted another repair or live trial in this study.
