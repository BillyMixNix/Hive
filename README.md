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

## Orchestration realms

Hive's production-management layer has three responsibilities:

- **Chamberlain:** records projects, tasks, workers, leases, progress, and evidence.
- **Steward:** ranks blockers, review work, and downstream leverage, then records user decisions.
- **Marshal:** supervises a bounded fleet of persistent command-backed workers.

Start the cockpit:

```bash
python hive_cockpit.py
```

Copy `fleet.example.json`, replace the three project paths, and start the
three-worker fleet:

```bash
python fleet_manager.py --config fleet.json
```

The Marshal intentionally refuses more than three enabled workers. Each worker
receives assignment text through stdin; only the explicit command array from
the fleet configuration is executed, always without a shell.
