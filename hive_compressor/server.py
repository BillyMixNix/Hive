"""Zero-extra-dependency HTTP API for the Hive Compressor MVP."""

from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .auth import auth_required, configured_hashes, validate_api_key
from .compressor import CompressionError, compress_records
from .metering import UsageMeter


MAX_BODY_BYTES = int(os.getenv("HIVE_MAX_BODY_BYTES", str(5 * 1024 * 1024)))
DB_PATH = os.getenv("HIVE_USAGE_DB", "hive_usage.db")
METER = UsageMeter(DB_PATH)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "HiveCompressor/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authenticate(self) -> tuple[bool, str | None]:
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else None
        ok, identity = validate_api_key(token)
        if not ok:
            self._send(401, {"error": "unauthorized"})
        return ok, identity

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/health":
            ready = (not auth_required()) or bool(configured_hashes())
            self._send(200 if ready else 503, {
                "status": "ok" if ready else "not_ready",
                "service": "hive-compressor",
                "version": "0.1.0",
                "auth_required": auth_required(),
            })
            return

        if self.path == "/v1/usage":
            ok, key_hash = self._authenticate()
            if not ok or not key_hash:
                return
            self._send(200, {"usage": METER.summary(key_hash)})
            return

        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/compress":
            self._send(404, {"error": "not_found"})
            return

        ok, key_hash = self._authenticate()
        if not ok or not key_hash:
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "invalid_content_length"})
            return

        if content_length <= 0:
            self._send(400, {"error": "empty_body"})
            return
        if content_length > MAX_BODY_BYTES:
            self._send(413, {"error": "request_too_large", "max_bytes": MAX_BODY_BYTES})
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "invalid_json"})
            return

        if not isinstance(payload, dict):
            self._send(400, {"error": "body_must_be_object"})
            return

        records = payload.get("records")
        mode = payload.get("mode", "c1")
        if not isinstance(records, list):
            self._send(400, {"error": "records_must_be_array"})
            return

        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        try:
            result = compress_records(records, mode=mode)
        except CompressionError as exc:
            self._send(422, {"error": "compression_contract_failed", "detail": str(exc)})
            return
        latency_ms = (time.perf_counter() - start) * 1000.0

        METER.record(request_id, key_hash, result, latency_ms)
        result["request_id"] = request_id
        result["stats"]["latency_ms"] = round(latency_ms, 3)
        self._send(200, result)


def run() -> None:
    host = os.getenv("HIVE_HOST", "127.0.0.1")
    port = int(os.getenv("HIVE_PORT", "8787"))
    if auth_required() and not configured_hashes():
        raise SystemExit(
            "HIVE_API_KEY_SHA256 is required. Generate a key with: "
            "python -m hive_compressor.keygen"
        )
    print(f"Hive Compressor listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()
