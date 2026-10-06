"""Task graph and inputs only. Never a verification result."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,'/opt/verifier')
import jvm_runner as j
config=json.loads(sys.argv[1])
work=Path('/work');home=work/'gradle-user-home'
j._event('input_probe_started')
j._copy_wrapper_distribution(Path('/approved-gradle-cache/wrapper/dists')/config['distribution'].removesuffix('.zip'),home,config['version'])
env={'JAVA_HOME':j.JAVA_HOME,'GRADLE_USER_HOME':str(home),'GRADLE_RO_DEP_CACHE':'/approved-gradle-cache',
     'HOME':'/work/home','TMPDIR':'/work/tmp','PATH':f'{j.JAVA_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','CI':'true'}
for rel in ['home','tmp']:(work/rel).mkdir()
for case in ['baseline','preserved']:
 project=work/case;shutil.copytree(Path('/source')/case,project)
 argv=[f'{j.JAVA_HOME}/bin/java','-Djava.io.tmpdir=/work/tmp','-classpath','gradle/wrapper/gradle-wrapper.jar',
  'org.gradle.wrapper.GradleWrapperMain','--no-daemon','--offline','--console=plain','--max-workers=2',
  '--rerun-tasks','--no-build-cache','-Dorg.gradle.jvmargs=-Xmx768m','--dry-run','-I','/probe/inputs.gradle',
  'test','--tests',config['frozen_tests'][0]['class_name']]
 j._event('input_probe_case',case=case,argv=argv)
 result=j._bounded_process(argv,cwd=project,env=env,timeout=120,max_log_bytes=200000)
 print(json.dumps({'case':case,'result':result,'verification':False}),flush=True)
 if result['returncode'] or result['timed_out']:raise SystemExit(1)
j._event('input_probe_complete')
