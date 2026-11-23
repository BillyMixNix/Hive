# Experiment 2: structured generation

Protocol revision 2b preserves the failed first generation run (45280078249):
all three 7B Planner responses were on-topic but the external vocabulary gate
incorrectly rejected their scan/brace wording. That is a harness failure, not a
model result. The gate now recognizes that wording while still requiring the
exact objective/file/symbol and rejecting unrelated files or feature work.
The three original response bytes and original usage are frozen for replay.
The continuation makes only the three unused Coder requests, so total real
inference remains bounded at six requests across the original and continuation.
Historical usage is included once, with replay explicitly identified separately
from new calls. This repair was selected after inspecting plans, before any
candidate or held-out result; it is not an independent replication or an unchanged
protocol rerun. Original artifacts, including the failure, must remain available.

This is a new frozen feasibility cohort on the original baseline
`87e64edc9b0d4fef6d6838f2fc6dc4ccca624bfb`. Experiment 1 evidence is unchanged.
The selected target remains `PlannerAgent._extract_json_object` in `planner.py`.

The external developer changes three conditions: compact source-grounded prompts,
JSON-schema model responses, and Qwen2.5-Coder 7B instead of 1.5B. Temperature is
0.2 with three predeclared seeds (1729, 2718, 31415). This joint change tests
feasibility; it cannot identify which condition caused a difference. There are
at most six inference requests for the entire cohort: one Planner and one Coder
per seed, with no retries, planner repair, or hand-written candidate substitution.

The original baseline `PlannerAgent.plan_task` and `CoderAgent.generate_patch`
remain in use with shared canonical repository state. Their model transport
records the original prompt and actual compact prompt. Raw Planner JSON must
match the objective, file and symbol and describe JSON extraction before Coder
can run. Raw Coder JSON contains only the complete method source. A trusted,
deterministic serializer indents that source and constructs a unified diff; it
does not repair its algorithm or signature. Hive's existing patch checks and a
Docker-only public smoke executor still run. Blocked original-agent output stays
blocked. A structurally safe transport patch can be measured diagnostically but
cannot pass the Hive-proposal criterion.

Eight public examples and 64 fresh distinct held-out cases are frozen along with
the protocol, schema/adapter/controller, worker, regression compatibility adapter,
and imported comparison/boundary helpers. The model receives only public examples
and the selected baseline method. The whole three-seed generation cohort finishes
before held-out feedback from any candidate is used. Every distinct admissible
patch is evaluated; duplicate source hashes share evaluation records and are not
counted as independent software improvements. No best-of-heldout promotion exists.

Each distinct patch is compared to the pinned baseline on identical inputs and
three shuffled evaluation repetitions with alternating order. Acceptance keeps
the 5-percentage-point gain threshold, no loss on baseline-correct cases, all
public examples, all recorded return-value regressions, and the same complete
lightweight repository test pass/skip counts as baseline. Median host batch
latency may grow by at most 25%. Cost comparison covers zero API fees only;
model tokens, request time, and incomplete telemetry are recorded separately.
Dollar compute/lifecycle cost is unknown, so even passing these gates cannot
establish full cost efficiency or recursive self-improvement.

The tested image omits optional Torch. Its existing module skip must match between
baseline and candidate; all other tests must pass. Before any generation call,
the entire baseline suite must pass in the same container. Existing legacy tests
and benchmark helpers create `_tmp_*` fixtures below the source tree. A frozen
pytest adapter changes only those modules' `Path` aliases to place these scratch
files in tmpfs. Assertions and on-disk test/production source stay unchanged and
read-only. Relative production reads use a scratch-directory symlink view of the
immutable source. In-interpreter pytest is a diagnostic regression check, not an
independent malicious-code oracle; held-out expected values and grading remain
outside the container.

Normal subjects retain Experiment 1 limits: nonroot, read-only root/source/harness,
no network/secrets/socket/capabilities, seccomp/no-new-privileges, 1 CPU, 256 MiB,
32 PIDs, 20 seconds, 16 MiB scratch and 256 KiB output. Repository tests use
512 MiB, 128 MiB scratch, 420 seconds and a 32 MiB file limit for legacy snapshots.
The inference service is separately bounded at 10 GiB, four CPUs and 128 PIDs;
the whole Actions job is capped at 45 minutes. Python and Ollama base images are
pinned by registry digest and Python dependencies have exact version pins. The
pulled model digest is checked against the predeclared prefix and its full digest
is recorded before generation.

The Actions workflow executes the expensive cohort only when the exact head commit
subject is `experiment2: run frozen cohort`. Evidence/ordinary code commits do
not spend inference budget. Repository permissions are read-only, checkout
credentials are removed, and artifacts/cleanup run even on failure. Keep this
commit marker deliberate; manually rerunning that same workflow is another cohort
and must be reported. Nothing writes or merges `main`, and no candidate is
automatically deployed.

Primary protocol references:
[Ollama structured responses](https://docs.ollama.com/capabilities/structured-outputs),
[generation API](https://docs.ollama.com/api/generate),
[model tags](https://ollama.com/library/qwen2.5-coder/tags).
