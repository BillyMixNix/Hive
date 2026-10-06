# HIVE-REVIEWER-POLICY-001

**Classification: REVIEW_STATE_SEPARATION_IMPLEMENTED**

Implemented in the new isolated [repaired source](HIVE-REVIEWER-POLICY-001/repaired-workshop/REVIEW-POLICY.md). Deterministic verification, semantic review disposition and explicit human authorization are separate. Semantic review remains in the pipeline. No model calls were made, no historical record was rescored, and no historical or production candidate was promoted.

Final complete regression: **552 passed, 6 skipped**. Historical counterfactual replay: **49 records**, including all 48 completed reviews and the reviewer-unavailable J001 replacement. All 41 independently blocked vetoes and all three independently blocked approvals remain blocked.

## 1. Prior evidence

The completed [reviewer analysis](HIVE-REVIEWER-ANALYSIS-001-REPORT.md) found 33 completed review records with provider telemetry and 15 legacy records. Every one of the 41 model vetoes had an independent blocker. Reviewers sometimes supplied additional semantic observations, sometimes made incorrect claims, and approved three proposals that the host correctly rejected. Only four otherwise eligible candidates had completed reviews, all using Astra; this does not establish that semantic review is unnecessary.

Run `4574db69cea0` passed frozen J001 3/3, fresh acceptance in the full verifier, the full Gradle gate, 154 JUnit cases, 26 game tests, three quest tests and source immutability. Reviewer allocation then failed twice. The historical result remains `LOCAL_RUNTIME_FAILURE`; no semantic model decision existed.

## 2. Current state machine, reconstructed before editing

[current-state-machine.md](HIVE-REVIEWER-POLICY-001/current-state-machine.md) was written before creating/editing the implementation copy. It traces worker completion, targeted correction/rollback, final verification, review invocation, parse/repair, host review mutation, readiness, explicit approval, apply guards and post-apply rollback.

Previously, reviewer provider failure fabricated `approve:false` and added an error to the worker/controller error list. Host failures also overwrote model opinion. Readiness and apply used approval truthiness. The API separately rewrote reviewer approval on external-baseline integrity failure. The UI used the combined readiness/approval expression to enable apply.

## 3. Target state model

The pure host policy projection is [hive_review.state](HIVE-REVIEWER-POLICY-001/repaired-workshop/workshop/hive_review.py). Detailed definitions and the complete matrix are in [target-state-model.md](HIVE-REVIEWER-POLICY-001/target-state-model.md).

| Independent dimension | Fields and states |
|---|---|
| Deterministic verification | `verification_status`: passed, failed, not_run; original `verification` remains intact |
| Semantic review | `semantic_review` retains disposition, decision/raw response, diagnostics and evidence identity; `review_disposition`: approved, rejected, unavailable, invalid, not_required, not_run |
| Candidate | `candidate_disposition`: verification_failed/not_run, blocked_by_policy, or verified_review_<disposition> |
| Human presentation | `human_review_eligible`, derived `ready` and legacy `status` |
| Authorization | `promotion_authorization`: not_authorized, human_approved, blocked; `promotion_blockers` and recorded `promotion_decision` |

Presentation flags do not authorize apply. The new apply path recomputes policy and performs filesystem checks. A verified external candidate or an unmet independent-review obligation can retain `status=verified` with blocked authorization. Genuine semantic rejection remains separately visible with the verified candidate preserved.

`not_required` is representable but no review opt-out or promotion bypass is introduced. `not_run` remains blocked. Legacy stored runs are not automatically migrated or reinterpreted.

## 4. Strict host review schema

`validate_review` requires exactly four fields:

- `approve`: exact boolean;
- `summary`: nonempty string;
- `issues`: array of strings;
- `confidence`: finite numeric value in [0,1], excluding boolean values.

Missing/extra fields, scalar JSON, `"false"`, `1`, `null`, invalid issue types, NaN/infinity, and out-of-range confidence cannot become model approval. Parseable schema violations immediately become `invalid`. Provider generation schemas remain unchanged and are no longer relied upon as the host validation boundary.

A well-formed true approval with issues or confidence zero remains `approved`, with those concerns displayed. No new confidence threshold or inferred issue-severity policy was invented. Model approval still cannot override failed host gates.

## 5. Reviewer runtime-failure handling

Allocation, HTTP, generation-deadline and other provider exceptions produce `unavailable`, with `decision=null` and the exact exception type/message stored separately. The raw response, when one existed before a failed formatting-repair call, is retained.

