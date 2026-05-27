"""
Conversational layer manager for Hive.

Uses Ollama's /api/chat endpoint with native tool calling.
Maintains conversation history, executes tool calls, and returns
Hive's natural language responses.
"""

import json
import requests
import time
from datetime import datetime

from conversation_prompt import SYSTEM_PROMPT, OLLAMA_TOOLS
from HiveMemoryAgent import HiveMemoryAgent
from HiveStateManager import HiveStateManager
from HiveLessonMemory import LessonMemory
from builder import BuilderAgent

try:
    import torch
except ImportError:
    torch = None


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-coder:7b"
_MAX_HISTORY_TURNS = 20
_REQUEST_TIMEOUT = 120


def _dummy_vector():
    if torch is not None:
        return torch.randn(256).to("cpu")
    return [0.0] * 256


class ConversationManager:
    def __init__(self, repo_root=".", model=None):
        self.model = model or DEFAULT_MODEL
        self.history = []  # user/assistant/tool turns only

        self.memory = HiveMemoryAgent(device="cpu")
        self.state = HiveStateManager(repo_root=repo_root)
        self.state.load_snapshot()
        self.lesson_memory = LessonMemory()
        self.builder = BuilderAgent()

        # System message built after lesson_memory is ready so trusted
        # lessons can be injected into the prompt at session start.
        self._system_message = {
            "role": "system",
            "content": self._build_system_prompt(),
        }

    def _build_system_prompt(self) -> str:
        """Build the system prompt, injecting trusted lessons at the bottom."""
        lessons = self._load_trusted_lessons()
        if not lessons:
            return SYSTEM_PROMPT

        lines = [SYSTEM_PROMPT, "", "--- LEARNED PATTERNS ---",
                 "These patterns have been validated through experience. Apply them automatically:"]
        for lesson in lessons:
            family = lesson.get("failure_family") or lesson.get("lesson_family") or "general"
            when = (lesson.get("failure_reason") or lesson.get("trigger_pattern") or "")[:120]
            instruction = (lesson.get("retry_instruction") or "")[:200]
            if instruction:
                entry = f"- [{family}]"
                if when:
                    entry += f" When: {when}."
                entry += f" Do: {instruction}"
                lines.append(entry)

        return "\n".join(lines)

    def _load_trusted_lessons(self) -> list:
        """Load trusted lessons relevant to conversational reasoning."""
        try:
            import json
            trusted = []
            universal_extra = []
            seen = set()
            with open(self.lesson_memory.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lesson = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    lid = lesson.get("lesson_id") or lesson.get("timestamp")
                    if lid in seen:
                        continue
                    seen.add(lid)
                    state = lesson.get("promotion_state", "")
                    scope = lesson.get("scope", "")
                    if state == "trusted":
                        trusted.append(lesson)
                    elif scope == "universal" and state not in ("retired",):
                        universal_extra.append(lesson)
            # Pilot-seeded reasoning lessons first, then other trusted
            seeded = [l for l in trusted if l.get("source") == "pilot_seeded"]
            other = [l for l in trusted if l.get("source") != "pilot_seeded"]
            return (seeded + other + universal_extra)[:20]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, user_text: str) -> str:
        """Send a message and return Hive's natural language response."""
        self.history.append({"role": "user", "content": user_text})
        response_text = self._run_turn()
        self._trim_history()
        return response_text

    # ------------------------------------------------------------------
    # Conversation loop
    # ------------------------------------------------------------------

    def _build_messages(self) -> list:
        return [self._system_message] + self.history

    def _run_turn(self) -> str:
        """Run one full conversation turn, handling tool calls until done."""
        while True:
            payload = {
                "model": self.model,
                "messages": self._build_messages(),
                "stream": False,
            }

            resp = self._ollama_post(payload)
            message = resp.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = message.get("content") or ""

            # Some models output tool calls as text rather than via the native
            # tool_calls field. Detect and normalise that here.
            if not tool_calls and content:
                tool_calls = self._extract_text_tool_calls(content)
                if tool_calls:
                    content = ""

            if tool_calls:
                # Record assistant turn with tool calls
                self.history.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls,
                    }
                )
                # Execute each tool and append results
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    result = self._dispatch_tool(name, args)
                    self.history.append(
                        {
                            "role": "tool",
                            "content": json.dumps(result, default=str),
                        }
                    )
                # Loop back to let model see results
                continue

            # No tool calls — final response
            self.history.append({"role": "assistant", "content": content})
            return content

    def _extract_text_tool_calls(self, content: str) -> list:
        """
        Detect tool calls embedded as JSON in the model's text output.
        Handles both single-object and array formats.
        Returns a normalised tool_calls list or empty list if none found.
        """
        valid_names = {t["function"]["name"] for t in OLLAMA_TOOLS}
        stripped = content.strip()

        # Try to find JSON block — may be wrapped in markdown fences
        import re
        json_candidates = re.findall(r"```(?:json)?\s*([\s\S]*?)```", stripped)
        if not json_candidates:
            # Try bare JSON object or array
            if stripped.startswith("{") or stripped.startswith("["):
                json_candidates = [stripped]

        for candidate in json_candidates:
            candidate = candidate.strip()
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            # Normalise to list
            items = parsed if isinstance(parsed, list) else [parsed]
            calls = []
            for item in items:
                name = item.get("name") or item.get("function", {}).get("name", "")
                args = item.get("arguments") or item.get("parameters") or {}
                if name in valid_names:
                    calls.append({"function": {"name": name, "arguments": args}})

            if calls:
                return calls

        return []

    def _ollama_post(self, payload: dict) -> dict:
        try:
            resp = requests.post(
                OLLAMA_CHAT_URL,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot reach Ollama at {OLLAMA_CHAT_URL}. "
                "Is Ollama running? Start it with: ollama serve"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama request timed out after {_REQUEST_TIMEOUT}s."
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Ollama request failed: {exc}")

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _trim_history(self):
        """Cap history at N turns to control context length."""
        max_messages = _MAX_HISTORY_TURNS * 2
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def _dispatch_tool(self, name: str, inputs: dict) -> dict:
        print(f"[Tool] {name}({inputs})")
        handlers = {
            "get_status": self._tool_get_status,
            "list_tasks": self._tool_list_tasks,
            "show_task": self._tool_show_task,
            "list_patches": self._tool_list_patches,
            "show_patch": self._tool_show_patch,
            "approve_patch": self._tool_approve_patch,
            "reject_patch": self._tool_reject_patch,
            "update_task_status": self._tool_update_task_status,
            "recall_memory": self._tool_recall_memory,
            "show_failures": self._tool_show_failures,
            "show_lessons": self._tool_show_lessons,
            "create_task": self._tool_create_task,
        }
        fn = handlers.get(name)
        if fn is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            return fn(**inputs)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_get_status(self):
        obs = self.state.get_observability_snapshot()
        current = obs.get("current") or {}
        last_patch = obs.get("last_patch") or {}
        failures = obs.get("failures") or {}
        system = obs.get("system") or {}

        recent_failures = failures.get("recent") or []
        summary_failures = [
            {
                "category": f.get("failure_category"),
                "reason": str(f.get("reason") or "")[:120],
                "timestamp": f.get("timestamp"),
            }
            for f in recent_failures[:3]
        ]

        return {
            "active_goal": current.get("active_goal"),
            "active_task_id": current.get("active_task_id"),
            "task_status": current.get("task_status"),
            "target_file": current.get("target_file"),
            "target_symbol": current.get("target_symbol"),
            "change_intent": current.get("change_intent"),
            "last_patch": {
                "file": last_patch.get("target_file"),
                "status": last_patch.get("patch_status"),
                "verdict": last_patch.get("reflection_verdict"),
                "timestamp": last_patch.get("timestamp"),
            },
            "recent_failures": summary_failures,
            "failure_counts": failures.get("counts_by_category") or {},
            "repo_loaded": system.get("repo_loaded"),
            "known_files_count": system.get("known_files_count"),
        }

    def _tool_list_tasks(self, n=60, status=None, tag=None):
        notes = self.memory.get_recent_notes(n)
        results = []

        for entry in notes:
            entry_tag = entry.get("tag") or ""
            entry_status = entry.get("status") or ""

            if tag is not None and entry_tag != tag:
                continue
            if status is not None and entry_status != status:
                continue
            if tag is None and entry_tag in ("", "none"):
                continue

            meta = entry.get("metadata") or {}
            results.append(
                {
                    "id": entry["id"],
                    "tag": entry_tag,
                    "status": entry_status,
                    "note": (entry.get("note") or "")[:120],
                    "target_file": meta.get("target_file"),
                    "work_mode": meta.get("work_mode"),
                    "timestamp": entry.get("timestamp"),
                }
            )

        return {"count": len(results), "entries": results}

    def _tool_show_task(self, task_id: int):
        entry = self.memory.get_task_by_id(task_id)
        if entry is None:
            return {"error": f"No entry found with ID {task_id}"}

        meta = entry.get("metadata") or {}
        builder_result = meta.get("builder_result") or {}

        return {
            "id": entry["id"],
            "tag": entry.get("tag"),
            "status": entry.get("status"),
            "note": entry.get("note"),
            "timestamp": entry.get("timestamp"),
            "target_file": meta.get("target_file"),
            "target_symbol": meta.get("target_symbol"),
            "work_mode": meta.get("work_mode"),
            "domain": meta.get("domain"),
            "artifact": meta.get("artifact"),
            "operation": meta.get("operation"),
            "completion_cues": meta.get("completion_cues") or [],
            "pilot_intent": meta.get("pilot_intent"),
            "next_action": builder_result.get("next_action"),
        }

    def _tool_list_patches(self, status="pending_pilot_review", n=50):
        notes = self.memory.get_recent_notes(n)
        patches = []

        for entry in reversed(notes):
            if entry.get("tag") != "patch":
                continue
            if status and entry.get("status") != status:
                continue

            meta = entry.get("metadata") or {}
            reflection = meta.get("reflection") or {}

            patches.append(
                {
                    "patch_id": entry["id"],
                    "task_id": meta.get("task_id"),
                    "target_file": meta.get("target_file"),
                    "target_symbol": (
                        meta.get("child_target_symbol")
                        or meta.get("target_symbol")
                    ),
                    "status": entry.get("status"),
                    "reflector_verdict": reflection.get("verdict"),
                    "note": (entry.get("note") or "")[:100],
                    "timestamp": entry.get("timestamp"),
                }
            )

        return {"count": len(patches), "patches": patches}

    def _tool_show_patch(self, patch_id: int):
        entry = self.memory.get_task_by_id(patch_id)
        if entry is None:
            return {"error": f"No entry found with ID {patch_id}"}
        if entry.get("tag") != "patch":
            return {"error": f"Entry {patch_id} is not a patch (tag={entry.get('tag')})"}

        meta = entry.get("metadata") or {}
        reflection = meta.get("reflection") or {}
        patch_text = meta.get("patch") or ""
        excerpt = "\n".join(patch_text.splitlines()[:20])

        return {
            "patch_id": entry["id"],
            "status": entry.get("status"),
            "task_id": meta.get("task_id"),
            "plan_id": meta.get("plan_id"),
            "child_task_title": meta.get("child_task_title"),
            "target_file": meta.get("target_file"),
            "target_symbol": (
                meta.get("child_target_symbol") or meta.get("target_symbol")
            ),
            "coder_reason": meta.get("reason"),
            "reflector_verdict": reflection.get("verdict"),
            "reflector_notes": reflection.get("reflection"),
            "patch_excerpt": excerpt,
            "timestamp": entry.get("timestamp"),
        }

    def _tool_approve_patch(self, patch_id: int):
        entry = self.memory.get_task_by_id(patch_id)
        if entry is None:
            return {"error": f"Patch {patch_id} not found"}
        if entry.get("tag") != "patch":
            return {"error": f"Entry {patch_id} is not a patch"}

        ok = self.memory.update_task_status(patch_id, "approved_pilot")
        if not ok:
            return {"error": f"Failed to update status for patch {patch_id}"}

        meta = entry.get("metadata") or {}
        return {
            "patch_id": patch_id,
            "status": "approved_pilot",
            "target_file": meta.get("target_file"),
            "message": (
                f"Patch {patch_id} approved. "
                "Run 'apply patch {patch_id}' in main.py to write it to disk."
            ),
        }

    def _tool_reject_patch(self, patch_id: int, reason: str):
        entry = self.memory.get_task_by_id(patch_id)
        if entry is None:
            return {"error": f"Patch {patch_id} not found"}
        if entry.get("tag") != "patch":
            return {"error": f"Entry {patch_id} is not a patch"}

        ok = self.memory.update_task_status(patch_id, "rejected_pilot")
        if not ok:
            return {"error": f"Failed to update status for patch {patch_id}"}

        meta = dict(entry.get("metadata") or {})
        meta["pilot_rejection_reason"] = reason
        meta["pilot_rejection_timestamp"] = datetime.utcnow().isoformat()
        self.memory.update_task_metadata(patch_id, meta)

        return {
            "patch_id": patch_id,
            "status": "rejected_pilot",
            "reason": reason,
        }

    def _tool_update_task_status(self, task_id: int, status: str):
        entry = self.memory.get_task_by_id(task_id)
        if entry is None:
            return {"error": f"Entry {task_id} not found"}

        ok = self.memory.update_task_status(task_id, status)
        if not ok:
            return {"error": f"Failed to update status for task {task_id}"}

        return {
            "task_id": task_id,
            "status": status,
            "note": (entry.get("note") or "")[:80],
        }

    def _tool_recall_memory(self, query: str):
        matches = self.memory.search_notes_by_keyword(query)
        return {
            "query": query,
            "count": len(matches),
            "matches": [m[:200] for m in matches[:10]],
        }

    def _tool_show_failures(self):
        obs = self.state.get_observability_snapshot()
        failures = obs.get("failures") or {}
        recent = failures.get("recent") or []

        formatted = [
            {
                "category": f.get("failure_category"),
                "reason": str(f.get("reason") or "")[:200],
                "task_id": f.get("task_id"),
                "target_file": f.get("target_file"),
                "timestamp": f.get("timestamp"),
            }
            for f in recent
        ]

        return {
            "recent_failures": formatted,
            "counts_by_category": failures.get("counts_by_category") or {},
        }

    def _tool_show_lessons(self, n=8):
        try:
            lessons = self.lesson_memory.get_recent_lessons(limit=n)
        except Exception:
            lessons = []

        formatted = [
            {
                "family": lesson.get("failure_family") or lesson.get("lesson_family"),
                "reason": (lesson.get("failure_reason") or "")[:150],
                "instruction": (lesson.get("retry_instruction") or "")[:150],
                "scope": lesson.get("scope"),
                "source": lesson.get("source"),
            }
            for lesson in lessons
        ]

        return {"count": len(formatted), "lessons": formatted}

    def _tool_create_task(self, goal: str):
        task = self.builder.build({"intent": goal})
        task_id = self.memory.ptr + 1

        self.memory.store(
            _dummy_vector(),
            tag="builder",
            note=f"{task['goal']} | next: {task['next_action']}",
            status=task.get("status", "drafted"),
            metadata={
                "builder_result": task,
                "work_mode": task.get("work_mode"),
                "domain": task.get("domain"),
                "artifact": task.get("artifact"),
                "operation": task.get("operation"),
                "validation": task.get("validation"),
                "target_file": None,
                "target_symbol": None,
                "completion_cues": [],
                "pilot_intent": task.get("pilot_intent"),
            },
        )

        return {
            "task_id": task_id,
            "goal": task["goal"],
            "status": task.get("status", "drafted"),
            "work_mode": task.get("work_mode"),
            "next_action": task.get("next_action"),
        }
