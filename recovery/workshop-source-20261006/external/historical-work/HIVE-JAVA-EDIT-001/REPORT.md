# HIVE-JAVA-EDIT-001 — action-space repair

The completed HIVE-LOCAL-001 study was not changed or rerun. Its `raw_results.json` remains 16 trials, 0 applied, with the original frozen classifications (13 model-task failures, 3 verifier-infrastructure failures). Original raw-results SHA-256: `d72667f3b0eb02d09e3b84a30966ee968d3cff772f4a19d4ce3f8439bd8a013d`. Original freeze SHA-256: `1173ddc3b3810fe36d5527a2e9ce75ea0c5b34c7ce6d06b693d298e3715750f9`.

## Change

The worker's response schema and prompt now list edit operations for each exact owned file. Java receives only the executor's existing exact `replace`, `create`, and `insert_after_anchor`; Python/JavaScript symbol insertion and HTML element insertion remain available only where executable. A host preflight rejects a provider's unsupported operation/file combination after ownership validation but before reading or writing source. No Java symbol resolver was added; the strict edit validator and other safety gates were not relaxed. See `EDIT-ACTION-SPACE.md` for the full language map.

The copied local-study classifier now gathers failed targeted-check evidence, prefers concrete Java compiler/JUnit failure evidence over broad infrastructure text, ignores raw model output for classification, and no longer treats a routine Gradle “dependency cache” notice as an infrastructure fault. Portable fixtures and tests reclassify T002, N006, and N008 as model-task failures for **diagnosis only**; the original frozen output is unchanged.

## Verification

- `python -m compileall -q .`: passed.
- Focused edit-protocol and structural-repair tests: 66 passed.
- Copied harness/classifier tests: 9 passed, including original-artifact hash checks.
- Complete combined Workshop + harness suite: 391 passed, 6 skipped.
- Separate no-model synthetic Java/JavaScript edit smoke: 2 passed.
- No cloud/model calls, benchmark rerun, production promotion, or candidate application.

## Offline replay analysis

The preserved 16 runs contain 28 structural-edit rejection records: 27 `unsupported_language` for Java `insert_after_symbol`, and one `anchor_resolution` failure. The latter proposal also contained a Java symbol edit, but the exact replacement failed first. Four original Java proposals were structurally executable and reached targeted verification: T002 backend `replace`, and T005/N006/N008 tests `create`. All four remained rejected by targeted checks or later run gates; they are **not** counted as successful. This counterfactual action-space analysis does not change the frozen 0/16 study result.

Remaining limitation: Java edits are exact-text only. The host does not parse Java syntax before targeted Gradle verification; an exact edit can still produce incorrect or uncompilable Java, as T002 demonstrated.
