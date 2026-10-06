"""Safe, run-owned snapshots for opt-in external Hive repositories.

External repositories are never edited in place.  This module copies a bounded
set of ordinary files into Workshop's run storage and verifies that the source
snapshot did not change while it was being copied.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path


MAX_EXTERNAL_FILES = 100_000
MAX_EXTERNAL_BYTES = 1_000_000_000
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "envs", "virtualenv",
    ".tox", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".cache", "cache", "caches", "node_modules", ".gradle", ".idea",
    "data", "media", "reports", "snapshots", "workspace", "hive_runs",
    "self_snapshots", "logs", "build", "dist", "target", "releases",
    "outputs", "artifacts",
})


class ExternalRootError(ValueError):
    """An external root or snapshot failed a fail-closed safety check."""


def _has_parent_component(value: str) -> bool:
    return ".." in value.replace("\\", "/").split("/")


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _is_reparse_or_link(path: Path, info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    if getattr(info, "st_file_attributes", 0) & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction(path)) if callable(isjunction) else False


def _is_repository_resource_data(relative: Path) -> bool:
    """Keep source-controlled resource trees named ``data`` in snapshots."""
    parts = [part.casefold() for part in relative.parts]
    for source_index, part in enumerate(parts):
        if part != "src":
            continue
        if any(parts[index:index + 2] == ["resources", "data"]
               for index in range(source_index + 1, len(parts) - 1)):
            return True
    return False


def _exclude_directory(relative: Path) -> bool:
    name = relative.name.casefold()
    if name not in EXCLUDED_DIRECTORIES:
        return False
    if name == "data":
        return not _is_repository_resource_data(relative)
    return True


def resolve_external_root(value: str, workshop_root: Path, runs_root: Path) -> Path:
    raw = str(value or "").strip()
    if len(raw) > 4096 or not raw or _has_parent_component(raw):
        raise ExternalRootError("external_source_root must be an absolute path without '..' components")
    requested = Path(raw).expanduser()
    if not requested.is_absolute():
        raise ExternalRootError("external_source_root must be absolute")
    try:
        root = requested.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExternalRootError(f"external_source_root cannot be resolved: {exc}") from exc
    if not root.is_dir():
        raise ExternalRootError("external_source_root must name an existing directory")
    try:
        workshop = Path(workshop_root).resolve(strict=True)
        runs = Path(runs_root).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ExternalRootError(f"Workshop roots cannot be resolved: {exc}") from exc
    if _overlaps(root, workshop):
        raise ExternalRootError("external_source_root must not be Workshop ROOT or overlap it")
    if _overlaps(root, runs):
        raise ExternalRootError("external_source_root must not overlap Workshop HIVE_RUNS")
    return root


def _inventory(root: Path) -> list[tuple[Path, Path, os.stat_result]]:
    """Return deterministic source files, refusing links and special files."""
    root = root.resolve(strict=True)
    files: list[tuple[Path, Path, os.stat_result]] = []
    total_bytes = 0

    def visit(directory: Path) -> None:
        nonlocal total_bytes
        try:
            with os.scandir(directory) as scanned:
                entries = sorted(scanned, key=lambda item: (item.name.casefold(), item.name))
        except OSError as exc:
            raise ExternalRootError(f"cannot inspect external repository directory {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ExternalRootError(f"cannot inspect external repository path {path}: {exc}") from exc
            if _is_reparse_or_link(path, info):
                raise ExternalRootError(f"external repositories containing symlinks/junctions are not supported: {path}")
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ExternalRootError(f"external repository path escapes its root: {path}") from exc
            if stat.S_ISDIR(info.st_mode):
                relative = path.relative_to(root)
                if not _exclude_directory(relative):
                    visit(path)
            elif stat.S_ISREG(info.st_mode):
                # Linked Git worktrees commonly use a .git text file that
                # points back to the original checkout. Never copy it.
                if entry.name.casefold() in {".git", ".hg", ".svn"}:
                    continue
                total_bytes += info.st_size
                files.append((path, path.relative_to(root), info))
                if len(files) > MAX_EXTERNAL_FILES:
                    raise ExternalRootError(f"external repository exceeds the {MAX_EXTERNAL_FILES} file snapshot limit")
                if total_bytes > MAX_EXTERNAL_BYTES:
                    raise ExternalRootError(f"external repository exceeds the {MAX_EXTERNAL_BYTES} byte snapshot limit")
            else:
                raise ExternalRootError(f"unsupported special file in external repository: {path}")

    visit(root)
    files.sort(key=lambda item: (item[1].as_posix().casefold(), item[1].as_posix()))
    return files


def _file_digest(path: Path, root: Path, expected: os.stat_result) -> str:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExternalRootError(f"external repository file escapes its root: {path}") from exc
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ExternalRootError(f"external repository path is not a regular file: {path}")
            digest = hashlib.sha256()
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ExternalRootError(f"cannot read external repository file {path}: {exc}") from exc
    if (opened.st_size, opened.st_mtime_ns) != (expected.st_size, expected.st_mtime_ns):
        raise ExternalRootError(f"external repository changed during snapshot: {path}")
    if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
        raise ExternalRootError(f"external repository changed while reading: {path}")
    return digest.hexdigest()


def _digest_inventory(root: Path, files: list[tuple[Path, Path, os.stat_result]]) -> str:
    digest = hashlib.sha256()
    for path, relative, info in files:
        name = relative.as_posix().encode("utf-8")
        content_hash = _file_digest(path, root, info).encode("ascii")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(content_hash)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    root = Path(root).resolve(strict=True)
    return _digest_inventory(root, _inventory(root))


def _git_revision(root: Path) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    env = {key: value for key, value in os.environ.items()
           if key.casefold() not in {"git_dir", "git_work_tree", "git_config", "git_config_count"}}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"})
    try:
        result = subprocess.run(
            [git, "-C", str(root), "-c", "core.fsmonitor=false", "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, timeout=5, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    revision = (result.stdout or "").strip()
    return revision if result.returncode == 0 and len(revision) in {40, 64} else None


def _copy_file(source: Path, destination: Path, root: Path, expected: os.stat_result) -> None:
    source = source.resolve(strict=True)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ExternalRootError(f"external repository file escapes its root: {source}") from exc
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as src, destination.open("xb") as dst:
            opened = os.fstat(src.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ExternalRootError(f"external repository path is not a regular file: {source}")
            if (opened.st_size, opened.st_mtime_ns) != (expected.st_size, expected.st_mtime_ns):
                raise ExternalRootError(f"external repository changed during snapshot: {source}")
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            after = os.fstat(src.fileno())
        if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise ExternalRootError(f"external repository changed while copying: {source}")
        # Keep execute bits (for example a checked-in wrapper script) while
        # ensuring the candidate stage can be edited by the current user.
        mode = stat.S_IMODE(expected.st_mode) | stat.S_IWUSR
        os.chmod(destination, mode)
    except ExternalRootError:
        raise
    except OSError as exc:
        raise ExternalRootError(f"cannot copy external repository file {source}: {exc}") from exc


def prepare_candidate(value: str, candidate_root: Path, workshop_root: Path, runs_root: Path) -> dict:
    baseline = resolve_external_root(value, workshop_root, runs_root)
    runs = Path(runs_root).resolve(strict=False)
    candidate = Path(candidate_root).resolve(strict=False)
    try:
        candidate.relative_to(runs)
    except ValueError as exc:
        raise ExternalRootError("candidate root must remain beneath Workshop HIVE_RUNS") from exc
    if candidate == runs or _overlaps(candidate, baseline):
        raise ExternalRootError("candidate root overlaps an unauthorized filesystem boundary")
    if candidate.exists():
        raise ExternalRootError("run-owned candidate root already exists")

    inventory = _inventory(baseline)
    baseline_sha256 = _digest_inventory(baseline, inventory)
    revision = _git_revision(baseline)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    try:
        candidate.mkdir()
        resolved_candidate = candidate.resolve(strict=True)
        try:
            resolved_candidate.relative_to(runs)
        except ValueError as exc:
            raise ExternalRootError("created candidate escaped Workshop HIVE_RUNS") from exc
        if resolved_candidate != candidate or _is_reparse_or_link(candidate, candidate.lstat()):
            raise ExternalRootError("created candidate path is aliased by a symlink or junction")
        for source, relative, info in inventory:
            destination = candidate / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(source, destination, baseline, info)
        copied_sha256 = tree_sha256(candidate)
        final_baseline_sha256 = tree_sha256(baseline)
        if copied_sha256 != baseline_sha256 or final_baseline_sha256 != baseline_sha256:
            raise ExternalRootError("external baseline changed while its isolated candidate was being created")
    except Exception:
        shutil.rmtree(candidate, ignore_errors=True)
        raise

    return {
        "external_root_mode": "candidate_only",
        "baseline_root": str(baseline),
        "baseline_revision": revision,
        "baseline_sha256": baseline_sha256,
        "candidate_root": str(candidate),
        "snapshot_excludes": sorted(EXCLUDED_DIRECTORIES),
        "promotion_allowed": False,
    }


def copy_candidate_tree(source_root: Path, destination_root: Path, authorized_root: Path) -> str:
    """Copy a validated run candidate into Hive's private editable stage."""
    source = Path(source_root).resolve(strict=True)
    authorized = Path(authorized_root).resolve(strict=False)
    destination = Path(destination_root).resolve(strict=False)
    try:
        destination.relative_to(authorized)
    except ValueError as exc:
        raise ExternalRootError("Hive stage destination is outside authorized run storage") from exc
    if _overlaps(source, destination) or destination.exists():
        raise ExternalRootError("Hive stage must be a new directory separate from the candidate")
    inventory = _inventory(source)
    snapshot_sha256 = _digest_inventory(source, inventory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.mkdir()
        for path, relative, info in inventory:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(path, target, source, info)
        if (tree_sha256(source) != snapshot_sha256
                or tree_sha256(destination) != snapshot_sha256):
            raise ExternalRootError("run-owned candidate changed while Hive created its private stage")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return snapshot_sha256


def baseline_unchanged(metadata: dict) -> bool:
    try:
        baseline = Path(metadata["baseline_root"]).resolve(strict=True)
        return (str(baseline) == metadata["baseline_root"] and baseline.is_dir()
                and tree_sha256(baseline) == metadata["baseline_sha256"])
    except (KeyError, OSError, RuntimeError, ExternalRootError, TypeError):
        return False
