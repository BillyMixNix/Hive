import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


MODEL = "qwen2.5-coder:7b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MAX_STEPS = 12

SYSTEM = """
You are a local coding agent operating inside a repository.

Available actions:

{"name":"list_files","arguments":{}}
{"name":"read_file","arguments":{"path":"relative/path"}}
{"name":"run_command","arguments":{"command":"pytest"}}
{"name":"finish","arguments":{"summary":"what was empirically verified"}}
{"name":"replace_in_file","arguments":{"path":"relative/path","old":"exact existing text","new":"replacement text"}}

Rules:
- Inspect the repository instead of guessing its language or structure.
- Use tools whenever you need information.
- Do not ask the user to perform actions for you.
- Return exactly ONE JSON action and no prose.
- If evidence shows source code or a test must change, use replace_in_file.
- A passing test run establishes mechanical validation, not intent conformance.
- You may request finish only after tests pass; the controller independently checks
  whether the current diff conforms to the original objective.
"""

OBJECTIVE = """
Inspect this repository and repair it. The intended behavior is that
calculate_total([10, 20, 30]) returns 60. Run the tests, diagnose the failure from
evidence, and continue until the implementation satisfies that intent and tests pass.
"""

CONFORMANCE_SYSTEM = """
You are the intent/conformance gate for a coding-agent controller. Tests passing is
only mechanical validation. Decide whether the candidate change satisfies the
ORIGINAL OBJECTIVE, rather than changing a verifier/specification to bless incorrect
behavior.

Test changes are allowed when evidence shows the old test was wrong. Reject changes
that merely move an expectation away from objective or pre-change specification
evidence. Consider all supplied evidence: objective, pre-change repository content,
candidate diff, test output, and current repository context.

Return exactly one JSON object with this schema:
{"decision":"ACCEPT|REVISE","category":"conformant|correct_context_wrong_intent|insufficient_evidence","reasons":["..."],"evidence":["..."]}
ACCEPT only when the evidence affirmatively supports intent satisfaction. If evidence
is ambiguous or the diff avoids the requested repair, return REVISE.
"""

EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".agent_runs"}
EXCLUDED_PREFIXES = (".aider",)


def normalize(raw):
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def ollama_chat(messages, model=MODEL, url=OLLAMA_URL):
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["message"]["content"]


def _is_text(path):
    try:
        path.read_text(encoding="utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def snapshot_repository(root):
    snapshot = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for filename in files:
            if filename.startswith(EXCLUDED_PREFIXES):
                continue
            path = Path(base) / filename
            relative = path.relative_to(root).as_posix()
            if _is_text(path):
                snapshot[relative] = path.read_text(encoding="utf-8")
    return snapshot


def repository_diff(before, after):
    chunks = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path, "").splitlines(keepends=True)
        new = after.get(path, "").splitlines(keepends=True)
        if old == new:
            continue
        chunks.extend(difflib.unified_diff(
            old,
            new,
            fromfile=f"a/{path}" if path in before else "/dev/null",
            tofile=f"b/{path}" if path in after else "/dev/null",
        ))
    return "".join(chunks) or "(no textual changes)"


