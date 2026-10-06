# Existing-interface expressibility

**A valid J001 plan is easily expressible without changing production Hive.** The manually constructed plan is `evidence/manual-valid-plan.json`; it has backend as sole owner, UI/tests canonically inactive, behavior-preserving acceptance, and no interface contract. It contains no implementation or patch. It is used only in deterministic interface tests, never as a live model answer or example.

`interface_probes.py` runs JSON Schema Draft 2020-12 validation using jsonschema 4.25.1 in an isolated tooling directory; validates the schema itself; calls `_normalize_plan`, `_validate_host_write_scope`, `_validate_intent_coverage`; and checks the exact dispatch predicate. It then runs the real isolated Hive orchestration against a copy of the frozen baseline with a synthetic planner callback returning that plan. The backend callback is reached and deliberately raises before any model generation/edit. Reviewer is subsequently invoked by normal orchestration and also stopped by the sentinel. The resulting run is rejected with a skipped full-gate prerequisite, not accepted software.

Evidence: `evidence/expressibility-dispatch.json`, `evidence/expressibility-runs/e00300000001/`, `evidence/counterfactual-probes-before.json`. Normalized minimal plan is recorded in probe 01. Model calls: zero; worker callback: reached; files changed: none; executable verification: none. The first script launch had a diagnostic-only incorrect baseline dictionary key and stopped before dispatch; the key was corrected and the isolated dispatch probe completed. Production files were unchanged.

## Counterfactual results before repair

| Probe | Schema | Controller | Reason / dispatch |
|---|---|---|---|
| 01 one active owner | Accept | Accept | backend |
| 02 two active owners, valid contract | Accept | Reject | duplicate backend/tests ownership |
| 03 second active role requests read-only work, no files | Accept | Reject | active goal requires write files |
| 04 one active plus canonical inactive | Accept | Accept | backend |
| 05 two inactive roles | Accept | Accept | backend active; UI/tests inactive |
| 06 unauthorized path | Reject | Reject | outside host scope |
| 07 duplicate plus missing contract | Accept | Reject | reports both defects |
| 08 two disjoint writers with contract | Accept | Accept | backend/tests; explicitly synthetic two-file scope |
| 09 single owner, no contract | Accept | Accept | no contract necessary |
| 10 inactive goal with write claim | Accept | Reject | ownership and inactive/files contradiction |
| 11 disjoint writers, missing required contract | Accept | Reject | multi-role contract required |
| 12 all inactive | Accept | Accept | no workers eligible; not task success |

Enumerating each role's membership in the one-file assignment gives eight subsets. All eight satisfy the existing generation schema; four satisfy ownership validation (none or exactly one). The four multiple-writer subsets fail. This is a count of permitted structural states, **not a probability distribution**. Both historical TRANSITION-002 responses satisfy their generation schema but fail the normal validator. The tests-only/UI-only generic plans in that enumeration demonstrate syntactic ownership expressibility, not task-semantic suitability for changing Java application behavior.

The read-only probe uses `hive_context.observe(..., read_file_excerpt, ...)` to read application source without assigning it as a write. `validate_edit` still denies the tests role an edit to that context file when its assignment is a different test file. Evidence: `evidence/read-versus-write.json`. Separate context access works for an existing worker; the planner does not represent a standalone active read-only worker. Inactive roles are skipped, not dispatched as observers. Host verification and reviewer are separate from worker write ownership.
