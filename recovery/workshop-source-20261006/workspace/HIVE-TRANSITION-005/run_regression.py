import json,os,subprocess,sys,uuid,shutil
from pathlib import Path
from bootstrap import HERE,save,sha
sys.dont_write_bytecode=True
label=sys.argv[1] if len(sys.argv)>1 else 'complete'
root=HERE/'evidence/regression'/label;root.mkdir(parents=True,exist_ok=False)
save(root/'source-manifest.json',{p.relative_to(HERE/'repaired-workshop').as_posix():sha(p) for p in (HERE/'repaired-workshop').rglob('*.py') if '__pycache__' not in p.parts})
temp='D:/CodexTemp/hive-transition-005-'+uuid.uuid4().hex[:8]
env=dict(os.environ,PYTHONPATH=str(HERE.parent/'hive-transition-003/tooling/python'),PYTHONDONTWRITEBYTECODE='1')
env.pop('HIVE_NFRT_SEED_MANIFEST',None);env.pop('HIVE_NFRT_SEED_SHA256',None)
configuration=json.loads((HERE/'evidence/configuration.json').read_text())
env['HIVE_GRADLE_TEST_CACHE']=configuration['approved']['approved_cache_root']
env['HIVE_GRADLE_TEST_BASELINE']=configuration['freeze']['baseline']['root']
cmd=[sys.executable,'-m','pytest','-q','--tb=short','-rs','--basetemp='+temp]
cp=subprocess.run(cmd,cwd=HERE/'repaired-workshop',env=env,text=True,capture_output=True)
(root/'pytest.log').write_bytes((cp.stdout+cp.stderr).encode())
save(root/'result.json',{'command':cmd,'exit_code':cp.returncode,'scope':'Complete repository suite, including actual Docker timeout/descendant cleanup'})
for p in Path(temp).glob('test_real_container_timeout*/real-trace'):
 shutil.copytree(p,root/'container-timeout')
for p in Path(temp).glob('test_real_full_compilation*/actual-gradle-result.json'):
 shutil.copyfile(p,root/'actual-gradle-result.json')
print(cp.stdout+cp.stderr,flush=True)
raise SystemExit(cp.returncode)
