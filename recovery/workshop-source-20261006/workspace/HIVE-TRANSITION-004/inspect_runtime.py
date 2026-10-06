"""Read the frozen verifier image/configuration; no verification or generation."""
import json,subprocess,sys
from pathlib import Path
from setup_study import HERE,PRIOR,save,sha
sys.dont_write_bytecode=True
freeze=json.loads((PRIOR/'FREEZE.json').read_text())
image=freeze['verifier_image_id']
out=HERE/'evidence/image';out.mkdir(exist_ok=False)
def docker(*argv):return subprocess.run(['docker',*argv],capture_output=True,timeout=30,check=True).stdout
config=json.loads(docker('image','inspect',image,'--format','{{json .Config}}'))
save(out/'config.json',config)
base=['run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges']
for name in ('runner.py','jvm_runner.py'):
 data=docker(*base,'--entrypoint','cat',image,'/opt/verifier/'+name)
 (out/name).write_bytes(data)
 assert sha(out/name)==sha(HERE/'repaired-workshop/verification'/name),(name,'image/source mismatch')
cp=subprocess.run(['docker',*base,'--entrypoint','/opt/java/openjdk/bin/java',image,'-version'],capture_output=True,timeout=30)
save(out/'java-version.json',{'returncode':cp.returncode,'stdout':cp.stdout.decode(),'stderr':cp.stderr.decode(),
 'note':'Post-hoc observation of identical pinned image, not a historical Java invocation log.'})
save(out/'runtime.json',json.loads(docker('info','--format','{{json .}}')) if False else {
 'image_id':image,'docker_server':docker('info','--format','{{.ServerVersion}}').decode().strip(),
 'host_cwd':str(Path.cwd()),'source_identity_verified':True})
print('Pinned image source and Java inspected; no verification run.')
