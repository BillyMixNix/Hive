"""Exactly four fresh real-verifier runs: baseline/candidate, direct/wrapped."""
import time,json,subprocess,shutil
from qcommon import *
from cell_harness import prepare_cell,external_context,capture_candidate
from recorder import VerifierRecorder

def canonical(report):
    rows=[]
    for c in report.get('checks',[]):
        d=c.get('detail');d=d if isinstance(d,dict) else {}
        rows.append({'name':c.get('name'),'passed':c.get('passed'),
            **{k:d[k] for k in ('returncode','timed_out','tests','acceptance_mismatches','report_error','baseline_unchanged','candidate_unchanged','frozen_tests_unchanged','stage_unchanged') if k in d}})
    return {'top_level_keys':sorted(report),'passed':report.get('passed'),'checks':rows}

def invocation_evidence(run_dir):
    invocations=list(Path(run_dir).glob('verification/*/invocation.json'))
    rows=[]
    for p in invocations:
        events=[json.loads(s) for s in (p.parent/'verification-events.jsonl').read_text().splitlines()]
        rows.append({'invocation_file':str(p),'invocation':read(p),'phase_counts':{phase:sum(e['phase']==phase for e in events) for phase in ('verifier_launch_requested','gradle_invoked','gradle_returned','junit_reports_collected','verifier_process_exit')},
            'junit_events':[e for e in events if e['phase']=='junit_reports_collected']})
    return rows

def main():
    configure();forbid_models();assert (HERE/'evidence/BEFORE.json').exists()
    assert not (HERE/'evidence/controls/STARTED.json').exists()
    assert manifest(SOURCE)==read(HERE/'evidence/production-before.json')
    image=subprocess.check_output([shutil.which('docker'),'image','inspect',FREEZE['verifier']['verifier_image_id'],'--format','{{.Id}}'],text=True).strip()
    assert image==FREEZE['verifier']['verifier_image_id'];assert attest(Path(FREEZE['baseline']['root']))
    save(HERE/'evidence/controls/STARTED.json',{'at':stamp(),'controls':['A-direct','A-wrapped','B-direct','B-wrapped'],'model_calls':0})
    preserved=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/runs/4574db69cea0/stage/src/main/java/dev/atmcompanion/state/SnapshotFormatter.java'
    assert sha(preserved)=='b8a17817ccbf0846cfb4e765f5b530b4790e8c5dcdf6fef16a02d19a0f35a4d3'
    task=FREEZE['tasks'][0];rows=[]
    for label in ('A-direct','A-wrapped','B-direct','B-wrapped'):
        root=HERE/'evidence/controls'/label;root.mkdir(exist_ok=False)
        rid,run_dir,candidate,external=prepare_cell(root/'runs',task)
        stage=run_dir/'stage';external_root.copy_candidate_tree(candidate,stage,run_dir)
        if label.startswith('B'):(stage/task['files'][0]).write_bytes(preserved.read_bytes())
        before=external_root.tree_sha256(stage);rec=VerifierRecorder(root/'measurement',capture=capture_candidate)
        original=hive.targeted_verify;wrapped=rec.wrap(original,'targeted');t0=time.monotonic()
        print(json.dumps({'event':'control_started','label':label,'at':stamp(),'candidate_sha256':before}),flush=True)
        with external_context(external,run_dir):report=(wrapped if label.endswith('wrapped') else original)(stage,'backend',task['files'])
        elapsed=time.monotonic()-t0
        proof=invocation_evidence(run_dir)
        row={'label':label,'report':report,'canonical':canonical(report),'wall_seconds':elapsed,'model_calls':0,
            'candidate_sha256':before,'candidate_unchanged':external_root.tree_sha256(stage)==before,
            'origin_unchanged':external_root.tree_sha256(candidate)==FREEZE['baseline']['sha256'],
            'frozen_test_sha256':external['frozen_junit_tests'][0]['sha256'],'frozen_tests_unchanged':hive_jvm.verify_frozen_artifacts(external['frozen_junit_tests'],run_dir),
            'native_invocation_evidence':proof,'recorder':rec.summary() if label.endswith('wrapped') else None,'records':rec.records}
        save(root/'result.json',row);rows.append(row);save(HERE/'evidence/controls/results.json',rows)
        print(json.dumps({'event':'control_finished','label':label,'passed':report['passed'],'seconds':elapsed,'native_invocations':len(proof),'measurement':row['recorder']}),flush=True)
    comparisons=[]
    for a,b in ((rows[0],rows[1]),(rows[2],rows[3])):
        comparisons.append({'control':a['label'][0],'candidate_identity_equal':a['candidate_sha256']==b['candidate_sha256'],'frozen_test_identity_equal':a['frozen_test_sha256']==b['frozen_test_sha256'],
            'acceptance_fields_equal':a['canonical']==b['canonical'],'direct_seconds':a['wall_seconds'],'wrapped_seconds':b['wall_seconds'],
            'exactly_one_native_invocation_each':len(a['native_invocation_evidence'])==len(b['native_invocation_evidence'])==1,
            'integrity_passed':all(r['candidate_unchanged'] and r['origin_unchanged'] and r['frozen_tests_unchanged'] for r in (a,b)),
            'measurement_status':b['recorder']['measurement_status']})
    save(HERE/'evidence/controls/comparison.json',comparisons)
    print(json.dumps(comparisons,indent=2),flush=True)
if __name__=='__main__':main()
