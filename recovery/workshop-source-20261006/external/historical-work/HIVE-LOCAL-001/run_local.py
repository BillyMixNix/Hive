"""Run the locked, local-only 16-task Hive characterization once."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from local_harness import (
    HERE, MIN_FREE_BYTES, MODEL, OLLAMA, OUTCOME_CLASSES, PORT, PreflightFailure,
    TASK_ORDER, approved_environment, build_request, classify, disk_free_bytes,
    model_inventory, no_cloud_key, reference_freeze, service_preflight, sha,
    source_manifest, task_specs, external_root,
)

FREEZE = HERE / "HIVE-LOCAL-001-FREEZE.json"
EVIDENCE = HERE / "execution"
CONTROL_FILES = (
    "local_harness.py", "make_local_freeze.py", "run_local.py",
    "serve_local.py", "test_local_harness.py", "INVENTORY.md",
)


class StopStudy(RuntimeError):
    pass


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def event(kind: str, **details) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    record = {"at_utc": datetime.now(timezone.utc).isoformat(), "kind": kind, **details}
    with (EVIDENCE / "events.ndjson").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print("LOCAL|" + kind + "|" + str(details.get("task_id", "")) + "|"
          + str(details.get("status", details.get("stage", ""))), flush=True)


def locked_freeze() -> tuple[dict, str]:
    lock = os.environ.get("HIVE_LOCAL_001_LOCK", "")
    if not re.fullmatch(r"[0-9a-f]{64}", lock):
        raise StopStudy("Exact local freeze lock must be supplied")
    if not FREEZE.is_file() or sha(FREEZE) != lock:
        raise StopStudy("Local freeze lock mismatch")
    if os.environ.get("HIVE_LOCAL_001_RUN_AUTHORIZATION") != lock:
        raise StopStudy("A separate exact-lock run authorization is required")
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    if frozen.get("status") != "frozen_not_executed":
        raise StopStudy("Local freeze is not the immutable pre-execution artifact")
    return frozen, lock


def preflight_task(frozen: dict, lock: str, task_id: str) -> tuple[list[dict], dict]:
    current, current_lock = locked_freeze()
    if current_lock != lock or current != frozen:
        raise StopStudy("Frozen study changed")
    for name in CONTROL_FILES:
        if sha(HERE / name) != frozen["control_files"][name]:
            raise StopStudy(f"Frozen local harness changed: {name}")
    reference = reference_freeze()
    if source_manifest() != frozen["workshop"]["source_manifest"]:
        raise StopStudy("Workshop source manifest changed")
    tasks = task_specs(reference)
    if ([task["id"] for task in tasks] != frozen["task_order"]
            or [{key: task[key] for key in ("id", "request_sha256", "test_sha256", "expected_cases")}
                for task in tasks] != frozen["tasks"]):
        raise StopStudy("Frozen task, prompt or acceptance hash changed")
    no_cloud_key()
    model = model_inventory()
    if model != frozen["local_model"]["identity"]:
        raise StopStudy("Installed Ollama model or runtime identity changed")
    approved = approved_environment(reference)
    if approved["baseline_sha256"] != frozen["baseline"]["sha256"]:
        raise StopStudy("Immutable baseline changed")
    if disk_free_bytes() < MIN_FREE_BYTES:
        raise StopStudy("Insufficient disk space for sealed local evaluation")
    service = service_preflight()
    if frozen["cloud_policy"] != {"allow_cloud": False, "max_tier": "local",
                                    "agent_backend": "classic", "api_key_required": False,
                                    "promotion": False}:
        raise StopStudy("Frozen local-only policy changed")
    return tasks, {"task_id": task_id, "baseline_sha256": approved["baseline_sha256"],
                   "image_id": approved["verifier_image_id"],
                   "cache_run_id": approved["approved_cache_run_id"],
                   "disk_free_bytes": disk_free_bytes(), "service": service}


def _call_summary(run: dict) -> dict:
    calls = (run.get("metadata") or {}).get("agent_calls") or []
    local = [call for call in calls if call.get("provider") == "ollama"]
    completed = [call for call in local if call.get("status") == "completed"]
    return {
        "model_calls": len(local),
        "model_call_wall_seconds": round(sum(float(call.get("wall_seconds") or 0)
                                             for call in local), 3) if local else None,
        "reported_input_tokens": sum(call["input_tokens"] for call in completed
                                     if isinstance(call.get("input_tokens"), int)) if completed else None,
        "reported_output_tokens": sum(call["output_tokens"] for call in completed
                                      if isinstance(call.get("output_tokens"), int)) if completed else None,
        "prompt_sizes": [{"role": item.get("role"), "chars": item.get("prompt_chars"),
                          "sha256": item.get("prompt_sha256")}
                         for item in run.get("prompt_trace") or []],
    }


def _containment_failure(run: dict) -> bool:
    verification = run.get("verification") or {}
    for check in verification.get("checks") or []:
        name = str(check.get("name") or "").casefold()
        if check.get("passed") is False and any(token in name for token in (
                "external_integrity", "source_immutability", "cache_integrity",
                "network_access_attempt")):
            return True
    return False


def execute_task(task: dict, frozen: dict, lock: str) -> dict:
    started = time.monotonic()
    task_id = task["id"]
    trial_id = uuid.uuid4().hex[:12]
    destination = EVIDENCE / task_id
    destination.mkdir(parents=True, exist_ok=False)
    request = build_request(task, {**frozen, "lock_sha256": lock,
                                   "local_model": {"tag": MODEL}}, trial_id)
    if (request["allow_cloud"] is not False or request["max_tier"] != "local"
            or request["agent_backend"] != "classic" or request["max_cost"] != 0.0):
        raise StopStudy("Local-only request policy violated before submission")
    write_json(destination / "request.json", request)
    outcome = {"task_id": task_id, "group": task["group"], "trial_id": trial_id,
               "status": "invalid", "classification": "INVALID", "applied": False}
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=40) as client:
            reply = client.post("/api/hive/build", json=request)
            if reply.status_code != 200:
                outcome.update(status="request_rejected", classification="HARNESS_FAILURE",
                               http_status=reply.status_code, response_excerpt=reply.text[:2000])
                return outcome
            job_id = reply.json()["job_id"]
            outcome["job_id"] = job_id
            deadline = time.monotonic() + 8 * 3600
            stage_log = []
            while time.monotonic() < deadline:
                response = client.get(f"/api/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                state = job.get("state")
                marker = (state, job.get("progress"), job.get("message"))
                if not stage_log or stage_log[-1]["marker"] != marker:
                    stage_log.append({"marker": marker,
                                      "elapsed_seconds": round(time.monotonic() - started, 3)})
                    write_json(destination / "stages.json", stage_log)
                    event("stage", task_id=task_id, stage=state, progress=job.get("progress"))
                if state in {"completed", "failed", "cancelled"}:
                    write_json(destination / "job.json", job)
                    run = job.get("result")
                    if not isinstance(run, dict):
                        outcome.update(status="job_" + str(state), classification="HARNESS_FAILURE",
                                       job_error=str(job.get("error") or "")[:2000])
                        return outcome
                    write_json(destination / "run.json", run)
                    outcome.update(status=str(run.get("status")), classification=classify(run),
                                   run_id=run.get("id"), changed_files=run.get("changed_files") or [],
                                   applied=bool(run.get("applied")),
                                   planner_outcome=(run.get("plan") or {}).get("summary"),
                                   repairs={"structural": len(run.get("edit_repairs") or []),
                                            "targeted": len(run.get("targeted_repairs") or []),
                                            "replans": len(run.get("replans") or [])},
                                   model=_call_summary(run))
                    integrity = run.get("external_baseline_integrity") or {}
                    outcome["integrity"] = integrity
                    external = (run.get("metadata") or {}).get("external_root") or {}
                    if (run.get("applied") or external.get("promotion_allowed") is not False
                            or integrity.get("baseline_unchanged") is False
                            or integrity.get("candidate_unchanged") is False):
                        outcome["classification"] = "INVALID"
                        raise StopStudy("External-root integrity or promotion boundary violated")
                    calls = (run.get("metadata") or {}).get("agent_calls") or []
                    if any(call.get("provider") != "ollama" for call in calls):
                        outcome["classification"] = "INVALID"
                        raise StopStudy("Evidence of a cloud provider call")
                    if _containment_failure(run):
                        outcome["classification"] = "INVALID"
                        raise StopStudy("Sealed verifier containment failure")
                    if external_root.tree_sha256(Path(frozen["baseline"]["root"])) != frozen["baseline"]["sha256"]:
                        outcome["classification"] = "INVALID"
                        raise StopStudy("Immutable external baseline changed")
                    candidate = Path(external.get("candidate_root") or "")
                    if not candidate.is_dir():
                        outcome["classification"] = "INVALID"
                        raise StopStudy("Run-owned candidate is missing")
                    outcome["candidate_sha256"] = external_root.tree_sha256(candidate)
                    if outcome["classification"] in {"FALSE_ACCEPTANCE", "INVALID"}:
                        raise StopStudy("False acceptance or invalid evidence")
                    return outcome
                time.sleep(5)
            outcome.update(status="job_timeout", classification="HARNESS_FAILURE")
            return outcome
    except StopStudy as exc:
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


def main() -> int:
    frozen, lock = locked_freeze()
    if EVIDENCE.exists():
        raise StopStudy("Study evidence already exists; no reruns are permitted")
    tasks, initial = preflight_task(frozen, lock, "PRESTART")
    EVIDENCE.mkdir()
    write_json(EVIDENCE / "preflight.json", initial)
    event("study_started", status="running", lock_sha256=lock, task_count=len(tasks))
    results = []
    try:
        for task in tasks:
            _, check = preflight_task(frozen, lock, task["id"])
            event("task_preflight", task_id=task["id"], **{k: v for k, v in check.items()
                                                             if k != "task_id"})
            event("task_started", task_id=task["id"])
            result = execute_task(task, frozen, lock)
            results.append(result)
            write_json(EVIDENCE / "raw_results.json", results)
            event("task_finished", task_id=task["id"], status=result["status"],
                  classification=result["classification"], run_id=result.get("run_id"))
            if result.get("must_stop"):
                raise StopStudy(result["stop_reason"])
        event("study_complete", status="completed", task_count=len(results))
        return 0
    except (StopStudy, PreflightFailure) as exc:
        event("study_stopped", status="stopped", reason=str(exc))
        write_json(EVIDENCE / "raw_results.json", results)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
