# Nix Workshop v0.10.4

This release fixes the two deterministic boundaries exposed by preserved Hive run `d3f9a50e3419` without changing model authority or retry budgets.

- FastAPI interface discovery no longer truncates the evidence consumed by `IntentEnvelope`; literal dictionary keys are recovered from both synchronous and asynchronous route handlers, including multiline returns.
- Static response analysis does not execute repository code, does not infer dynamic shapes, and does not treat nested scopes, comments, strings, or test text as application interfaces.
- The exact Ollama connection-display request now binds to the repository-verified `GET /api/status` response key `ollama`, allowing backend to remain inactive while UI and tests consume the existing contract.
- Observation requests are canonicalized by operation and normalized arguments. Repeating an already successful request fails closed as `RepeatedObservationError` instead of consuming all six observation slots.
- Observation history and duplicate protection persist across structural repair and the single bounded replan.
- Planner authority, exact ownership, validation, correction budgets, staging, verification, reviewer, human approval/apply, rollback, provider routing, and cloud budget controls are unchanged.
