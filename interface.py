class Interface:
    EXACT_COMMANDS = {
        "memory": "memory_recall",
        "lessons": "lessons",
        "pending patch reviews": "show_pending_patch_reviews",
        "show pending patch reviews": "show_pending_patch_reviews",
        "pending recoveries": "show_pending_recoveries",
        "show pending recoveries": "show_pending_recoveries",
        "current task": "current_task",
        "current goal": "current_task",
        "show current": "show_current",
        "show last patch": "show_last_patch",
        "show failures": "show_failures",
        "show lessons": "show_lessons",
        "show cockpit": "show_cockpit",
        "show conjectures": "show_conjectures",
        "show math lessons": "show_math_lessons",
        "math status": "math_status",
        "show hypotheses": "show_hypotheses",
        "show code lessons": "show_code_lessons",
        "code status": "code_status",
        "scan": "code_scan",
        "help": "help",
    }

    # Math commands: "explore collatz 1 1000", "conjecture <text>", "falsify <text>"
    MATH_PREFIX_COMMANDS = {
        "explore collatz ": "math_explore",
        "falsify ": "math_falsify",
        "conjecture ": "math_conjecture",
        "symbolic ": "math_symbolic",
        "formal ": "math_formal",
        "strategic ": "math_strategic",
    }

    # Code research commands
    CODE_PREFIX_COMMANDS = {
        "hypothesize ":       "code_hypothesize",
        "benchmark ":         "code_benchmark",
        "probe ":             "code_probe",
        "scan ":              "code_scan",
        "trace arch ":        "code_arch_trace",
        "adversarial test ":  "code_adversarial",
    }

    PREFIX_COMMANDS = {
        "apply patch ": ("apply_patch", "patch_id"),
        "rollback patch ": ("rollback_patch", "patch_id"),
        "verify patch ": ("verify_patch", "patch_id"),
        "approve patch ": ("approve_patch", "patch_id"),
        "reject patch ": ("reject_patch", "patch_id"),
        "review patch ": ("review_patch", "patch_id"),
        "show patch review ": ("review_patch", "patch_id"),
        "show recovery ": ("show_recovery", "task_id"),
        "show task ": ("show_task", "task_id"),
        "show goal ": ("show_task", "task_id"),
        "show patch ": ("show_patch", "patch_id"),
        "show plan ": ("show_plan", "task_id"),
        "show goal plan ": ("show_plan", "task_id"),
        "plan task ": ("plan_task", "task_id"),
        "plan goal ": ("plan_task", "task_id"),
        "code task ": ("code_task", "task_id"),
        "code goal ": ("code_task", "task_id"),
        "complete task ": ("complete_task", "task_id"),
        "complete goal ": ("complete_task", "task_id"),
        "delete task ": ("delete_task", "task_id"),
        "delete goal ": ("delete_task", "task_id"),
        "block task ": ("block_task", "task_id"),
        "block goal ": ("block_task", "task_id"),
        "active task ": ("active_task", "task_id"),
        "active goal ": ("active_task", "task_id"),
        "continue task ": ("continue_task", "task_id"),
        "continue goal ": ("continue_task", "task_id"),
    }

    PREFIX_TEXT_COMMANDS = {
        "pilot task ": ("pilot_task_intent", "task_id", "pilot_input"),
        "pilot goal ": ("pilot_task_intent", "task_id", "pilot_input"),
        "clarify task ": ("pilot_task_intent", "task_id", "pilot_input"),
        "clarify goal ": ("pilot_task_intent", "task_id", "pilot_input"),
        "pilot revise patch ": ("pilot_revise_patch", "patch_id", "pilot_guidance"),
        "pilot reject patch ": ("pilot_reject_patch", "patch_id", "pilot_reason"),
    }

    PREFIX_REVIEW_ID_COMMANDS = {
        "pilot accept patch ": "pilot_accept_patch",
    }

    def _invalid_response(self, text):
        return {
            "intent": "invalid",
            "context": {},
            "raw_text": text,
        }

    def _build_response(self, intent, text, context=None):
        context = dict(context or {})
        return {
            "intent": intent,
            "context": context or {},
            "raw_text": text,
        }

    def _parse_int_suffix(self, clean, prefix):
        raw_value = clean[len(prefix):].strip()
        return int(raw_value)

    def _parse_int_and_text_suffix(self, clean, prefix):
        raw_value = clean[len(prefix):].strip()
        parts = raw_value.split(None, 1)
        if len(parts) != 2:
            raise ValueError("Expected task id followed by pilot text.")
        return int(parts[0]), parts[1].strip()

    def process_input(self, text):
        clean = text.strip().lower()

        if clean in self.EXACT_COMMANDS:
            return self._build_response(self.EXACT_COMMANDS[clean], text)

        for prefix, (intent, context_key) in self.PREFIX_COMMANDS.items():
            if clean.startswith(prefix):
                try:
                    value = self._parse_int_suffix(clean, prefix)
                    return self._build_response(intent, text, {context_key: value})
                except ValueError:
                    return self._invalid_response(text)

        for prefix, (intent, id_key, text_key) in self.PREFIX_TEXT_COMMANDS.items():
            if clean.startswith(prefix):
                try:
                    numeric_id, payload_text = self._parse_int_and_text_suffix(clean, prefix)
                    if not payload_text:
                        raise ValueError("Pilot input is required.")
                    return self._build_response(
                        intent,
                        text,
                        {id_key: numeric_id, text_key: payload_text},
                    )
                except ValueError:
                    return self._invalid_response(text)

        for prefix, intent in self.PREFIX_REVIEW_ID_COMMANDS.items():
            if clean.startswith(prefix):
                try:
                    value = self._parse_int_suffix(clean, prefix)
                    return self._build_response(intent, text, {"patch_id": value})
                except ValueError:
                    return self._invalid_response(text)

        for prefix, intent in self.MATH_PREFIX_COMMANDS.items():
            if clean.startswith(prefix):
                payload_text = text[len(prefix):].strip()
                return self._build_response(intent, text, {"input": payload_text})

        for prefix, intent in self.CODE_PREFIX_COMMANDS.items():
            if clean.startswith(prefix):
                payload_text = text[len(prefix):].strip()
                return self._build_response(intent, text, {"input": payload_text})

        return self._build_response("build_or_design", text)
