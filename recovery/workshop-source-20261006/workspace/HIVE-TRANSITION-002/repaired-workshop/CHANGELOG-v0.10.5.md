# Nix Workshop v0.10.5

This release fixes the first boundary exposed by live run `63a86e692594` without increasing authority or correction budgets.

- Existing-provider redundancy is no longer recognized through a verb or synonym list. The host compares structured planner-declared provider changes with the immutable IntentEnvelope and repository-verified interface shape.
- Restating an already-satisfied path, response field, and type triggers the existing single planner-correction path regardless of wording.
- Legitimate backend activation remains possible when the user request names a concrete path, response field, or response type absent from the verified interface.
- Static repository facts now propagate safely recoverable JSON value types through local assignments and local provider tuple returns without importing or executing repository code.
- `GET /api/status` is grounded as returning boolean `ollama` and array `ollama_models` values.
- Test workers receive a dedicated bounded section of repository-local endpoint tests that actually construct `TestClient` and issue in-process HTTP calls. Synthetic planner fixtures cannot qualify for that section.
- Planner authority, exact file ownership, observation and correction budgets, validation, staging, verification, reviewer, explicit approval/apply, rollback, provider routing, and cloud controls are unchanged.
