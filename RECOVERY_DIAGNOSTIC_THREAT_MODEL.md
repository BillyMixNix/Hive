# RC1 verifier-to-model trust boundary

The frozen JUnit source is mounted only inside the isolated verifier. An application-source candidate can nevertheless influence JUnit XML, exceptions and process output, and may be able to read protected source during test execution. Those strings are human audit evidence, never model context.

The recovered unsafe worker path is `hive.py:targeted_verify` → `_targeted_diagnostic` → `_targeted_repair_prompt` → `run_build.observed_call` → agent. `observed_call` stores the prompt before the agent adapter sees it. The reviewer path is `hive_review.evidence` → `summarize_verification` → `collect` → `prompt`, including format repair. Both originally carried free-form fields from `jvm_runner.py` JUnit XML and `hive_verifier.py` stdout/stderr. The copied historical modules remain byte-identical; recovery-only hooks replace the two upstream projection functions during bounded canonical runs, and the downstream guard accepts only hash-registered prompts. Raw verifier records remain in run evidence for audit.

| Source/field | Trust class | Model transport |
| --- | --- | --- |
| Host task, frozen write scope, expected case count | HOST_TRUSTED | Allowed; task and scope are independently supplied by the host |
| Verifier `passed`, fixed check result, host timeout | VERIFIER_DERIVED_STRUCTURED | Allowed as strict booleans/fixed labels after validation; cannot change verifier truth |
| JUnit XML numeric case/failure/error/skip counts | VERIFIER_DERIVED_STRUCTURED, candidate-influenced | Prohibited: even bounded integers can encode candidate-controlled data; retained only in human audit evidence |
| JUnit classname, case name, message, exception, stack, XML body/attributes | MIXED / PROTECTED / CANDIDATE_CONTROLLED | Prohibited |
| stdout, stderr, Gradle text, compiler diagnostics, trace event text | MIXED / CANDIDATE_CONTROLLED | Prohibited |
| Verifier `error`, `report_error`, acceptance mismatch strings, controller `errors` | MIXED / UNKNOWN | Prohibited |
| Candidate diff for semantic review | CANDIDATE_CONTROLLED, public authored code | Allowed only as bounded candidate artifact, never as a verifier diagnostic; semantic reviewer needs it |
| Candidate file names in verifier output | CANDIDATE_CONTROLLED | Prohibited; only host write scope may be shown |
| Prompt trace | RECORDED MODEL CONTEXT | Safe only when the upstream projection hook has run; future reuse of raw run JSON is unqualified |
| Legacy chat context/state packets/resume from raw `run.json` | UNKNOWN | Outside the bounded RC1 replay; prohibited as model input |

Planner correction occurs before targeted verification in this source path; no post-verification JUnit input to it was found. Its ordinary task/source context is separate. The reviewer JSON-format repair reuses the same safe evidence object. Previous reviewer output and parser error remain untrusted; they cannot introduce raw verifier evidence through this path.

The boundary intentionally does not claim to make a semantic reviewer immune to prompt injection in a candidate diff. The claim is narrower: **arbitrary protected/candidate-emitted verifier text cannot be transported as a diagnostic**. External consumers that import raw audit records or run state into later prompts remain unqualified and are excluded from RECOVERY-002.

Falsification: show any frozen-test/JUnit/Gradle sentinel in a correction or reviewer request, any raw verifier field in the structured schema, or a forged diagnostic changing the host's verification decision. Any such result revokes readiness.
