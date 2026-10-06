# Nix Workshop v0.7.4

Focused worker-context isolation after the first live v0.7.3 Qwen replay.

## Worker-context isolation

- Supporting retrieval no longer sends unrelated `tests/` fixtures to implementation workers. Explicitly owned test files remain available to the tests worker as owned context.
- Previous worker proposals remain available as bounded read-only integration metadata: role, execution/response status, owned paths and edit operation manifest. Raw summaries, code strings, anchors, errors and provider output are excluded from later worker prompts.
- Replanning uses the same sanitized proposal rendering instead of serializing raw previous responses into the planner request.
- A final authoritative worker contract is repeated after all read-only context so stale excerpts and teammate data cannot redefine the current role, objective, files or acceptance criteria.
- Active proposals with edits receive a conservative task-focus check. Clearly unrelated proposals fail closed before staging; ownership, structural validation, approval, verification, rollback, budget and ledger behavior remain unchanged.
- Repository maps also exclude output/release/artifact directories.

## Verification

The release includes focused regressions for fixture exclusion, sanitized proposal metadata, final contract precedence, and unrelated worker proposals failing closed. Full verification results are recorded in `TEST_RESULTS.txt`.

Limitations: task-focus checking is a conservative lexical protocol guard, not semantic proof of correctness. The existing strict validator and reviewer remain authoritative.
