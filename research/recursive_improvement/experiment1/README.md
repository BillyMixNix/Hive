# Experiment 1

This study asks whether the existing Hive Planner and Coder can propose a useful
change to `PlannerAgent._extract_json_object`. It does not test open-ended RSI.
The baseline is commit `87e64edc9b0d4fef6d6838f2fc6dc4ccca624bfb`.

`protocol.json`, eight public examples, 32 held-out cases, the worker, controller,
and Dockerfile are SHA-256 frozen before generation. The model sees the contract
and public examples, never the held-out file. Held-out cases are hand-authored,
so this is a small selected software benchmark, not evidence of general ability.
They become public with this research commit and must be retired after this run.

The controller exports the pinned baseline. Only the permitted method body may
differ in a candidate; AST checks reject changes to imports, signatures,
decorators, other methods, evaluators, tests, and workflows. No candidate is
applied to the research checkout or any branch. Generated text is parsed and
patched as data on the host. Subject imports and execution happen only in Docker.

The local inference adapter replaces only the agents' model transport. It uses
real `qwen2.5-coder:1.5b` inference with a two-call, 2,048-output-token-per-call
budget, seed 1729 and temperature zero. The original `plan_task`, `generate_patch`,
validation, and fallback behavior remain in use. Coder receives a Docker-backed
public smoke executor. A fallback plan is recorded as a fallback, and a blocked
patch is never relabeled a successful proposal. Valid failed patches may be
evaluated diagnostically. No fabricated candidate is substituted for a failure.

The external controller compares actual return strings or exceptions to expected
answers. The candidate cannot award scores, omit cases, or supply expected values.
Each repetition uses the same inputs for both versions. Three fixed shuffle seeds
and alternating version order test repeatability, not independent model samples
or independent replication. Correctness is reported by distinct case and by
repetition; repetitions do not increase the number of independent cases.

Acceptance requires the original minimum 20 distinct cases, a five-percentage-
point held-out accuracy gain in every repetition, no baseline-correct regression,
all public examples, recorded regressions and repository tests, and at most 25%
median host wall-time growth. The zero-API-fee cost gate is reported separately
from model tokens, generation time and unknown dollar compute cost. Passing it
cannot establish a total lifecycle cost improvement. Timings supplied by the
subject are explicitly untrusted; host timing includes container overhead.

The runner requires an immutable local image ID, local Linux Docker daemon and
seccomp/resource controllers. Effective-policy probes test nonroot execution,
read-only source/harness/rootfs, no network or secrets/socket, dropped capabilities,
no-new-privileges, cgroup memory/CPU/PID limits, timeout cleanup, output bounds and
OOM termination. Containers have no writable host mounts. The oracle is not
mounted; the harness mount contains only `worker.py`. Pytest executes in a separate
512 MiB, 300-second container; other subjects use 256 MiB and 20 seconds. The
container shares a kernel with an expendable GitHub runner VM and is not a formal
guarantee against kernel exploits. In-container pytest shares an interpreter with
the subject and is a diagnostic regression check, not an independent score oracle.

The PR workflow has read-only GitHub permissions, no injected secrets, no persisted
checkout credentials, no branch-write or promotion operation, a 25-minute job
budget, and always uploads evidence and removes containers. It runs only for this
repository's research branch. `main` is never modified or merged.

To reproduce on a credential-free disposable Linux VM with Docker:

```sh
pip install requests==2.32.3 pytest==8.3.5 z3-solver==4.15.4.0
docker build -t hive-experiment1:local research/recursive_improvement/experiment1
# Start the pinned Ollama service and pull the protocol model as in the workflow.
python -m research.recursive_improvement.experiment1.run \
  --image "$(docker image inspect hive-experiment1:local --format '{{.Id}}')" \
  --output /tmp/hive-experiment1-evidence
```

Reuse recorded image/model digests when reproducing. Tags and package transitive
dependencies can change; exact image metadata is preserved per run. Output includes
the pre-inference freeze, raw prompts/responses, Planner/Coder provenance, patch,
per-case outcomes, host timing, security probes and errors. CPU seconds and dollar
compute cost are unknown unless independently instrumented; they are not invented.

Next experiment: retire these held-out cases, fix the observed pipeline failure,
repeat with independently generated candidates across several generation seeds,
and add externally measured CPU/energy and complete lifecycle cost before a broader
efficacy claim. Promotion remains a separate human-reviewed operation.
