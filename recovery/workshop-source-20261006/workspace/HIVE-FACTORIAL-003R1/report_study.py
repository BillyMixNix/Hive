"""Read-only reporting after execution; never imported by the trial controller."""
import collections,json,math,re
from pathlib import Path
from common import HERE,ROOT,STUDY,HIST,read,save,sha,stamp

def table(headers,rows):
    def cell(v):return str(v).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|']+['| '+' | '.join(cell(v) for v in row)+' |' for row in rows])
def main():
    f=read(HERE/'FREEZE.json');s=read(HERE/'evidence/analysis-summary.json');rows=read(HERE/'evidence/per-trial-analysis.json')
    integrity=read(HERE/'evidence/final-integrity.json') if (HERE/'evidence/final-integrity.json').exists() else {'passed':False}
    frozen_harness={name:sha(HERE/name)==digest for name,digest in f['instrumentation_files'].items()}
    lock_ok=sha(HERE/'FREEZE.json')==(HERE/'LOCK.sha256').read_text().strip()
    save(HERE/'evidence/reporting-integrity.json',{'at':stamp(),'freeze_lock_matches':lock_ok,'frozen_harness_files':frozen_harness,
        'passed':lock_ok and all(frozen_harness.values()),'scope':'Read-only postprocessing audit; no frozen file modified.'})
    integrity_ok=integrity['passed'] and lock_ok and all(frozen_harness.values())
    readiness=read(HERE/'evidence/readiness-results.json') if (HERE/'evidence/readiness-results.json').exists() else []
    complete=s['completed'];x=s['successes'];n=s['trials_observed'];u=s['usage'];trans=s['transitions']
    classification=('EXPERIMENT_INVALID' if complete and not integrity_ok else
        'EXPERIMENT_INCOMPLETE' if not complete else 'REPAIRED_HIVE_VERIFIED_SUCCESSES_OBSERVED' if x else 'REPAIRED_HIVE_ZERO_VERIFIED_SUCCESSES')
    # Distinguish entering full verification from actually executing its gate.
    actual_full=[];native=[];diffs=[];verification_stages=[];review_protocol=[];game_markers=[]
    for r in rows:
        folder=Path(r['evidence']);records=read(folder/'verification-records.json')
        native_run=read(folder/'run.json');semantic=native_run.get('semantic_review') or {}
        if semantic.get('parse_error') or semantic.get('validation_error') or semantic.get('repair_attempted'):
            review_protocol.append({'ordinal':r['ordinal'],'parse_error':semantic.get('parse_error'),
                'validation_error':semantic.get('validation_error'),'repair_attempted':semantic.get('repair_attempted',False),
                'repaired':semantic.get('repaired',False),'final_disposition':semantic.get('disposition'),
                'initial_raw_empty':semantic.get('raw')=='','source':str(folder/'run.json')})
        for record in records:
            report=record.get('report',{});serialized=json.dumps(report)
            for check in report.get('checks',[]):
                if check.get('name')!='frozen_junit_acceptance':continue
                detail=check.get('detail',{});tests=detail.get('tests',[])
                count=sum(t.get('tests',0) for t in tests)
                stage=('PASS' if check.get('passed') is True else
                    'VERIFIER_TIMEOUT' if detail.get('timed_out') is True else
                    'COMPILATION_FAILURE_BEFORE_FROZEN_TESTS' if count==0 and 'compileJava FAILED' in serialized else
                    'FROZEN_TEST_FAILURE' if count>0 else 'FAILED_WITHOUT_FRESH_TEST_CASES')
                verification_stages.append({'ordinal':r['ordinal'],'mode':record['kind'],'observed_stage':stage,'cases':count,
                    'failures':sum(t.get('failures',0) for t in tests),'native_check_name':check['name']})
        ran=any(c.get('name')=='full_gradle_check' for v in records for c in v.get('report',{}).get('checks',[]))
        actual_full.append({'ordinal':r['ordinal'],'full_gate_executed':ran,'full_verification_invoked':r['transitions']['full_gate']})
        for p in (HERE/'evidence/runs'/r['run_id']).rglob('invocation.json'):
            native.append({'ordinal':r['ordinal'],'path':str(p),'sha256':sha(p)})
        for p in (HERE/'evidence/runs'/r['run_id']/'verification').glob('full-*/verification-events.jsonl'):
            for line in p.read_text(encoding='utf-8').splitlines():
                event=json.loads(line);out=event.get('source_event',{}).get('text','')
                for match in re.finditer(r'(\d+) GAME TESTS COMPLETE[^\r\n]*',out):
                    game_markers.append({'ordinal':r['ordinal'],'cases':int(match.group(1)),
                        'marker':match.group(0),'event_time':event.get('wall_timestamp'),'source':str(p)})
        # Derive a readable diff after execution from already preserved snapshots.
        import environment as env
        task=next(t for t in f['tasks'] if t['id']==r['task_id'])
        for p in (folder/'verifications').glob('*/candidate.json'):
            snapshot=p.parent/'applied-source';paths=task['files']
            diff=env.hive.make_diff(Path(f['baseline']['root']),snapshot,paths)
            destination=p.parent/'candidate.diff';destination.write_text(diff,encoding='utf-8')
            diffs.append({'ordinal':r['ordinal'],'snapshot':str(snapshot),'diff':str(destination),'sha256':sha(destination)})
    save(HERE/'evidence/reachability-audit.json',{'full_gate':actual_full,'native_invocations':native,'derived_diffs':diffs,'verification_stages':verification_stages,'game_test_markers':game_markers})
    actual_full_count=sum(r['full_gate_executed'] for r in actual_full)
    descriptive=[]
    for r in rows:
        native=r['primary_outcome'];observed=native
        diagnostics=' '.join(str(v.get('exception_message','')) for v in r['plan_failures'] if isinstance(v,dict))
        stages=[v['observed_stage'] for v in verification_stages if v['ordinal']==r['ordinal'] and v['mode']=='targeted']
        if native=='PLANNER_FAILURE' and ('assigned to both' in diagnostics or 'owned by multiple' in diagnostics):
            observed='OWNERSHIP_FAILURE'
        elif native=='FROZEN_ACCEPTANCE_FAILURE' and stages and all(v=='COMPILATION_FAILURE_BEFORE_FROZEN_TESTS' for v in stages):
            observed='TARGETED_VERIFICATION_FAILURE: COMPILATION'
        descriptive.append({'ordinal':r['ordinal'],'native_outcome':native,'observed_failure_class':observed,
            'targeted_substages':stages,'verified_software_success':r['verified_software_success'],
            'basis':'Descriptive refinement from preserved diagnostics; raw outcome and success score unchanged.'})
    save(HERE/'evidence/descriptive-taxonomy.json',descriptive)
    save(HERE/'evidence/reviewer-protocol-audit.json',review_protocol)
    rate=x/n if n else 0.;ci=s['statistics']['interval'];p=s['statistics']['fisher_exact_two_sided_p']
    result_table=table(['#','Task','Model','Rep','Software outcome','Review','Software frontier','Calls','Minutes'],[
        [r['ordinal'],r['task_id'],r['model'],r['replicate'],r['primary_outcome'],r['semantic_review'],r['software_frontier'],r['model_calls'],f"{r['wall_seconds']/60:.2f}"] for r in rows])
    central=table(['Study / condition','Verified successes','Trials','Rate'],[
        ['FACTORIAL-002 Hive',0,16,'0%'],['FACTORIAL-002 single',0,16,'0%'],[STUDY+' repaired Hive',x,n,f'{rate:.2%}']])
    transition_table=table(['Transition','FACTORIAL-002 Hive',STUDY+' repaired Hive'],[
        ['Valid plan','2/16',f"{trans.get('valid_plan',0)}/{n}"],['Worker reached','2/16',f"{trans.get('worker',0)}/{n}"],
        ['Executable edit','0/16',f"{trans.get('executable_edit',0)}/{n}"],['Targeted verification attempt','0/16',f"{trans.get('targeted_verification',0)}/{n}"],
        ['Frozen acceptance','0/16',f"{trans.get('frozen_acceptance',0)}/{n}"],['Full gate executed','0/16',f'{actual_full_count}/{n}'],
        ['Full gate passed','0/16',f"{trans.get('full_gate_passed',0)}/{n}"],['Verified software success','0/16',f'{x}/{n}']])
    group_rows=[[field,key,row['successes'],row['trials'],f"{row['rate']:.2%}"] for field,groups in s['groups'].items() for key,row in groups.items()]
    success_rows=[r for r in rows if r['verified_software_success']]
    worker_task_checks=[v for r in rows for v in r['original_task_in_worker_prompts']]
    resource_rows=[]
    for r in rows:
        samples=r['resources'];pre=next((v for v in samples if v['label']=='pre-run'),{});post=next((v for v in samples if v['label']=='post-run'),{})
        vals=[v['free_host_gib'] for v in samples if v.get('free_host_gib') is not None]
        resource_rows.append([r['ordinal'],round(pre['free_host_gib'],3) if pre.get('free_host_gib') is not None else None,
            round(post['free_host_gib'],3) if post.get('free_host_gib') is not None else None,round(min(vals),3) if vals else None,
            pre.get('gpu_free_mib'),post.get('gpu_free_mib')])
    interesting=[]
    for r in rows:
        if r['errors'] or r['plan_failures']:interesting.append({'ordinal':r['ordinal'],'errors':r['errors'],'plan_failures':r['plan_failures']})
    save(HERE/'evidence/future-investigation.json',interesting)
    known_artifact=HERE/'evidence/future-investigation.json'
    text=f'''# {STUDY} — Repaired Controller Replication

**Classification: {classification}**

## 1. Experimental question

Did the frozen repaired Hive produce verified software across the same task/model/replicate cells that previously yielded 0/16? This study ran {n} of 16 cells; verified successes: **{x}/{n}**. Semantic review and promotion are separate dimensions. No candidate was promoted.

## 2. Historical baseline

FACTORIAL-002 remains 0/16 Hive and 0/16 single, with 37/29 model calls and 98.7/149.5 trial-minutes respectively. Fourteen Hive trials stopped during planning and two reached workers/edit preflight; none reached frozen acceptance or full verification. FACTORIAL-003 remains permanently EXPERIMENT_INVALID (zero valid completed cells, one compromised cell, fifteen unstarted). No historical cell is rescored or reused.

{central}

## 3. Frozen controller identity

Source tree hash: `{f['source']['tree_hash']}`. The new isolated copy is byte-identical to final NFRT-ATTESTATION-002 source. [FREEZE.json]({STUDY}/FREEZE.json), [source inventory]({STUDY}/evidence/source-inventory.json), and [production inventory]({STUDY}/evidence/production-inventory.json) record all bytes, pinned tool/runtime identities and configuration. Freeze timestamp: `{f['frozen_at']}`. Ollama version: `{f['ollama_version'].get('version')}`. Both local model digests match FACTORIAL-002.

## 4. Repairs included

Scope/correction feedback, complete context with truncation disabled, single-file exclusive ownership generation, original-task propagation, bounded legitimate correction diagnostics, observable verification, attested private NFRT reuse, fresh full compilation, strict reviewer schema, separated deterministic/review/promotion states, plus the qualified observational harness and generalized source-class NFRT attestation. No repair was made during this study.

## 5. Task/model/replicate design

Four unchanged tasks J001–J004 × qwen2.5-coder:14b and qwen3:8b × two replicates = sixteen Hive cells. Baseline, task text, authorized files and hidden acceptance identities are in the freeze. No new single-agent condition was run. The user authorized the sixteen Hive cells.

## 6. Trial order

Historical `random.Random(20261004)` shuffled task/replicate blocks and model/controller cells, then filtered Hive, preserving relative order. Frozen before outcomes:

{table(['Ordinal','Task','Model','Replicate','Historical ordinal'],[[i,c['task_id'],c['model'],c['replicate'],c['historical_ordinal']] for i,c in enumerate(f['order'],1)])}

## 7. Runtime policy

One bounded non-task readiness request per model, then serial trials. Residency unmanaged consistently: no manual loading/unloading, warmups, GPU tuning, parameter changes or replacement cells. `num_ctx=12288`, `truncate=false`, temperature 0.1; output caps planner 2048, workers 6000, reviewer 1536. Existing two-attempt provider policy, 900-second generation setting, normal corrections, historical aggregate reservation/decision budgets remain frozen. Targeted/full outer/full inner deadlines remain 240/660/600 seconds. Exact provider wire bodies and terminal accounting are preserved per attempt.

{table(['Readiness model','Result','Seconds','Scope'],[[r['model'],r['status'],round(r['elapsed_seconds'],3),'Short non-task diagnostic only'] for r in readiness])}

## 8. Integrity controls

The qualified recorder/candidate wrapper was copied byte-for-byte. All 52 assembled harness tests passed before freezing, including a scripted normal cell, exactly-once invocation, result/exception preservation, missing-field measurement errors and rollback. An initial test command failed because its temporary parent directory did not exist; its setup-error log/XML remain preserved. No inference occurred in those tests. Every cell started from a fresh baseline-derived candidate, with frozen tests held outside model-visible roots and private verifier caches. Scope, ownership, candidate hashes, frozen artifacts and source integrity remain host-enforced.

## 9. Per-trial results

{result_table}

[Raw aggregate]({STUDY}/evidence/raw-results.json) and [complete per-trial analysis]({STUDY}/evidence/per-trial-analysis.json) link run IDs, requests, outputs, plans, ownership, edits, corrections, review and resource observations. Transient applied-source snapshots and derived diffs survive rollback. A failure is not replaced.

## 10. Verified success results

Success requires a model-generated scoped candidate, fresh frozen acceptance, required full gate and identity/integrity. Reviewer unavailable/rejected cannot erase a deterministic success; neither confers promotion authorization.

{table(['Grouping','Value','Successes','Trials','Rate'],group_rows)}

{table(['Ordinal','Run ID','Verified source-manifest SHA-256'],[[r['ordinal'],r['run_id'],r['candidate_identity']['stage_source_sha256']] for r in success_rows])}

The two successful cells independently produced the same candidate source identity. Each received a fresh baseline and independently passed fresh verification; this is two successful trials and one unique successful implementation. Both successes were J001/qwen2.5-coder:14b, one per replicate. They required no worker correction. Their full gates each passed 154 JUnit cases, 26 game tests and 3 quest game tests; exact commands, completion markers and results remain in per-trial verification evidence and the reachability audit.

## 11. Transition reachability

{transition_table}

Full-verification entry and actual full-gate execution are distinct; {trans.get('full_gate',0)} entered full verification, {actual_full_count} reached a `full_gradle_check` result. Semantic review was invoked in {trans.get('semantic_review',0)}/{n}. External-candidate presentation restrictions remain in force. [Reachability audit]({STUDY}/evidence/reachability-audit.json).

## 12. Failure taxonomy

{table(['Primary outcome','Trials'],list(s['primary_outcomes'].items()))}

The table above preserves the frozen collector's native labels. The following diagnostic refinement separates duplicate ownership from other planner rejection and pre-test compilation failures from executed frozen-test failures. It changes no trial score or historical record.

{table(['Observed class','Trials'],list(collections.Counter(r['observed_failure_class'] for r in descriptive).items()))}

[Per-cell taxonomy with native labels]({STUDY}/evidence/descriptive-taxonomy.json).

Exact native errors and verifier results are retained. Primary software outcome, reviewer disposition and runtime events are reported separately. Planner corrections: {u['planner_corrections']}; structural worker corrections: {u['worker_structural_corrections']}; targeted corrections: {u['worker_targeted_corrections']}; repeated-proposal trials: {s['repeated_proposal_trials']}.

The frozen analysis found {s['malformed_response_trials']} malformed-response trials in terminal controller errors, but that measure omits successfully repaired reviewer parse failures. The separate review-protocol audit records {len(review_protocol)} affected trial(s): cell 2 returned an empty initial review and the normal evidence-preserving JSON repair returned a valid rejection. [Reviewer protocol audit]({STUDY}/evidence/reviewer-protocol-audit.json).

The frozen collector's broad `FROZEN_ACCEPTANCE_FAILURE` label can include compilation failure because the native acceptance check also fails when no fresh test report exists. It does **not** establish that frozen assertions executed. The observed substage below preserves that distinction without changing any PASS/FAIL score or native record.

{table(['Ordinal','Verifier mode','Observed substage','Fresh cases','Failures'],[[r['ordinal'],r['mode'],r['observed_stage'],r['cases'],r['failures']] for r in verification_stages])}

## 13. Semantic review

{table(['Disposition','Trials'],list(s['reviews'].items()))}

No review disposition is interpreted as human approval. Every row has `promotion_authorization=not_authorized`; native external-policy blocks remain recorded independently.

## 14. Runtime failures and resources

Trials with exhausted logical model calls, including reviewer-only failures: {s['runtime_failure_trials']}. Trials with any HTTP/provider-attempt error: {s['provider_attempt_error_trials']}; errored attempts: {s['provider_attempt_errors']}. Verifier runtime-failure trials: {s['verifier_runtime_failure_trials']}. These categories may overlap and are not summed as software failures.

All six runtime failures were qwen3:8b backend calls that exceeded the 900-second total generation limit. Cells 3, 6, 8, 9 and 12 failed before a worker response/edit. Cell 15 first produced an executable edit with two frozen-test failures, then timed out during targeted correction. The latter retains both its behavioral failure and runtime event. No reviewer call failed at the provider layer. The existing total-deadline policy ended these calls after one HTTP attempt; no manual retry was added.

{table(['Ordinal','Pre host free GiB','Post host free GiB','Sampled minimum GiB','Pre GPU free MiB','Post GPU free MiB'],resource_rows)}

Virtual memory, residency, Docker/process state and asynchronous sampling timestamps are in per-trial runtime artifacts. Sampled minima are not continuous measurements. Resource pressure was observed without runtime tuning.

## 15. Model/token/time usage

{table(['Metric','Observed'],[[k,u[k]] for k in ('model_calls','provider_attempts','input_tokens_known','output_tokens_known','model_seconds','verification_seconds','wall_seconds','successes_per_model_call','successes_per_trial_hour')])}

Token interpretation: {u['usage_interpretation']} All-attempt accounting complete: {u['all_attempt_token_accounting_complete']}. Readiness is excluded from task-call and trial-efficiency totals. Faster failure is not superior efficiency.

Total trial time was {u['wall_seconds']/60:.2f} minutes ({u['wall_seconds']/3600:.3f} hours), versus historical Hive's 98.7 trial-minutes. Model time was {u['model_seconds']/60:.2f} minutes and verifier time {u['verification_seconds']/60:.2f} minutes. These longer runs reached more stages; time alone is not a success comparison.

## 16. Comparison with FACTORIAL-002

Historical Hive 0/16 versus current {x}/{n}; observed absolute rate difference {rate*100:.2f} percentage points. The transition table separates candidate production from acceptance. Results occurred at different times with intentional changes to multiple controller/infrastructure mechanisms; no single-repair causal attribution is claimed.

## 17. Current single-agent comparison

Not run. Historical single remains 0/16 and is not represented as a contemporaneous control. Task/model/replicate-matched historical Hive records are preserved in the analysis artifact.

## 18. Statistical analysis

New rate {rate:.2%}; two-sided 95% Clopper–Pearson interval **{ci[0]:.2%}–{ci[1]:.2%}**. Two-sided Fisher exact p-value for historical 0/16 versus current {x}/{n}: **{p:.6f}**. All planned trials completed. This observed increase is not statistically significant at 0.05 under the requested exact comparison. Small repeated cells, temporal differences and shared hardware limit generalization; this result does not establish reliability or broad superiority.

## 19. Candidate/evidence integrity

Final audit passed: **{integrity_ok}**. [Final integrity]({STUDY}/evidence/final-integrity.json) includes controller, original source, prior evidence, baseline, all tests, cache/attestation/image, each candidate origin/stage, exact order, provider configuration and hidden-source absence checks. [Reporting integrity]({STUDY}/evidence/reporting-integrity.json) additionally rehashes the freeze lock and every frozen harness file. No apply/promotion call is authorized or executed. Each model receives only its own legitimate task/source/normal verification feedback.

Exact original task text is present in {sum(v['present'] for v in worker_task_checks)}/{len(worker_task_checks)} captured worker/correction wire requests. Candidate source identities and transient diffs are retained; no earlier candidate was used to seed another cell.

## 20. Future investigation

Native observed failures are listed in [future-investigation.json]({STUDY}/evidence/future-investigation.json). They were not repaired, used as manual hints or fed into later cells. This file records evidence for later diagnosis rather than asserting unsupported root causes.

Observed frontiers worth separate investigation are multi-file ownership conflicts (cells 4/11), worker generation deadlines, nonmatching replacement anchors (cell 13), pre-test compilation failures (cells 2/5/7), repeated failed proposals (cells 2/10), and J002 corrections that either timed out (cell 15) or changed the proposal but still failed the same two emitted cases (cell 16). No causal diagnosis or repair of these frontiers was performed in this study. [Postprocessing notes]({STUDY}/evidence/reporting-notes.md) disclose reporting-only corrections; the frozen execution files remained unchanged.

## 21. Limitations

Sixteen cells, two local models, four bounded tasks, one workstation. Historical and current conditions intentionally differ. Both observed successes concern the same task/model and produce the same implementation; they do not demonstrate success across the task suite. Exact binomial/Fisher calculations describe the requested comparison, but repeated task/model cells are not evidence of independent draws from a broad software-task population. Short readiness cannot establish full-workload reliability. Missing attempt token counts are not zero usage. Reviewer concerns remain distinct from test correctness. No candidate promotion is part of autonomous success. A new study would require separate authorization and identity.

## 22. Final classification

**{classification}** — {x} verified software successes across {n} completed cells. The measured result is retained. No extra trial, repair or promotion follows this report.
'''
    path=ROOT/(STUDY+'-REPORT.md');path.write_text(text,encoding='utf-8')
    save(HERE/'evidence/report.json',{'at':stamp(),'classification':classification,'report_sha256':sha(path),'completed':n,'successes':x})
    print(path)

if __name__=='__main__':main()
