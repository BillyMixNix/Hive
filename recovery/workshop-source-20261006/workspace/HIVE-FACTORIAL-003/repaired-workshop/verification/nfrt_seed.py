"""Host-pinned NFRT dependency seeds. No candidate results or cache-existence trust."""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path

PREFIX = 'caches/neoformruntime/intermediate_results/'
NAME = re.compile(r'[A-Za-z][A-Za-z0-9]*_[0-9a-f]{40}(?:_[A-Za-z][A-Za-z0-9]*\.(?:jar|tsrg|txt)|\.txt)')
SHA = re.compile(r'[0-9a-f]{64}')


def ordinary(path: Path, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError(f'NFRT seed linked or nonordinary path: {path}')
    return info


def digest(path):
    ordinary(Path(path))
    with Path(path).open('rb') as stream:
        value=hashlib.sha256()
        while chunk:=stream.read(1024*1024):value.update(chunk)
        return value.hexdigest()


def relative(value):
    if (not isinstance(value, str) or '\\' in value or ':' in value or
            value.startswith('/') or any(x in ('', '.', '..') for x in value.split('/'))):
        raise ValueError('unsafe NFRT attestation path')
    return value


def load_attestation(path, expected):
    path=Path(path)
    if not isinstance(expected,str) or not SHA.fullmatch(expected) or digest(path)!=expected:
        raise ValueError('NFRT attestation hash mismatch')
    if path.stat().st_size>32_000_000:
        raise ValueError('NFRT attestation too large')
    doc=json.loads(path.read_bytes())
    if doc.get('schema')!='hive-nfrt-seed-v1' or doc.get('kind')!='dependency-intermediates':
        raise ValueError('unsupported NFRT attestation')
    entries=doc.get('entries',[])
    if not 1<=len(entries)<=10000 or sum(r['size'] for r in entries)>1_000_000_000:
        raise ValueError('NFRT seed inventory bounds')
    names=set()
    for r in entries:
        name=r['path']
        if (not NAME.fullmatch(name) or name in names or type(r['size']) is not int
                or r['size']<0 or not SHA.fullmatch(r['sha256'])):
            raise ValueError('invalid NFRT intermediate entry')
        names.add(name)
    for r in entries:
        stem=r['path'].split('_')
        if f'{stem[0]}_{stem[1].split(".")[0]}.txt' not in names:
            raise ValueError('NFRT output lacks its attested node key')
    if not doc.get('forbidden_packages') or any(not re.fullmatch(r'[A-Za-z0-9_/]+/',p) for p in doc['forbidden_packages']):
        raise ValueError('NFRT application namespaces required')
    return doc


def verify_seed(source, doc):
    source=Path(source);ordinary(source,True)
    entries=doc['entries']
    if {p.name for p in source.iterdir()}!={r['path'] for r in entries}:
        raise ValueError('NFRT seed inventory mismatch (missing/extra file)')
    for row in entries:
        p=source/row['path']
        if ordinary(p).st_size!=row['size'] or digest(p)!=row['sha256']:
            raise ValueError('NFRT intermediate content hash/size mismatch')
        if p.suffix=='.jar':
            with zipfile.ZipFile(p) as jar:
                if any(n.startswith(tuple(doc['forbidden_packages'])) for n in jar.namelist()):
                    raise ValueError('NFRT seed contains candidate application/test artifact')
        elif re.fullmatch(r'[A-Za-z][A-Za-z0-9]*_[0-9a-f]{40}\.txt',p.name):
            key=json.loads(p.read_bytes())
            if f"{key['type']}_{key['hashValue']}.txt"!=p.name or not key.get('components'):
                raise ValueError('NFRT node key mismatch')
            material='\n'.join(f"{k}: {v['value']}" for k,v in sorted(key['components'].items()))
            if hashlib.sha1(material.encode()).hexdigest()!=key['hashValue']:
                raise ValueError('NFRT node components mismatch')
    return len(entries)


def private_copy(source, destination, manifest, expected):
    doc=load_attestation(manifest,expected)
    verify_seed(source,doc)
    destination=Path(destination)
    if destination.exists():
        raise ValueError('NFRT intermediate destination must be fresh and private')
    destination.mkdir(parents=True)
    try:
        for row in doc['entries']:
            original=Path(source)/row['path'];target=destination/row['path']
            # Byte copies, never links or shared writable cache paths.
            with original.open('rb') as src,target.open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024)
        verify_seed(destination,doc)
    except Exception:
        shutil.rmtree(destination)
        raise
    return {'files':len(doc['entries']),'bytes':sum(r['size'] for r in doc['entries']),
            'attestation_sha256':expected,'private_copy':True}


