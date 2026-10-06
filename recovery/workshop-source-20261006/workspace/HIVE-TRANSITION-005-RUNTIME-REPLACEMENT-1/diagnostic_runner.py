"""Successor local-only factorial runner. Never imports an OpenAI client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SOURCE_STUDY = Path('C:\\Users\\billy\\Documents\\Codex\\2026-09-13\\referenced-chatgpt-conversation-this-is-an\\work\\HIVE-FACTORIAL-001')
sys.path.insert(0, str(HERE))
import diagnostic_environment as prior  # noqa: E402
sys.path.insert(0, str(prior.WORKSHOP))
from factorial_runner_adapter import run_condition  # noqa: E402
from workshop.hive_protocol import LOCAL_CONTEXT_WINDOW

hive = prior.hive
hive_jvm = prior.hive_jvm
external_root = prior.external_root
providers = prior.providers

LOCK_PATH = HERE / "FREEZE.json"
PARENT_LOCK_SHA256 = "b53aed4c35736e5da6b717c0289c41a9bf85e8cb4d2f9c81cf489da1e0d81d70"
EVIDENCE = HERE / "evidence"
RUNS = EVIDENCE / "runs"
MODEL_NAMES = ("qwen3:8b", "qwen2.5-coder:14b")
CONDITIONS = ("single", "hive")
TASK_IDS = ("J001", "J002", "J003", "J004")
TEST_FILES = (
    "SnapshotFormatterUnicodeAcceptanceTest.java",
    "IngredientAllocationSlotAcceptanceTest.java",
    "ObservationMapAcceptanceTest.java",
    "ExecutionCoverageAcceptanceTest.java",
)
OUTPUT_LIMITS = {role: 2048 for role in ("planner", "ui", "backend", "tests", "reviewer")}
TOKEN_CEILING = 250_000
WALL_CEILING_SECONDS = 3600


class StudyStop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def append_event(kind: str, **data: object) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": timestamp(), "kind": kind, **data}, default=str) + "\n")


def task_specs() -> list[dict]:
    text = (SOURCE_STUDY / "TASKS.md").read_text(encoding="utf-8")
    sections = [item for item in text.split("\n## J") if item[:3].isdigit()]
    tasks = []
    for section, expected_id, test_file in zip(sections, TASK_IDS, TEST_FILES, strict=True):
        task_id = "J" + section[:3]
        if task_id != expected_id:
            raise StudyStop("task order changed")
        behavior = section.split("\n\n", 1)[1].split("\n\nWrite scope:", 1)[0].strip()
        scope_line = section.split("\n\nWrite scope:", 1)[1].split("\n", 1)[0]
        files = [part.strip().strip("`.,") for part in scope_line.split("`, `")]
        files = [item.replace("`", "") for item in files]
        request = behavior + "\n\nWrite scope:" + scope_line
        if not request or not files or any(not item.startswith("src/main/java/") for item in files):
            raise StudyStop(f"invalid task contract: {task_id}")
        source = (SOURCE_STUDY / "hidden-tests" / test_file).read_text(encoding="utf-8")
        class_name = "dev.atmcompanion." + {
            "J001": "state", "J002": "knowledge", "J003": "state", "J004": "execution",
        }[task_id] + "." + Path(test_file).stem
        tests = source.count("@Test")
        tasks.append({
            "id": task_id, "request": request, "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
            "files": files, "test_filename": test_file,
            "test_path": "src/test/java/" + class_name.replace(".", "/") + ".java",
            "test_class": class_name, "test_sha256": sha(SOURCE_STUDY / "hidden-tests" / test_file),
            "test_cases": tests,
        })
    if len(tasks) != len(TASK_IDS):
        raise StudyStop("expected four tasks")
    return tasks


def trial_order() -> list[dict]:
    rng = random.Random(20261004)
    blocks = [(task, repeat) for task in TASK_IDS for repeat in (1, 2)]
    rng.shuffle(blocks)
    order = []
    for task, repeat in blocks:
        cells = [(model, condition) for model in MODEL_NAMES for condition in CONDITIONS]
        rng.shuffle(cells)
        for model, condition in cells:
            order.append({"task_id": task, "replicate": repeat, "model": model, "controller": condition})
    return order


def model_inventory() -> list[dict]:
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=15, trust_env=False) as client:
        tags = {item["name"]: item for item in client.get("/api/tags").json()["models"]}
        result = []
        for name in MODEL_NAMES:
            entry = tags[name]
            detail = client.post("/api/show", json={"model": name}).json()
            info = detail["model_info"]
            context_keys = sorted(key for key in info if key.endswith(".context_length"))
            result.append({"name": name, "digest": entry["digest"], "bytes": entry["size"],
                           "quantization": entry["details"]["quantization_level"],
                           "parameter_size": detail["details"]["parameter_size"],
                           "native_context_length": info[context_keys[0]] if context_keys else None})
    return result


def lock_facts() -> dict:
    if sha(SOURCE_STUDY / "FREEZE.json") != PARENT_LOCK_SHA256:
        raise StudyStop("historical factorial freeze changed")
    parent_lock = json.loads((SOURCE_STUDY / "FREEZE.json").read_text(encoding="utf-8"))
    if task_specs() != parent_lock["tasks"] or trial_order() != parent_lock["order"]:
        raise StudyStop("historical task set or randomized order changed")
    prior.no_cloud_key()
    if providers.ollama_base() != "http://127.0.0.1:11434":
        raise StudyStop("Ollama endpoint is not the pinned local loopback address")
    reference = prior.reference_freeze()
    approved = prior.approved_environment(reference)
    if prior.disk_free_bytes() < prior.MIN_FREE_BYTES:
        raise StudyStop("less than eight GiB free")
    return {
        "study": "HIVE-TRANSITION-005", "status": "preregistered",
        "parent_freeze_sha256": PARENT_LOCK_SHA256,
        "apparatus_change": "Host exact-write-scope planning/correction and successor controller adapter only",
        "reference_lock_sha256": prior.ASTRA_LOCK,
        "baseline": {"root": reference["baseline"]["root"], "sha256": approved["baseline_sha256"]},
        "approved_cache_run_id": approved["approved_cache_run_id"],
        "verifier_image": reference["verifier"]["image"],
        "verifier_image_id": approved["verifier_image_id"],
        "verifier_limits": reference["verifier"]["limits"],
        "models": model_inventory(),
        "ollama_version": subprocess.run(["ollama", "--version"], capture_output=True,
                                         text=True, timeout=10, check=True).stdout.strip(),
        "ollama_environment": {name: os.environ.get(name) for name in
                               ("OLLAMA_CONTEXT_LENGTH", "OLLAMA_NUM_PARALLEL",
                                "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE")},
        "tasks": task_specs(), "order": trial_order(),
        "source_manifest_sha256": hashlib.sha256(json.dumps(prior.source_manifest(), sort_keys=True).encode()).hexdigest(),
        "files_sha256": {
            **{f"historical/{name}": sha(SOURCE_STUDY / name) for name in
               ("TASKS.md", "PROTOCOL.md", "PREFLIGHT_RESULTS.md", "preflight.py", "dry_run.py",
                "oracle_check.py", "test_runner.py")},
            "runner.py": sha(HERE / "runner.py"),
            "local_harness.py": sha(HERE / "local_harness.py"),
            "freeze_new_study.py": sha(HERE / "freeze_new_study.py"),
            "factorial_runner_adapter.py": sha(prior.WORKSHOP / "factorial_runner_adapter.py"),
            "APPARATUS-REPAIR.md": sha(prior.WORKSHOP.parent / "APPARATUS-REPAIR.md"),
        },
        "baseline_red_sha256": sha(SOURCE_STUDY / "preflight-evidence" / "baseline_red.json"),
        "oracle_targeted_sha256": sha(SOURCE_STUDY / "preflight-evidence" / "oracle-runs" / "oracle-targeted.json"),
        "oracle_full_sha256": sha(SOURCE_STUDY / "preflight-evidence" / "oracle-runs" / "oracle-full.json"),
        "oracle_candidate_sha256": external_root.tree_sha256(
            SOURCE_STUDY / "preflight-evidence" / "oracle-runs" / "external_candidates" / "oracle"),
        "policy": {"allow_cloud": False, "max_tier": "local", "max_cost": 0,
                   "token_ceiling": TOKEN_CEILING, "wall_ceiling_seconds": WALL_CEILING_SECONDS,
                   "promotion": False, "replicates_per_cell": 2, "seed": 20261004},
    }


def check_lock(lock: dict) -> None:
    if lock_facts() != lock:
        raise StudyStop("frozen apparatus, task, model, baseline, cache, or verifier differs")
    if sha(LOCK_PATH) != (HERE / "LOCK.sha256").read_text(encoding="ascii").strip():
        raise StudyStop("freeze lock hash differs")


async def run_one(cell: dict, lock: dict, task: dict, ordinal: int) -> dict:
    run_id = uuid.uuid4().hex[:12]
    evidence_dir = EVIDENCE / f"{ordinal:02d}-{task['id']}-r{cell['replicate']}-{cell['model'].replace(':', '-')}-{cell['controller']}"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    output = {"ordinal": ordinal, **cell, "run_id": run_id, "classification": "INVALID",
              "applied": False, "api_cost_usd": 0.0, "electricity_cost_usd": None}
    calls = []
    try:
        run_dir = RUNS / run_id
        external = external_root.prepare_candidate(
            lock["baseline"]["root"], RUNS / "external_candidates" / run_id,
            prior.WORKSHOP, RUNS,
        )
        candidate = Path(external["candidate_root"])
        profile = hive_jvm.inspect_gradle_project(candidate)
        if profile != hive_jvm.inspect_gradle_project(Path(lock["baseline"]["root"])):
            raise StudyStop("candidate Gradle profile differs from baseline")
        external["jvm_profile"] = profile
        source = (SOURCE_STUDY / "hidden-tests" / task["test_filename"]).read_text(encoding="utf-8")
        if sha(SOURCE_STUDY / "hidden-tests" / task["test_filename"]) != task["test_sha256"]:
            raise StudyStop("hidden acceptance changed")
        frozen = hive_jvm.freeze_junit_tests(candidate, [{
            "path": task["test_path"], "class_name": task["test_class"],
            "expected_cases": task["test_cases"], "source": source,
        }])
        external["frozen_junit_tests"] = hive_jvm.store_frozen_junit_tests(frozen, run_dir)
        save_json(evidence_dir / "candidate_metadata.json", {k: v for k, v in external.items() if k != "frozen_junit_tests"})
        token_reserved = 0
        token_actual = 0
        first_model_at = None
        call_boundary = None
        observation_requests = 0

        async def agent_call(role: str, prompt: str) -> str:
            nonlocal token_reserved, token_actual, first_model_at, call_boundary, observation_requests
            if getattr(providers, "RUNTIME_ABORTED", False):
                append_event("inference_blocked_after_runtime_failure", role=role)
                raise StudyStop("Authorized experiment stops inference after runtime failure")
            if providers.openai_key() or providers.ollama_base() != "http://127.0.0.1:11434":
                call_boundary = "cloud credential or nonlocal model endpoint became available"
                raise StudyStop(call_boundary)
            if cell["controller"] == "single" and role != "backend":
                raise StudyStop(f"single-agent condition unexpectedly requested {role}")
            if first_model_at is None:
                first_model_at = time.monotonic()
            limit = OUTPUT_LIMITS[role]
            prompt_bytes = len(str(prompt).encode("utf-8")) + 1000
            reservation = prompt_bytes + limit
            if token_reserved + reservation > TOKEN_CEILING:
                call_boundary = "aggregate token ceiling reached before call"
                raise StudyStop("aggregate model token ceiling reached before call")
            if time.monotonic() - first_model_at >= WALL_CEILING_SECONDS:
                call_boundary = "common wall ceiling reached before call"
                raise StudyStop("common wall ceiling reached before call")
            token_reserved += reservation
            call = {"role": role, "model": cell["model"], "provider": "ollama",
                    "prompt_sha256": hashlib.sha256(str(prompt).encode()).hexdigest(),
                    "prompt_bytes": prompt_bytes, "started_at": timestamp()}
            t0 = time.monotonic()
            try:
                response = await providers.ollama_chat(
                    cell["model"], [{"role": "user", "content": str(prompt)}],
                    f"You are the bounded {role} agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.",
                    response_format=hive.response_schema_for_prompt(role, prompt),
                    temperature=hive.LOCAL_TEMPERATURE, max_output_tokens=limit,
                    context_window=LOCAL_CONTEXT_WINDOW,
                    total_timeout=min(900.0, max(1.0, WALL_CEILING_SECONDS - (time.monotonic() - first_model_at))),
                )
                if (not isinstance(response.get("input_tokens"), int)
                        or not isinstance(response.get("output_tokens"), int)
                        or response["input_tokens"] <= 0
                        or response["output_tokens"] <= 0):
                    call_boundary = "Ollama usage missing or zero for a nonempty prompt"
                    raise StudyStop("Ollama usage missing; aggregate ceiling cannot be verified")
                token_actual += response["input_tokens"] + response["output_tokens"]
                call.update(status="completed", input_tokens=response["input_tokens"],
                            output_tokens=response["output_tokens"],
                            response_sha256=hashlib.sha256(response["text"].encode()).hexdigest())
                try:
                    active = httpx.get("http://127.0.0.1:11434/api/ps", timeout=5, trust_env=False).json()["models"]
                    loaded = next((item for item in active if item.get("name") == cell["model"]), None)
                    if loaded:
                        call["runtime"] = {key: loaded.get(key) for key in
                                           ("context_length", "size", "size_vram", "expires_at")}
                except Exception:
                    call["runtime"] = None
                if token_actual > TOKEN_CEILING:
                    call_boundary = "aggregate actual token ceiling exceeded"
                    raise StudyStop("aggregate actual token ceiling exceeded")
                if time.monotonic() - first_model_at > WALL_CEILING_SECONDS:
                    call_boundary = "common model-decision wall ceiling exceeded"
                    raise StudyStop("common model-decision wall ceiling exceeded")
                if role in {"ui", "backend", "tests"}:
                    try:
                        parsed_worker = hive._extract_json(response["text"])
                    except Exception:
                        parsed_worker = None
                    if isinstance(parsed_worker, dict) and parsed_worker.get("status") == "observe":
                        try:
                            valid_observation = hive._validate_worker_observation(parsed_worker)
                        except Exception:
                            valid_observation = None  # Hive rejects the malformed request itself.
                        if valid_observation is not None:
                            observation_requests += 1
                            if observation_requests > hive.MAX_OBSERVATIONS_PER_WORKER:
                                call_boundary = "common six-observation aggregate ceiling reached"
                                raise StudyStop(call_boundary)
                return response["text"]
            except Exception as exc:
                call.update(status="failed", error_type=type(exc).__name__, error_message=str(exc)[:1000])
                raise
            finally:
                call["wall_seconds"] = round(time.monotonic() - t0, 3)
                calls.append(call)
                save_json(evidence_dir / "calls.json", calls)

        metadata = {"max_tier": "local", "max_cost": 0.0, "cloud_spend": 0.0,
                    "agent_calls": calls, "external_root": external,
                    "experiment": {"study_id": "HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1", "condition_id": cell["controller"],
                                   "task_id": task["id"], "replicate_index": cell["replicate"],
                                   "condition_spec_sha256": sha(LOCK_PATH)},
                    "inference": {"temperature": hive.LOCAL_TEMPERATURE, "seed": None,
                                  "output_token_limits": OUTPUT_LIMITS}}
        run = await run_condition(
            controller=cell["controller"], task=task, candidate=candidate,
            runs=RUNS, model=cell["model"], provider_call=agent_call,
            metadata=metadata, run_id=run_id,
        )
        hive.save_run(RUNS, run)
        save_json(evidence_dir / "run.json", run)
        usage_complete = all(c.get("status") == "completed" for c in calls)
        output.update(status=run.get("status"), changed_files=run.get("changed_files") or [],
                      model_calls=len(calls),
                      input_tokens=sum(c["input_tokens"] for c in calls) if usage_complete else None,
                      output_tokens=sum(c["output_tokens"] for c in calls) if usage_complete else None,
                      model_seconds=round(sum(c["wall_seconds"] for c in calls), 3),
                      structural_repairs=len(run.get("edit_repairs") or []),
                      targeted_corrections=len(run.get("targeted_repairs") or []),
                      planner_corrections=max(0, len(run.get("plan_attempts") or []) - 1),
                      observation_requests=observation_requests,
                      full_verification=run.get("verification"), review=run.get("review"))
        output["classification"] = prior.classify(run)
        if call_boundary:
            output["call_boundary"] = call_boundary
            if ("usage missing" in call_boundary or "actual token ceiling exceeded" in call_boundary
                    or "cloud credential" in call_boundary):
                output["classification"] = "INVALID"
                output["stop_reason"] = call_boundary
        if run.get("status") == "ready" and output["classification"] != "VERIFIED_SUCCESS":
            output["classification"] = "FALSE_ACCEPTANCE"
        integrity = run.get("external_baseline_integrity") or {}
        if (run.get("applied") or external.get("promotion_allowed") is not False
                or integrity.get("baseline_unchanged") is False
                or external_root.tree_sha256(Path(lock["baseline"]["root"])) != lock["baseline"]["sha256"]):
            output["classification"] = "INVALID"
            output["stop_reason"] = "promotion or baseline integrity boundary"
        output["candidate_sha256"] = external_root.tree_sha256(candidate)
        return output
    except StudyStop as exc:
        output.update(status="safety_stop", classification="INVALID", stop_reason=str(exc))
        return output
    except Exception as exc:
        output.update(status="harness_error", classification="HARNESS_FAILURE",
                      error_type=type(exc).__name__, error_message=str(exc)[:2000])
        return output
    finally:
        try:
            if external_root.tree_sha256(Path(lock["baseline"]["root"])) != lock["baseline"]["sha256"]:
                output.update(classification="INVALID", stop_reason="immutable baseline changed")
        except Exception as exc:
            output.update(classification="INVALID", stop_reason=f"baseline integrity could not be checked: {type(exc).__name__}")
        output["wall_seconds"] = round(time.monotonic() - started, 3)
        save_json(evidence_dir / "result.json", output)


def main() -> int:
    if EVIDENCE.exists():
        raise StudyStop("study evidence exists; refusing to rerun or overwrite")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    check_lock(lock)
    EVIDENCE.mkdir()
    append_event("started", lock_sha256=sha(LOCK_PATH))
    tasks = {task["id"]: task for task in lock["tasks"]}
    results = []
    for ordinal, cell in enumerate(lock["order"], 1):
        try:
            check_lock(lock)
            append_event("trial_started", ordinal=ordinal, **cell)
            outcome = asyncio.run(run_one(cell, lock, tasks[cell["task_id"]], ordinal))
            results.append(outcome)
            save_json(EVIDENCE / "raw_results.json", results)
            append_event("trial_finished", ordinal=ordinal, classification=outcome["classification"], status=outcome["status"])
            if outcome["classification"] in {"FALSE_ACCEPTANCE", "INVALID"}:
                raise StudyStop(f"required safety stop after trial {ordinal}")
        except StudyStop as exc:
            append_event("stopped", ordinal=ordinal, reason=str(exc))
            return 2
    append_event("completed", trials=len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
