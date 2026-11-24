# Hive Experiment 3: bounded public-feedback repair

## Outcome

**No accepted candidate and no promotion.** All three seeds completed an initial attempt and one feedback repair. Seeds 4242 and 5656 returned byte-identical code on repair. Seed 7878 changed its method and improved from **8/14 to 9/14 public cases** and **48/96 to 64/96 held-out cases**. It still failed the frozen all-public-cases requirement. Every held-out extraction score repeated across all three matched trials.

The validator false positive was resolved: all six attempts reached Docker public smoke evaluation. Hive correctly rejected them with `sandbox_semantic_failed`. The raw fallback `reason` misleadingly says “Hard anchor enforcement blocked patch”; its failure code, `llm_error` and public execution trace identify semantic failure, not another neighboring-symbol rejection.

A separate harness failure invalidated the original Planner replay measurements: every call returned `OSError` during initialization before the extraction helper ran. The raw zero scores are preserved and are not interpreted as functional accuracy. A separately recorded evaluation-only diagnostic replays the exact code and inputs after repairing scratch working-directory handling, with zero extra inference. Its results are reported separately below. The original no-accepted-candidate outcome is already established by the public failures and does not depend on that broken replay gate.

## Human repair and baseline

Experiment 2 exposed a false positive in Hive's patch validator: unchanged neighboring function definitions in diff context were counted as modifications. The external developer repaired `extract_changed_def_names` to count actual added/removed definitions. For real numeric unified diffs, both Coder validation paths now provide trusted full source; the validator applies the diff as data and compares parsed trees outside the selected definition. This detects neighboring body changes even when no definition line appears in the hunk.

Tests independently cover unchanged neighboring context, body-only target hunks, neighboring body edits, import/module/class/decorator changes, and all three archived Experiment 2 patches without executing them. The existing shorthand-diff behavior and complexity helper exception are retained; this is not a claim of complete validation for every patch format. Experiment candidates use numeric unified diffs and an additional immutable method-body-only AST restriction.

