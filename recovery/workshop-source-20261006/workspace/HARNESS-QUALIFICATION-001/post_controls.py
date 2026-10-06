"""Sequential remaining qualification only; never runs a model or factorial."""
import subprocess,sys,json
from qcommon import *
def main():
    assert (HERE/'evidence/controls/comparison.json').exists(),'Real A/B controls must finish first'
    with (HERE/'evidence/POST-CONTROLS-STARTED.json').open('x') as f:json.dump({'at':stamp(),'model_calls':0},f)
    commands=[('nfrt-preflight',[sys.executable,'-B','-u',str(HERE/'nfrt_preflight.py')]),
        ('final-unit-tests',[sys.executable,'-B','-m','pytest',str(HERE/'test_recorder.py'),str(HERE/'test_cell_harness.py'),str(HERE/'test_orchestration.py'),'-q','-p','no:cacheprovider',f'--basetemp={HERE}/evidence/final-unit-temp',f'--junitxml={HERE}/evidence/final-unit-tests.xml']),
        ('real-scripted-cell',[sys.executable,'-B','-u',str(HERE/'run_dry_cell.py')]),
        ('final-audit',[sys.executable,'-B','-u',str(HERE/'audit_after.py')])]
    rows=[]
    for name,cmd in commands:
        print(json.dumps({'event':'qualification_step_started','step':name,'at':stamp()}),flush=True)
        with (HERE/(name+'.log')).open('w',encoding='utf-8') as stream:cp=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT)
        row={'step':name,'command':cmd,'exit_code':cp.returncode,'finished_at':stamp()};rows.append(row);save(HERE/'evidence/post-controls-steps.json',rows)
        print(json.dumps(row),flush=True)
        if cp.returncode:raise SystemExit(cp.returncode)
if __name__=='__main__':main()
