# Verification, semantic review and human authorization

Hive records independent `verification_status`, `review_disposition`, and
`promotion_authorization` fields. `candidate_disposition` describes the result;
`human_review_eligible` describes eligibility for the ordinary manual apply workflow.
The legacy `ready`/`status` fields are presentation only. Apply recomputes policy
and checks the exact staged artifact; neither field authorizes a write.

Semantic review is always attempted when the pipeline reaches that phase and
bounded authoritative evidence can be supplied. The reviewer assesses request
fulfillment beyond existing tests, compatibility, unrelated changes, weak tests,
integration concerns and supported security/performance risks. It cannot edit,
authenticate host evidence, waive deterministic checks or authorize promotion.

| Review disposition after passing deterministic gates | Ordinary manual operation |
|---|---|
| approved | Eligible for explicit human approval; never applied automatically |
| rejected | Preserve candidate and concerns; blocked; no rejection override introduced |
| unavailable | Preserve candidate and exact provider error; human may explicitly substitute |
| invalid | Preserve candidate, raw response and protocol diagnostic; human may explicitly substitute |
| not_run | Review obligation remains unmet; blocked |
| not_required | Representable for reporting; no opt-out or apply bypass is implemented |

Any deterministic failure, prior controller error, missing edit, source-integrity
failure or policy blocker prevents eligibility regardless of model opinion or
human approval. External-root/candidate-only runs remain non-promotable.

**Explicit independent-review obligation:** submit
`require_independent_review: true` to `POST /api/hive/build`, or set the “require
independent semantic review (no human substitution)” checkbox. Integrations calling
`hive.run_build` use the same boolean keyword. The host records it in `review_policy`;
workers and reviewers cannot relax it. It requires an actual valid approved semantic
review. Unavailable, invalid or rejected reviews remain blocked, even when a human
passes `approved: true`. There is no substitution override for this obligation.

This is an explicit policy input, not a natural-language obligation classifier.
Callers must set it whenever the task or governing policy requires independent
review. The default selects ordinary manually reviewed Workshop work. Do not rely
on the planner to infer or enforce this authorization policy from prose.

`POST /api/hive/apply` still requires the exact boolean `approved: true`; the core
`hive.apply_run` also requires `human_approved=True`. Unavailable/invalid review
substitution is recorded in `promotion_decision`; it never changes the model
disposition or fabricates model approval. Semantic rejection has no override.
Stale source/stage checks, scope/ownership checks, snapshots, post-apply verification
and rollback remain mandatory. New runs bind the complete staged source manifest
to verification and recheck it before apply. Legacy records are not migrated or
rescored; their apply path still requires a strictly valid actual model approval
and the original ready/manifests constraints.

Reviewer outputs must contain exactly `approve` (boolean), `summary` (nonempty
string), `issues` (array of strings), and finite numeric `confidence` in [0,1].
Boolean confidence, truthy strings/numbers, missing/extra fields and scalar JSON
are invalid. Issues and confidence are displayed; there is no invented confidence
threshold or issue-severity inference. A valid approval with concerns remains an
approval whose concerns the human can inspect.

The evidence object contains the original task, diff with explicit omissions,
changed files, host scope/ownership information, source/artifact identities,
targeted attempts, frozen/full verification summaries and complete aggregate case
counts. Raw logs are omitted with markers; existing structured runtime failure
messages are preserved. Hidden test source and stack traces are not added.
Structured JSON is never sliced. If the bounded evidence cannot fit, the review
is explicitly `not_run`; no critical task field is silently removed. Context and
output settings are unchanged and the provider still disables silent truncation.

Syntax failure permits the existing single formatting repair, carrying the same
authoritative evidence and its digest. Evidence loss/change blocks that repair
as `invalid`. A parseable schema violation is immediately `invalid`. Provider
failure, including during a formatting repair, is `unavailable`, with the original
invalid output and provider error retained separately. No retry budget is enlarged.

This policy does not establish model-review reliability or replace untested
semantic judgments with heuristics. It separates evidence, review and authority.
