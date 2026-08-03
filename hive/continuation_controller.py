"""Persistent continuation controller for Hive.

A successful child task is not a stopping condition. The controller persists a
parent objective and decides whether Hive continues, suspends, escalates, or is
actually complete. Watcher events are consumed from a durable JSONL queue.
"""
from __future__ import annotations
import argparse, json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

class Disposition(str, Enum):
    CONTINUE="continue"; SUSPEND="suspend"; PILOT="pilot"; COMPLETE="complete"

@dataclass
class ChildTask:
    id:str; objective:str; status:str="ready"
    evidence:list[str]=field(default_factory=list)
    blocker:dict[str,Any]|None=None

@dataclass
class ContinuationState:
    parent_goal:str; completion_cues:list[str]
    children:list[ChildTask]=field(default_factory=list)
    active_child:str|None=None; waiting_on:dict[str,Any]|None=None
    pilot_question:str|None=None; parent_complete:bool=False
    history:list[dict[str,Any]]=field(default_factory=list)
    @classmethod
    def load(cls,path:Path):
        raw=json.loads(path.read_text(encoding="utf-8")); raw["children"]=[ChildTask(**x) for x in raw.get("children",[])]
        return cls(**raw)
    def save(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(asdict(self),indent=2),encoding="utf-8")
    def child(self,child_id:str): return next(x for x in self.children if x.id==child_id)

def decide(state:ContinuationState)->tuple[Disposition,str]:
    if state.parent_complete:return Disposition.COMPLETE,"parent completion cues satisfied"
    if state.pilot_question:return Disposition.PILOT,state.pilot_question
    if state.waiting_on:return Disposition.SUSPEND,f"waiting on {state.waiting_on.get('kind','dependency')}"
    ready=[x for x in state.children if x.status in {"ready","failed"} and not x.blocker]
    if ready:return Disposition.CONTINUE,ready[0].id
    for child in [x for x in state.children if x.status=="blocked"]:
        b=child.blocker or {}
        if not b.get("requires_pilot",False):return Disposition.CONTINUE,f"resolve:{child.id}:{b.get('kind','blocker')}"
        return Disposition.PILOT,b.get("question",f"Pilot judgment required for {child.id}")
    return Disposition.CONTINUE,"derive_next_child"

def apply_event(state:ContinuationState,event:dict[str,Any])->None:
    kind=event["kind"]
    if kind=="child_completed":
        child=state.child(event["child_id"]);child.status="complete";child.evidence.extend(event.get("evidence",[]));state.active_child=None
    elif kind=="child_failed":
        child=state.child(event["child_id"]);child.status="failed";child.evidence.extend(event.get("evidence",[]));child.blocker=event.get("blocker");state.active_child=None
    elif kind=="dependency_started":state.waiting_on=event["dependency"]
    elif kind=="dependency_resolved":
        state.waiting_on=None
        # Preserve external evidence so cognition can inspect the result after wakeup.
        state.history.append({"kind":"dependency_evidence","result":event.get("result"),"evidence":event.get("evidence",{})})
    elif kind=="pilot_required":state.pilot_question=event["question"]
    elif kind=="pilot_answered":state.pilot_question=None
    elif kind=="parent_completed":state.parent_complete=True
    elif kind=="child_added":state.children.append(ChildTask(**event["child"]))
    else:raise ValueError(f"unknown continuation event: {kind}")
    state.history.append(event)

def consume_events(state:ContinuationState,queue:Path)->int:
    if not queue.exists():return 0
    lines=[x for x in queue.read_text(encoding="utf-8").splitlines() if x.strip()]
    for line in lines:apply_event(state,json.loads(line))
    queue.write_text("",encoding="utf-8")
    return len(lines)

def pilot_gate(state:ContinuationState)->tuple[bool,str]:
    disposition,reason=decide(state)
    # Hard invariant: ordinary continuation/suspension is never Pilot-facing.
    return disposition in {Disposition.PILOT,Disposition.COMPLETE},reason

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("state");ap.add_argument("--event");ap.add_argument("--consume");ap.add_argument("--pilot-gate",action="store_true")
    args=ap.parse_args();path=Path(args.state);state=ContinuationState.load(path)
    if args.consume:consume_events(state,Path(args.consume));state.save(path)
    if args.event:apply_event(state,json.loads(args.event));state.save(path)
    disposition,reason=decide(state)
    out={"disposition":disposition.value,"reason":reason}
    if args.pilot_gate:out["pilot_visible"]=pilot_gate(state)[0]
    print(json.dumps(out));return 0
if __name__=="__main__":raise SystemExit(main())
