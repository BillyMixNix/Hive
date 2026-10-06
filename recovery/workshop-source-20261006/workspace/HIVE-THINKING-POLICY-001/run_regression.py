"""Full inherited suite; vendored test tooling and real verifier safety probes."""
import subprocess
from common import *

def main():
    label=sys.argv[1] if len(sys.argv)>1 else 'full-regression'
    out=HERE/'evidence'/label;out.mkdir(exist_ok=False)
    old=read(ROOT/'HIVE-FACTORIAL-003R1/FREEZE.json')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'hive-transition-003/tooling/python'),PYTHONDONTWRITEBYTECODE='1')
    env.pop('HIVE_NFRT_SEED_MANIFEST',None);env.pop('HIVE_NFRT_SEED_SHA256',None)
    env['HIVE_GRADLE_TEST_CACHE']=old['verifier']['approved_cache_root']
    env['HIVE_GRADLE_TEST_BASELINE']=old['baseline']['root']
    cmd=[sys.executable,'-B','-m','pytest','-q','--tb=short','-rs','-p','no:cacheprovider',
        '--basetemp='+str(HERE/'evidence'/(label+'-temp')),'--junitxml='+str(out/'pytest.xml')]
    with (out/'pytest.log').open('w',encoding='utf-8') as f:p=subprocess.run(cmd,cwd=SOURCE,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
    save(out/'result.json',{'command':cmd,'exit_code':p.returncode,'model_calls':0,'test_tooling':env['PYTHONPATH']})
    print((out/'pytest.log').read_text(encoding='utf-8')[-14000:],flush=True)
    raise SystemExit(p.returncode)

if __name__=='__main__':main()
