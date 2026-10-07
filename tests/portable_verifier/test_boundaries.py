import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portable_verifier import acquire as a
from portable_verifier.bootstrap import reconstruct_launcher, baseline_outcome
from portable_verifier.redact import safe_diagnostics


class Boundaries(unittest.TestCase):
    def test_diagnostics_remove_sensitive_metadata_preserve_results(self):
        raw = '3 cases, 1 failure; Temurin 21.0.12.1 at /home/person/private\nhttps://user:pass@maven.neoforged.net/releases/artifact?signature=private\nAuthorization: Bearer example-token'
        result = safe_diagnostics(raw)
        for private in ('/home/person', 'user:pass', 'signature=', 'example-token'):
            self.assertNotIn(private, result)
        self.assertIn('3 cases, 1 failure', result)
        self.assertIn('21.0.12.1', result)
        self.assertIn('https://maven.neoforged.net/releases/artifact', result)

    def test_destination_and_url_authority(self):
        for p in ('../credential', '/private', 'C:/private', 'a\\b', 'a/../b'):
            with self.subTest(path=p), self.assertRaises(ValueError):
                a.safe_relative(p)
        for u in ('https://key@maven.neoforged.net/a', 'http://maven.neoforged.net/a',
                  'https://maven.neoforged.net/a?token=secret', 'https://evil.example/a'):
            with self.subTest(url=u), self.assertRaises(ValueError):
                a.safe_url(u)

    def test_wrong_upstream_bytes_are_removed_and_recorded(self):
        row = {'path': 'artifacts/file', 'size': 3, 'sha256': hashlib.sha256(b'old').hexdigest(),
               'urls': ['https://maven.neoforged.net/file']}
        with tempfile.TemporaryDirectory() as d, patch('urllib.request.getproxies', return_value={}), \
                patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'new')
            result = a.fetch(row, Path(d))
            self.assertEqual(result['status'], 'UNAVAILABLE')
            self.assertEqual(result['attempts'][0]['status'], 'HASH_MISMATCH')
            self.assertEqual(result['attempts'][0]['actual_sha256'], hashlib.sha256(b'new').hexdigest())
            self.assertFalse((Path(d) / row['path']).exists())
            self.assertFalse(list(Path(d).rglob('*.partial')))

    def test_poisoned_existing_cache_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'file'
            p.write_bytes(b'poison')
            with self.assertRaises(ValueError):
                a.fetch({'path': 'file', 'sha256': hashlib.sha256(b'right').hexdigest()}, Path(d))

    def test_linked_parent_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            (Path(d) / 'linked').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                a.fetch({'path': 'linked/new/file'}, Path(d))
            self.assertFalse(list(Path(outside).iterdir()))

    def test_pinned_manifest_inventory(self):
        c = a.catalog()
        self.assertEqual([len(c[k]) for k in ('modules', 'native', 'wrapper', 'nfrt_intermediates')], [420, 3895, 314, 22])
        missing = next(r for r in c['native'] if r['path'].endswith('binarypatcher-2.1.2-fatjar.jar'))
        self.assertEqual(missing['urls'], [a.BINARYPATCHER_URL])
        metadata = next(r for r in c['modules'] if '/minecraft-dependencies/' in r['path'])
        self.assertIn('/mojang-meta/', metadata['urls'][0])

    def test_functional_launcher_uses_only_verified_version_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            native = root / 'caches/neoformruntime/artifacts'
            native.mkdir(parents=True)
            p = native / 'minecraft_1.21.1_version_manifest.json'
            p.write_text(json.dumps({'id': '1.21.1', 'type': 'release', 'time': 'x', 'releaseTime': 'y'}))
            row = {'path': p.relative_to(root).as_posix(), 'sha256': a.digest(p), 'urls': ['https://piston-meta.mojang.com/pinned.json']}
            launcher = {'path': 'caches/neoformruntime/artifacts/minecraft_launcher_manifest.json', 'sha256': '0' * 64}
            result = reconstruct_launcher(root, {'native': [row, launcher]})
            self.assertFalse(result['matches_historical'])
            self.assertEqual(result['classification'], 'REPRODUCIBLE_FROM_PINNED_INPUTS')
            doc = json.loads((root / launcher['path']).read_bytes())
            self.assertEqual([x['id'] for x in doc['versions']], ['1.21.1'])
            p.write_text('changed')
            with self.assertRaises(ValueError):
                reconstruct_launcher(root, {'native': [row, launcher]})

    def test_baseline_success_requires_the_expected_failure(self):
        row = {'class_name': 'frozen.J001', 'tests': 3, 'failures': 1, 'errors': 0, 'skipped': 0}
        result = {'passed': False, 'checks': [{'name': 'frozen_junit_acceptance', 'passed': False,
                  'detail': {'tests': [row], 'timed_out': False, 'returncode': 1}}],
                  'isolation': {'backend': 'docker', 'available': True, 'network': 'none',
                  'rootfs': 'readonly', 'source': 'sanitized-readonly', 'workspace': 'tmpfs',
                  'limits': {'pids': 448, 'memory': '4g', 'memory_swap': '4g', 'cpus': 2}}}
        self.assertTrue(baseline_outcome(result, 'frozen.J001')[1])
        result['checks'].append({'name': 'source_immutability', 'passed': False})
        self.assertFalse(baseline_outcome(result, 'frozen.J001')[1])
        result['checks'].pop()
        result['isolation']['network'] = 'bridge'
        self.assertFalse(baseline_outcome(result, 'frozen.J001')[1])
        result['isolation']['network'] = 'none'
        row['failures'] = 0
        self.assertFalse(baseline_outcome(result, 'frozen.J001')[1])
        row['failures'] = 1
        result['checks'][0]['detail']['timed_out'] = True
        self.assertFalse(baseline_outcome(result, 'frozen.J001')[1])


if __name__ == '__main__':
    unittest.main()
