# Structured diagnostic provenance

The machine schema is [RECOVERY_DIAGNOSTIC_SCHEMA.json](RECOVERY_DIAGNOSTIC_SCHEMA.json). `hive_canonical.diagnostics.project` is the sole recovery projection. `validate` rejects extensions and wrong types. The recovery hooks run before the legacy controller records prompt telemetry. `_protected_agent_call` independently requires an exact prompt hash registered by the safe correction/reviewer constructor. A missing or invalid projection prevents the model call; it cannot turn FAIL into PASS.

| Field | Producing code / input | Domain and maximum | Candidate/protected influence |
| --- | --- | --- | --- |
| `schema_version` | Recovery constant | integer 1 | None |
| `phase` | Recovery caller | TARGETED, FULL | None |
| `verifier_status` | `hive_review.verification_status`, strict report topology | PASSED, FAILED, TIMED_OUT | Candidate affects verifier outcome, not text |
| `failure_class` | Fixed mapping from failed host check IDs and timeout | Six fixed enum values | Candidate affects verifier outcome, but XML count/text fields are never consulted; `FROZEN_ACCEPTANCE_FAILED` means the fixed frozen gate failed, not that a particular case ran |
| `checks[].check_id` | Exact check-name mapping; unknown names become UNKNOWN | Seven fixed enum values, ≤100 rows | Unknown/candidate names cannot enter field |
| `checks[].passed` | Strict boolean from verifier check | boolean, ≤100 | Candidate affects outcome |
| `host_expected_cases` | `hive_jvm.freeze_junit_tests` host manifest | 0–10000 or null | Frozen host input; protected case names excluded. Reported XML counts are **not** transported |
| `compilation_status` | Recovery constant | UNKNOWN | No independently authenticated compiler state exists in the result; Gradle task marker is not proof |
| `timeout` | Verifier `timed_out` boolean in fixed check detail | boolean | Candidate may cause timeout, not add text |
| `correction_allowed` | Recovery policy from phase and failed status | boolean | Never alters normal retry budget |
| `allowed_write_files` | Canonical host `CandidateSpec`, `_safe_scope` and Gradle source-only guard | ≤100 canonical paths | Host-owned, not copied from JUnit or candidate output |

The raw verifier result is preserved in `targeted_verifications`, `verification`, and verifier diagnostic files for a human auditor. The review object is a distinct `SafeReviewEvidence` instance, with its evidence hash registered in the active recovery context. It includes the legitimate host task, bounded candidate diff, host-scoped changed-file list, safe targeted/full projections and verified stage hash. It excludes raw `run.errors`, XML class/case names, assertion/exception text, stack traces, logs, raw XML and raw JUnit reports. The candidate diff is intentionally model-visible semantic review material; it is not a verifier diagnostic.

One limitation remains explicit: fixed check booleans are downstream of candidate execution. Numeric XML values stay in human audit evidence and cannot serve as a covert model channel. Fresh verifier result, source integrity and frozen gate continue to decide acceptance. `compilation_status=UNKNOWN` avoids claiming that a Gradle marker proves javac entered. Empty/malformed XML yields a generic verifier failure or failed projection, not a fabricated PASS.
