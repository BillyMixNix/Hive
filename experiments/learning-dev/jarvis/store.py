from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TERMINAL = {"SUCCEEDED", "FAILED", "REJECTED", "CANCELLED"}
MAX_LESSON_BYTES = 4_096
MAX_GUIDANCE_BYTES = 64_000
REQUEST_FIELDS = ("id", "kind", "goal", "workspace", "payload", "mutating", "max_attempts")
STATE_FIELDS = (
    "id", "created_at", "updated_at", "status", "kind", "goal", "workspace",
    "payload", "mutating", "approval", "attempts", "max_attempts", "lease_until",
    "result", "error", "checkpoint",
)
LESSON_STATE_FIELDS = (
    "id", "created_at", "task_id", "status", "summary", "successes", "failures",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def _init(self):
        with self.connect() as db:
            had_meta_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_meta'"
            ).fetchone() is not None
            schema = """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              status TEXT NOT NULL, kind TEXT NOT NULL, goal TEXT NOT NULL,
              workspace TEXT NOT NULL, payload TEXT NOT NULL, mutating INTEGER NOT NULL,
              approval TEXT NOT NULL DEFAULT 'NOT_REQUIRED', attempts INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 2, lease_until TEXT,
              result TEXT, error TEXT, checkpoint TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              timestamp TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL,
              previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
              FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS lessons (
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task_id TEXT NOT NULL,
              status TEXT NOT NULL, summary TEXT NOT NULL, evidence_event INTEGER NOT NULL,
              successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ledger_anchor (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              event_count INTEGER NOT NULL, head_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_meta (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at
              ON tasks(status, created_at);
            """
            if not had_meta_table:
                schema += "INSERT OR IGNORE INTO runtime_meta(key,value) VALUES('migration_state','in_progress');\n"
            schema += "COMMIT;"
            db.executescript(schema)
            migration = db.execute(
                "SELECT value FROM runtime_meta WHERE key='migration_state'"
            ).fetchone()
            if migration and migration["value"] == "in_progress":
                self._resume_v3_migration(db)
            db.execute("PRAGMA optimize")

    def _resume_v3_migration(self, db) -> None:
        """Atomically anchor and bind a legacy database; safe to retry after a crash."""
        db.execute("BEGIN IMMEDIATE")
        migration = db.execute(
            "SELECT value FROM runtime_meta WHERE key='migration_state'"
        ).fetchone()
        if not migration or migration["value"] != "in_progress":
            db.rollback()
            return
        valid, _, previous, count, bound_states, _, events = self._scan_events(db)
        tasks_ok, _ = self._verify_legacy_tasks(db, events)
        lessons_ok, _ = self._verify_lessons(db, events, require_bindings=False)
        if not valid or not tasks_ok or not lessons_ok:
            db.rollback()
            return
        anchor = db.execute(
            "SELECT event_count,head_hash FROM ledger_anchor WHERE singleton=1"
        ).fetchone()
        if anchor:
            if anchor["event_count"] != count or anchor["head_hash"] != previous:
                db.rollback()
                return
        else:
            db.execute(
                "INSERT INTO ledger_anchor(singleton,event_count,head_hash) VALUES(1,?,?)",
                (count, previous),
            )
        for row in db.execute("SELECT id FROM tasks ORDER BY created_at,id").fetchall():
            if row["id"] not in bound_states:
                self._event(db, row["id"], "TASK_STATE_BOUND", {
                    "migration": "v0.3", "legacy_history": True,
                })
        bound_lessons = {
            data.get("lesson_id")
            for row, data in events.values()
            if row["type"] in {"OUTCOME_RECORDED", "LESSON_STATE_BOUND"}
            and isinstance(data.get("lesson_digest"), str)
            and isinstance(data.get("lesson_id"), str)
        }
        for row in db.execute("SELECT * FROM lessons ORDER BY created_at,id").fetchall():
            lesson = dict(row)
            if lesson["id"] not in bound_lessons:
                self._event(db, lesson["task_id"], "LESSON_STATE_BOUND", {
                    "migration": "v0.3", "legacy_history": True,
                    "lesson_id": lesson["id"],
                    "evidence_event": lesson["evidence_event"],
                    "lesson_digest": self._digest(lesson, LESSON_STATE_FIELDS),
                })
        changed = db.execute(
            "UPDATE runtime_meta SET value='complete' WHERE key='migration_state' AND value='in_progress'"
        )
        if changed.rowcount != 1:
            raise RuntimeError("schema migration state changed unexpectedly")

    @contextmanager
    def worker_lock(self):
        """Hold a non-blocking, process-wide lock for a daemon or one-shot worker."""
        lock_path = Path(f"{self.path}.worker.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0"); handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f"another Jarvis worker is already using {self.path}") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @staticmethod
    def _canonical_task(row) -> dict[str, Any]:
        task = dict(row)
        for key in ("payload", "result", "checkpoint"):
            if task.get(key) and isinstance(task[key], str):
                task[key] = json.loads(task[key])
        task["mutating"] = bool(task["mutating"])
        return task

    @staticmethod
    def _digest(task: dict[str, Any], fields: tuple[str, ...]) -> str:
        body = json.dumps(
            {field: task.get(field) for field in fields},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _scan_events(self, db):
        previous = "GENESIS"
        count = 0
        bound_states: dict[str, str] = {}
        event_task_ids: set[str] = set()
        events: dict[int, tuple[Any, dict[str, Any]]] = {}
        try:
            for row in db.execute("SELECT * FROM events ORDER BY seq"):
                data = json.loads(row["data"])
                if not isinstance(data, dict):
                    return False, f"invalid data at event {row['seq']}", previous, count, bound_states, event_task_ids, events
                body = json.dumps({
                    "task_id": row["task_id"], "timestamp": row["timestamp"],
                    "type": row["type"], "data": data, "previous_hash": previous,
                }, sort_keys=True, separators=(",", ":"))
                expected = hashlib.sha256(body.encode()).hexdigest()
                if row["previous_hash"] != previous or row["hash"] != expected:
                    return False, f"broken at event {row['seq']}", previous, count, bound_states, event_task_ids, events
                if isinstance(data.get("state_digest"), str):
                    bound_states[row["task_id"]] = data["state_digest"]
                event_task_ids.add(row["task_id"])
                events[int(row["seq"])] = (row, data)
                previous = row["hash"]
                count += 1
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return False, f"malformed evidence ledger: {exc}", previous, count, bound_states, event_task_ids, events
        return True, "verified", previous, count, bound_states, event_task_ids, events

    @staticmethod
    def _verify_legacy_tasks(db, events) -> tuple[bool, str]:
        """Reconcile unanchored legacy rows with their semantic event history."""
        tasks = {row["id"]: dict(row) for row in db.execute("SELECT * FROM tasks")}
        status_by_task: dict[str, str] = {}
        created: set[str] = set()
        for _, (row, data) in events.items():
            task_id = row["task_id"]
            task = tasks.get(task_id)
            if not task:
                return False, f"legacy event references missing task {task_id}"
            if row["type"] == "TASK_CREATED":
                if task_id in created:
                    return False, f"duplicate TASK_CREATED evidence for {task_id}"
                initial_status = data.get("status")
                if not isinstance(initial_status, str):
                    return False, f"TASK_CREATED status missing for {task_id}"
                if (
                    data.get("kind") != task["kind"]
                    or data.get("goal") != task["goal"]
                    or not isinstance(data.get("mutating"), bool)
                    or data["mutating"] != bool(task["mutating"])
                ):
                    return False, f"TASK_CREATED request mismatch for {task_id}"
                created.add(task_id)
                status_by_task[task_id] = initial_status
                continue
            if task_id not in created:
                return False, f"TASK_CREATED evidence missing before event for {task_id}"
            has_from = "from" in data
            has_to = "to" in data
            if has_from or has_to:
                if not isinstance(data.get("from"), str) or not isinstance(data.get("to"), str):
                    return False, f"invalid status transition evidence for {task_id}"
                if status_by_task[task_id] != data["from"]:
                    return False, f"discontinuous status history for {task_id}"
                status_by_task[task_id] = data["to"]
        missing = set(tasks) - created
        if missing:
            return False, f"TASK_CREATED evidence missing for {sorted(missing)[0]}"
        for task_id, task in tasks.items():
            if status_by_task.get(task_id) != task["status"]:
                return False, f"legacy task status mismatch for {task_id}"
        return True, "verified"

    def _verify_lessons(self, db, events, *, require_bindings: bool) -> tuple[bool, str]:
        lessons = [dict(row) for row in db.execute("SELECT * FROM lessons")]
        task_status = {row["id"]: row["status"] for row in db.execute("SELECT id,status FROM tasks")}
        lesson_ids = {lesson["id"] for lesson in lessons}
        if len(lesson_ids) != len(lessons):
            return False, "duplicate lesson id"
        outcome_events = {
            seq: (row, data) for seq, (row, data) in events.items()
            if row["type"] == "OUTCOME_RECORDED"
        }
        bindings: dict[str, tuple[int, Any, dict[str, Any]]] = {}
        for seq, (row, data) in events.items():
            if row["type"] not in {"OUTCOME_RECORDED", "LESSON_STATE_BOUND"}:
                continue
            lesson_id = data.get("lesson_id")
            if isinstance(lesson_id, str) and isinstance(data.get("lesson_digest"), str):
                bindings[lesson_id] = (seq, row, data)
        used_outcomes: set[int] = set()
        used_evidence: set[int] = set()
        for lesson in lessons:
            if task_status.get(lesson["task_id"]) != "SUCCEEDED":
                return False, f"lesson source task is not succeeded for {lesson['id']}"
            evidence = lesson["evidence_event"]
            if not isinstance(evidence, int) or evidence in used_evidence:
                return False, f"invalid or duplicate evidence event for lesson {lesson['id']}"
            used_evidence.add(evidence)
            outcome = outcome_events.get(evidence)
            if not outcome:
                return False, f"outcome evidence missing for lesson {lesson['id']}"
            outcome_row, outcome_data = outcome
            used_outcomes.add(evidence)
            passed = outcome_data.get("passed")
            if not isinstance(passed, bool):
                return False, f"outcome verdict invalid for lesson {lesson['id']}"
            if outcome_row["task_id"] != lesson["task_id"] or outcome_data.get("summary") != lesson["summary"]:
                return False, f"lesson evidence mismatch for {lesson['id']}"
            successes = lesson["successes"]
            failures = lesson["failures"]
            if (
                not isinstance(successes, int) or isinstance(successes, bool) or successes < 0
                or not isinstance(failures, int) or isinstance(failures, bool) or failures < 0
            ):
                return False, f"lesson counters invalid for {lesson['id']}"
            if passed:
                state_valid = lesson["status"] in {"CANDIDATE", "TRUSTED"} and successes >= 1 and failures >= 0
            else:
                state_valid = lesson["status"] == "RETIRED" and failures >= 1 and successes >= 0
            if not state_valid:
                return False, f"lesson verdict state mismatch for {lesson['id']}"
            if require_bindings:
                binding = bindings.get(lesson["id"])
                if not binding:
                    return False, f"lesson state binding missing for {lesson['id']}"
                binding_seq, binding_row, binding_data = binding
                bound_evidence = binding_seq if binding_row["type"] == "OUTCOME_RECORDED" else binding_data.get("evidence_event")
                if binding_row["task_id"] != lesson["task_id"] or bound_evidence != evidence:
                    return False, f"lesson binding mismatch for {lesson['id']}"
                try:
                    expected_digest = self._digest(lesson, LESSON_STATE_FIELDS)
                except (TypeError, ValueError) as exc:
                    return False, f"invalid state for lesson {lesson['id']}: {exc}"
                if not hmac.compare_digest(binding_data["lesson_digest"], expected_digest):
                    return False, f"lesson state mismatch for {lesson['id']}"
        unmatched_outcomes = set(outcome_events) - used_outcomes
        if unmatched_outcomes:
            return False, f"outcome event {min(unmatched_outcomes)} has no lesson"
        if require_bindings:
            unmatched_bindings = set(bindings) - lesson_ids
            if unmatched_bindings:
                return False, f"bound lesson {sorted(unmatched_bindings)[0]} is missing"
        return True, "verified"

    def _event(self, db, task_id: str, event_type: str, data: dict[str, Any]) -> int:
        last = db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last["hash"] if last else "GENESIS"
        stamp = now()
        bound_data = dict(data)
        task_row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task_row:
            task = self._canonical_task(task_row)
            bound_data.update({
                "binding_version": 1,
                "request_digest": self._digest(task, REQUEST_FIELDS),
                "state_digest": self._digest(task, STATE_FIELDS),
            })
        body = json.dumps({"task_id": task_id, "timestamp": stamp, "type": event_type,
                           "data": bound_data, "previous_hash": previous}, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode()).hexdigest()
        cur = db.execute("INSERT INTO events(task_id,timestamp,type,data,previous_hash,hash) VALUES(?,?,?,?,?,?)",
                         (task_id, stamp, event_type, json.dumps(bound_data, sort_keys=True), previous, digest))
        anchor = db.execute(
            "UPDATE ledger_anchor SET event_count=event_count+1,head_hash=? WHERE singleton=1",
            (digest,),
        )
        if anchor.rowcount != 1:
            raise RuntimeError("evidence ledger anchor is missing")
        return int(cur.lastrowid)

    def create(self, *, kind: str, goal: str, workspace: str, payload: dict[str, Any],
               mutating: bool, max_attempts: int = 2) -> dict[str, Any]:
        if not isinstance(kind, str) or kind not in {"inspect", "command", "agent"}:
            raise ValueError(f"unsupported task kind: {kind}")
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 100_000:
            raise ValueError("goal must be a non-empty string of at most 100000 characters")
        if not isinstance(workspace, str) or not workspace:
            raise ValueError("workspace must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        if not isinstance(mutating, bool):
            raise ValueError("mutating must be a boolean")
        if kind == "command" and not mutating:
            raise ValueError("command tasks are always mutating and require approval")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts must be an integer between 1 and 100")
        if "timeout" in payload:
            timeout = payload["timeout"]
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86_400:
                raise ValueError("payload timeout must be an integer between 1 and 86400")
        if kind == "inspect" and "max_files" in payload:
            max_files = payload["max_files"]
            if not isinstance(max_files, int) or isinstance(max_files, bool) or not 1 <= max_files <= 100_000:
                raise ValueError("inspect max_files must be an integer between 1 and 100000")
        task_id = uuid.uuid4().hex[:12]
        stamp = now()
        status = "WAITING_APPROVAL" if mutating else "READY"
        approval = "PENDING" if mutating else "NOT_REQUIRED"
        root = str(Path(workspace).expanduser().resolve())
        with self._lock, self.connect() as db:
            db.execute("INSERT INTO tasks(id,created_at,updated_at,status,kind,goal,workspace,payload,mutating,approval,max_attempts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (task_id, stamp, stamp, status, kind, goal, root, json.dumps(payload), int(mutating), approval, max_attempts))
            self._event(db, task_id, "TASK_CREATED", {"status": status, "kind": kind, "goal": goal, "mutating": mutating})
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            return self._decode(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._decode(r) for r in rows]

    def overview(self) -> dict[str, Any]:
        """Return complete queue counts plus every nonterminal task for the Cockpit."""
        with self.connect() as db:
            db.execute("BEGIN")
            counts = {
                row["status"]: row["count"]
                for row in db.execute(
                    "SELECT status,COUNT(*) AS count FROM tasks GROUP BY status"
                )
            }
            placeholders = ",".join("?" for _ in TERMINAL)
            rows = db.execute(
                f"SELECT * FROM tasks WHERE status NOT IN ({placeholders}) ORDER BY created_at",
                tuple(sorted(TERMINAL)),
            ).fetchall()
            return {
                "total": sum(counts.values()),
                "by_status": counts,
                "nonterminal": [self._decode(row) for row in rows],
            }

    @staticmethod
    def _decode(row):
        return Store._canonical_task(row)

    def transition(self, task_id: str, status: str, event_type: str, data: dict[str, Any] | None = None,
                   *, expected_status: str | None = None, expected_attempt: int | None = None, **fields):
        data = data or {}
        allowed = {"approval", "result", "error", "checkpoint", "lease_until", "attempts"}
        if set(fields) - allowed:
            raise ValueError("unsupported task fields")
        encoded = {k: json.dumps(v) if k in {"result", "checkpoint"} and v is not None else v for k, v in fields.items()}
        encoded.update(status=status, updated_at=now())
        assignments = ",".join(f"{k}=?" for k in encoded)
        with self._lock, self.connect() as db:
            row = db.execute("SELECT status,attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            if expected_status is not None and row["status"] != expected_status:
                return None
            if expected_attempt is not None and row["attempts"] != expected_attempt:
                return None
            conditions = ["id=?"]
            predicates: list[Any] = [task_id]
            if expected_status is not None:
                conditions.append("status=?"); predicates.append(expected_status)
            if expected_attempt is not None:
                conditions.append("attempts=?"); predicates.append(expected_attempt)
            where = " AND ".join(conditions)
            values = (*encoded.values(), *predicates)
            changed = db.execute(f"UPDATE tasks SET {assignments} WHERE {where}", values)
            if changed.rowcount != 1:
                return None
            self._event(db, task_id, event_type, {"from": row["status"], "to": status, **data})
        return self.get(task_id)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE task_id=? ORDER BY seq", (task_id,)).fetchall()
            out = []
            for row in rows:
                item = dict(row); item["data"] = json.loads(item["data"]); out.append(item)
            return out

    def _verify_chain_db(self, db) -> tuple[bool, str]:
        migration = db.execute(
            "SELECT value FROM runtime_meta WHERE key='migration_state'"
        ).fetchone()
        if not migration or migration["value"] != "complete":
            return False, "schema migration is incomplete"
        valid, detail, previous, count, bound_states, event_task_ids, events = self._scan_events(db)
        if not valid:
            return False, detail
        anchor = db.execute(
            "SELECT event_count,head_hash FROM ledger_anchor WHERE singleton=1"
        ).fetchone()
        if not anchor:
            return False, "ledger anchor missing"
        if anchor["event_count"] != count or anchor["head_hash"] != previous:
            return False, "ledger anchor mismatch"
        task_ids = {row["id"] for row in db.execute("SELECT id FROM tasks")}
        orphaned = event_task_ids - task_ids
        if orphaned:
            return False, f"event task {sorted(orphaned)[0]} is missing"
        unbound = task_ids - set(bound_states)
        if unbound:
            return False, f"task state binding missing for {sorted(unbound)[0]}"
        for task_id, expected_state in bound_states.items():
            task_row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task_row:
                return False, f"bound task {task_id} is missing"
            try:
                actual_state = self._digest(self._canonical_task(task_row), STATE_FIELDS)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return False, f"invalid state for task {task_id}: {exc}"
            if not hmac.compare_digest(actual_state, expected_state):
                return False, f"task state mismatch for {task_id}"
        lessons_ok, lessons_detail = self._verify_lessons(db, events, require_bindings=True)
        if not lessons_ok:
            return False, lessons_detail
        return True, previous

    def verify_chain(self) -> tuple[bool, str]:
        with self.connect() as db:
            db.execute("BEGIN")
            return self._verify_chain_db(db)

    def _request_binding(self, db, task: dict[str, Any]) -> tuple[bool, str]:
        event_type = "TASK_APPROVED" if task["mutating"] else "TASK_CREATED"
        row = db.execute(
            "SELECT data FROM events WHERE task_id=? AND type=? ORDER BY seq DESC LIMIT 1",
            (task["id"], event_type),
        ).fetchone()
        data = None
        try:
            if row:
                data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            data = None
        expected = data.get("request_digest") if isinstance(data, dict) else None
        if not isinstance(expected, str) and not task["mutating"]:
            migrated = db.execute(
                "SELECT data FROM events WHERE task_id=? AND type='TASK_STATE_BOUND' ORDER BY seq DESC LIMIT 1",
                (task["id"],),
            ).fetchone()
            try:
                migration_data = json.loads(migrated["data"]) if migrated else None
            except (json.JSONDecodeError, TypeError):
                migration_data = None
            if (
                isinstance(migration_data, dict)
                and migration_data.get("migration") == "v0.3"
                and migration_data.get("legacy_history") is True
                and isinstance(migration_data.get("request_digest"), str)
            ):
                expected = migration_data["request_digest"]
        actual = self._digest(task, REQUEST_FIELDS)
        if not isinstance(expected, str):
            return False, f"{event_type} evidence is missing or predates request binding"
        if not hmac.compare_digest(expected, actual):
            return False, "the task request changed after authorization"
        return True, actual

    def recover(self, *, force: bool = False):
        stamp = now()
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if force:
                rows = db.execute(
                    "SELECT id,mutating,attempts,max_attempts FROM tasks WHERE status='RUNNING'"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id,mutating,attempts,max_attempts FROM tasks "
                    "WHERE status='RUNNING' AND (lease_until IS NULL OR lease_until<=?)",
                    (stamp,),
                ).fetchall()
            for row in rows:
                exhausted = row["attempts"] >= row["max_attempts"]
                status = "FAILED" if exhausted else ("WAITING_APPROVAL" if row["mutating"] else "READY")
                approval = ("EXPIRED" if row["mutating"] else "NOT_REQUIRED") if exhausted else (
                    "PENDING_RESTART" if row["mutating"] else "NOT_REQUIRED"
                )
                reason = (
                    "worker stopped during the final allowed attempt; outcome is uncertain"
                    if exhausted else
                    "mutation outcome uncertain; fresh approval required"
                    if row["mutating"] else
                    "worker restart" if force else "expired lease"
                )
                checkpoint = {"stage": "terminal" if exhausted else "recovered", "attempt": row["attempts"]}
                db.execute(
                    "UPDATE tasks SET status=?,approval=?,lease_until=NULL,updated_at=?,error=?,checkpoint=? WHERE id=?",
                    (status, approval, stamp, reason, json.dumps(checkpoint), row["id"]),
                )
                self._event(db, row["id"], "TASK_FAILED" if exhausted else "TASK_RECOVERED", {
                    "from": "RUNNING", "to": status,
                    "reason": reason,
                    "attempt": row["attempts"],
                })
        return len(rows)

    def claim_ready(self):
        """Atomically lease the oldest ready task across threads and processes."""
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            while True:
                row = db.execute(
                    "SELECT * FROM tasks WHERE status='READY' AND attempts<max_attempts ORDER BY created_at LIMIT 1"
                ).fetchone()
                if not row:
                    return None
                task = self._decode(row)
                bound, detail = self._request_binding(db, task)
                if bound:
                    break
                stamp = now()
                status = "WAITING_APPROVAL" if task["mutating"] else "FAILED"
                approval = "PENDING_CHANGED" if task["mutating"] else task["approval"]
                checkpoint = {"stage": "authorization_invalid", "attempt": task["attempts"]}
                db.execute(
                    "UPDATE tasks SET status=?,approval=?,updated_at=?,error=?,checkpoint=? WHERE id=? AND status='READY'",
                    (status, approval, stamp, detail, json.dumps(checkpoint), task["id"]),
                )
                self._event(db, task["id"], "TASK_APPROVAL_INVALIDATED", {
                    "from": "READY", "to": status, "reason": detail,
                })
            attempt = task["attempts"] + 1
            try:
                timeout = int(task["payload"].get("timeout", 900))
            except (AttributeError, OverflowError, TypeError, ValueError):
                timeout = 900
            timeout = max(1, min(timeout, 86_400))
            # Cover the adapter's bounded preflight and cleanup slack as well as
            # the model deadline. Startup recovery still force-recovers under the
            # single-worker process lock.
            lease = (datetime.now(timezone.utc) + timedelta(seconds=timeout + 180)).isoformat()
            stamp = now()
            changed = db.execute(
                "UPDATE tasks SET status='RUNNING',updated_at=?,attempts=?,lease_until=?,checkpoint=? "
                "WHERE id=? AND status='READY'",
                (stamp, attempt, lease, json.dumps({"stage": "executing", "attempt": attempt}), task["id"]),
            )
            if changed.rowcount != 1:
                return None
            self._event(db, task["id"], "TASK_STARTED", {
                "from": "READY", "to": "RUNNING", "attempt": attempt,
            })
        return self.get(task["id"])

    def ready(self):
        """Return the next ready task without claiming it (introspection only)."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE status='READY' ORDER BY created_at LIMIT 1").fetchone()
            return self._decode(row) if row else None

    def add_lesson(self, task_id: str, summary: str, passed: bool):
        if not isinstance(summary, str) or not summary.strip() or len(summary.encode("utf-8")) > MAX_LESSON_BYTES:
            raise ValueError(f"lesson summary must be non-empty and at most {MAX_LESSON_BYTES} UTF-8 bytes")
        if not isinstance(passed, bool):
            raise ValueError("passed must be a boolean")
        lesson_id = uuid.uuid4().hex[:12]
        stamp = now()
        status = "CANDIDATE" if passed else "RETIRED"
        successes = int(passed)
        failures = int(not passed)
        lesson = {
            "id": lesson_id, "created_at": stamp, "task_id": task_id,
            "status": status, "summary": summary,
            "successes": successes, "failures": failures,
        }
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger_ok, detail = self._verify_chain_db(db)
            if not ledger_ok:
                raise RuntimeError(f"evidence ledger verification failed: {detail}")
            task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                raise KeyError(task_id)
            if task["status"] != "SUCCEEDED":
                raise ValueError("outcomes require a succeeded task")
            event = self._event(db, task_id, "OUTCOME_RECORDED", {
                "passed": passed, "summary": summary,
                "lesson_id": lesson_id, "lesson_created_at": stamp,
                "lesson_status": status, "successes": successes, "failures": failures,
                "lesson_digest": self._digest(lesson, LESSON_STATE_FIELDS),
            })
            db.execute("INSERT INTO lessons(id,created_at,task_id,status,summary,evidence_event,successes,failures) VALUES(?,?,?,?,?,?,?,?)",
                       (lesson_id, stamp, task_id, status, summary, event, successes, failures))
        return lesson_id

    def lessons(self):
        with self.connect() as db:
            db.execute("BEGIN")
            rows = [dict(r) for r in db.execute("SELECT * FROM lessons ORDER BY created_at DESC")]
            ok, detail = self._verify_chain_db(db)
            if not ok:
                # Preserve v0.3's diagnostic view of human-entered rows. Never
                # present machine promotions as verified from a broken chain.
                # guidance() independently rejects all reuse in this state.
                return rows
            from hive_learning.ledger import bank
            rows.extend(dict(item, successes=1, failures=0) for item in bank(db))
            return rows

    def guidance(self, goal: str = "", limit: int = 20, *, learning_scope="development_real_model"):
        with self.connect() as db:
            db.execute("BEGIN")
            ledger_ok, detail = self._verify_chain_db(db)
            if not ledger_ok:
                raise RuntimeError(f"evidence ledger verification failed: {detail}")
            rows = db.execute(
                "SELECT id,status,summary,successes,failures FROM lessons "
                "WHERE status IN ('CANDIDATE','TRUSTED') ORDER BY successes DESC,created_at DESC LIMIT 500"
            ).fetchall()
            # Machine promotions have their own event type; never manufacture a
            # human OUTCOME_RECORDED event or treat an untested proposal as guidance.
            from hive_learning.ledger import bank
            rows = [dict(row) for row in rows]
            rows.extend(dict(item, successes=1, failures=0)
                        for item in bank(db, learning_scope))
            goal_terms = set(re.findall(r"[a-z0-9_]{3,}", goal.lower()))
            ranked = sorted(
                rows,
                key=lambda row: (
                    len(goal_terms & set(re.findall(r"[a-z0-9_]{3,}", row["summary"].lower()))),
                    row["successes"],
                ),
                reverse=True,
            )
            result = []
            used = 0
            for row in ranked:
                item = dict(row)
                size = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                if size > MAX_LESSON_BYTES + 1_000 or used + size > MAX_GUIDANCE_BYTES:
                    continue
                result.append(item); used += size
                if len(result) >= limit:
                    break
            return result
