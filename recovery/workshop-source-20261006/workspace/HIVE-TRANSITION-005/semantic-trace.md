# Requirement propagation

Exact copied requests, raw responses, normalized plan and correction record: [reconstruction artifacts](evidence/reconstruction). Original evidence remains unchanged.

| Requirement | original_task | planner_request | raw_planner_response | normalized_plan | worker_goal | worker_acceptance | interface_contract | initial_worker_prompt | correction_prompt |
|---|---|---|---|---|---|---|---|---|---|
| R1 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PARTIAL | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY |
| R2 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY |
| R3 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY |
| R4 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | ABSENT | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY |
| R5 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | ABSENT | ABSENT | ABSENT | ABSENT | ABSENT | ABSENT | ABSENT |
| R6 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PARTIAL | PRESENT_EQUIVALENTLY | ABSENT | PRESENT_EQUIVALENTLY | PRESENT_EQUIVALENTLY |
| R7 | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | PRESENT_EXPLICITLY | ABSENT | PARTIAL | ABSENT | PARTIAL | PARTIAL |

R1: Goal alone says handle pairs correctly; acceptance adds truncation semantics.

R2: Explicit in backend acceptance and both worker contracts.

R3: Explicit in backend acceptance and both worker contracts.

R4: Explicit in backend acceptance and both worker contracts.

R5: No ASCII compatibility statement/equivalent survives planner output or worker prompt. ASCII source examples are not a compatibility obligation.

R6: Preserve complete pairs during truncation is equivalent to not introducing a broken pair. Explicit no-unpaired wording remains only in global acceptance, which is not rendered.

R7: Global acceptance explicitly prohibits exceeding MAX_LINE_CHARS; worker criteria only names truncation to MAX_LINE_CHARS, leaving suffix-inclusive bound less explicit.

No interface contract was needed for one active owner. Inactive UI/tests own no files. Normalization preserved the model strings; it did not remove R5. Global acceptance is stored but not included in `_worker_prompt`; backend acceptance is included. The original request is not independently rendered. `_intent_envelope` recognizes specific cross-layer HTTP/UI requests only; its requirements list here is empty.
