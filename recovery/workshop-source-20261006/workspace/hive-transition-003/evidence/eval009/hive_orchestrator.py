"""Concurrent bounded observations plus dependency-ordered Hive workers."""
from __future__ import annotations

import argparse, concurrent.futures, hashlib, json, os, re, shutil, subprocess, sys, time, uuid
from pathlib import Path

from hive_java_symbols import JavaSymbolError, scoped_character_count

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "ATM-Companion"
RUNS = ROOT / "local-model-trial" / "orchestrated-runs"
GRADLE = Path(r"C:\Users\billy\.gradle\wrapper\dists\gradle-9.2.1-bin\2t0n5ozlw9xmuyvbp7dnzaxug\gradle-9.2.1\bin\gradle.bat")

SIGNATURE = re.compile(r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:record|class|enum|interface|[\w<>?,.\[\]]+)\s+[A-Za-z_$][\w$]*(?:\s*\([^;{}]*\))?\s*(?:\{|;)")
ACCEPTED = {"accepted", "accepted_after_environment_retry"}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def observe(spec: dict, output: Path) -> dict:
    started = time.time()
    records = []
    for relative in spec["read_only"]:
        path = PROJECT / relative
        text = path.read_text(encoding="utf-8", errors="replace")
        signatures = [line.strip() for line in text.splitlines() if SIGNATURE.match(line)][:160]
        records.append({"path": relative, "sha256": digest(path), "signatures": signatures, "characters": len(text)})
    result = {"id": spec["id"], "status": "complete", "started": started, "finished": time.time(), "records": records}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

def source_characters(child: dict) -> tuple[int, int]:
    total = 0
    scoped = 0
    target_symbols = list(child.get("target_symbols") or [])
    for relative in dict.fromkeys(child.get("writable", []) + child.get("read_only", [])):
        path = PROJECT / relative
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            total += len(text)
            if relative in child.get("writable", []) and target_symbols and path.suffix == ".java":
                scoped += scoped_character_count(text, relative, target_symbols)
            else:
                scoped += len(text)
    for spec in child.get("context_symbols", []):
        if "::" not in spec:
            raise JavaSymbolError(f"invalid context symbol {spec!r}")
        relative, symbol = spec.rsplit("::", 1)
        path = PROJECT / relative
        text = path.read_text(encoding="utf-8", errors="replace")
        scoped += scoped_character_count(text, relative, [symbol])
    return scoped, total

def route_children(plan: dict) -> tuple[list[dict], list[dict]]:
    """Recursively apply the existing frozen size policy before model work."""
    policy = plan.get("budget_policy", {})
    limit = int(policy.get("max_local_context_characters", 60_000))
    max_depth = int(policy.get("max_decomposition_depth", 3))
    max_children = int(policy.get("max_generated_children", 16))
    routed, decisions = [], []

    def visit(child: dict, depth: int) -> None:
        if len(routed) >= max_children:
            raise ValueError(f"recursive decomposition exceeded {max_children} generated children")
        size, full_size = source_characters(child)
        replacements = child.get("decompose_into", [])
        if size > limit and replacements:
            if depth >= max_depth:
                selected = dict(child)
                selected["force_escalation"] = True
                routed.append(selected)
                decisions.append({"child": child["id"], "decision": "decomposition_limit", "characters": size, "fullCharacters": full_size, "limit": limit, "depth": depth})
                return
            decisions.append({"child": child["id"], "decision": "decompose", "characters": size, "fullCharacters": full_size, "limit": limit, "depth": depth, "children": [item["id"] for item in replacements]})
            for replacement in replacements:
                visit(replacement, depth + 1)
        else:
            selected = dict(child)
            if size > limit:
                selected["force_escalation"] = True
                decision = "escalate"
            elif child.get("target_symbols"):
                decision = "local_symbol_scope"
            else:
                decision = "local"
            routed.append(selected)
            decisions.append({"child": child["id"], "decision": decision, "characters": size, "fullCharacters": full_size, "limit": limit, "depth": depth})

    for child in plan["children"]:
        visit(child, 0)
    return routed, decisions

def copy_project(destination: Path) -> None:
    shutil.copytree(PROJECT, destination, ignore=shutil.ignore_patterns(".gradle", "build", "run-gametest", "run-questtest", ".git", ".vscode", ".idea"))

def assemble_bundle(run: Path, plan: dict, children: list[dict], overlays: dict[str, Path], state: dict) -> tuple[bool, dict]:
    bundle = run / "promotion-bundle"
    candidate = bundle / "ATM-Companion"
    copy_project(candidate)
    promoted_files = {}
    for child in children:
        accepted = overlays[child["id"]]
        for relative in child["writable"]:
            source = accepted / "ATM-Companion" / relative
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            promoted_files[relative] = {"sha256": digest(target), "sourceRun": str(accepted)}
    frozen = {}
    for child in children:
        for relative in child.get("frozen_tests", []):
            source = overlays[child["id"]] / "ATM-Companion" / relative
            if relative not in frozen:
                frozen[relative] = digest(source)
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    frozen_changed = [relative for relative, expected in frozen.items() if digest(candidate / relative) != expected]
    env = os.environ.copy()
    env.update({"JAVA_HOME": str(ROOT / "jdk-21.0.12.1+1"), "PYTHONIOENCODING": "utf-8"})
    gradle_executable = GRADLE if GRADLE.is_file() else candidate / "gradlew.bat"
    command = plan.get("final_acceptance_command") or [str(gradle_executable), "test", "--no-daemon", "--console=plain", "-Dorg.gradle.jvmargs=-Xmx512m", "--max-workers=2", "--rerun-tasks", "--no-build-cache"]
    with (bundle / "acceptance.log").open("w", encoding="utf-8") as stream:
        gate = subprocess.run(command, cwd=candidate, env=env, stdout=stream, stderr=subprocess.STDOUT, text=True)
    manifest = {"status": "verified" if gate.returncode == 0 and not frozen_changed else "rejected", "manualPromotion": True, "promoted": False, "files": promoted_files, "frozenTests": frozen, "frozenTestsChanged": frozen_changed, "acceptanceCommand": command, "acceptanceExitCode": gate.returncode, "orchestrationResult": str(run / "result.json")}
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest["status"] == "verified", manifest

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--observe-only", action="store_true")
    parser.add_argument("--escalate", action="store_true", help="Escalate a rejected local child to the configured stronger worker")
    parser.add_argument("--escalation-model", default=os.environ.get("HIVE_ESCALATION_MODEL", ""), help="Optional Codex model override; empty uses the account configuration")
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    children, routing = route_children(plan)
    run = RUNS / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    observations_dir = run / "observations"
    observations_dir.mkdir(parents=True)
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(plan.get("observations", [])) or 1)) as pool:
        futures = {pool.submit(observe, spec, observations_dir / f"{spec['id']}.json"): spec["id"] for spec in plan.get("observations", [])}
        observed = {ident: future.result() for future, ident in futures.items()}
    ordered = [observed[spec["id"]] for spec in plan.get("observations", [])]
    (run / "context-bundle.json").write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    state = {"status": "observed" if args.observe_only else "children_pending", "started": started, "observationsFinished": time.time(), "routing": routing, "children": [], "manualPromotion": True}
    (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if args.observe_only:
        print(run)
        return 0
    overlays: dict[str, Path] = {}
    for child in children:
        if not child.get("frozen_tests"):
            state.update(status="plan_invalid", reason=f"{child['id']} lacks frozen_tests")
            (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            print(run)
            return 2
        if any(dep not in overlays for dep in child.get("depends_on", [])):
            state.update(status="dependency_blocked", reason=child["id"])
            (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            print(run)
            return 3
        seeds = [f"{item['path']}={ROOT / item['source']}" for item in child.get("seed", [])]
        for dep in child.get("depends_on", []):
            dep_child = next(item for item in children if item["id"] == dep)
            for relative in dep_child["writable"]:
                seeds.append(f"{relative}={overlays[dep] / 'ATM-Companion' / relative}")
        candidate = None
        completed = 1
        child_result = {"status": "skipped_for_escalation"}
        child_started = time.time()
        if not child.get("force_escalation"):
            before = {p.name for p in (ROOT / "local-model-trial" / "runs").glob("*") if p.is_dir()}
            command = [sys.executable, str(ROOT / "local-model-trial" / "hive_pipeline.py"),
                   "--task", str(ROOT / child["contract"]), "--writable", *child["writable"],
                   "--context", *child.get("read_only", []), "--frozen-tests", *child["frozen_tests"],
                   "--max-repairs", str(plan.get("max_repairs_per_child", 2)),
                   "--model-timeout", str(plan.get("budget_policy", {}).get("local_attempt_timeout_seconds", 900)),
                   "--observation-bundle", str(run / "context-bundle.json")]
            if seeds: command += ["--seed", *seeds]
            if child.get("forbidden_symbols"): command += ["--forbid-symbol", *child["forbidden_symbols"]]
            if child.get("edit_format"): command += ["--edit-format", child["edit_format"]]
            if child.get("max_changed_lines") is not None: command += ["--max-changed-lines", str(child["max_changed_lines"])]
            if child.get("preflight"): command += ["--preflight", str(ROOT / child["preflight"])]
            if child.get("target_symbols"): command += ["--target-symbol", *child["target_symbols"]]
            if child.get("allowed_new_symbols"): command += ["--allow-new-symbol", *child["allowed_new_symbols"]]
            if child.get("new_symbol_stubs"): command += ["--new-symbol-stubs", json.dumps(child["new_symbol_stubs"])]
            if child.get("required_obligations"): command += ["--required-obligations", *child["required_obligations"]]
            if child.get("symbol_markers"): command += ["--symbol-markers", json.dumps(child["symbol_markers"])]
            for context_symbol in child.get("context_symbols", []):
                command += ["--context-symbol", context_symbol]
            completed = subprocess.run(command, cwd=ROOT, env=os.environ.copy()).returncode
            new_runs = [p for p in (ROOT / "local-model-trial" / "runs").glob("*") if p.is_dir() and p.name not in before]
            candidate = max(new_runs, key=lambda p: p.stat().st_mtime) if new_runs else None
            child_result = json.loads((candidate / "result.json").read_text(encoding="utf-8")) if candidate and (candidate / "result.json").is_file() else {"status": "missing_result"}
        state["children"].append({"id": child["id"], "started": child_started, "finished": time.time(), "exitCode": completed, "run": str(candidate) if candidate else None, "result": child_result})
        accepted_run = candidate
        if child.get("force_escalation") or completed != 0 or child_result.get("status") not in ACCEPTED:
            if not args.escalate or (not candidate and not child.get("force_escalation")):
                state["status"] = "escalation_required" if not args.escalate else "child_rejected"
                state["escalation"] = {"eligible": True, "attempted": False, "child": child["id"]}
                (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                print(run)
                return 4
            escalation = [sys.executable, str(ROOT / "local-model-trial" / "hive_escalation.py"),
                          "--task", str(ROOT / child["contract"]), "--writable", *child["writable"],
                          "--context", *child.get("read_only", []), "--frozen-tests", *child["frozen_tests"],
                          "--observation-bundle", str(run / "context-bundle.json"), "--failed-run", str(candidate or run)]
            if args.escalation_model:
                escalation += ["--model", args.escalation_model]
            if seeds:
                escalation += ["--seed", *seeds]
            escalation_started = time.time()
            before_escalations = {p.name for p in (ROOT / "local-model-trial" / "escalation-runs").glob("*") if p.is_dir()}
            escalation_code = subprocess.run(escalation, cwd=ROOT, env=os.environ.copy()).returncode
            new_escalations = [p for p in (ROOT / "local-model-trial" / "escalation-runs").glob("*") if p.is_dir() and p.name not in before_escalations]
            escalated_run = max(new_escalations, key=lambda p: p.stat().st_mtime) if new_escalations else None
            escalated_result = json.loads((escalated_run / "result.json").read_text(encoding="utf-8")) if escalated_run and (escalated_run / "result.json").is_file() else {"status": "missing_result"}
            escalation_record = {"eligible": True, "attempted": True, "worker": "codex", "model": args.escalation_model, "started": escalation_started, "finished": time.time(), "exitCode": escalation_code, "run": str(escalated_run) if escalated_run else None, "result": escalated_result}
            state["children"][-1]["escalation"] = escalation_record
            if escalation_code != 0 or escalated_result.get("status") not in ACCEPTED:
                state["status"] = "escalation_rejected"
                (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                print(run)
                return 5
            accepted_run = escalated_run
        overlays[child["id"]] = accepted_run
    state["status"] = "assembling_bundle"
    (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    verified, manifest = assemble_bundle(run, plan, children, overlays, state)
    state["status"] = "ready_for_promotion" if verified else "final_gate_rejected"
    state["promotionBundle"] = str(run / "promotion-bundle")
    state["finalAcceptance"] = manifest
    state["promoted"] = False
    (run / "result.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(run)
    return 0 if verified else 6

if __name__ == "__main__":
    raise SystemExit(main())
