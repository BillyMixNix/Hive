# Hive

Hive is a **regression-first coding agent**.

The project no longer treats prompt advice as proof that a model has learned. A remembered lesson may help generate a patch, but executable evidence decides whether the system improved.

## The operating loop

1. A model proposes a patch.
2. Hive applies it in an isolated workspace.
3. Syntax and structural safety checks run.
4. Every recorded regression relevant to the changed file runs.
5. A patch that repeats any known failure is rejected.
6. Newly discovered failures are recorded as executable regression cases.

The model does not need to become permanently smarter. The surrounding system becomes progressively less able to repeat mistakes.

## Executable regression memory

Regression cases live in `validation/regressions/*.json`. They describe a target file, a callable, inputs, and either an expected return value or expected exception. Cases can also mutate the returned object afterward to detect accidental aliasing with caller-owned inputs.

Run the complete memory gate with:

```bash
python -m regression_gate
```

Run only cases for one file with:

```bash
python -m regression_gate --file router.py
```

The standard test suite runs the complete recorded regression memory, so a pull request cannot silently reintroduce a known behavior failure.

## What lessons are for

Hive may still retrieve lessons and include them in model prompts. They are hints, not authority. A lesson is useful only when the resulting patch passes executable checks.

## Current boundary

Hive is not claiming autonomous model training or reliable self-improvement through prompting. Its measurable promise is narrower:

> Once Hive can express a failure as a regression case, future accepted changes must not repeat it.

## Kingdom / Mind Constructor experiment

The `kingdom` package is an experimental layer for turning compressed human intent into divergent investigations, reality contact, recursively decomposed construction, and a final end-to-end walk of the original request.

Standard cognitive-topology mode:

```bash
python -m kingdom "Can cognition be externally extensible?" --branches 12 --workers 4
```

Construct mode adds forced incompatible worlds, branch novelty filtering, Arena verification, missing-capability promotion, dependency closure, executable construction rounds, durable checkpoints, and a terminal **Critical Intent Path**:

```bash
python -m kingdom "Build an artificial decompression intelligence" --construct --branches 12 --worlds 6
```

Near the end, Kingdom preserves the original request as an intent capsule, gives a fresh verifier the original intent plus the public finished state, and walks the real user/artifact path through the assembled result. Failed or unavailable steps cannot be semantically waved through: they reopen the construction graph at the exact broken path step. If all technical steps pass but the result has drifted from what the operator meant, a semantic repair target is opened under the original goal. Only a passing walk marks the root goal verified.

Each intent walk is written as its own SHA-256-addressed artifact and anchored in Hive's hash-chained ledger. The construction checkpoint is persisted after the walk, so reopened critical-path failures survive into resume mode. `--skip-intent-path` exists only as an explicit debugging escape hatch.

Restricted capability acquisition is an explicit opt-in. With `--forge-missing`, a missing pure-function capability may be proposed, independently acceptance-tested, policy-checked, tested through Hive's `RegressionGate`, executed again in an isolated timeout-bound runtime, registered into Arena only after passing, and then used to retry the exact blocked request:

```bash
python -m kingdom "Build an artificial decompression intelligence" --construct --forge-missing --branches 12 --worlds 6
```

The forge is deliberately not a general Python sandbox: generated tools cannot import modules or gain file, network, process, package, or privileged host authority.

See `Docs/KINGDOM_0.md` for the full architecture, authority boundary, critical intent-path contract, and open research claim.