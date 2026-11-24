# Hive Experiment 2: structured generation continuation

## Outcome

**No accepted candidate and no promotion.** Hive produced three distinct model-authored method patches. External Docker measurements showed repeatable held-out gains, but every patch failed the frozen all-public-cases requirement. Separately, Hive's original Coder rejected every patch with a false-positive `symbol_anchor_drift`: unchanged `_validate_task_list` context in the diff was counted as modified code. The host AST check confirms that only the allowed method body changed. These are **diagnostic improvements on this benchmark**, not a successful Hive-approved improvement or evidence of recursive self-improvement.

[Run 45282442247](https://github.com/BillyMixNix/Hive/actions/runs/45282442247) completed successfully, including cleanup and artifact preservation. A successful workflow means the experiment completed; all three candidate acceptance outcomes are failures.

## Scope and protocol

This feasibility study follows the unsuccessful [Experiment 1](../experiment1/REPORT.md). It keeps the original baseline `87e64edc9b0d4fef6d6838f2fc6dc4ccca624bfb` and permits a candidate to replace only the body of `PlannerAgent._extract_json_object` in `planner.py`. Production `planner.py` is not promoted or edited by this study.

Compared with Experiment 1, the external developer jointly changed the model to Qwen2.5-Coder 7B, compacted the model prompts, and introduced structured responses. Temperature is 0.2; generation seeds are 1729, 2718 and 31415. This is not an ablation and cannot identify which change caused an outcome.

The pinned baseline's existing `PlannerAgent.plan_task` and `CoderAgent.generate_patch` run with shared canonical repository state. A recorded transport supplies compact prompts and JSON schemas. It validates the raw plan's objective, file, symbol and extraction approach before invoking Coder. Coder returns a complete method; a deterministic serializer constructs the unified diff without repairing its algorithm. Hive's original patch checks and a Docker-only public smoke check still apply. A transport patch blocked by Hive can be evaluated diagnostically, but cannot count as an accepted Hive proposal.

The [protocol](../../../research/recursive_improvement/experiment2/protocol.json), eight public cases, 64 fresh distinct held-out cases, controller, worker and imported boundary/comparison helpers are frozen by SHA-256 before candidate generation. The model sees public examples and the selected original method, not held-out inputs or answers. All three candidates are generated before held-out evaluation. Each distinct source hash is evaluated, without selecting a winner for production. Duplicates share measurements rather than counting as independent improvements.

Three matched repetitions use shuffle seeds 11, 29 and 47 and alternate execution order. The frozen gates require at least a five percentage point held-out gain in each repetition, no loss on any baseline-correct case, all public cases, all four recorded regressions, matching baseline repository test pass/skip counts, and no more than 25% growth in median host batch latency. Exact expected error names are frozen; a subclass name does not silently count as `ValueError`. The API-fee comparison is zero versus zero; it is not a complete compute-cost comparison.

## Repairs and complete attempt history

These are parts of one adaptive feasibility study, not independent replications:

| Run | Source | Result before continuation |
| --- | --- | --- |
| [45278800840](https://github.com/BillyMixNix/Hive/actions/runs/45278800840) | `1e12af5` | Baseline preflight: 340 passed, 8 failed, 1 skipped because SymPy was missing. No inference. Added exact SymPy/mpmath dependency pins. |
| [45280078249](https://github.com/BillyMixNix/Hive/actions/runs/45280078249) | `cee8722` | Baseline: 348 passed, 1 skipped. Three on-topic, schema-conforming Planner responses were falsely rejected by the external vocabulary gate. No Coder calls. This was a harness failure. |
| [45281574396](https://github.com/BillyMixNix/Hive/actions/runs/45281574396) | `13d5e95` | Security preflight stopped: memory stress exited 137 while Docker reported `OOMKilled: false`. Cause not inferred from the exit code. No new inference. |
| [45282442247](https://github.com/BillyMixNix/Hive/actions/runs/45282442247) | `87cdd7d` | Complete: three new Coder responses, three distinct diagnostic patches, zero accepted Hive proposals. Each patch improves held-out scores but fails public correctness. |

Protocol revision **2b** repairs the over-literal plan vocabulary check to recognize scan/brace wording while retaining the objective/file/symbol and unrelated-feature checks. This repair was selected after reading Planner output, before any Coder output or candidate held-out feedback. The original three model responses and usage are frozen and replayed exactly; they are not rewritten plans. The continuation uses only the three unused Coder requests. The entire Experiment 2 budget is six real requests across both runs, not six additional requests per continuation. Historical usage is included once and explicitly marked as replayed. Original failed artifacts remain available.

The security preflight repair changes the trusted memory stress probe, not subject limits. A small parent observes the memory-hog child's SIGKILL plus a positive kernel cgroup `oom_kill` counter and the exact 256 MiB `memory.max`. Exit 137 alone still fails. The earlier ambiguous probe remains in the evidence.

## Isolation and measurement boundary

Candidate code executes only in Docker on an ephemeral Actions VM. The immutable local image ID, model identity, command-construction source and effective policy are preserved. Candidate containers have no network, credentials or Docker socket; UID 65534; read-only root, source and harness mounts; no Linux capabilities; seccomp and no-new-privileges; one CPU, 256 MiB RAM, 32 PIDs, 20 seconds, 16 MiB scratch and 256 KiB output. Host-side streams, deadlines and force-removal bound failed subjects. Repository regression runs retain those protections with 512 MiB RAM, 128 MiB scratch, a 32 MiB per-file limit and 420 seconds. The separate model service is capped at four CPUs, 10 GiB and 128 PIDs; the entire Actions job has a 45-minute limit.

The host checks the candidate AST as data and permits only the selected method body. It never imports or executes generated methods. Expected answers and scoring criteria are kept outside the subject container. Subject-reported per-case timing and CPU usage are marked untrusted; the latency gate uses host-observed whole-batch wall time, including container startup. Kernel resource evidence is collected using trusted preflight probes before candidate execution.

The same pinned lightweight image runs baseline and candidate repository tests. Torch is absent, giving one existing optional module skip that must match. A frozen compatibility adapter redirects only legacy test/benchmark `_tmp_*` fixture `Path` aliases to tmpfs; physical test/source bytes and assertions remain read-only. Relative production file reads use a scratch symlink view of immutable source. This pytest run shares an interpreter with the subject and is a regression diagnostic, not an adversarial scoring oracle. The external held-out comparison is authoritative.

## Actual measurements

Counts were identical in each of the three matched repetitions. Baseline accuracy on these **fresh** cases is 20/64 (31.25%) held-out and 4/8 public; it should not be compared as a score change against Experiment 1's different case set.

| Generation seed | Hive proposal | Held-out correct, each repeat | Gain over matched baseline | Public correct | Median host held-out batch, baseline → candidate | Ratio |
| --- | --- | --- | --- | --- | --- | --- |
| 1729 | Blocked | 45/64 (70.3125%) | +39.0625 percentage points | 7/8 | 247.209 → 244.767 ms | 0.9901 |
| 2718 | Blocked | 33/64 (51.5625%) | +20.3125 percentage points | 6/8 | 259.248 → 258.358 ms | 0.9966 |
| 31415 | Blocked | 32/64 (50%) | +18.75 percentage points | 6/8 | 253.115 → 255.475 ms | 1.0093 |

All three diagnostic patches passed the held-out gain/API-fee subgate, preserved every baseline-correct held-out case, passed all four recorded return-value regressions, and passed the identical repository suite: **348 passed, 0 failed, 1 skipped**. Their full regression runs took 172.138, 169.117 and 167.545 seconds; baseline took 167.838 seconds. All run-validity and host-latency checks passed. **The all-public-cases gate failed for every patch.** The lower-level accuracy/cost decision saying `accepted` in raw data is a subgate; `bounded_gates_passed` and `bounded_gain` are false for all candidates.

The original Coder's `symbol_anchor_drift` check rejected all three *before* its public smoke executor ran. The external controller then measured the safe transport patches as diagnostics under the predeclared protocol. This does not turn blocked patches into Hive proposals. The diff's unchanged neighboring method is visible in each retained [patch](candidate-1729.patch); external AST comparison and source hashes verify the permitted scope.

All patches fail public `pub2-b`, which requires skipping `{broken}` and returning the next valid object. Seeds 2718 and 31415 also fail `pub2-c`, containing braces and escaped quotes inside a JSON string. All three fail strict non-finite-number held-out cases. The algorithms use brace stacks without a complete string/escape-aware decoder or reliable restart after malformed prefixes. No code correction, threshold change, retry or best-of-heldout promotion was applied after viewing these results. Existing repository tests passing did not establish the new extraction contract.

| Generation accounting, entire Experiment 2 | Measured value |
| --- | --- |
| Real requests | 6: 3 historical Planner + 3 new Coder |
| Prompt tokens | 3,730 (1,803 Planner + 1,927 Coder) |
| Output tokens | 812 (283 Planner + 529 Coder) |
| Request wall time | 200.041 s (70.622 historical + 129.419 new) |
| API charges | $0, local Ollama |
| Compute/lifecycle dollar cost | Unknown |
| Complete response token telemetry | Yes, all six requests |

These totals count historical Planner usage once. Failed dependency/security preflights used zero model requests, but still consumed unpriced VM resources. Model download/build/test overhead is not included in request time. Trusted container CPU totals were unavailable (`cpu_seconds: null`); subject-reported CPU and per-case latency are not trusted cost measurements. Consequently this study does not establish full cost efficiency or a speed improvement from the small batch-latency differences.

Effective sandbox checks passed: timeout at **3,047.314 ms**, capped flood at **154.367 ms**, and the trusted memory probe at **262.988 ms**. Its child received SIGKILL, kernel `oom_kill` was 1 and `memory.max` was 268,435,456 bytes; Docker also reported `OOMKilled: true` in this final run. The parent exited 0, so the raw run status is correctly `completed`. Network/source/harness/root writes were denied, UID/capabilities/seccomp/no-new-privileges and CPU/PID/memory limits matched policy, and no credentials or Docker socket were present.

Correctness repeated across all three shuffled trials for each distinct patch; this is repeatability of one cohort on one continuation VM. There was no independent regeneration or cross-machine replication. All three source hashes differ; the study's original baseline and frozen evaluation hashes remained unchanged.

Full model digest: `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` (Q4_K_M). Subject image ID: `sha256:052ce200a4f8a73f22db2d164426535607d3dd959a0374e570c2ce2e4a63c499`. Docker 28.0.4, x86_64, kernel `7.0.0-1014-aws`, Python 3.11.18. Protocol SHA-256: `7a77ce34d7bfb5094076456f028bad951b1ec5af4d36259ccd6c2413d3ecbdd8`.

## Engineering verification

Implementation commit `87cdd7d3f96d5c1da8a43a1d67b8af5998eed888` passed [CI](https://github.com/BillyMixNix/Hive/actions/runs/45282442134): **376 tests and 7 subtests**, 194.62 seconds. The Reliability Gate also passed. The [exact CI summary](ci-87cdd7d.txt) is retained. Focused local controller/security checks passed 43 tests. Generated candidates were never executed locally.

## Interpretation and next experiment

This is progress from Experiment 1's inability to produce candidate code: the stronger structured setup produced three executable, localized algorithm changes with measured diagnostic accuracy gains. It still failed the stated full acceptance test, and the original Hive pipeline did not accept a proposal. Both the safety validator false positive and actual algorithm shortcomings must be addressed separately.

Next experiment: first repair and independently test the changed-symbol detector so unchanged diff context cannot trigger drift, while real edits to neighboring definitions remain blocked. Then freeze a new cohort with fresh held-out inputs and a bounded public-feedback repair cycle that lets Hive diagnose malformed-prefix/string/strict-JSON failures. Keep repair budget fixed, withhold all fresh held-out feedback until the full cohort is generated, and evaluate all distinct patches. An accepted helper improvement should then be tested through original end-to-end `plan_task` tasks and a second improvement cycle before making a recursive claim.

This study cannot establish recursive self-improvement, agent-wide task accuracy, a second successful improvement cycle, long-term reliability, generality or complete compute-cost efficiency. Repeated trials reuse the same 64 cases and are not 192 independent examples. Structured transport, model size and sampling changed together, and protocol revision 2b was an adaptive harness repair. Those limits must accompany any positive result.

## Reproducibility and evidence

The source is on `research/recursive-improvement`, draft [PR #39](https://github.com/BillyMixNix/Hive/pull/39). No candidate is automatically promoted. Main is neither modified nor merged. The workflow requires the deliberate commit subject `experiment2: run frozen cohort` to spend inference budget; this evidence commit does not use it. A deliberate rerun would constitute another run requiring separate accounting.

The [completed cohort ZIP](cohort-45282442247.zip) retains frozen source, original/actual prompts, raw model responses, exact patches, model usage, sandbox probes and evaluation telemetry. [measurements.json](measurements.json) is a readable derived summary; it does not replace the raw artifact. [attempts.json](attempts.json) records their SHA-256 digests and run history. The failed dependency, false vocabulary gate and ambiguous memory probe artifacts are preserved alongside the final continuation. Successful workflow completion is separate from a candidate satisfying the research gates.


| Preserved artifact | SHA-256 |
| --- | --- |
| [Dependency preflight](preflight-45278800840.zip) | `58828c1c9db9628444b6f9840fac85a87e06f49040c0fc72505d8e7e1697a101` |
| [Original Planner gate failure](goal-gate-failure-45280078249.zip) | `af71dafb06d9aea24c957272a5310003e26301c46cb1ac2e3c3fcb28de91494e` |
| [Ambiguous memory preflight](security-preflight-45281574396.zip) | `b6af8ebeca63f6a6db9e7a98651689c13c8582bc2e62b51538b613fe5b96b4d2` |
| [Completed continuation](cohort-45282442247.zip) | `cedb1d287b242f33590e1ab329e261f85c1efae18fa2cfc162150de808a9e113` |

The three exact model-generated patches are retained as inert review artifacts: [1729](candidate-1729.patch), [2718](candidate-2718.patch), [31415](candidate-31415.patch). None is applied to production. Main remains `b2d3df6fdbc2b3d395d74a0c25d3c777382cd170`.
