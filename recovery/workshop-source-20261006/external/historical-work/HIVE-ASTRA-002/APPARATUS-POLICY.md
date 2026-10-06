# HIVE-ASTRA-002 apparatus policy (defined before any 002 model result)

## Historical boundary

HIVE-ASTRA-001, including both freeze revisions and every raw trial artifact,
is immutable historical evidence. Its eight direct controls are apparatus-invalid:
the single complete-snapshot text field exceeded the Agents API per-string
limit before session creation. They are not Astra task failures or Hive wins.

## Direct-control context, version 1

`direct_context.py` is the only selector. It is deterministic, read-only, and
does not plan, decompose, edit, verify, review, or repair. The exact task text
remains verbatim. Source selection is based on repository paths, Java type and
method declarations, and lexical overlap with the task; no benchmark-task ID,
observed outcome, or acceptance assertion participates in ranking.

1. Enumerate regular UTF-8 source/config/docs in sorted repository-relative
   order. Reject linked/special paths, secrets, binaries, caches, generated
   state, and frozen acceptance sources. Record every eligible/excluded file
   and pruned subtree with a reason.
2. Build a sorted path-and-symbol repository index, bounded to 24,000 chars.
   Rank eligible files by exact filename stem, path-token, declaration-token,
   then capped text-token matches. Use path order as a stable tie-breaker.
3. Include up to 24 relevant files. A fitting file is included whole; larger
   files use scored line windows with line ranges and a 90,000-char per-file
   limit. Every omitted or partial file has an explicit reason and source hash.
4. Cap the entire context at 320,000 chars and the one Agents input text field
   (instructions + verbatim task + context) at 400,000 chars. The field cap is
   far below the observed 1,048,576-char provider maximum. If it cannot fit,
   fail before any API request; do not blindly trim the tail.

The direct agent gets one coding turn and returns a unified diff. It gets no
Hive planner, worker split, observation tools, obligation ledger, targeted
correction, reviewer, or autonomous repair. Both conditions use the same
baseline, frozen acceptance tests (verifier-only), and sealed full gate.

## Outcome classes

- `VERIFIED_SUCCESS`: frozen acceptance and full sealed gate passed.
- `MODEL_TASK_FAILURE`: model output or candidate failed a functioning task
  gate (including malformed/non-applicable diff, missing method, compile/test
  failure); no infrastructure cause is established.
- `VERIFIER_INFRA_FAILURE`: sealed gate could not complete due verifier runtime,
  resource, Docker, approved-cache, or dependency infrastructure failure.
- `PROVIDER_INFRA_FAILURE`: provider transport/service/quota/access failure
  prevented a model turn or continuation.
- `HARNESS_FAILURE`: request construction, input size, parsing/accounting, or
  experiment driver failed independently of model task performance.
- `FALSE_ACCEPTANCE`: a condition claimed ready/verified despite failing one
  required sealed gate. This is a stop condition.
- `INVALID`: integrity/freeze/containment evidence is missing or violated, or
  disposition cannot be assigned without guessing. This is a stop condition.

Classification never overwrites raw provider, model, or verifier artifacts.
Absent token usage and provider billing remain unknown, not zero.

## Validation-only provider limitation

The public Agents sessions API documents session creation with initial input;
for environment `none`, input is required and begins a turn. It does not
document a validation-only/dry-run endpoint. Therefore no live request with a
representative input is permitted in this apparatus-only phase. Local tests
must validate schema shape and the strict field-size bound. This limitation
must be reported, not treated as a successful provider validation.
