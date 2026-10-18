"""Protocol v1.1 repair for the Luna semantic-authority decomposition study.

The frozen requests, projections, solver, schedule, statistics, and cost ceiling
come directly from Protocol v1.  The sole experimental repair is an EOL-aware
source guard: direct worktree bytes are normalized only from CRLF to LF before
comparison with committed bytes, while canonical committed SHA-256 values and
blob OIDs remain in the preflight evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as v1


PROTOCOL_ID = "hive-luna-semantic-authority-decomposition-v1-1"
PROTOCOL_VERSION = "1.1"
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-semantic-authority-decomposition-v1-1-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-semantic-authority-decomposition-v1-1"

SEALED_V1_EVIDENCE_COMMIT = "91ce509af612af4404dc107231ce2a3a95c516dd"
SEALED_V1_IMPLEMENTATION_COMMIT = "0a4a657a2fcd789aff8ec26e00914be1dcb74152"
SEALED_V1_RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-semantic-authority-decomposition-v1-001"
)
SEALED_V1_EVIDENCE_TREE_OID = "b1fd56b4f070a0ea45c26b128654385c5cc94073"
SEALED_V1_ARTIFACT_SHA256 = {
    "EVIDENCE_INDEX.json": "f2002a27b62553c2cba798941745b0563c72e434d67679f7d17676956d974e0a",
    "MANIFEST.json": "f7e287953b4dd4103b348bcf8f7456a40918da6e6e8164fa5e51ceaec1fa048c",
    "PRECHECK.json": "e61af97009cff59831f275041146dae3d6b91eede12822cfd06c84feb5329b84",
    "PROTOCOL.json": "0d4514ac1734aab9f2c1498b2496f53402bccbdaf950670d6839d99f53d5a363",
    "RESULT.json": "6b4e84636d25cfca7a0835c21ef2897a27b41d1ac97aa2a4b062ba2f753e7afa",
    "RUN_STATUS.json": "ef925f2e4616032d0604cd82d8e8420607ebc8df07ab5bf32dcd48b7ccc4b699",
    "events.jsonl": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}
SEALED_V1_SOURCE_SHA256 = {
    "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1.md": (
        "a76c07669a494cb49c9151b807f0a60448d42eb3e8799daf3df2f7c4a4c5a199"
    ),
    "kingdom/decompression_semantic_authority_luna.py": (
        "fef6d2e752d63e7ead42903d0cdf5a3f475715c997420e638a79d0524903a75a"
    ),
    "tests/test_decompression_semantic_authority_luna.py": (
        "25927c6b39bcf11167b761ac6d91d774dd6e32adbdbd17e04b8b350afdca9544"
    ),
}
SEALED_V1_SOURCE_BLOB_OID = {
    "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1.md": (
        "41f8126ea1bb58af4e2a4b092c16e14989612794"
    ),
    "kingdom/decompression_semantic_authority_luna.py": (
        "cac79dc638e46efea78397582da7ffa5197b5d46"
    ),
    "tests/test_decompression_semantic_authority_luna.py": (
        "342bf11f87fe26474e6fa98b1d97e3af74275a4a"
    ),
}

SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *v1.SOURCE_FILES,
            "kingdom/decompression_semantic_authority_luna_v1_1.py",
            "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1_1.md",
            "tests/test_decompression_semantic_authority_luna_v1_1.py",
        )
    )
)

_BASE_PROTOCOL_ID = v1.PROTOCOL_ID
_BASE_PROTOCOL_VERSION = v1.PROTOCOL_VERSION
_BASE_RUN_DIR = v1.RUN_DIR
_BASE_SOURCE_FILES = v1.SOURCE_FILES
_BASE_GIT_REVISION_AND_SOURCES = v1._git_revision_and_sources
_BASE_ASSERT_SOURCES_UNCHANGED = v1._assert_sources_unchanged
_BASE_VERIFY_SEALED_PARENT = v1.verify_sealed_parent
_BASE_DETERMINISTIC_PREFLIGHT = v1.deterministic_preflight
_BASE_VERIFY_RUN = v1.verify_run


def _git(
    repo_root: Path, *args: str, check: bool = True, text: bool = True
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=text,
    )


def _source_state(repo_root: Path, relative: str) -> Mapping[str, Any]:
    tracked = _git(
        repo_root, "ls-files", "--error-unmatch", "--", relative, check=False
    )
    if tracked.returncode != 0:
        raise luna_v1.ApparatusFailure(f"experiment source is not committed: {relative}")
    try:
        head_oid = _git(repo_root, "rev-parse", f"HEAD:{relative}").stdout.strip()
        committed = _git(
            repo_root, "show", f"HEAD:{relative}", text=False
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise luna_v1.ApparatusFailure(
            f"experiment source cannot be hashed through Git: {relative}"
        ) from exc
    worktree_path = repo_root / relative
    if not worktree_path.is_file():
        raise luna_v1.ApparatusFailure(f"experiment source is missing: {relative}")
    return {
        "head_oid": head_oid,
        "committed_bytes": committed,
        "normalized_worktree_bytes": worktree_path.read_bytes().replace(b"\r\n", b"\n"),
        "canonical_sha256": hashlib.sha256(committed).hexdigest(),
    }


def _source_maps(
    repo_root: Path, source_files: Sequence[str] = SOURCE_FILES
) -> tuple[str, dict[str, str], dict[str, str]]:
    revision = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    sha256: dict[str, str] = {}
    blob_oids: dict[str, str] = {}
    for relative in source_files:
        state = _source_state(repo_root, relative)
        if state["normalized_worktree_bytes"] != state["committed_bytes"]:
            raise luna_v1.ApparatusFailure(
                f"experiment source differs from HEAD after CRLF normalization: {relative}"
            )
        sha256[relative] = state["canonical_sha256"]
        blob_oids[relative] = state["head_oid"]
    return revision, dict(sorted(sha256.items())), dict(sorted(blob_oids.items()))


def _git_revision_and_sources(
    repo_root: Path, source_files: Sequence[str] = SOURCE_FILES
) -> tuple[str, dict[str, str]]:
    revision, sha256, _ = _source_maps(repo_root, source_files)
    return revision, sha256


def _assert_sources_unchanged(
    repo_root: Path,
    preflight: Mapping[str, Any],
    source_files: Sequence[str] = SOURCE_FILES,
) -> None:
    expected_sha = preflight.get("source_file_sha256", {})
    expected_oids = preflight.get("source_file_git_blob_oid", {})
    selected = set(source_files)
    if (
        not isinstance(expected_sha, Mapping)
        or not isinstance(expected_oids, Mapping)
        or not expected_sha
        or not expected_oids
        or set(expected_sha) != selected
        or set(expected_oids) != selected
    ):
        raise luna_v1.ApparatusFailure("preflight source maps do not bind the frozen source list")
    revision = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if revision != preflight.get("source_revision"):
        raise luna_v1.ApparatusFailure("source revision changed after preflight")
    for relative in source_files:
        state = _source_state(repo_root, relative)
        if state["head_oid"] != expected_oids[relative]:
            raise luna_v1.ApparatusFailure(
                f"committed source blob changed after preflight: {relative}"
            )
        if state["normalized_worktree_bytes"] != state["committed_bytes"]:
            raise luna_v1.ApparatusFailure(
                f"direct worktree source differs from HEAD after CRLF normalization: {relative}"
            )
        if state["canonical_sha256"] != expected_sha[relative]:
            raise luna_v1.ApparatusFailure(
                f"canonical committed source SHA changed after preflight: {relative}"
            )


@contextmanager
def _base_v1_protocol_identity() -> Iterator[None]:
    current = v1.PROTOCOL_ID
    v1.PROTOCOL_ID = _BASE_PROTOCOL_ID
    try:
        yield
    finally:
        v1.PROTOCOL_ID = current


def verify_sealed_v1_failure(repo_root: Path) -> Mapping[str, Any]:
    try:
        evidence = _git(
            repo_root, "rev-parse", f"{SEALED_V1_EVIDENCE_COMMIT}^{{commit}}"
        ).stdout.strip()
        implementation = _git(
            repo_root, "rev-parse", f"{SEALED_V1_IMPLEMENTATION_COMMIT}^{{commit}}"
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 lineage cannot be resolved") from exc
    if evidence != SEALED_V1_EVIDENCE_COMMIT or implementation != SEALED_V1_IMPLEMENTATION_COMMIT:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 lineage resolved unexpectedly")
    parents = _git(
        repo_root, "show", "-s", "--format=%P", SEALED_V1_EVIDENCE_COMMIT
    ).stdout.strip().split()
    if parents != [SEALED_V1_IMPLEMENTATION_COMMIT]:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 evidence parent changed")
    current = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if _git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        SEALED_V1_EVIDENCE_COMMIT,
        current,
        check=False,
    ).returncode != 0:
        raise luna_v1.ApparatusFailure("current source does not descend from sealed Protocol v1")
    tree_oid = _git(
        repo_root,
        "rev-parse",
        f"{SEALED_V1_EVIDENCE_COMMIT}:{SEALED_V1_RUN_DIR.as_posix()}",
    ).stdout.strip()
    if tree_oid != SEALED_V1_EVIDENCE_TREE_OID:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 evidence tree changed")
    run_dir = repo_root / SEALED_V1_RUN_DIR
    actual_files = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    if actual_files != set(SEALED_V1_ARTIFACT_SHA256):
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 artifact set changed")
    for relative, digest in SEALED_V1_ARTIFACT_SHA256.items():
        if luna_v1._sha256_bytes((run_dir / relative).read_bytes()) != digest:
            raise luna_v1.ApparatusFailure(
                f"sealed Protocol-v1 artifact changed: {relative}"
            )
    for relative, expected_oid in SEALED_V1_SOURCE_BLOB_OID.items():
        oid = _git(
            repo_root, "rev-parse", f"{SEALED_V1_IMPLEMENTATION_COMMIT}:{relative}"
        ).stdout.strip()
        committed = _git(
            repo_root,
            "show",
            f"{SEALED_V1_IMPLEMENTATION_COMMIT}:{relative}",
            text=False,
        ).stdout
        if oid != expected_oid or hashlib.sha256(committed).hexdigest() != SEALED_V1_SOURCE_SHA256[relative]:
            raise luna_v1.ApparatusFailure(
                f"sealed Protocol-v1 implementation source changed: {relative}"
            )
    with _base_v1_protocol_identity():
        verified = _BASE_VERIFY_RUN(run_dir)
    if (
        verified.get("validity") != "INVALID"
        or verified.get("result_code") != "INVALID_APPARATUS"
        or verified.get("physical_generation_calls") != 0
        or verified.get("source_revision") != SEALED_V1_IMPLEMENTATION_COMMIT
    ):
        raise luna_v1.ApparatusFailure("sealed Protocol-v1 invalid result no longer verifies")
    return {
        "sealed_v1_evidence_commit": evidence,
        "sealed_v1_implementation_commit": implementation,
        "sealed_v1_evidence_tree_oid": tree_oid,
        "sealed_v1_result_sha256": SEALED_V1_ARTIFACT_SHA256["RESULT.json"],
        "sealed_v1_evidence_index_sha256": SEALED_V1_ARTIFACT_SHA256[
            "EVIDENCE_INDEX.json"
        ],
        "sealed_v1_verification": verified,
    }


def _verify_v1_1_lineage(repo_root: Path) -> Mapping[str, Any]:
    lineage = dict(_BASE_VERIFY_SEALED_PARENT(repo_root))
    lineage["sealed_protocol_v1_invalid_evidence"] = verify_sealed_v1_failure(repo_root)
    return lineage


def _deterministic_preflight_impl(
    repo_root: Path, *, require_committed: bool = True
):
    payload, cases, calls, sealed = _BASE_DETERMINISTIC_PREFLIGHT(
        repo_root, require_committed=require_committed
    )
    preflight = dict(sealed)
    preflight.pop("payload_sha256", None)
    if require_committed:
        revision, sha256, blob_oids = _source_maps(repo_root)
        if (
            revision != preflight.get("source_revision")
            or sha256 != preflight.get("source_file_sha256")
        ):
            raise luna_v1.ApparatusFailure("preflight source reporting is inconsistent")
    else:
        blob_oids = {}
    preflight["source_file_git_blob_oid"] = blob_oids
    preflight["source_guard"] = {
        "version": "direct-crlf-normalized-bytes-v1.1",
        "head_revision_required": True,
        "head_blob_must_match_preflight": True,
        "direct_worktree_crlf_to_lf_must_equal_committed_bytes": True,
        "canonical_git_show_sha256_must_match_preflight": True,
        "git_clean_filters_consulted_for_worktree_equality": False,
    }
    return payload, cases, calls, luna_v1._sealed(preflight)


@contextmanager
def _activated_protocol() -> Iterator[None]:
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "_git_revision_and_sources": _git_revision_and_sources,
        "_assert_sources_unchanged": _assert_sources_unchanged,
        "verify_sealed_parent": _verify_v1_1_lineage,
        "deterministic_preflight": _deterministic_preflight_impl,
    }
    originals = {name: getattr(v1, name) for name in replacements}
    for name, value in replacements.items():
        setattr(v1, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(v1, name, value)


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _activated_protocol():
        return _deterministic_preflight_impl(
            repo_root, require_committed=require_committed
        )


class SemanticDecompositionV11Runner(v1.SemanticDecompositionRunner):
    def run(self) -> Mapping[str, Any]:
        with _activated_protocol():
            return super().run()


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    with _activated_protocol():
        return _BASE_VERIFY_RUN(run_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        ACKNOWLEDGEMENT,
        dest="acknowledge",
        action="store_true",
        help="required acknowledgement for the one frozen 384-call Protocol-v1.1 run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(luna_v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge:
        parser.error(f"{ACKNOWLEDGEMENT} is required")
    luna_v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = SemanticDecompositionV11Runner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(luna_v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