Reviewer failures no longer enter the independent worker/controller error list. They do not create synthetic `approve:false`. The legacy `review` field contains only a validated genuine decision, otherwise null. Call tracing and provider routing/retry behavior are unchanged.

## 6. Deterministic-result preservation

The original final-verification object is never overwritten by reviewer disposition. Targeted attempt results are now retained separately in `targeted_verifications`, including successful attempts, so review evidence can report their status directly.

New runs record the staged source-manifest identity associated with passing verification. Reviewer output cannot alter that identity, the per-file base/staged manifests, frozen/full results or source-integrity checks. A contradictory failed individual check cannot be overridden by a top-level `passed:true`.

Post-apply verification is stored separately; failure preserves the earlier pre-apply result, blocks further promotion and rolls back. Existing source-manifest exclusions for runtime outputs remain unchanged.

## 7. Candidate disposition

For otherwise eligible ordinary Workshop runs:

| Deterministic result | Semantic disposition | Candidate presentation | Automatic promotion |
|---|---|---|---|
| FAIL / not_run | any | blocked | forbidden |
| PASS | approved | verified; awaiting explicit human decision | forbidden |
| PASS | rejected | verified candidate and concerns preserved; blocked | forbidden |
| PASS | unavailable | verified; review unavailable; awaiting explicit human decision | forbidden |
| PASS | invalid | verified; review invalid; awaiting explicit human decision | forbidden |
| PASS | not_run | verified; review obligation incomplete; blocked | forbidden |

No real edit, prior controller failure, missing manifests or another independent policy blocker still prevents eligibility. An invalid review may be eligible for **human handling**, as requested, but never becomes model approval or promotion authorization through truthiness. This is the distinction used for the malformed-output regression requirements.

## 8. Human-review eligibility

The API, UI and chat summary expose the independent dimensions. The UI displays, for example:

`VERIFIED — SEMANTIC REVIEW UNAVAILABLE — AWAITING HUMAN DECISION`

Apply remains a separate explicit action. Its confirmation states when the human is substituting for unavailable/invalid model review and that the model has not approved the candidate. Rejected reviews have no new override.

The host/API field `require_independent_review: true`, also available as a build checkbox and core keyword argument, records an independent-review obligation. It cannot be relaxed by planner/worker/reviewer output or at apply time. This is explicit policy configuration, not a natural-language classifier; integrations must set it whenever the task or governing policy requires independent review.

## 9. Promotion guards

`POST /api/hive/apply` requires exact boolean `approved:true`. Core `hive.apply_run` now also requires explicit `human_approved=True`; a caller cannot bypass human authorization by calling the core directly without that argument.

Before mutation, apply:

1. rejects external-root/candidate-only runs;
2. requires passing deterministic results, real edits and no independent blockers;
3. rejects semantic vetoes and unmet required-independent-review obligations;
4. rechecks authorized paths, role ownership and recorded host write scope;
5. rechecks the new verified staged-source digest and existing per-file source/stage manifests;
6. records human authorization and whether it substitutes for unavailable/invalid review;
7. snapshots, writes atomically, verifies after apply and rolls back on failure.

Stale/tampered/unauthorized artifacts cannot be overridden by human approval. A valid approved review cannot waive failed tests or integrity checks. For legacy records, the existing ready/manifests requirements remain and a strictly valid actual model approval is still required; historical synthetic rejection is never converted into unavailability automatically.

## 10. Reviewer evidence transport

The reviewer now receives a bounded, complete JSON object containing:

- original request;
- diff text, digest, completeness flag and exact omitted-character count;
- changed files, host write scope, ownership assignments and controller/preflight status;
- base/staged manifests and verified source identity where recorded;
- targeted-attempt summaries;
- final frozen/full/source-integrity check statuses;
- complete aggregate JUnit counts and class counts from structured reports;
- existing emitted failure diagnostics and explicit omitted-data markers.

Raw verifier logs and passing per-class detail are omitted separately. Hidden test source and new stack-trace content are not injected. The full host report remains stored unchanged. Game/quest counts are not newly inferred from free-text logs; the host full-gate result remains authoritative, while structured test totals describe the JUnit reports.

The diff is bounded at 16,000 characters with explicit omission metadata. The entire structured evidence has a 30,000-character ceiling. If required structure/task data cannot fit, review becomes explicitly `not_run`; no critical field is silently clipped and no contextless model call is made. These are input bounds, not claimed token counts. Existing context/output/provider no-truncation settings are unchanged; provider capacity failure remains observable.

