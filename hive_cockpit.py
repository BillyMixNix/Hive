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
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Hive</title>
  <style>
    :root {
      --bg: #090d12;
      --panel: #0e1620;
      --panel-2: #0c131b;
      --line: #1e2e3d;
      --text: #e2eaf3;
      --muted: #7a8fa0;
      --blue: #4da3ff;
      --green: #37c985;
      --amber: #f3b653;
      --red: #f06b6b;
      --purple: #b08cff;
    }
    * { box-sizing: border-box; margin: 0; }
    body {
      height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Segoe UI, system-ui, sans-serif;
      display: grid;
      grid-template-rows: 48px 1fr;
      overflow: hidden;
    }
    button, input, textarea, select { font: inherit; }
    button {
      border: 1px solid #253545;
      background: #131f2e;
      color: var(--text);
      border-radius: 6px;
      padding: 6px 14px;
      cursor: pointer;
      font-size: 13px;
      white-space: nowrap;
    }
    button:hover { background: #1a2d42; }
    button.primary { background: #1a5490; border-color: #2a7acc; }
    button.primary:hover { background: #1f65ab; }
    button.danger { background: #5e2428; border-color: #8a3338; }
    input, textarea, select {
      color: var(--text);
      background: #07101a;
      border: 1px solid #1e2e3d;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
      width: 100%;
    }
    textarea { resize: none; }

    /* Topbar */
    #topbar {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 0 16px;
      background: #0a1118;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    .brand {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--blue);
      flex-shrink: 0;
    }
    #stats { display: flex; gap: 6px; flex: 1; }
    .pill {
      border: 1px solid #1e2e3d;
      border-radius: 999px;
      padding: 2px 9px;
      background: #0b1420;
      color: var(--muted);
      font-size: 11px;
    }
    .pill.online { border-color: #1f4a35; color: var(--green); }

    /* Three-column shell */
    #shell {
      display: grid;
      grid-template-columns: 240px 1fr 300px;
      min-height: 0;
    }

    /* ── Left: conversation log ── */
    #left {
      background: var(--panel);
      border-right: 1px solid var(--line);
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    .sidebar-header {
      padding: 10px 12px 8px;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    #conv-log {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      padding: 6px;
      gap: 2px;
    }
    .conv-entry {
      padding: 8px 10px;
      border-radius: 6px;
      cursor: pointer;
      border-left: 2px solid transparent;
      transition: background 0.1s;
    }
    .conv-entry:hover { background: #0b1825; border-left-color: #2d4a62; }
    .conv-entry .pilot-line {
      font-size: 12px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 2px;
    }
    .conv-entry .hive-line {
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .conv-empty {
      padding: 16px 12px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }

    /* ── Center: active chat ── */
    #center {
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: var(--bg);
    }
    #chat-messages {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      padding: 28px 40px;
      gap: 24px;
    }
    #chat-empty {
      margin: auto;
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
    }
    #chat-empty .wordmark {
      font-size: 36px;
      font-weight: 800;
      letter-spacing: 0.12em;
      color: #1a3050;
    }
    #chat-empty .sub {
      font-size: 13px;
      color: var(--muted);
    }
    .chat-msg {
      display: flex;
      flex-direction: column;
      gap: 4px;
      max-width: 740px;
    }
    .chat-msg.pilot { align-self: flex-end; align-items: flex-end; }
    .chat-msg.hive  { align-self: flex-start; align-items: flex-start; }
    .chat-msg .label {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }
    .chat-msg .bubble {
      padding: 10px 14px;
      border-radius: 10px;
      font-size: 13px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .chat-msg.pilot .bubble { background: #0d1e33; border: 1px solid #1b3352; }
    .chat-msg.hive  .bubble { background: #0a1a10; border: 1px solid #183322; }
    .chat-msg.thinking .bubble { opacity: 0.45; font-style: italic; }

    #chat-input-area {
      border-top: 1px solid var(--line);
      padding: 12px 28px 16px;
      display: flex;
      gap: 10px;
      align-items: flex-end;
      background: var(--panel);
      flex-shrink: 0;
    }
    #chat-input {
      flex: 1;
      min-height: 42px;
      max-height: 130px;
      overflow-y: auto;
      line-height: 1.5;
    }

    /* ── Right: entity explorer ── */
    #right {
      background: var(--panel);
      border-left: 1px solid var(--line);
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    #entity-list {
      flex: 1;
      overflow-y: auto;
      padding: 6px;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    .etype-label {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--muted);
      padding: 8px 6px 3px;
    }
    .entity-item {
      padding: 6px 8px;
      border-radius: 5px;
      cursor: pointer;
      font-size: 12px;
    }
    .entity-item:hover { background: #0c1825; }
    .entity-item.active { background: #0d1e33; border-left: 2px solid var(--blue); padding-left: 6px; }
    .entity-item .e-name { color: var(--text); }
    .entity-item .e-meta { color: var(--muted); font-size: 11px; margin-top: 1px; }
    #file-panel {
      border-top: 1px solid var(--line);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      max-height: 220px;
    }
    #entity-content {
      flex: 1;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: #060c12;
      padding: 10px 12px;
      color: #c8d8e8;
      font-family: Consolas, monospace;
      font-size: 11px;
      line-height: 1.5;
      margin: 0;
      border: none;
    }

    /* ── Graph overlay ── */
    #graph-overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: var(--bg);
      flex-direction: column;
    }
    #graph-overlay.open { display: flex; }
    #graph-topbar {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 12px;
      height: 44px;
      background: #0a1118;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    #graph-shell {
      flex: 1;
      display: grid;
      grid-template-columns: 300px 1fr 340px;
      min-height: 0;
    }
    #graph-left, #graph-detail-panel {
      background: var(--panel);
      overflow: auto;
      padding: 12px;
    }
    #graph-left { border-right: 1px solid var(--line); }
    #graph-detail-panel { border-left: 1px solid var(--line); }
    #graph-wrap {
      overflow: auto;
      background-color: #050910;
      background-image:
        linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
      background-size: 42px 42px;
    }
    #graph { width: 1600px; height: 1400px; display: block; }

    /* graph nodes/edges */
    .node { cursor: pointer; filter: drop-shadow(0 6px 10px rgba(0,0,0,0.4)); }
    .node rect { stroke-width: 1.4; rx: 7; }
    .node text { fill: var(--text); font-size: 12px; pointer-events: none; }
    .node .meta { fill: var(--muted); font-size: 10px; }
    .edge { stroke: #253545; stroke-width: 1.2; fill: none; }
    .edge-label { fill: #5a7080; font-size: 10px; }
    .task rect   { fill: #0e1e30; stroke: var(--blue); }
    .plan rect   { fill: #17122a; stroke: var(--purple); }
    .child rect  { fill: #1e1a0e; stroke: var(--amber); }
    .patch rect  { fill: #0c2018; stroke: var(--green); }
    .review rect { fill: #22180e; stroke: var(--amber); }
    .failure rect{ fill: #221012; stroke: var(--red); }
    .lesson rect, .memory rect { fill: #0e1520; stroke: #3a5060; }
    .selected rect { stroke-width: 3; }
    .invalid rect  { stroke: var(--red); stroke-dasharray: 5 4; }

    /* graph sidebar reuse */
    .g-section { margin-bottom: 16px; }
    .g-section h2 { margin: 0 0 8px; font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: 0.05em; }
    .g-row { display: flex; gap: 8px; align-items: center; }
    .g-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .g-list-item { padding: 7px 9px; border: 1px solid #1e2e3d; border-radius: 6px; background: var(--panel-2); cursor: pointer; margin-bottom: 4px; }
    .g-list-item:hover { border-color: #2d4a62; }
    .g-list-item .title { font-size: 12px; }
    .g-list-item .meta  { color: var(--muted); font-size: 11px; margin-top: 2px; }
    .g-filters { display: flex; flex-wrap: wrap; gap: 5px; }
    .g-filters button.active { background: #1a4a70; border-color: var(--blue); }
    .g-chip { display: inline-block; border-radius: 999px; padding: 2px 7px; border: 1px solid #253545; color: var(--muted); font-size: 11px; margin: 2px 2px 2px 0; }
    .g-chip.bad  { border-color: #703035; color: #ff9da5; }
    .g-chip.good { border-color: #236040; color: #7ee0b3; }
    .current-card { border: 1px solid #1e3548; background: #0a1420; border-radius: 7px; padding: 9px 10px; margin-bottom: 10px; }
    .current-card .title { font-weight: 600; font-size: 12px; margin-bottom: 4px; }
    .current-card .meta  { color: var(--muted); font-size: 11px; }
    #node-list { display: flex; flex-direction: column; }
    .field-label { color: var(--muted); font-size: 11px; margin: 8px 0 3px; }
    #detail-pre, #g-transcript {
      white-space: pre-wrap; word-break: break-word;
      background: #060c12; border: 1px solid #1e2e3d; border-radius: 6px;
      padding: 9px; max-height: 260px; overflow: auto;
      color: #c8d8e8; font-family: Consolas, monospace; font-size: 11px;
    }
    #g-transcript { height: 180px; }
  </style>
</head>
<body>
  <header id="topbar">
    <div class="brand">Hive</div>
    <div id="stats"></div>
    <div style="display:flex;gap:8px;flex-shrink:0">
      <button id="toggle-graph">Graph</button>
      <button id="btn-restart">Restart Hive</button>
    </div>
  </header>

  <div id="shell">
    <!-- Left: conversation log -->
    <aside id="left">
      <div class="sidebar-header">Conversation</div>
      <div id="conv-log">
        <div class="conv-empty" data-placeholder>Start a conversation.<br>Your history will appear here.</div>
      </div>
    </aside>

    <!-- Center: active chat -->
    <main id="center">
      <div id="chat-messages">
        <div id="chat-empty">
          <div class="wordmark">HIVE</div>
          <div class="sub">Say something to begin.</div>
        </div>
      </div>
      <div id="chat-input-area">
        <textarea id="chat-input" placeholder="Talk to Hive..." rows="2"></textarea>
        <button id="chat-send" class="primary">Send</button>
      </div>
    </main>

    <!-- Right: entity / file explorer -->
    <aside id="right">
      <div class="sidebar-header">Project</div>
      <div id="entity-list">
        <div style="padding:12px 8px;color:var(--muted);font-size:12px;">No entities yet. Say &ldquo;create X&rdquo; to Hive.</div>
      </div>
      <div id="file-panel">
        <div class="sidebar-header">File</div>
        <pre id="entity-content">Select an entity.</pre>
      </div>
    </aside>
  </div>

  <!-- Graph overlay -->
  <div id="graph-overlay">
    <div id="graph-topbar">
      <span style="font-weight:700;font-size:13px;letter-spacing:0.05em">Graph</span>
      <div id="graph-pills" style="flex:1;display:flex;gap:6px;padding:0 10px;"></div>
      <div style="display:flex;gap:8px">
        <button id="graph-refresh">Refresh</button>
        <button id="graph-close">Close</button>
      </div>
    </div>
    <div id="graph-shell">
      <aside id="graph-left">
        <div class="g-section">
          <h2>New Task</h2>
          <textarea id="new-task" placeholder="Describe what Hive should do..." style="min-height:66px"></textarea>
          <div class="g-grid2" style="margin-top:7px">
            <button class="primary" id="create-task">Create</button>
            <button id="create-plan">Create + Plan</button>
          </div>
        </div>
        <div class="g-section">
          <h2>Current Work</h2>
          <div id="current-card" class="current-card">Loading...</div>
          <div class="g-grid2">
            <button id="focus-current">Focus Current</button>
            <button id="focus-latest">Focus Latest</button>
          </div>
        </div>
        <div class="g-section">
          <h2>Selected Actions</h2>
          <div class="g-grid2">
            <button data-action="show task">Show</button>
            <button data-action="plan task">Plan</button>
            <button data-action="code task">Code</button>
            <button data-action="review patch">Review Patch</button>
            <button data-action="apply patch">Apply Patch</button>
            <button data-action="rollback patch" class="danger">Rollback</button>
          </div>
        </div>
        <div class="g-section">
          <h2>Search</h2>
          <input id="graph-search" type="search" placeholder="Search tasks, files, status..." />
        </div>
        <div class="g-section">
          <h2>View</h2>
          <div class="g-filters" id="graph-filters">
            <button data-filter="active" class="active">Active</button>
            <button data-filter="current">Current</button>
            <button data-filter="blocked">Blocked</button>
            <button data-filter="patches">Patches</button>
            <button data-filter="invalid">Invalid</button>
            <button data-filter="all">All</button>
          </div>
        </div>
        <div class="g-section">
          <h2>Recent</h2>
          <div id="node-list"></div>
        </div>
      </aside>

      <div id="graph-wrap">
        <svg id="graph" aria-label="Hive task graph"></svg>
      </div>

      <aside id="graph-detail-panel">
        <div class="g-section" id="g-detail">
          <h2>Selected</h2>
          <div id="detail-body" style="color:var(--muted);font-size:12px">Select a node.</div>
        </div>
        <div class="g-section">
          <h2>Command</h2>
          <div class="g-row">
            <input id="g-command" placeholder="Raw Hive command" />
            <button id="g-send-command">Send</button>
          </div>
        </div>
        <div class="g-section">
          <h2>Transcript</h2>
          <pre id="g-transcript"></pre>
        </div>
      </aside>
    </div>
  </div>

  <script>
    // ── Utilities ──
    function esc(v) {
      return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
    }
    function shorten(v, n) { const s = String(v||''); return s.length<=n ? s : s.slice(0,n-3)+'...'; }
    async function api(path, opts) {
      const r = await fetch(path, opts);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }

    // ── Chat ──
    const chatMessages = document.getElementById('chat-messages');
    const chatEmpty    = document.getElementById('chat-empty');
    const convLog      = document.getElementById('conv-log');

    function appendMsg(role, text, extra) {
      if (chatEmpty) chatEmpty.remove();
      const d = document.createElement('div');
      d.className = 'chat-msg ' + role + (extra ? ' '+extra : '');
      d.innerHTML = `<div class="label">${role==='pilot'?'Pilot':'Hive'}</div><div class="bubble">${esc(text)}</div>`;
      chatMessages.appendChild(d);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return d;
    }

    function addToLog(pilotText, hiveText) {
      const ph = convLog.querySelector('[data-placeholder]');
      if (ph) ph.remove();
      const e = document.createElement('div');
      e.className = 'conv-entry';
      e.innerHTML = `<div class="pilot-line">▸ ${esc(shorten(pilotText, 48))}</div><div class="hive-line">${esc(shorten(hiveText, 56))}</div>`;
      e.addEventListener('click', () => chatMessages.scrollTop = chatMessages.scrollHeight);
      convLog.appendChild(e);
      convLog.scrollTop = convLog.scrollHeight;
    }

    async function sendChat() {
      const inp = document.getElementById('chat-input');
      const text = inp.value.trim();
      if (!text) return;
      inp.value = '';
      inp.style.height = '';
      document.getElementById('chat-send').disabled = true;
      appendMsg('pilot', text);
      const thinking = appendMsg('hive', 'Thinking…', 'thinking');
      try {
        const data = await api('/api/converse', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({message: text})
        });
        thinking.remove();
        const reply = data.response || '(no response)';
        appendMsg('hive', reply);
        addToLog(text, reply);
        refreshEntities();
      } catch(err) {
        thinking.remove();
        appendMsg('hive', 'Error: ' + err.message);
      } finally {
        document.getElementById('chat-send').disabled = false;
        inp.focus();
      }
    }

    document.getElementById('chat-send').addEventListener('click', sendChat);
    document.getElementById('chat-input').addEventListener('keydown', e => {
      if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    document.getElementById('chat-input').addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 130) + 'px';
    });

    // ── Entity explorer ──
    async function refreshEntities() {
      try {
        const data = await api('/api/entities');
        renderEntities(data.entities || []);
      } catch(_) {}
    }

    function renderEntities(entities) {
      const list = document.getElementById('entity-list');
      if (!entities.length) {
        list.innerHTML = '<div style="padding:12px 8px;color:var(--muted);font-size:12px;">No entities yet. Say &ldquo;create X&rdquo; to Hive.</div>';
        return;
      }
      const byType = {};
      for (const e of entities) {
        const t = e.entity_type || 'unknown';
        (byType[t] = byType[t] || []).push(e);
      }
      list.innerHTML = Object.keys(byType).sort().map(t =>
        `<div class="etype-label">${esc(t)}s</div>` +
        byType[t].map(e =>
          `<div class="entity-item" data-name="${esc(e.name)}" data-type="${esc(e.entity_type||'')}">
            <div class="e-name">${esc(e.name)}</div>
            <div class="e-meta">${esc(e.project||'')}${e.project?' · ':''}${esc(e.file||'')}</div>
          </div>`
        ).join('')
      ).join('');
      list.querySelectorAll('.entity-item').forEach(el => {
        el.addEventListener('click', async () => {
          list.querySelectorAll('.entity-item').forEach(i => i.classList.remove('active'));
          el.classList.add('active');
          try {
            const d = await api('/api/entity?name='+encodeURIComponent(el.dataset.name)+'&type='+encodeURIComponent(el.dataset.type));
            document.getElementById('entity-content').textContent = d.content || '(empty)';
          } catch(_) {
            document.getElementById('entity-content').textContent = 'Failed to load.';
          }
        });
      });
    }

    refreshEntities();
    setInterval(refreshEntities, 5000);

    // ── Status pills ──
    function updatePills(data) {
      const counts = {};
      for (const n of (data.nodes||[])) counts[n.kind] = (counts[n.kind]||0)+1;
      const online = data.hive_status === 'online';
      document.getElementById('stats').innerHTML = [
        [`Hive: ${data.hive_status||'?'}`, online],
        [`Files: ${data.known_files_count||0}`, false],
        [`Tasks: ${counts.task||0}`, false],
      ].map(([t,hi]) => `<span class="pill${hi?' online':''}">${esc(t)}</span>`).join('');
    }

    api('/api/state').then(updatePills).catch(()=>{});

    // ── Graph overlay ──
    let gState = { nodes:[], edges:[] };
    let gSelected = null;
    let gFilter = 'active';
    let gFocused = false;
    let transcriptCursor = 0;

    document.getElementById('toggle-graph').addEventListener('click', () => {
      document.getElementById('graph-overlay').classList.add('open');
      loadGraph();
    });
    document.getElementById('graph-close').addEventListener('click', () => {
      document.getElementById('graph-overlay').classList.remove('open');
    });
    document.getElementById('graph-refresh').addEventListener('click', loadGraph);
    document.getElementById('btn-restart').addEventListener('click', async () => {
      await api('/api/restart', {method:'POST'});
      setTimeout(loadGraph, 800);
    });

    async function loadGraph() {
      gState = await api('/api/state');
      updatePills(gState);
      renderGraphPills();
      renderCurrentCard();
      renderNodeList();
      renderGraph();
      if (!gFocused) { gFocused = true; focusBest(); }
    }

    function renderGraphPills() {
      const counts = {};
      for (const n of gState.nodes) counts[n.kind] = (counts[n.kind]||0)+1;
      document.getElementById('graph-pills').innerHTML = [
        ['Tasks', counts.task||0], ['Plans', counts.plan||0],
        ['Patches', counts.patch||0],
        ['Issues', gState.nodes.filter(n=>n.anchor&&n.anchor.valid_file===false).length],
      ].map(([k,v])=>`<span class="pill">${esc(k)}: ${v}</span>`).join('');
    }

    function filteredNodes() {
      const q = document.getElementById('graph-search').value.trim().toLowerCase();
      let nodes = gState.nodes.slice();
      if (gFilter==='active') {
        const floor = Math.max(0,(gState.latest_task_id||0)-80);
        nodes = nodes.filter(n => n.kind==='child' || typeof n.id!=='number' || n.id>=floor || n.status==='current' || n.status==='blocked' || n.anchor?.valid_file===false);
      } else if (gFilter==='current') {
        nodes = relatedTo(gState.current_task_id||gState.latest_task_id);
      } else if (gFilter==='blocked') {
        nodes = nodes.filter(n=>n.status==='blocked'||n.status==='pending_pilot_review');
      } else if (gFilter==='patches') {
        nodes = nodes.filter(n=>['patch','review'].includes(n.kind));
      } else if (gFilter==='invalid') {
        nodes = nodes.filter(n=>n.anchor&&n.anchor.valid_file===false);
      }
      if (!q) return nodes.slice(0, gFilter==='all'?240:120);
      return nodes.filter(n=>[n.id,n.kind,n.status,n.note,n.anchor?.target_file].join(' ').toLowerCase().includes(q)).slice(0,120);
    }

    function relatedTo(rootId) {
      if (rootId==null) return gState.nodes.slice(-60);
      const keep = new Set([String(rootId)]);
      let changed=true;
      while(changed){changed=false;for(const e of gState.edges){const f=String(e.from),t=String(e.to);if(keep.has(f)&&!keep.has(t)){keep.add(t);changed=true;}if(keep.has(t)&&!keep.has(f)){keep.add(f);changed=true;}}}
      return gState.nodes.filter(n=>keep.has(String(n.id)));
    }

    function laneFor(kind) { return {task:0,plan:1,child:2,patch:3,review:4,failure:4,lesson:5,memory:5}[kind]??5; }

    function renderGraph() {
      const nodes = filteredNodes();
      const ids = new Set(nodes.map(n=>String(n.id)));
      const byLane = new Map();
      for (const n of nodes) { const l=laneFor(n.kind); if(!byLane.has(l)) byLane.set(l,[]); byLane.get(l).push(n); }
      const pos = new Map();
      for (const [lane,ln] of byLane) ln.forEach((n,i)=>pos.set(String(n.id),{x:70+lane*250,y:60+i*112}));
      const svg = document.getElementById('graph');
      const edges = gState.edges.filter(e=>ids.has(String(e.from))&&ids.has(String(e.to))).map(e=>{
        const f=pos.get(String(e.from)),t=pos.get(String(e.to));
        if(!f||!t) return '';
        const x1=f.x+210,y1=f.y+31,x2=t.x,y2=t.y+31,mid=(x1+x2)/2;
        return `<path class="edge" d="M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}"/><text class="edge-label" x="${mid-18}" y="${(y1+y2)/2-5}">${esc(e.label||'')}</text>`;
      }).join('');
      const nodesSvg = nodes.map(n=>{
        const p=pos.get(String(n.id));
        const inv=n.anchor&&n.anchor.valid_file===false?' invalid':'';
        const sel=gSelected&&String(gSelected.id)===String(n.id)?' selected':'';
        return `<g class="node ${esc(n.kind)}${inv}${sel}" data-id="${esc(n.id)}" transform="translate(${p.x},${p.y})"><rect width="210" height="72"></rect><text x="10" y="20">${esc(shorten(n.label,30))}</text><text x="10" y="40" class="meta">${esc(shorten(n.status||'unknown',32))}</text><text x="10" y="58" class="meta">${esc(shorten(n.anchor?.target_file||'',30))}</text></g>`;
      }).join('');
      svg.innerHTML = edges + nodesSvg;
      svg.querySelectorAll('.node').forEach(el=>el.addEventListener('click',()=>selectNode(el.dataset.id)));
    }

    function renderCurrentCard() {
      const id = gState.current_task_id||gState.latest_task_id;
      const n = gState.nodes.find(n=>String(n.id)===String(id));
      const card = document.getElementById('current-card');
      if (!n) { card.innerHTML='<div class="meta" style="color:var(--muted);font-size:12px">No current task.</div>'; return; }
      card.innerHTML=`<div class="title">${esc(n.label)}</div><div class="meta">${esc(n.status||'?')} / ${esc(n.kind)}</div>`;
      card.onclick=()=>selectAndFocus(n.id);
    }

    function renderNodeList() {
      const items = filteredNodes();
      document.getElementById('node-list').innerHTML = items.map(n=>
        `<div class="g-list-item" data-id="${esc(n.id)}"><div class="title">${esc(n.label)}</div><div class="meta">${esc(n.kind)} / ${esc(n.status||'?')}</div></div>`
      ).join('');
      document.querySelectorAll('#node-list .g-list-item').forEach(el=>el.addEventListener('click',()=>selectNode(el.dataset.id)));
    }

    function selectNode(id) {
      gSelected = gState.nodes.find(n=>String(n.id)===String(id));
      renderGraph();
      renderDetail();
    }
    function selectAndFocus(id) { selectNode(id); setTimeout(()=>scrollTo(id),0); }
    function scrollTo(id) {
      const el = document.getElementById('graph').querySelector(`.node[data-id="${CSS.escape(String(id))}"]`);
      if (!el) return;
      const m = /translate\(([-0-9.]+),([-0-9.]+)\)/.exec(el.getAttribute('transform')||'');
      if (!m) return;
      const wrap = document.getElementById('graph-wrap');
      wrap.scrollTo({left:Math.max(0,+m[1]-wrap.clientWidth/2+120),top:Math.max(0,+m[2]-wrap.clientHeight/2+80),behavior:'smooth'});
    }
    function focusBest() {
      const inv = gState.nodes.find(n=>n.anchor&&n.anchor.valid_file===false);
      const id = inv?.id||gState.current_task_id||gState.latest_task_id;
      if (id!=null) selectAndFocus(id);
    }

    function renderDetail() {
      const det = document.getElementById('detail-body');
      if (!gSelected) { det.innerHTML='<span style="color:var(--muted);font-size:12px">Select a node.</span>'; return; }
      const a=gSelected.anchor||{}, ac=a.valid_file===false?'bad':(a.target_file?'good':'');
      det.innerHTML=`
        <div class="g-chip">${esc(gSelected.kind)}</div>
        <div class="g-chip">${esc(gSelected.status||'?')}</div>
        <h3 style="margin:8px 0 4px;font-size:13px">${esc(gSelected.label)}</h3>
        <div class="field-label">Anchor</div>
        <div><span class="g-chip ${ac}">file: ${esc(a.target_file||'none')}</span><span class="g-chip">symbol: ${esc(a.target_symbol||'none')}</span><span class="g-chip">conf: ${esc(a.confidence||'none')}</span></div>
        <div class="g-grid2" style="margin-top:8px">
          <button id="btn-repair">Set GUI Anchor + Replan</button>
          <button id="btn-replan">Replan Selected</button>
        </div>
        <div class="field-label">Note</div>
        <pre id="detail-pre">${esc(gSelected.note||'')}</pre>
      `;
      document.getElementById('btn-repair').addEventListener('click',()=>{
        const id=selectedTaskId(); if(id==null) return;
        sendCmd(`pilot task ${id} Target file is hive_gui.py.`);
        setTimeout(()=>sendCmd(`plan task ${id}`),1600);
      });
      document.getElementById('btn-replan').addEventListener('click',()=>{ const id=selectedTaskId(); if(id!=null) sendCmd(`plan task ${id}`); });
    }

    async function sendCmd(cmd) {
      cmd = String(cmd||'').trim(); if(!cmd) return;
      await api('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});
      document.getElementById('g-command').value='';
      setTimeout(loadGraph,1200);
    }

    function selectedNumericId() {
      if (!gSelected) return null;
      if (typeof gSelected.id==='number') return gSelected.id;
      const p=Number(gSelected.id); return Number.isInteger(p)?p:null;
    }
    function selectedTaskId() {
      if (!gSelected) return null;
      if (gSelected.kind==='task'&&typeof gSelected.id==='number') return gSelected.id;
      const m=gSelected.metadata; if(!m) return selectedNumericId();
      if (Number.isInteger(m.task_id)) return m.task_id;
      if (m.plan&&Number.isInteger(m.plan.task_id)) return m.plan.task_id;
      return selectedNumericId();
    }
    function highestTaskId() {
      const ids=gState.nodes.filter(n=>n.kind==='task'&&typeof n.id==='number').map(n=>n.id);
      return ids.length?Math.max(...ids):null;
    }

    document.getElementById('create-task').addEventListener('click',()=>{
      const t=document.getElementById('new-task').value.trim(); if(!t) return;
      document.getElementById('new-task').value=''; sendCmd(t);
    });
    document.getElementById('create-plan').addEventListener('click',async()=>{
      const t=document.getElementById('new-task').value.trim(); if(!t) return;
      const before=highestTaskId(); document.getElementById('new-task').value='';
      await sendCmd(t);
      setTimeout(async()=>{ await loadGraph(); const nx=highestTaskId(); if(nx&&nx!==before) sendCmd(`plan task ${nx}`); },2200);
    });
    document.getElementById('g-send-command').addEventListener('click',()=>sendCmd(document.getElementById('g-command').value));
    document.getElementById('g-command').addEventListener('keydown',e=>{ if(e.key==='Enter') sendCmd(e.target.value); });
    document.querySelectorAll('[data-action]').forEach(btn=>btn.addEventListener('click',()=>{
      const id=selectedNumericId(); if(id==null) return; sendCmd(`${btn.dataset.action} ${id}`);
    }));
    document.getElementById('graph-search').addEventListener('input',()=>{ renderNodeList(); renderGraph(); });
    document.querySelectorAll('#graph-filters button').forEach(btn=>btn.addEventListener('click',()=>{
      gFilter=btn.dataset.filter;
      document.querySelectorAll('#graph-filters button').forEach(b=>b.classList.toggle('active',b===btn));
      renderNodeList(); renderGraph(); focusBest();
    }));
    document.getElementById('focus-current').addEventListener('click',()=>{ const id=gState.current_task_id||gState.latest_task_id; if(id!=null) selectAndFocus(id); });
    document.getElementById('focus-latest').addEventListener('click',()=>{ if(gState.latest_task_id!=null) selectAndFocus(gState.latest_task_id); });

    // Transcript polling (for graph overlay)
    async function pollTranscript() {
      try {
        const d = await api(`/api/transcript?cursor=${transcriptCursor}`);
        transcriptCursor = d.cursor;
        if (d.text) { const t=document.getElementById('g-transcript'); t.textContent+=d.text; t.scrollTop=t.scrollHeight; }
      } catch(_) {}
      finally { setTimeout(pollTranscript,500); }
    }
    pollTranscript();
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

    HIVE.start()
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
