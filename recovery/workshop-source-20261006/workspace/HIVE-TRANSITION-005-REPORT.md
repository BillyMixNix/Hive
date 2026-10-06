# HIVE-TRANSITION-005 — Task→Worker Semantic Fidelity

Classification: **SEMANTIC_AND_CORRECTION_DEFECTS_REPAIRED**

The semantic and correction information channels are repaired and regression-tested. The single fresh live trial ended as **LOCAL_RUNTIME_FAILURE**. Fresh frozen acceptance: **False**; full-gate success: **False**. No model response was obtained, so the worker-revision and acceptance questions remain untested.

## 1. Prior experimental state

FACTORIAL-002 remains 0/16 Hive and 0/16 control successes; fourteen Hive runs stopped in planning. TRANSITION-001 repaired scope feedback/ownership validation; 002 repaired input truncation; 003 repaired single-file ownership generation. Its run `45ad10e6dd49` produced an edit but timed out, rolled back and repeated the same proposal. TRANSITION-004/004B/004C made verification observable and reused only attested invariant dependencies, then removed unused incremental-compilation bookkeeping. The 004C baseline completed in 207.605 bounded seconds with 3/1/0/0; the preserved candidate completed in 201.959 seconds with 3/2/0/0. Those are post-hoc failures, not autonomous successes. No historical result is rescored.

## 2. Frozen J001 requirement ledger

