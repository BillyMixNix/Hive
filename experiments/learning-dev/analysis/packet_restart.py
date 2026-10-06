"""Restore a committed public packet in a fresh process; never calls a model.

The external digest must come from a trusted checkpoint record. This verifies
transport and typed restoration, not whether an agent can use the restored state.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.state_packet import canonical, digest, validate_snapshot


def restore(packet, expected_digest):
    if set(packet) != {"schema", "snapshot_sha256", "state"}:
        raise ValueError("invalid packet envelope")
    if packet["schema"] != "hive.public-state-packet.v1":
        raise ValueError("unsupported packet schema")
    state = packet["state"]
    validate_snapshot(state)
    if digest(state) != expected_digest or packet["snapshot_sha256"] != expected_digest:
        raise ValueError("checkpoint commitment differs")
    return {
        "state": state,
        "current_evidence": [e["id"] for e in state["events"] if e["status"] == "current"],
        "superseded": [e["id"] for e in state["events"] if e["status"] == "superseded"],
        "rejected": [e["id"] for e in state["events"] if e["status"] == "rejected"],
        "unverified": [e["id"] for e in state["events"] if e["status"] == "unverified"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-sha256", required=True)
    args = parser.parse_args()
    print(canonical(restore(json.load(sys.stdin), args.checkpoint_sha256)))
