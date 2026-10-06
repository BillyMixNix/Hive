# v0.10.1 Planner Coverage Gate

- Preserves explicit runtime-display requirements in a host-derived immutable intent envelope before planning.
- Rejects plans that drop a required UI consumer, regression coverage, or existing interface contract; the planner retains its single bounded correction attempt.
- Adds deterministic FastAPI interface facts with method, path, handler, and statically recoverable literal response keys.
- Allows an existing backend interface to satisfy a UI/tests contract without forcing an unnecessary backend edit.
- Propagates relevant intent obligations and interface contracts into worker retrieval and prompts without expanding write scope.
- Runs staged pytest verification with a private writable `--basetemp` so environmental permission errors do not mask real failures.
- Preserves strict worker ownership, edit validation, observation/replan/repair budgets, deterministic verification, reviewer, explicit approval/apply, rollback, and provider budget controls.
