"""Hash-bound relocation/verification of the approved RC1 verifier inputs.

This can prove relocation of host-local artifacts; it cannot prove independent
reacquisition of the exact image or third-party Gradle/NFRT payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FREEZE = ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1/FREEZE.json"
ANCHOR = "dd5db7108c7d4e37ef757f7577456e0d9f5105db"
SEED_GIT_PATH = "recovery/workshop-source-20261006/workspace/HIVE-NFRT-ATTESTATION-002/evidence/approved-nfrt-seed-v2.json"
RUN_ID = "e5a7c314b902"
PREFIXES = ("wrapper/dists/gradle-9.2.1-bin/", "caches/modules-2/",
            "caches/neoformruntime/artifacts/", "caches/neoformruntime/assets/",
            "caches/neoformruntime/intermediate_results/")
PROVENANCE = ("artifacts.manifest.json", "provenance.json",
              "external-build-inputs.manifest.json", "external-build-inputs.provenance.json")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def paths(root: Path):
    cache = root / "hive_runs/approved-gradle-caches" / RUN_ID
    sibling = root / "hive_runs" / RUN_ID
    return cache, sibling


def verify_image_binding(expected_id: str) -> tuple[str, str]:
    sys.path.insert(0, str(ROOT))
    from hive_canonical.legacy.workshop.hive_verifier import DEFAULT_IMAGE
    exact = subprocess.run(["docker", "image", "inspect", expected_id, "--format", "{{.Id}}"],
                           capture_output=True, text=True, check=True).stdout.strip()
    launched = subprocess.run(["docker", "image", "inspect", DEFAULT_IMAGE, "--format", "{{.Id}}"],
                              capture_output=True, text=True, check=True).stdout.strip()
    if exact != expected_id or launched != expected_id:
        raise ValueError("verifier image tag does not resolve to the frozen image ID")
    return DEFAULT_IMAGE, launched


def _source_manifest(source_cache: Path, freeze: dict) -> tuple[bytes, list[dict]]:
    manifest_path = source_cache / ".hive-priming-provenance" / RUN_ID / "artifacts.manifest.json"
    data = manifest_path.read_bytes()
    if digest(data) != freeze["nfrt"]["identity"]["artifacts.manifest.json"]:
        raise ValueError("approved priming artifact manifest identity mismatch")
    rows = json.loads(data)["artifacts"]
    selected = [r for r in rows if r["path"].startswith(PREFIXES)]
    if not selected or len({r["path"] for r in selected}) != len(selected):
        raise ValueError("empty or ambiguous selected artifact inventory")
    return data, selected


def provision(source_cache: Path, fresh_root: Path) -> dict:
    freeze = json.loads(FREEZE.read_bytes())
    source_cache = source_cache.resolve(strict=True)
    fresh_root.mkdir(parents=True, exist_ok=True)
    fresh_root = fresh_root.resolve(strict=True)
    target_cache, target_sibling = paths(fresh_root)
    if target_cache.exists() or target_sibling.exists():
        raise ValueError("fresh provisioning target must be empty")
    if source_cache == target_cache or source_cache in target_cache.parents:
        raise ValueError("target overlaps source cache")
    manifest_data, rows = _source_manifest(source_cache, freeze)
    target_cache.mkdir(parents=True)
    count = 0
    total = 0
    for row in rows:
        relative = Path(row["path"])
        source = source_cache / relative
        if source.is_symlink() or not source.is_file() or source.stat().st_size != row["size"] or file_digest(source) != row["sha256"]:
            raise ValueError(f"source cache artifact mismatch: {row['path']}")
        destination = target_cache / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if file_digest(destination) != row["sha256"]:
            raise ValueError(f"relocated cache artifact mismatch: {row['path']}")
        count += 1
        total += row["size"]
    meta = target_cache / ".hive-priming-provenance" / RUN_ID
    meta.mkdir(parents=True)
    target_sibling.mkdir(parents=True)
    (meta / "artifacts.manifest.json").write_bytes(manifest_data)
    for name in PROVENANCE[1:]:
        src = source_cache / ".hive-priming-provenance" / RUN_ID / name
        raw = src.read_bytes()
        (meta / name).write_bytes(raw)
        if name.startswith("external-build-inputs."):
            (target_sibling / name).write_bytes(raw)
    seed = subprocess.run(["git", "-C", str(ROOT), "show", f"{ANCHOR}:{SEED_GIT_PATH}"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    if digest(seed) != freeze["nfrt"]["sha256"]:
        raise ValueError("committed NFRT attestation mismatch")
    (fresh_root / "approved-nfrt-seed-v2.json").write_bytes(seed)
    result = verify(fresh_root)
    result.update({"provisioning_kind": "HASH_VERIFIED_HOST_LOCAL_RELOCATION",
                   "copied_files": count, "copied_bytes": total})
    return result


def verify(fresh_root: Path) -> dict:
    freeze = json.loads(FREEZE.read_bytes())
    cache, sibling = paths(fresh_root.resolve(strict=True))
    data, rows = _source_manifest(cache, freeze)
    for row in rows:
        artifact = cache / row["path"]
        if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size != row["size"] or file_digest(artifact) != row["sha256"]:
            raise ValueError(f"provisioned cache artifact mismatch: {row['path']}")
    expected = {r["path"] for r in rows}
    actual = {p.relative_to(cache).as_posix() for prefix in PREFIXES
              for p in (cache / prefix).parent.rglob("*") if p.is_file() and p.relative_to(cache).as_posix().startswith(prefix)}
    if actual != expected:
        raise ValueError(f"provisioned cache unexpected/missing artifacts: {len(actual ^ expected)}")
    expected_hashes = {
        "provenance.json": freeze["nfrt"]["identity"]["provenance.json"],
        "external-build-inputs.manifest.json": freeze["nfrt"]["identity"]["downloaded_manifest_sha256"],
        "external-build-inputs.provenance.json": "0805a46b429c299d752928cc68b2306f642e34e2bc1c0ff6dfc50236984df5c4",
    }
    for name in PROVENANCE[1:]:
        meta = cache / ".hive-priming-provenance" / RUN_ID / name
        if not meta.is_file():
            raise ValueError(f"missing provenance: {name}")
        if name in expected_hashes and file_digest(meta) != expected_hashes[name]:
            raise ValueError(f"provenance identity mismatch: {name}")
        if name.startswith("external-build-inputs.") and (sibling / name).read_bytes() != meta.read_bytes():
            raise ValueError(f"sibling external-input provenance mismatch: {name}")
    seed = fresh_root / "approved-nfrt-seed-v2.json"
    if file_digest(seed) != freeze["nfrt"]["sha256"]:
        raise ValueError("relocated NFRT attestation mismatch")
    image = freeze["verifier"]["verifier_image_id"]
    invoked_tag, launched_image = verify_image_binding(image)
    return {"status": "PASS", "cache_root": str(cache), "seed_manifest": str(seed),
            "selected_artifact_count": len(rows), "selected_bytes": sum(r["size"] for r in rows),
            "artifact_manifest_sha256": digest(data), "image_id": image,
            "invoked_image_tag": invoked_tag, "invoked_image_tag_id": launched_image,
            "host_local_required_artifact": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("provision", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    args = parser.parse_args()
    if args.mode == "provision":
        if args.source_cache is None:
            parser.error("provision requires --source-cache")
        value = provision(args.source_cache, args.root)
    else:
        value = verify(args.root)
    print(json.dumps(value, indent=2))
