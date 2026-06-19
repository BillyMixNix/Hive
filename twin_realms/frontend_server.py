from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .content import build_core_loop_world
from .engine import TwinRealmsEngine
from .frontend_boundary import FrontendBoundary
from .runtime import TwinRealmsRuntime
from .tarrow import build_tarrow_aftermath_world


class FrontendSession:
    """Stateful HTTP-facing session for lightweight game clients."""

    def __init__(self, scenario="core"):
        self.scenario = scenario
        self.boundary = self._new_boundary(scenario)

    def reset(self, scenario=None):
        self.scenario = scenario or self.scenario
        self.boundary = self._new_boundary(self.scenario)
        return self.world_state()

    def world_state(self):
        return self.boundary.export_world_state()

    def submit(self, command):
        return self.boundary.submit_player_intention(command)

    @staticmethod
    def _new_boundary(scenario):
        if scenario == "core":
            state = build_core_loop_world()
        elif scenario == "tarrow":
            state = build_tarrow_aftermath_world()
        else:
            raise ValueError(f"unsupported frontend scenario: {scenario}")
        return FrontendBoundary(
            TwinRealmsRuntime(TwinRealmsEngine(state), mode="baseline")
        )


def make_handler(session):
    class FrontendRequestHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self._send_json({"ok": True})

        def do_GET(self):
            if self.path == "/health":
                self._send_json({"ok": True, "scenario": session.scenario})
                return
            if self.path == "/state":
                self._send_json(session.world_state())
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            payload = self._read_json()
            try:
                if self.path == "/new":
                    self._send_json(session.reset(payload.get("scenario")))
                    return
                if self.path == "/command":
                    self._send_json(session.submit(payload))
                    return
                self._send_json({"error": "not found"}, status=404)
            except (TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)

        def log_message(self, _format, *_args):
            return

        def _read_json(self):
            length = int(self.headers.get("content-length") or 0)
            if length == 0:
                return {}
            data = self.rfile.read(length).decode("utf-8")
            return json.loads(data)

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.end_headers()
            self.wfile.write(body)

    return FrontendRequestHandler


def run_server(host="127.0.0.1", port=8765, scenario="core"):
    session = FrontendSession(scenario=scenario)
    server = ThreadingHTTPServer((host, port), make_handler(session))
    print(f"Twin Realms frontend server listening on http://{host}:{port}")
    print("Endpoints: GET /state, POST /command, POST /new")
    server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Serve Twin Realms state for a 3D frontend prototype."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scenario", choices=["core", "tarrow"], default="core")
    args = parser.parse_args(argv)
    run_server(args.host, args.port, args.scenario)


if __name__ == "__main__":
    main()
