"""Run the complete inherited suite using the established isolated test harness."""
import hashlib,json,os,subprocess,sys,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
label=sys.argv[1]
out=HERE/'evidence'/label
out.mkdir(exist_ok=False)
source=HERE/'repaired-workshop'
manifest={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*.py') if '__pycache__' not in p.parts}
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
configuration=json.loads((HERE.parent/'HIVE-TRANSITION-005/evidence/configuration.json').read_text())
env=dict(os.environ,PYTHONPATH=str(HERE.parent/'hive-transition-003/tooling/python'),PYTHONDONTWRITEBYTECODE='1')
env.pop('HIVE_NFRT_SEED_MANIFEST',None);env.pop('HIVE_NFRT_SEED_SHA256',None)
env['HIVE_GRADLE_TEST_CACHE']=configuration['approved']['approved_cache_root']
env['HIVE_GRADLE_TEST_BASELINE']=configuration['freeze']['baseline']['root']
temp='D:/CodexTemp/hive-reviewer-policy-001-'+uuid.uuid4().hex[:8]
cmd=[sys.executable,'-B','-m','pytest','-q','--tb=short','-rs','-p','no:cacheprovider','--basetemp='+temp,'--junitxml='+str(out/'pytest.xml')]
with (out/'pytest.log').open('w',encoding='utf-8') as log:
    cp=subprocess.run(cmd,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
(out/'result.json').write_text(json.dumps({'command':cmd,'exit_code':cp.returncode,'scope':'Complete repository suite; no model calls; includes inherited real Docker/Gradle safety probes','temp':temp},indent=2))
print((out/'pytest.log').read_text(encoding='utf-8')[-18000:])
raise SystemExit(cp.returncode)
