# HIVE-TRANSITION-001 report

Classification: **PARTIAL_DIAGNOSIS**

The supported defect is incomplete propagation of the host's write and ownership contract into planner generation and correction. In ordinal 3, the host spends its only correction on a missing role contract while an unauthorized test-file assignment is already present. Correction supplies the requested contract, then a later validation stage exposes the scope violation and terminates the run. The repair makes scope errors visible together, constrains generated path choices to existing host authority, and enforces exclusive file ownership. It does not solve J001 inside Hive or relax any acceptance gate.

Concrete interface defects are reproduced and repaired, but the final live diagnostic still cannot produce a valid plan. Therefore a sufficient root cause of the failed execution trajectory has not been established. This classification does not assert that all Hive failures have the same cause, that the repair produces correct implementations reliably, or that model quality has been isolated as a cause.

## Ordinal 3: what actually happened

Task J001, replicate 2, qwen2.5-coder:14b, Hive, run `cace24ea0b5e`:

1. The planner receives the task, repository map, repository facts, explicit one-file write boundary and three-role plan contract. It receives no observation loop or direct edit action at this stage.
2. The first raw response is valid JSON. It assigns the allowed production file to backend and an unauthorized test file to tests. It omits the required multi-role interface contract.
3. `_normalize_plan` rejects the missing contract before `_validate_host_write_scope` can report the unauthorized assignment.
4. The single correction repeats the complete prompt and rejected plan, reports only the contract defect, and constrains `interface_contracts.minItems` to one. File paths remain unrestricted strings in the generation schema.
5. The corrected response supplies a linking contract and retains the unauthorized test file. Parsing and normalization pass; host scope validation now rejects it. The correction budget is exhausted.
6. No worker is called. No edit is proposed or executed. Verification and review are null. Baseline, candidate copy and stage all have the identical frozen hash `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`.

The earliest **observed rejected transition** is plan validation; the invalid scope choice is already visible in the first serialized plan. The terminal label “planner correction” is a symptom, not the diagnosis. No evidence supports blaming action parsing or the edit executor in this specimen, because neither is reached.

[Complete reconstruction](HIVE-TRANSITION-001/reconstruction.md) covers all twelve requested points with source functions, line references, stage events and errors. [Exact first prompt](HIVE-TRANSITION-001/evidence/ordinal-03/planner-1.prompt.txt), [first response](HIVE-TRANSITION-001/evidence/ordinal-03/planner-1.response.txt), [correction prompt](HIVE-TRANSITION-001/evidence/ordinal-03/planner-2.prompt.txt), and [corrected response](HIVE-TRANSITION-001/evidence/ordinal-03/planner-2.response.txt) match preserved SHA-256 values. Schemas are reconstructed from the frozen source; they were not independently captured as historical HTTP bodies. The before replay regenerates both prompts exactly.

## All sixteen Hive trials

| Earliest observable failure class | Count | Ordinals |
|---|---:|---|
| Missing role contract masks an existing host scope violation | 8 | 3, 8, 9, 14, 20, 21, 27, 32 |
| Inactive-role prose fails the recognized no-change contract | 6 | 4, 12, 16, 19, 24, 30 |
| Worker edit anchor is absent from source | 2 | 6, 26 |

All eight qwen2.5-coder trials repeat the primary specimen's failure class. Eleven of fourteen initially rejected plans already violate scope; all fourteen corrected rejected plans violate it. These overlapping observations are not additional trial counts. The six inactive-role failures include wording such as `No UI changes required`, which the host does not recognize as its canonical inactive goal. The two worker trials produce structurally shaped edit requests with invented anchors and fail one structural repair.

All thirty preserved planning responses parse as JSON. Fourteen runs stop in planner correction; two reach workers; none produce changed files or reach executable frozen acceptance/full Gradle verification. A failed `external_full_gate_prerequisite` record means the gate was skipped, not that Gradle executed and failed. No Hive trial records a local provider runtime failure.

[Per-trial taxonomy](HIVE-TRANSITION-001/failure-taxonomy.md) and [machine-readable attempts, source paths and hashes](HIVE-TRANSITION-001/failure-taxonomy.json) contain the complete classifications.

