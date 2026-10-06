"""Bounded local-model implementation loop for ATM Companion.

The pipeline never edits the production checkout while Qwen is working. Tests
are copied into the isolated checkout before the model runs and are never
passed to Aider as writable files. Only a declared production scope is
eligible for promotion after the full Gradle suite passes.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from hive_java_symbols import (
    JavaSymbolError,
    build_scoped_projection,
    merge_scoped_projection,
    select_java_symbol_context,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "ATM-Companion"
TRIALS = ROOT / "local-model-trial" / "runs"
JAVA_HOME = Path(r"C:\Users\billy\AppData\Roaming\PrismLauncher\java\java-runtime-delta")
AIDER = Path(r"C:\Users\billy\.local\bin\aider.exe")
GRADLE = Path(r"C:\Users\billy\.gradle\wrapper\dists\gradle-9.2.1-bin\2t0n5ozlw9xmuyvbp7dnzaxug\gradle-9.2.1\bin\gradle.bat")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int | None = None) -> int:
    with log.open("w", encoding="utf-8") as stream:
        try:
            process = subprocess.run(cmd, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            stream.write(f"\nPIPELINE TIMEOUT after {timeout} seconds\n")
            return 124
    return process.returncode


def junit_feedback(project: Path) -> str:
    failures: list[str] = []
    for report in (project / "build" / "test-results" / "test").glob("TEST-*.xml"):
        try:
            suite = ET.parse(report).getroot()
        except (ET.ParseError, OSError):
            continue
        for case in suite.findall("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            detail = failure if failure is not None else error
            if detail is not None:
                failures.append(
                    f"{case.get('classname')}.{case.get('name')}: "
                    f"{detail.get('message', '').strip()}\n{(detail.text or '').strip()[-3000:]}"
                )
    return "\n\n".join(failures) or "No parseable JUnit failure details were found; inspect the Gradle log."


def copy_project(destination: Path) -> None:
    ignored = shutil.ignore_patterns(".gradle", "build", "run-gametest", "run-questtest", ".git", ".vscode", ".idea")
    shutil.copytree(PROJECT, destination, ignore=ignored)


def gradle_environment_failure(log: Path) -> str | None:
    text = log.read_text(encoding="utf-8", errors="replace")
    markers = {
        "gradle_distribution_unavailable": "Downloading https://services.gradle.org/distributions/",
        "dependency_resolution_unavailable": "could not resolve plugin artifact",
        "network_permission_denied": "Permission denied: getsockopt",
    }
    for reason, marker in markers.items():
        if marker.lower() in text.lower():
            return reason
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Path to the human-authored contract prompt")
    parser.add_argument("--writable", nargs="+", required=True, help="Production paths relative to the project")
    parser.add_argument("--context", nargs="*", default=[], help="Read-only production paths relative to the project")
    parser.add_argument("--seed", nargs="*", default=[], help="Isolated-only overlays as relative=source paths")
    parser.add_argument("--exclude", nargs="*", default=[], help="Paths to remove from the isolated checkout")
    parser.add_argument("--frozen-tests", nargs="+", required=True, help="Test paths relative to the project")
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--model-timeout", type=int, default=900)
    parser.add_argument("--forbid-symbol", nargs="*", default=[], help="Reject writable candidates containing nonexistent or forbidden API spellings before Gradle")
    parser.add_argument("--observation-bundle", help="Bounded structured read-only observations to append to the worker contract")
    parser.add_argument("--edit-format", default=None, help="Override Aider's edit format for this worker")
    parser.add_argument("--max-changed-lines", type=int, default=None, help="Reject a candidate whose production diff exceeds this many added/deleted lines")
    parser.add_argument("--preflight", help="Python validator invoked with BASELINE_ROOT CANDIDATE_ROOT before Gradle")
    parser.add_argument("--target-symbol", nargs="*", default=[], help="Existing Java methods that may be edited through a Hive exact-symbol projection")
    parser.add_argument("--allow-new-symbol", nargs="*", default=[], help="New Java methods permitted in a symbol-scoped projection")
    parser.add_argument("--new-symbol-stubs", default="{}", help="JSON object mapping permitted new Java method names to insertion stubs")
    parser.add_argument("--required-obligations", nargs="*", default=[], help="Exact adapter obligations appended to the worker prompt")
    parser.add_argument("--symbol-markers", default="{}", help="JSON object mapping editable Java symbols to insertion marker names")
    parser.add_argument("--context-symbol", action="append", default=[], help="Read-only Java symbol as relative/path.java::method")
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    new_symbol_stubs = json.loads(args.new_symbol_stubs)
    if not isinstance(new_symbol_stubs, dict):
        raise SystemExit("--new-symbol-stubs must decode to a JSON object")
    symbol_markers = json.loads(args.symbol_markers)
    if not isinstance(symbol_markers, dict):
        raise SystemExit("--symbol-markers must decode to a JSON object")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    evidence = TRIALS / run_id
    isolated = evidence / "ATM-Companion"
    evidence.mkdir(parents=True, exist_ok=False)
    copy_project(isolated)
    baseline = evidence / "baseline"
    copy_project(baseline)
    for spec in args.seed:
        relative, source = spec.split("=", 1)
        target = isolated / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source), target)
    for relative in args.exclude:
        target = isolated / relative
        if target.is_file():
            target.unlink()
    frozen = {p: sha(isolated / p) for p in args.frozen_tests}
    task = Path(args.task).read_text(encoding="utf-8")
    if args.observation_bundle:
        observed = Path(args.observation_bundle).read_text(encoding="utf-8", errors="replace")[:24000]
        task += "\n\nAuthoritative bounded repository observations:\n" + observed
    symbol_contexts = []
    for spec in args.context_symbol:
        if "::" not in spec:
            raise SystemExit(f"invalid --context-symbol {spec!r}; expected relative/path.java::method")
        relative, symbol = spec.rsplit("::", 1)
        text = (isolated / relative).read_text(encoding="utf-8", errors="replace")
        selected = select_java_symbol_context(text, relative, symbol)
        symbol_contexts.append({
            "path": relative,
            "symbol": symbol,
            "symbolId": selected["selected_block"]["symbol_id"],
            "context": selected["prompt_context_text"],
            "contextBudget": selected["context_budget"],
        })
    if symbol_contexts:
        task += "\n\nAuthoritative Hive exact-symbol read-only context:\n" + json.dumps(symbol_contexts, indent=2)
    (evidence / "contract.txt").write_text(task, encoding="utf-8")
    boundary = {"writable": args.writable, "frozenTests": frozen, "promote": args.promote, "targetSymbols": args.target_symbol, "allowedNewSymbols": args.allow_new_symbol}
    (evidence / "boundary.json").write_text(json.dumps(boundary, indent=2) + "\n", encoding="utf-8")
    if symbol_contexts:
        (evidence / "symbol-context.json").write_text(json.dumps(symbol_contexts, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env.update({"JAVA_HOME": str(JAVA_HOME), "OLLAMA_API_BASE": "http://localhost:11434", "DO_NOT_TRACK": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "PYTHONIOENCODING": "utf-8"})
    config = ROOT / "local-model-trial" / "m4-activity-service"
    results = []
    for attempt in range(args.max_repairs + 1):
        mode = ("\n\nExecution mode: no_think. Do not narrate reasoning or provide a tutorial. Inspect the repository, edit only the allowed production file(s), and stop immediately after applying the edit.\n")
        prompt = (task + mode) if attempt == 0 else task + mode + "\nRepair only the production code using the exact failure below. Do not edit tests. Do not invent APIs absent from the supplied signatures.\n\nJUnit failure details:\n" + junit_feedback(isolated) + "\n\nAcceptance failure:\n" + (evidence / f"gradle-{attempt - 1}.log").read_text(encoding="utf-8", errors="replace")[-2500:]
        if args.required_obligations:
            prompt += (
                "\n\nHIVE CONTRACT OBLIGATIONS (machine-checked; satisfy every item exactly):\n"
                + "\n".join(f"- {item}" for item in args.required_obligations)
                + "\nDo not substitute a familiar API or nest a command under another command.\n"
            )
        prompt_file = evidence / f"prompt-{attempt}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        files = [isolated / p for p in args.writable]
        scoped_targets: list[tuple[Path, Path, str]] = []
        if args.target_symbol or args.allow_new_symbol:
            if len(args.writable) != 1 or Path(args.writable[0]).suffix != ".java":
                raise SystemExit("symbol-scoped mode currently requires exactly one writable Java file")
            relative = args.writable[0]
            full_path = isolated / relative
            full_text = full_path.read_text(encoding="utf-8", errors="replace")
            projection = build_scoped_projection(
                full_text,
                relative,
                target_symbols=args.target_symbol,
                allowed_new_symbols=args.allow_new_symbol,
                new_symbol_stubs=new_symbol_stubs,
                symbol_markers=symbol_markers,
            )
            scoped_path = evidence / "scoped-work" / relative
            scoped_path.parent.mkdir(parents=True, exist_ok=True)
            scoped_path.write_text(projection, encoding="utf-8")
            files = [scoped_path]
            scoped_targets.append((scoped_path, full_path, relative))
            prompt += (
                "\n\nHIVE EXACT-SYMBOL EDIT BOUNDARY:\n"
                f"- Edit the supplied scoped projection for {relative}.\n"
                f"- Existing editable methods: {', '.join(args.target_symbol) or 'none'}.\n"
                f"- Permitted new methods: {', '.join(args.allow_new_symbol) or 'none'}.\n"
                "- The controller will merge only those methods into the complete source file and reject undeclared methods.\n"
            )
            if symbol_markers:
                prompt += "- Replace the named insertion marker(s) in-place; preserve all surrounding syntax.\n"
            prompt_file.write_text(prompt, encoding="utf-8")
        cmd = [str(AIDER), "--config", str(config / "aider.yml"), "--env-file", str(config / "empty.env"), "--model-settings-file", str(config / "model-settings.yml"), "--model-metadata-file", str(config / "model-metadata.json"), "--message-file", str(prompt_file)]
        for path in files:
            cmd += ["--file", str(path)]
        for relative in args.context:
            cmd += ["--read", str(isolated / relative)]
        cmd += ["--max-chat-history-tokens", "12000", "--no-auto-commits"]
        if args.edit_format:
            cmd += ["--edit-format", args.edit_format]
        code = run(cmd, isolated, env, evidence / f"qwen-{attempt}.log", timeout=args.model_timeout)
        if code != 0:
            result = {"status": "model_timeout" if code == 124 else "model_process_failed", "run": str(evidence), "attempt": attempt, "promoted": False}
            (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return 2
        try:
            for scoped_path, full_path, relative in scoped_targets:
                original = full_path.read_text(encoding="utf-8", errors="replace")
                edited_projection = scoped_path.read_text(encoding="utf-8", errors="replace")
                merged = merge_scoped_projection(
                    original,
                    edited_projection,
                    relative,
                    target_symbols=args.target_symbol,
                    allowed_new_symbols=args.allow_new_symbol,
                )
                full_path.write_text(merged, encoding="utf-8")
        except JavaSymbolError as exception:
            (evidence / f"gradle-{attempt}.log").write_text(
                "PRE-GRADLE JAVA SYMBOL VALIDATION FAILED\n" + str(exception) + "\n",
                encoding="utf-8",
            )
            results.append({"attempt": attempt, "gradleExitCode": None, "preflight": "java_symbol_scope", "detail": str(exception)})
            continue
        for path, expected in frozen.items():
            if sha(isolated / path) != expected:
                (evidence / "result.json").write_text(json.dumps({"status": "frozen_test_modified", "attempt": attempt}, indent=2) + "\n", encoding="utf-8")
                return 3
        forbidden_hits = []
        for relative in args.writable:
            candidate_text = (isolated / relative).read_text(encoding="utf-8", errors="replace")
            for symbol in args.forbid_symbol:
                if symbol in candidate_text:
                    forbidden_hits.append(f"{relative}: forbidden/nonexistent API '{symbol}'")
        if forbidden_hits:
            (evidence / f"gradle-{attempt}.log").write_text(
                "PRE-GRADLE SYMBOL VALIDATION FAILED\n" + "\n".join(forbidden_hits) + "\n",
                encoding="utf-8",
            )
            results.append({"attempt": attempt, "gradleExitCode": None, "preflight": "forbidden_symbol"})
            continue
        if args.max_changed_lines is not None:
            changed_lines = 0
            for relative in args.writable:
                old = (baseline / relative).read_text(encoding="utf-8", errors="replace").splitlines()
                new = (isolated / relative).read_text(encoding="utf-8", errors="replace").splitlines()
                for line in difflib.ndiff(old, new):
                    if line.startswith("+ ") or line.startswith("- "):
                        changed_lines += 1
            if changed_lines > args.max_changed_lines:
                (evidence / f"gradle-{attempt}.log").write_text(
                    f"PRE-GRADLE DIFF BUDGET FAILED\nChanged lines: {changed_lines}\nMaximum: {args.max_changed_lines}\n",
                    encoding="utf-8",
                )
                results.append({"attempt": attempt, "gradleExitCode": None, "preflight": "diff_budget", "changedLines": changed_lines})
                continue
        if args.preflight:
            preflight_log = evidence / f"preflight-{attempt}.log"
            preflight_code = run([sys.executable, str(Path(args.preflight).resolve()), str(baseline), str(isolated)], ROOT, env, preflight_log)
            if preflight_code != 0:
                (evidence / f"gradle-{attempt}.log").write_text(
                    "PRE-GRADLE STRUCTURAL VALIDATION FAILED\n" + preflight_log.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
                results.append({"attempt": attempt, "gradleExitCode": None, "preflight": "structural"})
                continue
        gradle_executable = GRADLE if GRADLE.is_file() else isolated / "gradlew.bat"
        gradle = [str(gradle_executable), "test", "--no-daemon", "--console=plain", "-Dorg.gradle.jvmargs=-Xmx512m", "--max-workers=2", "--rerun-tasks", "--no-build-cache"]
        code = run(gradle, isolated, env, evidence / f"gradle-{attempt}.log")
        results.append({"attempt": attempt, "gradleExitCode": code})
        if code == 0:
            result = {"status": "accepted", "run": str(evidence), "attempts": results, "promoted": False}
            (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            if args.promote:
                for relative in args.writable:
                    source = isolated / relative
                    target = PROJECT / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                result["promoted"] = True
                (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return 0
        environment_failure = gradle_environment_failure(evidence / f"gradle-{attempt}.log")
        if environment_failure:
            result = {"status": "environment_failure", "reason": environment_failure, "run": str(evidence), "attempts": results, "promoted": False}
            (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return 4
    preflights = [item.get("preflight") for item in results if item.get("preflight")]
    final_status = "repeated_structural_failure" if len(preflights) > 1 and len(set(preflights)) == 1 else ("structural_failure" if preflights else "rejected")
    (evidence / "result.json").write_text(json.dumps({"status": final_status, "run": str(evidence), "attempts": results, "promoted": False}, indent=2) + "\n", encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
