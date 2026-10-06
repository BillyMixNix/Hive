"""A distinct negative fixture that actually triggers the unchanged JVM verifier."""
import time
from run_real_controls import *
def main():
    configure(OUT/'approved-nfrt-seed-v2.json')
    root=OUT/'real-controls/negative-java-plus-access-transformer';root.mkdir(exist_ok=False)
    task=FREEZE['tasks'][0];rid,run_dir,origin,external=cell_harness.prepare_cell(root/'runs',task)
    stage=run_dir/'stage';external_root.copy_candidate_tree(origin,stage,run_dir)
    outside=next(r for r in read(OUT/'sensitivity-fixtures.json') if r['case']=='F-unrelated')['paths'][0]
    with (stage/outside).open('a',encoding='utf-8',newline='') as f:f.write('\n// JVM-triggering harmless negative-control edit.\n')
    at='src/main/resources/META-INF/accesstransformer.cfg'
    p=stage/at;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('public net.minecraft.world.entity.Entity\n',encoding='utf-8')
    before=external_root.tree_sha256(stage);recorder=VerifierRecorder(root/'measurement',capture=cell_harness.capture_candidate)
    wrapped=recorder.wrap(hive.targeted_verify,'targeted');started=time.monotonic()
    with cell_harness.external_context(external,run_dir):report=wrapped(stage,'backend',[outside,at])
    elapsed=time.monotonic()-started;native=invocation_evidence(run_dir)
    phase_files=list(run_dir.glob('verification/*/verification-events.jsonl'))
    events=[e for path in phase_files for e in read_events(path)]
    row={'label':'negative-java-plus-access-transformer','at':stamp(),'report':report,'canonical':canonical(report),'seconds':elapsed,
        'candidate_sha256':before,'candidate_unchanged':external_root.tree_sha256(stage)==before,
        'origin_unchanged':external_root.tree_sha256(origin)==FREEZE['baseline']['sha256'],
        'frozen_tests_unchanged':hive_jvm.verify_frozen_artifacts(external['frozen_junit_tests'],run_dir),
        'frozen_test_sha256':external['frozen_junit_tests'][0]['sha256'],'changed_files':[outside,at],
        'native_invocation_evidence':native,'recorder':recorder.summary(),'records':recorder.records,
        'seed_copy_events':[],'compile_events':[],'preflight_events':events,'model_calls':0,'factorial_trial':False,'promotion_authorization':'not_authorized'}
    save(root/'result.json',row)
    qualified=read(OUT/'real-controls/results.json')[:3]+[row]
    save(OUT/'real-controls/qualified-results.json',qualified)
    assert not native and report['passed'] is False and 'NFRT source inventory changed' in json.dumps(report)
    assert any(e['phase']=='nfrt_seed_validation_started' for e in events)
    assert not any(e['phase']=='verifier_launch_requested' for e in events)
    assert len(recorder.records)==1 and recorder.summary()['measurement_status']=='MEASURED'
    print(json.dumps({'passed':report['passed'],'native_invocations':len(native),'nfrt_preflight_reached':True,'measurement':'MEASURED','seconds':elapsed}),flush=True)
if __name__=='__main__':main()
