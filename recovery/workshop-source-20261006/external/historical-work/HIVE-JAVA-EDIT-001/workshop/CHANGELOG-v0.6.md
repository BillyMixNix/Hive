# Nix Workshop v0.6

Focused runtime release built from the Desktop v0.4.2 source lineage.

- AI Code Lab accepts natural-language Python requests, requires structured output, snapshots before writes, and runs generated code through the existing bounded runner.
- Planner, workers, reviewer, and Code Lab use fail-closed structured JSON parsing with one bounded repair retry.
- Hive Build runs through observable background jobs with progress, cancellation, retention, and health summaries.
- Hive worker context is relevance-ranked and excludes runtime state and caches.
- Existing approval gates, budget controls, snapshots, rollback, ledger, and loopback-only service boundaries remain in force.

Verification: 36 tests passed, Python compilation passed, frontend parsing passed, and live Qwen returned valid runnable structured Code Lab output.
