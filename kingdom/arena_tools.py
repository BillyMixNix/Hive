from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .arena import ArenaObservation, ToolRequest


class PytestTool:
    """Host-owned pytest adapter with a deliberately narrow request surface.

    Models provide test node IDs, not command-line flags or shell fragments.
    Every selector must resolve to a Python file under an allowed test root.
    """

    name = "pytest"

    def __init__(
        self,
        root: str | Path = ".",
        *,
        allowed_roots: Sequence[str] = ("tests",),
        timeout: float = 90.0,
        max_selectors: int = 20,
        max_output_chars: int = 16000,
    ):
        self.root = Path(root).resolve()
        self.allowed_roots = tuple(str(item).strip("/\\") for item in allowed_roots if str(item).strip())
        self.timeout = timeout
        self.max_selectors = max_selectors
        self.max_output_chars = max_output_chars

    def _validate_selector(self, raw: str) -> str:
        selector = str(raw).strip()
        if not selector:
            raise ValueError("pytest selector cannot be empty")
        if selector.startswith("-") or "\n" in selector or "\r" in selector or "\x00" in selector:
            raise ValueError("pytest flags/control characters are not allowed")
        path_part = selector.split("::", 1)[0]
        if not path_part.endswith(".py"):
            raise ValueError("pytest selector must reference a .py test file")
        candidate = (self.root / path_part).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("pytest selector escapes repository root")
        try:
            relative = candidate.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ValueError("pytest selector escapes repository root") from exc
        if not any(relative == prefix or relative.startswith(prefix + "/") for prefix in self.allowed_roots):
            raise ValueError("pytest selector is outside allowed test roots")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        suffix = selector[len(path_part) :]
        return relative + suffix

    def execute(self, request: ToolRequest) -> ArenaObservation:
        if request.operation != "run":
            raise ValueError("pytest supports only operation='run'")
        raw = request.payload.get("selectors")
        if not isinstance(raw, list) or not raw:
            raise ValueError("pytest payload requires non-empty selectors list")
        if len(raw) > self.max_selectors:
            raise ValueError("too many pytest selectors")
        selectors = [self._validate_selector(item) for item in raw]

        try:
            process = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *selectors],
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ArenaObservation(
                request_id=request.request_id,
                branch_id=request.branch_id,
                tool=self.name,
                operation=request.operation,
                status="failed",
                claim=f"pytest timed out after {self.timeout:g}s.",
                detail=str(exc),
                source="pytest",
                confidence=1.0,
            )

        combined = ((process.stdout or "") + ("\n" + process.stderr if process.stderr else "")).strip()
        detail = combined[-self.max_output_chars :]
        if process.returncode == 0:
            status = "verified"
            claim = f"pytest passed for {len(selectors)} selector(s)."
        else:
            status = "failed"
            claim = f"pytest failed for {len(selectors)} selector(s) with exit code {process.returncode}."
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status=status,
            claim=claim,
            detail=detail,
            source="pytest:" + ",".join(selectors),
            confidence=1.0,
        )