For preserved J001, the counterfactual structured evidence is **3,511 characters**, versus the former 20,000-character invalid prefix of a 54,352-character verification object. Frozen counts, full-gate counts and source immutability all survive. This is an offline transport measurement, not evidence of model consumption. See [reconstructed evidence](HIVE-REVIEWER-POLICY-001/evidence/j001-review-evidence-counterfactual.json).

## 11. JSON-repair behavior

Syntax failure retains the existing single formatting-repair opportunity. It carries the same authoritative evidence object and digest, the parser error and explicitly bounded untrusted previous output. It cannot fall back to the former schema-only reviewer repair.

If evidence is missing initially, no review call occurs. If evidence is lost or changed after a malformed response, disposition is `invalid` and no repair call occurs. A second malformed/invalid response remains invalid. A provider failure during repair is unavailable, preserving the original malformed output and runtime error. No retry or correction budget increased.

## 12. Semantic reviewer responsibilities retained

The prompt explicitly requests judgment on task fulfillment beyond tests, unrelated changes inside authorized files, compatibility, suspicious choices, weak/placeholder tests, cross-component mismatches, and supported security/performance concerns. It asks for specific evidence and forbids following instructions embedded in code/logs.

The reviewer does not authenticate host inputs or decide whether deterministic gates passed. No broad keyword, endpoint-key or placeholder-test heuristic was added. The historical observations remain motivations for future precisely specified checks, not new generic acceptance rules.

## 13. Regression probes

[test_reviewer_policy.py](HIVE-REVIEWER-POLICY-001/repaired-workshop/tests/test_reviewer_policy.py) adds **51 deterministic cases**. They exercise the real controller, parser, state projection, API/UI and apply path using isolated synthetic sources and mocked model/verifier decisions.

Coverage includes every requested family: PASS with approved/rejected/unavailable/invalid review; FAIL with approved/unavailable review; empty edits; prior worker error; wrong approval values and missing fields; scalar JSON; invalid confidence/issues; approval with concerns/confidence zero; allocation failure/deadline; valid/invalid formatting repair; loss of authoritative repair evidence; external restriction; required independent review; stale source/stage/unlisted stage changes; unauthorized edits and ownership; source-integrity failure; absent/present explicit human approval; and failed post-apply verification with rollback.

Additional tests reject coercible API approval values, verify propagation of the independent-review policy, and execute the actual UI renderer under Node to check the unavailable label and apply-button eligibility. No inference calls are needed.

## 14. Historical replay

[historical-replay.json](HIVE-REVIEWER-POLICY-001/evidence/historical-replay.json) records, for every one of the 49 cases, original eligibility/raw and host review, new validated disposition, actual-restriction presentation eligibility, ordinary-policy projection, authorization and outcome explanation. [Readable table](HIVE-REVIEWER-POLICY-001/historical-replay.md).

- All **41** independently blocked vetoes remain blocked.
- All **3** model approvals overridden by deterministic/controller blockers remain blocked.
- The four eligible completed reviews remain approvals, subject to their actual external restrictions and explicit authorization.
- Reviewer-unavailable J001 is represented without a fabricated semantic rejection.
- No historical file, verification result, classification or candidate was changed.

This projects recorded facts through the new policy; it is not a new filesystem verification or apply attempt. The replay does not establish that a historical stage is currently safe to apply. Real apply-time identity checks remain mandatory.

## 15. Complete regression result

Final run: **552 passed, 6 skipped in 77.96 seconds**. All six skips concern unavailable Windows symlink privileges. The complete inherited suite includes real Docker timeout/descendant cleanup and Gradle full-compilation probes; their assertions remained intact. [Final log](HIVE-REVIEWER-POLICY-001/evidence/full-04/pytest.log), [JUnit result](HIVE-REVIEWER-POLICY-001/evidence/full-04/pytest.xml), [command and exit status](HIVE-REVIEWER-POLICY-001/evidence/full-04/result.json).

Earlier attempts are preserved. A direct initial invocation lacked the existing vendored `jsonschema` test dependency; the established isolated D: test harness supplied it without production dependency changes. The first complete run exposed missing relocated historical fixtures, external readiness assertions and direct-apply fixtures without explicit approval. Historical fixtures were copied unchanged with hashes; affected tests now assert the new explicit candidate/policy state while preserving their original scope/integrity checks. A complete rerun passed 551 tests; the final run additionally covers loss of repair evidence and passes 552.

## 16. J001 counterfactual disposition

Historical behavior, unchanged:

