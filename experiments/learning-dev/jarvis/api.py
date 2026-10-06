from __future__ import annotations

import json
import os
import hmac
import socket
from ipaddress import ip_address
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urlsplit

from .dashboard import COCKPIT_CSS, COCKPIT_HTML, COCKPIT_JS
from .store import Store, TERMINAL


MAX_BODY_BYTES = 1_000_000


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind one unambiguous local Cockpit listener per port."""

    # POSIX SO_REUSEADDR permits quick restarts without allowing a second live
    # listener. Windows needs the inverse plus SO_EXCLUSIVEADDRUSE below.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class LoopbackHTTPServerV6(LoopbackHTTPServer):
    address_family = socket.AF_INET6


def handler_for(store: Store, worker_status=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HiveJarvis/0.3"

        def version_string(self):
            return self.server_version

        def _raw(self, code, raw, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers(); self.wfile.write(raw)

        def _json(self, code, body):
            raw = json.dumps(body, indent=2).encode()
            self._raw(code, raw, "application/json; charset=utf-8")

        def _cockpit(self, raw, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            )
            self.end_headers(); self.wfile.write(raw)

        def _authorized(self):
            token = os.environ.get("JARVIS_API_TOKEN")
            supplied = self.headers.get("Authorization", "")
            return not token or hmac.compare_digest(supplied, f"Bearer {token}")

        def _valid_host(self):
            raw = self.headers.get("Host", "")
            try:
                hostname = urlsplit(f"//{raw}").hostname
                if not hostname:
                    return False
                return hostname.rstrip(".").lower() == "localhost" or ip_address(hostname).is_loopback
            except ValueError:
                return False

        def _body(self):
            size = int(self.headers.get("Content-Length", 0))
            if size < 0 or size > MAX_BODY_BYTES:
                raise ValueError(f"request body must be between 0 and {MAX_BODY_BYTES} bytes")
            body = json.loads(
                self.rfile.read(size) or b"{}",
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON number: {value}")),
            )
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            return body

        def do_GET(self):
            if not self._valid_host(): return self._json(421, {"error": "loopback Host header required"})
            path = urlparse(self.path).path
            if path == "/": return self._cockpit(COCKPIT_HTML, "text/html; charset=utf-8")
            if path == "/assets/cockpit.css": return self._cockpit(COCKPIT_CSS, "text/css; charset=utf-8")
            if path == "/assets/cockpit.js": return self._cockpit(COCKPIT_JS, "text/javascript; charset=utf-8")
            if not self._authorized(): return self._json(401, {"error": "unauthorized"})
            parts = path.strip("/").split("/")
            try:
                if parts == ["health"]:
                    ledger_ok, tip = store.verify_chain()
                    worker = worker_status() if worker_status else None
                    worker_ok = worker is None or (
                        worker.get("alive") and worker.get("thread_alive", True)
                        and not worker.get("heartbeat_stale", False)
                        and worker.get("consecutive_errors", 0) == 0
                    )
                    healthy = bool(ledger_ok and worker_ok)
                    return self._json(
                        200 if healthy else 503,
                        {"ok": healthy, "ledger_ok": ledger_ok, "ledger_tip": tip, "worker": worker},
                    )
                if parts == ["tasks"]: return self._json(200, store.list())
                if parts == ["overview"]: return self._json(200, store.overview())
                if len(parts) == 2 and parts[0] == "tasks": return self._json(200, store.get(parts[1]))
                if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "events": return self._json(200, store.events(parts[1]))
                if parts == ["lessons"]: return self._json(200, store.lessons())
                return self._json(404, {"error": "not found"})
            except KeyError: return self._json(404, {"error": "task not found"})

        def do_POST(self):
            if not self._valid_host(): return self._json(421, {"error": "loopback Host header required"})
            if not self._authorized(): return self._json(401, {"error": "unauthorized"})
            if self.headers.get("Origin"): return self._json(403, {"error": "browser-origin requests are not accepted"})
            ledger_ok, detail = store.verify_chain()
            if not ledger_ok: return self._json(503, {"error": f"evidence ledger verification failed: {detail}"})
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json": return self._json(415, {"error": "Content-Type must be application/json"})
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                body = self._body()
                if parts == ["tasks"]:
                    kind = body["kind"]
                    if "mutating" in body and not isinstance(body["mutating"], bool):
                        raise ValueError("mutating must be a JSON boolean")
                    mutating = True if kind == "command" else (
                        body["mutating"] if "mutating" in body else kind == "agent"
                    )
                    max_attempts = body.get("max_attempts", 2)
                    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
                        raise ValueError("max_attempts must be a JSON integer")
                    task = store.create(kind=kind, goal=body["goal"], workspace=body["workspace"],
                                        payload=body.get("payload", {}), mutating=mutating,
                                        max_attempts=max_attempts)
                    return self._json(201, task)
                if len(parts) == 3 and parts[0] == "tasks":
                    task = store.get(parts[1]); action = parts[2]
                    if action == "approve" and task["status"] == "WAITING_APPROVAL":
                        updated = store.transition(task["id"], "READY", "TASK_APPROVED",
                                                   expected_status=task["status"], approval="APPROVED")
                        return self._json(200, updated) if updated else self._json(409, {"error": "task status changed"})
                    if action == "reject" and task["status"] == "WAITING_APPROVAL":
                        updated = store.transition(task["id"], "REJECTED", "TASK_REJECTED",
                                                   expected_status=task["status"], approval="REJECTED")
                        return self._json(200, updated) if updated else self._json(409, {"error": "task status changed"})
                    if action == "cancel" and task["status"] not in TERMINAL | {"RUNNING"}:
                        updated = store.transition(task["id"], "CANCELLED", "TASK_CANCELLED",
                                                   expected_status=task["status"])
                        return self._json(200, updated) if updated else self._json(409, {"error": "task status changed"})
                    if action == "outcome" and task["status"] == "SUCCEEDED":
                        if not isinstance(body.get("passed"), bool):
                            raise ValueError("passed must be a JSON boolean")
                        lesson = store.add_lesson(task["id"], body["summary"], body["passed"])
                        return self._json(201, {"lesson_id": lesson})
                    return self._json(409, {"error": "action invalid for current state"})
                return self._json(404, {"error": "not found"})
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})

        def log_message(self, *_):
            return
    return Handler


def serve(store: Store, host="127.0.0.1", port=8765, worker_status=None, on_bound=None):
    try:
        parsed_host = None if host.lower() == "localhost" else ip_address(host)
        loopback = parsed_host is None or parsed_host.is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError("Jarvis binds to loopback only; use a TLS private tunnel terminating on localhost")
    server_type = LoopbackHTTPServerV6 if parsed_host is not None and parsed_host.version == 6 else LoopbackHTTPServer
    server = server_type((host, port), handler_for(store, worker_status))
    try:
        if on_bound:
            on_bound()
        server.serve_forever()
    finally:
        server.server_close()
