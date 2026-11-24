# Experiment 3: one bounded public-feedback repair

The baseline is `bbc0b2dcc216b51d4c13232754926f23ea45fd31`. Its validator repair
was written externally and passed 379 local tests with one optional skip. It is
not credited as a Hive improvement. Real unified diffs now compare parsed trusted
before/after source outside the selected definition; unchanged diff context is
not counted as an edited definition. Tests cover body-only neighbor edits,
module/import/class/decorator changes and all three archived Experiment 2 patches
as data. Legacy shorthand diffs and the existing complexity helper exception
retain their old behavior. This is not a general sandbox or proof about every
patch format. Experiment candidates use strict numeric unified diffs and an
additional immutable single-method-body AST boundary.

The original Planner runs once per seed (4242, 5656, 7878). The original Coder's
`generate_patch_with_revisions` gets at most one revision, using its existing local
initial-pass reflector. There are at most nine fresh request attempts for this
whole cohort: three Planner, three initial Coder and three repair Coder. Hive may
stop early; no external retry forces the budget to be consumed. Initial requests
use the declared seed, repairs use seed + 100000, temperature 0.2. Qwen2.5-Coder 7B
must match the full previously recorded model digest. No old model responses are
replayed for generation and no algorithm is hand-repaired or substituted.

Compact JSON-schema transport records original and actual prompts. Public-only
Docker outcomes and the previous method are supplied to the repair request. If
Hive retries before public execution, the recorded Hive contract-error context
is supplied instead. Feedback cannot change the objective, schemas, tests,
permissions, method scope or sandbox. Every admissible initial and repair patch
is retained, including blocked attempts. Candidate code is never imported or
executed by the host; parsing and strict diff application treat it as data.

Fourteen public examples, 96 fresh distinct held-out extraction inputs and eight
fresh Planner response-replay inputs are frozen before inference. Expectations
are specified by construction rather than by a reference extraction algorithm.
Input texts do not overlap previous studies. The held-out set contains related
families and is not a claim of 96 independent software tasks. The entire generation
cohort finishes before any held-out extraction or planning feedback exists.

All distinct source hashes are compared with baseline on the same three shuffled
repetitions (11, 29, 47), alternating order. Duplicate hashes reuse records and are
not independent improvements. Acceptance requires a five percentage point
held-out gain in every repetition, all public cases, no baseline-correct loss,
all recorded regressions, matching complete repository test pass/skip counts,
and at most 25% growth in median host batch wall latency. API-fee cost is zero
for both; tokens/request time are recorded separately and dollar compute cost is
unknown. Host container CPU totals are unavailable; worker timing is untrusted.

The added held-out response-replay gate calls original `Planner.plan_task` with
frozen raw model-like responses and no inference. All eight must produce the
expected goal, original-LLM source and correctly anchored repair task, with no
baseline-correct loss. The host owns expected goals and all grading. This tests
whether a helper change helps a real Planner code path. It does not test fresh
model reasoning, new coding tasks or a second self-improvement cycle.

Only Hive's chosen patch, selected using public feedback before held-out results,
can satisfy the bounded-gain claim. Other patches are diagnostic. All patches
are evaluated, without best-of-heldout promotion. Automatic promotion remains
disabled. Main is never changed or merged.

The Docker boundary, pinned image dependencies, effective-policy/OOM/output/time
probes and legacy scratch-path compatibility are reused unchanged from Experiment
2. Subject limits remain nonroot, no network/socket/credentials/capabilities,
read-only root/source/harness, seccomp/no-new-privileges, 1 CPU, 256 MiB, 32 PIDs,
20 seconds, 16 MiB scratch and 256 KiB output. Regression containers use 512 MiB,
128 MiB scratch, a 32 MiB file limit and 420 seconds. The inference service gets
four CPUs, 10 GiB and 128 PIDs. A 55-minute controller deadline leaves cleanup and
artifact time inside the 60-minute job. Interrupted requests retain started
records and unknown usage, rather than zero. Runtime/cleanup failures stop the
study. Original assertions and physical tests remain immutable; in-interpreter
pytest remains diagnostic, not an adversarial scoring oracle.

Only head commit subject `experiment3: run frozen cohort` triggers inference.
Ordinary code/evidence commits skip it. Frozen hashes, model identity, all request
records, raw responses, patches, public feedback, full scores, regression output
and failures are preserved. These changes jointly alter validator and feedback
conditions; any positive result is a bounded human-scaffolded helper improvement,
not proof of autonomous or recursive self-improvement.
