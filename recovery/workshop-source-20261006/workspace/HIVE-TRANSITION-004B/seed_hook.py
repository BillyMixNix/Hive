# Appended only to a diagnostic copy of the unchanged runner. Never installed.
_diagnostic_original_copy = _copy_external_build_inputs
def _copy_external_build_inputs(*args, **kwargs):
    result = _diagnostic_original_copy(*args, **kwargs)
    _event('diagnostic_intermediate_seed_started')
    manifest_file = Path('/probe/evidence/seed-manifest.json')
    raw = manifest_file.read_bytes()
    expected = os.environ['HIVE_DIAGNOSTIC_SEED_MANIFEST_SHA256']
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('diagnostic seed manifest hash mismatch')
    manifest = json.loads(raw)
    entries = manifest['entries']
    source = Path('/diagnostic-intermediates')
    destination = Path(args[0]) / 'caches/neoformruntime/intermediate_results'
    if destination.exists():
        raise ValueError('diagnostic generated-cache destination is not fresh')
    if {p.name for p in source.iterdir()} != {r['path'] for r in entries}:
        raise ValueError('diagnostic seed inventory mismatch')
    if len(entries) != 22 or sum(r['size'] for r in entries) != 163178447:
        raise ValueError('diagnostic frozen seed differs from measured bounded inventory')
    destination.mkdir()
    for row in entries:
        name = row['path']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('unsafe diagnostic seed filename')
        original = source/name
        if original.is_symlink() or not original.is_file():
            raise ValueError('linked or nonfile diagnostic seed')
        target = destination/name
        shutil.copyfile(original, target)
        if target.stat().st_size != row['size'] or hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('diagnostic seed content mismatch')
    _event('diagnostic_intermediate_seed_complete', count=len(entries),bytes=sum(r['size'] for r in entries),
           manifest_sha256=expected)
    return result
