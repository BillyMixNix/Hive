# Controlled local diagnostic results

Both diagnostics completed with the unchanged frozen baseline, J001 task and exact write scope, qwen2.5-coder:14b digest `9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849`, pinned verifier image `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`, and approved offline cache `e5a7c314b902`. Model tier stays local, temperature 0.1, output caps and token/wall budgets match the factorial. No source, test, cache or verifier promotion occurs.

| Revision | Run | Calls | Wall seconds | Worker calls | Result |
|---|---|---:|---:|---|---|
| 1 | `8aa64e4e455d` | 5 | 550.348 | backend, tests | MODEL_TASK_FAILURE; workers reached through a flawed overlapping plan; invalid escalation responses |
| 2, final | `75280298dd02` | 2 | 302.841 | none | MODEL_TASK_FAILURE; duplicate ownership retained after correction; rejected before dispatch |

Neither run produces an edit or reaches executable deterministic verification, frozen acceptance or the full Gradle gate. Neither is applied. All baseline/candidate/stage fingerprints remain identical. Revision 1's failed prerequisite sentinel is not an executed gate. The final repair has **not demonstrated valid live planner-to-worker progress**. Synthetic valid-plan regression dispatch is separate evidence.

The first run exposed an existing ownership-validation hole, documented in [live-revision1.md](live-revision1.md). Revision 2 closes that hole, tests its rejection and correction behavior, and reruns the controlled diagnostic. This is an adaptive two-revision investigation, not a two-replicate reliability comparison. The second run's model adds an interface contract but leaves the duplicate assignment; its first diagnostic includes both defects. The final correction schema permits empty contracts if the redundant role is removed. The model does not take that valid route.

Reproduction command for the completed final diagnostic was `python -u HIVE-TRANSITION-001/live_diagnostic.py 2` from the task workspace. The script refuses an already-existing evidence directory; do not delete or overwrite it to rerun. The original factorial batch entrypoint is never invoked. `diagnostic_runner.py` copies the frozen runner with study-label, import and source-path adaptations; `diagnostic_environment.py` points to the repaired source and original approved offline environment. The final entrypoint also records outgoing model prompt/schema and returned raw text without changing provider arguments.

Evidence: [comparison](evidence/live-comparison.json), [final preflight](evidence/live-revision2/preflight.json), [final run](evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/run.json), [raw result](evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/result.json), [first request](evidence/live-revision2/model-boundary/01/request.json), [correction request](evidence/live-revision2/model-boundary/02/request.json), [corrected raw response](evidence/live-revision2/model-boundary/02/response.json), [final identity check](evidence/final-source-identity.json).
