"""v0.5 runtime support for bounded, observable background work."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import json, re, threading, time, uuid
from pathlib import Path
from typing import Any, Callable

class State(str, Enum):
    QUEUED="queued"; PLANNING="planning"; UI="ui"; BACKEND="backend"; TESTS="tests"
    EDITING="editing"; TESTING="testing"; REPAIRING="repairing"
    VERIFICATION="verification"; REVIEW="review"; REVIEWING="reviewing"
    WAITING_APPROVAL="waiting_approval"; COMPLETED="completed"
    FAILED="failed"; CANCELLED="cancelled"

@dataclass
class Job:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: State = State.QUEUED
    progress: int = 0
    message: str = "Queued"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    def update(self, state: State, progress: int, message: str):
        terminal = (State.COMPLETED, State.FAILED, State.CANCELLED)
        with self.lock:
            # A late callback from a provider or verifier must never overwrite
            # a terminal cancellation/failure/completion already exposed to
            # the caller.
            if self.state in terminal:
                return False
            self.state, self.progress, self.message = state, max(0,min(100,progress)), message
            self.updated_at = time.time()
            self.events.append({"state":state.value,"progress":self.progress,"message":message,"at":self.updated_at})
            return True
    def finish(self, state: State, result: Any, message: str, error: str | None = None):
        if state not in (State.COMPLETED, State.FAILED, State.CANCELLED):
            raise ValueError("finish requires a terminal state")
        with self.lock:
            if self.state in (State.COMPLETED, State.FAILED, State.CANCELLED):
                return False
            self.result = result
            self.error = error
            return self.update(state, 100, message)
    def as_dict(self):
        with self.lock:
            return {"id":self.id,"state":self.state.value,"progress":self.progress,"message":self.message,"result":self.result,"error":self.error,"events":list(self.events)}

class JobManager:
    def __init__(self, max_jobs: int = 100): self.jobs: dict[str,Job] = {}; self.lock=threading.RLock(); self.max_jobs=max_jobs
    def start(self, worker: Callable[[Job],Any]) -> Job:
        job=Job(); self.jobs[job.id]=job; self._trim()
        def run():
            try:
                result=worker(job)
                with job.lock:
                    if job.state not in (State.COMPLETED,State.CANCELLED,State.FAILED):
                        job.result=result
                        job.update(State.COMPLETED,100,"Completed")
                    elif job.result is None:
                        job.result=result
            except Exception as exc:
                if job.cancel_event.is_set():
                    job.finish(State.CANCELLED,job.result,"Cancelled")
                else:
                    job.finish(State.FAILED,None,"Failed",str(exc))
            finally: job.done.set()
        threading.Thread(target=run,name="nix-workshop-job",daemon=True).start(); return job
    def get(self, job_id): return self.jobs.get(job_id)
    def _trim(self):
        terminal=(State.COMPLETED,State.FAILED,State.CANCELLED)
        old=sorted((j for j in self.jobs.values() if j.state in terminal),key=lambda j:j.updated_at)
        for job in old[:max(0,len(self.jobs)-self.max_jobs)]: self.jobs.pop(job.id,None)
    def cancel(self, job_id):
        job=self.get(job_id)
        if not job or job.state in (State.COMPLETED,State.FAILED,State.CANCELLED): return False
        job.cancel_event.set(); job.update(State.CANCELLED,job.progress,"Cancellation requested"); return True
    def health(self):
        active=sum(j.state not in (State.COMPLETED,State.FAILED,State.CANCELLED) for j in self.jobs.values())
        terminal=[j for j in self.jobs.values() if j.state in (State.COMPLETED,State.FAILED,State.CANCELLED)]
        return {"ok":True,"active_jobs":active,"jobs":len(self.jobs),"failed_jobs":sum(j.state is State.FAILED for j in terminal),"last_completed_at":max((j.updated_at for j in terminal),default=None)}

def parse_json(text: str, required=(), repair: Callable[[str],str|None]|None=None):
    candidates=[text.strip()]; match=re.search(r"\{.*\}",text,re.S)
    if match: candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value=json.loads(candidate)
            if isinstance(value,dict) and all(k in value for k in required): return value
        except json.JSONDecodeError: pass
    if repair:
        fixed=repair(text)
        if fixed: return parse_json(fixed,required=required)
    raise ValueError("Malformed agent JSON; no safe repair available")

def retrieve(root: Path, query: str, limit=8, max_chars=12000):
    terms=set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}",query.lower())); hits=[]
    excluded={".git","__pycache__",".venv","data","media","reports","snapshots","hive_runs","self_snapshots",".pytest_cache"}
    try: resolved_root=Path(root).resolve(strict=True)
    except (OSError,RuntimeError): return []
    for path in resolved_root.rglob("*"):
        try:
            relative=path.relative_to(resolved_root)
        except ValueError:
            continue
        # Exclusions describe content beneath the logical search root.  An
        # ancestor outside that root (including a staging directory named
        # hive_runs) is not repository content and must not suppress results.
        if any(part.startswith(".") or part.casefold() in excluded for part in relative.parts): continue
        if path.is_symlink(): continue
        try:
            resolved=path.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError,RuntimeError,ValueError):
            continue
        if not resolved.is_file(): continue
        try: content=path.read_text(encoding="utf-8")
        except (OSError,UnicodeError): continue
        score=sum(content.lower().count(t) for t in terms)
        if score: hits.append((score,relative,content[:max_chars]))
    hits.sort(key=lambda x:(-x[0],str(x[1])))
    return [{"path":str(p),"score":s,"content":c} for s,p,c in hits[:limit]]
