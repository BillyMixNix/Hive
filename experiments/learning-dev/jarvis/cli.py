from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from ipaddress import ip_address
from pathlib import Path

from . import __version__
from .api import serve as serve_api
from .codex_agent import CodexAgentError, check_codex
from .store import Store
from .supervisor import Supervisor


def _default_data_path() -> str:
    configured = os.environ.get("JARVIS_DATA")
    if configured:
        return configured
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return str(Path(os.environ["LOCALAPPDATA"]) / "HiveJarvis" / "jarvis.db")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return str(state_home / "hive-jarvis" / "jarvis.db")


def parser():
    p = argparse.ArgumentParser(prog="jarvis", description="Persistent Hive worker supervisor")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--data", default=_default_data_path())
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("start")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--open", dest="open_cockpit", action="store_true",
                     help="open the local Jarvis Cockpit in the default browser")
    sub.add_parser("once")
    add = sub.add_parser("add"); add.add_argument("goal"); add.add_argument("--workspace", default=".")
    add.add_argument("--kind", choices=("inspect", "command", "agent"), default="inspect")
    add.add_argument("--command", nargs=argparse.REMAINDER)
    access = add.add_mutually_exclusive_group()
    access.add_argument("--mutating", action="store_true", help="require approval and allow workspace edits")
    access.add_argument("--read-only", action="store_true", help="force an agent task into the read-only sandbox")
    sub.add_parser("list")
    show = sub.add_parser("show"); show.add_argument("task_id")
    for name in ("approve", "reject", "cancel"):
        x = sub.add_parser(name); x.add_argument("task_id")
    outcome = sub.add_parser("outcome"); outcome.add_argument("task_id"); outcome.add_argument("verdict", choices=("pass", "fail")); outcome.add_argument("summary")
    sub.add_parser("verify")
    sub.add_parser("agent-check")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "agent-check":
            status = check_codex(Path.cwd()); print(json.dumps(status, indent=2)); return 0 if status["ok"] else 1
        store = Store(args.data)
        if args.action == "start":
            with store.worker_lock():
                ledger_ok, detail = store.verify_chain()
                if not ledger_ok:
                    raise RuntimeError(f"evidence ledger verification failed: {detail}")
                recovered = store.recover(force=True)
                supervisor = Supervisor(store)
                supervisor.record_recovery(recovered)
                worker = threading.Thread(target=supervisor.serve, name="jarvis-worker", daemon=True)
                display_host = args.host
                try:
                    if ip_address(display_host).version == 6:
                        display_host = f"[{display_host}]"
                except ValueError:
                    pass
                cockpit_url = f"http://{display_host}:{args.port}/"

                def start_worker():
                    worker.start()
                    print(f"Jarvis Cockpit: {cockpit_url}")
                    if args.open_cockpit:
                        opener = threading.Timer(0.2, webbrowser.open, args=(cockpit_url,))
                        opener.daemon = True
                        opener.start()

                serve_api(
                    store, args.host, args.port,
                    worker_status=lambda: {**supervisor.health(), "thread_alive": worker.is_alive()},
                    on_bound=start_worker,
                )
        elif args.action == "once":
            with store.worker_lock():
                ledger_ok, detail = store.verify_chain()
                if not ledger_ok:
                    raise RuntimeError(f"evidence ledger verification failed: {detail}")
                store.recover(force=True)
                print(json.dumps({"worked": Supervisor(store).run_once()}))
        elif args.action == "add":
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: raise RuntimeError(f"evidence ledger verification failed: {detail}")
            if args.read_only and args.kind != "agent":
                raise ValueError("--read-only is only valid with --kind agent")
            payload = {"command": args.command} if args.kind == "command" else {}
            if args.kind == "command" and not args.command: raise ValueError("--command is required for command tasks")
            mutating = args.mutating or args.kind == "command" or (args.kind == "agent" and not args.read_only)
            print(json.dumps(store.create(kind=args.kind, goal=args.goal, workspace=args.workspace,
                                          payload=payload, mutating=mutating), indent=2))
        elif args.action == "list": print(json.dumps(store.list(), indent=2))
        elif args.action == "show": print(json.dumps({**store.get(args.task_id), "events": store.events(args.task_id)}, indent=2))
        elif args.action == "approve":
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: raise RuntimeError(f"evidence ledger verification failed: {detail}")
            task = store.get(args.task_id)
            if task["status"] != "WAITING_APPROVAL": raise ValueError("task is not waiting for approval")
            updated = store.transition(args.task_id, "READY", "TASK_APPROVED", expected_status=task["status"], approval="APPROVED")
            if updated is None: raise ValueError("task status changed; retry the action")
            print(json.dumps(updated, indent=2))
        elif args.action == "reject":
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: raise RuntimeError(f"evidence ledger verification failed: {detail}")
            task = store.get(args.task_id)
            if task["status"] != "WAITING_APPROVAL": raise ValueError("task is not waiting for approval")
            updated = store.transition(args.task_id, "REJECTED", "TASK_REJECTED", expected_status=task["status"], approval="REJECTED")
            if updated is None: raise ValueError("task status changed; retry the action")
            print(json.dumps(updated, indent=2))
        elif args.action == "cancel":
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: raise RuntimeError(f"evidence ledger verification failed: {detail}")
            task = store.get(args.task_id); status = task["status"]
            if status in {"SUCCEEDED", "FAILED", "REJECTED", "CANCELLED"}: raise ValueError("task is already terminal")
            if status == "RUNNING": raise ValueError("running task cancellation is not supported")
            updated = store.transition(args.task_id, "CANCELLED", "TASK_CANCELLED", expected_status=status)
            if updated is None: raise ValueError("task status changed; retry the action")
            print(json.dumps(updated, indent=2))
        elif args.action == "outcome":
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: raise RuntimeError(f"evidence ledger verification failed: {detail}")
            if store.get(args.task_id)["status"] != "SUCCEEDED": raise ValueError("outcomes require a succeeded task")
            print(json.dumps({"lesson_id": store.add_lesson(args.task_id, args.summary, args.verdict == "pass")}, indent=2))
        elif args.action == "verify":
            ok, detail = store.verify_chain(); print(json.dumps({"ok": ok, "detail": detail})); return 0 if ok else 1
    except (CodexAgentError, KeyError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    except KeyboardInterrupt:
        return 130
    return 0
