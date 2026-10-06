# Nix Workshop v0.7.3

Exactly two architectural additions, based on the real v0.7.2 Project Summary failures:

## 1. Boundary-aware editing

- `insert_before_symbol` and `insert_after_symbol` resolve unique, complete top-level Python/JavaScript definitions. Python decorators remain attached to their original definition. Common JS function-valued declarations and inline scripts are supported.
- `insert_after_element` resolves a unique HTML ID or the container of a direct heading, then inserts balanced sibling markup after the closing tag.
- New primitives lower to ordinary exact replacements. The existing `validate_edit` function is unchanged and remains authoritative both before source access and after lowering.
- Added atomic, in-memory preparation and structural checks for new and legacy edits: Python compilation, decorator attachment, declaration visibility, HTML balance/ID uniqueness, and inline handler bindings. No partial worker writes on failure.
- Decorator attachment checks include repeated Python definition names and class methods; an earlier definition cannot disappear behind a name-only lookup.
- Uses Python's syntax tree and a bundled Acorn 8.15.0 parser. Parsing never executes the proposed Python/JavaScript. Vendor source is excluded from planner/retrieved context but included with its license in the release.

## 2. Bounded originating-worker structural repair

- One structural repair model call per worker per run, through the existing caller and its provider/budget/cancellation gates.
- Repair receives concrete diagnostics, the rejected proposal, and the same responsibility, exact files, criteria and team plan. It replaces the entire unwritten proposal, then passes all existing and new checks.
- Scope violations are not retried. A valid plan-insufficient response still goes through the existing planner-only replan path. Replanning does not reset the structural repair budget.
- Invalid repair JSON, repeated structural failure, provider refusal or missing parser infrastructure fails closed. Parser infrastructure failures do not ask the model to fix its environment.
- Original proposal, diagnostic, repair reply and outcome are retained in both `run.edit_repairs` and the originating agent record; terminal failures also remain in `run.errors`.

## Compatibility and verification

Exact role scopes, the ownership validator, planner/replan validation, verification/reviewer gates, explicit apply approval, rollback, snapshots, ledger, provider routing, cloud budgets and the 900-second local timeout are preserved. The frontend is unchanged. No Context Preview or unrelated feature was added.

Added focused tests for structural boundaries, ambiguous/missing targets, Unicode offsets, JS templates/regex/arrow functions, HTML siblings, atomic failure, actual repair prompts/schemas, cross-scope repair attempts, bounded retries across replanning, parser availability, release hygiene, and the observed v0.7.2 failure shapes against real source. See TEST_RESULTS.txt for executed results.

Limitations: common top-level symbols and explicitly balanced HTML only; no TypeScript/JSX or arbitrary semantic correctness proof. Node is required for JS structural analysis; the included parser needs no online dependency installation. Captured-proposal replay uses controlled repair replies and is not evidence of a new live Qwen success.
