"""Acquire only hash-pinned upstream inputs. Never transfer a host cache."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'recovery/workshop-source-20261006'
HISTORICAL_RUN = CORPUS / 'external/original-v0.11.1/Nix_Workshop_v0_11_1/hive_runs'
INVENTORY = HISTORICAL_RUN / 'approved-gradle-caches/e5a7c314b902/.hive-priming-provenance/e5a7c314b902/artifacts.manifest.json'
INVENTORY_SHA = '83759b6046e4290e6388ea95b2013f12edf500d4f86f39cc3401dd646117c2f9'
NATIVE = HISTORICAL_RUN / 'e5a7c314b902/external-build-inputs.manifest.json'
NATIVE_SHA = '2135a0b94c2ff740e6fc8a441285a1e04088d31bf930628c124c26a6ea55a561'
SEED = CORPUS / 'workspace/HIVE-NFRT-ATTESTATION-002/evidence/approved-nfrt-seed-v2.json'
SEED_SHA = '9ec38a4912981e3e34e0ee4bbeb7c8dfa04a6d23beba3b49829a43e5b2a124a3'
BINARYPATCHER_URL = 'https://maven.neoforged.net/releases/net/neoforged/installertools/binarypatcher/2.1.2/binarypatcher-2.1.2-fatjar.jar'
GRADLE = {'name': 'gradle-9.2.1-bin.zip', 'sha256': '72f44c9f8ebcb1af43838f45ee5c4aa9c5444898b3468ab3f4af7b6076c5bc3f', 'size': 135535598, 'urls': ['https://services.gradle.org/distributions/gradle-9.2.1-bin.zip']}
JDK = {'name': 'temurin-jdk.tar.gz', 'sha256': 'ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94', 'urls': ['https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz']}
ORIGINS = ['https://repo.maven.apache.org/maven2', 'https://maven.neoforged.net/releases', 'https://libraries.minecraft.net', 'https://plugins.gradle.org/m2', 'https://maven.ftb.dev/releases', 'https://maven.architectury.dev', 'https://maven.neoforged.net/mojang-meta']


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def pinned_json(path: Path, expected: str):
    if path.is_symlink() or digest(path) != expected:
        raise ValueError('historical manifest identity mismatch')
    return json.loads(path.read_bytes())


def safe_relative(value: str) -> Path:
    if not isinstance(value, str) or '\\' in value or ':' in value or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('unsafe acquisition path')
    return Path(value)


def safe_url(value: str) -> str:
    p = urllib.parse.urlsplit(value)
    allowed = {urllib.parse.urlsplit(x).hostname for x in ORIGINS} | {'github.com', 'services.gradle.org', 'resources.download.minecraft.net', 'piston-meta.mojang.com', 'piston-data.mojang.com'}
    if p.scheme != 'https' or p.hostname not in allowed or p.username or p.password or p.query or p.fragment or p.port:
        raise ValueError('unapproved acquisition URL')
    return value


def catalog() -> dict:
    inventory = pinned_json(INVENTORY, INVENTORY_SHA)['artifacts']
    native = pinned_json(NATIVE, NATIVE_SHA)['files']
    seed = pinned_json(SEED, SEED_SHA)
    provenance = pinned_json(HISTORICAL_RUN / 'e5a7c314b902/external-build-inputs.provenance.json',
                             '0805a46b429c299d752928cc68b2306f642e34e2bc1c0ff6dfc50236984df5c4')
    modules = []
    for row in inventory:
        if not row['path'].startswith('caches/modules-2/files-2.1/'):
            continue
        _, _, _, group, artifact, version, content_key, filename = row['path'].split('/')
        if not re.fullmatch('[0-9a-f]{1,40}', content_key):
            raise ValueError('invalid Maven content key')
        suffix = '/'.join([group.replace('.', '/'), artifact, version, filename])
        origins = list(ORIGINS)
        if group.startswith(('net.neoforged', 'net.minecraftforge', 'cpw.mods', 'io.codechicken')):
            origins.insert(0, origins.pop(1))
        elif group.startswith('dev.ftb'):
            origins.insert(0, origins.pop(4))
        elif group.startswith('dev.architectury'):
            origins.insert(0, origins.pop(5))
        observed = [safe_url(u) for u in provenance['observed_source_urls'] if urllib.parse.urlsplit(u).path.endswith('/' + suffix)]
        modules.append({**row, 'urls': list(dict.fromkeys(observed + [safe_url(x + '/' + suffix) for x in origins])), 'classification': 'UNRESOLVED'})
    downloads = []
    for row in native:
        url = row.get('source_url')
        if url is None:
            if row['path'] != 'artifacts/net/neoforged/installertools/binarypatcher/2.1.2/binarypatcher-2.1.2-fatjar.jar':
                raise ValueError('unknown artifact without provenance')
            url = BINARYPATCHER_URL
        downloads.append({k: row[k] for k in ('path', 'size', 'sha256')} | {'path': 'caches/neoformruntime/' + row['path'], 'urls': [safe_url(url)], 'classification': 'UNRESOLVED'})
    generated = [r for r in inventory if r['path'].startswith('caches/modules-2/') and '/files-2.1/' not in r['path']]
    return {'schema': 1, 'historical_inventory_sha256': INVENTORY_SHA, 'historical_native_manifest_sha256': NATIVE_SHA,
            'jdk': JDK, 'gradle': GRADLE, 'modules': modules, 'native': downloads,
            'generated_gradle_metadata': [{**r, 'classification': 'UNRESOLVED'} for r in generated],
            'nfrt_intermediates': [{**r, 'classification': 'UNRESOLVED'} for r in seed['entries']],
            'wrapper': [r for r in inventory if r['path'].startswith('wrapper/dists/gradle-9.2.1-bin/')]}


def fetch(row: dict, root: Path) -> dict:
    """No auth headers, proxy credentials, or unverified destination bytes."""
    relative = safe_relative(row.get('path', row.get('name')))
    target = root / relative
    for p in [target, *target.parents]:
        if p.is_symlink() or (p != target and p.exists() and not p.is_dir()):
            raise ValueError('linked acquisition destination')
        if p == root:
            break
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or not target.is_file() or digest(target) != row['sha256']:
            raise ValueError('existing acquisition does not match pin')
        return {'path': relative.as_posix(), 'sha256': row['sha256'], 'size': target.stat().st_size, 'status': 'VERIFIED_EXISTING'}
    attempts = []
    for proxy in urllib.request.getproxies().values():
        if urllib.parse.urlsplit(proxy).username:
            raise ValueError('credential-bearing acquisition proxy refused')
    opener = urllib.request.build_opener()
    for url in row['urls']:
        safe_url(url)
        temporary = target.with_name(target.name + '.partial')
        try:
            h = hashlib.sha256()
            size = 0
            request = urllib.request.Request(url, headers={'User-Agent': 'Hive-Verifier-Reconstruction/1.0'})
            with opener.open(request, timeout=30) as response, temporary.open('xb') as out:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > min(500_000_000, max(1_000_000 + row.get('size', 0), 2 * row.get('size', 250_000_000))):
                        raise ValueError('download exceeds pinned size')
                    h.update(chunk)
                    out.write(chunk)
            actual = h.hexdigest()
            if actual != row['sha256'] or ('size' in row and size != row['size']):
                attempts.append({'url': url, 'status': 'HASH_MISMATCH', 'actual_sha256': actual, 'actual_size': size})
                continue
            os.replace(temporary, target)
            if digest(target) != row['sha256']:
                raise ValueError('destination hash mismatch')
            return {'path': relative.as_posix(), 'sha256': actual, 'size': size, 'url': url, 'status': 'BYTE_IDENTICAL', 'classification': 'INDEPENDENTLY_REACQUIRABLE', 'attempts': attempts}
        except (OSError, ValueError) as exc:
            attempts.append({'url': url, 'status': 'UNAVAILABLE', 'error_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)})
        finally:
            temporary.unlink(missing_ok=True)
    return {'path': relative.as_posix(), 'expected_sha256': row['sha256'], 'status': 'UNAVAILABLE', 'classification': 'UNRESOLVED', 'attempts': attempts}


def acquire(rows: list[dict], root: Path, workers: int = 12) -> list[dict]:
    if not 1 <= workers <= 24:
        raise ValueError('acquisition concurrency outside bound')
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda row: fetch(row, root), rows))
    return sorted(results, key=lambda r: r['path'])
