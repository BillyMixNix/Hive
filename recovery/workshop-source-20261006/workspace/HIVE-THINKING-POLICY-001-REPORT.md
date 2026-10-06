# HIVE-THINKING-POLICY-001

Classification: **THINKING_POLICY_MECHANISM_SUPPORTED**

Exactly six preselected fresh cells completed. Complete schema-valid worker responses were obtained in **6/6 cells**; **6/6** produced executable scoped text edits, **0/6** passed frozen acceptance, and **0/6** passed the full required gate. No candidate was applied.

## 1. Historical failure class

FACTORIAL-003R1 remains immutable: 2/16 verified software successes. This experiment selected its qwen3:8b cells 3, 6, 8, 9, 12 and 15 because their backend generations exhausted the normal 900-second limit. Historical data is not rescored.

Four selected calls emitted only thinking content. Cells 3 and 12 began answer content around 862 and 880 seconds but did not finish. All six established HTTP 200 streams within approximately 8–16 seconds; those were active generations, not demonstrated startup/allocation failures.

## 2. Stream reconstruction

The complete per-call reconstruction, exact wire hashes, model digest, settings, terminal states and resource references are in [historical-timeout-reconstruction.md](HIVE-THINKING-POLICY-001/historical-timeout-reconstruction.md) and [historical-calls.json](HIVE-THINKING-POLICY-001/evidence/historical-calls.json). Character/channel counts are not token counts; interrupted historical streams lack terminal provider usage.

**Denominator caveat:** 0/6 is completion of the six selected failed calls. Cell 15 timed out on correction after a completed initial worker and failed behavioral tests. Whole-cell historical any-worker completion, executable edit and targeted-verification reachability are each 1/6, not 0/6. Fresh whole cells can take different call paths.

## 3. Provider capability proof

Two pre-edit non-task requests used the same synthetic arithmetic prompt and JSON schema, context 12288, output cap 6000, temperature 0.1, truncate=false and 900-second bound. Both returned complete valid JSON on the frozen digest. `think:true` emitted 617 thinking characters and took 48.887s; `think:false` emitted 0 and took 6.011s. The first also loaded the model; this is transport proof, not a controlled speed or task-quality comparison.

The installed provider advertises thinking capability but omits supported-value metadata. The measured template exposes an explicit Boolean switch. A host-owned capability profile therefore binds the exact digest, template hash and provider version, rather than treating every thinking model as switchable. [Probe evidence](HIVE-THINKING-POLICY-001/evidence/capability/result.json). API background: [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking).

## 4. Transport implementation

`providers.ollama_chat` accepts optional Boolean `think`; omission preserves the prior body and avoids capability requests. Explicit values require the host-attested identity to match local provider metadata before generation. Unsupported values/models or identity drift fail clearly. The selected value is placed at the top level of the actual request, recorded in returned metadata and retained unchanged across retries. No post-failure switching is implemented.

## 5. Frozen role policy

Only bounded structured ui/backend/tests calls for the proven qwen3 profile receive false, including structural and targeted corrections. Planner/reviewer and unrelated model/provider combinations retain omitted/default behavior. The decision depends on provider/model capability, role, schema and finite bounds, never a task ID, source filename, cell number, previous failure or desired solution.

Unchanged: qwen3 digest; context 12288; worker/planner/reviewer output caps 6000/2048/1536; temperature 0.1; truncate=false; normal two-attempt provider policy; 900-second generation setting; one planner/structural/targeted correction; 3600-second aggregate decision ceiling; exact scopes; 240-second targeted and 660/600-second full verifier bounds; offline pinned image/JDK; NFRT attestation; fresh compilation; rerun-tasks/no-build-cache; all acceptance assertions; reviewer and promotion policies.

## 6. Regression results

Complete source suite: **656 passed, 6 skipped**. The skips are inherited Windows symlink limitations. Qualified harness: **52 passed**. New tests cover true/false/default transport, unsupported/mismatched identities, exact wire fields, default preservation, same-body retries, provider/deadline failures and actual application worker/correction dispatch. Existing scope, context, ownership, semantic transport, verifier, NFRT, rollback, reviewer and promotion protections pass.

Initial test setup failures and their resolution are retained, including vendored test-only dependency/fixture relocation and the provider-history assertion updated for the intentional transport extension. No gate was weakened. [Implementation and test notes](HIVE-THINKING-POLICY-001/implementation.md), [complete JUnit](HIVE-THINKING-POLICY-001/evidence/full-regression-final/pytest.xml), [harness JUnit](HIVE-THINKING-POLICY-001/evidence/harness-tests.xml).

