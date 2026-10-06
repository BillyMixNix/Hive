"""Successor factorial controller wiring; no model or benchmark is run here.

The caller owns the frozen task, local-only provider, token/wall budgets, sealed
verifier, and evidence directory. This adapter owns the controller-specific
planner/reviewer behavior and passes the task's exact write scope to Hive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Awaitable, Callable

from workshop import hive


AgentCall = Callable[[str, str], Awaitable[str]]


def _single_plan(request: str, files: list[str]) -> dict:
    return {
        "summary": request,
        "ui_goal": "no change needed",
        "backend_goal": request,
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": files, "tests": []},
        "interface_contracts": [],
        "provider_changes": [],
        "acceptance": [request],
        "worker_acceptance": {"ui": [], "backend": [request], "tests": []},
    }


async def run_condition(
    *,
    controller: str,
    task: dict,
    candidate: Path,
    runs: Path,
    model: str,
    provider_call: AgentCall,
    metadata: dict,
    run_id: str,
) -> dict:
    """Run either frozen controller with the same host-authorized file list.

    Planner responses from the Hive arm are returned unchanged to Hive. Hive
    records out-of-scope plans and spends its existing single correction there;
    this callback never converts such a response into a runtime exception.
    """
    if controller not in {"single", "hive"}:
        raise ValueError("controller must be single or hive")
    request = task["request"]
    files = task["files"]
    if not isinstance(request, str) or not request or not isinstance(files, list):
        raise ValueError("task must supply a request and exact file list")

    async def agent_call(role: str, prompt: str) -> str:
        if controller == "single":
            if role == "planner":
                return json.dumps(_single_plan(request, files))
            if role == "reviewer":
                return json.dumps({"approve": True, "summary": "Single-agent host gate", "issues": [], "confidence": 1.0})
            if role != "backend":
                raise ValueError(f"single-agent condition unexpectedly requested {role}")
        return await provider_call(role, prompt)

    return await hive.run_build(
        candidate, runs, request, model, agent_call,
        metadata=metadata, run_id=run_id, external_root_mode=True,
        allowed_write_files=files,
    )
