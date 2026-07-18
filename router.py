from executor import ExecutorAgent
from builder import BuilderAgent
from planner import PlannerAgent
from coder import CoderAgent


class Router:
    def __init__(self):
        self.builder = BuilderAgent()
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.coder = CoderAgent()

        self.intent_routes = {
            "plan_task": "plan_task",
            "code_task": "code_task",
            "memory_recall": "memory",
            "rollback_patch": "rollback_patch",
            "verify_patch": "verify_patch",
            "show_task": "show_task",
            "show_patch": "show_patch",
            "review_patch": "review_patch",
            "show_pending_patch_reviews": "show_pending_patch_reviews",
            "show_pending_recoveries": "show_pending_recoveries",
            "lessons": "lessons",
            "approve_patch": "approve_patch",
            "show_plan": "show_plan",
            "show_recovery": "show_recovery",
            "reject_patch": "reject_patch",
            "apply_patch": "apply_patch",
            "continue_task": "continue_task",
            "complete_task": "complete_task",
            "active_task": "active_task",
            "block_task": "block_task",
            "help": "help",
            "delete_task": "delete_task",
            "current_task": "current_task",
            "show_current": "show_current",
            "show_last_patch": "show_last_patch",
            "show_failures": "show_failures",
            "show_lessons": "show_lessons",
            "show_cockpit": "show_cockpit",
            "pilot_task_intent": "pilot_task_intent",
            "pilot_accept_patch": "pilot_accept_patch",
            "pilot_revise_patch": "pilot_revise_patch",
            "pilot_reject_patch": "pilot_reject_patch",
            # Math research routes
            "math_explore": "math_explore",
            "math_conjecture": "math_conjecture",
            "math_falsify": "math_falsify",
            "math_symbolic": "math_symbolic",
            "math_formal": "math_formal",
            "math_strategic": "math_strategic",
            "show_conjectures": "show_conjectures",
            "show_math_lessons": "show_math_lessons",
            "math_status": "math_status",
            # Code research routes
            "code_hypothesize": "code_hypothesize",
            "code_benchmark":   "code_benchmark",
            "code_probe":       "code_probe",
            "code_scan":        "code_scan",
            "code_arch_trace":  "code_arch_trace",
            "code_adversarial": "code_adversarial",
            "show_hypotheses":  "show_hypotheses",
            "show_code_lessons": "show_code_lessons",
            "code_status":      "code_status",
        }

    def normalize_command(self, command):
        return str(command or "").lower().strip()

    def validate_command_context(self, message):
        return "context" in message
    
    def normalize_context(self, context):
        return context if isinstance(context, dict) else {}
    
    def route(self, user_input, message):
        if not self.validate_command_context(message):
            return "error", {}

        intent = message.get("intent")
        context = self.normalize_context(message.get("context"))
        normalized_input = self.normalize_command(user_input)

        if intent in self.intent_routes:
            return self.intent_routes[intent], context

        return "builder", self.builder.build({"intent": normalized_input})