## 7. Diagnostic freeze

Source tree SHA-256: `9bff60ebc3c8feddafe91672ceb7d3d3f7cb6f651e3e277c4fa0aa4d95953afa`. Original source SHA-256: `f495206de7fecfe5950f941826a84dfd1d81d2ceac164a1899d5eede5cd04ca7`. Model digest: `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`. Provider: Ollama 0.34.0. [FREEZE.json](HIVE-THINKING-POLICY-001/FREEZE.json) contains byte inventories, exact task/test/baseline identities, image/JDK/Gradle identity, seed attestation, hardware, configuration and order. No frozen production or execution-harness file changed after task execution began.

## 8. Six-cell design and isolation

Historical relative order was preserved. Each selected condition received one fresh normal Hive execution from the unchanged baseline. No replacements, extra trials, warmups, model unload/reload, memory tuning, manual candidate fixes or promotion occurred. Hidden tests and previous candidates were not supplied as model context. The only pre-study inference was the two declared non-task probes.

## 9. Per-cell generation and paired outcomes

| Historical cell | Task / replicate | Historical selected worker result | Prospective worker times (seconds) | Historical frontier | New highest level |
|---|---|---|---|---|---|
| 3 | J004 / 1 | initial worker timeout | initial: 100.865 (complete); targeted correction: 120.725 (complete) | worker | TARGETED_VERIFICATION_REACHED |
| 6 | J003 / 1 | initial worker timeout | initial: 60.416 (complete); targeted correction: 79.868 (complete) | worker | TARGETED_VERIFICATION_REACHED |
| 8 | J003 / 2 | initial worker timeout | initial: 69.267 (complete); targeted correction: 86.956 (complete) | worker | TARGETED_VERIFICATION_REACHED |
| 9 | J002 / 2 | initial worker timeout | initial: 133.021 (complete); targeted correction: 177.685 (complete) | worker | TARGETED_VERIFICATION_REACHED |
| 12 | J004 / 2 | initial worker timeout | initial: 91.942 (complete); targeted correction: 115.240 (complete) | worker | TARGETED_VERIFICATION_REACHED |
| 15 | J002 / 1 | correction timeout; initial worker completed | initial: 130.240 (complete); targeted correction: 160.278 (complete) | worker_correction | TARGETED_VERIFICATION_REACHED |

All-worker call counts: 12/12 complete; 12/12 parseable and schema-valid; 0 worker deadline failures. Median completed-worker logical-call duration: 108.052s. Timing includes capability validation overhead; stream latency and provider-generated token accounting are recorded separately.

| Cell | Call | Kind | First answer seconds | Generated tokens | Thinking characters | Parse/schema valid |
|---|---|---|---:|---:|---:|---|
| 3 | 2 | initial | 15.667 | 247 | 0 | True / True |
| 3 | 3 | targeted correction | 14.777 | 252 | 0 | True / True |
| 6 | 2 | initial | 7.956 | 184 | 0 | True / True |
| 6 | 3 | targeted correction | 11.572 | 189 | 0 | True / True |
| 8 | 2 | initial | 7.930 | 208 | 0 | True / True |
| 8 | 3 | targeted correction | 12.239 | 207 | 0 | True / True |
| 9 | 2 | initial | 8.299 | 437 | 0 | True / True |
| 9 | 3 | targeted correction | 12.435 | 437 | 0 | True / True |
| 12 | 2 | initial | 10.851 | 240 | 0 | True / True |
| 12 | 3 | targeted correction | 15.283 | 240 | 0 | True / True |
| 15 | 2 | initial | 8.489 | 417 | 0 | True / True |
| 15 | 3 | targeted correction | 12.888 | 383 | 0 | True / True |

Generated-token counts are provider eval_count, not an independently tokenized answer count. No thinking content was observed for controlled worker calls; token totals can still include control tokens. All start/end times, request identities, attempts, complete responses and wire schemas are in [paired-analysis.json](HIVE-THINKING-POLICY-001/evidence/paired-analysis.json) and the referenced trial artifacts.

## 10. Actionability and edit quality

6/6 cells returned an implemented response with schema-valid operations in scope. 6/6 actually passed preflight and staged edits for verification. "Executable edit" means the text operation was executable, not that the resulting Java compiled. Malformed completed worker JSON: 0; schema-invalid worker responses: 0; unauthorized-operation responses: 0.

## 11. Verification outcomes

