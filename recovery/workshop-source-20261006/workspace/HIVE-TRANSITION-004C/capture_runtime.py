import json,subprocess,sys
from pathlib import Path
from bootstrap import HERE,save
label=sys.argv[1];root=HERE/'evidence/runs'/label
inv=json.loads((root/'diagnostics/invocation.json').read_text())
code=r'''
import json,pathlib,time
mounts=[l for l in pathlib.Path('/proc/self/mountinfo').read_text().splitlines() if any(s in l for s in ['/approved-gradle-cache',' /work ',' /source '])]
p=pathlib.Path('/work/candidate/build')
classes=list((p/'classes/java/main').rglob('*.class'));generated=list((p/'generated').rglob('*.java'))
print(json.dumps({'time':time.time(),'mountinfo':mounts,'main_classes':len(classes),'class_bytes':sum(f.stat().st_size for f in classes),'generated_java':[str(f) for f in generated],'test_classes':len(list((p/'classes/java/test').rglob('*.class')))}))
'''
cp=subprocess.run([inv['argv'][0],'exec',inv['container'],'python3','-c',code],capture_output=True,text=True,timeout=8)
save(root/f'runtime-observation-{sys.argv[2]}.json',{'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr})
print(cp.stdout)
