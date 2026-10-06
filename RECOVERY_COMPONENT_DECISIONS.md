# Earlier lineage decisions

The RC1 authority source is the FACTORIAL-003R1 Workshop controller identified in `RECOVERY_CONTROLLER_LINEAGE.md`. These earlier code lines are preserved in the parent recovery commit. They are not imported merely because they exist.

| Lineage | Source evidence | Decision | Reason |
|---|---|---|---|
| Sept. 8 repair executive / Sept. 9 state packets | repository `HiveAgent.py`, `planner.py:PlannerAgent`, `executor.py:ExecutorAgent`, `HiveStateManager.py`; predecessor branches recorded in `RECOVERY_MANIFEST.md` | A — superseded for Workshop coding authority; preserve history | Different controller/state contract; current `workshop/hive.py` has source-backed planning, stage, verifier and review path. No selected Workshop import points to this executive. |
| `hive-reference-model` | `recovery/reference_model/model.py:EventLedger`, `AuthorityPolicy`, `PromotionDecision`; `representation.py` | D — research/history | Executable reference model is separate from Workshop and not used by the selected run path. Its vocabulary is not evidence of live authority. |
| GROW failure-driven Workshop | `recovery/lineage/grow/grow/kernel/promotion.py`, `Docs/GROW_CONTINUATION.md` | D — research/history | Opt-in self-improvement and transfer rules belong to a different experiment; no demonstrated selected-controller dependency. |
| Project-state ledger | `recovery/lineage/project_state/hive_reference/project_state.py:ProjectLedger`, `Docs/PROJECT_STATE.md` | D — preserved research; possible future read-only adapter | Ledger hashes show source presence, not semantic truth; no Workshop import or tested bridge. |
| Orchestration cockpit | repository `hive_cockpit.py` and `RECOVERY_MANIFEST.md` | D — history | Sept-era UI/orchestration, no selected Workshop runtime import. |
| Self-diagnosis / speculative refinement | candidate and reference research sources noted in `RECOVERY_MANIFEST.md` | D — history | No frozen causal test establishing it as Workshop authority. |
| Later `think:false` policy | `W/HIVE-THINKING-POLICY-001/repaired-workshop/workshop/thinking_policy.py` and its diagnostic report | D — experiment only | Worker completion improved in six timeout paths, but 0/6 frozen/full-gate successes; RC1 uses preceding 003R1 policy. |

Here `W/` expands to `recovery/workshop-source-20261006/workspace/`. The distinctions A–D are the question's supersedes/depends/adapter/history categories. No earlier component is required as a runtime dependency by the selected source; no adapter is installed in RC1 merely in anticipation of later work.
