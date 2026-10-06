# Nix Workshop v0.7.7

## Repository-derived grounding

- Added a compact deterministic repository-facts layer for framework and integration evidence.
- Planner prompts now receive detected framework, route declaration examples, and frontend API usage from application source.
- Backend and repair prompts receive the same facts as read-only evidence, with an explicit FastAPI contract when the repository uses FastAPI.
- The prompts explicitly prohibit substituting a different framework, such as Flask decorators or `jsonify` in a FastAPI application.
- Added focused tests for deterministic facts, noise-free bounded output, planner/worker injection, and live run telemetry.

The existing validator, agent scopes, approval flow, provider routing, budget controls, verification, rollback, snapshots, and ledger behavior are unchanged.
