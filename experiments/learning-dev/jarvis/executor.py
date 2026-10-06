from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from .codex_agent import (
    INTERNAL_CONTROL_DIR_ENV,
    _codex_environment,
    _python_runtime_paths,
    _run_bounded,
)


class ExecutionError(RuntimeError):
    pass


_OUTCOME_FIELDS = {"success", "summary", "files_changed", "verification", "blocker"}


def _typed_builtin_outcome(raw: str) -> dict:
    """Re-validate the built-in adapter's final JSON before persisting it.

    Custom adapters and command stdout are intentionally never promoted to this
    trusted field; their output remains an opaque process log.
    """
    try:
        outcome = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExecutionError("built-in agent returned an invalid final outcome") from exc
    if not isinstance(outcome, dict) or set(outcome) != _OUTCOME_FIELDS:
        raise ExecutionError("built-in agent final outcome has unexpected fields")
    if not isinstance(outcome["success"], bool) or not isinstance(outcome["summary"], str):
        raise ExecutionError("built-in agent final outcome has invalid success or summary fields")
    if not isinstance(outcome["files_changed"], list) or not all(
        isinstance(item, str) for item in outcome["files_changed"]
    ):
        raise ExecutionError("built-in agent final outcome has invalid files_changed")
    if not isinstance(outcome["verification"], list) or not all(
        isinstance(item, str) for item in outcome["verification"]
    ):
        raise ExecutionError("built-in agent final outcome has invalid verification")
    if outcome["blocker"] is not None and not isinstance(outcome["blocker"], str):
        raise ExecutionError("built-in agent final outcome has invalid blocker")
    return outcome


def _workspace(task) -> Path:
    root = Path(task["workspace"]).resolve()
    if not root.is_dir():
        raise ExecutionError(f"workspace does not exist: {root}")
    configured_roots = os.environ.get("JARVIS_WORKSPACE_ROOTS", "").strip()
    if configured_roots:
        try:
            raw_roots = json.loads(configured_roots)
        except json.JSONDecodeError:
            raw_roots = configured_roots.split(os.pathsep)
        if not isinstance(raw_roots, list) or not all(isinstance(item, str) and item for item in raw_roots):
            raise ExecutionError("JARVIS_WORKSPACE_ROOTS must be a JSON string array or path-separated list")
        allowed = [Path(item).expanduser().resolve() for item in raw_roots]
        if not any(root == candidate or root.is_relative_to(candidate) for candidate in allowed):
            raise ExecutionError(f"workspace is outside JARVIS_WORKSPACE_ROOTS: {root}")
    return root


def _agent_command() -> list[str]:
    """Resolve the external-agent argv without invoking a shell.

    JSON argv is the safest override on every platform. The legacy string form is
    retained for compatibility, while the bundled Codex adapter is the default.
    """
    configured_json = os.environ.get("JARVIS_AGENT_COMMAND_JSON", "").strip()
    if configured_json:
        try:
            command = json.loads(configured_json)
        except json.JSONDecodeError as exc:
            raise ExecutionError(f"invalid JARVIS_AGENT_COMMAND_JSON: {exc}") from exc
    else:
        configured = os.environ.get("JARVIS_AGENT_COMMAND", "").strip()
        if configured:
            command = shlex.split(configured)
        else:
            command = [sys.executable, str(Path(__file__).with_name("codex_agent.py"))]
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise ExecutionError("agent command must be a non-empty JSON string array")
    return command


def _custom_agent_configured() -> bool:
    return bool(
        os.environ.get("JARVIS_AGENT_COMMAND_JSON", "").strip()
        or os.environ.get("JARVIS_AGENT_COMMAND", "").strip()
    )


def _agent_environment(task_id: str, custom: bool, control_dir: str | None = None) -> dict[str, str]:
    child = _codex_environment()
    if custom:
        allowed_raw = os.environ.get("JARVIS_AGENT_ALLOW_ENV", "")
        allowed = {item.strip().upper() for item in allowed_raw.split(",") if item.strip()}
        for name, value in os.environ.items():
            if name.upper() in allowed:
                child[name] = value
        if allowed_raw:
            child["JARVIS_AGENT_ALLOW_ENV"] = allowed_raw
    else:
        if not control_dir:
            raise ExecutionError("the built-in Codex adapter requires a protected control directory")
        child[INTERNAL_CONTROL_DIR_ENV] = control_dir
    child["JARVIS_TASK_ID"] = task_id
    return child


