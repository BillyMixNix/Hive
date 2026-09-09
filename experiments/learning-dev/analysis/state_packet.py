"""Offline packet experiment primitives. No model calls or paid launch path.

Inputs must be a trusted public snapshot of THIS recipient, not prior outcomes.
Hashes bind bytes, not truth. Callers remain responsible for snapshot provenance.
"""
import hashlib
import json
from pathlib import PurePosixPath

from hive_learning.evaluate import grade, validate_files


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


FIELDS = {"objective", "files", "constraints", "allowed_actions", "events", "uncertainties", "verification"}
EVENT_FIELDS = {"id", "sequence", "kind", "status", "source", "text"}


def validate_snapshot(snapshot):
    if set(snapshot) != FIELDS:
        raise ValueError("public snapshot fields differ; private fields are forbidden")
    if not isinstance(snapshot["objective"], str) or not snapshot["objective"].strip():
        raise ValueError("missing objective")
    validate_files(snapshot["files"])
    for field in ("constraints", "allowed_actions", "uncertainties", "verification"):
        if not isinstance(snapshot[field], list) or any(not isinstance(x, str) or not x.strip() for x in snapshot[field]):
            raise ValueError("invalid public declarations")
    if not snapshot["allowed_actions"] or not snapshot["verification"]:
        raise ValueError("missing authority or verification")
    if not isinstance(snapshot["events"], list):
        raise ValueError("invalid event history")
    ids, last = set(), -1
    for event in snapshot["events"]:
        if set(event) != EVENT_FIELDS:
            raise ValueError("invalid event fields")
        if any(not isinstance(event[k], str) or not event[k].strip() for k in EVENT_FIELDS - {"sequence"}):
            raise ValueError("event strings required")
        if event["id"] in ids or type(event["sequence"]) is not int or event["sequence"] <= last:
            raise ValueError("duplicate or unordered event")
        if event["kind"] not in {"observation", "action", "plan", "claim"} or event["status"] not in {"current", "superseded", "rejected", "unverified"}:
            raise ValueError("untyped event")
        if event["kind"] in {"plan", "claim"} and event["status"] == "current":
            raise ValueError("plan or claim cannot become current evidence")
        ids.add(event["id"])
        last = event["sequence"]


def compile_packet(snapshot, max_bytes=100_000):
    validate_snapshot(snapshot)
    # Preserve every supplied distinction. No heuristic truncation or inference.
    packet = {"schema": "hive.public-state-packet.v1", "snapshot_sha256": digest(snapshot),
              "state": json.loads(canonical(snapshot))}
    if len(canonical(packet).encode()) > max_bytes:
        raise ValueError("packet exceeds budget; fuller-context fallback required")
    return packet


def verify_packet(packet, snapshot):
    expected = compile_packet(snapshot)
    if canonical(packet) != canonical(expected):
        raise ValueError("packet omitted, changed, or promoted public state")
    return True


def prompt_conditions(snapshot, lessons):
    """Paired public content; formatting is the packet intervention.

    raw and packet have identical information. lessons adds advice to raw.
    Packet overhead counts toward cost; compactness is measured, never assumed.
    """
    packet = compile_packet(snapshot)
    if not isinstance(lessons, list) or any(not isinstance(x, str) for x in lessons):
        raise ValueError("lessons must be frozen text")
    raw = json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False)
    return {"raw": raw, "lessons": raw + "\nAdvisory lessons:\n" + canonical(lessons),
            "packet": canonical(packet)}


def score_candidate(snapshot, candidate, protected_tests, *, calls, decision, call_limit=36):
    """Grade actual final source, not diff-shaped prose. Trusted local bench only."""
    validate_snapshot(snapshot)
    validate_files(candidate)
    validate_files(protected_tests)
    if type(calls) is not int or type(call_limit) is not int or not 0 <= calls <= call_limit or call_limit < 1:
        raise ValueError("invalid call accounting")
    if decision not in {"SATISFIED", "FAILED", "EXHAUSTED"}:
        raise ValueError("unknown controller decision")
    baseline = snapshot["files"]
    if set(candidate) != set(baseline) or set(protected_tests) & set(candidate):
        raise ValueError("candidate scope or protected-test collision")
    if any(not PurePosixPath(p).name.startswith("test_") for p in protected_tests):
        raise ValueError("invalid protected tests")
    if any(candidate[p] != source for p, source in baseline.items() if PurePosixPath(p).name.startswith("test_")):
        raise ValueError("public tests changed")
    result = grade(candidate, protected_tests)
    valid = result["valid"]
    return {"candidate_sha256": digest(candidate), "evaluation": result,
            "false_completion": valid and decision == "SATISFIED" and not result["passed"],
            "penalized_calls": (calls if result["passed"] else call_limit) if valid else None,
            "usable": valid}
