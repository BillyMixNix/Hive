# Hive public contract repair — offline result

**The revised controller rejects the known input-mutation approval path when the caller declares input preservation.**

Three saved top-k patches are rejected using only their existing public tests and the new observer. All still pass the original public assertion, but the observer measures that the caller’s values list changed. The baseline and lesson patches are identical bytes, so these represent two distinct defective implementations. The pre-existing correct reference passes.

| Saved condition | Public tests | New input check |
|---|---|---|
| baseline | Passed | Rejected: values changed |
| lesson | Passed | Rejected: values changed |
| neutral | Passed | Rejected: values changed |
| Correct reference | Passed | Passed |

The real repair gate rejects and rolls back the bad proposal. Reviewer PASS and an already-complete task state cannot override it, and final validation rechecks the current candidate. The original separate acceptance oracle is retained. Resuming with a weaker contract is rejected. A full-adapter replay of the earlier successful capacity repair still completes using its nine recorded actions; it is a deterministic regression test, not a fresh model result.

Validation: **199 tests passed, 2 skipped, 5 additional subtests passed**, including 19 new tests. New coverage exercises aliases, helper calls, exception returns, local copies, permitted internal cache changes, missing observations, unsupported values, timeout, immutable public tests, policy changes and controller integration. Machine-readable evidence and source hashes are in report.json and pytest.xml.

**No new model requests or API charges.** The cumulative conservative bound remains **$3.4695976 of the original $5**. Earlier lesson-study scores and frozen runtime files remain unchanged.

This is an engineering correction to an explicit public input contract. It does not establish learning gain, automatically infer requirements, enforce arbitrary natural-language contracts, or expand the controller’s repair choices. Its evidence concerns supported final argument values on observed public-test calls; unseen inputs and adversarial code are outside this result.

Implementation, usage and limits: ../../CONTRACT_REVIEW_REPAIR.md.
