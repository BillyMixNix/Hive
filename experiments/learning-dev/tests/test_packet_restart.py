"""Hand-authored transition oracle, tested across a real process boundary."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from analysis.state_packet import compile_packet, digest

DECODER = Path(__file__).resolve().parents[1]/"analysis/packet_restart.py"


def checkpoint():
    # A failed repair, later file revision, stale success, and unverified claim
    # must survive together without confusing old success with current evidence.
    return {
        "objective": "Handle explicit zero without changing the public interface",
        "files": {"config.py": "def limit(x):\n    return 10 if x is None else x\n"},
        "constraints": ["Do not change public tests"],
        "allowed_actions": ["read", "edit config.py", "run public tests"],
        "events": [
            {"id": "old-pass", "sequence": 1, "kind": "observation", "status": "superseded", "source": "public-test-run:1", "text": "Default case passed before zero was tested"},
            {"id": "zero-failed", "sequence": 2, "kind": "observation", "status": "current", "source": "public-test-run:2", "text": "Zero returned 10; expected 0 in the prior revision"},
            {"id": "bad-repair", "sequence": 3, "kind": "action", "status": "rejected", "source": "scope-check:3", "text": "Attempt to change public tests rejected"},
            {"id": "repair", "sequence": 4, "kind": "action", "status": "current", "source": "file-write:4", "text": "Changed fallback to an explicit None check"},
            {"id": "claimed-pass", "sequence": 5, "kind": "claim", "status": "unverified", "source": "assistant:5", "text": "Everything passes now"},
        ],
        "uncertainties": ["The latest revision has not been tested"],
        "verification": ["Run public tests on the latest revision before completion"],
    }


def fresh(packet, commitment, tmp_path):
    # Empty working directory, isolated Python, no parent conversation or fixture
    # passed to the child. Shared decoder code is available; this is not a sandbox.
    return subprocess.run([sys.executable, "-I", str(DECODER), "--checkpoint-sha256", commitment],
        input=json.dumps(packet), text=True, capture_output=True, cwd=tmp_path,
        env={"PYTHONDONTWRITEBYTECODE": "1"}, timeout=10)


def test_restart_restores_exact_state_and_keeps_evidence_distinctions(tmp_path):
    state = checkpoint()
    packet = compile_packet(state)
    result = fresh(packet, digest(state), tmp_path)
    assert result.returncode == 0, result.stderr
    restored = json.loads(result.stdout)
    assert restored["state"] == state
    assert restored["current_evidence"] == ["zero-failed", "repair"]
    assert restored["superseded"] == ["old-pass"]
    assert restored["rejected"] == ["bad-repair"]
    assert restored["unverified"] == ["claimed-pass"]


@pytest.mark.parametrize("mutation", ["stale_file", "omit_failure", "erase_uncertainty", "promote_claim", "reorder", "expand_authority", "self_rehash"])
def test_restart_rejects_loss_or_promotion(tmp_path, mutation):
    state = checkpoint()
    packet = copy.deepcopy(compile_packet(state))
    s = packet["state"]
    if mutation == "stale_file": s["files"]["config.py"] = "def limit(x): return x or 10\n"
    if mutation == "omit_failure": s["events"].pop(1)
    if mutation == "erase_uncertainty": s["uncertainties"] = []
    if mutation == "promote_claim": s["events"][-1]["status"] = "current"
    if mutation == "reorder": s["events"].reverse()
    if mutation == "expand_authority": s["allowed_actions"].append("publish")
    if mutation == "self_rehash":
        s["uncertainties"] = []
        packet["snapshot_sha256"] = digest(s)
    result = fresh(packet, digest(state), tmp_path)
    assert result.returncode != 0
    assert not result.stdout
