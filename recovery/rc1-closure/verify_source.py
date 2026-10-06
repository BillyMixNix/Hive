"""Verify RC1 legacy byte preservation and the explicit closure adapter delta."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "recovery/rc1"))
import manifest  # noqa: E402

PARENT_COMMIT = "dd5db7108c7d4e37ef757f7577456e0d9f5105db"
PARENT_SOURCE_MANIFEST_SHA = "35617f3e24887b013bcc0e237c2f51276dee20983c4b2004f1298dfaeb531f55"
PATHS = (
    "RECOVERY_FIXTURE_MAP.json",
    "tests/recovery/test_rc1_closure.py",
    "recovery/rc1-closure/fixture_resolver.py",
    "recovery/rc1-closure/gradle_trust_probe.py",
    "recovery/rc1-closure/baseline_control.py",
    "recovery/rc1-closure/verify_source.py",
    "recovery/rc1-closure/environment/verify_environment.py",
    "recovery/rc1-closure/environment/ENVIRONMENT_MANIFEST.json",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict:
    parent = ROOT / "recovery/rc1/SOURCE_MANIFEST.json"
    if sha(parent.read_bytes()) != PARENT_SOURCE_MANIFEST_SHA:
        raise ValueError("RC1 source manifest changed")
    current, _ = manifest.build(ROOT)  # verifies all byte-preserved legacy blobs
    prior = json.loads(parent.read_bytes())
    old = {row["path"]: row for row in prior["files"]}
    rows = []
    for row in current["files"]:
        entry = dict(row)
        previous = old.get(row["path"])
        if previous is None:
            raise ValueError(f"unexpected runtime file: {row['path']}")
        if row["path"] == "hive_canonical/controller.py":
            entry["status"] = "ADAPTED"
            entry["recovered_source_path"] = row["path"]
            entry["recovered_revision"] = PARENT_COMMIT
            entry["pre_adaptation_sha256"] = previous["sha256"]
            entry["adaptation_reason"] = "Reject unqualified Gradle build-control scope before model execution"
        elif row["sha256"] != previous["sha256"]:
            raise ValueError(f"unexplained runtime drift: {row['path']}")
        rows.append(entry)
    for path in PATHS:
        data = (ROOT / path).read_bytes()
        rows.append({"path": path, "sha256": sha(data), "bytes": len(data),
                     "status": "NEW_RECOVERY_CODE", "recovered_source_path": None,
                     "recovered_revision": None,
                     "adaptation_reason": "Deterministic closure evidence, resolver or guard tests"})
    return {"schema_version": 1, "parent_commit": PARENT_COMMIT,
            "parent_source_manifest_sha256": PARENT_SOURCE_MANIFEST_SHA,
            "files": rows}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "verify"))
    args = parser.parse_args()
    path = ROOT / "recovery/rc1-closure/SOURCE_MANIFEST.json"
    data = build()
    if args.mode == "write":
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif json.loads(path.read_bytes()) != data:
        raise ValueError("closure source manifest drift")
    print(f"verified {len(data['files'])} source and recovery files")
