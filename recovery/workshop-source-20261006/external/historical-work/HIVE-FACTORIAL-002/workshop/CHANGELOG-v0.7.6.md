# Nix Workshop v0.7.6

Focused repair-boundary follow-up after the v0.7.5 live Qwen replay.

## Bounded structural repair

- Structural repair prompts now provide explicit format-specific recovery rules: HTML anchor failures should select a real element id/direct heading, while Python/JavaScript failures should select a real top-level symbol.
- The repair contract explicitly forbids repeating the rejected edit and permits a safe no-op when no valid target exists.
- The host compares repaired edit proposals against the rejected proposal and fails closed with a structured diagnostic if the model repeats it. No recursive repair is possible.
- Workers are explicitly told that requesting files already in their exact write scope is not a valid `plan_insufficient` escalation.

The existing strict validator, ownership checks, approval flow, provider routing, budgets, verification, rollback, snapshots, and ledger behavior are unchanged.

## Verification

`python -m compileall -q .` and `python -m pytest -q` passed: 194 passed, 1 skipped.

The clean extracted v0.7.6 archive was also verified with the same result. The symlink regression remains skipped on this Windows host because symlink creation is unavailable.
