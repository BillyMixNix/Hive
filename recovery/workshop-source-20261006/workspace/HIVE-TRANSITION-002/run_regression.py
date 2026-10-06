import json, subprocess, uuid
from pathlib import Path
from diagnostic_capture import save
HERE=Path(__file__).resolve().parent
previous=json.loads((HERE.parent/'HIVE-TRANSITION-001/evidence/regression-final.json').read_text())
command=previous['command']
command=[c for c in command if not c.startswith('--basetemp=')]
command.insert(3,'tests/test_planning_input_fidelity.py')
command.append('--basetemp=D:/CodexTemp/hive-transition-002-'+uuid.uuid4().hex[:8])
result=subprocess.run(command,cwd=HERE/'repaired-workshop',text=True,capture_output=True)
(HERE/'evidence/regression.log').write_bytes((result.stdout+result.stderr).encode())
save(HERE/'evidence/regression.json',{'command':command,'exit_code':result.returncode})
print(result.stdout+result.stderr)
raise SystemExit(result.returncode)
