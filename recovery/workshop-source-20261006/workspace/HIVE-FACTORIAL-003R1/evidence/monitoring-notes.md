# Live monitoring / analysis notes

The frozen serial executor was launched once. No production or frozen harness file has been changed after freezing. `report_study.py` is postprocessing only, added after the freeze, never imported by execution and never used to construct model context.

Cell 1 (`bc33f077e5b9`): first valid plan, sole backend worker, one edit; targeted PASS (209.820 s), full verification PASS (273.783 s), semantic review approved. Three model calls, 947.316 s trial wall time. No correction or promotion.

Cell 2 (`b719455d5468`): first valid plan, backend edit, actual compiler failure (compileJava FAILED), zero fresh frozen cases, targeted result false (135.932 s). Normal targeted correction repeated the effective failed proposal; `RepeatedFailedProposal` rejected it before another verifier invocation. First reviewer response empty at 1536 output tokens; normal evidence-preserving JSON repair produced rejected review. Five model calls, 1805.570 s trial wall time. The frozen collector labels the gate failure FROZEN_ACCEPTANCE_FAILURE; final analysis must explicitly distinguish this pre-test compilation failure from an executed failing assertion. Do not edit the raw row or rescore it.

Cell 3 (`091f5b539b27`): valid first plan; backend generation timed out at 900.019 s, no worker response/edit/verifier. Semantic review rejected. LOCAL_RUNTIME_FAILURE, three calls, 1342.282 s. No replacement. Cell 4 started in frozen order.

All subsequent facts must be read from the preserved executor/events/raw results, not inferred from these interim notes.

Cell 4 (f7b1ecbf9816): two planner attempts, duplicate ownership persisted (ExecutionAssessment assigned to both backend/tests); no worker. Frozen collector labels PLANNER_FAILURE because its text heuristic does not match 'assigned to both'. Final descriptive taxonomy must identify ownership failure from exact native diagnostics without changing the raw ledger, success score, or frozen code. 470.655 s; review not_run. Cell 5 (3026e044d3c1), J003 r1 qwen2.5, started at 04:38:21 UTC.