def revision_id(snapshot):
    digest = hashlib.sha256()
    for path, content in sorted(snapshot.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


@dataclass
class ConformanceDecision:
    decision: str
    category: str
    reasons: list
    evidence: list
    raw: str = ""

    @property
    def accepted(self):
        return self.decision == "ACCEPT"


class LocalAgent:
    """Bounded local agent with revision-bound validation and conformance gates."""

    def __init__(
        self,
        root=None,
        objective=OBJECTIVE,
        agent_chat: Callable = ollama_chat,
        conformance_chat: Callable = ollama_chat,
        max_steps=MAX_STEPS,
        log_path=None,
    ):
        self.root = Path(root or os.getcwd()).resolve()
        self.objective = objective.strip()
        self.agent_chat = agent_chat
        self.conformance_chat = conformance_chat
        self.max_steps = max_steps
        default_log = self.root / ".agent_runs" / "latest.jsonl"
        self.log_path = Path(log_path).resolve() if log_path else default_log
        self.baseline = snapshot_repository(self.root)
        try:
            log_relative = self.log_path.relative_to(self.root).as_posix()
        except ValueError:
            pass
        else:
            self.baseline.pop(log_relative, None)
        self.messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": self.objective},
        ]
        self.validation_state = "MISSING"
        self.validated_revision = None
        self.test_evidence = ""
        self.conformance = None
        self.rejected_revision = None
        self.rejections = 0
        self.completed = False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        self.log("run_started", objective=self.objective,
                 baseline_revision=revision_id(self.baseline),
                 max_steps=self.max_steps)

    def log(self, event, **details):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "validation_state": self.validation_state,
            **details,
        }
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    def current_snapshot(self):
        snapshot = snapshot_repository(self.root)
        try:
            log_relative = self.log_path.relative_to(self.root).as_posix()
        except ValueError:
            pass
        else:
            # Observability must not mutate the candidate revision it describes.
            snapshot.pop(log_relative, None)
        return snapshot

    def current_revision(self):
        return revision_id(self.current_snapshot())

    def safe_path(self, relative):
        candidate = (self.root / relative).resolve()
        if os.path.commonpath([self.root, candidate]) != str(self.root):
            raise ValueError("Path escapes repository root.")
        return candidate

    def list_files(self):
        return "\n".join(sorted(self.current_snapshot()))

    def read_file(self, path):
        try:
            return self.safe_path(path).read_text(encoding="utf-8")
        except Exception as exc:
            return f"ERROR: {exc}"

    def invalidate_validation(self, reason):
        self.validation_state = "IMPLEMENTED"
        self.validated_revision = None
        self.test_evidence = ""
        self.conformance = None
        self.rejected_revision = None
        self.log("validation_invalidated", reason=reason,
                 revision=self.current_revision())

    def replace_in_file(self, path, old, new):
        try:
            target = self.safe_path(path)
            content = target.read_text(encoding="utf-8")
            if old not in content:
                return "ERROR: Exact text to replace was not found."
            if content.count(old) != 1:
                return "ERROR: Replacement target is ambiguous."
            target.write_text(content.replace(old, new, 1), encoding="utf-8")
            self.invalidate_validation(f"updated {path}")
            return f"SUCCESS: Updated {path}"
        except Exception as exc:
            return f"ERROR: {exc}"

    def run_command(self, command):
        if command not in {"pytest", "pytest -v", "pytest --verbose"}:
            return f"BLOCKED: command not allowed: {command}"
        verbosity = ["-v"] if command in {"pytest -v", "pytest --verbose"} else []
        temp_parent = self.root / ".agent_runs"
        temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pytest_", dir=temp_parent) as temporary:
            test_temp = Path(temporary) / "basetemp"
            bytecode_temp = Path(temporary) / "pycache"
            environment = os.environ.copy()
            environment["PYTHONPYCACHEPREFIX"] = str(bytecode_temp)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *verbosity, "-p", "no:cacheprovider",
                 f"--basetemp={test_temp}"],
                shell=False,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=60,
                env=environment,
            )
        output = (
            f"EXIT CODE: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        revision = self.current_revision()
        if result.returncode == 0:
            self.validation_state = "VALIDATED"
            self.validated_revision = revision
            self.test_evidence = output
            self.conformance = None
        else:
            self.validation_state = "IMPLEMENTED"
            self.validated_revision = None
            self.test_evidence = output
            self.conformance = None
        self.log("mechanical_validation", command=command,
                 exit_code=result.returncode, revision=revision, output=output)
        return output

    def evidence_packet(self):
        current = self.current_snapshot()
        return {
            "original_objective": self.objective,
            "pre_change_repository": self.baseline,
            "proposed_diff": repository_diff(self.baseline, current),
            "test_results": self.test_evidence,
            "current_repository": current,
            "validated_revision": self.validated_revision,
        }

    def evaluate_conformance(self):
        packet = self.evidence_packet()
        try:
            raw = self.conformance_chat([
                {"role": "system", "content": CONFORMANCE_SYSTEM},
                {"role": "user", "content": json.dumps(packet, indent=2)},
            ])
        except Exception as exc:
            raw = json.dumps({"evaluator_error": str(exc)})
        try:
            parsed = json.loads(normalize(raw))
            decision = parsed.get("decision", "REVISE").upper()
            if decision not in {"ACCEPT", "REVISE"}:
                raise ValueError("invalid decision")
            reasons = parsed.get("reasons", [])
            evidence = parsed.get("evidence", [])
            if not isinstance(reasons, list) or not reasons:
                raise ValueError("at least one reason is required")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("at least one evidence item is required")
            result = ConformanceDecision(
                decision=decision,
                category=parsed.get("category", "insufficient_evidence"),
                reasons=reasons,
                evidence=evidence,
                raw=raw,
            )
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            result = ConformanceDecision(
                decision="REVISE",
                category="insufficient_evidence",
                reasons=[f"Conformance evaluator returned an invalid judgment: {exc}"],
                evidence=[raw],
                raw=raw,
            )
        self.conformance = result
        if result.accepted:
            self.validation_state = "CONFORMANT"
            self.rejected_revision = None
        else:
            self.rejections += 1
            self.validation_state = "VALIDATED"
            self.rejected_revision = self.current_revision()
        self.log("conformance_decision", decision=result.decision,
                 category=result.category, reasons=result.reasons,
                 evidence=result.evidence, revision=self.current_revision(),
                 rejection_number=self.rejections)
        return result

    def request_finish(self, summary=""):
        current_revision = self.current_revision()
        if (self.validation_state not in {"VALIDATED", "CONFORMANT"}
                or self.validated_revision != current_revision):
            reason = (
                "COMPLETION REJECTED: The current repository revision has not passed "
                "pytest. Continue investigating and validate after every change."
            )
            self.log("completion_rejected", reason=reason,
                     revision=current_revision)
            return False, reason

        if self.rejected_revision == current_revision:
            reason = (
                "COMPLETION REJECTED: This exact repository revision already failed "
                "the intent gate. Revise the candidate before requesting another "
                "conformance decision."
            )
            self.log("completion_rejected", reason=reason,
                     revision=current_revision)
            return False, reason

        if self.validation_state != "CONFORMANT":
            decision = self.evaluate_conformance()
            if not decision.accepted:
                reason = (
                    "COMPLETION REJECTED BY INTENT GATE: "
                    f"category={decision.category}; "
                    f"reasons={' | '.join(decision.reasons)}. "
                    "Revise the implementation using this evidence, rerun tests, "
                    "and request finish again."
                )
                self.log("completion_rejected", reason=reason,
                         revision=current_revision)
                return False, reason

        self.completed = True
        self.log("completion_accepted", summary=summary,
                 revision=current_revision, retries=self.rejections)
        return True, "COMPLETION ACCEPTED: mechanically validated and conformant."

    def execute_action(self, action):
        name = action.get("name")
        arguments = action.get("arguments", {})
        self.log("action", name=name, arguments=arguments,
                 revision=self.current_revision())
        if name == "finish":
            return self.request_finish(arguments.get("summary", ""))
        if name == "list_files":
            return False, self.list_files()
        if name == "read_file":
            return False, self.read_file(arguments.get("path", ""))
        if name == "run_command":
            return False, self.run_command(arguments.get("command", ""))
        if name == "replace_in_file":
            return False, self.replace_in_file(
                arguments.get("path", ""),
                arguments.get("old", ""),
                arguments.get("new", ""),
            )
        return False, (
            f"ERROR: Unknown tool '{name}'. Use one of: list_files, read_file, "
            "replace_in_file, run_command, finish."
        )

    def run(self):
        for step in range(1, self.max_steps + 1):
            print(f"\n===== AGENT STEP {step}/{self.max_steps} =====")
            raw = self.agent_chat(self.messages)
            print(f"MODEL:\n{raw}")
            normalized = normalize(raw)
            try:
                action = json.loads(normalized)
                if not isinstance(action, dict):
                    raise ValueError("action must be an object")
            except (json.JSONDecodeError, ValueError):
                observation = "PROTOCOL ERROR: Return exactly one valid JSON action."
                self.log("protocol_error", raw=raw)
            else:
                finished, observation = self.execute_action(action)
                print(f"\nOBSERVATION:\n{observation}")
                if finished:
                    print("\n===== AGENT FINISHED — CONFORMANT =====")
                    return True
            self.messages.append({"role": "assistant", "content": normalized})
            self.messages.append({
                "role": "user",
                "content": f"TOOL RESULT:\n{observation}\nChoose the next action.",
            })
        self.log("max_steps_reached", retries=self.rejections,
                 revision=self.current_revision())
        print("\n===== MAX STEPS REACHED — NOT COMPLETE =====")
        return False


if __name__ == "__main__":
    LocalAgent().run()
