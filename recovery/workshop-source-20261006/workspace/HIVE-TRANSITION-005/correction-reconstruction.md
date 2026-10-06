# Historical correction reconstruction

Run `45ad10e6dd49`, request 03. Exact outbound body, original/revised raw response, original proposal and token measurements are copied under [evidence/reconstruction](evidence/reconstruction). The preserved correction was a timeout correction, not a response to the later frozen behavioral failures.

- Classification: targeted verification failed after the 240-second subprocess timeout.
- Supplied verifier evidence: [exact diagnostic](evidence/reconstruction/historical-correction-diagnostic.txt). No partial stdout/stderr survived the historical timeout.
- Test names, assertion messages, expected/actual values: absent; no behavioral result existed then.
- Source: same complete baseline-owned source as initial worker prompt, after rollback.
- Original task: absent as an independent authority; same lossy planner-derived goal/criteria/summary.
- Previous proposal: supplied in full (212 generated tokens; below 16,000-character cap).
- Revision instruction: explicitly requires an effectively different complete replacement; byte-identical canonical proposals fail as RepeatedFailedProposal.
- Schema: unchanged role-scoped worker schema in exact wire JSON, supports implemented/escalated response; observations prohibited in targeted correction.
- Input accounting: initial worker 5,512 tokens; correction 6,007. Both match preserved rendered counts. num_ctx=12,288; truncate=false; output cap=6,000; correction full-cap slack=281 tokens.
- Corrected response: byte-identical edit proposal. Host rejected it before another verification and kept rollback intact.

Historical adequacy: **CORRECTION_EVIDENCE_INCOMPLETE** for code repair (and original-task semantics were lossy). A timeout without phase/output cannot identify a Java behavioral defect. Repetition violated the revision instruction, but does not demonstrate inability to learn from an assertion the model never received.

Prospective transport defect: `_targeted_repair_prompt` slices the first 6,000 characters of arbitrary report JSON. [Real-report replay](evidence/reconstruction/correction-clipping.json) demonstrates that the structured JUnit counts after verbose stdout/stderr disappear and JSON is cut mid-field. `_reports` parses JUnit testcase failure elements but retains only counts, discarding existing runtime failure messages. No hidden source is needed to transport emitted test names, exception types and failure messages. Proposed repair is bounded, prioritized runtime diagnostics with explicit omission markers; no test source or stack trace is sent.
