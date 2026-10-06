import json,os,subprocess,sys,uuid,shutil
from pathlib import Path
from setup_study import HERE,PRIOR,save,sha
sys.dont_write_bytecode=True
seal={'diagnosis_sha256':sha(HERE/'diagnosis.md'),
 'phase':'After initial measurements, before any behavioral repair/post-regression replay',
 'runtime_behavioral_repair':'none','source_manifest':{p.relative_to(HERE/'repaired-workshop').as_posix():sha(p)
    for p in (HERE/'repaired-workshop').rglob('*.py') if '__pycache__' not in p.parts}}
if not (HERE/'evidence/pre-replay-diagnosis-seal.json').exists():save(HERE/'evidence/pre-replay-diagnosis-seal.json',seal)
else:assert json.loads((HERE/'evidence/pre-replay-diagnosis-seal.json').read_text())['diagnosis_sha256']==seal['diagnosis_sha256']
save(HERE/'evidence/tested-source-manifest.json',seal['source_manifest'])
temp='D:/CodexTemp/hive-transition-004-'+uuid.uuid4().hex[:8]
env=dict(os.environ,PYTHONPATH=str(PRIOR/'tooling/python'),PYTHONDONTWRITEBYTECODE='1')
cmd=[sys.executable,'-m','pytest','-q','--tb=short','-rs','--basetemp='+temp]
cp=subprocess.run(cmd,cwd=HERE/'repaired-workshop',env=env,text=True,capture_output=True)
(HERE/'evidence/regression.log').write_bytes((cp.stdout+cp.stderr).encode())
save(HERE/'evidence/regression.json',{'command':cmd,'exit_code':cp.returncode,'scope':'Complete available repository suite, including real container teardown integration test'})
for p in Path(temp).glob('test_real_container_timeout*/real-trace'):
 shutil.copytree(p,HERE/'evidence/regression-container-timeout',dirs_exist_ok=True)
 if (p.parent/'synthetic-command.json').exists():shutil.copy2(p.parent/'synthetic-command.json',HERE/'evidence/regression-container-timeout/synthetic-command.json')
print(cp.stdout+cp.stderr,flush=True)
raise SystemExit(cp.returncode)
