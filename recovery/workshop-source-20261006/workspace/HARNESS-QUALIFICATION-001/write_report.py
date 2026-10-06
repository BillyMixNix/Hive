"""Qualification report from current evidence only; no historical rescoring."""
from qcommon import *
def main():
    audit=read(HERE/'evidence/final-audit.json');matrix=read(HERE/'evidence/nfrt-preflight/matrix.json');dry=read(HERE/'evidence/scripted-cell/qualification.json')
    trials=read(HERE/'evidence/controls/results.json');comp=read(HERE/'evidence/controls/comparison.json')
    run=read(HERE/'evidence/scripted-cell/run.json');row=read(HERE/'evidence/scripted-cell/aggregate-row.json')
    tests=audit['unit_tests'];unitrows=[]
    import xml.etree.ElementTree as ET
    unitroot=ET.parse(HERE/'evidence/final-unit-tests.xml').getroot()
    for c in unitroot.iter('testcase'):unitrows.append({'name':c.get('name'),'classname':c.get('classname'),'failed':c.find('failure') is not None or c.find('error') is not None})
    save(HERE/'evidence/unit-case-index.json',unitrows)
    table='\n'.join(f"| {r['label']} | {'FAIL' if r['counts']['failures'] else 'PASS'} | {r['counts']['tests']} | {r['counts']['failures']} | {r['counts']['errors']} | {r['counts']['skipped']} | {r['seconds']:.3f} | {str(r['timed_out']).lower()} |" for r in audit['real_controls'])
    scopes='\n'.join(f"| {r['task']} | {'; '.join('`'+p+'`' for p in r['authorized_write_scope'])} | {'yes' if r['compatible'] else 'no'} |" for r in matrix['tasks'])
    criteria='\n'.join(f"| {name.replace('_',' ')} | {'PASS' if ok else 'FAIL'} |" for name,ok in audit['criteria'].items())
    checks=dry['canonical_verifier_result']['checks'];frozen=next(c for c in checks if c['name']=='frozen_junit_acceptance');testrows=frozen.get('tests',[])
    drycounts={k:sum(t.get(k,0) for t in testrows) for k in ('tests','failures','errors','skipped')}
    transient=read(HERE/'evidence/scripted-cell/measurement/1/candidate.json')
    changed_files=[p.name for p in sorted(HERE.glob('*')) if p.is_file()]
    report=f'''# HIVE-FACTORIAL-003-HARNESS-QUALIFICATION-001

**Classification: {audit['classification']}**

**Harness qualification: {'PASS' if audit['harness_qualified'] else 'NOT ESTABLISHED'}. Future J001–J004 factorial readiness: {'READY' if audit['factorial_ready'] else 'NOT READY'}.**

The repaired observation path preserves the real verifier's behavior in the tested conditions. No model inference, factorial trial, production change, timeout change, test change, NFRT-policy change or promotion occurred. The existing NFRT attestation remains incompatible with three task scopes, so no new factorial may begin under the current policy.

## 1. Invalid prior study

HIVE-FACTORIAL-003 remains permanently `EXPERIMENT_INVALID`: zero valid completed cells, one compromised cell and fifteen unstarted cells. It was not resumed, rescored or replaced. Its original executors and evidence remain byte-identical. The candidate used for control B comes from the earlier independently completed run `4574db69cea0`, not from the compromised FACTORIAL-003 cell.

## 2. Harness/production boundary

All repair and qualification files are new files in `HARNESS-QUALIFICATION-001/`. Production runs directly from the frozen `HIVE-FACTORIAL-003/repaired-workshop/` tree, with Python bytecode writes disabled. The production inventory contains {audit['production_files_checked']} files; its original tree hash remains `{FREEZE['source']['tree_hash']}`.

[harness-scope.md](HARNESS-QUALIFICATION-001/harness-scope.md) separates measurement code from frozen production. [harness-inventory.json](HARNESS-QUALIFICATION-001/evidence/harness-inventory.json) enumerates every historical harness file, function, class, line and hash. No planner, worker, reviewer, provider, production verifier, schema, source-integrity routine, task, frozen test or promotion policy was modified.

## 3. Exact defects

The prior recorder passed `kind` both positionally and by keyword to `event(kind, **data)`. That raised before the wrapped verifier call. Its unfinished row lacked `host_elapsed_seconds`, which later aggregation indexed unconditionally. Instrumentation was therefore visible to Hive as a verification exception, and result collection subsequently crashed.

The earlier frozen-test setup API mistake is also avoided: the new cell setup calls existing `freeze_junit_tests(candidate, specs)` and `store_frozen_junit_tests(specs, run_dir)` separately, preserving exact test hashes and content-free metadata.

## 4. Harness repair

`recorder.py` supplies one reusable wrapper for targeted and full verifier seams. Event names are positional-only and distinct from `verifier_kind`. Every fallible measurement step—clock, candidate capture, event writing, result copying and result persistence—is guarded separately from the single underlying call.

The wrapper returns the original verifier result object, never a synthetic verdict. It re-raises the original verifier exception object. Ordinary recorder failures enter a separate in-memory `MEASUREMENT_FAILURE` ledger. The verifier still runs, and failed writers are not recursively invoked to report their own failure. Writers receive copies of result data.

`collect_records` treats missing/invalid timing, partial rows and absent outcome observations as explicit measurement errors. It retains known timing totals without claiming complete timing and supplies no software verdict. `cell_harness.collect_cell` preserves Hive's native result separately and disallows study scoring of qualification runs. Measurement failure must disqualify an observation at the driver boundary; it is not injected into Hive's verifier path.

The old executors remain immutable and unsafe to reuse unchanged. A future authorized study must use the repaired components and its own frozen, qualified driver. This qualification does not silently deploy or resume an executor.

## 5. Wrapper equivalence contract

[wrapper-contract.md](HARNESS-QUALIFICATION-001/wrapper-contract.md) defines argument identity, return identity, exception identity/type/message, real-verifier versus measurement side effects, event ordering and incomplete-evidence handling. Timing equality is not required. Wrapper traceback frames may differ; exception semantics must not.

Native verifier behavior remains authoritative. Returned FAIL stays returned FAIL; returned timeout stays a timeout report; a raised exception or raised timeout remains an exception until the unchanged production caller handles it. Empty, null, malformed and extended fixtures pass through untouched; the recorder never repairs or authenticates them.

## 6. Deterministic wrapper tests

Final qualification suite: **{tests['tests']} passed, {tests['failures']} failures, {tests['errors']} errors, {tests['skipped']} skipped**. [JUnit evidence](HARNESS-QUALIFICATION-001/evidence/final-unit-tests.xml) and [case index](HARNESS-QUALIFICATION-001/evidence/unit-case-index.json) preserve every case.

Coverage includes PASS, FAIL, exceptions, raised/returned timeouts, the exact historical event collision injected as a writer failure, clock/capture/result-writer errors, missing and invalid durations, partial rows, unexpected fields, null/empty/malformed return fixtures, uncopyable objects, writer mutation attempts, repeated calls, positional/keyword candidate capture, seam restoration and full controller rollback/finalization. No test changes a production file.

## 7. Sentinel invocation proof

Six direct/wrapped sentinel probes cover targeted/full wrappers × return/exception/timeout. Each records a unique underlying marker, one direct reference call and exactly one additional underlying call through the wrapper. Arguments retain identity; return or exception objects retain identity. Start/finish events and timing exist, and there is no second wrapped invocation. [sentinel-proof.json](HARNESS-QUALIFICATION-001/evidence/sentinel-proof.json) contains the counters and marker evidence.

## 8. Real verifier A/B qualification

Both controls use the actual frozen `hive.targeted_verify` entry point with the same external context that Hive establishes, exact baseline-origin metadata, host-stored frozen tests, approved image and NFRT configuration. Each invocation has a fresh isolated stage, private verifier cache and new native evidence directory.

A is the unchanged frozen baseline. B is the preserved candidate from run `4574db69cea0`, file hash `b8a17817ccbf0846cfb4e765f5b530b4790e8c5dcdf6fef16a02d19a0f35a4d3`, previously established as passing frozen J001 acceptance. Historical results are expectations only; every displayed result below comes from a new actual verifier invocation.

| Control | Current frozen result | Cases | Failures | Errors | Skipped | Host seconds | Timed out |
|---|---|---:|---:|---:|---:|---:|---|
{table}

Within each pair, candidate hashes, frozen-test hashes, top-level result structure, check names/results, exit code, timeout state, case counts, failure identities/messages and acceptance mismatch details agree. Variable paths, timestamps, process/container IDs and logs are excluded from the equality projection. Full raw results remain preserved. Source hashes before/after and frozen-artifact checks establish unchanged source/integrity.

Every run has exactly one native verifier invocation, one Gradle target invocation and one JUnit-report collection. Invocation files and native process-exit events prove actual execution; wrapper events alone were not accepted as proof. See [comparison.json](HARNESS-QUALIFICATION-001/evidence/controls/comparison.json) and [results.json](HARNESS-QUALIFICATION-001/evidence/controls/results.json).

The baseline pair failed `truncationNeverSplitsAPair()` in both runs. The B pair passed all three cases. No previous PASS was reused. These are fixture-verification results, not autonomous software successes. The 240-second deadline, offline mode, `--rerun-tasks`, `--no-build-cache`, pinned JDK/image, attested private seeding and fresh compilation are unchanged.

## 9. Exception/timeout qualification

Controlled verifier fixtures exercise the exact installed targeted/full wrapper path with normal FAIL, raised error and raised `subprocess.TimeoutExpired`. The original exception objects and messages are preserved. A real short-lived subprocess timeout is also tested. No 240-second real-verifier budget is reduced or increased by that unit fixture; it tests Python exception transport separately.

The production interface may itself return a structured failed report for its internal errors. That existing behavior is untouched. The wrapper does not introduce an exception-to-FAIL conversion. Measurement exceptions never replace the verifier's result/exception and are classified separately.

## 10. Rollback/isolation

The two deterministic full-controller fixtures exercise a failed targeted result with working and deliberately broken measurement writers. Both invoke the underlying verifier once, return normal correction feedback, reject a repeated proposal, roll back the stage, record semantic review and create an aggregate row. Writer-error text is absent from the native Hive run/errors. Hooks are restored after each use.

The real scripted cell additionally proves rollback after an actual frozen test failure. Its transient candidate hash was `{transient['candidate_sha256']}`. Final stage and untouched candidate origin both match baseline `{FREEZE['baseline']['sha256']}`. Frozen tests are stored outside the editable tree. No apply/promotion call occurs.

## 11. NFRT task-scope matrix

The existing attestation hash remains `{FREEZE['nfrt']['sha256']}`. Its only independently mutable source is `SnapshotFormatter.java`.

| Task | Authorized write scope | Existing NFRT attestation compatible? |
|---|---|---|
{scopes}

Each row combines static scope comparison with the actual `configured_seed` validator on a fresh baseline copy containing harmless comments in the authorized files. J001 is accepted; J002–J004 fail closed with `NFRT reconstruction input changed`. These probes are not compiled and are not software-task trials. The attestation is not broadened and no unverified fallback is added. [Matrix and diagnostics](HARNESS-QUALIFICATION-001/evidence/nfrt-preflight/matrix.json).

**The future four-task factorial is NOT READY.** A separately justified policy must cover each task's source scope before a new study is frozen.

## 12. Scripted full-cell dry run

One complete cell used scripted planner/worker/reviewer JSON, the normal frozen Hive controller and the real isolated targeted verifier. Provider entry points were disabled. The planner contract was a canonical single-owner fixture; the worker replayed the archived, known-failing TRANSITION-003 implementation. This is an explicitly scripted qualification fixture, not task inference or a new autonomous attempt.

The observed path was: fresh trial/candidate creation → valid plan and ownership → scoped staged edit → real targeted verifier → **{drycounts['tests']} frozen cases, {drycounts['failures']} failures, {drycounts['errors']} errors, {drycounts['skipped']} skipped** → normal worker correction → scripted identical proposal rejected → stage rollback → full gate skipped by unchanged prerequisites → scripted semantic rejection → finalized run and aggregate row.

Native invocation count: **1**. Recorder invocation count: **1**. Measurement status: `{row['measurement_status']}`. Model calls: **0**. The full Gradle gate was not needed for this deliberately failing qualification fixture and was not represented as passed. [Dry-run proof](HARNESS-QUALIFICATION-001/evidence/scripted-cell/qualification.json), [native run](HARNESS-QUALIFICATION-001/evidence/scripted-cell/run.json), [aggregate row](HARNESS-QUALIFICATION-001/evidence/scripted-cell/aggregate-row.json).

## 13. Integrity audit

Final audit: **{audit['production_files_checked']} frozen source files unchanged; {audit['prior_files_checked']:,} prior evidence entries unchanged**. Baseline, all four frozen tests, pinned verifier image, approved dependency cache and NFRT attestation revalidated. All control candidate and origin hashes remained unchanged; the scripted stage was rolled back to baseline. No historical classification changed. [final-audit.json](HARNESS-QUALIFICATION-001/evidence/final-audit.json).

## 14. Files changed

Only new qualification files and evidence were created. The repair itself is `recorder.py` plus its integration in `cell_harness.py`. Supporting files are `qcommon.py`, `scripted_fixture.py`, the three `test_*.py` modules, `sentinel_proof.py`, `run_controls.py`, `nfrt_preflight.py`, `run_dry_cell.py`, `post_controls.py`, `seal_before.py`, `audit_after.py`, `write_report.py`, scope/contract/matrix documents and generated evidence. The requested report is at the workspace root. Existing FACTORIAL-003 and production files were not edited.

## 15. Qualification decision

| Criterion | Result |
|---|---|
{criteria}

Final classification: **{audit['classification']}**. Harness-specific equivalence and integrity criteria {'passed' if audit['harness_qualified'] else 'did not all pass'}. All four task scopes were preflighted; their incompatibility blocks the future factorial independently of wrapper qualification.

## 16. Remaining blockers and limits

J002–J004 are incompatible with the existing NFRT source attestation. Resolving that requires a separate evidence-backed policy task; it was not attempted here. A future study must use a fresh identifier and explicit authorization. FACTORIAL-003 must never be resumed at cell 2 or relabeled valid.

This qualification establishes the tested in-process observation boundary, not immunity to fatal process termination, resource exhaustion that prevents Python execution, permanently hung writers or external file mutation. It does not qualify model/provider reliability or estimate software-task success. Only the actual targeted verifier was exercised with Docker; the full wrapper shares the tested implementation and has deterministic seam/exception coverage, but no separate real full-gate control was run. No factorial or model invocation is automatically scheduled.
'''
    path=ROOT/'HIVE-FACTORIAL-003-HARNESS-QUALIFICATION-001-REPORT.md';path.write_text(report,encoding='utf-8')
    save(HERE/'evidence/report.json',{'at':stamp(),'classification':audit['classification'],'harness_qualified':audit['harness_qualified'],'factorial_ready':audit['factorial_ready'],'report_sha256':sha(path),'model_calls':0,'factorial_trials':0,'promotion_calls':0})
    print(path,flush=True)
if __name__=='__main__':main()