| Cell | Verifier calls | Calls failing compilation | Calls failing behavioral tests | Frozen JUnit result | Full gate | Review |
|---|---:|---:|---:|---|---|---|
| 3 | 1 | 1 | 0 | not run: compilation failed | not run | rejected |
| 6 | 1 | 1 | 0 | not run: compilation failed | not run | rejected |
| 8 | 1 | 1 | 0 | not run: compilation failed | not run | rejected |
| 9 | 1 | 1 | 0 | not run: compilation failed | not run | approved |
| 12 | 1 | 1 | 0 | not run: compilation failed | not run | rejected |
| 15 | 2 | 0 | 2 | failed | not run | rejected |

Native aggregate labels are retained in raw results. Where they say FROZEN_ACCEPTANCE_FAILURE after compilation failed, no frozen JUnit execution or behavioral decision is implied. Exact return codes, case counts, mismatches, emitted compiler diagnostics and verifier timings are in the paired analysis. No failure was manually fixed or accepted on partial output.

## 12. Correction outcomes

Normal targeted corrections: 6. Structural corrections: 0. Cells stopped by repeated-proposal rejection: 5. No extra attempt or mode switch was added.

| Cell | Proposal comparison |
|---|---|
| 3 | calls 2→3: IDENTICAL_EDIT_PAYLOAD |
| 6 | calls 2→3: IDENTICAL_EDIT_PAYLOAD |
| 8 | calls 2→3: IDENTICAL_EDIT_PAYLOAD |
| 9 | calls 2→3: BYTE_IDENTICAL |
| 12 | calls 2→3: BYTE_IDENTICAL |
| 15 | calls 2→3: MATERIALLY_DIFFERENT |

IDENTICAL_EDIT_PAYLOAD distinguishes a changed summary/JSON representation from a changed implementation; it is not mislabeled byte-identical. Different payloads require semantic inspection before claiming meaningful repair.

The last cell was inspected: its correction removed an early negative-count check that preceded explicit null-value validation, retaining a later negative-count check. This changes possible behavior and is MATERIALLY_DIFFERENT. Both initial and revised candidates compiled and ran all three frozen cases; both failed all three with the same failure identities. The correction received all three emitted case names, exception types and messages. [Read-only semantic assessment](HIVE-THINKING-POLICY-001/evidence/correction-semantic-assessment.json).

## 13. Resources and runtime events

Exhausted logical runtime-failure cells: 0; worker generation deadlines: 0; verifier-runtime-failure cells: 0. Attempts with an HTTP/stream error: 1. The first planner attempt returned HTTP 500 with CUDA initialization/process failure; its normal retry completed. This recovered event did not become a replacement trial.

| Cell | Pre-run free host GiB | Minimum free host GiB | Minimum free virtual GiB | Minimum free GPU MiB |
|---|---:|---:|---:|---:|
| 3 | 4.768 | 0.798 | 0.507 | 1148 |
| 6 | 0.813 | 0.210 | 0.408 | 1148 |
| 8 | 2.624 | 0.335 | 0.420 | 1148 |
| 9 | 1.370 | 0.374 | 0.414 | 1148 |
| 12 | 1.584 | 0.229 | 0.461 | 1148 |
| 15 | 2.112 | 0.585 | 0.888 | 1142 |

Additional non-worker protocol observations (the thinking intervention did not apply to these roles):

| Cell | Role/call | Kind | Seconds | Terminal state | Answer characters |
|---|---|---|---:|---|---:|
| 15 | reviewer / 4 | initial | 790.722 | length | 0 |

A provider stream ending at its output cap can be complete at transport level while providing no valid review JSON. Existing evidence-preserving JSON repair remains in policy. These observations do not change worker completion or deterministic candidate outcomes.

Logical task-model calls: 25; HTTP attempts: 26; known completed-call input/output tokens: 137034/14748. Model-call seconds: 4544.658; verifier seconds: 1185.589; summed cell wall seconds: 5864.528. Failed attempts without terminal accounting have unknown usage. Resource snapshots include residency, relevant processes and Docker state; no pressure-driven configuration changes occurred.

## 14. Paired historical comparison

| Endpoint | Historical selected cohort | Prospective cohort |
|---|---:|---:|
| Complete responses for selected failed call paths | 0/6 | Fresh-cell structured response: 6/6 |
| Any completed worker response in whole cell | 1/6 | 6/6 |
| Executable edit | 1/6 | 6/6 |
| Targeted verifier invoked | 1/6 | 6/6 |
| Compiled candidate with frozen JUnit cases executed | 1/6 | 1/6 |
| Frozen acceptance | 0/6 | 0/6 |
| Full-gate software success | 0/6 | 0/6 |
| Exhausted worker runtime failure | 6/6 | 0/6 |

