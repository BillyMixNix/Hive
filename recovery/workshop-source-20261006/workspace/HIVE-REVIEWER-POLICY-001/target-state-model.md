# Target state model

The authoritative projection is `workshop/hive_review.py:state`. It reads immutable host verification results, independently validated semantic output, prior controller errors, real changed files/manifests and host policy. It does not apply files and does not treat its presentation flags as proof of current filesystem integrity.

| Dimension | States / meaning |
|---|---|
| `verification_status` | passed, failed, not_run; derived from the host result and individual checks |
| `semantic_review` | Disposition, validated decision or null, raw/repair response, exact provider failure or validation error, evidence digest |
| `review_disposition` | approved, rejected, unavailable, invalid, not_required, not_run |
| `candidate_disposition` | verification_failed/not_run; blocked_by_policy for independent controller/manifest/no-edit blockers despite a PASS; otherwise verified_review_<disposition> |
| `human_review_eligible` | Eligible for the ordinary explicit human-approval workflow; never grants write authority |
| `promotion_authorization` | not_authorized, human_approved, blocked |
| `promotion_blockers` | Independent gates, external-candidate restriction, required independent review or semantic veto |
| `promotion_decision` | Recorded only on explicit apply approval after guards; records model-review substitution and exact staged-manifest identity |
| `ready` / legacy `status` | Derived presentation; new apply path recomputes policy and rechecks the stage/source, scope and ownership |

With real edits, valid manifests and no other host blocker:

| Verification | Semantic review | Ordinary human-review eligibility | Promotion without explicit approval |
|---|---|---|---|
| failed / not_run | any | false | forbidden |
| passed | approved | true | forbidden |
| passed | rejected | false; candidate and concerns preserved | forbidden |
| passed | unavailable | true; no model decision | forbidden |
| passed | invalid | true; invalid raw output preserved, no valid model decision | forbidden |
| passed | not_run | false | forbidden |
| passed | not_required | false in this policy; no opt-out is implemented | forbidden |

External candidate-only policy always prevents the ordinary approval/apply workflow. A host `require_independent_review=True` obligation requires an actual approved review; human approval cannot waive it. There is no semantic-rejection override. The API/UI expose this explicit policy input; integrations must set it when task/policy requires independent review. No model or natural-language heuristic decides authorization policy.

Malformed/wrong-type approval cannot become **model approval or promotion authorization**. It can become an explicitly labeled invalid review eligible for human handling after independent gates pass, as required by the invalid-review policy. This distinction resolves the apparent conflict between invalid-review presentation eligibility and forbidding truthiness-based eligibility.

Apply requires exact `human_approved=True` even for direct core calls. It rechecks the policy, forbids external candidates, rejects failed gates/earlier errors/no edits, rechecks role and host scope, verifies the full staged-source digest and per-file base/stage manifests, snapshots, writes atomically, then verifies again. Failed post-apply verification records a separate failed result and rolls back; it does not rewrite the earlier passing verifier record or model opinion.

Reviewer provider exceptions are recorded in `semantic_review.failure`, not the common worker/controller error list. Syntax failure has one evidence-preserving formatting repair. Parseable schema violations are immediately invalid. Evidence loss/change before repair is invalid with no second call. Failure of the repair provider is unavailable, with initial malformed output retained. Confidence and issues are shown to the human; no confidence threshold or inferred issue severity is introduced.

Historical replay is a pure projection. For `4574db69cea0` it reports both:

- Actual external policy retained: **verified / review unavailable / external candidate-only / not promoted**.
- Explicit hypothetical ordinary-Workshop policy projection: **verified / review unavailable / human-review eligible / not authorized / not promoted**.

The latter is the requested policy counterfactual, not a removal of the actual candidate's external restriction. Historical source, run JSON, verification and classification remain unchanged.
