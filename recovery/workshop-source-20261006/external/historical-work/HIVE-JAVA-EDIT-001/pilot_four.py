"""One-pass, local-only T001–T004 diagnostic of the Java action-space repair."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from local_harness import (
    HERE, MIN_FREE_BYTES, MODEL, approved_environment, build_request, classify,
    disk_free_bytes, external_root, model_inventory, no_cloud_key,
    reference_freeze, sha, source_manifest, task_specs,
)


TASK_IDS = ("T001", "T002", "T003", "T004")
STUDY = "HIVE-JAVA-EDIT-001-FOUR"
EVIDENCE = HERE / "pilot-four-evidence"
BASE_URL = "http://127.0.0.1:8767"
MODEL_DIGEST = "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849"


class StopPilot(RuntimeError):
    pass


def write_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def event(kind: str, **details):
    record = {"at_utc": datetime.now(timezone.utc).isoformat(), "kind": kind, **details}
    with (EVIDENCE / "events.ndjson").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("FOUR|" + kind + "|" + str(details.get("task_id", "")) + "|"
          + str(details.get("status", details.get("stage", ""))), flush=True)


def manifest_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preflight(frozen: dict | None = None):
    no_cloud_key()
    reference = reference_freeze()
    tasks = [task for task in task_specs(reference) if task["id"] in TASK_IDS]
    if tuple(task["id"] for task in tasks) != TASK_IDS:
        raise StopPilot("Selected task order changed")
    model = model_inventory()
    if model["digest"] != MODEL_DIGEST:
        raise StopPilot("Local model digest changed")
    approved = approved_environment(reference)
    if disk_free_bytes() < MIN_FREE_BYTES:
        raise StopPilot("Less than 8 GiB free for isolated candidates")
    source = source_manifest()
    with httpx.Client(base_url=BASE_URL, timeout=15, trust_env=False) as client:
        health = client.get("/api/health").json()
        process = client.get("/api/preflight").json()
    if (not health.get("ok") or (health.get("jobs") or {}).get("active_jobs") != 0
            or process.get("openai_key_loaded") is not False
            or (health.get("apparatus") or {}).get("jvm_verifier_image") != reference["verifier"]["image"]
            or (health.get("apparatus") or {}).get("jvm_verifier_pids") != 448):
        raise StopPilot("Serving pilot Workshop is not idle, keyless, or on approved verifier")
    facts = {
        "study": STUDY, "task_order": list(TASK_IDS),
        "tasks": [{key: task[key] for key in ("id", "request_sha256", "test_sha256", "expected_cases")}
                  for task in tasks],
        "source_manifest_sha256": manifest_digest(source),
        "reference_lock_sha256": sha(HERE.parent / "HIVE-ASTRA-002" / "FREEZE-002.json"),
        "model": model,
        "baseline": {"root": reference["baseline"]["root"], "sha256": approved["baseline_sha256"]},
        "verifier_image_id": approved["verifier_image_id"],
        "approved_cache_run_id": approved["approved_cache_run_id"],
        "policy": {"allow_cloud": False, "max_tier": "local", "max_cost": 0.0,
                   "agent_backend": "classic", "promotion": False},
    }
    if frozen is not None and facts != frozen:
        raise StopPilot("Pilot apparatus or frozen input changed")
    return tasks, facts


def run_task(task: dict, frozen: dict, lock: str):
    task_id = task["id"]
    started = time.monotonic()
    destination = EVIDENCE / task_id
    destination.mkdir()
    request = build_request(task, {"baseline": frozen["baseline"], "local_model": {"tag": MODEL},
                                   "lock_sha256": lock}, uuid.uuid4().hex[:12])
    request["experiment"].update(study_id=STUDY, condition_id="patched_hive_local")
    if (request["allow_cloud"] or request["max_tier"] != "local"
            or request["max_cost"] != 0.0 or request["agent_backend"] != "classic"):
        raise StopPilot("Cloud-disabled request invariant failed")
    write_json(destination / "request.json", request)
    outcome = {"task_id": task_id, "classification": "INVALID", "status": "started", "applied": False}
    try:
        with httpx.Client(base_url=BASE_URL, timeout=40, trust_env=False) as client:
            response = client.post("/api/hive/build", json=request)
            if response.status_code != 200:
                outcome.update(status="request_rejected", classification="HARNESS_FAILURE",
                               http_status=response.status_code, response_excerpt=response.text[:2000])
                return outcome
            job_id = response.json()["job_id"]
            outcome["job_id"] = job_id
            deadline = time.monotonic() + 8 * 3600
            last_stage = None
            while time.monotonic() < deadline:
                job = client.get(f"/api/jobs/{job_id}").json()
                stage = (job.get("state"), job.get("progress"), job.get("message"))
                if stage != last_stage:
                    event("stage", task_id=task_id, stage=job.get("state"), progress=job.get("progress"))
                    write_json(destination / "last_stage.json", {"state": stage[0], "progress": stage[1],
                                                                 "message": stage[2]})
                    last_stage = stage
                if job.get("state") in {"completed", "failed", "cancelled"}:
                    write_json(destination / "job.json", job)
                    run = job.get("result")
                    if not isinstance(run, dict):
                        outcome.update(status="job_" + str(job.get("state")), classification="HARNESS_FAILURE",
                                       job_error=str(job.get("error") or "")[:2000])
                        return outcome
                    write_json(destination / "run.json", run)
                    calls = (run.get("metadata") or {}).get("agent_calls") or []
                    outcome.update(status=run.get("status"), classification=classify(run),
                                   run_id=run.get("id"), applied=bool(run.get("applied")),
                                   changed_files=run.get("changed_files") or [],
                                   model_calls=len(calls),
                                   model_generation_seconds=round(sum(float(call.get("wall_seconds") or 0)
                                                                       for call in calls), 3),
                                   structural_repairs=len(run.get("edit_repairs") or []),
                                   targeted_corrections=len(run.get("targeted_repairs") or []))
                    ext = (run.get("metadata") or {}).get("external_root") or {}
                    integrity = run.get("external_baseline_integrity") or {}
                    if (run.get("applied") or ext.get("promotion_allowed") is not False
                            or any(call.get("provider") != "ollama" for call in calls)
                            or integrity.get("baseline_unchanged") is False
                            or integrity.get("candidate_unchanged") is False
                            or any(check.get("passed") is False and check.get("name") in {
                                "external_integrity", "source_immutability", "cache_integrity",
                                "network_access_attempt"}
                                for check in (run.get("verification") or {}).get("checks") or [])
                            or external_root.tree_sha256(Path(frozen["baseline"]["root"])) != frozen["baseline"]["sha256"]):
                        outcome["classification"] = "INVALID"
                        raise StopPilot("Cloud, promotion, or baseline-integrity boundary reached")
                    candidate = Path(ext.get("candidate_root") or "")
                    if not candidate.is_dir():
                        outcome["classification"] = "INVALID"
                        raise StopPilot("Run-owned candidate is missing")
                    outcome["candidate_sha256"] = external_root.tree_sha256(candidate)
                    if outcome["classification"] in {"INVALID", "FALSE_ACCEPTANCE"}:
                        raise StopPilot("Invalid or false-acceptance result")
                    return outcome
                time.sleep(5)
            outcome.update(status="job_timeout", classification="HARNESS_FAILURE")
            return outcome
    except StopPilot as exc:
        outcome["must_stop"] = True
        outcome["stop_reason"] = str(exc)
        return outcome
    except (OSError, httpx.HTTPError, KeyError, ValueError) as exc:
        outcome.update(status="harness_error", classification="HARNESS_FAILURE",
                       error_type=type(exc).__name__, error_message=str(exc)[:2000])
        return outcome
    finally:
        outcome["wall_seconds"] = round(time.monotonic() - started, 3)
        write_json(destination / "result.json", outcome)


def main():
    if EVIDENCE.exists():
        raise StopPilot("Pilot evidence exists; refusing any rerun or overwrite")
    tasks, frozen = preflight()
    EVIDENCE.mkdir()
    write_json(EVIDENCE / "PILOT-FOUR-FREEZE.json", frozen)
    lock = sha(EVIDENCE / "PILOT-FOUR-FREEZE.json")
    event("started", status="running", lock_sha256=lock, task_count=4)
    results = []
    try:
        for task in tasks:
            preflight(frozen)
            event("task_started", task_id=task["id"])
            result = run_task(task, frozen, lock)
            results.append(result)
            write_json(EVIDENCE / "raw_results.json", results)
            event("task_finished", task_id=task["id"], status=result["status"],
                  classification=result["classification"])
            if result.get("must_stop") or result["classification"] in {"FALSE_ACCEPTANCE", "INVALID"}:
                raise StopPilot(f"Safety stop after {task['id']}")
        event("completed", status="completed", task_count=len(results))
        return 0
    except Exception as exc:
        event("stopped", status="stopped", error_type=type(exc).__name__, reason=str(exc)[:1000])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