Six selected historical failures and six fresh, unseeded whole-cell executions do not estimate overall Hive reliability or isolate all temporal/resource/stochastic effects. Planner policy stayed fixed but freshly generated plans can differ. No formal significance claim is made.

## 15. Quality tradeoff and compilation diagnosis

Completion is not accepted software. The first five candidates have a directly demonstrated shared edit-boundary problem: inserting a member inside a record header or another method, or replacing only a method header with a whole method and leaving the original body behind. Literal replay exactly matches applied files; Java lacks the Python/JavaScript structural preflight branch. Actual prompts warn about splitting declarations and contain complete original source. Correction schemas allow different edits and do not force repetition.

Correction transport also loses useful diagnostic detail: its explicitly marked tail-only string budget drops the first compiler error in those five corrections, retaining later cascading errors. This is a measured information-selection limitation, not evidence that restoring the first error alone would produce correct code. Historical J003 controls received their sole compiler error and still failed their revised edits. No diagnostic or Java edit repair was introduced during this experiment.

The same J003 placement failure occurred in historical qwen2.5-coder cells 5 and 7, before this policy. That supports recurrence, not a claim that thinking-off has no quality cost. Historical interrupted answers cannot provide a completed-code accuracy control; the selected cohort includes only one prior compiled initial candidate. Completed but invalid code and ineffective corrections leave the competing quality hypothesis unresolved. [Read-only compilation diagnosis](HIVE-THINKING-POLICY-001/compilation-analysis.md), [exact splice replay](HIVE-THINKING-POLICY-001/evidence/compilation-causal-replay.json). No unrelated edit repair was installed.

Heterogeneity matters: prospective cell 6 avoided the source-boundary error and compiled both proposals, but its historical counterpart had two frozen failures in three cases whereas the prospective initial and revised candidates each had three. This is an observed worse case count in the only previously compiled pair, not isolated evidence of a thinking-mode causal effect. Five newly completed initial proposals failed compilation; no new accepted software was obtained. Classification is therefore limited to the completion mechanism.

## 16. Integrity audit

Final audit passed. Source hash before/after: `9bff60ebc3c8feddafe91672ceb7d3d3f7cb6f651e3e277c4fa0aa4d95953afa`. 69,553 historical files checked with no changes. Baseline, frozen tests, image/cache/attestation references, frozen order, candidate-origin baseline identity and staged identities match. All controlled worker requests actually sent false; planner/reviewer requests omitted the field. All candidates stayed scoped and unapplied. [Final audit](HIVE-THINKING-POLICY-001/evidence/final-integrity.json).

## 17. Files changed

Only the new isolated source copy changed: `app.py`, `workshop/providers.py`, new `workshop/thinking_policy.py`, new `workshop/thinking_profiles.json`, new `tests/test_thinking_policy.py`, and the targeted historical-provider assertion in `tests/test_semantic_fidelity.py`. [Exact source diff](HIVE-THINKING-POLICY-001/evidence/source-change.diff). Study-only scripts/artifacts provide reconstruction, probes, regression, freeze, copied qualified instrumentation, analysis and reporting. Prior production/evidence trees remain byte-identical.

## 18. Falsification criteria

The transport mechanism would be undermined by false requests still producing thinking-only deadline exhaustion, schema/settings drift, or unrecorded retries. Useful software improvement would be undermined by unusable completions and unchanged verified outcomes. The Java-boundary diagnosis would be undermined by replay differing from applied source or compiler failures originating elsewhere. Preserved wire streams, literal replay, deterministic results and the final audit allow those claims to be checked.

## 19. Remaining uncertainties

This is a selected six-cell diagnostic on one exact model/provider/runtime, not a reliability study. Optional thinking may still affect semantic quality. Fresh planner outputs and fluctuating resource pressure limit attribution beyond the observed channel/completion change. No claim is made that fixing declaration placement alone would satisfy tasks: source inspection also exposes possible independent type/body defects. Capability profiles must be requalified for version/digest/template changes. Semantic review remains fallible and cannot override deterministic failure.

## 20. Final classification

**THINKING_POLICY_MECHANISM_SUPPORTED**.

The observed result is 6/6 cells with completed structured worker responses, 6/6 executable edits, 0/6 frozen acceptance and 0/6 full-gate successes. The completion mechanism and engineering outcome are reported independently. Historical studies retain their original classifications; no candidate is promoted.
