"""Complete available repository test suite, not just the former boundary subset."""
import json,os,subprocess,sys,uuid
from pathlib import Path
from setup_study import save
HERE=Path(__file__).resolve().parent
env=dict(os.environ,PYTHONPATH=str(HERE/'tooling/python'),PYTHONDONTWRITEBYTECODE='1')
cmd=[sys.executable,'-m','pytest','-q','--tb=short','-rs','--basetemp=D:/CodexTemp/hive-transition-003-'+uuid.uuid4().hex[:8]]
result=subprocess.run(cmd,cwd=HERE/'repaired-workshop',env=env,text=True,capture_output=True)
(HERE/'evidence/regression.log').write_bytes((result.stdout+result.stderr).encode())
save(HERE/'evidence/regression.json',{'command':cmd,'scope':'complete available repository suite','exit_code':result.returncode})
print(result.stdout+result.stderr,flush=True)
raise SystemExit(result.returncode)
