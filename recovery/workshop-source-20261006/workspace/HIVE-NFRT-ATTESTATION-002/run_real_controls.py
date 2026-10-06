"""Actual frozen targeted gates through the qualified recorder; no model/provider calls."""
import subprocess,shutil,time,copy
from common import *
# Reuse qualified code byte-for-byte. Bind its candidate setup to the isolated
# current source in memory; no old harness or production file is edited.
sys.path.insert(0,str(ROOT/'HARNESS-QUALIFICATION-001'))
import qcommon
qcommon.SOURCE=SOURCE
import cell_harness
from recorder import VerifierRecorder
from run_controls import invocation_evidence,canonical

def main():
    configure(OUT/'approved-nfrt-seed-v2.json')
    assert all(r['compatible'] for r in read(OUT/'scope-preflight/matrix.json')['tasks'])
    assert read(OUT/'full-regression-final/result.json')['exit_code']==0
    out=OUT/'real-controls';out.mkdir(exist_ok=False)
    save(out/'STARTED.json',{'at':stamp(),'model_calls':0,'source_inventory':inventory(SOURCE),
        'recorder_sha256':sha(ROOT/'HARNESS-QUALIFICATION-001/recorder.py'),'cell_harness_sha256':sha(ROOT/'HARNESS-QUALIFICATION-001/cell_harness.py')})
    task=FREEZE['tasks'][0]
    known=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/runs/4574db69cea0/stage'/task['files'][0]
    assert sha(known)=='b8a17817ccbf0846cfb4e765f5b530b4790e8c5dcdf6fef16a02d19a0f35a4d3'
    outside=next(r for r in read(OUT/'sensitivity-fixtures.json') if r['case']=='F-unrelated')['paths'][0]
    rows=[]
    for label in ['baseline','known-good-J001','outside-and-added-main','negative-access-transformer']:
        root=out/label;root.mkdir()
        rid,run_dir,origin,external=cell_harness.prepare_cell(root/'runs',task)
        stage=run_dir/'stage';external_root.copy_candidate_tree(origin,stage,run_dir);paths=list(task['files'])
        if label=='known-good-J001':(stage/task['files'][0]).write_bytes(known.read_bytes())
        if label=='outside-and-added-main':
            with (stage/outside).open('a',encoding='utf-8',newline='') as f:f.write('\n// Independent application source control.\n')
            new='src/main/java/qualification/independence/FreshCompilationProbe.java'
            p=stage/new;p.parent.mkdir(parents=True);p.write_text('package qualification.independence; final class FreshCompilationProbe {}\n',encoding='utf-8')
            paths=[outside,new]
        if label=='negative-access-transformer':
            p=stage/'src/main/resources/META-INF/accesstransformer.cfg';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('public net.minecraft.world.entity.Entity\n',encoding='utf-8');paths=[p.relative_to(stage).as_posix()]
        before=external_root.tree_sha256(stage)
        recorder=VerifierRecorder(root/'measurement',capture=cell_harness.capture_candidate)
        wrapped=recorder.wrap(hive.targeted_verify,'targeted')
        print('Starting actual control',label,stamp(),flush=True);started=time.monotonic()
        with cell_harness.external_context(external,run_dir):report=wrapped(stage,'backend',paths)
        elapsed=time.monotonic()-started;native=invocation_evidence(run_dir)
        events=[]
        for inv in native:events.extend(read_events(Path(inv['invocation_file']).parent/'verification-events.jsonl'))
        row={'label':label,'at':stamp(),'report':report,'canonical':canonical(report),'seconds':elapsed,
            'candidate_sha256':before,'candidate_unchanged':external_root.tree_sha256(stage)==before,
            'origin_unchanged':external_root.tree_sha256(origin)==FREEZE['baseline']['sha256'],
            'frozen_tests_unchanged':hive_jvm.verify_frozen_artifacts(external['frozen_junit_tests'],run_dir),
            'frozen_test_sha256':external['frozen_junit_tests'][0]['sha256'],'changed_files':paths,
            'native_invocation_evidence':native,'recorder':recorder.summary(),'records':recorder.records,
            'seed_copy_events':[e for e in events if 'nfrt' in e.get('phase','')],
            'compile_events':gradle_events(events),
            'model_calls':0,'factorial_trial':False,'promotion_authorization':'not_authorized'}
        save(root/'result.json',row);rows.append(row);save(out/'results.json',rows)
        print('Completed',label,'passed=',report.get('passed'),'seconds=',round(elapsed,3),'native=',len(native),flush=True)
        assert row['candidate_unchanged'] and row['origin_unchanged'] and row['frozen_tests_unchanged']
        assert recorder.summary()['measurement_status']=='MEASURED' and len(recorder.records)==1
        assert len(native)==(0 if label.startswith('negative') else 1)
    print('Real control sequence completed; no candidates applied.',flush=True)
def read_events(path):return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
def gradle_events(events):
    text=''.join(e.get('source_event',{}).get('text','') for e in events
        if e.get('phase')=='process_output' and e.get('source_event',{}).get('stream')=='stderr')
    return [json.loads(line.split('HIVE_GRADLE_DIAGNOSTIC ',1)[1]) for line in text.splitlines() if line.startswith('HIVE_GRADLE_DIAGNOSTIC ')]
if __name__=='__main__':main()
