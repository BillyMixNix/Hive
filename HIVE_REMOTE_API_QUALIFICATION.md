# HIVE-REMOTE-API-QUALIFICATION-001

**Result: bounded provider infrastructure implemented and offline-tested; remote Hive coding apparatus remains UNAVAILABLE.** No real API request, candidate generation, Gradle execution, remote deployment, promotion, RECOVERY-002 launch or historical-evidence modification was performed. New branch: `remote/hive-api-qualification`, based on `63c0281672e130baceafe62b61901e17a73c7fb0`.

The tested implementation commit is `ae5a9074250172ffd40b0df795f9ec5201bad7ae`. Machine evidence is preserved in [preflight](remote/evidence/preflight/HIVE_REMOTE_API_QUALIFICATION.json), [prepared J001](remote/evidence/prepare/J001-PREPARED.json), [missing-key smoke](remote/evidence/smoke-unavailable/HIVE_REMOTE_API_SMOKE.json), [validation records](remote/evidence/VALIDATION.json), and the [hash index](remote/evidence/INDEX.json). The smoke's `API_MODEL_NOT_CONFIGURED` value is an explicit placeholder; no real model or API request was used. The publication commit adds these evidence files without changing implementation or historical apparatus.

## Apparatus findings

| Component / proof level | Observed classification and limit |
|---|---|
| Recovered controller | **EXACTLY_REPRODUCED source bytes**: all 42 canonical files match the unchanged 001C source manifest by path and SHA-256. This is artifact-backed source recovery, not behavioral replication. |
| Historical evidence corpus | Git tree `214a81054c99ec4a12db04f60d17bb25ec9011bb` unchanged. Recovery tree and historical tests remain untouched. |
| Frozen J001 baseline | Git tree `517e5cb3a523f944c68833b196bd511cbcd0fc07` unchanged. Its historical source hash is `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`. No new remote verifier baseline run. |
| Frozen acceptance | SHA-256 `80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159`; source remains outside model-visible baseline. Scope stays one ordinary Java source file. No test changes. |
| Docker/image | **UNAVAILABLE here**: no Docker executable, no exact image `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`. No independently verified remote registry source in recovery evidence. |
| Cache/build inputs/NFRT | **UNAVAILABLE here**: repository contains manifests, not approved approximately 1.4 GB payload; 4,866 selected payload files and 4,873-file sealed layout remain required. Transfer rights are unverified. No transfer attempted. |
| Container Java/Gradle | **UNAVAILABLE here**: cannot inspect actual runtime. Required historical values: Temurin 21.0.12.1+1 and Gradle 9.2.1. Exact Gradle ZIP was independently recovered in 001C; that alone is insufficient for the apparatus. |
| Host Python | **DIFFERENT_ENVIRONMENT**: Linux CPython 3.12.14, compared with sealed Windows CPython 3.13.14, DLLs, stdlib, package/import-path/startup identities. Installed test dependencies do not qualify it. |
| Network/isolation | Original verifier implementation preserved. No live Docker/network/cancellation/secret probe on this host; operational qualification is **UNAVAILABLE**. |
| Full apparatus | Neither byte-identical nor functionally reconstructed remotely. No clean-machine reproduction, cross-host apparatus replication or remote behavioral replication. |

The original 001C result remains **host-bound attested**, at its exact approved host/root/runtime, and ready for its separately authorized one-shot RECOVERY-002 envelope. This report grants no portability or cloud substitution. If the same image/cache are later hash-relocated, that proves those bytes and relocation only. A Linux Python layer would still be different. **FUNCTIONALLY_RECONSTRUCTED** is reserved for a separately documented apparatus that actually passes corresponding controls; it is not a synonym for dependency versions that look similar.

## Checks performed

- New tests: **30 passed, 10 subtests passed**, including call/token/dollar reservations, missing/invalid counts and usage, parallel calls, cancellation, secret-contaminated prompts/responses, safe exact HTTP evidence, no retry/fallback, immutable controller identity, preserved hidden-test boundary, blocked launch and manual/step-scoped workflow configuration.
- Combined new and unchanged recovery suite: **137 passed, 1 failed, 10 subtests passed**. The failed historical test is `test_unattested_python_import_path_fails_closed`: it expects `host Python runtime differs`, while this Linux host rejects earlier with `Python runtime is not the attested host installation`. The security boundary rejects the apparatus, but the test assertion fails. This is not reported as a passing recovery gate.
- The same single failure was reproduced in an untouched detached sparse worktree at `63c0281`, with the same Linux interpreter and test dependencies.
- Historical `recovery/rc1-replay/verify_source.py verify`: **FAILED** on both the new branch and untouched recovery anchor. Investigation found identical per-path records and file hashes, but different list ordering for `NFRT-SEED-POLICY.md`/`jvm_runner.py` and `LICENSE-acorn.txt`/`NOTICE.md`/`acorn.cjs` between Windows and Linux `Path` sorting. No recovery manifest or checker was changed. The new path-indexed identity check does not override this historical gate failure.
- `git diff` against the anchor for `hive_canonical`, `recovery` and `tests/recovery`: empty. The historical recovery tree and canonical Git tree remain unchanged. No hidden test was copied into a model-visible workspace.