def configured_seed(tree, cache, profile, baseline_sha256, image_id, downloaded_manifest_sha256):
    """Only host environment selects an attestation. Candidate config cannot select it."""
    manifest=os.environ.get('HIVE_NFRT_SEED_MANIFEST')
    expected=os.environ.get('HIVE_NFRT_SEED_SHA256')
    if manifest is None and expected is None:
        return None  # Explicit policy: verified reconstruction when no seed is configured.
    if not manifest or not expected:
        raise ValueError('incomplete NFRT seed configuration')
    doc=load_attestation(manifest,expected)
    identity=doc['identity']
    if (identity['baseline_sha256']!=baseline_sha256 or identity['image_id']!=image_id
            or identity['jvm_profile']!=profile or identity['downloaded_manifest_sha256']!=downloaded_manifest_sha256):
        raise ValueError('NFRT build/tool identity mismatch')
    cache=Path(cache)
    proof=cache/'.hive-priming-provenance'/cache.name
    for name in ('artifacts.manifest.json','provenance.json'):
        if digest(proof/name)!=identity[name]:
            raise ValueError('NFRT priming provenance mismatch')
    priming=json.loads((proof/'provenance.json').read_bytes())
    if (priming.get('candidate_sha256')!=baseline_sha256 or priming.get('cache_priming_succeeded') is not True
            or priming.get('artifact_manifest_sha256')!=identity['artifacts.manifest.json']):
        raise ValueError('NFRT priming not approved')
    inventory=json.loads((proof/'artifacts.manifest.json').read_bytes())['artifacts']
    indexed={r['path']:r for r in inventory}
    for row in doc['entries']:
        if indexed.get(PREFIX+row['path'])!={**row,'path':PREFIX+row['path']}:
            raise ValueError('NFRT intermediate not sealed by priming')
    # Bind ALL approved module/tool bytes, not only version strings. Existing
    # downloaded-input checks remain responsible for assets/artifacts.
    actual=[]
    modules=cache/'caches/modules-2';ordinary(modules,True)
    for p in modules.rglob('*'):
        if p.is_dir():ordinary(p,True)
        else:actual.append(p.relative_to(cache).as_posix())
    module_rows=[r for r in inventory if r['path'].startswith('caches/modules-2/')]
    if set(actual)!={r['path'] for r in module_rows}:
        raise ValueError('NFRT tool/dependency inventory mismatch')
    for row in module_rows:
        p=cache/relative(row['path'])
        if ordinary(p).st_size!=row['size'] or digest(p)!=row['sha256']:
            raise ValueError('NFRT tool/dependency hash mismatch')
    # These paths and this compatibility review are host-attested, never model
    # supplied. All other source/config bytes and the exact file set are fixed.
    from workshop import external_root
    source_rows=doc['source_inventory']
    fixed={relative(r['path']):r['sha256'] for r in source_rows}
    mutable=doc['independent_java_sources']
    if (not mutable or len(set(mutable))!=len(mutable) or
            any(p not in fixed or not p.startswith('src/main/java/') or not p.endswith('.java') for p in mutable)):
        raise ValueError('invalid independently attested source scope')
    measured=doc.get('reconstruction_inputs')
    if not isinstance(measured,dict) or not measured.get('inputProperties') or not measured.get('inputFiles'):
        raise ValueError('missing measured reconstruction compatibility evidence')
    current=external_root._inventory(Path(tree))
    if {r.as_posix() for _,r,_ in current}!=set(fixed):
        raise ValueError('NFRT source inventory changed')
    for p,rel,info in current:
        if rel.as_posix() not in mutable and external_root._file_digest(p,Path(tree).resolve(),info)!=fixed[rel.as_posix()]:
            raise ValueError(f'NFRT reconstruction input changed: {rel.as_posix()}')
    source=cache/PREFIX.rstrip('/')
    verify_seed(source,doc)
    return {'source':source,'manifest':Path(manifest),'sha256':expected,'document':doc}
