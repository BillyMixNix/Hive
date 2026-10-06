"""Complete inherited Hive regression with established Docker/Gradle safety probes."""
import os,subprocess,uuid
from common import *
def main():
    label=sys.argv[1] if len(sys.argv)>1 else 'full-regression'
    out=OUT/label;out.mkdir(exist_ok=False)
    save(out/'source-inventory.json',inventory(SOURCE))
    env=dict(os.environ,PYTHONPATH=str(ROOT/'hive-transition-003/tooling/python'),PYTHONDONTWRITEBYTECODE='1')
    env.pop('HIVE_NFRT_SEED_MANIFEST',None);env.pop('HIVE_NFRT_SEED_SHA256',None)
    env['HIVE_GRADLE_TEST_CACHE']=str(CACHE);env['HIVE_GRADLE_TEST_BASELINE']=str(BASE)
    temp=OUT/(label+'-temp')
    cmd=[sys.executable,'-B','-m','pytest','-q','--tb=short','-rs','-p','no:cacheprovider','--basetemp='+str(temp),'--junitxml='+str(out/'pytest.xml')]
    with (out/'pytest.log').open('w',encoding='utf-8') as f:cp=subprocess.run(cmd,cwd=SOURCE,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
    save(out/'result.json',{'command':cmd,'exit_code':cp.returncode,'model_calls':0,'scope':'Complete Hive repository suite including actual Docker/Gradle safety probes'})
    print((out/'pytest.log').read_text(encoding='utf-8')[-16000:],flush=True)
    raise SystemExit(cp.returncode)
if __name__=='__main__':main()
