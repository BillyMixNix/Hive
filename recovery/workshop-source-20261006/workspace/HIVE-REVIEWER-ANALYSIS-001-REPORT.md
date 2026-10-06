# Hive model reviewer: responsibilities, incremental value and availability

Analysis completed against the final TRANSITION-005 source preserved in `HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop`. **No production code, promotion policy, historical result or candidate was changed. No model or real verifier was invoked.**

**Conclusion:** the reviewer combines a potentially useful semantic assessment with checks the controller already enforces. The available history contains **no demonstrated reviewer-only veto of an otherwise eligible candidate**. It does contain additional semantic observations on already-failing candidates, incorrect reviewer claims, and approvals overridden by deterministic checks. Reviewer unavailability is not evidence of a software defect. It should be recorded separately from verification and should not, by itself, prevent a fully verified candidate from being presented for explicit human review/approval. It must not be translated into model approval or automatic promotion.

This is a recommendation, not a policy change. Current Hive still requires reviewer approval. Current external-root diagnostic runs are additionally **non-promotable regardless of reviewer approval**.

**Evidence and coverage**

The read-only inventory searched the current transition workspace and the preserved September 13 Workshop and September 22 local-model-trial work areas. It found 692 `run.json`/`result.json` paths, including 330 Hive-shaped run files representing 211 distinct IDs. Copies were deduplicated by ID; meaningful review-field conflicts occurred only in a reused test-fixture ID. Separate result records with non-null reviews all matched indexed run records. The scan reported access-denied pytest directories and two malformed test-fixture JSON files; these limitations are retained in the inventory. Unexpanded archives, deleted runs and locations outside these roots are not covered.

| Indexed category | Unique IDs |
|---|---:|
| Completed review with provider-call telemetry | 33 |
| Legacy raw review without provider-call telemetry | 15 |
| Reviewer attempted, no model decision | 1 |
| No review observed | 40 |
| Single-agent host approval stand-in | 32 |
| Test fixtures | 80 |
| Explicit controlled reviewer fixtures | 5 |
| Deterministic probes/replays | 5 |

The 48 completed review records are not 48 independent, identically configured experiments. Fifteen legacy records lack call-level provenance. They are reported separately, not elevated to the evidentiary strength of the 33 instrumented calls. Fixtures, single-agent approval stubs and this analysis's synthetic probes are excluded from empirical reviewer-benefit counts.

Evidence: [inventory](HIVE-REVIEWER-ANALYSIS-001/evidence/inventory.json), [classified audit](HIVE-REVIEWER-ANALYSIS-001/evidence/history-audit.json), [all completed reviews with original artifact links](HIVE-REVIEWER-ANALYSIS-001/historical-review-ledger.md), [separate result cross-check](HIVE-REVIEWER-ANALYSIS-001/evidence/result-crosscheck.json).

**Every explicit reviewer responsibility**

The complete substantive instruction is: “Approve only if the diff matches the request, stays narrowly scoped, and deterministic verification passed.” The reviewer is read-only and must return `approve`, `summary`, `issues`, and `confidence`.

| Responsibility | Actual information/authority | What it does not establish |
|---|---|---|
| Judge whether the diff matches the user request | Original request and a bounded unified diff | Complete correctness, exhaustive behavioral preservation or coverage of every requirement |
| Judge narrow scope | Request and diff; may notice unrelated behavior inside an allowed file | Exact authorization is enforced by host scope/ownership checks, not this opinion |
| Require passing deterministic verification | Serialized verifier result, subject to prompt clipping | Reviewer does not execute, reproduce or authenticate the checks |
| Explain the conclusion and list issues | Free-text strings | No enforced evidence citation, severity, counterexample or issue-to-requirement mapping |
| Express confidence | Number requested in [0,1] | No confidence threshold, calibration or decision rule consumes it |
| Return the required review JSON | Local generation schema; one bounded JSON-format repair after parsing failure | Host parsing does not validate the review against that schema |
| Stay read-only | No reviewer edit dispatch or worker observation loop | It cannot repair code, change scope, alter tests or grant human approval |

“Review security,” “prove test adequacy,” “audit frozen-test integrity,” “verify cache attestation” and “authorize promotion” are **not separately assigned reviewer duties**. Safety or regression concerns can fall under request compliance, especially when requested, but there is no dedicated exhaustive security or semantic audit contract. The model's actual veto authority is broader than the stated duties: any false approval can block, without a validated reason.

