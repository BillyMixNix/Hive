"""Learning state lives in Jarvis's existing anchored event ledger."""
import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def history(db):
    return [dict(json.loads(row[0]), task_id=row[1], created_at=row[2]) for row in db.execute(
        "SELECT data,task_id,timestamp FROM events WHERE type='LEARNING_FINISHED' ORDER BY seq"
    )]


def bank(db, scope="development_real_model"):
    # Caller must verify the Jarvis chain in the same transaction first.
    retired = {json.loads(row[0])["episode_id"] for row in db.execute(
        "SELECT data FROM events WHERE type='LEARNING_RETIRED'"
    )}
    return [dict(item["lesson"], id=item["episode_id"], status="EXPERIMENT_VERIFIED",
                 evidence_scope=item["scope"], suite_sha256=item["suite_sha256"],
                 task_id=item["task_id"], created_at=item["created_at"])
            for item in history(db) if item["verdict"] == "PROMOTED" and item["scope"] == scope
            and item["episode_id"] not in retired]


def retire(store, episode_id, reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
        raise ValueError("retirement requires a bounded reason")
    with store._lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ok, detail = store._verify_chain_db(db)
        if not ok:
            raise RuntimeError(detail)
        matches = [item for item in history(db)
                   if item["episode_id"] == episode_id and item["verdict"] == "PROMOTED"]
        if not matches:
            raise ValueError("episode has no promoted lesson")
        return store._event(db, matches[0]["task_id"], "LEARNING_RETIRED", {
            "episode_id": episode_id, "reason": reason,
        })


def append(store, task_id, event_type, data):
    with store._lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ok, reason = store._verify_chain_db(db)
        if not ok:
            raise RuntimeError(reason)
        return store._event(db, task_id, event_type, data)


def finish(store, task_id, report, expected_parent):
    with store._lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ok, reason = store._verify_chain_db(db)
        if not ok:
            raise RuntimeError(reason)
        if digest(bank(db, report["scope"])) != expected_parent:
            report = dict(report, verdict="INVALID", reason="parent bank changed during episode")
        store._event(db, task_id, "LEARNING_FINISHED", report)
        return report


def begin(store, task_id, suite_hash, config, suite):
    with store._lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ok, reason = store._verify_chain_db(db)
        if not ok:
            raise RuntimeError(reason)
        task = store.get(task_id)
        if task["status"] != "FAILED":
            raise ValueError("learning requires a terminal FAILED task")
        previous = [json.loads(row[0]) for row in db.execute(
            "SELECT data FROM events WHERE type='LEARNING_STARTED'"
        )]
        if any(item["suite_sha256"] == suite_hash for item in previous):
            raise ValueError("suite already consumed; interrupted attempts cannot silently retry")
        active = {item["episode_id"] for item in previous}
        finished = {item["episode_id"] for item in history(db)}
        if active - finished:
            raise ValueError("an unfinished learning episode requires explicit adjudication")
        lessons = bank(db, config["adapter"]["scope"])
        if len(lessons) >= 19:
            raise ValueError("bank capacity reached; cannot silently discard retained lessons")
        accepted = {item["episode_id"] for item in history(db)
                    if item["verdict"] == "PROMOTED" and item["scope"] == config["adapter"]["scope"]}
        inherited = []
        for item in previous:
            if item["episode_id"] in accepted:
                for case in item["suite"]["cases"]:
                    inherited.append(dict(case, id=item["episode_id"] + ":" + case["id"], split="retention"))
        known_fixtures = {digest(case["files"]) for case in inherited}
        if any(digest(case["files"]) in known_fixtures for case in suite["cases"]):
            raise ValueError("new suite reuses a previously promoted fixture")
        if len(inherited) + len(suite["cases"]) > 36:
            raise ValueError("retention capacity reached; cannot silently drop inherited tests")
        failure = {key: task[key] for key in ("id", "goal", "error", "checkpoint", "result")}
        if len(canonical(failure).encode()) > 100_000:
            raise ValueError("failure packet exceeds 100000 bytes; select a bounded public failure")
        packet = {"schema": "hive.learning.failure.v1", "failure": failure,
                  "parent_lessons": lessons}
        data = {"task_id": task_id, "suite_sha256": suite_hash,
                "failure_sha256": digest(packet), "parent_bank_sha256": digest(lessons),
                "config": config, "suite": suite, "inherited_cases_sha256": digest(inherited)}
        data["episode_id"] = digest(data)
        store._event(db, task_id, "LEARNING_STARTED", data)
        return data, packet, lessons, inherited
