from hive_llm import ask_model
from builder import format_pilot_brief
from HiveLessonMemory import LessonMemory
from planner_prompt import PLANNER_PROMPT_TEMPLATE
from anchor_utils import canonicalize_task_anchor, merge_anchor_with_span
import json
import re 


ALLOWED_TASK_TYPES = {
    "bugfix",
    "architecture",
    "state",
    "routing",
    "feature",
    "validation",
    "refactor",
    "docs",
    # Math research
    "math_exploration",
    "math_conjecture",
    "math_symbolic",
    "math_adversarial",
    "math_formal",
    "math_strategic",
    # Code research
    "code_hypothesis",
    "code_adversarial",
    "code_benchmark",
    "code_formal",
    "code_invariant",
    "code_regression",
}

ALLOWED_CHANGE_INTENTS = {
    "modify_existing_logic",
    "insert_line_after_anchor",
    "update_prompt_contract",
    "tighten_validation",
    "adjust_routing_order",
    "update_state_handling",
    "refactor_local_block",
}

INTENT_NORMALIZATION = {
    "insert_docstring": "modify_existing_logic",
    "add_docstring": "modify_existing_logic",
    "insert_comment": "modify_existing_logic",
    "add_comment": "modify_existing_logic",
    "clarify_comment": "modify_existing_logic",
}

ALLOWED_EXPECTED_OPERATIONS = {
    "replace",
    "rename",
    "insert_after_anchor",
    "insert_comment",
    "insert_docstring",
    "tighten_guard",
    "update_contract",
    "update_help_text",
    "reorder_logic",
    "update_state_flow",
    "refactor_block",
    "modify_logic",
}

KNOWN_FILES = {
    "main.py",
    "router.py",
    "interface.py",
    "planner.py",
    "planner_prompt.py",
    "coder.py",
    "coder_context.py",
    "coder_validation.py",
    "coder_block_ops.py",
    "coder_constraints.py",
    "coder_failures.py",
    "coder_prompting.py",
    "builder.py",
    "executor.py",
    "reflector.py",
    "reflector_prompt.py",
    "HiveMemoryAgent.py",
    "HiveLessonMemory.py",
    "HiveStateManager.py",
    "HiveAgent.py",
    "HiveBridge.py",
    "hive_llm.py",
    "repo_map.py",
}


