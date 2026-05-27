"""
System prompt and tool schema definitions for Hive's conversational layer.

OLLAMA_TOOLS uses the Ollama /api/chat tool format:
  { "type": "function", "function": { "name", "description", "parameters" } }
"""

SYSTEM_PROMPT = """You are Hive — a co-pilot and intelligent development partner working alongside the Pilot.

You share full visibility into the system: tasks, patches, failures, lessons, and memory. You and the Pilot work as near-equals — you bring structured memory, tireless iteration, and pattern recognition; the Pilot brings judgment, direction, and the outside view.

Voice: Conversational but sharp. Speak naturally. You can have opinions. You can push back. You can ask questions.

RULES — follow these without exception:
1. Never narrate what you are about to do. Do it.
2. When you need data, call the tool immediately — do not explain that you will call it first.
3. Never output a numbered list as a response plan. If you have data, reason from it. If you need data, get it first.
4. After a tool returns results, respond directly from those results. Do not summarize generically.
5. If a task status is done or complete, its failures are historical — not active problems.
6. If a task is blocked, call show_task to read the actual block reason before recommending anything.

Format: Natural prose. Tight. No headers. No padding. Lead with the substance.

--- TOOLS ---
To fetch data, output a JSON call on a line by itself:
{"name": "TOOL_NAME", "arguments": {}}

Available tools:
- get_status — current status: active task, last patch, recent failures, system readiness
- list_tasks(n, status, tag) — list memory entries; filter by tag or status
- show_task(task_id) — full details on a specific task by ID
- list_patches(status, n) — list patches; default status=pending_pilot_review
- show_patch(patch_id) — full patch details including diff excerpt
- approve_patch(patch_id) — mark a patch pilot-approved
- reject_patch(patch_id, reason) — reject a patch with a reason
- update_task_status(task_id, status) — update task status
- recall_memory(query) — search memory by keyword
- show_failures — recent failures and counts by category
- show_lessons(n) — recent lessons from the lesson database
- create_task(goal) — create a new task from a goal description"""


def _fn(name, description, properties=None, required=None):
    """Build a single Ollama-format tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


OLLAMA_TOOLS = [
    _fn(
        "get_status",
        (
            "Get the current Hive system status: active task, last patch outcome, "
            "recent failures, and system readiness. Call this when the Pilot asks "
            "what's going on, what the current state is, or for an overview."
        ),
    ),
    _fn(
        "list_tasks",
        (
            "List recent entries from Hive memory. Filter by tag (e.g. 'patch', 'plan', "
            "'complexity', 'self-improvement') or by status. "
            "Use without filters to see all recent work."
        ),
        properties={
            "n": {
                "type": "integer",
                "description": "How many recent memory entries to scan. Default 60.",
            },
            "status": {
                "type": "string",
                "description": (
                    "Filter by status. Task statuses: drafted, active, complete, blocked. "
                    "Patch statuses: pending_pilot_review, applied, rejected, blocked."
                ),
            },
            "tag": {
                "type": "string",
                "description": (
                    "Filter by memory tag. Common values: 'patch', 'plan', "
                    "'complexity', 'self-improvement', 'error-handling', 'builder'."
                ),
            },
        },
    ),
    _fn(
        "show_task",
        "Get full details on a specific memory entry by ID.",
        properties={
            "task_id": {
                "type": "integer",
                "description": "The memory entry ID number.",
            },
        },
        required=["task_id"],
    ),
    _fn(
        "list_patches",
        (
            "List patches awaiting pilot review or recently processed. "
            "Returns patch IDs, target files, and reflector verdicts."
        ),
        properties={
            "status": {
                "type": "string",
                "description": (
                    "Filter by patch status. Default: pending_pilot_review. "
                    "Other values: applied, rejected, blocked, approved_pilot."
                ),
            },
            "n": {
                "type": "integer",
                "description": "How many recent memory entries to scan. Default 50.",
            },
        },
    ),
    _fn(
        "show_patch",
        (
            "Get full details on a specific patch: target file, target symbol, "
            "coder reason, reflector verdict, and the first 20 lines of the diff."
        ),
        properties={
            "patch_id": {
                "type": "integer",
                "description": "The patch memory entry ID.",
            },
        },
        required=["patch_id"],
    ),
    _fn(
        "approve_patch",
        (
            "Mark a patch as pilot-approved (status: approved_pilot). "
            "Actual file application still requires running apply in main.py."
        ),
        properties={
            "patch_id": {
                "type": "integer",
                "description": "The patch memory entry ID to approve.",
            },
        },
        required=["patch_id"],
    ),
    _fn(
        "reject_patch",
        "Reject a patch and record the reason. Sets status to rejected_pilot.",
        properties={
            "patch_id": {
                "type": "integer",
                "description": "The patch memory entry ID to reject.",
            },
            "reason": {
                "type": "string",
                "description": "Why the patch is being rejected.",
            },
        },
        required=["patch_id", "reason"],
    ),
    _fn(
        "update_task_status",
        "Update a task's status in memory. Use to mark tasks active, blocked, complete, or drafted.",
        properties={
            "task_id": {
                "type": "integer",
                "description": "The memory entry ID of the task.",
            },
            "status": {
                "type": "string",
                "description": "New status: active, blocked, complete, drafted, pending.",
            },
        },
        required=["task_id", "status"],
    ),
    _fn(
        "recall_memory",
        (
            "Search Hive memory by keyword. Returns notes that contain the query string. "
            "Use when the Pilot asks what Hive knows about a topic, file, or symbol."
        ),
        properties={
            "query": {
                "type": "string",
                "description": "Keyword or phrase to search for in memory notes.",
            },
        },
        required=["query"],
    ),
    _fn(
        "show_failures",
        "Show recent failures recorded in the Hive system along with failure counts by category.",
    ),
    _fn(
        "show_lessons",
        (
            "Show recent failure lessons from the Hive lesson database. "
            "These are patterns extracted from past failures with retry instructions."
        ),
        properties={
            "n": {
                "type": "integer",
                "description": "Number of recent lessons to retrieve. Default 8.",
            },
        },
    ),
    _fn(
        "create_task",
        "Create a new task from a goal description and store it in Hive memory. Returns the assigned task ID.",
        properties={
            "goal": {
                "type": "string",
                "description": "What needs to be done. Be specific.",
            },
        },
        required=["goal"],
    ),
]
