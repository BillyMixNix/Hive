# Nix Workshop v0.7.5

Focused worker coding-path improvements after the v0.7.4 live Qwen replay.

## Reliable bounded worker coding

- Owned-file worker context now includes a deterministic structural target index for existing HTML ids, direct headings, and top-level Python/JavaScript symbols.
- Worker prompts explicitly direct the model to use real source targets and never invent placeholder anchors or ids.
- Missing or ambiguous literal `replace` and `insert_after_anchor` targets now produce repairable structural diagnostics.
- The originating worker receives at most one complete replacement proposal under the same exact file scope and contract. Scope violations remain non-repairable, and the existing validator remains authoritative.
- Run telemetry records bounded actual prompt and response text alongside their lengths and SHA-256 hashes, making the real model contract inspectable without unbounded logs.
- Added a cross-file worker-path regression covering owned context, symbol/element edits, bounded repair, validator enforcement, review, and no automatic apply.

## Verification

`python -m compileall -q .` passed.

`python -m pytest -q` passed: 194 passed, 1 skipped.

The symlink regression remains skipped on this Windows host because symlink creation is unavailable. Existing ownership, approval, budget, verification, rollback, snapshot, ledger, planner/replan, and provider-routing behavior remains covered.
