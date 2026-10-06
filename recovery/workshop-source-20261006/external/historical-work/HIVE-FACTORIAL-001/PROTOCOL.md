# HIVE-FACTORIAL-001 preregistered local 2×2 pilot

This is a new local characterization, not an Astra continuation or a rerun of HIVE-LOCAL-001. Four new Java tasks (J001–J004), two independent replicates each, two installed models, and two controllers yield 32 candidate runs. The immutable M3.2 baseline and hidden JUnit sources are common to all runs. Each run starts with a fresh run-owned external candidate. No promotion or application is permitted.

## Factors

- Model: exact locally installed `qwen3:8b` or `qwen2.5-coder:14b` digest recorded in the lock. No download, cloud fallback, or model substitution.
- Controller: `single` or `hive`. Both use the *same frozen Hive host executor* for external-root snapshotting, observations, Java edit validation, bounded structural/targeted repair, and sealed verification. The `single` condition has one model enactment agent: its file list is the exact write scope in TASKS.md; deterministic adapters supply a no-decomposition plan and accept only after host verification, so no model planner or reviewer is invoked. The `hive` condition uses the unmodified planner, workers, correction paths, and reviewer. This isolates the model coordination layer; it does **not** compare Hive against an unrestricted agent or remove the shared safety executor.

The exact task text in TASKS.md, including its file scope, is sent unchanged in both conditions. A common host allowlist rejects a Hive plan that assigns any file outside that public scope before workers execute; the single-agent adapter receives the same scope. Hidden test source, test names, and verifier outputs are withheld until after the proposal. The baseline source and approved dependency/input caches are read-only; the verifier remains network-disabled.

## Common limits and order

- Within each task/replicate block, controller/model cell order is pseudorandomized with seed `20261004`; the complete 32-run order is recorded in the lock before the first model request.
- Same maximum of 250,000 aggregate input+output model tokens per run, enforced before each call using UTF-8 request bytes as a conservative upper bound on input token count plus the host's output-token limit. Actual tokens need not match and are recorded separately. Same 3,600-second model-decision wall deadline from first model request; sealed verification retains its own bounded timeout and is not interrupted mid-container. These are equal *ceilings*, not forced equal consumption.
- Same installed Ollama service, model-specific native context and quantization recorded in the lock, same host-controlled temperature and per-role output limits as the frozen Workshop. No seed support is assumed; replicates measure nondeterminism. No cloud key in the child process.
- Same aggregate six read-only observation ceiling per run (and the unchanged six-per-worker limit), one structural repair and one targeted correction per worker, exact-edit language operations, external-root boundary, frozen targeted JUnit acceptance, and full offline Gradle/GameTest gate only after acceptance passes. The model cannot choose verifier commands.
- No failed trial is rerun. Stop the whole study on false acceptance, frozen lock/baseline/test/cache/image mismatch, containment breach, cloud contact, or promotion. Infrastructure and harness errors remain distinct from model task failure.

## Scoring and evidence

`VERIFIED_SUCCESS` requires the hidden targeted acceptance and complete sealed gate to pass. Other classes are `MODEL_TASK_FAILURE`, `VERIFIER_INFRA_FAILURE`, `LOCAL_RUNTIME_FAILURE`, `HARNESS_FAILURE`, `FALSE_ACCEPTANCE`, and `INVALID`. A model or controller producing a plausible diff is not success. Record each raw run, planner/worker/reviewer result, observations, corrections, changed files, verifier checks, model calls/input/output tokens, wall time, local generation time, and baseline/candidate integrity. Unknown usage stays unknown; local API cost is zero by design. Do not call one factor superior solely from aggregate totals; task heterogeneity and four-task sample size limit inference.

This protocol and all four tests must be hashed and locked before any benchmark model call. Existing Astra and HIVE-LOCAL-001 evidence must not be modified.