## Observable Astra contrast

The independent evidence demonstrates actual source inspection, one authorized source-file change, baseline failure reproduction, and candidate execution against existing tests and 10,698 supplemental probes. Its initial report is BLOCKED on the sealed environment; later independent `sealed-evidence/full.json` records frozen J001 acceptance and the full Gradle gate against the same candidate fingerprint. Those are preserved Astra results, not new Hive successes.

Hive's planner must complete a multi-field role serialization contract before the worker can inspect source or edit. Ordinal 3 never reaches those capabilities. The relevant contrast is access to an executable engineering loop, not hidden reasoning or copying the successful implementation. [contrast.md](HIVE-TRANSITION-001/contrast.md) compares information, task representation, schemas, actions, parsing, feedback and validation, and identifies missing original tool-transcript evidence.

## Repair and falsification

Only one production file changes: [workshop/hive.py](HIVE-TRANSITION-001/repaired-workshop/workshop/hive.py). The evaluated original remains untouched; this is a separate repaired source copy. The [patch](HIVE-TRANSITION-001/repair.patch) includes the implementation and new regression tests and passes a read-only `git apply --check` against the frozen source. The tests run from the delivered study layout and consume its preserved response artifacts.

- Planner initial/correction schemas use exact host-authorized path enums, intersected with existing role scopes. With no host boundary, the existing schema is preserved.
- Normalization collects scope and ownership violations together with other plan errors before requesting correction. It never deletes an assignment or invents a plan.
- The prompt explicitly states the existing canonical inactive goal and single-owner requirement. A scope/ownership correction may deactivate a role without being forced to invent a contract. Genuine multi-role plans still require a linking contract.
- Duplicate role ownership is rejected. This final tightening was justified by the first new diagnostic, which exposed a preexisting mismatch between promised and implemented validation.

No J001 implementation is embedded in Hive. Synthetic edit regressions use an unrelated `Widget.value` example. No worker edit operations, write authority, deterministic gates, frozen acceptance, model tier, inference settings, correction limits, promotion policy, or candidate isolation are broadened.

The main diagnosis would be falsified if the original first-attempt validation already reported the scope error, or if its correction already carried a path-constrained schema. Exact source reconstruction and replay show otherwise. The ownership finding would be falsified if the overlapping live plan were rejected by the original validator; differential replay shows it is accepted there. Live failure after repair limits its behavioral benefit and must not be relabeled as success. [diagnosis.md](HIVE-TRANSITION-001/diagnosis.md) gives evidence and explicit falsification criteria for each supported or competing hypothesis.

## Deterministic regression and historical replay

Final boundary suite: **237 passed, 2 skipped**. Skips are existing symlink tests requiring unavailable Windows privileges. The first invocation encountered an inaccessible default pytest temp directory; recorded successful runs use fresh task-specific temp directories. See [final test log](HIVE-TRANSITION-001/evidence/regression-final.log) and [exact command](HIVE-TRANSITION-001/evidence/regression-final.json).

[New tests](HIVE-TRANSITION-001/repaired-workshop/tests/test_planner_transition.py) cover preserved failing responses, a valid equivalent plan, malformed and scope-violating output, correction exhaustion, worker eligibility, schema isolation, empty/absent authority, and the newly exposed duplicate ownership. Existing tests cover observations, Java edits, external isolation, intent coverage, provider schemas and verifier ordering. Dispatch/edit tests use explicitly synthetic verifier sentinels; they are not J001 acceptance evidence.

Full before/after replay of ordinal 3 returns the same terminal failure with no workers, edits or verification. Both raw responses remain correctly rejected. The change is the complete first diagnostic and a correction schema that permits removing the unauthorized role. [Replay report](HIVE-TRANSITION-001/historical-replay.md) links both runs and full prompts/schemas.

[Differential replay](HIVE-TRANSITION-001/evidence/differential-plan-replay.json) checks 32 preserved plans: all 30 factorial acceptance decisions remain unchanged, with exactly two accepted plans. The first live diagnostic's overlapping corrected plan, accepted by the original validator, is rejected by the final repair. No previously rejected plan becomes accepted.

