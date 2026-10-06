"""Actual pinned Gradle compiler control; synthetic probe, not acceptance evidence."""
import json,os,shutil,subprocess,uuid
from pathlib import Path
import pytest
from verification import jvm_runner
from workshop import hive_verifier

def test_policy_is_private_and_does_not_change_source(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'App.java').write_text('class App {}')
    before=(source/'App.java').read_bytes()
    home=tmp_path/'private-gradle-home'
    jvm_runner._install_fresh_compilation_policy(home)
    assert (source/'App.java').read_bytes()==before
    assert list(source.iterdir())==[source/'App.java']
    assert (home/'init.d/hive-fresh-compilation.gradle').read_text()==jvm_runner.FRESH_COMPILATION_POLICY

PROBE=r'''
import json,os,pathlib,shutil,subprocess,sys
sys.path.insert(0,'/probe');import jvm_runner as runner
p=pathlib.Path('/work/probe');p.mkdir()
shutil.copytree('/baseline/gradle',p/'gradle')
home=pathlib.Path('/work/gradle-home')
runner._copy_wrapper_distribution(pathlib.Path('/approved/wrapper/dists/gradle-9.2.1-bin'),home,'9.2.1')
runner._install_fresh_compilation_policy(home)
(p/'settings.gradle').write_text("rootProject.name='synthetic-verifier-policy'")
(p/'build.gradle').write_text("plugins { id 'java' }; tasks.withType(JavaCompile).configureEach { doFirst { assert !options.incremental; println 'HIVE_TEST_FULL_COMPILATION' } }")
src=p/'src/main/java/Demo.java';src.parent.mkdir(parents=True)
env=dict(os.environ,GRADLE_USER_HOME=str(home),HOME='/work',TMPDIR='/work',JAVA_HOME='/opt/java/openjdk')
argv=['/opt/java/openjdk/bin/java','-Djava.io.tmpdir=/work','-classpath','gradle/wrapper/gradle-wrapper.jar','org.gradle.wrapper.GradleWrapperMain','--no-daemon','--offline','--console=plain','--max-workers=2','--rerun-tasks','--no-build-cache','-Dorg.gradle.jvmargs=-Xmx768m','compileJava']
src.write_text('public class Demo { public static int value() { return 17; } }')
ok=subprocess.run(argv,cwd=p,env=env,capture_output=True,text=True,timeout=90)
first={'returncode':ok.returncode,'stdout':ok.stdout,'stderr':ok.stderr,'class_created':(p/'build/classes/java/main/Demo.class').is_file()}
src.write_text('public class Demo { invalid syntax }')
bad=subprocess.run(argv,cwd=p,env=env,capture_output=True,text=True,timeout=90)
second={'returncode':bad.returncode,'stdout':bad.stdout,'stderr':bad.stderr,'old_class_retained':(p/'build/classes/java/main/Demo.class').exists()}
print(json.dumps({'first':first,'second':second}))
'''

def test_real_full_compilation_and_invalid_source_rejection(tmp_path):
    docker=shutil.which('docker');baseline=os.environ.get('HIVE_GRADLE_TEST_BASELINE');cache=os.environ.get('HIVE_GRADLE_TEST_CACHE')
    if not docker or not baseline or not cache:pytest.skip('Explicit approved Gradle test fixtures unavailable')
    script=tmp_path/'probe.py';script.write_text(PROBE)
    name='hive-full-compile-test-'+uuid.uuid4().hex[:10]
    command=[docker,'run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL',
       '--security-opt','no-new-privileges','--pids-limit','448','--cpus','2','--memory','4g','--memory-swap','4g',
       '--tmpfs','/work:rw,size=2g,mode=1777','--tmpfs','/tmp:rw,size=128m,mode=1777','--env','PYTHONDONTWRITEBYTECODE=1']
    for host,target in [(Path(jvm_runner.__file__).parent,'/probe'),(Path(baseline),'/baseline'),(Path(cache),'/approved'),(script,'/probe-test.py')]:
        command+=['--mount',f'type=bind,source={host},target={target},readonly']
    command+=['--entrypoint','python3',hive_verifier.DEFAULT_IMAGE,'/probe-test.py']
    try:cp=subprocess.run(command,capture_output=True,text=True,timeout=200)
    finally:subprocess.run([docker,'rm','-f',name],capture_output=True,timeout=10)
    (tmp_path/'actual-gradle-result.json').write_text(cp.stdout)
    assert cp.returncode==0,cp.stderr
    result=json.loads(cp.stdout)
    assert result['first']['returncode']==0 and result['first']['class_created'],result
    assert 'HIVE_TEST_FULL_COMPILATION' in result['first']['stdout']
    assert result['second']['returncode']!=0 and 'error:' in result['second']['stderr'],result
    assert not result['second']['old_class_retained']
