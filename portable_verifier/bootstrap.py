"""Fail-closed, model-free J001 reconstruction from an empty cloud/VM root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .acquire import ROOT, CORPUS, GRADLE, JDK, catalog, digest, acquire

ANCHOR = 'f93a6c2f79d25d24bdea1b171cd82a6b1f336667'
OLD_IMAGE = 'sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26'
BASELINE = CORPUS / 'external/m3.2-baseline'
BASELINE_SHA = '230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388'
TEST_SHA = '80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159'
IMAGE_TAG = 'nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy'
EXPECTED = {'tests': 3, 'failures': 1, 'errors': 0, 'skipped': 0, 'timed_out': False}


def command(argv, timeout=30):
    # Only an allowlist of operational environment variables; no inherited secrets.
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'HOME') if k in os.environ}
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          timeout=timeout, env=env)


def source_identity(expected_commit):
    if len(expected_commit) != 40 or any(c not in '0123456789abcdef' for c in expected_commit):
        raise ValueError('expected commit must be a full Git SHA')
    actual = command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).stdout.strip()
    if actual != expected_commit:
        raise ValueError('checkout commit mismatch')
    protected = ['hive_canonical', 'hive_remote', 'recovery', 'tests/recovery',
                 'tests/remote_api', '.github/workflows/hive-remote-api.yml']
    if command(['git', '-C', str(ROOT), 'diff', '--name-only', ANCHOR, 'HEAD', '--', *protected]).stdout.strip():
        raise ValueError('protected experiment source changed from published anchor')
    if command(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=no']).stdout.strip():
        raise ValueError('tracked checkout is dirty')
    if command(['git', '-C', str(ROOT), 'ls-files', '--others', '--exclude-standard']).stdout.strip():
        raise ValueError('unexpected untracked checkout files')
    return actual


def wrapper(rows, archive, root):
    if digest(archive) != GRADLE['sha256']:
        raise ValueError('Gradle ZIP mismatch')
    with zipfile.ZipFile(archive) as zip:
        for row in rows:
            relative = '/'.join(row['path'].split('/')[4:])
            if row['size'] == 0 and row['path'].endswith(('.ok', '.lck')):
                data = b''
            else:
                data = zip.read(relative)
            if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('extracted Gradle file mismatch')
            target = root / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if target.name == 'gradle':
                target.chmod(0o755)
            if digest(target) != row['sha256']:
                raise ValueError('Gradle destination file mismatch')
    return {'files': len(rows), 'status': 'BYTE_IDENTICAL', 'classification': 'REPRODUCIBLE_FROM_PINNED_INPUTS'}


def compare_rows(root, rows):
    results = []
    for row in rows:
        p = root / row['path']
        results.append({'path': row['path'], 'expected_sha256': row['sha256'],
                        'actual_sha256': digest(p) if p.is_file() and not p.is_symlink() else None,
                        'matches': p.is_file() and not p.is_symlink() and p.stat().st_size == row['size'] and digest(p) == row['sha256']})
    return results


def baseline_outcome(result, test_class):
    counts = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0, 'timed_out': False}
    reported_classes = []
    checks = result.get('checks', [])
    for check in checks:
        detail = check.get('detail', {})
        if isinstance(detail, dict):
            counts['timed_out'] |= bool(detail.get('timed_out'))
            for row in detail.get('tests', []):
                reported_classes.append(row.get('class_name'))
                for name in ('tests', 'failures', 'errors', 'skipped'):
                    counts[name] += row.get(name, 0)
    isolated = result.get('isolation', {})
    correct_isolation = all(isolated.get(k) == v for k, v in {
        'backend': 'docker', 'available': True, 'network': 'none', 'rootfs': 'readonly',
        'source': 'sanitized-readonly', 'workspace': 'tmpfs'}.items())
    correct_limits = all(isolated.get('limits', {}).get(k) == v for k, v in {
        'pids': 448, 'memory': '4g', 'memory_swap': '4g', 'cpus': 2}.items())
    acceptance = [x for x in checks if x.get('name') == 'frozen_junit_acceptance']
    qualified = (counts == EXPECTED and result.get('passed') is False
                 and reported_classes == [test_class] and correct_isolation and correct_limits
                 and {x.get('name') for x in checks if x.get('passed') is not True} == {'frozen_junit_acceptance'}
                 and len(acceptance) == 1 and acceptance[0].get('detail', {}).get('returncode') == 1
                 and not acceptance[0].get('detail', {}).get('report_error'))
    return counts, qualified


def build_image(downloads, work, evidence):
    if digest(downloads / JDK['name']) != JDK['sha256']:
        raise ValueError('JDK archive identity mismatch')
    context = work / 'image-context'
    context.mkdir()
    with tarfile.open(downloads / JDK['name']) as tar:
        tar.extractall(context / 'jdk-extraction', filter='data')
    roots = list((context / 'jdk-extraction').iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('ambiguous JDK archive')
    roots[0].rename(context / 'jdk')
    (context / 'jdk-extraction').rmdir()
    for name in ('runner.py', 'jvm_runner.py', 'prime_runner.py'):
        shutil.copyfile(ROOT / 'hive_canonical/legacy/verification' / name, context / name)
    for name in ('Dockerfile', 'prime_inputs.py', 'redact.py'):
        shutil.copyfile(ROOT / 'portable_verifier' / name, context / name)
    command(['docker', 'build', '--network=none', '--platform=linux/amd64', '-t', IMAGE_TAG, str(context)], timeout=600)
    image = command(['docker', 'image', 'inspect', IMAGE_TAG, '--format', '{{.Id}}']).stdout.strip()
    java = command(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL',
                    '--security-opt=no-new-privileges', '--entrypoint', '/opt/java/openjdk/bin/java', image, '-version'])
    if '21.0.12.1' not in java.stderr:
        raise ValueError('JDK release mismatch')
    evidence['image'] = {'image_id': image, 'historical_image_id': OLD_IMAGE, 'matches_historical': image == OLD_IMAGE,
                         'base_manifest': 'sha256:de572b33eae61a53675a87bbd02b5e365df7b6b2b06c9276124e965cec08c452',
                         'java_version': java.stderr.strip(), 'container_python': '3.13.14',
                         'classification': 'DIFFERENT_ENVIRONMENT', 'historical_exact_classification': 'MISSING_PROVENANCE'}
    python = command(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL',
                       '--security-opt=no-new-privileges', '--entrypoint', 'python3', image,
                       '-I', '-S', '-c', 'import platform; print(platform.python_version())']).stdout.strip()
    if python != '3.13.14':
        raise ValueError('container Python version mismatch')
    evidence['image']['container_python'] = python
    return image


def reconstruct_launcher(downloads, c):
    """Functional discovery index for ONLY 1.21.1, derived from pinned metadata.

    Not the old global launcher index. Its new digest enters the new apparatus
    manifest. No archive snapshot or old host bytes are used.
    """
    row = next(r for r in c['native'] if r['path'].endswith('minecraft_1.21.1_version_manifest.json'))
    path = downloads / row['path']
    if digest(path) != row['sha256']:
        raise ValueError('version metadata not pinned')
    version = json.loads(path.read_bytes())
    item = {k: version[k] for k in ('id', 'type', 'time', 'releaseTime')}
    if item['id'] != '1.21.1':
        raise ValueError('unexpected Minecraft version')
    item.update({'url': row['urls'][0], 'sha1': hashlib.sha1(path.read_bytes()).hexdigest(),
                 'complianceLevel': version.get('complianceLevel', 1)})
    raw = json.dumps({'latest': {'release': '1.21.1', 'snapshot': '1.21.1'}, 'versions': [item]},
                     sort_keys=True, separators=(',', ':')).encode()
    target = downloads / 'caches/neoformruntime/artifacts/minecraft_launcher_manifest.json'
    target.write_bytes(raw)
    old = next(r for r in c['native'] if r['path'].endswith('minecraft_launcher_manifest.json'))
    return {'path': old['path'], 'sha256': digest(target), 'historical_sha256': old['sha256'],
            'size': len(raw), 'matches_historical': digest(target) == old['sha256'],
            'status': 'FUNCTIONALLY_RECONSTRUCTED', 'classification': 'REPRODUCIBLE_FROM_PINNED_INPUTS',
            'input_sha256': row['sha256'], 'scope': '1.21.1-only discovery index; no other versions'}


def functional_baseline(downloads, work, c, evidence):
    # This does not reuse RECOVERY-002, the old Python attestation, or an old seed.
    if not shutil.which('docker'):
        raise RuntimeError('DOCKER_UNAVAILABLE')
    info = json.loads(command(['docker', 'info', '--format', '{{json .}}']).stdout)
    evidence['docker'] = {k: info.get(k) for k in ('ServerVersion', 'Driver', 'CgroupVersion', 'OSType', 'Architecture', 'NCPU', 'MemTotal')}
    from hive_canonical.legacy.workshop import hive_jvm, hive_verifier, external_root
    from hive_canonical.legacy.verification import prime_gradle_cache as prime
    if external_root.tree_sha256(BASELINE) != BASELINE_SHA:
        raise ValueError('baseline identity mismatch')
    freeze = json.loads((CORPUS / 'workspace/HIVE-FACTORIAL-003R1/FREEZE.json').read_bytes())
    profile = hive_jvm.inspect_gradle_project(BASELINE)
    if profile != freeze['verifier']['jvm_profile']:
        raise ValueError('unchanged verifier profile mismatch')
    task = next(t for t in freeze['tasks'] if t['id'] == 'J001')
    hidden = CORPUS / 'external/historical-work/HIVE-FACTORIAL-001/hidden-tests' / task['test_filename']
    if digest(hidden) != TEST_SHA:
        raise ValueError('frozen test identity mismatch')
    image = build_image(downloads, work, evidence)
    run_id = os.urandom(6).hex()
    cache = work / 'hive_runs/approved-gradle-caches' / run_id
    sibling = work / 'hive_runs' / run_id
    cache.mkdir(parents=True)
    sibling.mkdir()
    shutil.copytree(downloads / 'caches', cache / 'caches')
    evidence['wrapper'] = wrapper(c['wrapper'], downloads / GRADLE['name'], cache)
    # Readonly mount destinations retain the verifier's qualified namespace.
    for p in cache.rglob('*'):
        p.chmod(0o777 if p.is_dir() else 0o666)
    cache.chmod(0o777)
    (cache / 'wrapper').chmod(0o777)
    # On Linux, chmod alone does not authorize utimensat with explicit times.
    # NFRT sets Last-Modified timestamps even on byte-verified cached inputs.
    # This fixed maintenance process sees ONLY the fresh cache, no candidate or
    # frozen tests. CAP_CHOWN is absent from priming and acceptance containers.
    ownership_script = (
        'import os,stat; from pathlib import Path; root=Path("/owned-cache"); '
        'paths=[root,*root.rglob("*")]; '
        'assert all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in paths); '
        '[os.chown(p,65532,65532,follow_symlinks=False) for p in paths]'
    )
    command(['docker', 'run', '--rm', '--network=none', '--read-only', '--user=0:0',
             '--cap-drop=ALL', '--cap-add=CHOWN', '--security-opt=no-new-privileges',
             '--mount', f'type=bind,source={cache},target=/owned-cache',
             '--entrypoint=python3', image, '-I', '-S', '-c', ownership_script], timeout=60)
    evidence['cache_ownership'] = {'uid': 65532, 'gid': 65532, 'scope': 'fresh run-owned cache only',
                                   'phase': 'fixed maintenance; no candidate execution',
                                   'priming_caps': 'ALL_DROPPED', 'verifier_caps': 'ALL_DROPPED'}
    profile_file = work / 'profile.json'
    profile_file.write_text(json.dumps(profile))
    cmd = ['docker', 'run', '--rm', '--network=bridge', '--read-only', '--cap-drop=ALL',
           '--security-opt=no-new-privileges', '--pids-limit=448', '--memory=4g', '--memory-swap=4g', '--cpus=2',
           '--tmpfs=/work:rw,nosuid,nodev,size=4g,mode=1777', '--tmpfs=/tmp:rw,nosuid,nodev,size=128m,mode=1777',
           '--mount', f'type=bind,source={BASELINE},target=/source,readonly',
           '--mount', f'type=bind,source={profile_file},target=/profile.json,readonly',
           '--mount', f'type=bind,source={cache},target=/approved-gradle-cache',
           '--entrypoint=python3', image, '/opt/verifier/prime_inputs.py']
    primed = command(cmd, timeout=1560)
    evidence['priming'] = json.loads(primed.stdout)
    if evidence['priming'].get('priming_succeeded') is not True:
        raise RuntimeError('PINNED_INPUT_PRIMING_FAILED')
    # Generated Gradle metadata is inventoried separately, never called exact.
    module_comparison = compare_rows(cache, c['modules'])
    native_comparison = compare_rows(cache, c['native'])
    launcher = evidence.get('functional_launcher')
    if launcher:
        native_comparison = [x for x in native_comparison if x['path'] != launcher['path']]
        if digest(cache / launcher['path']) != launcher['sha256']:
            raise RuntimeError('PRIMING_CHANGED_FUNCTIONAL_LAUNCHER')
    known_modules = {r['path'] for r in c['modules']}
    actual_modules = {p.relative_to(cache).as_posix() for p in (cache / 'caches/modules-2/files-2.1').rglob('*') if p.is_file()}
    if not all(x['matches'] for x in module_comparison + native_comparison) or actual_modules != known_modules:
        raise RuntimeError('PRIMING_CHANGED_PINNED_INPUTS')
    evidence['nfrt_comparison'] = compare_rows(cache / 'caches/neoformruntime/intermediate_results', c['nfrt_intermediates'])
    evidence['cache_metadata_comparison'] = compare_rows(cache, c['generated_gradle_metadata'])
    evidence['generated_cache_inventory'] = prime._inventory_cache(cache)
    now = datetime.now(timezone.utc).isoformat()
    manifest, provenance = prime.build_external_build_input_records(cache, profile, baseline_sha256=BASELINE_SHA,
                        container_image_id=image, observed_urls=[], acquisition_started_utc=evidence['started_utc'],
                        acquisition_ended_utc=now, priming_command=['createMinecraftArtifacts', 'testClasses'])
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    provenance.update({'external_build_inputs_manifest_sha256': hashlib.sha256(raw).hexdigest(), 'cache_priming_succeeded': True})
    (sibling / 'external-build-inputs.manifest.json').write_bytes(raw)
    (sibling / 'external-build-inputs.provenance.json').write_text(json.dumps(provenance))
    # Use the unchanged verifier's existing no-seed reconstruction policy.
    for key in ('HIVE_NFRT_SEED_MANIFEST', 'HIVE_NFRT_SEED_SHA256', 'NIX_HIVE_VERIFIER_IMAGE'):
        os.environ.pop(key, None)
    os.environ['GRADLE_USER_HOME'] = str(cache)
    frozen = hive_jvm.freeze_junit_tests(BASELINE, [{'path': task['test_path'], 'class_name': task['test_class'],
             'expected_cases': task['test_cases'], 'source': hidden.read_text(encoding='utf-8')}])
    metadata = hive_jvm.store_frozen_junit_tests(frozen, work / 'frozen-j001')
    started = time.monotonic()
    result = hive_verifier.run_isolated(BASELINE, 'targeted', [], timeout=240, external_root=True,
                    frozen_junit_tests=metadata, expected_jvm_profile=profile,
                    expected_external_baseline_sha256=BASELINE_SHA, diagnostics_dir=work / 'private-diagnostics')
    evidence['verifier_result_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    evidence['targeted_elapsed_seconds'] = round(time.monotonic() - started, 3)
    counts, qualified = baseline_outcome(result, task['test_class'])
    evidence['baseline_result'] = counts
    evidence['baseline_matches_host_bound'] = qualified
    evidence['isolation'] = result.get('isolation', {})
    if external_root.tree_sha256(BASELINE) != BASELINE_SHA or digest(hidden) != TEST_SHA:
        raise RuntimeError('SOURCE_CHANGED_DURING_VERIFICATION')
    if not evidence['baseline_matches_host_bound']:
        raise RuntimeError('J001_BASELINE_NOT_REPRODUCED')
    evidence['classification'] = 'FUNCTIONALLY_RECONSTRUCTED'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['acquire', 'functional-baseline'])
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = {'schema': 1, 'experiment': 'PORTABLE-VERIFIER-001', 'model_calls': 0, 'task_id': 'J001',
                'historical_anchor': ANCHOR, 'baseline_sha256': BASELINE_SHA, 'frozen_test_sha256': TEST_SHA,
                'expected_baseline': EXPECTED, 'classification': 'UNAVAILABLE', 'baseline_matches_host_bound': False,
                'host_local_payloads_used': False, 'python': platform.python_version(), 'system': platform.system(),
                'machine': platform.machine(), 'full_verification': 'NOT_REQUESTED', 'promotion': 'UNAVAILABLE',
                'started_utc': datetime.now(timezone.utc).isoformat()}
    try:
        evidence['git_commit'] = source_identity(args.expected_commit)
        if args.mode == 'functional-baseline' and not shutil.which('docker'):
            raise RuntimeError('DOCKER_UNAVAILABLE')
        if args.root.exists():
            raise ValueError('bootstrap root must not exist')
        args.root.mkdir(parents=True)
        c = catalog()
        rows = [GRADLE, JDK] + c['modules'] + c['native']
        downloads = args.root / 'downloads'
        evidence['acquisition'] = acquire(rows, downloads, workers=24)
        failed = [r for r in evidence['acquisition'] if r['status'] not in ('BYTE_IDENTICAL', 'VERIFIED_EXISTING')]
        launcher_path = 'caches/neoformruntime/artifacts/minecraft_launcher_manifest.json'
        if args.mode == 'functional-baseline' and failed and all(r['path'] == launcher_path for r in failed):
            evidence['functional_launcher'] = reconstruct_launcher(downloads, c)
            failed = []
        if failed:
            raise RuntimeError('PINNED_INPUT_UNAVAILABLE')
        if args.mode == 'functional-baseline':
            work = args.root / 'work'
            work.mkdir()
            functional_baseline(downloads, work, c, evidence)
        else:
            evidence['classification'] = 'PINNED_DOWNLOADS_ACQUIRED_ONLY'
    except Exception as exc:
        # Paths, stderr, credential values and private platform identifiers excluded.
        evidence['blocker'] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    evidence['ended_utc'] = datetime.now(timezone.utc).isoformat()
    # Hash loaded runtime inputs, using relative public names rather than paths.
    runtime = []
    stdlib_root = Path(os.__file__).resolve().parent
    for module in list(sys.modules.values()):
        file = getattr(module, '__file__', None)
        if file:
            p = Path(file).resolve()
            try:
                name = p.relative_to(stdlib_root).as_posix()
            except ValueError:
                continue
            if p.is_file():
                runtime.append({'path': name, 'sha256': digest(p)})
    evidence['loaded_python_runtime_files'] = sorted({r['path']: r for r in runtime}.values(), key=lambda r: r['path'])
    evidence['python_executable_sha256'] = digest(Path(sys.executable))
    evidence['python_startup'] = {'isolated': bool(sys.flags.isolated), 'site_disabled': bool(sys.flags.no_site)}
    args.evidence.mkdir(parents=True, exist_ok=False)
    (args.evidence / 'manifest.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: evidence[k] for k in ('classification', 'baseline_matches_host_bound', 'model_calls')}))
    return 0 if evidence['baseline_matches_host_bound'] or evidence['classification'] == 'PINNED_DOWNLOADS_ACQUIRED_ONLY' else 2


if __name__ == '__main__':
    sys.exit(main())
