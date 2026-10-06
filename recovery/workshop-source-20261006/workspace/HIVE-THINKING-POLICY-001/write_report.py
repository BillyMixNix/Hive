"""Completed-cohort report only; no changes to frozen execution or candidates."""
import statistics
from common import *

def main():
    summary=read(HERE/'evidence/analysis-summary.json');rows=read(HERE/'evidence/paired-analysis.json')
    audit=read(HERE/'evidence/final-integrity.json');lock=read(HERE/'FREEZE.json')
    assert summary['complete'] and len(rows)==6 and audit['passed']
    a=summary['aggregates'];t=a['transitions'];workers=[c for r in rows for c in r['workers']]
    tested_cells=sum(any(any(c['counts']['tests']>0 for c in v['checks']) for v in r['verification']) for r in rows)
    classification=sys.argv[1]
    assert classification in {'THINKING_POLICY_MECHANISM_SUPPORTED','THINKING_POLICY_USEFUL_IMPROVEMENT_SUPPORTED','THINKING_POLICY_QUALITY_REGRESSION','THINKING_POLICY_NO_MEANINGFUL_EFFECT'}
    proof=read(HERE/'evidence/capability/result.json');hist=read(HERE/'evidence/historical-calls.json')
    assessments={r['run_id']:r for r in read(HERE/'evidence/correction-semantic-assessment.json')['assessments']}
    repeats=sum(any(e.get('exception_type')=='RepeatedFailedProposal' for e in r['errors'] if isinstance(e,dict)) for r in rows)
    all_attempts=[at for r in rows for c in r['calls'] for at in c['attempt_details']]
    attempt_errors=[at for at in all_attempts if at['transport'].get('http_status',200)>=400 or at['stream_provider_errors'] or at['transport'].get('stream_error')]
    md=[f'# HIVE-THINKING-POLICY-001', '',f'Classification: **{classification}**','',
        f'Exactly six preselected fresh cells completed. Complete schema-valid worker responses were obtained in **{a["complete_structured_worker_response"]}/6 cells**; **{t["executable_edit"]}/6** produced executable scoped text edits, **{t["frozen_acceptance"]}/6** passed frozen acceptance, and **{a["verified_software_success"]}/6** passed the full required gate. No candidate was applied.',
        '', '## 1. Historical failure class', '',
        'FACTORIAL-003R1 remains immutable: 2/16 verified software successes. This experiment selected its qwen3:8b cells 3, 6, 8, 9, 12 and 15 because their backend generations exhausted the normal 900-second limit. Historical data is not rescored.',
        '', 'Four selected calls emitted only thinking content. Cells 3 and 12 began answer content around 862 and 880 seconds but did not finish. All six established HTTP 200 streams within approximately 8–16 seconds; those were active generations, not demonstrated startup/allocation failures.',
        '', '## 2. Stream reconstruction', '',
        'The complete per-call reconstruction, exact wire hashes, model digest, settings, terminal states and resource references are in [historical-timeout-reconstruction.md](HIVE-THINKING-POLICY-001/historical-timeout-reconstruction.md) and [historical-calls.json](HIVE-THINKING-POLICY-001/evidence/historical-calls.json). Character/channel counts are not token counts; interrupted historical streams lack terminal provider usage.',
        '', '**Denominator caveat:** 0/6 is completion of the six selected failed calls. Cell 15 timed out on correction after a completed initial worker and failed behavioral tests. Whole-cell historical any-worker completion, executable edit and targeted-verification reachability are each 1/6, not 0/6. Fresh whole cells can take different call paths.',
        '', '## 3. Provider capability proof', '',
        f'Two pre-edit non-task requests used the same synthetic arithmetic prompt and JSON schema, context 12288, output cap 6000, temperature 0.1, truncate=false and 900-second bound. Both returned complete valid JSON on the frozen digest. `think:true` emitted {proof["rows"][0]["thinking_characters"]} thinking characters and took {proof["rows"][0]["elapsed_seconds"]:.3f}s; `think:false` emitted {proof["rows"][1]["thinking_characters"]} and took {proof["rows"][1]["elapsed_seconds"]:.3f}s. The first also loaded the model; this is transport proof, not a controlled speed or task-quality comparison.',
        '', 'The installed provider advertises thinking capability but omits supported-value metadata. The measured template exposes an explicit Boolean switch. A host-owned capability profile therefore binds the exact digest, template hash and provider version, rather than treating every thinking model as switchable. [Probe evidence](HIVE-THINKING-POLICY-001/evidence/capability/result.json). API background: [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking).',
        '', '## 4. Transport implementation', '',
        '`providers.ollama_chat` accepts optional Boolean `think`; omission preserves the prior body and avoids capability requests. Explicit values require the host-attested identity to match local provider metadata before generation. Unsupported values/models or identity drift fail clearly. The selected value is placed at the top level of the actual request, recorded in returned metadata and retained unchanged across retries. No post-failure switching is implemented.',
        '', '## 5. Frozen role policy', '',
        'Only bounded structured ui/backend/tests calls for the proven qwen3 profile receive false, including structural and targeted corrections. Planner/reviewer and unrelated model/provider combinations retain omitted/default behavior. The decision depends on provider/model capability, role, schema and finite bounds, never a task ID, source filename, cell number, previous failure or desired solution.',
        '', 'Unchanged: qwen3 digest; context 12288; worker/planner/reviewer output caps 6000/2048/1536; temperature 0.1; truncate=false; normal two-attempt provider policy; 900-second generation setting; one planner/structural/targeted correction; 3600-second aggregate decision ceiling; exact scopes; 240-second targeted and 660/600-second full verifier bounds; offline pinned image/JDK; NFRT attestation; fresh compilation; rerun-tasks/no-build-cache; all acceptance assertions; reviewer and promotion policies.',
        '', '## 6. Regression results', '',
        'Complete source suite: **656 passed, 6 skipped**. The skips are inherited Windows symlink limitations. Qualified harness: **52 passed**. New tests cover true/false/default transport, unsupported/mismatched identities, exact wire fields, default preservation, same-body retries, provider/deadline failures and actual application worker/correction dispatch. Existing scope, context, ownership, semantic transport, verifier, NFRT, rollback, reviewer and promotion protections pass.',
        '', 'Initial test setup failures and their resolution are retained, including vendored test-only dependency/fixture relocation and the provider-history assertion updated for the intentional transport extension. No gate was weakened. [Implementation and test notes](HIVE-THINKING-POLICY-001/implementation.md), [complete JUnit](HIVE-THINKING-POLICY-001/evidence/full-regression-final/pytest.xml), [harness JUnit](HIVE-THINKING-POLICY-001/evidence/harness-tests.xml).',
        '', '## 7. Diagnostic freeze', '',
        f'Source tree SHA-256: `{lock["source"]["tree_hash"]}`. Original source SHA-256: `{lock["source"]["origin_tree_hash"]}`. Model digest: `{proof["digest"]}`. Provider: Ollama {proof["version"]["version"]}. [FREEZE.json](HIVE-THINKING-POLICY-001/FREEZE.json) contains byte inventories, exact task/test/baseline identities, image/JDK/Gradle identity, seed attestation, hardware, configuration and order. No frozen production or execution-harness file changed after task execution began.',
        '', '## 8. Six-cell design and isolation', '',
        'Historical relative order was preserved. Each selected condition received one fresh normal Hive execution from the unchanged baseline. No replacements, extra trials, warmups, model unload/reload, memory tuning, manual candidate fixes or promotion occurred. Hidden tests and previous candidates were not supplied as model context. The only pre-study inference was the two declared non-task probes.',
        '', '## 9. Per-cell generation and paired outcomes', '',
        '| Historical cell | Task / replicate | Historical selected worker result | Prospective worker times (seconds) | Historical frontier | New highest level |',
        '|---|---|---|---|---|---|']
    for r in rows:
        historical=next(h for h in hist if h['historical_cell']==r['historical_cell'])
        times='; '.join(f"{c['kind']}: {c['elapsed_seconds']:.3f} ({'complete' if c['response_complete'] else c.get('status')})" for c in r['workers']) or 'not reached'
        oldresult='correction timeout; initial worker completed' if r['historical_cell']==15 else 'initial worker timeout'
        md.append(f"| {r['historical_cell']} | {r['task_id']} / {r['replicate']} | {oldresult} | {times} | {historical['historical_frontier']} | {r['highest_level']} |")
    md+=['', f'All-worker call counts: {a["worker_call_counts"]["response_complete"]}/{a["worker_calls"]} complete; {a["worker_call_counts"]["schema_valid"]}/{a["worker_calls"]} parseable and schema-valid; {a["worker_timeouts"]} worker deadline failures. Median completed-worker logical-call duration: {a["median_completed_worker_seconds"]:.3f}s. Timing includes capability validation overhead; stream latency and provider-generated token accounting are recorded separately.',
        '', '| Cell | Call | Kind | First answer seconds | Generated tokens | Thinking characters | Parse/schema valid |', '|---|---|---|---:|---:|---:|---|']
    for r in rows:
        for c in r['workers']:
            at=c['attempt_details'][-1] if c['attempt_details'] else None
            first=at['channels']['content']['first_seconds'] if at else None
            md.append(f"| {r['historical_cell']} | {c['number']} | {c['kind']} | {first:.3f} | {c.get('output_tokens','unknown')} | {at['channels']['thinking']['characters'] if at else 'unknown'} | {c['parseable']} / {c['schema_valid']} |" if first is not None else f"| {r['historical_cell']} | {c['number']} | {c['kind']} | not observed | unknown | unknown | {c['parseable']} / {c['schema_valid']} |")
    md+=['', 'Generated-token counts are provider eval_count, not an independently tokenized answer count. No thinking content was observed for controlled worker calls; token totals can still include control tokens. All start/end times, request identities, attempts, complete responses and wire schemas are in [paired-analysis.json](HIVE-THINKING-POLICY-001/evidence/paired-analysis.json) and the referenced trial artifacts.',
        '', '## 10. Actionability and edit quality', '',
        f'{a["actionable_response"]}/6 cells returned an implemented response with schema-valid operations in scope. {t["executable_edit"]}/6 actually passed preflight and staged edits for verification. "Executable edit" means the text operation was executable, not that the resulting Java compiled. Malformed completed worker JSON: {a["quality"]["malformed_worker_responses"]}; schema-invalid worker responses: {a["quality"]["schema_invalid_workers"]}; unauthorized-operation responses: {a["quality"]["unauthorized_operation_responses"]}.',
        '', '## 11. Verification outcomes', '', '| Cell | Verifier calls | Calls failing compilation | Calls failing behavioral tests | Frozen JUnit result | Full gate | Review |', '|---|---:|---:|---:|---|---|---|']
    for r in rows:
        tested=any(c['counts']['tests']>0 for v in r['verification'] for c in v['checks'])
        acceptance='passed' if r['transitions']['frozen_acceptance'] else 'failed' if tested else 'not run: compilation failed'
        gate='passed' if r['transitions']['full_gate_passed'] else 'failed' if r['transitions']['full_gate'] else 'not run'
        md.append(f"| {r['historical_cell']} | {len(r['verification'])} | {r['quality_flags']['compilation_failures']} | {r['quality_flags']['behavioral_fails']} | {acceptance} | {gate} | {r['semantic_review']} |")
    md+=['', 'Native aggregate labels are retained in raw results. Where they say FROZEN_ACCEPTANCE_FAILURE after compilation failed, no frozen JUnit execution or behavioral decision is implied. Exact return codes, case counts, mismatches, emitted compiler diagnostics and verifier timings are in the paired analysis. No failure was manually fixed or accepted on partial output.',
        '', '## 12. Correction outcomes', '',
        f'Normal targeted corrections: {sum(r["worker_targeted_corrections"] for r in rows)}. Structural corrections: {sum(r["worker_structural_corrections"] for r in rows)}. Cells stopped by repeated-proposal rejection: {repeats}. No extra attempt or mode switch was added.',
        '', '| Cell | Proposal comparison |', '|---|---|']
    for r in rows:
        reviewed=assessments.get(r['run_id'])
        md.append(f"| {r['historical_cell']} | "+'; '.join(f"calls {c['earlier_call']}→{c['later_call']}: {reviewed['classification'] if reviewed else c['comparison']}" for c in r['correction_comparison'])+' |')
    md+=['', 'IDENTICAL_EDIT_PAYLOAD distinguishes a changed summary/JSON representation from a changed implementation; it is not mislabeled byte-identical. Different payloads require semantic inspection before claiming meaningful repair.',
        '', 'The last cell was inspected: its correction removed an early negative-count check that preceded explicit null-value validation, retaining a later negative-count check. This changes possible behavior and is MATERIALLY_DIFFERENT. Both initial and revised candidates compiled and ran all three frozen cases; both failed all three with the same failure identities. The correction received all three emitted case names, exception types and messages. [Read-only semantic assessment](HIVE-THINKING-POLICY-001/evidence/correction-semantic-assessment.json).',
        '', '## 13. Resources and runtime events', '',
        f'Exhausted logical runtime-failure cells: {a["runtime_failure_cells"]}; worker generation deadlines: {a["worker_timeouts"]}; verifier-runtime-failure cells: {a["verifier_runtime_failure_cells"]}. Attempts with an HTTP/stream error: {len(attempt_errors)}. The first planner attempt returned HTTP 500 with CUDA initialization/process failure; its normal retry completed. This recovered event did not become a replacement trial.',
        '', '| Cell | Pre-run free host GiB | Minimum free host GiB | Minimum free virtual GiB | Minimum free GPU MiB |', '|---|---:|---:|---:|---:|']
    for r in rows:
        res=r['resources'];pre=next((s for s in res if s['label']=='pre-run'),res[0])
        vals=[min(s[k] for s in res if s[k] is not None) for k in ('free_host_gib','free_virtual_gib','gpu_free_mib')]
        md.append(f"| {r['historical_cell']} | {pre['free_host_gib']:.3f} | {vals[0]:.3f} | {vals[1]:.3f} | {vals[2]} |")
    totals=a['totals']
    unusable_nonworkers=[(r,c) for r in rows for c in r['calls'] if c['role'] not in ('ui','backend','tests') and not c['schema_valid']]
    if unusable_nonworkers:
        md+=['', 'Additional non-worker protocol observations (the thinking intervention did not apply to these roles):', '', '| Cell | Role/call | Kind | Seconds | Terminal state | Answer characters |', '|---|---|---|---:|---|---:|']
        for r,c in unusable_nonworkers:
            at=c['attempt_details'][-1] if c['attempt_details'] else {};terminal=at.get('terminal') or {}
            md.append(f"| {r['historical_cell']} | {c['role']} / {c['number']} | {c['kind']} | {c['elapsed_seconds']:.3f} | {terminal.get('done_reason',c.get('status'))} | {at.get('channels',{}).get('content',{}).get('characters','unknown')} |")
        md+=['', 'A provider stream ending at its output cap can be complete at transport level while providing no valid review JSON. Existing evidence-preserving JSON repair remains in policy. These observations do not change worker completion or deterministic candidate outcomes.']
    md+=['', f'Logical task-model calls: {totals["model_calls"]}; HTTP attempts: {totals["provider_attempts"]}; known completed-call input/output tokens: {totals["input_tokens_known"]}/{totals["output_tokens_known"]}. Model-call seconds: {totals["model_seconds"]:.3f}; verifier seconds: {totals["verification_seconds"]:.3f}; summed cell wall seconds: {totals["wall_seconds"]:.3f}. Failed attempts without terminal accounting have unknown usage. Resource snapshots include residency, relevant processes and Docker state; no pressure-driven configuration changes occurred.',
        '', '## 14. Paired historical comparison', '',
        '| Endpoint | Historical selected cohort | Prospective cohort |', '|---|---:|---:|',
        f'| Complete responses for selected failed call paths | 0/6 | Fresh-cell structured response: {a["complete_structured_worker_response"]}/6 |',
        f'| Any completed worker response in whole cell | 1/6 | {t["worker_response"]}/6 |',
        f'| Executable edit | 1/6 | {t["executable_edit"]}/6 |',
        f'| Targeted verifier invoked | 1/6 | {t["targeted_verification"]}/6 |',
        f'| Compiled candidate with frozen JUnit cases executed | 1/6 | {tested_cells}/6 |',
        f'| Frozen acceptance | 0/6 | {t["frozen_acceptance"]}/6 |',
        f'| Full-gate software success | 0/6 | {a["verified_software_success"]}/6 |',
        f'| Exhausted worker runtime failure | 6/6 | {sum(any(c.get("status")=="failed" for c in r["workers"]) for r in rows)}/6 |',
        '', 'Six selected historical failures and six fresh, unseeded whole-cell executions do not estimate overall Hive reliability or isolate all temporal/resource/stochastic effects. Planner policy stayed fixed but freshly generated plans can differ. No formal significance claim is made.',
        '', '## 15. Quality tradeoff and compilation diagnosis', '',
        'Completion is not accepted software. The first five candidates have a directly demonstrated shared edit-boundary problem: inserting a member inside a record header or another method, or replacing only a method header with a whole method and leaving the original body behind. Literal replay exactly matches applied files; Java lacks the Python/JavaScript structural preflight branch. Actual prompts warn about splitting declarations and contain complete original source. Correction schemas allow different edits and do not force repetition.',
        '', 'Correction transport also loses useful diagnostic detail: its explicitly marked tail-only string budget drops the first compiler error in those five corrections, retaining later cascading errors. This is a measured information-selection limitation, not evidence that restoring the first error alone would produce correct code. Historical J003 controls received their sole compiler error and still failed their revised edits. No diagnostic or Java edit repair was introduced during this experiment.',
        '', 'The same J003 placement failure occurred in historical qwen2.5-coder cells 5 and 7, before this policy. That supports recurrence, not a claim that thinking-off has no quality cost. Historical interrupted answers cannot provide a completed-code accuracy control; the selected cohort includes only one prior compiled initial candidate. Completed but invalid code and ineffective corrections leave the competing quality hypothesis unresolved. [Read-only compilation diagnosis](HIVE-THINKING-POLICY-001/compilation-analysis.md), [exact splice replay](HIVE-THINKING-POLICY-001/evidence/compilation-causal-replay.json). No unrelated edit repair was installed.',
        '', 'Heterogeneity matters: prospective cell 6 avoided the source-boundary error and compiled both proposals, but its historical counterpart had two frozen failures in three cases whereas the prospective initial and revised candidates each had three. This is an observed worse case count in the only previously compiled pair, not isolated evidence of a thinking-mode causal effect. Five newly completed initial proposals failed compilation; no new accepted software was obtained. Classification is therefore limited to the completion mechanism.',
        '', '## 16. Integrity audit', '',
        f'Final audit passed. Source hash before/after: `{audit["source_tree_hash_after"]}`. {audit["prior_files_checked"]:,} historical files checked with no changes. Baseline, frozen tests, image/cache/attestation references, frozen order, candidate-origin baseline identity and staged identities match. All controlled worker requests actually sent false; planner/reviewer requests omitted the field. All candidates stayed scoped and unapplied. [Final audit](HIVE-THINKING-POLICY-001/evidence/final-integrity.json).',
        '', '## 17. Files changed', '',
        'Only the new isolated source copy changed: `app.py`, `workshop/providers.py`, new `workshop/thinking_policy.py`, new `workshop/thinking_profiles.json`, new `tests/test_thinking_policy.py`, and the targeted historical-provider assertion in `tests/test_semantic_fidelity.py`. [Exact source diff](HIVE-THINKING-POLICY-001/evidence/source-change.diff). Study-only scripts/artifacts provide reconstruction, probes, regression, freeze, copied qualified instrumentation, analysis and reporting. Prior production/evidence trees remain byte-identical.',
        '', '## 18. Falsification criteria', '',
        'The transport mechanism would be undermined by false requests still producing thinking-only deadline exhaustion, schema/settings drift, or unrecorded retries. Useful software improvement would be undermined by unusable completions and unchanged verified outcomes. The Java-boundary diagnosis would be undermined by replay differing from applied source or compiler failures originating elsewhere. Preserved wire streams, literal replay, deterministic results and the final audit allow those claims to be checked.',
        '', '## 19. Remaining uncertainties', '',
        'This is a selected six-cell diagnostic on one exact model/provider/runtime, not a reliability study. Optional thinking may still affect semantic quality. Fresh planner outputs and fluctuating resource pressure limit attribution beyond the observed channel/completion change. No claim is made that fixing declaration placement alone would satisfy tasks: source inspection also exposes possible independent type/body defects. Capability profiles must be requalified for version/digest/template changes. Semantic review remains fallible and cannot override deterministic failure.',
        '', '## 20. Final classification', '',f'**{classification}**.', '',
        f'The observed result is {a["complete_structured_worker_response"]}/6 cells with completed structured worker responses, {t["executable_edit"]}/6 executable edits, {t["frozen_acceptance"]}/6 frozen acceptance and {a["verified_software_success"]}/6 full-gate successes. The completion mechanism and engineering outcome are reported independently. Historical studies retain their original classifications; no candidate is promoted.']
    target=ROOT/'HIVE-THINKING-POLICY-001-REPORT.md';target.write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(target)

if __name__=='__main__':main()