[Task-only requirement ledger](HIVE-TRANSITION-005/requirement-ledger.md) identifies seven explicit requirements: pair preservation, control sanitization, section-sign sanitization, ellipsis, ASCII compatibility, no newly unpaired surrogate, and total bound. It adds no requirements from tests. Scope remains exactly `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

## 3. Requirement propagation trace

[Human-assessed semantic trace](HIVE-TRANSITION-005/semantic-trace.md) and [machine-readable trace](HIVE-TRANSITION-005/semantic-trace.json) distinguish explicit/equivalent/partial/absent information at all nine requested stages. Exact preserved wire requests, raw responses and normalized plan are copied under [reconstruction evidence](HIVE-TRANSITION-005/evidence/reconstruction). The planner received the full task. R5 disappears in raw planner output. Normalization preserves the remaining strings. R1–R4 survive local acceptance; R6 is represented equivalently by pair preservation. Global acceptance explicitly retains R7, while worker-local wording is less explicit about the total suffix-inclusive bound.

## 4. Earliest semantic-loss boundary

R5 is a **model omission at PLANNER REQUEST → PLANNER OUTPUT**, made consequential by **controller omission at NORMALIZED PLAN → WORKER CONTRACT**: no independent original task reaches the worker. The empty host intent envelope does not restore it. Normalization and serialization are not the loss boundary. The preserved candidate passed the ASCII case; this means R5 loss is not demonstrated to have caused its two surrogate failures.

## 5. Architectural semantics analysis

[Architecture analysis](HIVE-TRANSITION-005/architecture.md) documents the previous plan-only executor test and intended decomposition. Worker-local acceptance should specialize responsibility without replacing host requirements. `_worker_prompt` received summary/goal/local criteria, not the enclosing original request or global plan acceptance. General semantic completeness was not validated. The schema can express the task; the interface depended on error-free model summarization.

## 6. Deterministic semantic probes

All ten pre-edit synthetic plans normalized and rendered, including omitted ASCII/sanitization/bound/suffix, weakened surrogate language, paraphrase, distributed criteria, contradiction and local criteria with global invariants. No semantic omission was detected. [Before probes](HIVE-TRANSITION-005/evidence/semantic-probes-before.json); [after probes](HIVE-TRANSITION-005/evidence/semantic-probes-after.json). After repair, all retain the exact host task and their local criteria. Contradictory natural language is not falsely claimed to be automatically rejected; the worker now has both authorities and an explicit conflict rule.

A separate [strict generation-schema check](HIVE-TRANSITION-005/evidence/semantic-generation-schema-check.json) removes the copied host-only `_intent_envelope` metadata and confirms all ten semantic variants satisfy the unchanged generation schema, normalization and scope validation. No model was called for these probes.

## 7. Pre-edit diagnosis

[Sealed pre-edit diagnosis](HIVE-TRANSITION-005/semantic-loss-diagnosis.md) predates production edits; [seal](HIVE-TRANSITION-005/evidence/pre-edit-seal.json). Supported interface defect: lossy planner output replaces task authority in worker prompts. Competing explanation: a fully informed Qwen may still implement the task incorrectly. Falsification: find equivalent ASCII compatibility in the preserved worker wire, or demonstrate the original task was independently transmitted. The preserved requests support neither.

## 8. Semantic-fidelity repair

`original_task` explicitly carries the enclosing host request through initial, observation, JSON repair, structural repair and targeted-correction worker construction. Replanning uses the same closure and unchanged host task. The task applies within assigned responsibility/files; it grants no additional writes. Local criteria remain present. No task-specific extraction, solution or semantic keyword validator was added. Context size remains 12,288, temperature/model/output limits unchanged, silent truncation disabled.

## 9. Semantic regression results

New deterministic tests exercise real single/multiple worker dispatch, host/local criteria, inactive-role skipping, repair helpers, correction dispatch and repeated-proposal rollback, paraphrases and contradictions, malformed plans, and sealed hidden source outside prompt context. Existing scope, ownership and provider context tests remain. [Semantic tests](HIVE-TRANSITION-005/repaired-workshop/tests/test_semantic_fidelity.py).

## 10. TRANSITION-003 correction reconstruction

[Exact correction reconstruction](HIVE-TRANSITION-005/correction-reconstruction.md). The historical message said only “Isolated verification timed out after 240s.” No test names, assertion messages or expected/actual values existed in that correction. Original owned source and the full previous proposal were supplied. It explicitly demanded a materially different replacement and warned about repeated-proposal rejection. The model repeated the same canonical edit. Initial input was 5,512 tokens; correction 6,007; preserved runtime/rendered counts matched, num_ctx=12,288 and truncate=false.

## 11. Correction-evidence adequacy

Historical classification: **CORRECTION_EVIDENCE_INCOMPLETE** for repairing Java behavior, with an independently lossy task contract. A timeout without phase evidence cannot explain an assertion failure not yet observed. The repeated response is noncompliance with the revision instruction, not evidence that the model ignored a concrete failing assertion. Do not substitute 004C's later results for the actual 003 feedback.

## 12. Correction transport repair

Replaying the actual 004C report through the old formatter produced 16,908 serialized characters, clipped to 6,000; the structured tests field began at character 16,580. Both failing test names happened to survive stdout, but counts/acceptance mismatches did not. `_reports` also discarded emitted JUnit failure attributes while aggregating counts. The repair preserves bounded test names, exception types and emitted messages, without test source or stack traces. `_targeted_diagnostic` prioritizes results, removes machine inventory lines from logs and retains valid JSON with explicit omission markers. It preserves timeout/report errors. [Correction replay](HIVE-TRANSITION-005/evidence/correction-replay.json). The replay does not invent historical assertion messages that were never retained.

## 13. Complete regression result

**501 passed, 6 skipped** in the final full-suite run; platform skips concern unavailable symlink privileges. [Full log](HIVE-TRANSITION-005/evidence/regression/complete-03/pytest.log). Real Docker timeout/descendant cleanup and actual full-compilation valid/invalid-source probes passed. A preliminary direct test invocation hit Windows default-temp permissions; the established isolated D: temp harness resolved that setup problem. The first complete run found an obsolete plan-only wording test and an incorrect native-vs-external gate assumption in a new fixture; both test expectations were corrected without changing gates. The second full run passed; the final run also covers preserved missing-report diagnostics. Earlier runs remain recorded.

## 14. Verifier readiness

| Control | Bounded verifier seconds | Total host seconds | Frozen cases / failures / errors / skipped | Ready |
|---|---:|---:|---|---|
| readiness-baseline | 202.621 | 234.673 | 3/1/0/0 | True |
| readiness-preserved | 207.068 | 239.580 | 3/2/0/0 | True |


[Readiness decision](HIVE-TRANSITION-005/evidence/readiness.json). Each control used a fresh isolated candidate, the production attested NFRT seed, unchanged image/JDK, offline gates, source integrity and 240-second bounded verifier. Host totals also include integrity/preflight/postflight and cleanup outside that inherited bound. Readiness requires the same failing test identities as 004C, not just matching counts. No model call is permitted if either control fails.

## 15. Exactly one live J001 trajectory

Run `272595f790fd`. [Complete trajectory](HIVE-TRANSITION-005/evidence/live-summary.json). [Exact HTTP requests/responses](HIVE-TRANSITION-005/evidence/live-diagnostic/wire).

Planner first-attempt validity: **not evaluated; no model plan**. Original task present in live initial worker contract: **worker not reached**. Logical model calls: **1**. Successful model responses: **0**. Normal protocol budgets were unchanged. No Astra implementation, preserved candidate or hidden test source was supplied to the new model trajectory. Candidate snapshots are captured only after the model proposes them, for evidence, never as model inputs.

The fresh trial did not test worker behavior: no completed model response, worker dispatch, candidate edit, targeted correction, frozen acceptance or full gate occurred. Two HTTP attempts belong to the provider's pre-existing single retry inside one logical planner call. The first returned HTTP 500 with a 5,843,582,976-byte CUDA-host allocation failure. The second attempt's exact outcome is in the call/error evidence below. A contemporaneous memory sample showed 669,696 KiB free physical memory and 929,216 KiB free virtual-memory capacity. The runner later reported healthy/processing with context 12,288 but exposed no completed token accounting. That does not establish why the second attempt stalled. The outbound planner content was identical to TRANSITION-003; the repaired worker prompt was never reached. No resource settings were changed and no additional trial was launched.

Live error record (verbatim structured evidence):

```json
[
  {
    "role": "run",
    "stage": "agent_call",
    "exception_type": "OllamaRequestError",
    "exception_message": "Ollama chat failed at http://127.0.0.1:11434: chat attempt 2/2: OllamaRequestError: Ollama generation exceeded the 900-second total limit"
  }
]
```


## 16. Initial candidate result

Initial proposal differs from TRANSITION-003: **not evaluated; no implementation**.

No initial targeted verification occurred in the live trial.

No live candidate source or diff exists: the trial did not reach edit creation. The external candidate hash remains identical to baseline.

## 17. Correction behavior

Normal targeted corrections: **0**. Materially different second proposal: **not evaluated**. Repeated-proposal rejection triggered: **False**. No fresh worker correction prompt was issued. Its fidelity is established only by deterministic regression and preserved-report replay, not by a live repair response. No manually derived solution hints are added.

## 18. Revised candidate result

No second executable candidate reached verification. Consult the trajectory for the exact stopping condition.

## 19. Frozen acceptance result

Fresh frozen acceptance reached: **False**. A planner response, worker dispatch or applied transient edit is not task success. Readiness replays are separately labeled controls; the preserved candidate is still a historical failure.

## 20. Full-gate result

Full-gate verifier invoked: **False**. Full gate passed: **False**. The inherited full verifier itself rechecks frozen acceptance before the fixed `clean build runGameTestServer runQuestTestServer packTestJar` gate. Promotion: **none**.

## 21. Failure-frontier comparison

| Experiment | Furthest verified transition |
|---|---|
| FACTORIAL-002 | mostly planning; two reached worker/edit preflight |
| TRANSITION-001 | ownership validation |
| TRANSITION-002 | ownership validation with complete input |
| TRANSITION-003 | executable edit → verifier invocation |
| TRANSITION-004 | verifier timeout localized |
| TRANSITION-004B | dependency reconstruction reused |
| TRANSITION-004C | frozen JUnit decision on verifier-only replay |
| TRANSITION-005 | model runtime before PLAN; worker fidelity verified only deterministically |

## 22. Unchanged safety properties

[Final integrity audit](HIVE-TRANSITION-005/evidence/final-audit.json) verifies 10114 prior files unchanged, approved cache/baseline/image/attestation integrity, exact gate implementation outside diagnostic report enrichment, unchanged provider/context/scope/ownership/edit validation, and readonly mounts/container cleanup. Production changes: `workshop/hive.py` and `verification/jvm_runner.py`; tests: `tests/test_semantic_fidelity.py` and `tests/test_hive_scopes.py`. [Reviewable patch](HIVE-TRANSITION-005/production.patch). No assertion/selector/source-scope, retry budget, timeout, dependency reuse or compilation-mode changes. No cached candidate classes/tests/reports/acceptance state are reused.

## 23. Remaining uncertainties

Transport completeness does not prove semantic reasoning or compliance. Preserved ASCII compatibility passed despite omission; no causal claim ties that omission to the surrogate failures. Bounded diagnostics may explicitly omit excess information. The repair does not add natural-language entailment validation. Disabled truncation preserves the prior fail-closed context policy; byte-perfect internal attention is not observable. No completed live token accounting or exact model visibility is available; [known-sent configuration only](HIVE-TRANSITION-005/evidence/live-input-measurements.json). One diagnostic cannot establish reliability or a success-rate improvement. Prior evidence and classifications remain frozen. If the fresh trial never reaches a worker, Questions C and D remain untested rather than falsified.
