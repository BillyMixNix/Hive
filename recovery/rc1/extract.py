"""Extract only the selected controller's source blobs into the RC1 namespace.

The extraction reads committed Git blobs, bypassing checkout line-ending filters.
It never writes to the recovered archive.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ANCHOR = "edadbd8da46f3fd5ace479b7292012665d80096f"
ARCHIVE = "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1"


def git_blob(repo: Path, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{ANCHOR}:{path}"], stderr=subprocess.PIPE
    )


def extract(repo: Path) -> list[dict]:
    repo = repo.resolve()
    freeze = json.loads(git_blob(repo, f"{ARCHIVE}/FREEZE.json"))
    expected = freeze["source"]["production_files"]
    result = []
    for rel in sorted(expected):
        if not rel.startswith(("workshop/", "verification/")):
            continue
        source = f"{ARCHIVE}/repaired-workshop/{rel}"
        data = git_blob(repo, source)
        sha = hashlib.sha256(data).hexdigest()
        if sha != expected[rel]["sha256"] or len(data) != expected[rel]["size"]:
            raise ValueError(f"Frozen source identity differs: {source}")
        target = repo / "hive_canonical" / "legacy" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError(f"Copied source differs: {target}")
        result.append({"path": target.relative_to(repo).as_posix(), "source": source, "sha256": sha})
    if not result:
        raise ValueError("No frozen controller files selected")
    return result


if __name__ == "__main__":
    rows = extract(Path(__file__).resolve().parents[2])
    print(f"Extracted {len(rows)} byte-preserved controller/verifier files")