The repaired baseline is **`bbc0b2dcc216b51d4c13232754926f23ea45fd31`**. Local full suite: **379 passed, 1 skipped** (152.09 s). [Baseline GitHub CI](https://github.com/BillyMixNix/Hive/actions/runs/45333440384): **386 passed, 7 subtests passed** (172.87 s), with Reliability Gate success. [CI summary](ci-bbc0b2d.txt) is retained. This human-written validator improvement is part of the baseline and is not credited as Hive self-improvement. Production `planner.py` remains unchanged before and after the study.

## Frozen study

Controller source: `b2b8d01c4aeb622d2c6ed3a7d8758cbe97f76474`. [Run 45334226981](https://github.com/BillyMixNix/Hive/actions/runs/45334226981) uses 214 frozen source/criteria hashes, including the pinned baseline Python sources, new protocol, cases, worker, transport and imported comparison/boundary helpers. [Protocol and implementation](../../../research/recursive_improvement/experiment3/README.md) describe the complete setup. Focused controller/boundary checks passed **67 tests** locally before launch. [Implementation CI](https://github.com/BillyMixNix/Hive/actions/runs/45334226798) passed **392 tests and 7 subtests**; Reliability Gate passed. The [exact summary](ci-b2b8d01.txt) is preserved.

Three fresh seeds (4242, 5656, 7878) use the original Planner once and original Coder `generate_patch_with_revisions` with at most one revision. Maximum total real request attempts is nine. Initial requests use each seed; repair requests use seed + 100000. Qwen2.5-Coder 7B must match full digest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`, temperature 0.2. Compact schema transport records original and actual prompts and does not repair candidate algorithms. The original local initial-pass reflector is used; it makes no inference call.

The model receives **14 public examples** and only public Docker outcomes/previous source for its optional repair. When Hive retries before public execution, its contract-error context is supplied instead. No external retry forces Hive to use its budget. Only original-LLM Planner/Coder proposals count; blocked transport patches can be measured diagnostically. Hive chooses its final patch using public feedback before held-out evaluation. Every admissible initial and repair source is retained and evaluated; identical source hashes share results. No best-of-heldout selection or automatic promotion exists.

There are **96 fresh distinct held-out extraction inputs** and **eight fresh held-out Planner response-replay tasks**, with no input-text overlap with Experiments 1/2. Expectations are specified by construction independently of any candidate/reference extraction algorithm. All generation finishes before any held-out extraction or planning results exist. Cases include related families, and repeated trials use the same cases; this is not a claim of independent general software tasks.

Matched evaluations use shuffle seeds 11, 29 and 47 with alternating order. Frozen gates require at least five percentage points of held-out gain in each repetition; all public examples; no baseline-correct extraction loss; all recorded regressions; matching full baseline repository pass/skip counts; and no more than 25% growth in median host held-out batch wall time. Eight response-replay tests call original `Planner.plan_task` without inference and require original-LLM source, expected goal and one correctly anchored repair task, with all eight correct and no baseline-correct loss. Host scoring owns all expected answers, case membership and decisions. These replays test an actual Planner path, not fresh model reasoning or another coding task.

## Actual extraction and repair measurements

These are fresh cases, so their percentages cannot be compared directly with Experiment 2's different case set. Baseline is **32/96 held-out and 6/14 public** in every matched trial.

| Generation seed | Initial public → repair | Initial held-out → repair, each repeat | Repair changed source? | Hive final proposal |
| --- | --- | --- | --- | --- |
| 4242 | 8/14 → 8/14 | 48/96 → 48/96 | No, identical bytes | Blocked |
| 5656 | 8/14 → 8/14 | 48/96 → 48/96 | No, identical bytes | Blocked |
| 7878 | 8/14 → 9/14 | 48/96 → 64/96 | Yes | Blocked |

Six transport attempts yielded **three distinct source hashes**, not six independent improvements. Seed 7878's initial source is identical to seed 5656's. All attempts are retained in [candidates.json](candidates.json) and as exact inert patch files. The two initial source variants use essentially the same brace-balancing strategy; the successful partial repair adds JSON syntax validation. Static review found ordinary extraction code, without test introspection or grading manipulation. No human algorithm correction was applied.

| Source hash prefix | Public | Held-out, each repeat | Matched median host batch, baseline → patch | Ratio |
| --- | --- | --- | --- | --- |
| `ef9ffd9c` | 8/14 | 48/96 (50%) | 242.799 → 237.582 ms | 0.9785 |
| `1dd202f1` | 8/14 | 48/96 (50%) | 244.249 → 241.641 ms | 0.9893 |
| `6b52cc0f` | 9/14 | 64/96 (66.6667%) | 250.614 → 252.103 ms | 1.0059 |

All three distinct sources pass the held-out gain/API-fee subgate, preserve all baseline-correct held-out cases, pass all four recorded return-value regressions, match the complete baseline repository suite (**379 passed, 0 failed, 1 skipped**) and meet the host-latency gate. All fail the all-public-cases gate. No final patch is selected by Hive, and every `bounded_gain` is false. An `accepted` lower-level accuracy/cost subgate in raw data is not the full acceptance decision.

Full repository wall times were baseline **170.234 s**; sources `ef9ffd9c` **167.753 s**, `1dd202f1` **168.521 s**, and `6b52cc0f` **170.268 s**. The suite runs once per distinct source, whereas extraction scores and latency are measured in three matched repetitions. These tests miss the new contract failures and are not sufficient evidence of extraction correctness.

The partial repair handles additional quoted-brace cases by checking JSON syntax before returning. It still does not reliably restart after a malformed/unclosed prefix or reject non-finite JSON numbers. It fails five public cases, including malformed-prefix recovery and NaN/Infinity handling. No thresholds, expected answers, candidate code or public requirements were changed after observing these results.

| Entire generation cohort | Measured value |
| --- | --- |
| Real requests | 9: 3 Planner + 6 Coder |
| Prompt tokens | 9,409: 2,571 Planner + 6,838 Coder |
| Output tokens | 1,168: 281 Planner + 887 Coder |
| Request wall time | 317.920 s: 77.473 Planner + 240.448 Coder |
| Complete response token telemetry | Yes, all nine requests |
| API charges | $0, local Ollama |
| Compute/lifecycle dollar cost | Unknown |

The repeated unchanged repairs still consumed requests, tokens and time. There were no cancelled or extra generation requests in this experiment. Builds, model download, CI, evaluations and the later zero-inference diagnostic consume additional unpriced compute and are not included in model request wall time. Trusted container CPU totals are null; worker-reported timings are untrusted. Zero API fees do not establish zero lifecycle cost or cost efficiency.

## Planner replay diagnostic and compatibility follow-up

The original worker used `/subject` as its working directory. `PlannerAgent` creates `LessonMemory`, which attempts to create `hive_lessons.jsonl` there. Every original replay output was `OSError`; a structurally valid JSON response envelope did not establish a valid functional measurement. This was an external harness mistake. The original raw 0/8 rows remain in the artifact rather than being overwritten.

The follow-up uses a tmpfs working directory with symlinks to immutable subject source and a separate scratch lesson file. Source, tests, expected goals, original scoring function, eight inputs, all six patch bytes, three source hashes, baseline and sandbox limits are unchanged. It first reproduces the read-only initialization error and then requires a clean baseline positive control. It has no model service and makes **zero inference requests**. Because this instrumentation repair was selected after inspecting held-out output, it is a diagnostic follow-up, not an unchanged replication or another generation trial. No follow-up result can turn a public-failing blocked candidate into an accepted proposal.

[Diagnostic run 45337482248](https://github.com/BillyMixNix/Hive/actions/runs/45337482248) completed successfully with **zero inference requests**. The trusted baseline probe confirmed `[Errno 30] Read-only file system: hive_lessons.jsonl`. With scratch storage fixed, the clean baseline positive control passed and every batch had a valid response envelope.

| Version | Correct Planner replays, each of three repetitions |
| --- | --- |
| Baseline | 3/8 |
| Initial source variants `ef9ffd9c`, `1dd202f1` | 5/8 |
| Repaired source `6b52cc0f` | 6/8 |

No baseline-correct replay regressed. All three sources still fail the frozen all-eight requirement. The repaired version continues to fail malformed/unclosed prefixes. This is evidence that its partial helper improvement helps a real original Planner path on these fixed response messages. It is not evidence of better fresh model reasoning, improved coding-task success, another accepted proposal or a second self-improvement cycle.

The [exact diagnostic artifact](replay-45337482248.zip) and [derived measurements](replay-measurements.json) are preserved. Artifact SHA-256: `d6830cbc3f84dbd353fa573af101b35d24d7357f2e1ae86f0b4487f1dd8e740d`. The 21 diagnostic input/boundary hashes remained unchanged, as did all candidate source hashes. The original raw artifact and its invalid planning rows remain available alongside this supplemental measurement.

Commit `edfac8c9d79a3537e53e454e7aeed79114481f5e` also corrects a compatibility edge in the externally written checker: a target body edit need not include a changed `def` line, so the existing one-helper complexity exception must not require one. Normal bug-fix tasks retain the full source-tree scope check, and two helpers are still rejected. The focused checks passed **38 tests**; the complete local suite passed **387 tests, 1 skipped** in 157.75 s. [Follow-up GitHub CI](https://github.com/BillyMixNix/Hive/actions/runs/45337482154) passed **394 tests and 7 subtests**; Reliability Gate passed. The [exact CI summary](ci-edfac8c.txt) is preserved. This follow-up is outside the pinned Experiment 3 baseline and has no effect on its ordinary bug-fix candidate measurements. It is another human engineering fix, not a Hive improvement.

## Isolation, resource and cost limits

Generated code is never imported or executed by the host. Parsing, strict diff application and AST comparison treat it as data. All candidate public smoke, extraction, planning and regression execution uses the immutable local Docker image. Subject containers are nonroot, have no network/credentials/socket/capabilities, read-only root/source/harness, seccomp/no-new-privileges, one CPU, 256 MiB, 32 PIDs, 20 seconds, 16 MiB scratch and 256 KiB output. Full repository runs use 512 MiB, 128 MiB scratch, 32 MiB per-file limit and 420 seconds. Effective-policy, timeout, flood and kernel OOM probes precede inference.

The separate model service has four CPUs, 10 GiB and 128 PIDs. A 55-minute controller deadline leaves cleanup/artifact time within the 60-minute job. Cleanup failures stop evaluation. Started request records are persisted before HTTP so interrupted usage remains unknown rather than zero. API fees are zero for both versions; tokens, request time and evaluation wall time are separate. Compute/lifecycle dollar cost and trusted container CPU totals remain unknown, and subject-reported timing is untrusted. Batch latency includes container overhead and does not establish a microbenchmark speed improvement.

The frozen compatibility adapter redirects only legacy test/benchmark scratch `Path` aliases to tmpfs. Physical tests/assertions/source stay read-only. Torch is absent, and its optional skip must match. Same-interpreter pytest is diagnostic, not an adversarial oracle. Container isolation shares the VM kernel; its controls are defense in depth, not a VM-escape guarantee.

## Interpretation and next experiment

The bounded feedback loop produced one measurable partial repair and two unchanged retries. It did not produce an accepted improvement. The checker now permits legitimate local diffs and the sandbox correctly rejects candidates that fail the declared behavior. The negative result points to weak algorithmic repair and ineffective use of feedback, rather than the prior false anchor rejection.

Next experiment: require a short diagnosis of the concrete public failure mechanism before Coder repairs it, test whether the plan changes after feedback, and explicitly record unchanged retries. Retire the now-published held-out inputs, freeze fresh cases including malformed-prefix, string/escape and strict-number combinations, and keep the model/request budget fixed. A positive helper result should subsequently be tested on fresh model-driven planning/coding tasks and a second improvement cycle.

Even a passing candidate would establish at most a bounded helper improvement under externally supplied objectives, scaffolding and public feedback. Model/prompt/validator/feedback changes are joint conditions, not a causal ablation. It does not establish autonomous objective discovery, improved fresh model reasoning, a second self-improvement cycle, generality, long-term reliability or complete cost efficiency.

## Evidence and branch safety

The [original cohort artifact](cohort-45334226981.zip), exact prompts/responses, all six patches, public feedback, per-case outcomes, usage, frozen sources and failures are retained with SHA-256 digests in [attempts.json](attempts.json). Ordinary evidence commits do not use the deliberate `experiment3: run frozen cohort` subject, so they skip inference. Any deliberate rerun is another run requiring separate accounting. All work stays on `research/recursive-improvement`, draft [PR #39](https://github.com/BillyMixNix/Hive/pull/39). Main is not modified or merged, and no candidate is deployed automatically.


[measurements.json](measurements.json) summarizes the original measurements; it does not replace the raw artifact. Original artifact SHA-256: `61fef5f6cc04d75e6769e7cac3402a927d3aca8e8883056aa125d99990246a16`. Protocol SHA-256: `38e631ea4b79a5e8697e50c01b07fb911f20a8513b8e68c428f55f8e609dbca6`.

Original environment: Docker 28.0.4, x86_64, kernel `7.0.0-1014-aws`, image `sha256:76580bb61a9a44611a73cc32caf624cdfe4a5e13b8b928fb31b2090feed2e560`. Effective resource probes passed: timeout 3,040.792 ms; output cap 147.571 ms; OOM probe 243.061 ms with child SIGKILL, kernel `oom_kill: 1`, `memory.max: 268435456` and Docker `OOMKilled: true`. The parent completed successfully. Effective write/network/UID/capability/seccomp/privilege/CPU/PID/memory checks matched policy, and cleanup succeeded.

For original study reproduction, check out controller commit `b2b8d01c4aeb622d2c6ed3a7d8758cbe97f76474` and its pinned baseline. Its 214-file manifest is verified against that commit, not against later compatibility edits on the branch. Re-running generation constitutes another cohort requiring fresh accounting. Diagnostic source is pinned separately at `edfac8c9d79a3537e53e454e7aeed79114481f5e`; its 21-file manifest preserves the exact original candidate bytes and Planner grading inputs. Replaying those saved patches makes no model requests. Source identity, seeds and hashes permit reconstruction but do not establish identical regeneration across machines.

No candidate patch is applied to production. Main remains `b2d3df6fdbc2b3d395d74a0c25d3c777382cd170`.


The [integrity audit](integrity.json) verifies every frozen source hash against its pinned Git commit and every included artifact source file. Actions' default hidden-path exclusion omitted the `.github` workflow paths from the ZIPs (two original, one diagnostic). Their exact bytes are recovered from the pinned commits in [archived-workflows](archived-workflows/) and SHA-256 checked. The downloaded ZIPs are preserved unchanged. This omission affects artifact completeness, not the runtime freeze or candidate scoring.