These are infrastructure tests on the execution workspace, not evidence that GitHub Actions or a cloud VM has run this workflow. The workflow and artifact upload have not been dispatched. A real OpenAI key is absent, so a real provider smoke is not executed. Missing-key smoke evidence records zero requests/generation calls and **UNAVAILABLE**, not PASS. Synthetic HTTP mocks never establish account access or software correctness.

## Delivered and blocked work

Delivered: asynchronous provider protocol, OpenAI Responses adapter, unchanged local-provider wrapper and mock, exact request/response evidence, safe metadata, persistent token/call ledger, optional tariff reservation, manual GitHub workflow, source/environment inventory, prepared frozen J001 plan, secret-handling instructions and evidence retrieval instructions.

Blocked: a real cloud coding launcher. `require_remote_qualification` rejects even a forged successful JSON record. There is no unsafe fallback, generic remote-shell escape or switch that reuses RECOVERY-002. This follows the requested stop conditions: exact apparatus bytes/acquisition and legal transfer are unresolved, and the original Python/environment gates do not qualify Linux. A prepared task is available for review without enabling execution.

Smallest next step: determine an authorized source for the exact verifier image/cache/NFRT payload and resolve transfer rights. Then freeze and qualify a new remote apparatus with model-free failing-baseline and passing full-gate controls plus live isolation checks. Do not spend coding-model credits before that work. The provider connection smoke can be performed independently with one tiny public prompt.

## Answers

1. **Strong remote API inference:** implemented through the existing callable, without local inference. Live account/model access remains untested; no model alias is assumed.
2. **Hive without the user's computer:** remote infrastructure can run on GitHub after workflow/secret setup. Full coding execution is blocked until remote apparatus qualification. A dedicated cloud VM is the future coding apparatus choice, not an existing deployment.
3. **Remote verifier:** still **UNAVAILABLE**, not byte-identical or functionally reconstructed. Some source components are exactly reproduced; the full environment is not.
4. **Fair local/API comparison:** structurally possible through the same callable and frozen controller/task/verifier. It requires new paired trials with matched budgets, wrapper/format/temperature/reasoning policies and qualified apparatus. Historical factorial/Ollama calls used different provider policies and cannot silently become the local arm.
5. **Credentials:** excluded from prompts and evidence by tested provider boundaries; removed from provider-process environment; no credentials forwarded by the unchanged isolated verifier. Actual remote candidate/verifier isolation has not been live-tested. The trusted host administrator remains in the trust boundary.
6. **Usage/budget:** counts, returned usage, generation/API request counts, timings and unsettled reservations are preserved. Hard call/token limits are enforced before generation; missing usage halts. Optional dollar reservation depends on correctly supplied upper tariffs. Lost responses can carry unknown charges; no retry follows.
7. **First real launch:** resolve apparatus transfer/acquisition, qualify and review a new remote contract, pass tiny API smoke, freeze the exact model/configuration/budgets, then separately authorize one remote J001 run. The current coding command refuses execution. See `HIVE_REMOTE_API_REPRODUCE.md` for concrete setup and retrieval steps.
8. **Unproven:** actual API connectivity/model entitlement; GitHub workflow execution/artifact retrieval; remote Python reconstruction; legal artifact transfer; exact verifier/cache availability; remote targeted/full baseline controls; live isolation; controller behavior with a remote model; coding success; paired comparison.

Readiness values below distinguish code readiness from live apparatus qualification. Provider YES means implemented and offline-tested, not a successful real API smoke. Secret YES means the implemented credential boundary was tested; remote operational isolation remains unproven.

```text
REMOTE_MODEL_PROVIDER_READY = YES
REMOTE_HIVE_RUNNER_READY = NO
REMOTE_VERIFIER_QUALIFIED = NO
API_SECRET_ISOLATED = YES
READY_FOR_FIRST_CONTROLLED_API_HIVE_RUN = NO
```

## Public privacy redaction

Public publication was explicitly authorized after preparation of `c3a299c032decdec199d721592473a9bc67c5790`. The public snapshot removes private filesystem paths from captured command/trace metadata and host kernel/build details from two environment reports. Implementation bytes, test counts, failures, outcomes, frozen identities, budgets and token usage are unchanged. Evidence indices were recomputed for the redacted bytes; [the redaction record](remote/evidence/PRIVACY_REDACTIONS.json) preserves original and published SHA-256 identities. The original commits are retained locally as provenance references and are not ancestors of the public snapshot, so sensitive original metadata is not disclosed through Git history.