The reviewer receives neither an independent full-source bundle nor the normalized plan/ownership map, host write allowlist, worker risks or observation history as dedicated fields. Some may happen to appear in the request or diff. The current local call is a prompt-only review, not a repository-inspection agent. The persistent-agent backend maintains a per-role session but supplies no execution environment; this does not create a reviewer file-inspection protocol.

Sources: [review prompt](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L1852), [generation schema](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive_protocol.py#L126), [JSON parser/repair](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L799), [provider routing](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/app.py#L674), [persistent backend](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/persistent_agent.py#L115).

**All decision and rejection paths**

After workers and final verification, `_run_build_impl` invokes the reviewer even if verification failed, earlier errors exist or no edits survived. External runs skip the full gate when prerequisites fail, but still invoke the reviewer. Runs terminating earlier during planning never reach this branch; those are not reviewer rejections.

| Condition at the review boundary | Current effect |
|---|---|
| Model returns `approve: false` | `rejected`, even with all checks passing and no issues stated |
| Missing `approve`, or a falsey value such as null/zero/empty string | `rejected`; no required-field/type validation |
| Provider raises: allocation, HTTP, generation deadline, unavailable model, configured routing/budget denial, etc. | Synthetic false review, reviewer error added, `rejected`; no semantic judgment occurred |
| Initial review is not parseable JSON | One same-role JSON repair through normal routing |
| JSON repair also fails, or its provider call fails | Synthetic false review, error recorded, `rejected` |
| Parseable JSON has an unusable shape, e.g. scalar `true` | Later dictionary operation raises; outer handler marks run `failed` |
| Verification did not pass | Host forces `approve` false, regardless of model approval |
| Any accumulated run errors | Host forces false, regardless of model approval |
| No changed files | Host forces false, regardless of model approval |
| Truthy approval with successful verification, no errors and changed files | `ready`; issues and confidence do not independently veto |

The last rule uses Python truthiness, not `approve is True`. Consequently, a parseable wrong-type approval such as the string `"false"` reaches `ready` in the deterministic probe. Conversely, a valid `approve: false` with an empty issue list rejects. A true approval with a “Major issue” and confidence zero also reaches `ready`. These are controller protocol observations, not evidence that the current Ollama schema normally generates those malformed values. The Ollama path supplies a strict generation schema, but that is not a host validation substitute; the classic cloud path does not supply the same schema parameter.

There is no worker implementation-repair loop after reviewer veto. The one reviewer repair is JSON formatting repair, not a semantic appeal or candidate revision. The final stored `review` and `agents.reviewer.parsed` include host mutations; they must not be mistaken for the raw model judgment. This audit uses raw output, or `repair_raw` when a repair supplied the decision.

Promotion has independent gates: `/api/hive/apply` requires explicit human approval; `_apply_run_locked` forbids candidate-only external runs, requires `ready`, passing verification and truthy reviewer approval, rejects already-applied/stale/tampered runs, validates source/stage manifests, snapshots before mutation, verifies after apply and rolls back on failure. A model approval cannot waive these conditions. Reviewer absence is currently a blocking condition even if a human wants to apply an ordinary Workshop run.

Sources: [review and host overrides](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L2643), [apply guards and rollback](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L2824), [explicit human approval](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/app.py#L1046).

**Reviewer input adequacy**

The prompt builder silently slices the diff at 70,000 **characters** and verifier JSON at 20,000 **characters**. These are not token limits. It does not preserve a structured complete check summary before inserting logs or label the omitted content. The reviewer JSON-repair prompt supplies the schema, parser error and up to 16,000 characters of previous output, but does **not** resend the original request, diff or verification. A stateless repair call therefore lacks the primary review evidence independently of the previous malformed response.

For replacement run `4574db69cea0`, the preserved outbound request exactly matches the current constructor: all 454 request characters and all 828 diff characters were included. The verification object was **54,352 characters**, of which only **20,000** were sent. The prefix contains the frozen and full-gate passing flags, but ends inside a log string and omits the `source_immutability` check entirely. It is not valid complete JSON. This is caller-side clipping despite `truncate=false`; it is not proof of provider-side truncation or the cause of allocation failure. No model-visible consumption is established because the provider failed to allocate.

This limits claims that the current reviewer is a complete, independent integrity auditor. It does not undo the actual host verification or justify interpreting absence as approval. Measurement and synthetic tail-sentinel results are in [reviewer-input.json](HIVE-REVIEWER-ANALYSIS-001/evidence/reviewer-input.json).

**What the historical reviewer actually caught**

An **additional diagnostic observation** means a supported defect not identified by the recorded deterministic diagnostic. An **incremental veto** means the reviewer blocked a candidate that had no independent deterministic blocker. These are different measurements.

| Completed review outcome | Count | Interpretation |
|---|---:|---|
| Model veto, verifier already failed | 36 | 28 instrumented, 8 legacy; rejection was already required |
| Model veto, verifier passed but prior errors and no applied edits | 5 | All legacy; passing baseline tests did not make these eligible candidates |
| Model approval, no independent blocker | 4 | All instrumented Astra reviews; no unique defect reported |
| Model approval despite independent blockers | 3 | Controller correctly refused approval |
| **Reviewer-only veto of an otherwise eligible candidate** | **0** | None demonstrated in this corpus |

The four eligible approvals were `7c6c5048fe4f`, `ff68bfb9a92b`, `f8c99fa2fb5f` in HIVE-ASTRA-001 and `c391de6f3eaf` in the persistent-agent evaluation. Their actual reviewer call metadata names `gpt-6-astra`; the run's top-level local-model setting is not sufficient to identify the reviewer. The instrumented local-review records are overwhelmingly reviews of already-ineligible proposals. There is **no successful local review of an otherwise eligible candidate in this retrieved set**, so these observations cannot estimate local review sensitivity on good candidates.

The following cases account for the substantive legacy findings and important counterexamples; the full ledger contains every completed review:

| Run | Reviewer finding | Independent evidence and judgment |
|---|---|---|
| `2860452e9caf` | Test uses the wrong endpoint and wrong required keys | Test calls `/api/endpoint` and expects `key1`…`key5`; request explicitly names `/api/context/preview` and five different keys. Pytest stopped at 404 before checking keys. **Wrong-key observation is supported additional diagnostic value**, but candidate already failed. The reviewer also incorrectly says the implemented endpoint path is wrong: the app diff actually adds `/api/context/preview`. |
| `0d713899908d` | New endpoint/frontend tests are not implemented | Added test bodies contain only comments and `pass`. The recorded verifier failed earlier at app import (`FastAPI.route` AttributeError), not test adequacy. **Supported additional diagnostic value**, not an incremental veto. |
| `68634751129b` | Missing backend; incomplete UI integration | Backend parse failure already explains the missing backend, and pytest fails importing nonexistent `main`. The UI diff nests `refreshProjectSummary` inside `refreshStatus` while an inline button calls it globally; JavaScript parsing passed. Thus a separate integration defect is observable. The reviewer only said “UI integration logic is incomplete,” without identifying that mechanism. **Qualified semantic observation; no precise model diagnosis established.** It also inaccurately describes the changed files as HTML/JavaScript when the other changed file is a Python test. |
| `6cf6a981c0f6` | Missing endpoint and undefined test `client` | Backend edit had already failed its exact-anchor requirement; pytest reports the same NameError. Redundant rejection, not an incremental catch. |
| `96e5cd28a4df` | Missing endpoint, 404 | Same endpoint failure already in pytest. |
| `9adaba0967ce`, `10aa42800bb5` | Indentation errors | Python compilation/pytest already reports them. |
| `801b972128ee` | Out-of-scope test change; missing endpoint; indentation | The only changed file is `tests/test_worker_failure_reporting.py`, inside the expressly allowed tests scope. Scope complaint is incorrect. Backend call failure and compilation failure already block. Edit operation choice is not reliably recoverable from a final diff alone. |
| `813b8f112c63`, `9028a64c5adb`, `f52a2afdea53`, `195211d71768`, `9292cd525989` | Requested Project Summary work absent despite passing verification | All have zero changed files and prior agent/planner errors. Host policy already rejects; no useful implementation existed to approve. |
| `a12214d93ad3`, `5d6eee8ea24e` | Model approves the proposal | Empty proposals with earlier errors; host overrides approval. These approvals are unsupported by the available implementation evidence. |
| `e66097b0d1c2` | JSON-repair review approves “all requirements” | Original reviewer response was empty; formatting repair approved. Edits had failed exact-anchor preflight, no diff existed, full gate was skipped. Host overrides. The repair's incomplete review context prevents attributing this solely to model reasoning. |

All 28 instrumented vetoes repeat already-failed verification, missing edits or failed prerequisites. For example, Astra correctly describes NFRT native-thread failures and missing methods already reported by compilation; Qwen reports absent diffs after worker preflight/rollback. TRANSITION-003's reviewer did not independently discover its candidate's Unicode defects: the edit was already rolled back after timeout, and the reviewer saw no diff. Its later frozen behavioral failures came from verifier replay, not model review.

HIVE-EVAL-009 supplies no evidence of an additional current-style model reviewer catch. Its saved orchestration result records deterministic child acceptance, a final `Gradle test` gate, frozen-test integrity and manual promotion; no separate model review result is recorded. The accessible orchestrator chooses `ready_for_promotion` from final acceptance. This is a different architecture and gate, not proof that today's semantic review has no value. See [preserved EVAL-009 contrast and provenance](hive-transition-003/eval009-contrast.md).

**The fully verified candidate blocked by reviewer unavailability**

Replacement run `4574db69cea0` produced a scoped candidate, passed frozen J001 **3/3**, then passed the actual full Gradle gate: **154 JUnit cases, 26 game tests and 3 quest tests**. Targeted and full reports also record passing source immutability. The full task list was `clean build runGameTestServer runQuestTestServer packTestJar`.

Reviewer inference then failed both existing provider attempts: HTTP 500 with CUDA initialization/process failure, followed by HTTP 500 with failure to allocate a 5,843,582,976-byte CUDA_Host buffer. The review call took about 65.8 seconds and produced **no review decision**. The controller synthesized `approve: false`, added an error and rejected the run. This is a demonstrated availability dependency after passing gates, not a semantic rejection. Historical classification remains `LOCAL_RUNTIME_FAILURE`; no result is rescored and nothing is promoted.

Evidence: [unchanged replacement report](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1-REPORT.md), [verification summary](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/verification-summary.json), [runtime summary](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/model-runtime-summary.json), [original run](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/runs/4574db69cea0/run.json).

**Deterministic versus genuinely semantic responsibilities**

| Judgment | Deterministic replacement or existing protection | Semantic remainder |
|---|---|---|
| Did required verification pass? | Already host-owned: exit/timeout status, frozen class/case counts, failures/errors/skips, required task configuration and fresh reports | None in deciding whether those specified checks passed; passing tests is not universal correctness |
| Were only authorized files/operations used? | Exact role/file scope, exclusive ownership, safe paths, operation schema, anchor/structure preflight | Whether an authorized-file change is relevant or unnecessarily broad |
| Were sources/tests/build inputs altered improperly? | Frozen source hashes, baseline/profile identity, source immutability, attested dependencies, manifests/stale-base checks | Whether the authorized new code is behaviorally correct; integrity proves identity, not intent |
| Did a real eligible proposal exist? | Changed-file list, prior-error state, preflight/staging result; already enforced | Whether a nonempty edit meaningfully fulfills the request |
| Is the review itself well formed and usable? | Strict host JSON-schema/type validation, explicit unavailable/invalid/approved/rejected states, complete input accounting can be deterministic | Whether an issue is true; a schema cannot authenticate free-text reasoning |
| Does an exact endpoint/API/response shape exist? | AST/interface checks or contract tests when supplied with a host-authoritative structured contract | Extracting complete meaning from arbitrary prose; state-dependent behavior not described by the shape |
| Are requested tests merely empty placeholders? | Deterministically flag trivial `pass`/empty bodies under an explicit policy | Test adequacy, weak assertions, missing scenarios and false reassurance; “no assert” alone is not universally invalid because helpers can assert or failures can be exception-based |
| Are ordinary behavior, invariants and cross-component semantics preserved? | Concrete properties, regression cases and contract checks can cover specified parts | Unspecified boundaries, interactions and counterexamples not captured by existing checks |
| Is the implementation narrowly necessary, compatible and free of subtle regressions? | Some rules can be formalized as protected symbols/interfaces, dependency constraints or explicit policy | Relevance, tradeoffs, accidental behavior changes, security/performance implications beyond existing specification |
| May this exact artifact be promoted? | Explicit human authorization, verified artifact identity, ready-state/policy checks, snapshots, post-apply verification and rollback | Human acceptance of residual semantic risk; not model availability or a confidence number |

Current `hive._validate_worker_task_focus` explicitly calls itself a conservative protocol guard, not a semantic code validator. Planner intent/interface checks formalize selected obligations; they do not prove arbitrary natural-language compliance. Frozen acceptance can replace reviewer judgment for the properties it actually checks, but not for all possible interpretations of the task. Source integrity cannot detect incorrect authorized code. A passing full build cannot establish that every requested feature was implemented.

The supported extra historical findings are good candidates for concrete contract checks and placeholder-test detection once their predicates are explicitly specified. That does not justify a broad keyword-based “semantic validator.” A model or human may discover a new counterexample; the reproducible regression/property check for that counterexample can then become deterministic evidence.

Relevant code: [scope/ownership/plan validation](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L387), [edit preflight](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L1320), [task-focus limitations](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L1039), [source guard](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/workshop/hive.py#L1262), [frozen JVM gate and report checks](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop/verification/jvm_runner.py#L563).

**Deterministic confirmation of controller behavior**

Thirteen synthetic probes called the real unchanged `hive.run_build`, using private scratch sources, scripted model replies and mocked verifier outcomes. No real inference, Docker, Gradle or apply operation ran. They establish control flow, not candidate correctness or empirical reviewer quality.

| Probe | Observed status |
|---|---|
| Valid approval, valid staged edit, passing verifier fixture | ready |
| Semantic veto / unsupported veto with no issues | rejected / rejected |
| Approval with a major issue and confidence zero | ready |
| Wrong-type `approve: "false"` | ready |
| Missing approval / scalar JSON | rejected / failed |
| Invalid JSON then valid repair / invalid twice | ready / rejected |
| Provider unavailable | rejected |
| Approval with failed verification / no edit / worker error | rejected / rejected / rejected |

Artifacts: [probe results](HIVE-REVIEWER-ANALYSIS-001/evidence/controller-probes.json), [reproducible analysis script](HIVE-REVIEWER-ANALYSIS-001/analyze.py). Scripts preserve existing probe directories rather than overwrite them. The real repository suite was not rerun: no production change was made, and these focused probes answer the policy questions without additional infrastructure/model work.

**Availability recommendation and its limits**

Reviewer unavailability should **not erase or invalidate a completed deterministic verification result, label the implementation incorrect, or prevent preservation/presentation of the exact verified candidate for human review**. The replacement run demonstrates why: an unrelated allocation failure currently converts an otherwise verified result into rejection.

For a future authorized policy change, keep three independent facts: the deterministic result, the review disposition (`approved`, `rejected`, `unavailable` or `invalid`), and promotion authorization. Never map unavailable to approved. Preserve all deterministic gates and reject candidates with real gate failures. An evidence-backed semantic concern should remain visible and require resolution or an explicit authorized human decision; it should not disappear merely because tests pass.

For ordinary manually approved Workshop changes, I recommend allowing explicit human semantic review to substitute when model review is unavailable. Model availability alone should not be an indispensable prerequisite to that human decision. For unattended promotion, or a task explicitly requiring independent review, passing tests alone is insufficient: an unavailable required review still leaves an unmet obligation. This analysis does not authorize unattended promotion, a new bypass or use of an external diagnostic candidate in production.

Before any later policy implementation, the deterministic review-schema weakness, clipped input and evidence-free formatting-repair behavior should be treated as separate interface findings. None was repaired here. Any later implementation needs explicit tests showing that true verification failures, stale/tampered artifacts, unauthorized writes and unresolved required approvals remain blocked, and that `unavailable` never masquerades as `approve: true`.

**Uncertainties and falsification**

There were only four otherwise eligible completed reviews, all Astra; the local reviewer comparison is dominated by already-failed candidates. Zero incremental vetoes therefore does not establish reviewer redundancy for all software or models. The reviewer may find untested semantic defects in future cases. The legacy additional observations demonstrate that useful analysis is possible but not that a mandatory model veto improves acceptance quality.

The “no demonstrated incremental veto” finding would be falsified by a preserved run with passing required verification, valid scope/integrity, an actual eligible edit, and a supported reviewer-discovered defect that the independent gates did not already block. The value of a mandatory reviewer would need measurement on such eligible candidates, with issue correctness adjudicated, false vetoes and availability failures counted, and provider/source versions separated. Conversely, new deterministic properties covering a supported semantic finding reduce that finding's future incremental value.

All 153 files of the analyzed source and all 653 indexed historical run/result files carrying hashes were rechecked after analysis; none changed. The artifacts and scripts under `HIVE-REVIEWER-ANALYSIS-001/`, plus this report, are the only new work. See [integrity audit](HIVE-REVIEWER-ANALYSIS-001/evidence/integrity.json). Historical classifications, frozen tests, approved cache attestations, promotion restrictions and the fully verified but reviewer-unavailable replacement result remain unchanged.