## New live-model evidence

Two separately recorded adaptive diagnostics use frozen M3.2, J001, the exact qwen2.5-coder:14b digest, the original single-file scope, temperature/output limits, local-only policy, pinned verifier image and approved offline cache. They do not overwrite HIVE-FACTORIAL-002 and are not reliability replicates. [Revision 1](HIVE-TRANSITION-001/FREEZE.json) and [revision 2](HIVE-TRANSITION-001/FREEZE-revision2.json) have separate freezes. Diagnostic harness adaptations are in [diagnostic-harness.patch](HIVE-TRANSITION-001/diagnostic-harness.patch); `run_one` retains its original gating and budget behavior.

Revision 1, run `8aa64e4e455d`, records five calls and reaches backend and tests through a flawed overlapping plan. Both workers return invalid `plan_insufficient` requests for their already-owned file. No edit or executable verification follows. This is an exposed validation gap, **not clean transition improvement**. Its source, freeze and replay artifacts are preserved under `evidence/revision-1/`; [live-revision1.md](HIVE-TRANSITION-001/live-revision1.md) documents the limitation.

Final revision, run **`75280298dd02`**, records two planner calls, one correction, 302.841 wall seconds and `MODEL_TASK_FAILURE` / `failed`. The model repeats duplicate ownership in its corrected plan. The repaired validator rejects it before any worker. This changes the specific rejection from an unauthorized test path to duplicate ownership; it **does not demonstrate valid progress beyond planning**.

| Measurement | Historical ordinal 3 | Revision 1 diagnostic | Final revision diagnostic |
|---|---|---|---|
| Worker reached | No | Yes, through a flawed overlapping plan | **No** |
| Valid scoped edit produced | No | No | **No** |
| Executable deterministic verification reached | No | No | **No** |
| Frozen acceptance reached | No | No | **No** |
| Full Gradle gate reached | No | No | **No** |
| Candidate/stage differ from baseline | No | No | **No** |
| Applied / cloud cost | No / $0 | No / $0 | No / $0 |

The valid equivalent plan reaches a worker only in deterministic regression fixtures, not in either live diagnostic. No frozen acceptance success is claimed for Hive. See [final raw result](HIVE-TRANSITION-001/evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/result.json), [full run](HIVE-TRANSITION-001/evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/run.json), [captured model-boundary requests and responses](HIVE-TRANSITION-001/evidence/live-revision2/model-boundary/02/request.json), and [comparison with final tree hashes](HIVE-TRANSITION-001/evidence/live-comparison.json).

The scope and feedback hypothesis is therefore **insufficient as a complete explanation**: fixing the demonstrated interface defects did not make the local model emit a valid plan in the final diagnostic. The test has exposed that limit rather than manufacturing a PASS. No further repair or model trial was performed after this terminal result.

## Integrity and remaining uncertainty

All **18,002** inventoried original factorial files are unchanged, with none missing or added, excluding Python/pytest caches. The evaluated source manifest exactly matches its frozen hash. [Evidence integrity](HIVE-TRANSITION-001/evidence/factorial-integrity-after.json), [frozen source check](HIVE-TRANSITION-001/evidence/frozen-source-integrity.json), [repair hashes](HIVE-TRANSITION-001/evidence/repair-manifest.json), and [final code/diagnostic lock check](HIVE-TRANSITION-001/evidence/final-source-identity.json) preserve provenance. Both new candidate and stage trees still match the immutable baseline after their runs.

Context delivery remains unresolved. All historical corrections and worker calls report 2,050 input tokens at a 4,096-token runtime despite much longer host prompts. In revision 1, a worker claims a missing constant that is present in its preserved source context. Effective token sequences and relevant server truncation events are unavailable; context loss is plausible, not proved. Source access at the host is not evidence that the model retained or used it.

The planner still uses a substantial role contract for small changes, and external role semantics cannot be fully inferred from arbitrary file paths. The repair addresses explicit path authority and exclusive ownership, not all semantic correctness. The independent Astra result establishes solvability, not transferable reliability. The present evidence does not estimate Hive's success rate or show superiority over the single-agent control.
