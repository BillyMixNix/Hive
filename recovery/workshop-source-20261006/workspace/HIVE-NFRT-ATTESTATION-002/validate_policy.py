"""Sequential preflight, complete regression, then real controls. No inference."""
import subprocess
from common import *
def main():
    assert not (OUT/'VALIDATION-STARTED.json').exists();save(OUT/'VALIDATION-STARTED.json',{'at':stamp(),'model_calls':0})
    rows=[]
    for script in ['preflight_scopes.py','run_regression.py','run_real_controls.py']:
        print('Starting',script,stamp(),flush=True)
        with (HERE/(script+'.log')).open('w',encoding='utf-8') as f:cp=subprocess.run([sys.executable,'-B','-u',str(HERE/script)],stdout=f,stderr=subprocess.STDOUT)
        rows.append({'script':script,'exit_code':cp.returncode,'finished':stamp()});save(OUT/'validation-steps.json',rows)
        print('Completed',script,cp.returncode,stamp(),flush=True)
        if cp.returncode:raise SystemExit(cp.returncode)
if __name__=='__main__':main()
