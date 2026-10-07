"""Trusted acquisition step, not acceptance verification. No frozen tests loaded."""
import hashlib
import json
import shutil
from pathlib import Path

from jvm_runner import _bounded_process, _source_digest
from prime_runner import _validate_profile


def main():
    config = json.loads(Path('/profile.json').read_bytes())
    source = Path('/source')
    _validate_profile(source, config)  # Unchanged wrapper and acceptance-policy identity.
    before = _source_digest(source)
    project = Path('/work/candidate')
    shutil.copytree(source, project)
    Path('/tmp/home').mkdir()
    Path('/tmp/tmp').mkdir()
    env = {'JAVA_HOME': '/opt/java/openjdk', 'GRADLE_USER_HOME': '/approved-gradle-cache',
           'HOME': '/tmp/home', 'TMPDIR': '/tmp/tmp', 'LANG': 'C.UTF-8', 'CI': 'true',
           'PATH': '/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin'}
    # Resolve only the inputs needed for J001. No hidden acceptance source here.
    argv = ['/opt/java/openjdk/bin/java', '-Djava.io.tmpdir=/tmp/tmp', '-classpath',
            'gradle/wrapper/gradle-wrapper.jar', 'org.gradle.wrapper.GradleWrapperMain',
            '--no-daemon', '--console=plain', '--info', '--max-workers=2',
            '--no-build-cache', '-Dorg.gradle.jvmargs=-Xmx768m',
            'createMinecraftArtifacts', 'testClasses']
    result = _bounded_process(argv, cwd=project, env=env, timeout=1500,
                              max_log_bytes=12000)
    unchanged = _source_digest(source) == before
    print(json.dumps({'priming_succeeded': result['returncode'] == 0 and not result['timed_out'] and unchanged,
                      'source_unchanged': unchanged, 'timed_out': result['timed_out'],
                      'returncode': result['returncode'], 'wall_seconds': result['wall_seconds'],
                      'stdout_sha256': hashlib.sha256(result['stdout'].encode()).hexdigest(),
                      'stderr_sha256': hashlib.sha256(result['stderr'].encode()).hexdigest()}))


if __name__ == '__main__':
    main()
