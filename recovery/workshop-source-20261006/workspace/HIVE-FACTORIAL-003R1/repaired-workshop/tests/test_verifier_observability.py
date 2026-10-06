import json
import subprocess
import sys
import shutil
from pathlib import Path
import pytest
from workshop import hive_verifier
from workshop.verifier_trace import VerificationTrace
from test_hive_isolated_verifier import Result,source_tree


@pytest.mark.parametrize('code',[0,7])
def test_real_process_success_failure_capture_and_exit(tmp_path,code):
    trace=VerificationTrace(tmp_path/'candidate','targeted',tmp_path/'trace')
    command=[sys.executable,'-u','-c',f"import sys; print('out'); print('err',file=sys.stderr); sys.exit({code})"]
    cp=trace.capture(command,timeout=5,docker='unused',container='synthetic')
    assert cp.returncode==code and cp.stdout.strip()=='out' and cp.stderr.strip()=='err'
    events=[json.loads(x) for x in (trace.root/'verification-events.jsonl').read_text().splitlines()]
    assert events[-1]['phase']=='verifier_process_exit' and events[-1]['returncode']==code
    assert all(a['monotonic']<=b['monotonic'] for a,b in zip(events,events[1:]))


def test_real_timeout_retains_partial_both_streams_and_phase(tmp_path):
    trace=VerificationTrace(tmp_path/'candidate','targeted',tmp_path/'trace')
    script="import sys,time; print('partial stdout',flush=True); print('partial stderr',file=sys.stderr,flush=True); time.sleep(15)"
    with pytest.raises(subprocess.TimeoutExpired):
        trace.capture([sys.executable,'-u','-c',script],timeout=.5,docker='unused',container='synthetic')
    assert 'partial stdout' in (trace.root/'stdout.log').read_text()
    assert 'partial stderr' in (trace.root/'stderr.log').read_text()
    events=[json.loads(x) for x in (trace.root/'verification-events.jsonl').read_text().splitlines()]
    assert events[-1]['phase']=='timeout_fired'


def test_timeout_partial_pass_json_cannot_pass_cleanup_and_termination(tmp_path,monkeypatch):
    root=source_tree(tmp_path)
    commands=[]
    children={'container':True,'gradle':True,'test_jvm':True}
    temporary=[]
    def fake_run(argv,**kwargs):
        commands.append(argv)
        if argv[1:3]==['image','inspect']:return Result(stdout='sha256:fixed')
        if argv[1]=='run':
            temporary.append(Path(argv[argv.index('--mount')+1].split('source=')[1].split(',target=')[0]).parent)
            raise subprocess.TimeoutExpired(argv,240,output=b'{"passed":true,"checks":[]}',stderr=b'partial error')
        if argv[1:3]==['rm','-f']:
            children.clear();return Result(stdout='removed')
        if argv[1]=='inspect':return Result(returncode=1,stderr='Error: No such object')
        raise AssertionError(argv)
    monkeypatch.setattr(hive_verifier.shutil,'which',lambda _: '/usr/bin/docker')
    monkeypatch.setattr(hive_verifier.subprocess,'run',fake_run)
    report=hive_verifier.run_isolated(root,'full',diagnostics_dir=tmp_path/'trace')
    assert not report['passed'] and not children and all(not p.exists() for p in temporary)
    assert (tmp_path/'trace/stdout.log').read_text()=='{"passed":true,"checks":[]}'
    assert (tmp_path/'trace/stderr.log').read_text()=='partial error'
    events=[json.loads(x) for x in (tmp_path/'trace/verification-events.jsonl').read_text().splitlines()]
    phases=[e['phase'] for e in events]
    assert phases.index('timeout_fired')<phases.index('termination_requested')<phases.index('termination_result')<phases.index('cleanup_complete')
    assert next(e for e in events if e['phase']=='container_after_termination')['absence_confirmed']
    assert 'timed out' in report['checks'][0]['detail']


def test_container_events_retain_source_clock_and_host_order(tmp_path):
    trace=VerificationTrace(tmp_path/'candidate','targeted',tmp_path/'trace')
    event={'phase':'project_available','monotonic':12,'elapsed_ms':5,'wall_timestamp':'example','pid':1}
    script=f"import sys; print({'HIVE_VERIFIER_EVENT '+json.dumps(event)!r},file=sys.stderr,flush=True)"
    trace.capture([sys.executable,'-u','-c',script],timeout=5,docker='unused',container='synthetic')
    events=[json.loads(x) for x in (trace.root/'verification-events.jsonl').read_text().splitlines()]
    row=next(e for e in events if e['phase']=='project_available')
    assert row['source_event']['monotonic']==12 and row['clock_domain']=='host'
    assert trace.summary()['last_observed_phase']=='project_available'


def test_real_container_timeout_removes_descendant_tree(tmp_path,monkeypatch):
    """Real container teardown; synthetic sleeping processes, no model/J001 test."""
    docker=shutil.which('docker')
    if not docker:pytest.skip('Docker unavailable for container teardown integration test')
    try:
        cp=subprocess.run([docker,'image','inspect',hive_verifier.DEFAULT_IMAGE],capture_output=True,timeout=8)
    except (OSError,subprocess.TimeoutExpired):pytest.skip('Pinned verifier image unavailable')
    if cp.returncode:pytest.skip('Pinned verifier image unavailable')
    root=source_tree(tmp_path)
    # Only this synthetic test substitutes the container program. Production
    # gate entrypoints/commands have no substitution option. This isolates
    # lifecycle behavior from an unrelated legacy Python /work copystat error.
    script="import subprocess,sys,time,os; child=subprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(120)']); print('parent',os.getpid(),'child',child.pid,flush=True); time.sleep(120)"
    real_run=subprocess.run
    def synthetic_program(argv,**kwargs):
        if len(argv)>1 and argv[1]=='run':
            argv=[*argv[:-3],'--entrypoint','python3',argv[-3],'-u','-c',script]
            (tmp_path/'synthetic-command.json').write_text(json.dumps(argv))
        return real_run(argv,**kwargs)
    monkeypatch.setattr(hive_verifier.subprocess,'run',synthetic_program)
    report=hive_verifier.run_isolated(root,'targeted',['tests/test_ok.py'],timeout=20,diagnostics_dir=tmp_path/'real-trace')
    assert not report['passed'] and 'timed out' in report['checks'][0]['detail']
    events=[json.loads(x) for x in (tmp_path/'real-trace/verification-events.jsonl').read_text().splitlines()]
    sampled='\n'.join(s.get('stdout','') for e in events if e['phase']=='process_state' for s in e['samples'])
    assert 'time.sleep(120)' in sampled, 'actual descendant must be observed before teardown'
    assert next(e for e in events if e['phase']=='container_after_termination')['absence_confirmed']
    assert next(e for e in events if e['phase']=='cleanup_complete')['removed']
