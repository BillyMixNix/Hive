"""Persistent continuation controller for Hive.

A successful child task is not a stopping condition.  The controller persists a
parent objective and derives whether Hive should continue, suspend on an
external dependency, or escalate to the Pilot.

This module deliberately contains no model-specific code.  It is the durable
control-plane contract around cognition/workers.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Disposition(str, Enum):
    CONTINUE = "continue"
    SUSPEND = "suspend"
    PILOT = "pilot"
    COMPLETE = "complete"


@dataclass
class ChildTask:
    id: str
    objective: str
    status: str = "ready"  # ready|running|blocked|complete|failed
    evidence: list[str] = field(default_factory=list)
    blocker: dict[str, Any] | None = None


@dataclass
class ContinuationState:
    parent_goal: str
    completion_cues: list[str]
    children: list[ChildTask] = field(default_factory=list)
    active_child: str | None = None
    waiting_on: dict[str, Any] | None = None
    pilot_question: str | None = None
    parent_complete: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "ContinuationState":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["children"] = [ChildTask(**x) for x in raw.get("children", [])]
        return cls(**raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def child(self, child_id: str) -> ChildTask:
        return next(x for x in self.children if x.id == child_id)


def decide(state: ContinuationState) -> tuple[Disposition, str]:
    if state.parent_complete:
        return Disposition.COMPLETE, "parent completion cues satisfied"
    if state.pilot_question:
        return Disposition.PILOT, state.pilot_question
    if state.waiting_on:
        return Disposition.SUSPEND, f"waiting on {state.waiting_on.get('kind', 'dependency')}"

    ready = [x for x in state.children if x.status in {"ready", "failed"} and not x.blocker]
    if ready:
        return Disposition.CONTINUE, ready[0].id

    blocked = [x for x in state.children if x.status == "blocked"]
    for child in blocked:
        b = child.blocker or {}
        if not b.get("requires_pilot", False):
            return Disposition.CONTINUE, f"resolve:{child.id}:{b.get('kind', 'blocker')}"
        return Disposition.PILOT, b.get("question", f"Pilot judgment required for {child.id}")

    # This is intentionally not COMPLETE.  An unresolved parent with no next
    # child is a planning gap and must return to cognition.
    return Disposition.CONTINUE, "derive_next_child"


def apply_event(state: ContinuationState, event: dict[str, Any]) -> None:
    kind = event["kind"]
    if kind == "child_completed":
        child = state.child(event["child_id"])
        child.status = "complete"
        child.evidence.extend(event.get("evidence", []))
        state.active_child = None
    elif kind == "child_failed":
        child = state.child(event["child_id"])
        child.status = "failed"
        child.evidence.extend(event.get("evidence", []))
        child.blocker = event.get("blocker")
        state.active_child = None
    elif kind == "dependency_started":
        state.waiting_on = event["dependency"]
    elif kind == "dependency_resolved":
        state.waiting_on = None
    elif kind == "pilot_required":
        state.pilot_question = event["question"]
    elif kind == "pilot_answered":
        state.pilot_question = None
    elif kind == "parent_completed":
        state.parent_complete = True
    elif kind == "child_added":
        state.children.append(ChildTask(**event["child"]))
    else:
        raise ValueError(f"unknown continuation event: {kind}")
    state.history.append(event)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("--event", help="JSON event to apply before deciding")
    args = ap.parse_args()
    path = Path(args.state)
    state = ContinuationState.load(path)
    if args.event:
        apply_event(state, json.loads(args.event))
        state.save(path)
    disposition, reason = decide(state)
    print(json.dumps({"disposition": disposition.value, "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
