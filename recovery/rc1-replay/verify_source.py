"""Validate the 001C runtime delta against immutable RC1/001B provenance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "recovery/rc1"))
import manifest  # noqa: E402

CLOSURE_SHA = "8e10fedfa30205e2d381d0f7696fc6c4b8c8998f776f704718347ad2144eb192"
NEW_RUNTIME = {"hive_canonical/diagnostics.py", "hive_canonical/replay.py"}
ADAPTED = {"hive_canonical/controller.py"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict:
    closure_path = ROOT / "recovery/rc1-closure/SOURCE_MANIFEST.json"
    if sha(closure_path.read_bytes()) != CLOSURE_SHA:
        raise ValueError("001B source provenance changed")
    closure = json.loads(closure_path.read_bytes())
    old = {row["path"]: row for row in closure["files"] if row["path"].startswith("hive_canonical/")}
    current, _ = manifest.build(ROOT)  # checks every copied legacy source byte
    rows = []
    for row in current["files"]:
        path = row["path"]
        previous = old.get(path)
        if path in NEW_RUNTIME:
            if previous is not None:
                raise ValueError("new runtime path previously existed")
            row.update(status="NEW_RECOVERY_CODE", recovered_source_path=None,
                       recovered_revision=None, adaptation_reason="001C safe diagnostic or host-bound replay boundary")
        elif path in ADAPTED:
            if previous is None:
                raise ValueError("adapted controller has no predecessor")
            row.update(status="ADAPTED", recovered_source_path=path,
                       recovered_revision="427ad3cce3916aa6d0c0b450d43ad1833b8688eb",
                       pre_adaptation_sha256=previous["sha256"],
                       adaptation_reason="Allow only recovery-built, hash-registered post-verification model prompts")
        elif previous is None or row["sha256"] != previous["sha256"]:
            raise ValueError(f"unexplained runtime drift: {path}")
        rows.append(row)
    if {row["path"] for row in rows} != set(old) | NEW_RUNTIME:
        raise ValueError("runtime file set differs from reviewed 001B plus 001C delta")
    return {"schema_version": 1, "closure_commit": "427ad3cce3916aa6d0c0b450d43ad1833b8688eb",
            "closure_source_manifest_sha256": CLOSURE_SHA, "files": rows,
            "promotion_authorization": "unavailable", "model_calls_in_001c": 0}


if __name__ == "__main__":
    destination = ROOT / "recovery/rc1-replay/SOURCE_MANIFEST.json"
    value = build()
    if len(sys.argv) != 2 or sys.argv[1] not in ("write", "verify"):
        raise SystemExit("usage: verify_source.py write|verify")
    if sys.argv[1] == "write":
        destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    elif json.loads(destination.read_bytes()) != value:
        raise ValueError("001C source manifest drift")
    print(f"verified {len(value['files'])} runtime files")