class PlannerAgent:
    def __init__(self, state_manager=None):
        self.state_manager = state_manager
        self.lesson_memory = LessonMemory()

    def _get_pilot_guardrails(self, task, limit=5):
        task = task or {}
        metadata = task.get("metadata") or {}
        target_file = task.get("target_file") or metadata.get("target_file")
        target_symbol = task.get("target_symbol") or metadata.get("target_symbol")
        change_type = task.get("task_type") or metadata.get("task_type")
        preferred_recovery_action = "replan_task" if metadata.get("recovery_status") == "replan_ready" else None
        current_context = {
            "target_symbol": target_symbol,
            "file": target_file,
            "change_type": change_type,
        }
        return self.lesson_memory.get_pilot_guardrails(
            file=target_file,
            change_type=change_type,
            target_symbol=target_symbol,
            preferred_recovery_action=preferred_recovery_action,
            current_context=current_context,
            limit=limit,
        )

    def _normalize_expected_operation(self, child):
        description = (child.get("description") or "").strip().lower()
        title = (child.get("title") or "").strip().lower()
        target_symbol = (child.get("target_symbol") or "").strip().lower()
        change_intent = (child.get("change_intent") or "").strip()
        expected_operation = (child.get("expected_operation") or "").strip()

        combined = " ".join(part for part in [title, description, target_symbol] if part)

        has_anchor_language = any(phrase in combined for phrase in [
            "after `", 'after "', "after '",
            "immediately after",
            "insert after",
            "add after",
            "after anchor",
            "named anchor",
        ])

        has_reorder_language = any(phrase in combined for phrase in [
            "before applying",
            "before checking",
            "before running",
            "before replace heuristics",
            "prioritize",
            "priority",
            "checked before",
            "check before",
            "evaluate before",
            "run before",
            "first before",
            "earlier than",
            "precede",
            "precedence",
            "order of checks",
            "routing order",
        ])

        has_generic_logic_language = any(phrase in combined for phrase in [
            "modify",
            "update",
            "adjust",
            "change",
            "extend",
            "preserve fallback",
            "existing logic",
            "within",
            "in the function",
            "in the method",
        ])

        has_comment_language = any(phrase in combined for phrase in [
            "insert a comment",
            "add a comment",
            "clarify comment",
            "comment above",
            "comment below",
            "inline comment",
            "explain that",
            "explain why",
            "document why",
        ])

        has_docstring_language = any(phrase in combined for phrase in [
            "docstring",
            "triple-quoted",
            '"""',
            "'''",
        ])

        has_help_text_language = any(phrase in combined for phrase in [
            "help text",
            "usage text",
            "error message",
            "warning text",
            "description text",
            "user-facing text",
        ])

        if expected_operation == "insert_after_anchor" and not has_anchor_language:
            if has_reorder_language:
                return "reorder_logic"
            return "modify_logic"

        if not expected_operation:
            if has_anchor_language:
                return "insert_after_anchor"
            if has_docstring_language:
                return "insert_docstring"
            if has_comment_language:
                return "insert_comment"
            if has_help_text_language:
                return "update_help_text"
            if has_reorder_language:
                return "reorder_logic"
            if change_intent == "tighten_validation":
                return "tighten_guard"
            if change_intent == "update_prompt_contract":
                return "update_contract"
            if change_intent == "update_state_handling":
                return "update_state_flow"
            if change_intent == "refactor_local_block":
                return "refactor_block"
            if has_generic_logic_language or change_intent == "modify_existing_logic":
                return "modify_logic"

        return expected_operation

    def _normalize_completion_cues(self, child):
        cues = child.get("completion_cues") or []
        expected_operation = child.get("expected_operation")
        normalized = []

        for cue in cues:
            if not isinstance(cue, str):
                continue

            cue = cue.strip()
            if cue:
                normalized.append(cue)

        if expected_operation == "reorder_logic" and not normalized:
            normalized = ["if expected_operation", "replace_intent", "fallback"]
        elif expected_operation == "insert_comment" and not normalized:
            normalized = ["# ", "anchored_symbol", "anchor_span"]
        elif expected_operation == "modify_logic" and not normalized:
            normalized = ["expected_operation", "replace_intent"]

        return normalized[:3]

    def _extract_required_completion_cues(self, text):
        raw_text = text or ""
        cues = []

        for marker in (
            "required code in the final patch:",
            "required code in final patch:",
            "completion cue:",
            "completion cues:",
        ):
            match = re.search(re.escape(marker) + r"\s*(.+)", raw_text, flags=re.IGNORECASE)
            if not match:
                continue

            payload = match.group(1).strip().rstrip(".")
            if any(marker in payload for marker in ("(", ")", "{", "}", "=", ":", ".")):
                cues.append(payload)
            for quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'|`([^`]+)`', payload):
                cue = next((part for part in quoted if part), "").strip()
                if cue:
                    cues.append(cue)

            if not cues and payload:
                parts = [part.strip() for part in re.split(r"\s*\|\s*|\s*;\s*", payload) if part.strip()]
                for part in parts:
                    cues.append(part.rstrip("."))
            break

        deduped = []
        seen = set()
        for cue in cues:
            normalized = cue.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)

        return deduped[:3]

    def _normalize_change_intent(self, change_intent):
        if not isinstance(change_intent, str) or not change_intent.strip():
            return change_intent

        normalized = INTENT_NORMALIZATION.get(change_intent.strip(), change_intent.strip())
        return normalized

    def _infer_change_intent(self, description, target_file=None):
        text = (description or "").lower()

        if "insert" in text and "immediately after" in text:
            return "insert_line_after_anchor"
        if "prompt" in text or "response contract" in text or "json response" in text:
            return "update_prompt_contract"
        if "validate" in text or "validation" in text or "reject" in text:
            return "tighten_validation"
        if "route" in text or "routing" in text:
            return "adjust_routing_order"
        if "state" in text or "snapshot" in text or "persist" in text:
            return "update_state_handling"
        if "refactor" in text:
            return "refactor_local_block"
        return "modify_existing_logic"

    def _is_analysis_only_description(self, text):
        lowered = (text or "").lower().strip()

        banned_starts = [
            "inspect ",
            "review ",
            "clarify ",
            "understand ",
            "analyze ",
            "explore ",
            "consider ",
            "verify ",
            "check ",
            "prepare ",
            "identify ",
            "find ",
            "look at ",
        ]

        if any(lowered.startswith(prefix) for prefix in banned_starts):
            return True

        weak_phrases = [
            "review the current code",
            "define the smallest safe improvement",
            "plan the initial patch",
            "check that the change works",
            "identify nearby stable lines",
            "capture patch context",
            "inspect implementation area",
            "clarify intended behavior",
            "prepare one-file-first change",
            "verify result",
        ]

        return any(phrase in lowered for phrase in weak_phrases)

    def summarize_plan(self, plan):
        return json.dumps(plan, indent=4)

    def _get_known_files(self):
        if self.state_manager is not None:
            files = self.state_manager.get_known_files()
            if files:
                return set(files)
        return set(KNOWN_FILES)

    def _resolve_symbol_to_file(self, symbol):
        if self.state_manager is not None:
            resolved = self.state_manager.resolve_symbol_to_file(symbol)
            if resolved:
                return resolved
        return None

    def _get_known_symbols(self):
        if self.state_manager is not None:
            repo_map = self.state_manager.get_repo_map() or {}
            symbol_to_file = repo_map.get("symbol_to_file") or {}
            if symbol_to_file:
                return list(symbol_to_file.keys())

        return [
            "select_target_block",
            "_prepare_rewritten_block",
            "generate_patch_with_revisions",
            "generate_patch",
            "_fallback_patch",
            "plan_task",
            "_fallback_plan",
            "_build_prompt",
            "_build_anchor_from_task",
            "_build_anchor_from_plan",
            "_apply_anchor_to_child_tasks",
            "_extract_explicit_symbol_from_text",
            "_extract_explicit_file_from_text",
            "apply_patch",
            "verify_patch_context",
            "validate_patch_semantics",
            "route",
            "evaluate",
            "main",
            "build",
        ]

    def _build_prompt(self, task, hint=""):
        pilot_guardrails = self.lesson_memory.format_pilot_guardrails_for_prompt(
            self._get_pilot_guardrails(task),
        )
        return PLANNER_PROMPT_TEMPLATE.format(
            task_id=task["id"],
            task_note=task["note"],
            hint=hint,
            pilot_brief=format_pilot_brief(task),
            pilot_guardrails=pilot_guardrails,
        )

    def _extract_json_object(self, raw_response):
        start = raw_response.find("{")
        end = raw_response.rfind("}")

        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model response.")

        return raw_response[start:end + 1]

    def _validate_task_list(self, tasks):
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("tasks must be a non-empty list.")

        for item in tasks:
            if not isinstance(item, dict):
                raise ValueError("Each task in tasks must be a dictionary.")

            title = item.get("title")
            description = item.get("description")

            if not isinstance(title, str) or not title.strip():
                raise ValueError("Each task must include a non-empty string title.")

            if not isinstance(description, str) or not description.strip():
                raise ValueError("Each task must include a non-empty string description.")

            completion_cues = item.get("completion_cues")
            if completion_cues is not None:
                if not isinstance(completion_cues, list) or not completion_cues:
                    raise ValueError("completion_cues must be a non-empty list when present.")

                for cue in completion_cues:
                    if not isinstance(cue, str) or not cue.strip():
                        raise ValueError("Each completion cue must be a non-empty string.")

            expected_operation = item.get("expected_operation")
            if expected_operation is not None:
                if not isinstance(expected_operation, str) or not expected_operation.strip():
                    raise ValueError("expected_operation must be a non-empty string when present.")

    def _normalize_task_list(self, tasks, parent_task_id):
        normalized = []

        for i, item in enumerate(tasks, start=1):
            if not isinstance(item, dict):
                raise ValueError("Each task in tasks must be a dictionary.")

            raw_change_intent = item.get("change_intent")
            normalized_change_intent = self._normalize_change_intent(raw_change_intent)

            task = {
                "task_id": f"task-{parent_task_id}-{i}",
                "title": item.get("title"),
                "description": item.get("description"),
                "status": "planned",
                "depends_on": [],
                "target_file": item.get("target_file"),
                "target_symbol": item.get("target_symbol"),
                "change_intent": normalized_change_intent,
                "expected_operation": item.get("expected_operation"),
                "completion_cues": item.get("completion_cues") or [],
                "task_type": item.get("task_type"),
            }

            if raw_change_intent != normalized_change_intent:
                task["raw_change_intent"] = raw_change_intent

            canonicalize_task_anchor(
                task,
                state_manager=self.state_manager,
                default_anchor_source="planner_normalized",
            )
            normalized.append(task)

        return normalized


    def _normalize_dependencies(self, dependencies):
        if not isinstance(dependencies, list):
            raise ValueError("dependencies must be a list.")

        known_files = self._get_known_files()
        filtered = []
        seen = set()

        for dep in dependencies:
            if isinstance(dep, str) and dep in known_files and dep not in seen:
                filtered.append(dep)
                seen.add(dep)

        return filtered or ["main.py"]
        
    def _extract_explicit_file_from_text(self, text):
        lowered = (text or "").lower()

        exact_matches = []
        for file_name in self._get_known_files():
            patterns = [
                rf"`{re.escape(file_name.lower())}`",
                rf'"{re.escape(file_name.lower())}"',
                rf"'{re.escape(file_name.lower())}'",
                rf"\b{re.escape(file_name.lower())}\b",
            ]
            if any(re.search(pattern, lowered) for pattern in patterns):
                exact_matches.append(file_name)

        if exact_matches:
            return sorted(exact_matches, key=len, reverse=True)[0]

        return None


    def _extract_explicit_symbol_from_text(self, text):
        raw_text = text or ""
        lowered = raw_text.lower()
        symbols = self._get_known_symbols()

        if not symbols:
            return None

        scoring_text = raw_text
        scoring_lowered = lowered
        for file_name in self._get_known_files():
            scoring_text = re.sub(re.escape(file_name), " ", scoring_text, flags=re.IGNORECASE)
            scoring_lowered = re.sub(re.escape(file_name.lower()), " ", scoring_lowered)

        # 1. Prefer exact quoted/backticked symbol mentions.
        quoted_matches = []
        for symbol in symbols:
            patterns = [
                rf"`{re.escape(symbol)}`",
                rf'"{re.escape(symbol)}"',
                rf"'{re.escape(symbol)}'",
            ]
            if any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in patterns):
                quoted_matches.append(symbol)

        if quoted_matches:
            return sorted(quoted_matches, key=len, reverse=True)[0]

        # 2. Prefer exact identifier-style matches.
        exact_matches = []
        for symbol in symbols:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol.lower())}(?![A-Za-z0-9_])"
            for match in re.finditer(pattern, lowered):
                trailing = lowered[match.end():match.end() + 3]
                if trailing == ".py":
                    continue
                exact_matches.append(symbol)
                break

        if exact_matches:
            return sorted(exact_matches, key=len, reverse=True)[0]

        # 3. Last resort: token-overlap scoring, not raw substring-first matching.
        def normalize_token(token):
            token = (token or "").strip().lower()
            if len(token) > 5 and token.endswith("ing"):
                return token[:-3]
            if len(token) > 4 and token.endswith("ed"):
                return token[:-2]
            if len(token) > 4 and token.endswith("es"):
                return token[:-2]
            if len(token) > 3 and token.endswith("s"):
                return token[:-1]
            return token

        def tokenize(value):
            raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", (value or "").lower())
            parts = []
            for raw in raw_tokens:
                for piece in raw.split("_"):
                    norm = normalize_token(piece)
                    if len(norm) >= 3:
                        parts.append(norm)
            return parts

        text_tokens = tokenize(raw_text)
        if not text_tokens:
            return None

        text_token_set = set(text_tokens)
        scored = []

        for symbol in symbols:
            symbol_tokens = tokenize(symbol)
            if not symbol_tokens:
                continue

            symbol_token_set = set(symbol_tokens)
            overlap = text_token_set & symbol_token_set
            if not overlap:
                continue

            overlap_score = len(overlap)
            token_hits = sum(text_tokens.count(token) for token in overlap)
            coverage = overlap_score / max(len(symbol_token_set), 1)

            scored.append({
                "symbol": symbol,
                "score": (overlap_score * 10) + token_hits + coverage,
                "overlap": overlap_score,
                "coverage": coverage,
            })

        if not scored:
            return None

        scored.sort(
            key=lambda entry: (
                entry["score"],
                entry["overlap"],
                entry["coverage"],
                len(entry["symbol"]),
            ),
            reverse=True,
        )

        best = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None

        # Require a meaningful match before accepting fallback resolution.
        if best["overlap"] < 2 and best["coverage"] < 0.6:
            return None

        if runner_up is not None:
            if best["score"] - runner_up["score"] < 2 and best["overlap"] == runner_up["overlap"]:
                return None

        return best["symbol"]

    def _infer_symbol_from_text_for_file(self, text, target_file):
        """Infer the most relevant symbol in target_file from text. Delegates to shared algorithm."""
        if not self.state_manager or not target_file:
            return None
        symbols = self.state_manager.get_symbols_for_file(target_file) or []
        if not symbols:
            return None
        from main import _score_symbols_for_text
        return _score_symbols_for_text(text, symbols, target_file)

    def _build_anchor_from_task(self, task):
        metadata = task.get("metadata") or {}
        existing = metadata.get("anchor") or {}

        explicit_symbol = self._extract_explicit_symbol_from_text(task.get("note"))
        explicit_file = self._extract_explicit_file_from_text(task.get("note"))

        target_symbol = (
            task.get("target_symbol")
            or metadata.get("target_symbol")
            or existing.get("target_symbol")
            or explicit_symbol
        )

        target_file = (
            task.get("target_file")
            or metadata.get("target_file")
            or existing.get("target_file")
            or explicit_file
        )

        if target_file and not target_symbol:
            inferred_symbol = self._infer_symbol_from_text_for_file(
                task.get("note"),
                target_file,
            )
            if inferred_symbol:
                target_symbol = inferred_symbol

        if target_symbol:
            resolved_file = self._resolve_symbol_to_file(target_symbol)
            if resolved_file:
                target_file = resolved_file

        return merge_anchor_with_span({
            "target_file": target_file,
            "target_symbol": target_symbol,
            "scope": existing.get("scope") or "single_file",
            "anchor_level": "symbol" if target_symbol else "file",
            "anchor_source": existing.get("anchor_source") or ("task_note" if explicit_symbol or explicit_file else "unknown"),
        }, target_file, target_symbol, state_manager=self.state_manager)

    def _build_anchor_from_plan(self, task, plan):
        parent_anchor = self._build_anchor_from_task(task)
        plan_symbol = (
            self._extract_explicit_symbol_from_text(plan.get("goal"))
            or self._extract_explicit_symbol_from_text(plan.get("next_action"))
        )

        effective_symbol = parent_anchor.get("target_symbol") or plan_symbol

        effective_file = parent_anchor.get("target_file")
        if effective_symbol:
            resolved_file = self._resolve_symbol_to_file(effective_symbol)
            if resolved_file:
                effective_file = resolved_file

        if not effective_file:
            effective_file = (
                self._extract_explicit_file_from_text(plan.get("goal"))
                or self._extract_explicit_file_from_text(plan.get("next_action"))
            )

        return merge_anchor_with_span({
            "target_file": effective_file,
            "target_symbol": effective_symbol,
            "scope": parent_anchor.get("scope") or "single_file",
            "anchor_level": "symbol" if effective_symbol else "file",
            "anchor_source": parent_anchor.get("anchor_source") or "task_note",
        }, effective_file, effective_symbol, state_manager=self.state_manager)

    def _apply_anchor_to_child_tasks(self, tasks, anchor, fallback_target_file=None):
        anchored_file = anchor.get("target_file")
        anchored_symbol = anchor.get("target_symbol")
        scope = anchor.get("scope") or "single_file"

        for child in tasks:
            child_metadata = child.get("metadata") or {}
            child_anchor = dict(child_metadata.get("anchor") or {})

            if anchored_symbol:
                child_anchor["target_symbol"] = anchored_symbol
                child_anchor["anchor_level"] = "symbol"

            if anchored_file:
                child_anchor["target_file"] = anchored_file

            child_anchor["scope"] = child_anchor.get("scope") or scope
            child_anchor["anchor_source"] = child_anchor.get("anchor_source") or anchor.get("anchor_source") or "plan_anchor"

            child_metadata["anchor"] = child_anchor
            child["metadata"] = child_metadata

            if anchored_symbol:
                child["target_symbol"] = anchored_symbol

            if scope == "single_file" and anchored_file:
                child["target_file"] = anchored_file
            elif not child.get("target_file"):
                child["target_file"] = fallback_target_file

            canonicalize_task_anchor(
                child,
                target_file=child.get("target_file"),
                target_symbol=child.get("target_symbol"),
                state_manager=self.state_manager,
                default_scope=scope,
                default_anchor_level="symbol" if child.get("target_symbol") else "file",
                default_anchor_source=child_anchor.get("anchor_source") or anchor.get("anchor_source") or "planner_normalized",
            )

            if anchored_symbol:
                description = child.get("description") or child.get("title") or ""
                if anchored_symbol.lower() not in description.lower():
                    child["description"] = (
                        f"{description} (target method: {anchored_symbol})"
                    ).strip()
    
    def _extract_explicit_file_from_task(self, task):
        return self._extract_explicit_file_from_text(task.get("note"))
    
    def _is_architectural_task(self, task):
        note = (task.get("note") or "").lower()
        architectural_tokens = [
            "architecture",
            "architectural",
            "execution-flow",
            "execution flow",
            "child-task",
            "child task",
            "decomposition",
            "routing",
            "compatibility",
            "plan state",
            "planner",
            "main.py",
        ]
        return any(token in note for token in architectural_tokens)

    def _task_mentions_multiple_files(self, task):
        metadata = task.get("metadata") or {}
        text_fields = [
            task.get("note"),
            metadata.get("note"),
            metadata.get("planner_hint"),
        ]
        mentioned = set()

        for text in text_fields:
            if not isinstance(text, str):
                continue
            for file_name in self._get_known_files():
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(file_name)}(?![A-Za-z0-9_])", text):
                    mentioned.add(file_name)

        return len(mentioned) > 1

    def _classify_plan_failure(self, exc):
        message = str(exc or "").strip()
        lowered = message.lower()

        if (
            isinstance(exc, json.JSONDecodeError)
            or "no json object found" in lowered
            or "expecting value" in lowered
            or "extra data" in lowered
        ):
            return "invalid_llm_plan_shape"

        if "without target_symbol" in lowered or "missing target_symbol" in lowered:
            return "planner_missing_target_symbol"

        if "unknown target_file" in lowered or "unknown files" in lowered:
            return "planner_unknown_file_reference"

        return "planner_validation_failure"

    def _should_use_narrow_fallback(self, task, anchor):
        anchored_file = anchor.get("target_file")
        anchored_symbol = anchor.get("target_symbol")

        if not anchored_file or not anchored_symbol:
            return False

        if self._is_architectural_task(task):
            return False

        if self._task_mentions_multiple_files(task):
            return False

        note = str(task.get("note") or "").lower()
        broad_tokens = [
            " and ",
            " then ",
            "across ",
            "multiple files",
            "decompose",
            "child tasks",
            "child-task",
            "planner emits",
            "rollback",
        ]
        return not any(token in note for token in broad_tokens)

    def _build_fallback_completion_cues(self, task, target_symbol, expected_operation):
        task_metadata = task.get("metadata") or {}
        stored_cues = task.get("completion_cues") or task_metadata.get("completion_cues") or []
        normalized_stored_cues = self._normalize_completion_cues({
            "completion_cues": stored_cues,
            "expected_operation": expected_operation,
        })
        concrete_stored_cues = [
            cue for cue in normalized_stored_cues
            if self._completion_cue_looks_concrete(cue)
        ]
        if concrete_stored_cues:
            return concrete_stored_cues[:3]

        extracted_cues = self._extract_required_completion_cues(task.get("note"))
        if extracted_cues:
            return extracted_cues[:3]

        child = {
            "title": f"Fallback update for {target_symbol}",
            "description": str(task.get("note") or "").strip(),
            "target_symbol": target_symbol,
            "expected_operation": expected_operation,
        }
        normalized = self._normalize_completion_cues(child)
        concrete = [cue for cue in normalized if self._completion_cue_looks_concrete(cue)]
        return concrete[:3]

    def _completion_cue_looks_concrete(self, cue):
        text = str(cue or "").strip()
        if not text:
            return False

        concrete_markers = (
            "(",
            ")",
            "[",
            "]",
            "{",
            "}",
            "=",
            ".",
            ":",
            "#",
            "\"",
            "'",
        )
        concrete_tokens = (
            "return ",
            "raise ",
            "if ",
            "elif ",
            "else:",
            "def ",
            "class ",
        )
        return any(marker in text for marker in concrete_markers) or any(token in text for token in concrete_tokens)

    def _build_narrow_fallback_plan(self, task, anchor, failure_code, error_text):
        target_file = anchor.get("target_file")
        target_symbol = anchor.get("target_symbol")
        description = str(task.get("note") or "").strip()
        task_type = str((task.get("task_type") or (task.get("metadata") or {}).get("task_type") or "bugfix")).strip() or "bugfix"
        change_intent = self._normalize_change_intent(
            task.get("change_intent")
            or (task.get("metadata") or {}).get("change_intent")
            or self._infer_change_intent(description, target_file=target_file)
        )
        child = {
            "title": f"Fallback narrow task for {target_symbol}",
            "description": description,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "change_intent": change_intent,
            "expected_operation": self._normalize_expected_operation({
                "title": f"Fallback narrow task for {target_symbol}",
                "description": description,
                "target_symbol": target_symbol,
                "change_intent": change_intent,
            }),
            "completion_cues": [],
            "task_type": task_type,
        }
        child["completion_cues"] = self._build_fallback_completion_cues(
            task,
            target_symbol,
            child["expected_operation"],
        )
        plan = {
            "task_id": task["id"],
            "goal": description,
            "task_type": task_type if task_type in ALLOWED_TASK_TYPES else "bugfix",
            "tasks": self._normalize_task_list([child], parent_task_id=task["id"]),
            "dependencies": [target_file] if target_file else ["main.py"],
            "risks": [
                "Planner fallback was used after planner validation failed.",
                "Keep the patch anchored to the exact target symbol only.",
            ],
            "next_action": f"Apply a narrow single-symbol edit in {target_symbol}.",
            "status": "planned",
            "source": "fallback_narrow_task",
            "llm_error": error_text,
            "metadata": {
                "anchor": dict(anchor),
                "planner_source": "fallback_narrow_task",
                "planner_failure_code": failure_code,
                "planner_failure_detail": error_text,
            },
        }
        self._apply_anchor_to_child_tasks(
            plan["tasks"],
            anchor,
            fallback_target_file=target_file,
        )
        return plan

    def _validate_plan_required_fields(self, plan):
        """Check required top-level fields exist and have correct types."""
        required_fields = ["goal", "tasks", "dependencies", "risks", "next_action", "status"]
        for field in required_fields:
            if field not in plan:
                raise ValueError(f"Missing field in model response: {field}")
        if not isinstance(plan["goal"], str) or not plan["goal"].strip():
            raise ValueError("goal must be a non-empty string.")
        if not isinstance(plan["risks"], list):
            raise ValueError("risks must be a list.")
        if not isinstance(plan["next_action"], str) or not plan["next_action"].strip():
            raise ValueError("next_action must be a non-empty string.")
        if not isinstance(plan["status"], str) or not plan["status"].strip():
            raise ValueError("status must be a non-empty string.")

    def _validate_plan_task_type(self, plan):
        """Validate and normalise task_type field."""
        task_type = plan.get("task_type", "bugfix")
        if not isinstance(task_type, str) or not task_type.strip():
            raise ValueError("task_type must be a non-empty string.")
        task_type = task_type.strip()
        if task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"Unsupported task_type: {task_type}")
        plan["task_type"] = task_type
        return task_type

    def _validate_plan_child_tasks(self, plan):
        """Validate each child task's required fields, intents, operations, and cues."""
        for child in plan["tasks"]:
            target_file = child.get("target_file")
            if not isinstance(target_file, str) or not target_file.strip():
                raise ValueError(f"Child task missing target_file: {child}")
            if target_file not in self._get_known_files():
                raise ValueError(f"Child task references unknown target_file: {target_file}")

            target_symbol = child.get("target_symbol")
            if not isinstance(target_symbol, str) or not target_symbol.strip():
                raise ValueError("Planner produced task without target_symbol")

            change_intent = child.get("change_intent")
            if not isinstance(change_intent, str) or not change_intent.strip():
                raise ValueError(f"Child task missing change_intent: {child}")
            if change_intent not in ALLOWED_CHANGE_INTENTS:
                raise ValueError(f"Unsupported change_intent: {change_intent}")

            child["expected_operation"] = self._normalize_expected_operation(child)
            expected_operation = child.get("expected_operation")
            if expected_operation is not None:
                if not isinstance(expected_operation, str) or not expected_operation.strip():
                    raise ValueError(f"Child task has invalid expected_operation: {child}")
                if expected_operation not in ALLOWED_EXPECTED_OPERATIONS:
                    raise ValueError(f"Unsupported expected_operation: {expected_operation}")

            child["completion_cues"] = self._normalize_completion_cues(child)
            completion_cues = child.get("completion_cues")
            if completion_cues is not None:
                if not isinstance(completion_cues, list):
                    raise ValueError(f"Child task completion_cues must be a list: {child}")
                normalized_cues = []
                for cue in completion_cues:
                    if not isinstance(cue, str) or not cue.strip():
                        raise ValueError(f"Child task completion_cues must contain non-empty strings: {child}")
                    if not self._completion_cue_looks_concrete(cue):
                        raise ValueError("completion_cues must be concrete diff-visible code strings.")
                    normalized_cues.append(cue.strip())
                child["completion_cues"] = normalized_cues

            if not child.get("task_type"):
                child["task_type"] = plan["task_type"]

    def _validate_plan_file_references(self, plan, text_fields):
        """Check that all .py filenames mentioned in plan text are known files."""
        mentioned_files = set()
        for text in text_fields:
            cleaned = (
                text.replace(",", " ").replace(".", " . ").replace("(", " ")
                    .replace(")", " ").replace(":", " ").replace('"', " ").replace("'", " ")
            )
            for token in cleaned.split():
                if token.endswith(".py"):
                    mentioned_files.add(token.strip())
        known_files = self._get_known_files()
        unknown_files = [name for name in mentioned_files if name not in known_files]
        if unknown_files:
            raise ValueError(f"Plan references unknown files: {unknown_files}")

    def _validate_plan(self, plan, parent_task_id, default_target_file=None, task=None):
        """
        Validate the given plan. Delegates to focused sub-validators.
        Returns the validated and normalised plan.
        """
        self._validate_plan_required_fields(plan)

        self._validate_task_list(plan["tasks"])
        plan["tasks"] = self._normalize_task_list(plan["tasks"], parent_task_id=parent_task_id)

        anchor = self._build_anchor_from_plan(task or {}, plan)
        self._apply_anchor_to_child_tasks(plan["tasks"], anchor, fallback_target_file=default_target_file)

        plan_metadata = dict(plan.get("metadata") or {})
        plan_metadata["anchor"] = anchor
        plan["metadata"] = plan_metadata

        for child in plan["tasks"]:
            if self._is_analysis_only_description(child.get("description", "")):
                raise ValueError(f"Child task is not coder-executable: {child.get('description')}")

        plan["dependencies"] = self._normalize_dependencies(plan["dependencies"])

        anchored_file = anchor.get("target_file")
        if anchored_file and anchor.get("scope") == "single_file":
            deps = [dep for dep in plan["dependencies"] if dep == anchored_file]
            plan["dependencies"] = deps or [anchored_file]

        effective_target_file = (
            anchored_file
            or default_target_file
            or (plan["dependencies"][0] if plan["dependencies"] else None)
            or "main.py"
        )

        self._apply_anchor_to_child_tasks(plan["tasks"], anchor, fallback_target_file=effective_target_file)

        task_type = self._validate_plan_task_type(plan)

        text_fields = [plan["goal"], plan["next_action"]]
        for child in plan["tasks"]:
            text_fields.append(str(child.get("title", "")))
            text_fields.append(str(child.get("description", "")))

        self._validate_plan_child_tasks(plan)
        self._validate_plan_file_references(plan, text_fields)

        plan_metadata = plan.get("metadata") or {}
        plan_metadata["anchor"] = dict(anchor)
        plan["metadata"] = plan_metadata

        if task is not None and self._is_architectural_task(task):
            if len(plan["tasks"]) < 2 and not anchored_file:
                raise ValueError(
                    "Architectural tasks must decompose into at least 2 child tasks when no single-file anchor is available."
                )

        return plan
    
    def plan_task(self, task, hint=""):
        prompt = self._build_prompt(task, hint=hint)
        anchor = self._build_anchor_from_task(task)

        try:
            raw_response = ask_model(prompt).strip()
            json_text = self._extract_json_object(raw_response)
            plan = json.loads(json_text)

            if not isinstance(plan, dict):
                raise ValueError("Planner response must be a JSON object.")

            task_metadata = task.get("metadata") or {}
            default_target_file = task_metadata.get("target_file")
            
            plan = self._validate_plan(
                plan,
                parent_task_id=task["id"],
                default_target_file=default_target_file,
                task=task,
            )

            plan["task_id"] = task["id"]
            plan["source"] = "llm"
            plan_metadata = dict(plan.get("metadata") or {})
            plan_metadata["planner_source"] = "llm"
            plan["metadata"] = plan_metadata

            return plan

        except Exception as e:
            failure_code = self._classify_plan_failure(e)
            if self._should_use_narrow_fallback(task, anchor):
                return self._build_narrow_fallback_plan(
                    task,
                    anchor,
                    failure_code=failure_code,
                    error_text=str(e),
                )
            return {
                "task_id": task["id"],
                "goal": task.get("note", ""),
                "tasks": [],
                "dependencies": [],
                "risks": ["Planner failed to produce a valid coder-executable plan."],
                "next_action": "",
                "status": "blocked",
                "source": "planner_error",
                "llm_error": str(e),
                "metadata": {
                    "anchor": anchor,
                    "planner_source": "planner_error",
                    "planner_failure_code": failure_code,
                },
            }
