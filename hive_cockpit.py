import json
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
PROJECT_DIR = None  # set by --project arg in main()

CONVERSE_MANAGER = None
CONVERSE_LOCK = threading.Lock()


def get_converse_manager():
    global CONVERSE_MANAGER
    if CONVERSE_MANAGER is None:
        with CONVERSE_LOCK:
            if CONVERSE_MANAGER is None:
                from conversation_manager import ConversationManager
                CONVERSE_MANAGER = ConversationManager(
                    project_dir=str(PROJECT_DIR or ROOT)
                )
    return CONVERSE_MANAGER


def _read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _shorten(value, limit=120):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _entry_kind(entry):
    tag = str(entry.get("tag") or "").lower()
    status = str(entry.get("status") or "").lower()
    metadata = entry.get("metadata") or {}

    if tag == "builder" or "builder_result" in metadata:
        return "task"
    if tag == "plan" or "plan" in metadata:
        return "plan"
    if tag == "patch" or "patch" in metadata:
        return "patch"
    if "review" in tag or status == "pending_pilot_review":
        return "review"
    if "lesson" in tag:
        return "lesson"
    if "failure" in tag:
        return "failure"
    return "memory"


def _metadata_anchor(entry):
    metadata = entry.get("metadata") or {}
    anchor = metadata.get("anchor") or {}
    plan = metadata.get("plan") or {}
    if not anchor and isinstance(plan, dict):
        anchor = plan.get("metadata", {}).get("anchor") or {}

    target_file = (
        metadata.get("target_file")
        or anchor.get("target_file")
        or (plan.get("target_file") if isinstance(plan, dict) else None)
    )
    target_symbol = metadata.get("target_symbol") or anchor.get("target_symbol")
    source = anchor.get("anchor_source") or ("metadata" if target_file or target_symbol else "none")
    confidence = "none"
    if target_file or target_symbol:
        confidence = "explicit" if source in {"explicit", "planner_normalized"} else "inferred"

    return {
        "target_file": target_file,
        "target_symbol": target_symbol,
        "source": source,
        "confidence": confidence,
    }


def _metadata_work(entry):
    metadata = entry.get("metadata") or {}
    plan = metadata.get("plan") if isinstance(metadata, dict) else None
    if not isinstance(plan, dict):
        plan = {}
    builder_result = metadata.get("builder_result") if isinstance(metadata, dict) else None
    if not isinstance(builder_result, dict):
        builder_result = {}

    def pick(*values):
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return None

    work_mode = pick(
        metadata.get("work_mode"),
        metadata.get("task_kind"),
        plan.get("work_mode"),
        plan.get("task_kind"),
        builder_result.get("work_mode"),
        builder_result.get("task_kind"),
    )
    domain = pick(metadata.get("domain"), plan.get("domain"), builder_result.get("domain"))
    artifact = pick(metadata.get("artifact"), plan.get("artifact"), builder_result.get("artifact"))
    operation = pick(metadata.get("operation"), plan.get("operation"), builder_result.get("operation"))
    validation = pick(metadata.get("validation"), plan.get("validation"), builder_result.get("validation"))
    task_type = pick(metadata.get("task_type"), plan.get("task_type"), builder_result.get("task_type"))

    try:
        from work_ontology import build_work_profile
        profile = build_work_profile(
            task={"note": entry.get("note"), "metadata": metadata},
            plan=plan,
        )
    except Exception:
        profile = {}

    return {
        "work_mode": work_mode or profile.get("work_mode"),
        "domain": domain or profile.get("domain"),
        "artifact": artifact or profile.get("artifact"),
        "operation": operation or profile.get("operation"),
        "validation": validation or profile.get("validation"),
        "task_type": task_type,
    }


def _child_work(parent_entry, plan, child):
    metadata = parent_entry.get("metadata") or {}
    try:
        from work_ontology import build_work_profile
        profile = build_work_profile(
            task={"note": parent_entry.get("note"), "metadata": metadata},
            plan=plan,
            child=child,
        )
    except Exception:
        profile = {}

    return {
        "work_mode": child.get("work_mode") or child.get("task_kind") or profile.get("work_mode"),
        "domain": child.get("domain") or plan.get("domain") or profile.get("domain"),
        "artifact": child.get("artifact") or plan.get("artifact") or profile.get("artifact"),
        "operation": child.get("operation") or plan.get("operation") or profile.get("operation"),
        "validation": child.get("validation") or plan.get("validation") or profile.get("validation"),
        "task_type": child.get("task_type") or plan.get("task_type"),
        "creates_symbols": child.get("creates_symbols") or [],
        "wires_into_symbols": child.get("wires_into_symbols") or [],
        "insertion_region": child.get("insertion_region") or "",
    }


class HiveProcess:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.output = []
        self.output_queue = queue.Queue()
        self.reader = None

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self._append("[Starting Hive]\n")
            self.proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "main.py")],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.reader = threading.Thread(target=self._read_output, daemon=True)
            self.reader.start()

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self._append("[Hive stopped]\n")

    def send(self, command):
        command = str(command or "").strip()
        if not command:
            return False, "Command is empty."
        self.start()
        with self.lock:
            if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
                return False, "Hive is offline."
            self._append(f"\nPilot > {command}\n")
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
        return True, "sent"

    def status(self):
        if self.proc and self.proc.poll() is None:
            return "online"
        return "offline"

    def transcript_since(self, cursor):
        with self.lock:
            cursor = max(0, int(cursor or 0))
            text = "".join(self.output[cursor:])
            return {"cursor": len(self.output), "text": text, "status": self.status()}

    def _read_output(self):
        if not self.proc or not self.proc.stdout:
            return
        while True:
            chunk = self.proc.stdout.read(1)
            if not chunk:
                break
            self._append(chunk)
        self._append("\n[Hive process ended]\n")

    def _append(self, text):
        self.output.append(text)
        if len(self.output) > 40000:
            del self.output[:5000]


HIVE = HiveProcess()


