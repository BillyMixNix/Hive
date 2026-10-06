"""Replay an operator-curated project ledger with checked document evidence.

This adapter verifies source bytes and excerpt presence, then delegates authority
and temporal decisions to EventLedger. It does not infer facts from prose or
prove that an operator's interpretation of a matching excerpt is correct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hive_reference.model import (
    Authority, CanonicalEvent, ClaimRevision, EffectOp, EvidenceBasis,
    EvidenceRef, EventLedger, FactKey, Observation, StateEffect, TruthStatus,
)


class ProjectStateError(ValueError):
    """An input cannot be safely interpreted as the documented ledger format."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectStateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ProjectStateError(f"non-finite JSON number: {value}")


def _fields(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(value, dict):
        raise ProjectStateError("expected an object")
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing or extra:
        raise ProjectStateError(f"invalid fields: missing={sorted(missing)}, extra={sorted(extra)}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectStateError(f"{label} must be nonempty text")
    return value


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ProjectStateError(f"{label} must use 1-100 letters, digits, underscores or hyphens")
    return value


def _time(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProjectStateError(f"{label} must be a nonnegative integer")
    return value


@dataclass
class ProjectLedger:
    project: str
    ledger: EventLedger
    records: dict[str, dict[str, Any]]

    def view(self, *, valid_at: int | None = None, known_at: int | None = None) -> dict[str, Any]:
        known = self.ledger.head_record_seq if known_at is None else _time(known_at, "known_at")
        events = [event for event in self.ledger.events if event.recorded_at <= known]
        valid = max((event.effective_time for event in events), default=0) if valid_at is None else _time(valid_at, "valid_at")
        snapshot = self.ledger.replay(valid_at=valid, known_at=known)
        ambiguous = set(snapshot.ambiguous_keys)
        current = {cell.source_claim_id for cell in snapshot.cells if cell.key not in ambiguous}
        replaced = {item.replaced_claim_id for item in snapshot.history if item.replaced_claim_id}
        admissions = {item.event_id: item for item in self.ledger.decisions}
        replay = {item.event_id: item for item in snapshot.decisions}
        rows = []
        for event in events:
            claim = event.claims[0]
            admission = admissions[event.event_id]
            applied = replay.get(event.event_id)
            if event.effective_time > valid:
                status = "future"
            elif claim.claim_id in current:
                status = "current"
            elif applied is not None and not applied.admitted:
                status = "not_applied"
            elif claim.claim_id in replaced:
                status = "superseded"
            elif claim.valid_to is not None and claim.valid_to <= valid:
                status = "expired"
            else:
                status = "inactive"
            row = dict(self.records[claim.claim_id])
            row.update(status=status, admission=admission.status.value,
                       reason=applied.reason if applied else admission.reason)
            rows.append(row)
        conflicts = []
        for key in snapshot.ambiguous_keys:
            entries = [item for item in snapshot.contradictions
                       if item.key == key and item.resolution == "unresolved"]
            conflicts.append({"subject": key.subject, "predicate": key.predicate,
                              "claim_ids": sorted({cid for item in entries for cid in item.claim_ids})})
        return {
            "schema_version": 1,
            "project": self.project,
            "scope": "operator_curated_documented_state",
            "valid_at": valid,
            "known_at": known,
            "ledger_sha256": self.ledger.digest,
            "snapshot_sha256": snapshot.digest,
            "current": [row for row in rows if row["status"] == "current"],
            "conflicts": conflicts,
            "other_records": [row for row in rows if row["status"] != "current"],
        }


def load_project(path: str | Path) -> ProjectLedger:
    """Load a manifest; every cited UTF-8 file must be beneath its directory."""
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object,
                      parse_constant=_constant)
    _fields(data, {"schema_version", "project", "sources", "records"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ProjectStateError("schema_version must be 1")
    project = _text(data["project"], "project")
    if not isinstance(data["sources"], list) or not isinstance(data["records"], list):
        raise ProjectStateError("sources and records must be arrays")
    ledger = EventLedger()
    sources = {}
    for source in data["sources"]:
        _fields(source, {"id", "path", "sha256", "recorded_at"})
        sid = _name(source["id"], "source id")
        if sid in sources:
            raise ProjectStateError(f"duplicate source id: {sid}")
        relative = Path(_text(source["path"], "source path"))
        resolved = (path.parent / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(path.parent):
            raise ProjectStateError("source path must stay beneath the manifest directory")
        expected = source["sha256"]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ProjectStateError("source sha256 must be 64 lowercase hexadecimal characters")
        raw = resolved.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ProjectStateError(f"source hash mismatch: {source['path']}")
        text = raw.decode("utf-8")
        observed = Observation.create(
            f"source_{sid}", sid, _time(source["recorded_at"], "source recorded_at"),
            {"path": relative.as_posix(), "file_sha256": expected, "text": text},
            provenance=("operator_curated_project_state_v1",),
        )
        ledger.append_observation(observed)
        sources[sid] = (observed, text, relative.as_posix(), expected)

    required = {"id", "subject", "predicate", "value", "effective_time", "recorded_at",
                "basis", "truth", "authority", "source", "excerpt"}
    for record in data["records"]:
        _fields(record, required, {"supersedes", "valid_to"})
        _time(record["recorded_at"], "record recorded_at")
    records = {}
    for record in sorted(data["records"], key=lambda item: item["recorded_at"]):
        cid = _name(record["id"], "record id")
        if cid in records:
            raise ProjectStateError(f"duplicate record id: {cid}")
        sid = _name(record["source"], "record source")
        if sid not in sources:
            raise ProjectStateError(f"unknown source: {sid}")
        observed, text, source_path, source_hash = sources[sid]
        excerpt = _text(record["excerpt"], "excerpt")
        offset = text.find(excerpt)
        if offset < 0:
            raise ProjectStateError(f"excerpt not found in {source_path}: {cid}")
        line = text[:offset].count("\n") + 1
        evidence = EvidenceRef.from_observation(observed, f"{source_path}:L{line}")
        value = record["value"]
        if type(value) not in (str, int, float, bool, type(None)):
            raise ProjectStateError("record values must be JSON scalars")
        if isinstance(value, float) and not math.isfinite(value):
            raise ProjectStateError("record values must be finite")
        supersedes = record.get("supersedes", [])
        if not isinstance(supersedes, list):
            raise ProjectStateError("supersedes must be an array of record ids")
        supersedes = tuple(_name(item, "superseded record id") for item in supersedes)
        key = FactKey(_name(record["subject"], "subject"), _name(record["predicate"], "predicate"))
        valid_to = record.get("valid_to")
        if valid_to is not None:
            valid_to = _time(valid_to, "valid_to")
        basis = EvidenceBasis(record["basis"])
        if basis is EvidenceBasis.INFERRED:
            raise ProjectStateError("inferred records require a licensed rule; this adapter does not register rules")
        claim = ClaimRevision(
            claim_id=cid, key=key, value=value, basis=basis,
            truth=TruthStatus(record["truth"]), authority=Authority(record["authority"]),
            valid_from=_time(record["effective_time"], "effective_time"), valid_to=valid_to,
            recorded_at=record["recorded_at"], evidence=(evidence,),
            supersedes_claim_ids=supersedes,
        )
        ledger.append_event(CanonicalEvent(
            event_id=f"event_{cid}", event_type="project_record",
            effective_time=claim.valid_from, recorded_at=claim.recorded_at,
            entities=(key.subject,), requirements=(),
            effects=(StateEffect(cid, key, EffectOp.SET, value),), claims=(claim,),
            causal_parents=(), hard_dependencies=(), evidence=(evidence,),
        ))
        records[cid] = {
            "id": cid, "subject": key.subject, "predicate": key.predicate, "value": value,
            "basis": claim.basis.value, "truth": claim.truth.value,
            "authority": claim.authority.value, "effective_time": claim.valid_from,
            "recorded_at": claim.recorded_at, "supersedes": list(supersedes),
            "evidence": {"source": sid, "path": source_path, "sha256": source_hash,
                         "line": line, "excerpt": excerpt},
        }
    return ProjectLedger(project, ledger, records)


def render_text(view: dict[str, Any]) -> str:
    lines = [f"Project: {json.dumps(view['project'], ensure_ascii=False)}",
             f"Documented state at {view['valid_at']}; known at {view['known_at']}",
             "", "Current:"]
    for row in view["current"]:
        value = json.dumps(row["value"], ensure_ascii=False)
        evidence = row["evidence"]
        lines.extend([f"- {row['subject']}.{row['predicate']}: {value}",
                      f"  Evidence: {evidence['path']}:{evidence['line']} [{row['id']}]"])
    if not view["current"]:
        lines.append("- No admitted current facts.")
    if view["conflicts"]:
        lines.extend(["", "Unresolved:"])
        for item in view["conflicts"]:
            lines.append(f"- {item['subject']}.{item['predicate']}: UNKNOWN ({', '.join(item['claim_ids'])})")
    if view["other_records"]:
        lines.extend(["", "Other records:"])
        for row in view["other_records"]:
            value = json.dumps(row["value"], ensure_ascii=False)
            lines.append(f"- {row['id']}: {row['status']} / {row['reason']} ({value})")
    lines.extend(["", "Assertions are operator-curated; matching evidence does not prove interpretation."])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--valid-at", type=int)
    parser.add_argument("--known-at", type=int)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        view = load_project(args.manifest).view(valid_at=args.valid_at, known_at=args.known_at)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"project-state: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(view, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(render_text(view), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
