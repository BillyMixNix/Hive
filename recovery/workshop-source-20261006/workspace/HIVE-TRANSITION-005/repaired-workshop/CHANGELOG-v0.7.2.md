# Nix Workshop v0.7.2

Focused fixes following the real Project Summary replay with qwen2.5-coder:14b.

- Workers receive OVERALL OBJECTIVE, YOUR RESPONSIBILITY, YOUR FILES, TEAM PLAN, and YOUR ACCEPTANCE CRITERIA. Global feature acceptance remains in the plan for overall verification; it is no longer passed to every worker as its own assignment or retrieval query.
- Planner output now requires explicit `worker_acceptance` lists for UI, backend and tests. Missing or malformed role criteria go through the existing bounded planner correction path. Replans preserve other roles' criteria and update the affected worker's contract, including repair calls.
- Implementation is presented first. Escalation is reserved for inability to complete the worker's own responsibility with its write scope. Prompts explain that teammates implement the other portions. Removed the copyable `concrete blocker` escalation example.
- HTML context indexes container IDs/headings and JavaScript symbols, splits camelCase identifiers, follows local helper calls, and diversifies selected regions. It prioritizes complete useful regions before clipping to the existing size limits. The real Settings query now includes the Settings markup, OpenAI card, `api()` and `refreshStatus()`.
- Added tests at actual worker/repair call boundaries, tests for planner criteria validation and bounded replanning, and retrieval regressions using the actual Workshop page plus large synthetic HTML/JS fixtures.

Edit validation, file ownership scopes, staged edit application, approval/apply, rollback, verification, provider routing, cloud budgets, and the 900-second local timeout are unchanged. Existing saved runs remain readable; new generated plans must include per-role criteria.

Limitations: source excerpts remain bounded and JavaScript discovery is a lightweight index, not a full JavaScript parser. This patch's automated tests verify the supplied contracts and retrieved context; a new live Qwen build has not been run for v0.7.2.
