"""Create the HIVE-FACTORIAL-002 lock once, after read-only preflight."""

from __future__ import annotations

import json
from pathlib import Path

import runner


def main() -> None:
    facts = runner.lock_facts()
    lock_path = Path(runner.LOCK_PATH)
    hash_path = lock_path.with_name("LOCK.sha256")
    if lock_path.exists() or hash_path.exists() or runner.EVIDENCE.exists():
        raise RuntimeError("successor freeze or evidence already exists; refusing to overwrite")
    payload = json.dumps(facts, indent=2, ensure_ascii=False) + "\n"
    with lock_path.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    digest = runner.sha(lock_path)
    with hash_path.open("x", encoding="ascii") as stream:
        stream.write(digest + "\n")
    runner.check_lock(facts)
    print(f"HIVE-FACTORIAL-002 lock: {digest}")


if __name__ == "__main__":
    main()
