"""Complete the remaining validation after correcting isolated test setup."""
import subprocess
from common import *
def main():
    save(OUT/'FINAL-VALIDATION-STARTED.json',{'at':stamp(),'reason':'Exact archived fixture setup and intentional policy-equality assertion update; no additional runtime repair','model_calls':0})
    rows=[]
    for script,args in [('run_regression.py',['full-regression-final']),('run_real_controls.py',[])]:
        print('Starting',script,stamp(),flush=True)
        with (HERE/(script+'.final.log')).open('w',encoding='utf-8') as f:cp=subprocess.run([sys.executable,'-B','-u',str(HERE/script),*args],stdout=f,stderr=subprocess.STDOUT)
        rows.append({'script':script,'arguments':args,'exit_code':cp.returncode,'finished':stamp()});save(OUT/'final-validation-steps.json',rows)
        print('Completed',script,cp.returncode,stamp(),flush=True)
        if cp.returncode:raise SystemExit(cp.returncode)
if __name__=='__main__':main()
