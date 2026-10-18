"""Offline wiring demonstration. Responses and lesson are scripted fixtures.

PROMOTED in development_simulated scope is never real-model learning evidence.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from jarvis.store import Store
from jarvis.supervisor import Supervisor
from .evaluate import write_files
from .loop import run


LESSON = {"when": "An inclusive capacity boundary is rejected at equality.",
          "summary": "Check equality explicitly when a limit is inclusive; a strict comparison excludes the boundary.",
          "rationale": "The observed failure rejects an input exactly at the declared maximum."}


def suite():
    return {"schema": "hive.learning.suite.v1", "suite_id": "scripted-wiring-only-v1", "cases": [
        {"id": "capacity", "split": "trigger", "goal": "Admit quantities up to and including capacity; preserve tests.",
         "files": {"capacity.py": "def admit(quantity, capacity):\n    return quantity < capacity\n",
                   "test_visible.py": "from capacity import admit\ndef test_below():\n    assert admit(3, 5)\n"},
         "protected_tests": {"test_protected.py": "from capacity import admit\ndef test_boundary():\n    assert admit(5, 5)\n    assert not admit(6, 5)\n"}},
        {"id": "deadline", "split": "transfer", "goal": "Accept arrivals at or before the deadline; preserve tests.",
         "files": {"arrival.py": "def on_time(arrived, deadline):\n    return arrived < deadline\n",
                   "test_visible.py": "from arrival import on_time\ndef test_before():\n    assert on_time(4, 10)\n"},
         "protected_tests": {"test_protected.py": "from arrival import on_time\ndef test_boundary():\n    assert on_time(10, 10)\n    assert not on_time(11, 10)\n"}},
        {"id": "signed_sum", "split": "retention", "goal": "Preserve correct addition of signed integers and existing tests.",
         "files": {"arithmetic.py": "def add(a, b):\n    return a + b\n",
                   "test_visible.py": "from arithmetic import add\ndef test_positive():\n    assert add(2, 3) == 5\n"},
         "protected_tests": {"test_protected.py": "from arithmetic import add\ndef test_signed():\n    assert add(-3, 2) == -1\n    assert add(0, 0) == 0\n"}},
    ]}


class ScriptedAdapter:
    identity = {"scope": "development_simulated", "transport": "scripted_fixture", "model": "none"}

    def propose(self, packet):
        assert packet["failure"]["error"]
        return dict(LESSON), {"calls": 1, "prompt_tokens": 0, "output_tokens": 0}

    def repair(self, root, goal, lessons, calls):
        # Intentionally scripted to exercise the loop; not autonomous inference.
        if any(item.get("summary") == LESSON["summary"] for item in lessons):
            for name in ("capacity.py", "arrival.py"):
                path = root / name
                if path.exists():
                    path.write_text(path.read_text().replace(" < ", " <= "))
        return {"calls": 1, "prompt_tokens": 0, "output_tokens": 0}


def seed_failure(store, root):
    root.mkdir()
    write_files(root, {"check.py": "def admit(n, cap):\n    return n < cap\nassert admit(5, 5), 'inclusive capacity rejects equality'\n"})
    task = store.create(kind="command", goal="Admit a quantity equal to capacity.", workspace=str(root),
                        payload={"command": [sys.executable, "check.py"]}, mutating=True, max_attempts=1)
    store.transition(task["id"], "READY", "TASK_APPROVED", expected_status="WAITING_APPROVAL", approval="APPROVED")
    Supervisor(store).run_once()
    assert store.get(task["id"])["status"] == "FAILED"
    return task["id"]


def main():
    with tempfile.TemporaryDirectory(prefix="hive-loop-demo-") as temp:
        root = Path(temp)
        store = Store(root / "state" / "jarvis.db")
        task_id = seed_failure(store, root / "failed-work")
        path = root / "suite.json"
        raw = json.dumps(suite(), indent=2).encode()
        path.write_bytes(raw)
        report = run(store, task_id, path, hashlib.sha256(raw).hexdigest(), ScriptedAdapter())
        reopened = Store(store.path)
        report["persisted_simulated_guidance"] = len(reopened.guidance(learning_scope="development_simulated"))
        report["ordinary_jarvis_guidance"] = len(reopened.guidance())
        report["ledger_verified"] = reopened.verify_chain()[0]
        report["interpretation"] = "Scripted integration verification only; no model inference or learning gain measured."
        print(json.dumps(report, indent=2))
        return 0 if report["verdict"] == "PROMOTED" and report["ledger_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
