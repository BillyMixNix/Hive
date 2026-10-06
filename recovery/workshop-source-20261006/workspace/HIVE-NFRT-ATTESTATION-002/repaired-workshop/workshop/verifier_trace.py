"""Durable verifier diagnostics. Events/output never grant acceptance."""
from __future__ import annotations
import datetime
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

EVENT_PREFIX = "HIVE_VERIFIER_EVENT "

# Read-only, bounded diagnostic sample. Thread.print briefly attaches to the
# JVM; this is recorded as diagnostic activity, never acceptance evidence.
JVM_SAMPLE = r'''
import json,pathlib,subprocess,time
rows=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  if not cmd.split(' ',1)[0].endswith('/bin/java'):continue
  row={'pid':int(p.name),'cmdline':cmd}
  for f in ['stat','status','io','wchan']:
   try:row[f]=(p/f).read_text()
   except OSError as e:row[f]=str(e)
  if 'org.gradle.launcher.daemon.bootstrap.GradleDaemon' in cmd:
   try:
    cp=subprocess.run(['/opt/java/openjdk/bin/jcmd',p.name,'Thread.print'],capture_output=True,text=True,timeout=4)
    row['thread_dump']={'returncode':cp.returncode,'stdout':cp.stdout[:160000],'stderr':cp.stderr[:2000]}
   except Exception as e:row['thread_dump_error']=str(e)
  rows.append(row)
 except OSError:pass
cgroup={}
for name in ['cpu.stat','memory.current','memory.events','memory.stat','io.stat','pids.current']:
 try:cgroup[name]=(pathlib.Path('/sys/fs/cgroup')/name).read_text()
 except OSError:pass
p=pathlib.Path('/work/candidate/build')
print(json.dumps({'wall_timestamp':time.time(),'processes':rows,'cgroup':cgroup,
 'main_class_count':len(list((p/'classes/java/main').rglob('*.class'))),
 'test_class_count':len(list((p/'classes/java/test').rglob('*.class'))),
 'generated_java_count':len(list((p/'generated').rglob('*.java')))}))
'''


class VerificationTrace:
    def __init__(self, tree: Path, mode: str, root: Path | None = None):
        self.started = time.monotonic()
        self.run_id = Path(tree).parent.name
        self.root = Path(root) if root is not None else Path(tree).parent / "verification" / f"{mode}-{uuid.uuid4().hex[:12]}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.last_phase = None
        self.last_verifier_phase = None
        self.event("verification_requested", mode=mode, source=str(tree))

    def event(self, phase, **fields):
        with self.lock:
            now = time.monotonic()
            row = {"monotonic": now, "wall_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "run_id": self.run_id, "phase": phase, "elapsed_ms": round((now-self.started)*1000, 3),
                   "clock_domain": "host", **fields}
            if phase not in {"process_output", "process_state", "diagnostic_error"}:
                self.last_phase = phase
                if fields.get("origin") == "container": self.last_verifier_phase = phase
            with (self.root / "verification-events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False)+"\n")

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")

    def state(self, docker, container, stop):
        rows = []
        # Read-only bounded samples, taken before the verification deadline.
        for args in (["inspect", "--format", "{{json .State}}", container],
                     ["top", container, "-eo", "pid,ppid,stat,etime,time,wchan:24,args"],
                     ["stats", "--no-stream", "--format", "{{json .}}", container]):
            if stop.is_set(): break
            try:
                cp = subprocess.run([docker, *args], capture_output=True, text=True, timeout=2)
                rows.append({"argv": [docker,*args], "returncode": cp.returncode,
                             "stdout": cp.stdout[-32000:], "stderr": cp.stderr[-4000:]})
            except Exception as exc:
                rows.append({"argv": [docker,*args], "error": f"{type(exc).__name__}: {exc}"})
        self.event("process_state", container=container, samples=rows)
        if not stop.is_set():
            try:
                cp=subprocess.run([docker,'exec',container,'python3','-c',JVM_SAMPLE],
                                  capture_output=True,text=True,timeout=7)
                filename=f'jvm-state-{int((time.monotonic()-self.started)*1000)}.json'
                self.save(filename, {'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr,
                                     'probe':'read-only procfs and bounded jcmd Thread.print'})
                self.event('jvm_state_sample', container=container, artifact=filename, returncode=cp.returncode)
            except Exception as exc:
                self.event('diagnostic_error',detail=f'JVM sample: {exc}')

    def capture(self, command, *, timeout, docker, container):
        stdout_path, stderr_path = self.root/"stdout.log", self.root/"stderr.log"
        self.save("invocation.json", {"argv":command, "cwd":str(Path.cwd()), "timeout_seconds":timeout,
                  "container":container, "host_environment":"Inherited by Docker CLI; not collected. Only explicit --env entries enter container."})
        stop = threading.Event()
        def observe():
            try:
                with stderr_path.open("r", encoding="utf-8", errors="replace") as stream:
                    pending = ""
                    while True:
                        chunk = stream.read(65536)
                        pending += chunk
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            if not line.startswith(EVENT_PREFIX): continue
                            try:
                                source = json.loads(line[len(EVENT_PREFIX):])
                                phase = source.pop("phase")
                                self.event(phase, container=container, origin="container", source_event=source)
                            except (ValueError, KeyError, TypeError):
                                self.event("diagnostic_error", detail="Malformed container diagnostic event")
                        if stop.is_set() and not chunk: break
                        if not chunk: stop.wait(.05)
            except Exception as exc:
                self.event("diagnostic_error", detail=str(exc))
        def sample():
            # No delayed samples may hold up deadline enforcement/termination.
            if timeout < 10: return
            for due in (min(120, timeout*.5), min(180,timeout*.75), max(0, timeout-15)):
                delay=max(0, launched+due-time.monotonic())
                if stop.wait(delay): return
                self.state(docker, container, stop)
        self.event("verifier_launch_requested", container=container, timeout_seconds=timeout)
        launched = time.monotonic()
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            reader=threading.Thread(target=observe, daemon=True)
            sampler=threading.Thread(target=sample, daemon=True)
            reader.start(); sampler.start()
            try:
                cp=subprocess.run(command, stdout=out, stderr=err, timeout=timeout)
                # Also supports injected deterministic process runners in tests.
                for value, handle in ((getattr(cp,'stdout',None),out),(getattr(cp,'stderr',None),err)):
                    if value: handle.write(value.encode() if isinstance(value,str) else value)
                self.event("verifier_process_exit", container=container, returncode=cp.returncode)
            except subprocess.TimeoutExpired as exc:
                for value, handle in ((exc.stdout,out),(exc.stderr,err)):
                    if value and handle.tell()==0: handle.write(value.encode() if isinstance(value,str) else value)
                out.flush(); err.flush()
                self.event("timeout_fired", container=container, timeout_seconds=timeout,
                           last_observed_phase=self.last_verifier_phase or self.last_phase)
                raise
            finally:
                out.flush(); err.flush(); stop.set(); reader.join(timeout=2); sampler.join(timeout=3)
        return subprocess.CompletedProcess(command, cp.returncode,
                    stdout_path.read_text(encoding="utf-8",errors="replace"),
                    stderr_path.read_text(encoding="utf-8",errors="replace"))

    def summary(self):
        return {"directory":str(self.root), "events":str(self.root/"verification-events.jsonl"),
                "stdout":str(self.root/"stdout.log"), "stderr":str(self.root/"stderr.log"),
                "last_observed_phase":self.last_verifier_phase or self.last_phase,
                "elapsed_ms":round((time.monotonic()-self.started)*1000,3)}
