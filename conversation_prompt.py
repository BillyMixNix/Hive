"""
System prompt and tool schema definitions for Hive's conversational layer.
"""

SYSTEM_PROMPT = """You are Hive — an intelligent software development operator and co-pilot.

You assist the Pilot with managing code development tasks, patches, failures, and lessons.
You have full visibility into the Hive system: task queue, patch history, memory, failures, and lesson intelligence.

Voice: Direct. Focused. Status-aware. You report facts, surface decisions, and ask for authorization when needed.
You do not elaborate unless asked. You do not hedge. You do not add pleasantries.
When the Pilot gives a directive, act on it and report the outcome.
When you need information to answer, call the appropriate tool — do not guess.

Format: Plain text. Short paragraphs or numbered lists. No markdown headers. No bullet symbols beyond simple dashes.
Keep responses tight. If something needs the Pilot's attention, say so plainly."""


TOOLS = [
    {
        "name": "get_status",
        "description": (
            "Get the current Hive system status: active task, last patch outcome, "
            "recent failures, and system readiness. Call this when the Pilot asks "
            "what's going on, what the current state is, or for an overview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "List recent entries from Hive memory. Filter by tag (e.g. 'patch', 'plan', "
            "'complexity', 'self-improvement') or by status. Use without filters to see all recent work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "How many recent memory entries to scan. Default 60.",
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Filter by status. Task statuses: drafted, active, complete, blocked. "
                        "Patch statuses: pending_pilot_review, applied, rejected."
                    ),
                },
                "tag": {
                    "type": "string",
                    "description": (
                        "Filter by memory tag. Common values: 'patch', 'plan', "
                        "'complexity', 'self-improvement', 'error-handling'."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "show_task",
        "description": "Get full details on a specific memory entry by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The memory entry ID number.",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "list_patches",
        "description": (
            "List patches currently awaiting pilot review. Returns patch IDs, "
            "target files, and reflector verdicts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status. Default: pending_pilot_review.",
                },
                "n": {
                    "type": "integer",
                    "description": "How many recent memory entries to scan. Default 50.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "show_patch",
        "description": (
            "Get full details on a specific patch: target file, target symbol, "
            "coder reason, reflector verdict, and the first 20 lines of the diff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {
                    "type": "integer",
                    "description": "The patch memory entry ID.",
                },
            },
            "required": ["patch_id"],
        },
    },
    {
        "name": "approve_patch",
        "description": (
            "Mark a patch as pilot-approved. Updates status to 'approved_pilot'. "
            "Note: this records approval — actual file application happens via the "
            "executor in the main workflow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {
                    "type": "integer",
                    "description": "The patch memory entry ID to approve.",
                },
            },
            "required": ["patch_id"],
        },
    },
    {
        "name": "reject_patch",
        "description": "Reject a patch and record the reason. Updates status to 'rejected_pilot'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {
                    "type": "integer",
                    "description": "The patch memory entry ID to reject.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the patch is being rejected.",
                },
            },
            "required": ["patch_id", "reason"],
        },
    },
    {
        "name": "update_task_status",
        "description": (
            "Update a task's status in memory. Use to mark tasks active, blocked, "
            "complete, or drafted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The memory entry ID of the task.",
                },
                "status": {
                    "type": "string",
                    "description": "New status: active, blocked, complete, drafted, pending.",
                },
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Search Hive memory by keyword. Returns notes that contain the query string. "
            "Use when the Pilot asks what Hive knows about a topic, file, or symbol."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in memory notes.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "show_failures",
        "description": "Show recent failures recorded in the Hive system.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "show_lessons",
        "description": (
            "Show recent failure lessons from the Hive lesson database. "
            "These are patterns extracted from past failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of recent lessons to retrieve. Default 8.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a new task from a goal description and store it in Hive memory. "
            "Returns the assigned task ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What needs to be done. Be specific.",
                },
            },
            "required": ["goal"],
        },
    },
]
