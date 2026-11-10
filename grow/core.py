from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class ExperimentInvalid(RuntimeError):
    """Raised when a GROW-0 integrity or stop condition is violated."""


class ForbiddenWriteError(PermissionError):
    """Raised when a candidate attempts to write outside the mutable boundary."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_json(data: Any) -> str:
    return sha256_text(stable_json(data))


def normalize_relpath(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    normalized = Path(raw).as_posix().lstrip("./")
    if not normalized or normalized == "." or normalized.startswith("../") or "/../" in f"/{normalized}":
        raise ForbiddenWriteError(f"unsafe relative path: {value!r}")
    return normalized


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def hash_paths(repo_root: str | Path, paths: Iterable[str]) -> dict[str, str | None]:
    root = Path(repo_root).resolve()
    result: dict[str, str | None] = {}
    for rel in sorted({normalize_relpath(path) for path in paths}):
        target = root / rel
        result[rel] = file_hash(target) if target.is_file() else None
    return result


def tree_manifest(
    root: str | Path,
    *,
    include: Iterable[str] | None = None,
    ignore_parts: Iterable[str] = (".git", "__pycache__", ".pytest_cache", ".venv", "backups"),
    ignore_rel_prefixes: Iterable[str] = ("grow/state/",),
) -> dict[str, str]:
    base = Path(root).resolve()
    ignored = set(ignore_parts)
    ignored_prefixes = tuple(str(prefix).replace("\\", "/") for prefix in ignore_rel_prefixes)
    allowed = None if include is None else {normalize_relpath(item) for item in include}
    manifest: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if any(part in ignored or part.startswith("_tmp_reliability_") for part in path.relative_to(base).parts):
            continue
        if any(rel.startswith(prefix) for prefix in ignored_prefixes):
            continue
        if allowed is not None and rel not in allowed:
            continue
        manifest[rel] = file_hash(path)
    return manifest


def manifest_hash(manifest: dict[str, str]) -> str:
    return hash_json(manifest)


@dataclass(frozen=True)
class ModelConfig:
    identity: str
    digest: str
    temperature: float
    seed: int
    context_tokens: int
    max_output_tokens: int
    max_calls_per_case: int
    safety_profile: str = "hive-default"

    @property
    def config_hash(self) -> str:
        return hash_json(asdict(self))


@dataclass
class GenerationRecord:
    generation_id: str
    parent_id: str | None
    source_workshop_snapshot_hash: str
    model_configuration_hash: str
    benchmark_bundle_id: str
    creation_timestamp: str
    triggering_failure_id: str | None = None
    proposed_architectural_change: dict[str, Any] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    before_hashes: dict[str, str | None] = field(default_factory=dict)
    after_hashes: dict[str, str | None] = field(default_factory=dict)
    validation_results: dict[str, Any] = field(default_factory=dict)
    regression_results: dict[str, Any] = field(default_factory=dict)
    transfer_results: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    disposition: str = "PENDING"
    rejection_reason: str | None = None


class AppendOnlyLedger:
    """Hash-chained JSONL ledger. Candidate workspaces never receive this path."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def _read_raw(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ExperimentInvalid(f"lineage ledger corrupted at line {line_no}: {exc}") from exc
        return records

    def verify(self) -> bool:
        prev_hash = "GENESIS"
        for index, envelope in enumerate(self._read_raw()):
            payload = envelope.get("payload")
            if envelope.get("prev_hash") != prev_hash:
                return False
            expected = hash_json({"prev_hash": prev_hash, "payload": payload})
            if envelope.get("entry_hash") != expected:
                return False
            prev_hash = expected
        return True

    def entries(self) -> list[dict[str, Any]]:
        if not self.verify():
            raise ExperimentInvalid("lineage ledger hash chain failed verification")
        return [record["payload"] for record in self._read_raw()]

    def append(self, payload: dict[str, Any]) -> str:
        if not self.verify():
            raise ExperimentInvalid("refusing append to corrupted lineage ledger")
        raw = self._read_raw()
        prev_hash = raw[-1]["entry_hash"] if raw else "GENESIS"
        entry_hash = hash_json({"prev_hash": prev_hash, "payload": payload})
        envelope = {"prev_hash": prev_hash, "entry_hash": entry_hash, "payload": payload}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(stable_json(envelope) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry_hash

    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        for entry in self.entries():
            if entry.get("record_type") == "generation" and entry.get("generation_id") == generation_id:
                return entry
        return None

    def parent_is_eligible(self, generation_id: str) -> bool:
        entry = self.get_generation(generation_id)
        return bool(entry and entry.get("disposition") == "PROMOTED")


class LessonLedger(AppendOnlyLedger):
    """Rejected-candidate lessons with the same tamper-evident semantics as lineage."""

    def sanitized_lessons(self, hidden_markers: Iterable[str] = ()) -> list[dict[str, Any]]:
        hidden = {str(marker) for marker in hidden_markers if str(marker)}
        lessons = []
        for entry in self.entries():
            if entry.get("record_type") != "rejection_lesson":
                continue
            copied = json.loads(json.dumps(entry))
            text = stable_json(copied)
            if any(marker in text for marker in hidden):
                raise ExperimentInvalid("hidden transfer material detected in rejection lesson")
            lessons.append(copied)
        return lessons


class CandidateWorkspace:
    """
    Copy-on-write candidate containing only explicitly mutable workshop files.

    It is intentionally not a repository clone. Evaluators, hidden cases, benchmark
    definitions, promotion logic, ledgers, and ancestor files are absent.
    """

    def __init__(self, repo_root: str | Path, mutable_paths: Iterable[str]):
        self.repo_root = Path(repo_root).resolve()
        self.mutable_paths = tuple(sorted({normalize_relpath(path) for path in mutable_paths}))
        self._tmp = tempfile.TemporaryDirectory(prefix="hive-grow0-candidate-")
        self.root = Path(self._tmp.name).resolve()
        for rel in self.mutable_paths:
            source = self.repo_root / rel
            if not source.is_file():
                raise ExperimentInvalid(f"mutable workshop path does not exist: {rel}")
            destination = self.root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self.before_hashes = hash_paths(self.root, self.mutable_paths)
        self.write_attempts: list[dict[str, Any]] = []

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "CandidateWorkspace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _assert_mutable(self, relpath: str | Path) -> str:
        rel = normalize_relpath(relpath)
        if rel not in self.mutable_paths:
            self.write_attempts.append({"path": rel, "allowed": False, "timestamp": utc_now()})
            raise ForbiddenWriteError(f"candidate write forbidden: {rel}")
        return rel

    def read_text(self, relpath: str | Path) -> str:
        rel = normalize_relpath(relpath)
        if rel not in self.mutable_paths:
            raise PermissionError(f"candidate read forbidden: {rel}")
        return (self.root / rel).read_text(encoding="utf-8")

    def write_text(self, relpath: str | Path, text: str) -> None:
        rel = self._assert_mutable(relpath)
        target = self.root / rel
        target.write_text(text, encoding="utf-8")
        self.write_attempts.append({"path": rel, "allowed": True, "timestamp": utc_now()})

    def hashes(self) -> dict[str, str | None]:
        return hash_paths(self.root, self.mutable_paths)

    def changed_files(self) -> list[str]:
        after = self.hashes()
        return [rel for rel in self.mutable_paths if after.get(rel) != self.before_hashes.get(rel)]


@dataclass(frozen=True)
class IntegritySnapshot:
    ancestor_manifest_hash: str
    immutable_hashes: dict[str, str | None]
    benchmark_hash: str
    transfer_hash: str
    evaluator_hash: str
    promotion_hash: str
    model_config_hash: str


def make_integrity_snapshot(
    *,
    repo_root: str | Path,
    immutable_paths: Iterable[str],
    benchmark_path: str,
    transfer_path: str,
    evaluator_path: str,
    promotion_path: str,
    model_config_hash: str,
) -> IntegritySnapshot:
    root = Path(repo_root)
    manifest = tree_manifest(root)
    hashes = hash_paths(root, immutable_paths)
    return IntegritySnapshot(
        ancestor_manifest_hash=manifest_hash(manifest),
        immutable_hashes=hashes,
        benchmark_hash=file_hash(root / benchmark_path),
        transfer_hash=file_hash(root / transfer_path),
        evaluator_hash=file_hash(root / evaluator_path),
        promotion_hash=file_hash(root / promotion_path),
        model_config_hash=model_config_hash,
    )


def verify_ancestor_and_kernel(
    snapshot: IntegritySnapshot,
    *,
    repo_root: str | Path,
    immutable_paths: Iterable[str],
    benchmark_path: str,
    transfer_path: str,
    evaluator_path: str,
    promotion_path: str,
    model_config_hash: str,
) -> dict[str, Any]:
    root = Path(repo_root)
    current_manifest_hash = manifest_hash(tree_manifest(root))
    checks = {
        "ancestor_unchanged": current_manifest_hash == snapshot.ancestor_manifest_hash,
        "immutable_paths_unchanged": hash_paths(root, immutable_paths) == snapshot.immutable_hashes,
        "benchmark_unchanged": file_hash(root / benchmark_path) == snapshot.benchmark_hash,
        "hidden_transfer_unchanged": file_hash(root / transfer_path) == snapshot.transfer_hash,
        "evaluator_unchanged": file_hash(root / evaluator_path) == snapshot.evaluator_hash,
        "promotion_logic_unchanged": file_hash(root / promotion_path) == snapshot.promotion_hash,
        "model_config_unchanged": model_config_hash == snapshot.model_config_hash,
    }
    return {"passed": all(checks.values()), "checks": checks}


def marker_scan(texts: dict[str, str], forbidden_markers: Iterable[str]) -> dict[str, Any]:
    hits: list[dict[str, str]] = []
    markers = [str(marker) for marker in forbidden_markers if str(marker).strip()]
    for path, text in texts.items():
        for marker in markers:
            if marker in text:
                hits.append({"path": path, "marker": marker})
    return {"passed": not hits, "hits": hits}
