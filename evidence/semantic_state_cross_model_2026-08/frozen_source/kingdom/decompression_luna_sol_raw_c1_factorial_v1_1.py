"""Clean restart of the frozen Luna/Sol x Raw/C1 factorial experiment.

Protocol v1.1 changes only the protocol/run identity and sealed lineage after
v1 stopped fail-closed on a pre-response transport error.  Every
hypothesis-bearing input and every inference rule remains inherited from v1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Sequence

from hive_llm import ask_hive
from kingdom import decompression_luna_sol_raw_c1_factorial as v1


PROTOCOL_ID = "hive-luna-sol-raw-c1-factorial-v1.1"
PROTOCOL_VERSION = "1.1"
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/luna-sol-raw-c1-factorial-v1-1-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-luna-sol-raw-c1-factorial-v1-1"

SEALED_V1_EVIDENCE_COMMIT = "a76e28031321a2b5d255b7df39d0d4db425fce22"
SEALED_V1_SOURCE_REVISION = "45f6f16eef5f3a323a88ab99addca7d7ba6ee62e"
SEALED_V1_RUN_TREE_OID = "1f75fc5744228ff0eab70af788b75f380c50fd3c"
SEALED_V1_RESULT_SHA256 = (
    "8a032a1116172cfbee796db76031b490365bbaefeec91181de09ebfaf00c199b"
)
SEALED_V1_INDEX_SHA256 = (
    "5921f5829fc56d71253cbcb63edfb3d60602beab9cfba964ce0e8f4c0daae55f"
)
SEALED_V1_FAILED_CALL_SHA256 = (
    "1ae785570658d0ccfbdde4a7d6f2b0bdaf74a4607e671c4a3336562b68a7a8f9"
)
SEALED_V1_RESPONSE_IDS_SHA256 = (
    "bf783f69a5349a5e4155fe5f37098eb5ac3921cf7341e9674e18b016fae1fc19"
)
SEALED_V1_COMMON_SOURCES_SHA256 = (
    "d976efc02d00423b70bb35a485f8ccd63051005cf3bc6b92f4d486484702e599"
)
SEALED_V1_RESPONSE_ID_COUNT = 21

MODULE_PATH = "kingdom/decompression_luna_sol_raw_c1_factorial_v1_1.py"
TEST_PATH = "tests/test_decompression_luna_sol_raw_c1_factorial_v1_1.py"
PROTOCOL_PATH = (
    "benchmarks/decompression_test/PROTOCOL_LUNA_SOL_RAW_C1_FACTORIAL_V1_1.md"
)
SOURCE_FILES = tuple(
    dict.fromkeys((*v1.SOURCE_FILES, MODULE_PATH, TEST_PATH, PROTOCOL_PATH))
)

_BASE_BINDINGS = {
    "PROTOCOL_ID": v1.PROTOCOL_ID,
    "PROTOCOL_VERSION": v1.PROTOCOL_VERSION,
    "RUN_DIR": v1.RUN_DIR,
    "SOURCE_FILES": v1.SOURCE_FILES,
    "verify_sealed_parent": v1.verify_sealed_parent,
}
BASE_RUN_DIR = _BASE_BINDINGS["RUN_DIR"]


@contextmanager
def _bindings(replacements: Mapping[str, Any]):
    originals = {name: getattr(v1, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v1, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(v1, name, value)


@contextmanager
def _base_v1_bindings():
    with _bindings(_BASE_BINDINGS):
        yield


def _extract_sealed_v1_response_ids(repo_root: Path) -> frozenset[str]:
    response_ids = []
    for path in sorted((repo_root / BASE_RUN_DIR).glob("*/calls/call_*.json")):
        call = json.loads(path.read_text(encoding="utf-8"))
        v1._verify_seal(call)
        response_id = call.get("transport_metadata", {}).get("response_id")
        if isinstance(response_id, str) and response_id:
            response_ids.append(response_id)
    if len(response_ids) != SEALED_V1_RESPONSE_ID_COUNT or len(
        set(response_ids)
    ) != SEALED_V1_RESPONSE_ID_COUNT:
        raise v1.ApparatusFailure("sealed v1 response identities are incomplete or reused")
    frozen = frozenset(response_ids)
    digest = v1._sha256_text(v1._canonical_json(sorted(frozen)))
    if digest != SEALED_V1_RESPONSE_IDS_SHA256:
        raise v1.ApparatusFailure("sealed v1 response identity set changed")
    return frozen


def _verify_common_source_equivalence(repo_root: Path) -> Mapping[str, Any]:
    precheck_path = repo_root / BASE_RUN_DIR / "PRECHECK.json"
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    v1._verify_seal(precheck)
    recorded = precheck.get("source_file_sha256")
    base_sources = set(_BASE_BINDINGS["SOURCE_FILES"])
    if not isinstance(recorded, Mapping) or set(recorded) != base_sources:
        raise v1.ApparatusFailure("sealed v1 common source hash set is incomplete")
    digest = v1._sha256_text(v1._canonical_json(recorded))
    if digest != SEALED_V1_COMMON_SOURCES_SHA256:
        raise v1.ApparatusFailure("sealed v1 common source hash map changed")
    current_revision = v1._git(repo_root, "rev-parse", "HEAD").stdout.strip()
    for relative in sorted(base_sources):
        content = subprocess.run(
            ["git", "show", f"{current_revision}:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        if v1._sha256_bytes(content) != recorded[relative]:
            raise v1.ApparatusFailure(
                f"v1.1 common source differs from sealed v1: {relative}"
            )
    return {
        "common_source_count": len(base_sources),
        "common_sources_sha256": digest,
        "common_sources_match_sealed_v1": True,
    }


def verify_sealed_v1(repo_root: Path) -> Mapping[str, Any]:
    resolved = v1._git(
        repo_root, "rev-parse", f"{SEALED_V1_EVIDENCE_COMMIT}^{{commit}}"
    ).stdout.strip()
    if resolved != SEALED_V1_EVIDENCE_COMMIT:
        raise v1.ApparatusFailure("sealed v1 evidence commit did not resolve exactly")
    parent_line = v1._git(
        repo_root, "rev-list", "--parents", "-n", "1", SEALED_V1_EVIDENCE_COMMIT
    ).stdout.strip()
    if parent_line != f"{SEALED_V1_EVIDENCE_COMMIT} {SEALED_V1_SOURCE_REVISION}":
        raise v1.ApparatusFailure("sealed v1 evidence commit has unexpected parentage")
    tree_oid = v1._git(
        repo_root,
        "rev-parse",
        f"{SEALED_V1_EVIDENCE_COMMIT}:{BASE_RUN_DIR.as_posix()}",
    ).stdout.strip()
    if tree_oid != SEALED_V1_RUN_TREE_OID:
        raise v1.ApparatusFailure("sealed v1 run tree identity changed")
    current = v1._git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if v1._git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        SEALED_V1_EVIDENCE_COMMIT,
        current,
        check=False,
    ).returncode != 0:
        raise v1.ApparatusFailure("v1.1 source does not descend from sealed v1 evidence")

    result_path = repo_root / BASE_RUN_DIR / "RESULT.json"
    index_path = repo_root / BASE_RUN_DIR / "EVIDENCE_INDEX.json"
    failed_path = repo_root / BASE_RUN_DIR / "sol_raw/calls/call_000006.json"
    frozen_hashes = {
        "v1_result_sha256": (result_path, SEALED_V1_RESULT_SHA256),
        "v1_evidence_index_sha256": (index_path, SEALED_V1_INDEX_SHA256),
        "v1_failed_call_sha256": (failed_path, SEALED_V1_FAILED_CALL_SHA256),
    }
    for name, (path, expected) in frozen_hashes.items():
        if not path.is_file() or v1._sha256_bytes(path.read_bytes()) != expected:
            raise v1.ApparatusFailure(f"sealed {name} changed")

    with _base_v1_bindings():
        verified = v1.verify_run(repo_root / BASE_RUN_DIR)
    if (
        verified.get("verified") is not True
        or verified.get("validity") != "INVALID"
        or verified.get("result_code") != "INVALID_APPARATUS"
        or verified.get("physical_generation_calls") != 22
        or verified.get("decision_artifacts") != 21
        or verified.get("unique_response_ids") != 21
        or verified.get("source_revision") != SEALED_V1_SOURCE_REVISION
    ):
        raise v1.ApparatusFailure("sealed v1 apparatus-failure evidence did not verify")
    response_ids = _extract_sealed_v1_response_ids(repo_root)
    common_sources = _verify_common_source_equivalence(repo_root)
    return {
        "restart_parent": SEALED_V1_EVIDENCE_COMMIT,
        "current_revision": current,
        "v1_source_revision": SEALED_V1_SOURCE_REVISION,
        "v1_run_tree_oid": SEALED_V1_RUN_TREE_OID,
        "v1_response_id_count": len(response_ids),
        "v1_response_ids_sha256": SEALED_V1_RESPONSE_IDS_SHA256,
        **common_sources,
        **{name: expected for name, (_path, expected) in frozen_hashes.items()},
        "v1_verification": verified,
        "v1_disposition": "INVALID_APPARATUS",
        "v1_outputs_excluded_from_v1_1": True,
    }


def sealed_v1_response_ids(repo_root: Path) -> frozenset[str]:
    verify_sealed_v1(repo_root)
    return _extract_sealed_v1_response_ids(repo_root)


def verify_sealed_parent(repo_root: Path) -> Mapping[str, Any]:
    return verify_sealed_v1(repo_root)


@contextmanager
def _v1_1_bindings():
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "verify_sealed_parent": verify_sealed_parent,
    }
    with _bindings(replacements):
        yield


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _v1_1_bindings():
        payload, cases, calls, preflight = v1.deterministic_preflight(
            repo_root, require_committed=require_committed
        )
    if preflight["protocol_id"] != PROTOCOL_ID:
        raise v1.ApparatusFailure("v1.1 preflight protocol identity was not activated")
    if len(calls) != v1.MAX_GENERATION_CALLS:
        raise v1.ApparatusFailure("v1.1 call count differs from frozen v1")
    return payload, cases, calls, preflight


def derived_frozen_values(repo_root: Path) -> Mapping[str, Any]:
    with _v1_1_bindings():
        return v1.derived_frozen_values(repo_root)


class RestartRunner(v1.FactorialRunner):
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn=ask_hive,
        require_committed: bool = True,
        progress_stream: Any | None = None,
    ) -> None:
        self.sealed_v1_response_ids = sealed_v1_response_ids(repo_root)

        def disjoint_ask(prompt, **kwargs):
            metadata = kwargs["metadata"]
            response = ask_fn(prompt, **kwargs)
            response_id = metadata.get("response_id")
            if response_id in self.sealed_v1_response_ids:
                metadata["sealed_v1_response_id_rejected"] = response_id
                metadata["sealed_v1_response_id_rejected_sha256"] = v1._sha256_text(
                    str(response_id)
                )
                metadata["response_id"] = None
            return response

        super().__init__(
            repo_root=repo_root,
            output_dir=output_dir,
            ask_fn=disjoint_ask,
            require_committed=require_committed,
            progress_stream=progress_stream,
        )

    def run(self) -> Mapping[str, Any]:
        with _v1_1_bindings():
            return super().run()


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    with _v1_1_bindings():
        verified = v1.verify_run(run_dir)
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = sealed_v1_response_ids(repo_root)
    intersections: set[str] = set()
    explicit_rejections = []
    for path in sorted(run_dir.glob("*/calls/call_*.json")):
        call = json.loads(path.read_text(encoding="utf-8"))
        v1._verify_seal(call)
        metadata = call.get("transport_metadata")
        if not isinstance(metadata, Mapping):
            raise v1.ApparatusFailure("v1.1 call metadata is malformed")
        response_id = metadata.get("response_id")
        if isinstance(response_id, str) and response_id in forbidden:
            intersections.add(response_id)
        rejected = metadata.get("sealed_v1_response_id_rejected")
        rejected_hash = metadata.get("sealed_v1_response_id_rejected_sha256")
        if rejected is not None or rejected_hash is not None:
            if (
                not isinstance(rejected, str)
                or rejected not in forbidden
                or rejected_hash != v1._sha256_text(rejected)
                or response_id is not None
                or call.get("status") != "metadata_rejected"
                or call.get("admission_error", {}).get("message")
                != "response ID is missing"
            ):
                raise v1.ApparatusFailure(
                    "sealed-v1 response-ID rejection envelope is incoherent"
                )
            explicit_rejections.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "response_id_sha256": rejected_hash,
                }
            )
    if intersections:
        raise v1.ApparatusFailure("v1.1 reused a sealed-v1 provider response identity")
    if len(explicit_rejections) > 1:
        raise v1.ApparatusFailure("v1.1 contains multiple cross-run identity rejections")
    if explicit_rejections:
        result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
        v1._verify_seal(result)
        failed_pointer = result.get("failure_evidence", {}).get(
            "failed_call_artifact", {}
        )
        if (
            result.get("validity") != "INVALID"
            or result.get("result_code") != "INVALID_APPARATUS"
            or result.get("apparatus_failure", "").split(" metadata rejected:")[-1]
            != " response ID is missing"
            or failed_pointer.get("path") != explicit_rejections[0]["path"]
        ):
            raise v1.ApparatusFailure(
                "cross-run identity rejection is not the terminal apparatus failure"
            )
    enriched = dict(verified)
    enriched.update(
        {
            "sealed_v1_response_id_overlap": 0,
            "sealed_v1_response_id_rejections": len(explicit_rejections),
            "sealed_v1_response_ids_sha256": SEALED_V1_RESPONSE_IDS_SHA256,
        }
    )
    return enriched


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(ACKNOWLEDGEMENT, dest="acknowledge", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--derive-frozen-values", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    if args.verify is not None:
        print(v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if args.derive_frozen_values:
        print(v1._pretty_json(derived_frozen_values(repo_root)), end="")
        return 0
    if not args.acknowledge:
        parser.error(f"{ACKNOWLEDGEMENT} is required")
    v1.frontier._check_live_prerequisites()
    result = RestartRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
        ask_fn=ask_hive,
    ).run()
    print(v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
