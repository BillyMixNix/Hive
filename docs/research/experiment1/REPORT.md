# Hive Experiment 1 — no demonstrated improvement

Date: November 23, 2026. Branch: `research/recursive-improvement`.
Draft PR: [#39](https://github.com/BillyMixNix/Hive/pull/39).
Verified implementation: `f18d5a965b913f13329f45332c3394e7f0f22c62`.

**Result:** Hive made real Planner and Coder inference calls, but neither completed
generation attempt produced an admissible candidate. Baseline scoring and sandbox
controls worked. There is no measured candidate gain, no accepted code change to
Hive's production modules, and no evidence of recursive self-improvement.

## Fixed study

The baseline is `87e64edc9b0d4fef6d6838f2fc6dc4ccca624bfb`. The selected software
task was to improve `PlannerAgent._extract_json_object`, which currently slices
between the first opening brace and last closing brace. The contract requires the
first independently decodable JSON object, handling malformed prefixes, nested
objects, quoted braces and trailing objects/prose; absent objects raise ValueError.
This is a method-level parsing benchmark, not an end-to-end coding benchmark.

Eight public examples and 32 distinct held-out cases, thresholds, worker and
controller identities were frozen before inference. Generation saw the public
examples and baseline source, never the held-out file. The held-out expected
answers remained in the external host controller and were not mounted in subject
containers. Protocol, public-case and held-out hashes are identical across both
completed runs. Controller repairs have separate commits and per-run hashes.

Acceptance required at least 20 distinct paired held-out cases; at least five
percentage points more accuracy in every repetition; no baseline-correct case
regression; all public examples and recorded regressions; passing repository
tests; and at most 25% median host batch latency growth. The original zero-API-fee
cost gate is separate from full lifecycle compute cost, which remains unknown.
No threshold was relaxed after observing results.

## Actual measurements

| Measurement | First completed run | Run after adapter repair |
|---|---:|---:|
| Actions run | [45262925695](https://github.com/BillyMixNix/Hive/actions/runs/45262925695) | [45263989826](https://github.com/BillyMixNix/Hive/actions/runs/45263989826) |
| Baseline public correctness, each repetition | 5/8 (62.5%) | 5/8 (62.5%) |
| Baseline held-out correctness, each repetition | 15/32 (46.875%) | 15/32 (46.875%) |
| Repetition shuffle seeds | 11, 29, 47 | 11, 29, 47 |
| Median host held-out batch wall time | 348.885 ms | 251.604 ms |
| Baseline recorded return-value regressions | 4/4 | 4/4 |
| Real model calls | 2 | 2 |
| Prompt tokens | 5,812 | 5,835 |
| Output tokens | 429 | 2,368 |
| Generation call wall time | 94.592 s | 183.261 s |
| Candidate correctness, latency, regressions | Not evaluated: no valid candidate | Not evaluated: no valid candidate |
| Promotion | Disabled | Disabled |

Across both generation attempts: **4 calls, 11,647 prompt tokens, 2,797 output
tokens, 277.853 seconds of model-call wall time, and $0 paid API charges**.
The model ran locally on the GitHub VM. Dollar compute cost and independently
measured CPU/energy cost are unknown. Downloads, infrastructure attempts and CI
are not included in that inference-time total. Zero API fees do not establish zero
cost or satisfaction of a complete lifecycle cost budget.

Each accuracy fraction has only 32 distinct held-out cases. Repetitions do not
turn these into 96 independent cases. Host latency includes fresh container
startup and cleanup and must not be interpreted as isolated method runtime.
Subject-side method timers are untrusted diagnostics.

## Failure analysis and repairs

Two infrastructure attempts preceded real inference. Run
[45262206999](https://github.com/BillyMixNix/Hive/actions/runs/45262206999) built the
image but failed while inspecting a base-image tag not loaded by BuildKit. The
workflow now explicitly pulls that image before recording it. Run
[45262410643](https://github.com/BillyMixNix/Hive/actions/runs/45262410643) exposed
output-pipe backpressure during the flooding self-test. The runner now disconnects
the attachment before forcibly removing the container; an ordering regression
test and subsequent real Docker self-tests verify the repair. Both attempts made
zero model calls.

The first completed run used the original agents without shared repository state.
Coder rejected the task because required `target_symbol_id`, `lineno` and
`end_lineno` proof was missing. The experiment adapter now uses the original
`HiveStateManager`, rebuilds its baseline repository map, canonicalizes the task
anchor, supplies that shared state to both agents, and checks the proof before
spending model calls. A focused test verifies the actual span. This was an
engineering repair by the external developer, not a Hive-generated improvement.

The follow-up had the correct anchor:
`planner.py::PlannerAgent._extract_json_object`, lines 526–533. Its Planner output
nevertheless drifted toward an unrelated feature in `main.py`; the normalizer kept
the authorized file/symbol anchor. Coder then repeated prose in `REASON:` until
the 2,048-token cap, with `done_reason: length`, and emitted no `PATCH:` section.
Hive returned `failure_code: missing_patch_section` and `status: blocked`.
The policy rejected it. No generated candidate was imported or executed, and no
hand-written replacement was substituted.

Consequently matched baseline/candidate trials, candidate repository regressions,
candidate cost/latency comparison and the empirical acceptance gate could not be
completed. Their values are unavailable, not zero and not passes. Experiment CI
success means the bounded study ran and preserved its failure, not efficacy.

## Isolation and verification

Each subject uses a local immutable image ID, nonroot UID 65534, read-only root,
source and worker mounts, no network, no Docker socket or credentials, all
capabilities dropped, no-new-privileges and default seccomp. Limits are 1 CPU,
256 MiB memory with no extra swap, 32 PIDs, 16 MiB tmpfs, 20 seconds wall time,
and 256 KiB output. The separate repository-test mode is capped at 512 MiB and
300 seconds. The Oracle and policy stay outside the subject process. Only the
authorized method body can differ; AST checks protect signatures, decorators,
imports, other methods, tests, evaluators, workflow and sandbox definitions.

Both completed runs passed effective-policy and destructive-limit probes:
read-only writes and external-network access denied; no capabilities, privilege
escalation, socket or credentials; cgroup CPU/memory/PID limits observed; busy
loop timed out; flooding stopped at the output limit; memory exhaustion produced
an OOM kill. These are observed controls on an expendable Linux VM, not a formal
guarantee against kernel exploits. Pytest inside a subject interpreter is only a
diagnostic regression check; the external held-out comparator is authoritative.

On implementation commit `f18d5a9`, all three workflows passed: Experiment 1,
Reliability Gate, and [CI](https://github.com/BillyMixNix/Hive/actions/runs/45263989686).
The full CI suite recorded **366 passed and 7 passing subtests in 238.35 s**;
the focused controller/policy suite recorded **33 passed**. Earlier local
verification on `e8593fd` recorded 358 passed, 1 skipped (Torch unavailable), and
7 passing subtests. That older local log is explicitly labeled by commit.
`py_compile` and `git diff --check` also passed. Only the research branch was
updated. `main` remained at `b2d3df6fdbc2b3d395d74a0c25d3c777382cd170`.

## Reproducibility and limits

Both runs used `qwen2.5-coder:1.5b`, Q4_K_M, digest
`d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668`,
Ollama 0.40.17, seed 1729, temperature zero, 16,384 context, four inference
threads and at most two 2,048-output-token calls per run. Raw image metadata,
freeze manifests, prompts, responses, model usage, case results and self-tests are
preserved in the two run directories. Artifact ZIP digests were verified before
extracting those records; `evidence_sha256.json` indexes preserved file contents.

Baseline outputs were repeatable across all six baseline repetitions on two VMs.
Generation was not bitwise reproducible: the Planner prompt bytes and recorded
generation settings/model digest matched, but its two responses differed. The
VM kernels/images differed; Coder context also changed after the adapter repair.
These runs are not a controlled independent replication of an improvement, and
the cause of generation divergence was not established. Mutable image tags and
transitive dependency resolution also limit exact future environment recreation.

The study covers one selected method, one small model configuration and
hand-authored cases. It neither demonstrates RSI nor disproves that a stronger
configuration could improve Hive. Existing global test fixtures also create
temporary directories beneath the source tree; future candidate-wide regression
runs must address that compatibility while preserving immutable evaluator files.
That path was not exercised because neither proposal became executable.

## Next experiment

Keep the verified sandbox and canonical state integration. Retire these published
held-out cases. First add an independent check that a plan remains on the requested
goal before spending a Coder call, and constrain the patch response so repeated
explanations cannot consume the whole budget. Then freeze a new study with fresh
held-out tasks, a clearly identified stronger backend or smaller prompt contract,
several independent generation seeds, pinned environment artifacts, and externally
measured compute/lifecycle cost. Evaluate every admissible proposal without
discarding failed attempts. No automatic deployment or change to `main` follows
from this report.
