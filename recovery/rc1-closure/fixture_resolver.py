"""Recovery-only, exact-byte materialization of provenance-proven archived fixtures.

This never changes the recovered corpus. Destinations must be in a separate
isolated test worktree; the seven permitted Git blobs and hashes are explicit.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath


class FixtureResolutionError(ValueError):
    pass


# The recovery mapping is host-owned authority, not a caller-supplied source
# selector. Bind the exact reviewed map before any Git blob is copied.
REVIEWED_MAP_SHA256 = "d216a98dc39062bc6bad7c0a2aff21b13f58b30e3c97aab333a062ac0b929bdc"


def _relative(value: str) -> Path:
    p = PurePosixPath(value)
    if (not value or p.is_absolute() or "\\" in value or ":" in value
            or any(part in {".", "..", ""} for part in value.split("/"))):
        raise FixtureResolutionError(f"unsafe fixture path: {value}")
    return Path(*p.parts)


def _assert_no_links(root: Path, destination: Path) -> None:
    if destination != root and root not in destination.parents:
        raise FixtureResolutionError("fixture destination escapes isolated worktree")
    current = root
    if current.is_symlink():
        raise FixtureResolutionError("isolated root is a link")
    for part in destination.relative_to(root).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if current.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise FixtureResolutionError(f"link or junction in fixture destination: {current}")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if proc.returncode:
        raise FixtureResolutionError(f"Git worktree identity check failed: {' '.join(args)}")
    return proc.stdout.strip()


def _assert_isolated_worktree(repo: Path, root: Path, mapping: dict) -> None:
    # A linked detached worktree is disposable recovery test state; an arbitrary
    # directory or the original recovered corpus is not an acceptable target.
    if not (root / ".git").is_file() or _git(root, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD":
        raise FixtureResolutionError("destination must be a detached linked test worktree")
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise FixtureResolutionError("destination is not its Git worktree root")
    if Path(_git(repo, "rev-parse", "--git-common-dir")).resolve() != Path(_git(root, "rev-parse", "--git-common-dir")).resolve():
        raise FixtureResolutionError("destination is not linked to the recovered repository")
    corpus = "recovery/workshop-source-20261006"
    if _git(root, "rev-parse", f"HEAD:{corpus}") != _git(repo, "rev-parse", f"{mapping['anchor_commit']}:{corpus}"):
        raise FixtureResolutionError("destination historical corpus identity differs")
    test_base = "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1/repaired-workshop/tests"
    for name, expected in mapping["requesting_test_sha256"].items():
        raw = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{test_base}/{name}"],
                             capture_output=True, check=False)
        if raw.returncode or hashlib.sha256(raw.stdout).hexdigest() != expected:
            raise FixtureResolutionError(f"frozen requesting test identity differs: {name}")


def materialize(repo: Path, isolated_root: Path, map_file: Path, requested: tuple[str, ...] | None = None) -> list[dict]:
    repo = repo.resolve(strict=True)
    if isolated_root.is_symlink() or (hasattr(isolated_root, "is_junction") and isolated_root.is_junction()):
        raise FixtureResolutionError("isolated root is a link")
    isolated_root = isolated_root.resolve(strict=True)
    if repo == isolated_root or repo in isolated_root.parents or isolated_root in repo.parents:
        raise FixtureResolutionError("fixtures require a separate isolated worktree")
    raw_map = map_file.read_bytes()
    if hashlib.sha256(raw_map).hexdigest() != REVIEWED_MAP_SHA256:
        raise FixtureResolutionError("fixture mapping differs from reviewed identity")
    mapping = json.loads(raw_map)
    _assert_isolated_worktree(repo, isolated_root, mapping)
    rows = mapping["fixtures"]
    by_name = {row["relative_path"]: row for row in rows}
    if len(by_name) != len(rows):
        raise FixtureResolutionError("ambiguous duplicate fixture mapping")
    names = requested if requested is not None else tuple(by_name)
    output = []
    for name in names:
        if name not in by_name:
            raise FixtureResolutionError(f"unmapped fixture: {name}")
        row = by_name[name]
        if row.get("disposition") != "EXACT_FIXTURE_IDENTITY_PROVEN_AT_OTHER_PATH":
            raise FixtureResolutionError(f"fixture identity not proven: {name}")
        rel = _relative(name)
        src = mapping["source_prefix"] + rel.as_posix()
        dest_rel = _relative(mapping["destination_prefix"] + rel.as_posix())
        destination = isolated_root / dest_rel
        _assert_no_links(isolated_root, destination)
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", f"{mapping['anchor_commit']}:{src}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if proc.returncode != 0:
            raise FixtureResolutionError(f"committed fixture missing: {name}")
        digest = hashlib.sha256(proc.stdout).hexdigest()
        if digest != row["sha256"]:
            raise FixtureResolutionError(f"fixture identity mismatch: {name}")
        if destination.exists():
            if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise FixtureResolutionError(f"existing destination mismatch: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _assert_no_links(isolated_root, destination)
            with destination.open("xb") as stream:
                stream.write(proc.stdout)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise FixtureResolutionError(f"post-materialization mismatch: {name}")
        output.append({"source_git_path": src, "destination": str(destination), "sha256": digest,
                       "bytes": len(proc.stdout)})
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--isolated-root", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    records = materialize(args.repo, args.isolated_root, args.map)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"materialized {len(records)} proven fixtures")