def _protect_supervisor_state(task: dict, root: Path) -> None:
    if task["kind"] != "agent" or not task["mutating"]:
        return
    drive_root = Path(root.anchor).resolve()
    user_home = Path.home().resolve()
    if root == drive_root or root == user_home or user_home.is_relative_to(root):
        raise ExecutionError("mutating agent workspace is too broad; select a project directory")
    values = [
        *task.get("_protected_paths", []),
        str(Path(__file__).resolve().parent.parent),
        *(str(path) for path in _python_runtime_paths()),
    ]
    for value in values:
        protected = Path(value).expanduser().resolve()
        if protected == root or protected.is_relative_to(root) or root.is_relative_to(protected):
            raise ExecutionError(
                f"mutating agent workspace contains protected Jarvis state or runtime: {protected}"
            )


def execute(task: dict) -> dict:
    root = _workspace(task)
    _protect_supervisor_state(task, root)
    payload = task["payload"]
    if task["kind"] == "inspect":
        try:
            max_files = int(payload.get("max_files", 200))
        except (OverflowError, TypeError, ValueError) as exc:
            raise ExecutionError("inspect max_files must be an integer") from exc
        max_files = max(1, min(max_files, 100_000))
        files = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size})
                if len(files) >= max_files:
                    break
        return {"workspace": str(root), "files": files, "truncated": len(files) == max_files}

    if task["kind"] not in {"command", "agent"}:
        raise ExecutionError(f"unknown task kind: {task['kind']}")

    try:
        timeout = int(payload.get("timeout", 900))
    except (OverflowError, TypeError, ValueError) as exc:
        raise ExecutionError("task timeout must be an integer") from exc
    timeout = max(1, min(timeout, 86_400))
    if task["kind"] == "agent":
        custom = _custom_agent_configured()
        if custom and not task["mutating"]:
            raise ExecutionError("custom agent connectors require an approved mutating task")
        if task["mutating"] and task.get("approval") != "APPROVED":
            raise ExecutionError("mutating agent task is not approved")
        command = _agent_command()
        stdin = json.dumps({
            "contract_version": 1,
            "task_id": task["id"],
            "goal": task["goal"],
            "workspace": str(root),
            "lessons": payload.get("lessons", []),
            "mutating": bool(task["mutating"]),
            "approval": task.get("approval", "NOT_REQUIRED"),
            "timeout_seconds": timeout,
        })
    else:
        custom = False
        if not task.get("mutating") or task.get("approval") != "APPROVED":
            raise ExecutionError("command tasks are mutating and require approval")
        command = payload.get("command")
        stdin = payload.get("stdin")

    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise ExecutionError("command must be a non-empty JSON string array")
    if stdin is not None and not isinstance(stdin, str):
        raise ExecutionError("process stdin must be a string or null")
    # The adapter owns the model deadline; allow bounded Windows ACL setup and
    # process-tree cleanup to finish before the supervisor's outer kill fence.
    process_timeout = timeout + 120 if task["kind"] == "agent" else timeout
    environment = (
        _agent_environment(task["id"], custom, task.get("_control_dir"))
        if task["kind"] == "agent"
        else {**os.environ, "JARVIS_TASK_ID": task["id"]}
    )
    returncode, stdout, stderr, timed_out = _run_bounded(
        command,
        cwd=root,
        prompt=stdin,
        timeout=process_timeout,
        require_crash_safe=bool(task["mutating"]),
        env=environment,
    )
    result = {"command": command, "exit_code": returncode, "stdout": stdout, "stderr": stderr}
    if timed_out:
        raise ExecutionError(json.dumps({**result, "timed_out": True}))
    if returncode != 0:
        raise ExecutionError(json.dumps(result))
    if task["kind"] == "agent" and not custom:
        result["outcome"] = _typed_builtin_outcome(stdout)
    return result
