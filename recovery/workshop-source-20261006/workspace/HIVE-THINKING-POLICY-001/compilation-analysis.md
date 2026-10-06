# Why the first five prospective edits do not compile

Read-only analysis requested during the frozen six-cell study. No new model call, candidate modification, verifier run or production repair is part of this analysis. Later cells continue under the existing freeze.

## Direct cause: invalid Java declaration placement

| Prospective cell | Historical paired cell | Observed operation | Where the method actually lands | Result |
|---|---|---|---|---|
| 1: J004 r1 | 3 | Two `insert_after_anchor` operations | Inside the component lists of two multiline record declarations, before the remaining parameters and opening body brace | 40 compiler errors; no JUnit execution |
| 2: J003 r1 | 6 | `insert_after_anchor` after `notIntegrated(String reason) {` | Inside the existing method body | 7 compiler errors; no JUnit execution |
| 3: J003 r2 | 8 | The same method-header anchor | Inside the existing method body | 7 compiler errors; no JUnit execution |
| 4: J002 r2 | 9 | `replace` whose `find` is only the opening method header | The replacement supplies a complete method but leaves the original body after it, at class level | 17 compiler errors; no JUnit execution |
| 5: J004 r2 | 12 | Two `insert_after_anchor` operations | Same invalid positions within record component lists as cell 1 | 40 compiler errors; no JUnit execution |

The applied source in the second J003 replicate contains:

```java
public static <T> Observation<T> notIntegrated(String reason) {    public <U> Observation<U> map(java.util.function.Function<? super T, ? extends U> mapper) {
```

The new method is nested inside another method. In J004, `public int ...` instead appears between record parameters. A leading newline would change formatting, not the invalid grammatical location.

J002 demonstrates that disabling only literal-anchor insertion would not eliminate this class. Its exact replacement target is `public static boolean canSatisfy(List<List<Integer>> matchingSlots, Map<Integer, Integer> counts) {`, but its replacement includes the whole method through a closing `}`. The preserved original body follows at lines 36–45 of the applied file. The shared mechanism is selecting a declaration header fragment as though it were the whole member.

The actual first-applied files and compiler stderr are preserved under each trial's `verifications/1/applied-source/` and `verifications/001-result.json`. These are transient candidates subsequently rolled back, not accepted implementations.

## What Hive does, exactly

`workshop/hive.py:_prepare_agent_edits` resolves a unique literal anchor and constructs `old.replace(anchor, anchor + insertion, 1)`; for replacement it uses `old.replace(find, replacement, 1)`. It does not interpret "after this method header" as "after the entire method", expand a match to its enclosing member, or move an insertion into a record body. In-memory replay of the recorded operations reproduces all seven affected files in the first five trials exactly. There is no observed corruption, relocation or newline stripping by transport/execution.

`workshop/hive_edits.py:supported_operations` gives Java exact replacement, creation and literal-anchor insertion; it explicitly has no Java symbol resolver. `validate_transition` parses Python and JavaScript/HTML but has no Java branch. Its successful Java return therefore does not establish valid Java syntax. Scope and exact-match checks pass; the unchanged compiler is the first Java syntax/type gate. The verifier correctly rejects the results.

## Was the model told the boundary semantics?

Yes. The exact initial wire requests contain both:

- "a unique literal anchor when it does not split a declaration"
- "do not add a declaration after a decorator/function header"

These originate in `workshop/hive_protocol.py:worker_edit_contract` and `WORKER_RESPONSE_CONTRACT`. Exact replacement is available as an alternative, but it still requires a correctly chosen source span. The observed errors cannot be explained by a controller translating a valid "insert after complete member" instruction incorrectly: the model requested literal text operations at the invalid positions/spans.

This supports a concrete model action-selection failure and an interface limitation: the Java action contract leaves grammatical placement to the model, while its host checks prove literal uniqueness rather than a valid Java member boundary. It does not establish that no valid edit was expressible.

The full original content of every edited file occurs in the actual initial and correction wire requests for all five prospective cells and both historical J003 controls. No owned-source truncation marker occurs. These requests specify `num_ctx=12288` and `truncate=false`. Missing source or a controller-generated abbreviated method header is therefore not the observed cause. This is a sent-input check, not a claim to inspect the model's internal attention.

## Why the correction did not recover

All five normal targeted correction requests include emitted compiler errors and the previous proposal. All five corrected responses retain exactly the same edit payload. Cells 1–3 change their summaries; cells 4–5 repeat the entire response byte-for-byte. Hive's repeated-proposal guard rejects those payloads before a second verifier invocation. A summary claiming "correct syntax" did not change the code or its insertion point.

