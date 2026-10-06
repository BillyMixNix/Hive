# HIVE-TRANSITION-001: failure taxonomy

Source: `C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002/evidence/raw_results.json`, all 16 Hive trial `run.json` files and raw prompt traces. Every preserved plan parses as JSON. Classification records the earliest observable rejected transition; it does not infer hidden reasoning. Machine-readable per-attempt parse results, latent scope violations, errors, paths and hashes are in [failure-taxonomy.json](failure-taxonomy.json).

| Earliest failure class | Trials |
|---|---:|
| Missing role contract masks an already-present host scope violation | 8 |
| Inactive-role prose fails the recognized no-change contract | 6 |
| Worker edit anchor absent from source | 2 |

| Ordinal | Task / replicate | Model | Run | Primary class | Worker calls |
|---:|---|---|---|---|---:|
| 3 | J001 / r2 | qwen2.5-coder:14b | `cace24ea0b5e` | planner_missing_contract_masks_host_scope_violation | 0 |
| 4 | J001 / r2 | qwen3:8b | `a11a613abe9f` | planner_inactive_role_representation_mismatch | 0 |
| 6 | J004 / r1 | qwen3:8b | `e66097b0d1c2` | worker_edit_anchor_mismatch | 2 |
| 8 | J004 / r1 | qwen2.5-coder:14b | `be5c4b76eeac` | planner_missing_contract_masks_host_scope_violation | 0 |
| 9 | J003 / r1 | qwen2.5-coder:14b | `dbf0e6b7b221` | planner_missing_contract_masks_host_scope_violation | 0 |
| 12 | J003 / r1 | qwen3:8b | `5e231107ad2d` | planner_inactive_role_representation_mismatch | 0 |
| 14 | J003 / r2 | qwen2.5-coder:14b | `9140b61fa309` | planner_missing_contract_masks_host_scope_violation | 0 |
| 16 | J003 / r2 | qwen3:8b | `6c6a1636f8f2` | planner_inactive_role_representation_mismatch | 0 |
| 19 | J002 / r2 | qwen3:8b | `b35db6c70d35` | planner_inactive_role_representation_mismatch | 0 |
| 20 | J002 / r2 | qwen2.5-coder:14b | `a3754f78f834` | planner_missing_contract_masks_host_scope_violation | 0 |
| 21 | J004 / r2 | qwen2.5-coder:14b | `aa76bec28cb3` | planner_missing_contract_masks_host_scope_violation | 0 |
| 24 | J004 / r2 | qwen3:8b | `921471f64dd7` | planner_inactive_role_representation_mismatch | 0 |
| 26 | J001 / r1 | qwen3:8b | `dcb16552e596` | worker_edit_anchor_mismatch | 2 |
| 27 | J001 / r1 | qwen2.5-coder:14b | `ce99ccc67fe6` | planner_missing_contract_masks_host_scope_violation | 0 |
| 30 | J002 / r1 | qwen3:8b | `a8ffcf83b9fc` | planner_inactive_role_representation_mismatch | 0 |
| 32 | J002 / r1 | qwen2.5-coder:14b | `a34bf14e197f` | planner_missing_contract_masks_host_scope_violation | 0 |

All eight qwen2.5-coder:14b trials have the same first rejection and then fail host scope after adding a contract. All six qwen3 planner failures have an inactive-role mismatch: e.g. `No UI changes required` is outside `_no_change_goal`'s accepted prefixes. Some also omit a required contract; one already supplies a contract. Three of these six initially propose unauthorized paths; all six do after correction. Thus 11/14 initial rejected plans and 14/14 corrected rejected plans violate host scope. The two initial plans that pass stay inside host scope. These are overlapping observations, not additional trial counts.

Fourteen trials terminate in planner correction exhaustion. Ordinals 6 and 26 reach backend workers and one structural repair each, then reject unresolved anchors. They record a failed `external_full_gate_prerequisite` sentinel, not execution of frozen JUnit or full Gradle. No Hive trial produces changed files, reaches frozen acceptance, or runs the full gate. No Hive provider call is recorded as a local runtime failure; this does not establish adequate model context. All candidates retain the baseline hash. No evidence here supports diagnosing a parser incompatibility or a deterministic acceptance failure.

All correction calls report 2,050 input tokens at runtime context length 4,096 despite prompts of 20,478–21,145 characters. Both workers also report 2,050. This is evidence of a possible context-delivery bottleneck, not proof of which instructions the model actually retained. Provider code sends full text and no explicit `num_ctx`; effective token sequence is not preserved.
