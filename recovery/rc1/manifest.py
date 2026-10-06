"""Emit and verify byte-level provenance for the candidate-only RC1 runtime."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from extract import ANCHOR, ARCHIVE, git_blob


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(root: Path) -> tuple[dict, dict]:
    root = root.resolve()
    freeze = json.loads(git_blob(root, f"{ARCHIVE}/FREEZE.json"))
    selected = freeze["source"]["production_files"]
    records = []
    for file in sorted((root / "hive_canonical").rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts:
            continue
        rel = file.relative_to(root).as_posix()
        data = file.read_bytes()
        item = {"path": rel, "sha256": sha(data), "bytes": len(data)}
        if rel.startswith("hive_canonical/legacy/workshop/"):
            origin_rel = rel.removeprefix("hive_canonical/legacy/")
        elif rel.startswith("hive_canonical/legacy/verification/"):
            origin_rel = rel.removeprefix("hive_canonical/legacy/")
        else:
            origin_rel = None
        if origin_rel in selected:
            source = f"{ARCHIVE}/repaired-workshop/{origin_rel}"
            if sha(git_blob(root, source)) != item["sha256"] or item["sha256"] != selected[origin_rel]["sha256"]:
                raise ValueError(f"Recovered source no longer byte-preserved: {rel}")
            item.update(status="BYTE_PRESERVED", recovered_source_path=source,
                        recovered_revision=ANCHOR, adaptation_reason=None)
        else:
            item.update(status="NEW_RECOVERY_CODE", recovered_source_path=None,
                        recovered_revision=None,
                        adaptation_reason="Candidate-only authority adapter or namespace metadata")
        records.append(item)
    if not records:
        raise ValueError("No canonical runtime files")
    source_manifest = {"schema_version": 1, "anchor_commit": ANCHOR,
                       "selected_freeze_tree_sha256": freeze["source"]["tree_hash"],
                       "files": records}
    provenance = {
        "schema_version": 1, "recovery_anchor": ANCHOR,
        "selected_controller": "HIVE-FACTORIAL-003R1/repaired-workshop",
        "selected_source_freeze": f"{ARCHIVE}/FREEZE.json",
        "selected_source_tree_sha256": freeze["source"]["tree_hash"],
        "selected_production_tree_sha256": freeze["source"]["production_tree_hash"],
        "runtime_copy_policy": "Only workshop/ and verification/ production blobs copied byte-for-byte; new candidate-only adapter separated in hive_canonical",
        "live_model_trial_performed": False,
        "promotion_authorization": "unavailable",
        "excluded_runtime_authority": ["historical evidence", "experimental thinking policy", "unverified promotion bundle"],
    }
    return source_manifest, provenance


def write(root: Path) -> None:
    manifest, provenance = build(root)
    out = root / "recovery" / "rc1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Bound {len(manifest['files'])} runtime files to RC1 provenance")


if __name__ == "__main__":
    write(Path(__file__).resolve().parents[2])
