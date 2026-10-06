# Minimal structural ownership repair

Production change: `repaired-workshop/workshop/hive.py`, only `_planner_response_schema()` and the schema-update portion of `_plan_correction_prompt()`. `evidence/production-function-diff.json` confirms all other functions, including normalizers, validators, dispatch and edit execution, are unchanged. TRANSITION-002 provider/context code is byte-identical.

When host authorization contains one distinct path, `_planner_response_schema` returns complete `anyOf` alternatives for each role whose pre-existing scope permits that path, plus the existing all-inactive state. An owner branch permits exactly that one file for its chosen role and requires nonempty own acceptance. Every other role gets canonical `no change needed`, no write files, and no acceptance entries. The model supplies the active goal and chooses the owner. No filename, task ID, language, symbol, or role priority is used to pick it. Scopes with zero, multiple, or unspecified host paths retain their existing behavior.

The correction logic applies independently required interface minimums to every alternative. It does not remove intent requirements or grant writes. The initial and correction text stay unchanged. Duplicate historical outputs are still rejected by the normal validator even if a provider ignores the schema. No normalizer discards claims.

This is deliberately narrower than a new ownership-map protocol: it encodes a capacity fact already implied by a one-file write scope. It prevents duplicate writers in that generation language while retaining genuine disjoint multi-role plans for larger scopes. The freeform selected-owner goal can still contradict its files (for example, claim `no change needed`); the unchanged semantic validator continues to reject that. This is not a claim that every schema-valid output is task-valid.

`repair.patch` is an applyable diff against final TRANSITION-002. `git apply --check` passed without modifying that prior tree. `repair-manifest.json` hashes the one production file and affected tests. Generated runtime test files are excluded from the patch.

## Deterministic evidence

One-file owner subsets: 8/8 previously schema-valid, now 4/8. Exactly the four subsets with at most one owner remain. The controller still accepts those same four structural states and rejects the same four overlaps. `counterfactual-probes-before/after.json` records the complete probes, including read-only access, unauthorized paths, inactivity contradictions, independent missing contracts, valid two-file coordination and no-contract single-role planning.

The **complete available repository suite** passed: **447 passed, 6 skipped**, all six skips due to unavailable Windows symlink privileges. This is broader than TRANSITION-002's 253-test boundary subset. Twenty new ownership test cases cover one-file combinations, different paths/languages and eligible owners, read/write distinction, inactive and unauthorized claims, correction constraints, unchanged multi-role plans, dispatch containment, schema-copy isolation and historical rejection. Prior T001 scope and T002 transport tests remain in the suite; only schema-shape assertions were adapted to inspect all alternatives. Actual correction text still matches the preserved complete prompt.

No frozen acceptance or J001 implementation success follows from these tests. Several controller tests use existing synthetic verifier fixtures. The single live trial independently tests the actual local provider and unchanged deterministic gates.
