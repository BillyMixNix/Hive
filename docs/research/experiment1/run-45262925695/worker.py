"""Untrusted-side adapter. No expected answers, thresholds, secrets, or scoring.

Every response is untrusted data; only the external controller awards correctness.
"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import resource
import socket
import sys
import time


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def main():
    mode = sys.argv[1]
    payload = json.load(sys.stdin)
    if mode == "hang":
        while True:
            pass
    if mode == "flood":
        while True:
            print("x" * 8192, flush=True)
    if mode == "oom":
        blocks = []
        while True:
            blocks.append(bytearray(8 * 1024**2))
    if mode == "probe":
        denied = {}
        for name, path in {"source": "/subject/planner.py", "harness": "/harness/worker.py",
                           "rootfs": "/etc/hive-probe"}.items():
            try:
                with open(path, "a") as stream:
                    stream.write("")
                denied[name] = False
            except OSError:
                denied[name] = True
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=1)
            denied["network"] = False
        except OSError:
            denied["network"] = True
        cgroup = Path("/sys/fs/cgroup")
        emit({"uid": os.getuid(), "denied": denied,
              "status": Path("/proc/self/status").read_text(),
              "memory_max": (cgroup / "memory.max").read_text().strip(),
              "pids_max": (cgroup / "pids.max").read_text().strip(),
              "cpu_max": (cgroup / "cpu.max").read_text().strip(),
              "docker_socket": Path("/var/run/docker.sock").exists(),
              "credentials": any(k in os.environ for k in ("GITHUB_TOKEN", "GH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"))})
        return
    sys.path.insert(0, "/subject")
    if mode == "syntax":
        ast.parse(Path("/subject/planner.py").read_text())
        emit({"syntax": True})
        return
    if mode == "pytest":
        import pytest
        os.chdir("/subject")
        raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider"]))
    if mode == "regressions":
        # Definitions and expectations stay with the controller. This side only calls.
        import importlib
        result = []
        for item in payload["calls"]:
            module = importlib.import_module(item["module"])
            cls = getattr(module, item["class"])
            obj = cls.__new__(cls)
            try:
                value = getattr(obj, item["method"])(*item["args"])
                result.append({"id": item["id"], "value": value})
            except Exception as exc:
                result.append({"id": item["id"], "error": type(exc).__name__})
        emit(result)
        return
    if mode != "extract":
        raise ValueError("Unknown worker mode")
    with contextlib.redirect_stdout(io.StringIO()):
        from planner import PlannerAgent
        obj = PlannerAgent.__new__(PlannerAgent)
    result = []
    for item in payload["inputs"]:
        started = time.perf_counter_ns()
        try:
            text = obj._extract_json_object(item["input"])
            elapsed = (time.perf_counter_ns() - started) / 1e6
            record = {"id": item["id"], "text": text}
        except Exception as exc:
            elapsed = (time.perf_counter_ns() - started) / 1e6
            record = {"id": item["id"], "error": type(exc).__name__}
        record["latency_ms_untrusted"] = elapsed
        result.append(record)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    emit({"responses": result, "cpu_seconds_untrusted": usage.ru_utime + usage.ru_stime})


if __name__ == "__main__":
    main()
