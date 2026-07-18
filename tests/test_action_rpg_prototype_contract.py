from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from twin_realms.frontend_server import FrontendSession, make_handler


def test_frontend_session_connects_action_shell_to_backend_combat():
    session = FrontendSession(scenario="core")

    start = session.world_state()
    move = next(
        command
        for command in start["available_player_commands"]
        if command["command"] == "move"
        and command["intent"]["destination_id"] == "loc:den"
    )
    moved = session.submit(move)
    attack = next(
        command
        for command in moved["world_state"]["available_player_commands"]
        if command["command"] == "attack"
    )
    attacked = session.submit(attack)

    assert moved["accepted"] is True
    assert moved["world_state"]["entities"]["char:player"]["location_id"] == "loc:den"
    assert attacked["accepted"] is True
    assert attacked["events"][0]["animation"] == "attack"
    assert attacked["events"][0]["combat"]["damage"] > 0
    assert attacked["world_state"]["entities"]["char:hostile"]["health"] < 48
    assert session.boundary.engine.verify_replay()


def test_frontend_http_server_exposes_state_and_validated_commands():
    session = FrontendSession(scenario="core")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        state = _request(port, "GET", "/state")
        move = next(
            command
            for command in state["available_player_commands"]
            if command["command"] == "move"
            and command["intent"]["destination_id"] == "loc:den"
        )
        moved = _request(port, "POST", "/command", move)
        invalid = _request(port, "POST", "/command", {"command": "spawn_gold"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert state["schema"] == "twin_realms.frontend.v1"
    assert moved["accepted"] is True
    assert moved["world_state"]["entities"]["char:player"]["location_id"] == "loc:den"
    assert invalid["accepted"] is False
    assert invalid["events"][0]["animation"] == "reject"


def _request(port, method, path, payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    conn.close()
    assert response.status == 200
    return data
