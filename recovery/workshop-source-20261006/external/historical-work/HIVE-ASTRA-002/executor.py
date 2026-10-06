"""Proposed HIVE-ASTRA-002 driver; never run before operator approves FREEZE-002.

The direct control uses one bounded deterministic repository context and one
Agents turn. Both conditions use the same sealed JVM verifier. All artifacts
remain run-owned; no candidate is promoted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

import httpx

HERE = Path(__file__).resolve().parent
WORKSHOP = HERE / "workshop"
CHALLENGE = HERE
HISTORICAL = HERE.parent / "HIVE-ASTRA-001"
HISTORICAL_LOCK = "2d33ce88af66ed3e1f0c1e73ce3a1de62ffe36cd355a21554cc7306fddb6d291"
APPROVED_WORKSHOP = HERE.parent / "Nix-Workshop-v0.11.1-persistent-agents" / "Nix_Workshop_v0_11_1"
LOCK = os.environ.get("HIVE_ASTRA_002_LOCK", "")
EVIDENCE = CHALLENGE / "execution-002"
sys.path.insert(0, str(WORKSHOP))

from workshop import external_root, hive_jvm, hive_verifier, persistent_agent, providers  # noqa: E402
from verification import prime_gradle_cache  # noqa: E402
from control_request import DIRECT_INSTRUCTIONS, build_direct_request  # noqa: E402
from outcomes import classify, Outcome  # noqa: E402

STOP_WORDS = ("insufficient_quota", "billing_hard_limit", "spend limit", "budget limit",
              "hard limit", "hard_limit_reached", "credit balance")
SOURCE_EXCLUDES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                   ".mypy_cache", ".ruff_cache", "data", "media", "reports", "snapshots",
                   "workspace", "hive_runs", "self_snapshots", "logs", "build", "dist",
                   "outputs", "releases", "artifacts", ".codex", ".agents"}
class StopExperiment(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


RUNNER_HASH = sha(Path(__file__).read_bytes())


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def record(kind: str, payload: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "events.ndjson").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(), "kind": kind, **payload},
            ensure_ascii=False, default=str) + "\n")
    print("BENCHMARK|" + kind + "|" + str(payload.get("task_id", payload.get("task", "")))
          + "|" + str(payload.get("condition", payload.get("status", ""))), flush=True)


def checked_hash(path: Path, expected: str) -> bool:
    return path.is_file() and sha(path.read_bytes()) == expected


def freeze() -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", LOCK):
        raise StopExperiment("The operator must supply the approved HIVE_ASTRA_002_LOCK")
    if not checked_hash(CHALLENGE / "FREEZE-002.json", LOCK):
        raise StopExperiment("Freeze-002 lock mismatch")
    if not checked_hash(HISTORICAL / "FREEZE-v2.json", HISTORICAL_LOCK):
        raise StopExperiment("Historical Freeze-v2 lock mismatch")
    frozen = json.loads((CHALLENGE / "FREEZE-002.json").read_text(encoding="utf-8"))
    if frozen.get("status") != "proposed_not_executed":
        raise StopExperiment("Freeze-002 is not the proposed, unmodified artifact")
    if os.environ.get("HIVE_ASTRA_002_RUN_AUTHORIZATION") != LOCK:
        raise StopExperiment("Freeze-002 execution requires a separate exact-lock authorization")
    return frozen


def source_manifest_ok(frozen: dict) -> bool:
    expected = {row["path"]: (row["sha256"], row["size"])
                for row in frozen["workshop"]["source_manifest"]}
    found = {}
    for path in WORKSHOP.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(WORKSHOP)
        parts = rel.parts
        name = path.name
        if (any(part in SOURCE_EXCLUDES for part in parts) or name.startswith(".env")
                or path.suffix == ".pyc" or re.search(
                    r"(?i)(^credentials|^secrets|\.key$|\.pem$|\.p12$|\.pfx$|\.log$)", name)):
            continue
        data = path.read_bytes()
        found[rel.as_posix()] = (sha(data), len(data))
    return found == expected


def apparatus_manifest_ok(frozen: dict) -> bool:
    controls = frozen["control_apparatus"]["files"]
    if not all(checked_hash(CHALLENGE / name, digest)
               for name, digest in controls.items()):
        return False
    history = frozen["relationship_to_001"]
    return (checked_hash(HISTORICAL / "execution-v2" / "raw_results.json",
                         history["raw_results_sha256"])
            and checked_hash(HISTORICAL / "execution-v2" / "events.ndjson",
                             history["event_log_sha256"]))


def task_specs(frozen: dict) -> list[dict]:
    result = []
    for group_name in ("replication", "novel"):
        group = frozen["task_groups"][group_name]
        root = HISTORICAL if group_name == "replication" else CHALLENGE
        task_path = root / group["task_spec_path"]
        if not checked_hash(task_path, group["task_spec_sha256"]):
            raise StopExperiment(f"Frozen {group_name} task specification changed")
        matches = re.findall(r"(?ms)^## ([TN]\d{3}) — [^\n]+\n\n(.*?)\n\nFrozen test: `([^`]+)`\.",
                             task_path.read_text(encoding="utf-8"))
        expected = group["tasks"]
        if len(matches) != len(expected):
            raise StopExperiment(f"Frozen {group_name} task count changed")
        for (task_id, request, filename), entry in zip(matches, expected):
            if (task_id != entry["id"] or request != entry["request"]
                    or filename != Path(entry["test_path"]).name):
                raise StopExperiment(f"Frozen {group_name} task text changed: {task_id}")
            test_path = root / entry["test_path"]
            if not checked_hash(test_path, entry["test_sha256"]):
                raise StopExperiment(f"Frozen acceptance test changed: {test_path}")
            source = test_path.read_text(encoding="utf-8")
            package = re.search(r"(?m)^package\s+([\w.]+)\s*;", source)
            if not package:
                raise StopExperiment(f"Frozen test package missing: {test_path}")
            classname = package.group(1) + "." + Path(filename).stem
            result.append({"id": task_id, "group": group_name, "request": request,
                           "test": {"path": "src/test/java/" + package.group(1).replace(".", "/")
                                    + "/" + filename, "class_name": classname,
                                    "expected_cases": entry["expected_cases"], "source": source}})
    return result


def preflight_pair(frozen: dict, tasks: list[dict], task_id: str) -> dict:
    if sha(Path(__file__).read_bytes()) != RUNNER_HASH:
        raise StopExperiment("Execution harness changed after import")
    current = freeze()
    if (current != frozen or task_specs(current) != tasks
            or not source_manifest_ok(current) or not apparatus_manifest_ok(current)):
        raise StopExperiment("Frozen challenge/source state changed")
    baseline = Path(current["baseline"]["root"])
    baseline_hash = external_root.tree_sha256(baseline)
    if baseline_hash != current["baseline"]["tree_sha256"]:
        raise StopExperiment("Immutable baseline hash mismatch")
    root = APPROVED_WORKSHOP / "hive_runs"
    run_id = current["approved_cache"]["run_id"]
    cache = root / "approved-gradle-caches" / run_id
    evidence = root / run_id
    prov = cache / ".hive-priming-provenance" / run_id
    files = {
        "gradle_artifact_manifest_sha256": prov / "artifacts.manifest.json",
        "gradle_priming_provenance_sha256": prov / "provenance.json",
        "external_build_inputs_manifest_sha256": evidence / "external-build-inputs.manifest.json",
        "external_build_inputs_provenance_sha256": evidence / "external-build-inputs.provenance.json",
        "frozen_junit_manifest_sha256": evidence / "frozen-junit-manifest.json",
    }
    for name, path in files.items():
        if not checked_hash(path, current["approved_cache"][name]):
            raise StopExperiment(f"Approved cache provenance mismatch: {name}")
    inventory = json.loads(files["gradle_artifact_manifest_sha256"].read_text(encoding="utf-8"))
    if prime_gradle_cache._inventory_cache(cache) != inventory.get("artifacts"):
        raise StopExperiment("Approved Gradle artifact inventory mismatch")
    image = hive_verifier.DEFAULT_IMAGE
    if image != current["verifier"]["image"]:
        raise StopExperiment("Hive-selected verifier image changed")
    docker = __import__("shutil").which("docker")
    if not docker:
        raise StopExperiment("Docker unavailable")
    inspected = subprocess.run([docker, "image", "inspect", image, "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=15)
    image_id = inspected.stdout.strip() if inspected.returncode == 0 else ""
    if image_id != current["verifier"]["image_id"]:
        raise StopExperiment("Approved verifier image changed")
    profile = hive_jvm.inspect_gradle_project(baseline)
    if not profile or profile.get("version") != current["verifier"]["gradle_wrapper_version"]:
        raise StopExperiment("Gradle profile changed")
    os.environ["GRADLE_USER_HOME"] = str(cache.resolve(strict=True))
    hive_jvm.gradle_cache_locations(profile)
    hive_jvm.external_build_input_locations(
        profile, baseline_sha256=baseline_hash, container_image_id=image_id)
    if not hive_jvm.verify_frozen_artifacts(
            json.loads(files["frozen_junit_manifest_sha256"].read_text(encoding="utf-8")), evidence):
        raise StopExperiment("Approved frozen-JUnit manifest changed")
    health = httpx.get("http://127.0.0.1:8765/api/health", timeout=10).json()
    if health.get("version") != current["workshop"]["version"] or not health.get("ok"):
        raise StopExperiment("Workshop service changed or unhealthy")
    apparatus = health.get("apparatus") or {}
    if (apparatus.get("study") != "HIVE-ASTRA-002"
            or apparatus.get("jvm_verifier_pids") != current["verifier"]["limits"]["pids"]
            or apparatus.get("jvm_verifier_image") != current["verifier"]["image"]):
        raise StopExperiment("Serving Workshop process has not loaded the frozen 002 verifier policy")
    if (health.get("jobs") or {}).get("active_jobs") != 0:
        raise StopExperiment("Unexpected active Workshop job")
    key = providers.openai_key()
    if not key or not key.startswith("sk-proj-"):
        raise StopExperiment("Approved project-scoped API key unavailable")
    approved_line = next((line for line in (APPROVED_WORKSHOP / ".env.local").read_text(
        encoding="utf-8").splitlines() if line.lstrip().startswith("OPENAI_API_KEY=")), "")
    approved_key = approved_line.split("=", 1)[1].strip().strip('"').strip("'") if approved_line else ""
    if key != approved_key:
        raise StopExperiment("API key differs from approved project file")
    return {"task": task_id, "baseline_sha256": baseline_hash, "image_id": image_id,
            "source_manifest_count": len(current["workshop"]["source_manifest"])}


def safe_diff_paths(diff: str, candidate: Path) -> list[str]:
    if ("GIT binary patch" in diff or "Binary files " in diff or
            re.search(r"(?m)^(?:rename|copy) (?:from|to) |^old mode |^new mode |^deleted file mode|^new file mode (?!100644$)", diff)):
        raise ValueError("Unsupported binary, rename, mode, symlink, or deletion diff")
    headers = re.findall(r"(?m)^diff --git a/([^\n\t ]+) b/([^\n\t ]+)\s*$", diff)
    oldnew = re.findall(r"(?m)^--- (?:a/([^\n\t ]+)|(/dev/null))\n\+\+\+ b/([^\n\t ]+)\s*$", diff)
    if not headers or len(headers) != len(oldnew):
        raise ValueError("Expected a complete git-style unified diff for each changed file")
    paths = []
    for (left, right), (old_path, dev_null, new_path) in zip(headers, oldnew):
        if left != right or right != new_path or (old_path and old_path != right):
            raise ValueError("Diff path mismatch or unsupported rename")
        parts = PurePosixPath(right).parts
        if (not parts or parts[:3] != ("src", "main", "java") or
                any(part in {"", ".", ".."} for part in parts) or
                right.startswith("/") or "\\" in right or ":" in right or
                not right.endswith(".java")):
            raise ValueError("Diff path is outside authorized source scope")
        target = candidate.joinpath(*parts)
        target.resolve(strict=False).relative_to(candidate.resolve(strict=True))
        for parent in target.parents:
            if parent == candidate:
                break
            if parent.is_symlink():
                raise ValueError("Diff path crosses a symlink")
        if target.is_symlink() or (dev_null and target.exists()):
            raise ValueError("Diff path has unsafe existing target")
        paths.append(right)
    if len(paths) != len(set(paths)):
        raise ValueError("Diff repeats a file")
    return paths


def apply_diff(diff: str, candidate: Path) -> list[str]:
    paths = safe_diff_paths(diff, candidate)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    for args in (["git", "apply", "--check", "--whitespace=nowarn", "-"],
                 ["git", "apply", "--whitespace=nowarn", "-"]):
        result = subprocess.run(args, cwd=candidate, input=diff, text=True,
                                capture_output=True, env=env, timeout=30)
        if result.returncode != 0:
            raise ValueError("Unified diff rejected by git apply: " + result.stderr[:2000])
    return paths


def assert_sealed_report(report: dict, frozen: dict) -> None:
    isolation = report.get("isolation") or {}
    if (not isolation.get("available") or isolation.get("network") != "none"
            or isolation.get("image_id") != frozen["verifier"]["image_id"]):
        raise StopExperiment("Sealed verifier containment unavailable or changed")
    for check in report.get("checks") or []:
        name = str(check.get("name", "")).lower()
        if not check.get("passed") and (
                "source_immutability" in name or "network" in name
                or "cache_integrity" in name):
            raise StopExperiment(f"Sealed verifier integrity/containment failure: {name}")


async def direct_turn(body: dict, destination: Path) -> dict:
    started = time.monotonic()
    destination.mkdir(parents=True, exist_ok=True)
    prompt = body["input"][0]["content"][0]["text"]
    (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
    key = providers.openai_key()
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json",
               "OpenAI-Beta": "agents=v1"}
    output = {"session_id": None, "turn_id": None, "turns": 0, "usage": None,
              "wall_seconds": None, "status": "invalid"}
    async with httpx.AsyncClient(base_url=providers.OPENAI_BASE, timeout=60.0) as client:
        async def request(method: str, path: str, **kwargs):
            response = await client.request(method, path, headers=headers, **kwargs)
            if not response.is_success:
                detail = response.text[:1200]
                if any(word in detail.lower() for word in STOP_WORDS):
                    raise StopExperiment("Provider refused request at project spend limit")
                raise RuntimeError(f"Agents API {response.status_code}: {detail}")
            return response.json()
        try:
            result = await request("POST", "/agents/sessions", json=body)
            session_id = result.get("id")
            if not session_id:
                raise RuntimeError("Agents create-session response omitted id")
            output["session_id"] = session_id
            output["turns"] = 1
            deadline = time.monotonic() + 900
            turn = None
            while time.monotonic() < deadline:
                result = await request("GET", f"/agents/sessions/{session_id}/turns",
                                       params={"order": "desc", "limit": 20})
                turns = result.get("data") or []
                if turns:
                    turn = turns[0]
                    if turn.get("status") in {"completed", "failed", "cancelled"}:
                        break
                await asyncio.sleep(1)
            if not turn or turn.get("status") not in {"completed", "failed", "cancelled"}:
                raise TimeoutError("Direct Astra turn exceeded frozen 900-second limit")
            output["turn_id"] = turn.get("id")
            output["turn_status"] = turn.get("status")
            output["usage"] = turn.get("usage")
            if turn.get("status") != "completed":
                raise RuntimeError("Direct Astra turn " + str(turn.get("status")))
            usage = turn.get("usage")
            if turn.get("id"):
                try:
                    detail = await request("GET", f"/agents/sessions/{session_id}/turns/{turn['id']}")
                    usage = detail.get("usage") or usage
                except Exception as exc:
                    output["usage_read_error_type"] = type(exc).__name__
            output["usage"] = usage
            items = await request("GET", f"/agents/sessions/{session_id}/items",
                                  params={"order": "desc", "limit": 100})
            response = persistent_agent._assistant_text(items, turn.get("id"))
            (destination / "response.txt").write_text(response, encoding="utf-8")
            if not response:
                raise RuntimeError("Direct Astra completed without text")
            output["status"] = "completed"
            return output
        except BaseException as exc:
            output["error_type"] = type(exc).__name__
            output["error_message"] = str(exc)[:2000]
            if isinstance(exc, (StopExperiment, TimeoutError)):
                output["stop_experiment"] = True
            return output
        finally:
            output["wall_seconds"] = round(time.monotonic() - started, 3)
            write_json(destination / "model.json", output)


def run_direct(task: dict, frozen: dict) -> dict:
    started = time.monotonic()
    trial = uuid.uuid4().hex[:12]
    run_dir = WORKSHOP / "hive_runs" / trial
    candidate = WORKSHOP / "hive_runs" / "external_candidates" / trial
    evidence = EVIDENCE / task["id"] / "direct"
    evidence.mkdir(parents=True, exist_ok=True)
    outcome = {"task_id": task["id"], "condition": "direct", "trial_id": trial,
               "status": "invalid", "candidate_root": str(candidate), "applied": False}
    try:
        metadata = external_root.prepare_candidate(
            frozen["baseline"]["root"], candidate, WORKSHOP, WORKSHOP / "hive_runs")
        forbidden = [entry["test"]["path"] for entry in task_specs(frozen)]
        body, manifest = build_direct_request(
            Path(frozen["baseline"]["root"]), task["request"],
            model=frozen["provider"]["model"], frozen_test_paths=forbidden,
        )
        write_json(evidence / "context_manifest.json", manifest)
        model = asyncio.run(direct_turn(body, evidence))
        outcome["model"] = model
        if model.get("stop_experiment"):
            outcome["status"] = "provider_refusal"
            raise StopExperiment(model.get("error_message") or "Provider spend-limit refusal")
        if model.get("status") != "completed":
            outcome["status"] = "model_failed"
            return outcome
        diff = (evidence / "response.txt").read_text(encoding="utf-8")
        try:
            paths = apply_diff(diff, candidate)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            outcome["status"] = "diff_rejected"
            outcome["diff_error"] = f"{type(exc).__name__}: {exc}"
            return outcome
        outcome["changed_files"] = paths
        outcome["candidate_sha256_after_edit"] = external_root.tree_sha256(candidate)
        if not external_root.baseline_unchanged(metadata):
            raise StopExperiment("Immutable baseline changed during direct condition")
        profile = hive_jvm.inspect_gradle_project(candidate)
        if profile != hive_jvm.inspect_gradle_project(Path(frozen["baseline"]["root"])):
            raise StopExperiment("Gradle profile changed in direct candidate")
        specs = hive_jvm.freeze_junit_tests(Path(frozen["baseline"]["root"]), [task["test"]])
        junit = hive_jvm.store_frozen_junit_tests(specs, run_dir)
        target = hive_verifier.targeted_verify_isolated(
            candidate, [], external_root=True, frozen_junit_tests=junit,
            expected_jvm_profile=profile,
            expected_external_baseline_sha256=frozen["baseline"]["tree_sha256"])
        outcome["acceptance"] = target
        assert_sealed_report(target, frozen)
        if target.get("passed"):
            full = hive_verifier.verify_tree_isolated(
                candidate, external_root=True, frozen_junit_tests=junit,
                expected_jvm_profile=profile,
                expected_external_baseline_sha256=frozen["baseline"]["tree_sha256"])
            outcome["full_gate"] = full
            assert_sealed_report(full, frozen)
        outcome["status"] = ("verified" if target.get("passed") and
                             (outcome.get("full_gate") or {}).get("passed")
                             else "verification_failed")
        if external_root.tree_sha256(candidate) != outcome["candidate_sha256_after_edit"]:
            raise StopExperiment("Verifier mutated direct candidate")
        if not external_root.baseline_unchanged(metadata):
            raise StopExperiment("Immutable baseline changed during verification")
        return outcome
    except StopExperiment:
        raise
    except BaseException as exc:
        outcome["status"] = "infrastructure_error"
        outcome["error_type"] = type(exc).__name__
        outcome["error_message"] = str(exc)[:2000]
        return outcome
    finally:
        outcome["wall_seconds"] = round(time.monotonic() - started, 3)
        write_json(evidence / "result.json", outcome)


def run_hive(task: dict, frozen: dict) -> dict:
    started = time.monotonic()
    evidence = EVIDENCE / task["id"] / "hive"
    evidence.mkdir(parents=True, exist_ok=True)
    outcome = {"task_id": task["id"], "condition": "hive", "status": "invalid",
               "applied": False, "promotion_allowed": False}
    request_body = {"request": task["request"], "allow_cloud": True,
                    "agent_backend": "persistent",
                    "persistent_agent_model": frozen["provider"]["model"],
                    "external_source_root": frozen["baseline"]["root"],
                    "allow_external_root": True, "frozen_junit_tests": [task["test"]],
                    "experiment": {"study_id": "HIVE-ASTRA-002",
                                   "condition_id": "hive", "task_id": task["id"],
                                   "replicate_index": 1, "trial_id": uuid.uuid4().hex[:12],
                                   "condition_spec_sha256": LOCK}}
    write_json(evidence / "request.json", request_body)
    try:
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=40) as client:
            response = client.post("/api/hive/build", json=request_body)
            if response.status_code != 200:
                raise RuntimeError(f"Hive build HTTP {response.status_code}: {response.text[:1500]}")
            job_id = response.json()["job_id"]
            outcome["job_id"] = job_id
            deadline = time.monotonic() + 8 * 3600
            observations = []
            while time.monotonic() < deadline:
                response = client.get(f"/api/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                state = job.get("state")
                if not observations or observations[-1]["state"] != state:
                    observations.append({"elapsed_seconds": round(time.monotonic() - started, 3),
                                         "state": state, "progress": job.get("progress")})
                    write_json(evidence / "stages.json", observations)
                if state in {"completed", "failed", "cancelled"}:
                    write_json(evidence / "job.json", job)
                    outcome["job_state"] = state
                    run = job.get("result")
                    if isinstance(run, dict):
                        write_json(evidence / "run.json", run)
                        outcome["run_id"] = run.get("id")
                        outcome["status"] = run.get("status", state)
                        outcome["changed_files"] = run.get("changed_files")
                        full_report = run.get("verification") or {}
                        checks = full_report.get("checks") or []
                        outcome["acceptance"] = next(
                            (check for check in checks
                             if check.get("name") == "frozen_junit_acceptance"), None)
                        outcome["full_gate"] = next(
                            (check for check in checks
                             if check.get("name") == "full_gradle_check"), None)
                        outcome["verification"] = {
                            "passed": full_report.get("passed"),
                            "isolation": full_report.get("isolation"),
                        }
                        if full_report:
                            assert_sealed_report(full_report, frozen)
                        outcome["review"] = run.get("review")
                        outcome["agent_calls"] = (run.get("metadata") or {}).get("agent_calls")
                        integrity = run.get("external_baseline_integrity") or {}
                        if integrity and (not integrity.get("baseline_unchanged")
                                          or not integrity.get("candidate_unchanged")):
                            raise StopExperiment("Hive external-root integrity violation")
                        if run.get("applied") or (run.get("metadata") or {}).get(
                                "external_root", {}).get("promotion_allowed"):
                            raise StopExperiment("Hive external-root promotion violation")
                        if any("spend limit" in str(error).lower() or
                               "insufficient_quota" in str(error).lower()
                               for error in run.get("errors", [])):
                            raise StopExperiment("Provider spend-limit refusal in Hive run")
                    else:
                        outcome["status"] = "job_" + str(state)
                        if any(word in str(job.get("error", "")).lower() for word in STOP_WORDS):
                            raise StopExperiment("Provider spend-limit refusal in Hive job")
                    return outcome
                time.sleep(5)
            outcome["status"] = "job_timeout"
            return outcome
    except StopExperiment:
        raise
    except BaseException as exc:
        outcome["status"] = "infrastructure_error"
        outcome["error_type"] = type(exc).__name__
        outcome["error_message"] = str(exc)[:2000]
        return outcome
    finally:
        outcome["wall_seconds"] = round(time.monotonic() - started, 3)
        write_json(evidence / "result.json", outcome)


def main() -> int:
    frozen = freeze()
    tasks = task_specs(frozen)
    operator_cap = os.environ.get("HIVE_ASTRA_002_OPERATOR_CAP_USD", "")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", operator_cap) or float(operator_cap) <= 0:
        raise StopExperiment("A separately authorized provider-side experiment cap is required")
    if EVIDENCE.exists():
        raise StopExperiment("Execution evidence already exists; no reruns permitted")
    preflight = preflight_pair(frozen, tasks, "PRESTART")
    EVIDENCE.mkdir(parents=True)
    write_json(EVIDENCE / "operator_constraint.json", {
        "source": "operator_confirmation",
        "provider_side_project_limit_usd": float(operator_cap),
        "independently_verified_by_workshop": False,
        "lock_sha256": LOCK, "preflight": preflight,
        "runner_sha256": RUNNER_HASH,
        "direct_prompt_template_sha256": sha(DIRECT_INSTRUCTIONS.encode("utf-8")),
        "prompt_template": DIRECT_INSTRUCTIONS,
    })
    record("experiment_started", {"lock_sha256": LOCK, "operator_limit_usd": float(operator_cap)})
    order = frozen["paired_evaluation"]["within_pair_order"]
    results = []
    try:
        for task in tasks:
            pair = [("hive", run_hive), ("direct", run_direct)]
            if order[task["id"]] == "direct-first":
                pair.reverse()
            pre = preflight_pair(frozen, tasks, task["id"])
            record("pair_preflight", pre)
            for name, action in pair:
                record("condition_started", {"task_id": task["id"], "condition": name})
                result = action(task, frozen)
                result["outcome_class"] = classify(result).value
                results.append(result)
                record("condition_finished", {"task_id": task["id"], "condition": name,
                                              "status": result.get("status"),
                                              "outcome_class": result["outcome_class"],
                                              "trial_id": result.get("trial_id"),
                                              "run_id": result.get("run_id")})
                write_json(EVIDENCE / "raw_results.json", results)
                if result.get("status") == "job_timeout":
                    raise StopExperiment("Hive job exceeded the execution driver deadline")
                if result["outcome_class"] in {Outcome.FALSE_ACCEPTANCE.value, Outcome.INVALID.value}:
                    raise StopExperiment("False acceptance or invalid condition evidence")
            record("pair_finished", {"task_id": task["id"]})
        record("experiment_complete", {"condition_runs": len(results)})
        return 0
    except StopExperiment as exc:
        record("experiment_stopped", {"reason": str(exc)})
        write_json(EVIDENCE / "raw_results.json", results)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