The actual correction generation schemas equal their respective initial schemas. `anchor`, `find`, `insert` and replacement content remain free string fields; they are not enums/constants containing the previous proposal. The schema allows a different edit in the same scope. Repetition is therefore not forced by a frozen previous-answer schema. This does not claim all model reasoning/attention or correction-interface limitations have been excluded.

### Measured correction limitation: first compiler diagnostic is omitted

`workshop/hive.py:_targeted_diagnostic` preserves structured check outcomes but bounds strings by taking their **tail**, initially the last 1,600 characters, within a 6,000-character serialized budget. The omission is explicitly marked; the JSON is complete. However, compiler errors are not selected structurally. In all five prospective corrections this removes the first emitted Java error and its direct location, leaving later cascading errors. This is separate from the cause of the initial malformed edit.

| Cell | First emitted error | Delivered in correction stderr? | Distinct file/line/message triples emitted / delivered |
|---|---|---|---|
| 1 | ExecutionContext.java:19: record components cannot have modifiers | No | 34 / 5 |
| 2 | Observation.java:20: illegal start of expression | No | 4 / 2 |
| 3 | Observation.java:20: illegal start of expression | No | 4 / 2 |
| 4 | IngredientAllocation.java:36: illegal start of type | No | 14 / 4 |
| 5 | ExecutionContext.java:19: record components cannot have modifiers | No | 34 / 5 |

Counts deduplicate repeated Gradle/compiler messages; they are not total compiler error counts. The reconstruction reads actual process-output events and compares them with the parsed diagnostic object in the correction wire request. Both historical J003 controls had just one distinct compiler error, which survived transport; their revised proposals still failed. Thus tail-only diagnostic transport loses useful evidence, but preserving the first error alone is not proven sufficient for repair. The current full source and previous operation still made the placement mistake inferable. Do not claim either complete diagnostic delivery or demonstrated causation of repeated proposals.

## Independent historical support

FACTORIAL-003R1 cells 5 and 7, both qwen2.5-coder:14b J003 runs, selected the same `notIntegrated` opening-header anchor and also failed compilation. Their corrections switched to replacing just that header, leaving the old method's trailing body behind; compilation failed again. The placement/fragment-boundary class therefore existed before this thinking-policy intervention and across model configurations.

FACTORIAL-003R1 cell 2 is a different compile-error class: an `int` code point was passed to `Character` APIs requiring a `char`. Do not collapse every compiler failure into anchor placement.

## Sixth cell: a contrasting valid boundary, but incorrect behavior

Prospective cell 6 (historical cell 15, J002 r1) replaced the opening method header with that header plus new statements, without adding a closing brace. The existing body therefore remained inside its original method. This candidate **compiled**, executed all three frozen cases and failed all three. Its normal correction changed the implementation by removing an early negative-count check that preceded the null-value check. The revised candidate compiled again and failed the same three cases. No full gate was eligible.

All three emitted case names, exception types and failure messages survived into this correction request. This differs from the compiler-diagnostic tail loss in cells 1–5. The revised payload is materially different, but the measured behavioral result did not improve. See `evidence/correction-semantic-assessment.json` and both actual verifier results in `evidence/trials/06-J002-r1-qwen3_8b/verifications/`.

The sixth cell confirms that the existing literal operation language can express a syntactically valid Java change. It limits the claim: the interface is not incapable of all valid edits. The demonstrated five-cell failure is choosing the wrong source boundary, not a universal compiler or executor defect. The historical counterpart also compiled but failed two of three cases before its correction timed out; this prospective candidate has a worse initial case count (three failures). Fresh plans/outputs differ, so this is an observed paired quality difference, not isolated causal proof about optional thinking.

## Limits and next boundary

Fixing placement alone is not proof of a correct candidate. By source inspection, prospective J003 r1 also uses an undeclared method type parameter `U`; r2's unavailable branch passes a `T` value into a result typed `Observation<U>`. J002 r2 compares primitive `int` locals to `null`. The observed compiler stopped on earlier syntax errors, so no post-placement compiler or behavioral result is claimed. No candidate was manually repaired to test these observations.

The supported next investigation is Java declaration-boundary expression/validation and evidence-driven edit revision, including preservation of the first relevant compiler diagnostic. An exact unique string is not necessarily a legal declaration boundary. A general future repair would need to demonstrate valid member placement without task/file whitelists, preserve all scope checks and still run compilation and frozen tests. No such repair is installed during this study.

The strongest falsifiers would be an applied file differing from the requested splice, missing boundary warnings/source in the actual wire request, or a preserved compiler result showing a different first failure. The read-only replay and prompt checks in `evidence/compilation-causal-replay.json` reproduce all six initial proposals and the two historical controls, with full source grounding confirmed. They do not prove that disabling thinking caused or did not exacerbate other quality defects.