def build_state_payload():
    memory = _read_json(ROOT / "hive_memory.json", [])
    snapshot = _read_json(ROOT / "hive_state_snapshot.json", {})
    try:
        from repo_map import RepoMap
        repo_map = RepoMap(root=ROOT).build()
    except Exception:
        repo_map = ((snapshot.get("repo_state") or {}).get("repo_map") or snapshot.get("repo_map") or {})
    known_files = set(repo_map.get("known_files") or [])

    entries = [entry for entry in memory if isinstance(entry, dict)]
    visible = entries[-250:]
    id_set = {entry.get("id") for entry in visible}
    nodes = []
    edges = []
    child_nodes = []

    for entry in visible:
        entry_id = entry.get("id")
        metadata = entry.get("metadata") or {}
        kind = _entry_kind(entry)
        anchor = _metadata_anchor(entry)
        anchor["valid_file"] = not anchor.get("target_file") or anchor.get("target_file") in known_files
        work = _metadata_work(entry)

        nodes.append({
            "id": entry_id,
            "kind": kind,
            "tag": entry.get("tag"),
            "status": entry.get("status"),
            "note": entry.get("note"),
            "label": f"{entry_id}: {_shorten(entry.get('note') or entry.get('tag'), 54)}",
            "timestamp": entry.get("timestamp"),
            "anchor": anchor,
            "work": work,
            "metadata": metadata,
        })

        parent_id = metadata.get("task_id")
        if parent_id in id_set and parent_id != entry_id:
            edges.append({"from": parent_id, "to": entry_id, "label": kind})

        plan = metadata.get("plan") if isinstance(metadata, dict) else None
        if isinstance(plan, dict):
            for index, child in enumerate(plan.get("tasks") or [], start=1):
                child_id = f"{entry_id}-child-{index}"
                work = _child_work(entry, plan, child)
                child_anchor = {
                    "target_file": child.get("target_file"),
                    "target_symbol": child.get("target_symbol"),
                    "source": (child.get("metadata") or {}).get("anchor", {}).get("anchor_source") or "plan",
                    "confidence": "inferred" if child.get("target_file") or child.get("target_symbol") else "none",
                    "valid_file": not child.get("target_file") or child.get("target_file") in known_files,
                }
                child_nodes.append({
                    "id": child_id,
                    "kind": "child",
                    "tag": "child_task",
                    "status": child.get("status"),
                    "note": child.get("description") or child.get("title"),
                    "label": f"{child.get('task_id') or child_id}: {_shorten(child.get('title') or child.get('description'), 48)}",
                    "timestamp": entry.get("timestamp"),
                    "anchor": child_anchor,
                    "work": work,
                    "metadata": child,
                })
                edges.append({"from": entry_id, "to": child_id, "label": "child"})

    nodes.extend(child_nodes)

    current = ((snapshot.get("observability") or {}).get("current") or {})
    system = ((snapshot.get("observability") or {}).get("system") or {})
    current_task_id = current.get("task_id") or current.get("id")
    latest_task_id = None
    task_ids = [entry.get("id") for entry in entries if _entry_kind(entry) == "task" and isinstance(entry.get("id"), int)]
    if task_ids:
        latest_task_id = max(task_ids)
    try:
        from orchestration import OrchestrationLedger
        orchestration = OrchestrationLedger(
            ROOT / ".hive" / "orchestration_events.jsonl"
        ).snapshot()
    except Exception as exc:
        orchestration = {
            "projects": [],
            "workers": [],
            "tasks": [],
            "summary": {
                "project_count": 0,
                "active_projects": 0,
                "blocked_projects": 0,
                "stalled_projects": 0,
                "active_workers": 0,
                "ready_tasks": 0,
                "assigned_tasks": 0,
                "event_count": 0,
            },
            "error": str(exc),
        }
    try:
        from steward import build_steward_brief
        steward = build_steward_brief(orchestration)
    except Exception as exc:
        steward = {
            "realm": "steward",
            "attention": [],
            "primary_attention": None,
            "highest_leverage": None,
            "briefing": "Steward briefing unavailable.",
            "error": str(exc),
        }

    return {
        "nodes": nodes,
        "edges": edges,
        "current": current,
        "current_task_id": current_task_id,
        "latest_task_id": latest_task_id,
        "system": system,
        "known_files_count": len(known_files),
        "generated_at": time.time(),
        "hive_status": HIVE.status(),
        "orchestration": orchestration,
        "steward": steward,
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Hive Cockpit</title>
  <style>
    :root {
      --bg: #090d12;
      --panel: #101720;
      --panel-2: #0c131b;
      --line: #223140;
      --text: #e6edf3;
      --muted: #96a5b4;
      --blue: #4da3ff;
      --green: #37c985;
      --amber: #f3b653;
      --red: #f06b6b;
      --purple: #b08cff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Segoe UI, system-ui, sans-serif;
      display: grid;
      grid-template-rows: auto 1fr;
      overflow: hidden;
    }
    button, input, textarea, select {
      font: inherit;
    }
    button {
      border: 1px solid #2c4054;
      background: #172334;
      color: var(--text);
      border-radius: 6px;
      padding: 7px 10px;
      cursor: pointer;
    }
    button:hover { background: #20314a; }
    button.primary { background: #1c5f9f; border-color: #2f83d0; }
    button.danger { background: #733033; border-color: #9b3c40; }
    input, textarea, select {
      width: 100%;
      color: var(--text);
      background: #08111a;
      border: 1px solid #26394c;
      border-radius: 6px;
      padding: 8px;
    }
    textarea { resize: vertical; min-height: 86px; }
    #topbar {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 14px;
      align-items: center;
      padding: 10px 12px;
      background: #111821;
      border-bottom: 1px solid var(--line);
    }
    .brand { font-size: 18px; font-weight: 700; letter-spacing: 0; }
    .stats { display: flex; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 13px; }
    .pill {
      border: 1px solid #2a3b4f;
      border-radius: 999px;
      padding: 3px 9px;
      background: #0b121a;
    }
    #shell {
      min-height: 0;
      display: grid;
      grid-template-columns: 330px minmax(420px, 1fr) 390px;
      gap: 0;
    }
    aside, main { min-height: 0; }
    #left, #right {
      background: var(--panel);
      border-right: 1px solid var(--line);
      overflow: auto;
      padding: 12px;
    }
    #right {
      border-right: 0;
      border-left: 1px solid var(--line);
    }
    .section { margin-bottom: 16px; }
    .section h2 {
      margin: 0 0 8px;
      font-size: 13px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0.04em;
    }
    .row { display: flex; gap: 8px; align-items: center; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .filters button.active {
      background: #245d8d;
      border-color: #4da3ff;
    }
    .current-card {
      border: 1px solid #294158;
      background: #0b1420;
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 12px;
    }
    .current-card .title {
      font-weight: 700;
      margin-bottom: 5px;
    }
    .current-card .meta {
      color: var(--muted);
      font-size: 12px;
    }
    #portfolio { display: flex; flex-direction: column; gap: 7px; }
    #command-queue { display: flex; flex-direction: column; gap: 6px; }
    .project-card {
      border: 1px solid #294158;
      background: #0b1420;
      border-radius: 8px;
      padding: 9px;
    }
    .project-card.blocked { border-color: var(--amber); }
    .project-card.stalled { border-color: var(--red); }
    .project-card .project-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
    }
    .project-card .project-meta {
      color: var(--muted);
      font-size: 11px;
      margin-top: 5px;
    }
    .progress-track {
      height: 4px;
      background: #172334;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 7px;
    }
    .progress-track span {
      display: block;
      height: 100%;
      background: var(--blue);
    }
    .command-item {
      border-left: 3px solid #53677d;
      background: #0b121a;
      padding: 7px 8px;
      font-size: 12px;
    }
    .command-item.assigned { border-left-color: var(--green); }
    .command-item.blocked { border-left-color: var(--amber); }
    .command-item .meta { color: var(--muted); font-size: 11px; margin-top: 3px; }
    #graph-wrap {
      position: relative;
      min-height: 0;
      overflow: auto;
      background-color: #05080d;
      background-image:
        linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
      background-size: 42px 42px;
    }
    #graph {
      width: 1600px;
      height: 1400px;
      display: block;
    }
    .node {
      cursor: pointer;
      filter: drop-shadow(0 8px 14px rgba(0,0,0,0.35));
    }
    .node rect { stroke-width: 1.4; rx: 7; }
    .node text { fill: var(--text); font-size: 12px; pointer-events: none; }
    .node .meta { fill: var(--muted); font-size: 10px; }
    .edge { stroke: #31465d; stroke-width: 1.2; fill: none; }
    .edge-label { fill: #738497; font-size: 10px; }
    .task rect { fill: #122338; stroke: var(--blue); }
    .plan rect { fill: #1d1930; stroke: var(--purple); }
    .child rect { fill: #252015; stroke: var(--amber); }
    .patch rect { fill: #13291e; stroke: var(--green); }
    .review rect { fill: #2b1e15; stroke: var(--amber); }
    .failure rect { fill: #2c1519; stroke: var(--red); }
    .lesson rect, .memory rect { fill: #111923; stroke: #53677d; }
    .selected rect { stroke-width: 3; }
    .invalid rect { stroke: var(--red); stroke-dasharray: 5 4; }
    #node-list { display: flex; flex-direction: column; gap: 6px; }
    .list-item {
      padding: 8px;
      border: 1px solid #223140;
      border-radius: 7px;
      background: var(--panel-2);
      cursor: pointer;
    }
    .list-item:hover { border-color: #3d5b78; }
    .list-item .title { font-size: 13px; }
    .list-item .meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .chip {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 7px;
      border: 1px solid #2d4055;
      color: var(--muted);
      font-size: 12px;
      margin: 2px 3px 2px 0;
    }
    .chip.bad { border-color: #884247; color: #ff9da5; }
    .chip.good { border-color: #2b7b5a; color: #7ee0b3; }
    .chip.mode { border-color: #5b4f89; color: #c7b8ff; }
    .work-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
      margin-top: 6px;
    }
    .work-row {
      border: 1px solid #223140;
      border-radius: 7px;
      background: #0b121a;
      padding: 7px 8px;
    }
    .work-row b {
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 2px;
    }
    #detail pre, #transcript {
      white-space: pre-wrap;
      word-break: break-word;
      background: #070d13;
      border: 1px solid #223140;
      border-radius: 7px;
      padding: 10px;
      max-height: 300px;
      overflow: auto;
      color: #d9e3ec;
      font-family: Consolas, monospace;
      font-size: 12px;
    }
    #transcript { height: 260px; }
    .field-label { color: var(--muted); font-size: 12px; margin: 8px 0 4px; }
    .tab-bar {
      display: flex;
      gap: 4px;
      margin-bottom: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }
    .tab {
      flex: 1;
      background: transparent;
      border: 1px solid transparent;
      color: var(--muted);
      font-size: 13px;
    }
    .tab.active {
      background: #172334;
      border-color: #2c4054;
      color: var(--text);
    }
    #entity-list { display: flex; flex-direction: column; gap: 4px; }
    #entity-content {
      white-space: pre-wrap;
      word-break: break-word;
      background: #070d13;
      border: 1px solid #223140;
      border-radius: 7px;
      padding: 10px;
      max-height: 340px;
      overflow: auto;
      color: #d9e3ec;
      font-family: Consolas, monospace;
      font-size: 12px;
    }
    #chat-messages {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 480px;
      overflow: auto;
      margin-bottom: 10px;
    }
    .chat-msg { border-radius: 7px; padding: 8px 10px; font-size: 13px; line-height: 1.5; }
    .chat-msg.pilot { background: #0f1e2d; border: 1px solid #2c4054; }
    .chat-msg.hive { background: #0b1a10; border: 1px solid #2a5040; }
    .chat-msg .speaker { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
    .chat-msg.thinking { opacity: 0.5; font-style: italic; }
    @media (max-width: 1100px) {
      #shell { grid-template-columns: 300px 1fr; }
      #right { display: none; }
    }
  </style>
</head>
<body>
  <header id="topbar">
    <div class="brand">Hive Cockpit</div>
    <div class="stats" id="stats"></div>
    <div class="row">
      <button id="refresh">Refresh</button>
      <button id="restart">Restart Hive</button>
    </div>
  </header>

  <div id="shell">
    <aside id="left">
      <section class="section">
        <h2>New Task</h2>
        <textarea id="new-task" placeholder="Describe what Hive should do..."></textarea>
        <div class="grid2" style="margin-top:8px">
          <button class="primary" id="create-task">Create</button>
          <button id="create-plan">Create + Plan</button>
        </div>
      </section>

      <section class="section">
        <h2>Current Work</h2>
        <div id="current-card" class="current-card">Loading...</div>
        <div class="grid2">
          <button id="focus-current">Focus Current</button>
          <button id="focus-latest">Focus Latest</button>
        </div>
      </section>

      <section class="section">
        <h2>Steward's Brief</h2>
        <div id="steward-brief"><div class="meta">Reading the kingdom...</div></div>
      </section>

      <section class="section">
        <h2>Worker Fleet</h2>
        <div id="worker-fleet"><div class="meta">Marshal not reporting.</div></div>
      </section>

      <section class="section">
        <h2>Project Portfolio</h2>
        <div id="portfolio"><div class="meta">Waiting for project observations...</div></div>
      </section>

      <section class="section">
        <h2>Command Queue</h2>
        <div id="command-queue"><div class="meta">No commands reported.</div></div>
      </section>

      <section class="section">
        <h2>Selected Actions</h2>
        <div class="grid2">
          <button data-action="show task">Show</button>
          <button data-action="plan task">Plan</button>
          <button data-action="code task">Code</button>
          <button data-action="review patch">Review Patch</button>
          <button data-action="apply patch">Apply Patch</button>
          <button data-action="rollback patch" class="danger">Rollback</button>
        </div>
      </section>

      <section class="section">
        <h2>Search</h2>
        <input id="search" type="search" placeholder="Search tasks, files, status..." />
      </section>

      <section class="section">
        <h2>View</h2>
        <div class="filters" id="filters">
          <button data-filter="active" class="active">Active</button>
          <button data-filter="current">Current</button>
          <button data-filter="blocked">Blocked</button>
          <button data-filter="patches">Patches</button>
          <button data-filter="invalid">Invalid Anchors</button>
          <button data-filter="all">All</button>
        </div>
      </section>

      <section class="section">
        <h2>Recent Nodes</h2>
        <div id="node-list"></div>
      </section>
    </aside>

    <main id="graph-wrap">
      <svg id="graph" aria-label="Hive task graph"></svg>
    </main>

    <aside id="right">
      <div class="tab-bar">
        <button class="tab active" data-tab="selected">Selected</button>
        <button class="tab" data-tab="project">Project</button>
        <button class="tab" data-tab="chat">Chat</button>
      </div>

      <div id="tab-selected">
        <section class="section" id="detail">
          <h2>Selected</h2>
          <div id="detail-body">Select a node to inspect its plan, patch, anchor, or task metadata.</div>
        </section>

        <section class="section">
          <h2>Command</h2>
          <div class="row">
            <input id="command" placeholder="Raw Hive command" />
            <button id="send-command">Send</button>
          </div>
        </section>

        <section class="section">
          <h2>Transcript</h2>
          <pre id="transcript"></pre>
        </section>
      </div>

      <div id="tab-project" style="display:none">
        <section class="section">
          <h2>Project Entities</h2>
          <div id="entity-list"><div class="meta">Loading...</div></div>
        </section>
        <section class="section">
          <h2>File</h2>
          <pre id="entity-content">Select an entity to view its file.</pre>
        </section>
      </div>

      <div id="tab-chat" style="display:none">
        <section class="section">
          <h2>Hive Chat</h2>
          <div id="chat-messages"></div>
          <div class="row">
            <input id="chat-input" placeholder="Talk to Hive..." />
            <button id="chat-send" class="primary">Send</button>
          </div>
        </section>
      </div>
    </aside>
  </div>

  <script>
    let state = { nodes: [], edges: [] };
    let selected = null;
    let transcriptCursor = 0;
    let activeFilter = 'active';
    let didInitialFocus = false;

    const graph = document.getElementById('graph');
    const graphWrap = document.getElementById('graph-wrap');
    const list = document.getElementById('node-list');
    const stats = document.getElementById('stats');
    const search = document.getElementById('search');
    const detail = document.getElementById('detail-body');
    const transcript = document.getElementById('transcript');
    const currentCard = document.getElementById('current-card');
    const stewardBrief = document.getElementById('steward-brief');
    const workerFleet = document.getElementById('worker-fleet');
    const portfolio = document.getElementById('portfolio');
    const commandQueue = document.getElementById('command-queue');

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      })[ch]);
    }

    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function refresh() {
      state = await api('/api/state');
      renderStats();
      renderCurrentCard();
      renderStewardBrief();
      renderWorkerFleet();
      renderPortfolio();
      renderCommandQueue();
      renderList();
      renderGraph();
      if (selected) {
        const next = state.nodes.find(n => String(n.id) === String(selected.id));
        if (next) selectNode(next.id);
      } else if (!didInitialFocus) {
        didInitialFocus = true;
        focusPreferredNode();
      }
    }

    function renderStats() {
      const counts = {};
      for (const node of state.nodes) counts[node.kind] = (counts[node.kind] || 0) + 1;
      const summary = state.orchestration?.summary || {};
      stats.innerHTML = [
        ['Hive', state.hive_status],
        ['Projects', summary.active_projects || 0],
        ['Workers', summary.active_workers || 0],
        ['Ready', summary.ready_tasks || 0],
        ['Assigned', summary.assigned_tasks || 0],
        ['Blocked', summary.blocked_projects || 0],
        ['Stalled', summary.stalled_projects || 0],
        ['Known files', state.known_files_count],
        ['Tasks', counts.task || 0],
        ['Issues', state.nodes.filter(n => n.anchor && n.anchor.valid_file === false).length],
      ].map(([k, v]) => `<span class="pill">${escapeHtml(k)}: ${escapeHtml(v)}</span>`).join('');
    }

    function formatDuration(seconds) {
      if (seconds == null) return '?';
      if (seconds < 60) return `${Math.ceil(seconds)}s`;
      const minutes = Math.ceil(seconds / 60);
      if (minutes < 60) return `${minutes}m`;
      const hours = Math.ceil(minutes / 60);
      if (hours < 48) return `${hours}h`;
      return `${Math.ceil(hours / 24)}d`;
    }

    function renderPortfolio() {
      const projects = state.orchestration?.projects || [];
      if (!projects.length) {
        portfolio.innerHTML = '<div class="meta">No projects have reported to Hive yet.</div>';
        return;
      }
      portfolio.innerHTML = projects.map(project => {
        const progress = project.progress || {};
        const fraction = progress.fraction;
        const eta = project.eta || {};
        const etaText = eta.low_seconds == null
          ? 'ETA awaiting evidence'
          : `ETA ${formatDuration(eta.low_seconds)}–${formatDuration(eta.high_seconds)}`;
        const flags = [
          project.blocked ? 'blocked' : '',
          project.stalled ? 'stalled' : '',
        ].filter(Boolean);
        const className = flags[0] || '';
        const status = flags.length ? flags.join(' / ') : (project.status || 'unknown');
        const progressText = progress.total
          ? `${progress.completed}/${progress.total} tasks`
          : 'progress unreported';
        return `
          <article class="project-card ${escapeHtml(className)}">
            <div class="project-head">
              <span>${escapeHtml(project.name || project.project_id)}</span>
              <span>${escapeHtml(status)}</span>
            </div>
            <div class="project-meta">
              ${escapeHtml(progressText)} · ${escapeHtml(etaText)} · ${escapeHtml(project.confidence || 'low')} confidence
            </div>
            ${fraction == null ? '' : `
              <div class="progress-track"><span style="width:${Math.round(fraction * 100)}%"></span></div>
            `}
          </article>
        `;
      }).join('');
    }

    function renderStewardBrief() {
      const brief = state.steward || {};
      const attention = brief.attention || [];
      if (!attention.length) {
        stewardBrief.innerHTML = `<div class="meta">${escapeHtml(
          brief.briefing || 'No intervention required.'
        )}</div>`;
        return;
      }
      const primary = brief.primary_attention || attention[0];
      const leverage = brief.highest_leverage;
      stewardBrief.innerHTML = `
        <article class="project-card ${primary.kind === 'blocker' ? 'blocked' : ''}">
          <div class="project-head">
            <span>${escapeHtml(primary.title)}</span>
            <span>${escapeHtml(primary.kind)}</span>
          </div>
          <div class="project-meta">${escapeHtml(primary.message)}</div>
          <div class="meta" style="margin-top:5px">${escapeHtml(primary.recommended_action)}</div>
          <div class="grid2 steward-actions" style="margin-top:8px">
            <button data-steward-action="approve">Approve</button>
            <button data-steward-action="defer">Defer 1 day</button>
            <button data-steward-action="reprioritize">Set priority</button>
            <button data-steward-action="context">Supply context</button>
            <button data-steward-action="reject" class="danger">Reject</button>
          </div>
        </article>
        ${leverage && leverage.task_id !== primary.task_id ? `
          <div class="command-item">
            <div>Highest leverage: ${escapeHtml(leverage.title)}</div>
            <div class="meta">${escapeHtml(leverage.message)}</div>
          </div>
        ` : ''}
        <div class="meta" style="margin-top:7px">
          ${escapeHtml(brief.summary?.blocker_count || 0)} blockers ·
          ${escapeHtml(brief.summary?.review_count || 0)} reviews ·
          ${escapeHtml(brief.summary?.leverage_count || 0)} leverage moves
        </div>
      `;
      stewardBrief.querySelectorAll('[data-steward-action]').forEach(button => {
        button.addEventListener('click', () => takeStewardAction(
          button.dataset.stewardAction,
          primary
        ));
      });
    }

    function renderWorkerFleet() {
      const marshal = (state.orchestration?.workers || [])
        .find(worker => worker.worker_id === 'marshal');
      const fleet = marshal?.fleet;
      if (!fleet) {
        workerFleet.innerHTML = '<div class="meta">Marshal not reporting.</div>';
        return;
      }
      const workers = fleet.workers || [];
      workerFleet.innerHTML = `
        <div class="project-head">
          <span>${escapeHtml(fleet.running || 0)}/${escapeHtml(fleet.limit || 3)} active</span>
          <span>${escapeHtml(marshal.status || 'unknown')}</span>
        </div>
        ${workers.map(worker => `
          <div class="command-item ${worker.running ? 'assigned' : 'blocked'}">
            <div>${escapeHtml(worker.worker_id)}</div>
            <div class="meta">
              ${worker.running ? 'running' : 'stopped'} ·
              ${escapeHtml((worker.capabilities || []).join(', ') || 'no capabilities')} ·
              restarts ${escapeHtml(worker.restart_count || 0)}
            </div>
          </div>
        `).join('')}
      `;
    }

    async function takeStewardAction(action, item) {
      const payload = {
        action,
        task_id: item.task_id || null,
        project_id: item.task_id ? null : item.project_id,
      };
      if (action === 'defer') payload.value = 86400;
      if (action === 'reprioritize') {
        const value = window.prompt('Priority from -100 to 100:', '10');
        if (value === null) return;
        payload.value = Number(value);
      }
      if (action === 'context') {
        const value = window.prompt('What context does Hive need?');
        if (!value) return;
        payload.value = value;
      }
      if (action === 'reject') {
        const note = window.prompt('Why are you rejecting this recommendation?');
        if (note === null) return;
        payload.note = note;
      }
      stewardBrief.querySelectorAll('button').forEach(button => button.disabled = true);
      try {
        await api('/api/steward/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        await refresh();
      } catch (err) {
        window.alert('Steward action failed: ' + err.message);
        await refresh();
      }
    }

    function renderCommandQueue() {
      const tasks = (state.orchestration?.tasks || [])
        .filter(task => !['completed', 'cancelled'].includes(task.status))
        .sort((a, b) => (b.priority || 0) - (a.priority || 0))
        .slice(0, 12);
      if (!tasks.length) {
        commandQueue.innerHTML = '<div class="meta">No commands reported.</div>';
        return;
      }
      commandQueue.innerHTML = tasks.map(task => {
        const worker = task.assigned_worker_id
          ? ` → ${task.assigned_worker_id}`
          : '';
        const dependencies = (task.depends_on || []).length
          ? ` · waits for ${(task.depends_on || []).join(', ')}`
          : '';
        const className = task.status === 'assigned' || task.status === 'running'
          ? 'assigned'
          : (task.status === 'blocked' ? 'blocked' : '');
        return `
          <div class="command-item ${escapeHtml(className)}">
            <div>${escapeHtml(task.title || task.task_id)}</div>
            <div class="meta">
              ${escapeHtml(task.project_id || 'unassigned project')} ·
              ${escapeHtml(task.status || 'unknown')}${escapeHtml(worker)}${escapeHtml(dependencies)}
            </div>
          </div>
        `;
      }).join('');
    }

    function filteredNodes() {
      const q = search.value.trim().toLowerCase();
      let nodes = state.nodes.slice();
      if (activeFilter === 'active') {
        const floor = Math.max(0, (state.latest_task_id || 0) - 80);
        nodes = nodes.filter(n => {
          if (n.kind === 'child') return true;
          return typeof n.id !== 'number' || n.id >= floor || n.status === 'current' || n.status === 'blocked' || n.anchor?.valid_file === false;
        });
      } else if (activeFilter === 'current') {
        const current = state.current_task_id || state.latest_task_id;
        nodes = relatedNodesFor(current);
      } else if (activeFilter === 'blocked') {
        nodes = nodes.filter(n => n.status === 'blocked' || n.status === 'pending_pilot_review');
      } else if (activeFilter === 'patches') {
        nodes = nodes.filter(n => ['patch', 'review'].includes(n.kind));
      } else if (activeFilter === 'invalid') {
        nodes = nodes.filter(n => n.anchor && n.anchor.valid_file === false);
      }
      if (!q) return nodes.slice(0, activeFilter === 'all' ? 240 : 120);
      return nodes.filter(n => {
        const w = n.work || {};
        const haystack = [
          n.id, n.kind, n.status, n.note,
          n.anchor?.target_file, n.anchor?.target_symbol,
          w.work_mode, w.domain, w.artifact, w.operation, w.validation, w.task_type
        ].join(' ').toLowerCase();
        return haystack.includes(q);
      }).slice(0, activeFilter === 'all' ? 240 : 120);
    }

    function relatedNodesFor(rootId) {
      if (rootId == null) return state.nodes.slice(-60);
      const keep = new Set([String(rootId)]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const edge of state.edges) {
          const from = String(edge.from);
          const to = String(edge.to);
          if (keep.has(from) && !keep.has(to)) { keep.add(to); changed = true; }
          if (keep.has(to) && !keep.has(from)) { keep.add(from); changed = true; }
        }
      }
      return state.nodes.filter(n => keep.has(String(n.id)));
    }

    function renderCurrentCard() {
      const currentId = state.current_task_id || state.latest_task_id;
      const node = state.nodes.find(n => String(n.id) === String(currentId));
      if (!node) {
        currentCard.innerHTML = '<div class="meta">No current task recorded.</div>';
        return;
      }
      const a = node.anchor || {};
      const w = node.work || {};
      const invalid = a.valid_file === false ? ' bad' : '';
      currentCard.innerHTML = `
        <div class="title">${escapeHtml(node.label)}</div>
        <div class="meta">${escapeHtml(node.status || 'unknown')} / ${escapeHtml(node.kind)}</div>
        <div style="margin-top:6px">
          <span class="chip mode">${escapeHtml(w.work_mode || 'no mode')}</span>
          <span class="chip">${escapeHtml(w.domain || 'no domain')}</span>
          <span class="chip${invalid}">${escapeHtml(a.target_file || 'no file')}</span>
          <span class="chip">${escapeHtml(a.target_symbol || 'no symbol')}</span>
        </div>
      `;
      currentCard.onclick = () => selectAndFocus(node.id);
    }

    function renderList() {
      const items = filteredNodes();
      list.innerHTML = items.map(n => `
        <div class="list-item" data-id="${escapeHtml(n.id)}">
          <div class="title">${escapeHtml(n.label)}</div>
          <div class="meta">${escapeHtml(n.kind)} / ${escapeHtml(n.status || 'unknown')} ${workChipText(n)} ${anchorChipText(n)}</div>
        </div>
      `).join('');
      list.querySelectorAll('.list-item').forEach(el => {
        el.addEventListener('click', () => selectNode(el.dataset.id));
      });
    }

    function anchorChipText(node) {
      const anchor = node.anchor || {};
      if (!anchor.target_file && !anchor.target_symbol) return '';
      return ` / ${anchor.target_file || 'none'}::${anchor.target_symbol || 'none'}`;
    }

    function workChipText(node) {
      const work = node.work || {};
      const mode = work.work_mode || '';
      const domain = work.domain || '';
      if (!mode && !domain) return '';
      return ` / ${mode || 'mode?'}:${domain || 'domain?'}`;
    }

    function laneFor(kind) {
      return { task: 0, plan: 1, child: 2, patch: 3, review: 4, failure: 4, lesson: 5, memory: 5 }[kind] ?? 5;
    }

    function renderGraph() {
      const nodes = filteredNodes();
      const nodeIds = new Set(nodes.map(n => String(n.id)));
      const byLane = new Map();
      for (const node of nodes) {
        const lane = laneFor(node.kind);
        if (!byLane.has(lane)) byLane.set(lane, []);
        byLane.get(lane).push(node);
      }

      const positions = new Map();
      for (const [lane, laneNodes] of byLane.entries()) {
        laneNodes.forEach((node, index) => {
          positions.set(String(node.id), { x: 70 + lane * 250, y: 60 + index * 112 });
        });
      }

      const edgeSvg = state.edges
        .filter(e => nodeIds.has(String(e.from)) && nodeIds.has(String(e.to)))
        .map(e => {
          const from = positions.get(String(e.from));
          const to = positions.get(String(e.to));
          if (!from || !to) return '';
          const x1 = from.x + 210, y1 = from.y + 31, x2 = to.x, y2 = to.y + 31;
          const mid = (x1 + x2) / 2;
          return `<path class="edge" d="M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}" />
                  <text class="edge-label" x="${mid - 18}" y="${(y1 + y2) / 2 - 5}">${escapeHtml(e.label || '')}</text>`;
        }).join('');

      const nodeSvg = nodes.map(n => {
        const p = positions.get(String(n.id));
        const invalid = n.anchor && n.anchor.valid_file === false ? ' invalid' : '';
        const selectedClass = selected && String(selected.id) === String(n.id) ? ' selected' : '';
        return `<g class="node ${escapeHtml(n.kind)}${invalid}${selectedClass}" data-id="${escapeHtml(n.id)}" transform="translate(${p.x},${p.y})">
          <rect width="210" height="72"></rect>
          <text x="10" y="20">${escapeHtml(shorten(n.label, 30))}</text>
          <text x="10" y="40" class="meta">${escapeHtml(shorten(`${n.status || 'unknown'} / ${workChipText(n).replace(/^ \/ /, '')}`, 32))}</text>
          <text x="10" y="58" class="meta">${escapeHtml(shorten(anchorChipText(n).replace(/^ \/ /, ''), 30))}</text>
        </g>`;
      }).join('');

      graph.innerHTML = edgeSvg + nodeSvg;
      graph.querySelectorAll('.node').forEach(el => {
        el.addEventListener('click', () => selectNode(el.dataset.id));
      });
    }

    function shorten(value, limit) {
      const text = String(value || '');
      return text.length <= limit ? text : text.slice(0, limit - 3) + '...';
    }

    function selectNode(id) {
      selected = state.nodes.find(n => String(n.id) === String(id));
      renderGraph();
      renderDetail();
    }

    function selectAndFocus(id) {
      selectNode(id);
      setTimeout(() => scrollToNode(id), 0);
    }

    function scrollToNode(id) {
      const el = graph.querySelector(`.node[data-id="${CSS.escape(String(id))}"]`);
      if (!el) return;
      const transform = el.getAttribute('transform') || '';
      const match = /translate\(([-0-9.]+),([-0-9.]+)\)/.exec(transform);
      if (!match) return;
      const x = Number(match[1]);
      const y = Number(match[2]);
      graphWrap.scrollTo({
        left: Math.max(0, x - graphWrap.clientWidth / 2 + 120),
        top: Math.max(0, y - graphWrap.clientHeight / 2 + 80),
        behavior: 'smooth'
      });
    }

    function focusPreferredNode() {
      const invalid = state.nodes.find(n => n.anchor && n.anchor.valid_file === false);
      const preferredId = invalid?.id || state.current_task_id || state.latest_task_id;
      if (preferredId != null) selectAndFocus(preferredId);
    }

    function renderDetail() {
      if (!selected) {
        detail.textContent = 'Select a node to inspect its plan, patch, anchor, or task metadata.';
        return;
      }
      const a = selected.anchor || {};
      const w = selected.work || {};
      const anchorClass = a.valid_file === false ? 'bad' : (a.target_file ? 'good' : '');
      const createSymbols = Array.isArray(w.creates_symbols) ? w.creates_symbols : [];
      const wireSymbols = Array.isArray(w.wires_into_symbols) ? w.wires_into_symbols : [];
      detail.innerHTML = `
        <div class="chip">${escapeHtml(selected.kind)}</div>
        <div class="chip">${escapeHtml(selected.status || 'unknown')}</div>
        <div class="chip mode">${escapeHtml(w.work_mode || 'mode unknown')}</div>
        <div class="chip">${escapeHtml(w.domain || 'domain unknown')}</div>
        <h3>${escapeHtml(selected.label)}</h3>
        <div class="field-label">Work Ontology</div>
        <div class="work-grid">
          <div class="work-row"><b>Mode</b>${escapeHtml(w.work_mode || 'none')}</div>
          <div class="work-row"><b>Domain</b>${escapeHtml(w.domain || 'none')}</div>
          <div class="work-row"><b>Artifact</b>${escapeHtml(w.artifact || 'none')}</div>
          <div class="work-row"><b>Operation</b>${escapeHtml(w.operation || 'none')}</div>
          <div class="work-row"><b>Validation</b>${escapeHtml(w.validation || 'none')}</div>
          ${createSymbols.length ? `<div class="work-row"><b>Creates</b>${escapeHtml(createSymbols.join(', '))}</div>` : ''}
          ${wireSymbols.length ? `<div class="work-row"><b>Wires Into</b>${escapeHtml(wireSymbols.join(', '))}</div>` : ''}
          ${w.insertion_region ? `<div class="work-row"><b>Insertion Region</b>${escapeHtml(w.insertion_region)}</div>` : ''}
        </div>
        <div class="field-label">Anchor</div>
        <div>
          <span class="chip ${anchorClass}">file: ${escapeHtml(a.target_file || 'none')}</span>
          <span class="chip">symbol: ${escapeHtml(a.target_symbol || 'none')}</span>
          <span class="chip">confidence: ${escapeHtml(a.confidence || 'none')}</span>
          <span class="chip">source: ${escapeHtml(a.source || 'none')}</span>
        </div>
        <div class="grid2" style="margin-top:10px">
          <button id="repair-gui-anchor">Set GUI Anchor + Replan</button>
          <button id="replan-selected">Replan Selected</button>
        </div>
        <div class="field-label">Note</div>
        <pre>${escapeHtml(selected.note || '')}</pre>
        <div class="field-label">Metadata</div>
        <pre>${escapeHtml(JSON.stringify(selected.metadata || {}, null, 2))}</pre>
      `;
      document.getElementById('repair-gui-anchor').addEventListener('click', repairGuiAnchor);
      document.getElementById('replan-selected').addEventListener('click', replanSelected);
    }

    async function sendCommand(command) {
      command = String(command || '').trim();
      if (!command) return;
      await api('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command })
      });
      document.getElementById('command').value = '';
      setTimeout(refresh, 1200);
    }

    function selectedNumericId() {
      if (!selected) return null;
      if (typeof selected.id === 'number') return selected.id;
      const parsed = Number(selected.id);
      return Number.isInteger(parsed) ? parsed : null;
    }

    function selectedTaskId() {
      if (!selected) return null;
      if (selected.kind === 'task' && typeof selected.id === 'number') return selected.id;
      const metaTask = selected.metadata && selected.metadata.task_id;
      if (Number.isInteger(metaTask)) return metaTask;
      const planTask = selected.metadata && selected.metadata.plan && selected.metadata.plan.task_id;
      if (Number.isInteger(planTask)) return planTask;
      return selectedNumericId();
    }

    function repairGuiAnchor() {
      const taskId = selectedTaskId();
      if (taskId == null) return;
      sendCommand(`pilot task ${taskId} Target file is hive_gui.py. Do not use Bazaar.switch or any vendor/archive symbol. Plan this as a GUI cockpit change.`);
      setTimeout(() => sendCommand(`plan task ${taskId}`), 1600);
    }

    function replanSelected() {
      const taskId = selectedTaskId();
      if (taskId == null) return;
      sendCommand(`plan task ${taskId}`);
    }

    document.getElementById('refresh').addEventListener('click', refresh);
    document.getElementById('restart').addEventListener('click', async () => {
      await api('/api/restart', { method: 'POST' });
      setTimeout(refresh, 800);
    });
    document.getElementById('create-task').addEventListener('click', () => {
      const text = document.getElementById('new-task').value.trim();
      if (!text) return;
      document.getElementById('new-task').value = '';
      sendCommand(text);
    });
    document.getElementById('create-plan').addEventListener('click', async () => {
      const text = document.getElementById('new-task').value.trim();
      if (!text) return;
      const before = highestTaskId();
      document.getElementById('new-task').value = '';
      await sendCommand(text);
      setTimeout(async () => {
        await refresh();
        const next = highestTaskId();
        if (next && next !== before) sendCommand(`plan task ${next}`);
      }, 2200);
    });
    document.getElementById('send-command').addEventListener('click', () => sendCommand(document.getElementById('command').value));
    document.getElementById('command').addEventListener('keydown', e => {
      if (e.key === 'Enter') sendCommand(e.target.value);
    });
    document.querySelectorAll('[data-action]').forEach(button => {
      button.addEventListener('click', () => {
        const id = selectedNumericId();
        if (id == null) return;
        sendCommand(`${button.dataset.action} ${id}`);
      });
    });
    search.addEventListener('input', () => {
      renderList();
      renderGraph();
    });
    document.querySelectorAll('#filters button').forEach(button => {
      button.addEventListener('click', () => {
        activeFilter = button.dataset.filter;
        document.querySelectorAll('#filters button').forEach(b => b.classList.toggle('active', b === button));
        renderList();
        renderGraph();
        focusPreferredNode();
      });
    });
    document.getElementById('focus-current').addEventListener('click', () => {
      const id = state.current_task_id || state.latest_task_id;
      if (id != null) selectAndFocus(id);
    });
    document.getElementById('focus-latest').addEventListener('click', () => {
      if (state.latest_task_id != null) selectAndFocus(state.latest_task_id);
    });

    function highestTaskId() {
      const ids = state.nodes
        .filter(n => n.kind === 'task' && typeof n.id === 'number')
        .map(n => n.id);
      return ids.length ? Math.max(...ids) : null;
    }

    async function pollTranscript() {
      try {
        const data = await api(`/api/transcript?cursor=${transcriptCursor}`);
        transcriptCursor = data.cursor;
        if (data.text) {
          transcript.textContent += data.text;
          transcript.scrollTop = transcript.scrollHeight;
        }
      } catch (err) {
        console.error(err);
      } finally {
        setTimeout(pollTranscript, 500);
      }
    }

    refresh();
    pollTranscript();
    setInterval(refresh, 6000);

    // --- Tab switching ---
    const TABS = ['selected', 'project', 'chat'];
    document.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        TABS.forEach(t => {
          document.getElementById('tab-' + t).style.display = t === tab ? '' : 'none';
        });
        if (tab === 'project') refreshEntities();
      });
    });

    async function refreshEntities() {
      try {
        const data = await api('/api/entities');
        renderEntities(data.entities || []);
      } catch (err) {
        document.getElementById('entity-list').textContent = 'Failed to load entities.';
      }
    }

    function renderEntities(entities) {
      const list = document.getElementById('entity-list');
      if (!entities.length) {
        list.innerHTML = '<div class="meta">No entities materialized yet. Say "create X" to Hive.</div>';
        return;
      }
      const byType = {};
      for (const e of entities) {
        const t = e.entity_type || 'unknown';
        (byType[t] = byType[t] || []).push(e);
      }
      list.innerHTML = Object.keys(byType).sort().map(type => `
        <div style="margin-bottom:10px">
          <div class="field-label">${escapeHtml(type.charAt(0).toUpperCase() + type.slice(1))}s</div>
          ${byType[type].map(e => `
            <div class="list-item" data-entity-name="${escapeHtml(e.name)}" data-entity-type="${escapeHtml(e.entity_type || '')}">
              <div class="title">${escapeHtml(e.name)}</div>
              <div class="meta">${escapeHtml(e.project || '')} · ${escapeHtml(e.file || '')}</div>
            </div>
          `).join('')}
        </div>
      `).join('');
      list.querySelectorAll('.list-item[data-entity-name]').forEach(el => {
        el.addEventListener('click', async () => {
          try {
            const name = el.dataset.entityName;
            const type = el.dataset.entityType;
            const data = await api('/api/entity?name=' + encodeURIComponent(name) + '&type=' + encodeURIComponent(type));
            document.getElementById('entity-content').textContent = data.content || '(empty)';
          } catch (err) {
            document.getElementById('entity-content').textContent = 'Failed to load entity file.';
          }
        });
      });
    }

    setInterval(() => {
      if (document.querySelector('.tab[data-tab="project"].active')) refreshEntities();
    }, 5000);

    // --- Chat ---
    function appendChatMsg(speaker, text, cls) {
      const box = document.getElementById('chat-messages');
      const div = document.createElement('div');
      div.className = 'chat-msg ' + speaker + (cls ? ' ' + cls : '');
      div.innerHTML = `<div class="speaker">${escapeHtml(speaker.charAt(0).toUpperCase() + speaker.slice(1))}</div>${escapeHtml(text)}`;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      return div;
    }

    async function sendChat() {
      const input = document.getElementById('chat-input');
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      document.getElementById('chat-send').disabled = true;
      appendChatMsg('pilot', text);
      const thinking = appendChatMsg('hive', 'Thinking...', 'thinking');
      try {
        const data = await api('/api/converse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        thinking.remove();
        appendChatMsg('hive', data.response || '(no response)');
        // refresh entity list in case something was materialized
        refreshEntities();
      } catch (err) {
        thinking.remove();
        appendChatMsg('hive', 'Error: ' + err.message);
      } finally {
        document.getElementById('chat-send').disabled = false;
        input.focus();
      }
    }

    document.getElementById('chat-send').addEventListener('click', sendChat);
    document.getElementById('chat-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/state":
            self._send_json(build_state_payload())
            return
        if parsed.path == "/api/steward":
            payload = build_state_payload()
            self._send_json({
                "ok": True,
                "steward": payload.get("steward") or {},
            })
            return
        if parsed.path == "/api/transcript":
            cursor = parse_qs(parsed.query).get("cursor", ["0"])[0]
            self._send_json(HIVE.transcript_since(cursor))
            return
        if parsed.path == "/api/entities":
            try:
                index_path = ROOT / ".hive_index.json"
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
                entities = sorted(index.values(), key=lambda e: (e.get("entity_type", ""), e.get("name", "")))
            except Exception:
                entities = []
            self._send_json({"entities": entities})
            return
        if parsed.path == "/api/entity":
            qs = parse_qs(parsed.query)
            name = (qs.get("name") or [""])[0]
            entity_type = (qs.get("type") or [""])[0]
            try:
                from HiveMaterializer import HiveMaterializer
                content = HiveMaterializer(project_dir=str(ROOT)).read_entity(name, entity_type)
            except Exception:
                content = None
            if content is None:
                self._send_json({"error": "Entity not found"}, status=404)
            else:
                self._send_json({"name": name, "entity_type": entity_type, "content": content})
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/command":
            payload = self._read_body()
            ok, message = HIVE.send(payload.get("command"))
            self._send_json({"ok": ok, "message": message}, status=200 if ok else 400)
            return
        if parsed.path == "/api/restart":
            HIVE.stop()
            HIVE.start()
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/converse":
            payload = self._read_body()
            message = str(payload.get("message") or "").strip()
            if not message:
                self._send_json({"ok": False, "error": "Empty message"}, status=400)
                return
            try:
                manager = get_converse_manager()
                response = manager.chat(message)
                self._send_json({"ok": True, "response": response})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if parsed.path == "/api/orchestration/events":
            payload = self._read_body()
            event_type = str(payload.get("event_type") or "").strip()
            subject_id = str(payload.get("subject_id") or "").strip()
            allowed_prefixes = ("project.", "worker.", "task.")
            if not event_type.startswith(allowed_prefixes):
                self._send_json(
                    {"ok": False, "error": "Unsupported orchestration event type"},
                    status=400,
                )
                return
            try:
                from orchestration import OrchestrationLedger
                event = OrchestrationLedger(
                    ROOT / ".hive" / "orchestration_events.jsonl"
                ).append(
                    event_type,
                    subject_id,
                    payload.get("payload") or {},
                    source=payload.get("source") or "cockpit_api",
                    occurred_at=payload.get("occurred_at"),
                    event_id=payload.get("event_id"),
                )
            except (TypeError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json({"ok": True, "event": event}, status=201)
            return
        if parsed.path == "/api/steward/action":
            payload = self._read_body()
            try:
                from orchestration import OrchestrationLedger
                from steward import StewardController, build_steward_brief
                ledger = OrchestrationLedger(
                    ROOT / ".hive" / "orchestration_events.jsonl"
                )
                event = StewardController(ledger).act(
                    str(payload.get("action") or ""),
                    task_id=(
                        str(payload.get("task_id")).strip()
                        if payload.get("task_id") is not None else None
                    ),
                    project_id=(
                        str(payload.get("project_id")).strip()
                        if payload.get("project_id") is not None else None
                    ),
                    value=payload.get("value"),
                    note=payload.get("note"),
                )
                brief = build_steward_brief(ledger.snapshot())
            except (TypeError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json({
                "ok": True,
                "event": event,
                "steward": brief,
            })
            return
        if parsed.path == "/api/dispatch/claim":
            payload = self._read_body()
            try:
                from orchestration import Dispatcher, OrchestrationLedger
                assignment = Dispatcher(
                    OrchestrationLedger(
                        ROOT / ".hive" / "orchestration_events.jsonl"
                    )
                ).claim(str(payload.get("worker_id") or "").strip())
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json({"ok": True, "assignment": assignment})
            return
        if parsed.path == "/api/dispatch/acknowledge":
            payload = self._read_body()
            if not isinstance(payload.get("accepted"), bool):
                self._send_json(
                    {"ok": False, "error": "accepted must be a boolean"},
                    status=400,
                )
                return
            try:
                from orchestration import Dispatcher, OrchestrationLedger
                event = Dispatcher(
                    OrchestrationLedger(
                        ROOT / ".hive" / "orchestration_events.jsonl"
                    )
                ).acknowledge(
                    str(payload.get("worker_id") or "").strip(),
                    str(payload.get("task_id") or "").strip(),
                    str(payload.get("lease_id") or "").strip(),
                    accepted=payload["accepted"],
                    reason=payload.get("reason"),
                )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=409)
                return
            self._send_json({"ok": True, "event": event})
            return
        if parsed.path == "/api/dispatch/complete":
            payload = self._read_body()
            try:
                from orchestration import Dispatcher, OrchestrationLedger
                event = Dispatcher(
                    OrchestrationLedger(
                        ROOT / ".hive" / "orchestration_events.jsonl"
                    )
                ).complete(
                    str(payload.get("worker_id") or "").strip(),
                    str(payload.get("task_id") or "").strip(),
                    str(payload.get("lease_id") or "").strip(),
                    outcome=payload.get("outcome") or {},
                )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=409)
                return
            self._send_json({"ok": True, "event": event})
            return
        if parsed.path == "/api/dispatch/renew":
            payload = self._read_body()
            try:
                from orchestration import Dispatcher, OrchestrationLedger
                event = Dispatcher(
                    OrchestrationLedger(
                        ROOT / ".hive" / "orchestration_events.jsonl"
                    )
                ).renew(
                    str(payload.get("worker_id") or "").strip(),
                    str(payload.get("task_id") or "").strip(),
                    str(payload.get("lease_id") or "").strip(),
                )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=409)
                return
            self._send_json({"ok": True, "event": event})
            return
        if parsed.path == "/api/dispatch/fail":
            payload = self._read_body()
            if not isinstance(payload.get("retryable", False), bool):
                self._send_json(
                    {"ok": False, "error": "retryable must be a boolean"},
                    status=400,
                )
                return
            try:
                from orchestration import Dispatcher, OrchestrationLedger
                event = Dispatcher(
                    OrchestrationLedger(
                        ROOT / ".hive" / "orchestration_events.jsonl"
                    )
                ).fail(
                    str(payload.get("worker_id") or "").strip(),
                    str(payload.get("task_id") or "").strip(),
                    str(payload.get("lease_id") or "").strip(),
                    error=str(payload.get("error") or "worker_failed"),
                    outcome=payload.get("outcome") or {},
                    retryable=payload.get("retryable", False),
                )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=409)
                return
            self._send_json({"ok": True, "event": event})
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        return


def main():
    global PROJECT_DIR
    args = sys.argv[1:]
    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 < len(args):
            PROJECT_DIR = Path(args[idx + 1]).resolve()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Hive Cockpit running at {url}")
    if PROJECT_DIR:
        print(f"Project: {PROJECT_DIR}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        HIVE.stop()
        server.server_close()


if __name__ == "__main__":
    main()