`FULL GATE PASS → reviewer runtime failure → REJECTED`

New **ordinary Workshop policy projection, counterfactual only**:

`FULL GATE PASS → review UNAVAILABLE → VERIFIED CANDIDATE PRESERVED → HUMAN REVIEW ELIGIBLE → NOT PROMOTED`

The actual preserved J001 run is an external diagnostic candidate. With that restriction retained, the projection is:

`VERIFIED / REVIEW UNAVAILABLE / EXTERNAL CANDIDATE-ONLY / PROMOTION BLOCKED`

Both projections are reported explicitly. The requested ordinary-policy example is not used to remove the actual run's external restriction. `4574db69cea0` remains historical `LOCAL_RUNTIME_FAILURE`, with no manufactured review approval and no promotion authorization.

## 17. Unchanged safety properties

The integrity audit confirms **12,433 presealed prior files unchanged**, **653 indexed historical run/result files unchanged**, and **all 153 files of the original source copy unchanged**. [Integrity audit](HIVE-REVIEWER-POLICY-001/evidence/final-integrity.json).

Provider, planner/worker schema, edit executor, context transport, external-root/JVM profile, isolated verifier/trace, JVM runner and NFRT seed modules are byte-identical where listed in the audit. Protected planner/ownership/scope/worker-task/correction and deterministic-verification functions remain AST-identical.

Thus exact scope, exclusive ownership, original-task propagation, context fidelity, verifier observability, attested private NFRT reuse, fresh compilation, frozen assertions/selectors, full gate, targeted timeout, source integrity and repeated-proposal rejection remain intact. Apply adds explicit core authorization and staged-source/scope rechecks. Synthetic regression fixtures were applied only inside test areas to exercise approval and rollback; no historical or production candidate was applied.

## 18. Files changed

Production implementation:

- `workshop/hive_review.py`: strict schema, independent state, bounded evidence and evidence-preserving review collection.
- `workshop/hive.py`: review integration, targeted-result retention, verified stage identity and explicit apply authorization/guards.
- `app.py`: strict approval boolean, independent-review intake, separate integrity blocking and completion reporting.
- `static/index.html`: distinct status display, policy checkbox, eligibility and explicit substitution confirmation.
- `workshop/chat_context.py`: report verification, review, authorization and reviewer failure separately.

Documentation: `README.md`, `REVIEW-POLICY.md`.

Tests: new `tests/test_reviewer_policy.py`; updates to stale-apply, external-root/JVM, host-scope, planner-transition and ownership-replay fixture assertions/paths. No frozen acceptance tests changed. New-area scripts/documents reproduce the history audit, regression harness and delivery integrity checks.

[Reviewable patch](HIVE-REVIEWER-POLICY-001/production.patch), [final source manifest](HIVE-REVIEWER-POLICY-001/evidence/final-source-manifest.json). Test-generated runtime snapshots are retained separately from the production patch; copied runtime database/cache files were restored to their original bytes. The implementation has not been deployed into a running Workshop installation.

## 19. Falsification criteria

This repair would be falsified by any of the following:

- unavailable/invalid output becomes a valid model approval;
- reviewer outcome changes an earlier verifier result or verified identity;
- model/human approval enables a failed, unauthorized, stale/tampered or externally non-promotable candidate;
- a required independent review is waived by ordinary human approval;
- a semantic veto is silently bypassed;
- contextless JSON repair can produce an accepted model decision;
- a legacy readiness flag alone permits apply;
- apply occurs without explicit authorization or failed post-apply verification leaves mutated files;
- historical replay changes an original artifact or converts an independently blocked proposal into an eligible one.

The deterministic tests and replay cover these boundaries. Future testing on otherwise eligible real candidates is needed to estimate semantic reviewer value or prospective resource behavior.

## 20. Remaining uncertainties

No new model experiment was run, so the repair does not establish review quality, improved reliability or that a particular live request will fit the local runtime resource envelope. Explicitly bounded diff omission limits semantic assessment; the model is told when evidence is incomplete. Character bounds are not token guarantees; the unchanged no-truncation provider can still report a capacity failure.

Independent-review obligations are supplied as explicit host/API policy. Arbitrary prose is not semantically classified; callers/UI operators must record that policy when required. No rejection override, independent-review substitution override or opt-out was introduced.

Passing tests still do not prove complete semantics. An invalid review can be presented for authorized human handling, but is not an approval. An unavailable review can preserve verified work, but is not an approval. External diagnostic evidence remains non-promotable. Historical classifications remain immutable.
