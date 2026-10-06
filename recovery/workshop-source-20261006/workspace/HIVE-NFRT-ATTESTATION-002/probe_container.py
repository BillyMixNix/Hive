"""Offline diagnostic input capture only. No reconstruction/compile/test task executes."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,'/opt/verifier')
import jvm_runner as j
cfg=json.loads(sys.argv[1]);work=Path('/work');home=work/'gradle-user-home'
j._copy_wrapper_distribution(Path('/approved-gradle-cache/wrapper/dists')/cfg['distribution'].removesuffix('.zip'),home,cfg['version'])
for n in ['home','tmp']:(work/n).mkdir()
env={'JAVA_HOME':j.JAVA_HOME,'GRADLE_USER_HOME':str(home),'GRADLE_RO_DEP_CACHE':'/approved-gradle-cache',
     'HOME':'/work/home','TMPDIR':'/work/tmp','PATH':f'{j.JAVA_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','CI':'true'}
for case in cfg['probe_cases']:
    project=work/case;shutil.copytree(Path('/source')/case,project)
    argv=[f'{j.JAVA_HOME}/bin/java','-Djava.io.tmpdir=/work/tmp','-classpath','gradle/wrapper/gradle-wrapper.jar',
        'org.gradle.wrapper.GradleWrapperMain','--no-daemon','--offline','--console=plain','--max-workers=2',
        '--rerun-tasks','--no-build-cache','-Dorg.gradle.jvmargs=-Xmx768m','--dry-run','-I','/probe/inputs.gradle','createMinecraftArtifacts']
    result=j._bounded_process(argv,cwd=project,env=env,timeout=120,max_log_bytes=220000)
    print(json.dumps({'case':case,'result':result,'argv':argv,'diagnostic_only':True,'verification':False}),flush=True)
