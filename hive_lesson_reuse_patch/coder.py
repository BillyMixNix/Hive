from pathlib import Path
import ast
import re
import textwrap
from dataclasses import asdict
from typing import Any

PatchData = dict[str, Any]
from hive_llm import ask_model, ask_hive, CreditsExhaustedError
from HiveLessonMemory import LessonMemory

from coder_prompting import (
    build_prompt,
    build_revision_prompt,
    build_block_rewrite_prompt,
    build_symbol_locked_prompt,
    get_plan_goal_text,
    prepare_context_for_prompt,
    prepare_block_rewrite_input,
)
from coder_constraints import derive_patch_constraints
from coder_context import (
    extract_code_blocks,
    select_edit_context,
    select_target_block,
)
from coder_validation import (
    preflight_patch_contract,
    task_allows_comment_only_change,
    validate_patch_data,
    validate_patch_against_anchor,
    validate_patch_matches_task_intent,
    validate_symbol_locked_patch,
)

from coder_block_ops import (
    should_use_block_rewrite,
    rewrite_block_to_diff,
    validate_block_rewrite_minimality,
)
from coder_failures import (
    classify_failure,
    build_retry_guidance,
    build_symbol_drift_retry,
)
from failure_intelligence import (
    infer_fix_strategy,
    infer_trigger_pattern,
    interpret_failure,
)
from scripts.intent_detector import (
    check_intent_with_patch,
    derive_expected_outputs_from_task,
)
from work_ontology import FILE_LEVEL_WORK_MODES, normalize_work_mode


class CoderAgent:
    def __init__(self, memory=None, state_manager=None, executor=None):
        self.lesson_memory = LessonMemory()
        self._lessons_enabled = True  # honored by lesson-fetch chokepoints; toggled by benchmarks
        self.memory = memory
        self.state_manager = state_manager
        self.executor = executor

    def _sandbox_test_patch(self, patch_data: PatchData):
        """
        Run sandbox validation for a proposed patch.

        Returns:
            dict: sandbox report
        """
        if self.executor is None:
            return {
                "applied": False,
                "syntax_valid": False,
                "semantic_valid": False,
                "errors": ["Executor not attached to CoderAgent."],
                "notes": "Sandbox unavailable.",
            }

        return self.executor.test_patch_in_sandbox(
            patch_text=patch_data["patch"],
            target_file=patch_data["target_file"],
            patch_reason=patch_data.get("reason", ""),
        )

    def _target_is_top_level_function(self, target_file, func_name):
        if not target_file or not func_name:
            return False

        try:
            tree = ast.parse(Path(target_file).read_text(encoding="utf-8"))
        except Exception:
            return False

        return any(
            isinstance(node, ast.FunctionDef) and node.name == func_name
            for node in tree.body
        )

    def _run_behavioral_intent_check(self, patch_data, task):
        target_file = patch_data.get("target_file")
        func_name = (
            task.get("target_symbol")
            or (task.get("metadata") or {}).get("target_symbol")
            or patch_data.get("context_target")
        )
        task_note = task.get("note") or (task.get("metadata") or {}).get("note") or ""
        test_inputs = [2, 3, 5]
        expected = derive_expected_outputs_from_task(task_note, func_name or "", test_inputs)

        if expected is None:
            return {"skipped": True, "reason": "no explicit simple return-expression intent detected"}
        if not self._target_is_top_level_function(target_file, func_name):
            return {"skipped": True, "reason": "target symbol is not a top-level function executable by the intent gate"}

        return check_intent_with_patch(
            target_file,
            patch_data.get("patch", ""),
            func_name,
            test_inputs,
            expected,
        )

    def _attach_behavioral_intent_gate(self, candidate_patch_data, task, sandbox_report):
        intent_check = self._run_behavioral_intent_check(candidate_patch_data, task)
        candidate_patch_data["intent_check"] = intent_check

        if intent_check.get("skipped"):
            return sandbox_report
        if intent_check.get("drift_detected"):
            gated_report = dict(sandbox_report)
            gated_report["semantic_valid"] = False
            gated_report["errors"] = list(gated_report.get("errors") or [])
            gated_report["errors"].append("Behavioral intent drift detected.")
            gated_report["notes"] = (gated_report.get("notes") or "") + " Behavioral intent check failed."
            gated_report["intent_check"] = intent_check
            return gated_report

        gated_report = dict(sandbox_report)
        gated_report["intent_check"] = intent_check
        return gated_report

    def _get_change_intent(self, task, plan):
        return (
            task.get("change_intent")
            or ((task.get("metadata") or {}).get("change_intent"))
            or "modify_existing_logic"
        )

    def _get_pilot_guardrails(self, task, plan=None, target_file=None, limit=5):
        if not getattr(self, "_lessons_enabled", True):
            return []
        task = task or {}
        metadata = task.get("metadata") or {}
        resolved_target_file = target_file or task.get("target_file") or metadata.get("target_file")
        target_symbol = task.get("target_symbol") or metadata.get("target_symbol")
        change_type = task.get("task_type") or metadata.get("task_type") or (plan or {}).get("task_type")
        preferred_recovery_action = "retry_patch" if metadata.get("retry_source") == "pilot_revision" else None
        current_context = {
            "file": resolved_target_file,
            "target_symbol": target_symbol,
            "change_type": change_type,
        }
        return self.lesson_memory.get_pilot_guardrails(
            file=resolved_target_file,
            change_type=change_type,
            target_symbol=target_symbol,
            preferred_recovery_action=preferred_recovery_action,
            current_context=current_context,
            limit=limit,
        )

    def _attach_pilot_guardrails(self, task, plan=None, target_file=None):
        task = dict(task or {})
        metadata = dict(task.get("metadata") or {})
        pilot_guardrails = self._get_pilot_guardrails(task, plan=plan, target_file=target_file)
        metadata["pilot_guardrails"] = pilot_guardrails
        metadata["pilot_guardrails_text"] = self.lesson_memory.format_pilot_guardrails_for_prompt(pilot_guardrails)
        task["metadata"] = metadata
        return task

    def _build_pilot_retry_context(self, task):
        metadata = task.get("metadata") or {}
        if metadata.get("retry_source") != "pilot_revision":
            return ""

        lines = [
            "PILOT RETRY CONTEXT:",
            f"- Retry source: {metadata.get('retry_source')}",
            f"- Pilot guidance: {metadata.get('pilot_guidance') or 'none'}",
        ]
        reflector_summary = metadata.get("reflector_summary") or {}
        if reflector_summary:
            lines.append(
                "- Previous reflector summary: "
                f"verdict={reflector_summary.get('verdict') or 'none'} "
                f"notes={reflector_summary.get('reflection') or 'none'}"
            )
        rejected_patch_excerpt = str(metadata.get("rejected_patch_excerpt") or "").strip()
        if rejected_patch_excerpt:
            lines.append("- Previous rejected patch excerpt:")
            lines.append(rejected_patch_excerpt[:1200])
        lines.append("- Do not reuse the same rejected patch shape.")
        lines.append("- Preserve the same target only if the pilot correction still points to that target.")
        return "\n".join(lines)

    def _format_rejection_context(self, task_id, target_file):
        if self.memory is None:
            return "", []

        rejected_patches = self.memory.get_rejected_patches_for_task(
            task_id,
            target_file=target_file,
        )
        if not rejected_patches:
            return "", []

        normalized = []
        for r in rejected_patches:
            if isinstance(r, str):
                normalized.append(r)
            elif isinstance(r, dict):
                metadata = r.get("metadata", {})
                if isinstance(metadata, dict) and "reason" in metadata:
                    normalized.append(metadata["reason"])
                else:
                    normalized.append(r.get("note", str(r)))
            else:
                normalized.append(str(r))

        rejection_context = "Previous patch rejections:\n" + "\n".join(
            f"- {entry}" for entry in normalized
        )
        return rejection_context, normalized

    def _compose_retry_lesson_text(self, last_error, recent_lessons, rejected_patches=None):
        lesson_text = self.lesson_memory.format_lessons_for_prompt(recent_lessons)
        baseline_guidance = build_retry_guidance(
            last_error,
            recent_lessons=[],
            rejected_patches=rejected_patches,
        )
        retry_guidance = build_retry_guidance(
            last_error,
            recent_lessons=recent_lessons,
            rejected_patches=rejected_patches,
        )
        guidance_changed = retry_guidance.strip() != baseline_guidance.strip()
        return {
            "text": f"{retry_guidance}\n\n{lesson_text}".strip(),
            "guidance_changed": guidance_changed,
        }

    def _record_retry_lesson_use(self, lessons, *, guidance_changed=False, reuse_context=None):
        used_lesson_ids = []
        seen = set()

        for lesson in lessons or []:
            lesson_id = lesson.get("lesson_id")
            if not lesson_id or lesson_id in seen:
                continue
            seen.add(lesson_id)
            if self.lesson_memory.record_lesson_use(
                lesson_id,
                match_reasons=lesson.get("_match_reasons") or [],
                guidance_changed=guidance_changed,
                reuse_context=reuse_context,
            ):
                used_lesson_ids.append(lesson_id)

        return used_lesson_ids

    def _record_retry_lesson_outcome(self, lesson_ids, success, outcome_note, *, reuse_helped=None, reuse_context=None):
        seen = set()
        for lesson_id in lesson_ids or []:
            if not lesson_id or lesson_id in seen:
                continue
            seen.add(lesson_id)
            self.lesson_memory.record_lesson_outcome(
                lesson_id,
                success=success,
                outcome_note=outcome_note,
                reuse_helped=reuse_helped,
                reuse_context=reuse_context,
            )

    def _record_failure_interpretation(self, interpretation):
        lesson = asdict(interpretation.lesson)
        self.lesson_memory.add_lesson(**lesson)

        if self.state_manager is not None:
            self.state_manager.record_failure(dict(interpretation.observability))
            self.state_manager.save_snapshot()

    def _lookup_similar_lessons(self, interpretation, limit=1):
        classification = interpretation.classification
        evidence = interpretation.evidence
        return self.lesson_memory.find_relevant_lessons(
            file=evidence.target_file,
            change_type="diff_patch",
            limit=limit,
            failure_code=classification.failure_code,
            target_symbol=evidence.target_symbol,
            context_mode=evidence.context_mode,
            trigger_pattern=interpretation.lesson.trigger_pattern,
            fix_strategy=interpretation.lesson.fix_strategy,
            lesson_level=None,
            current_context={
                "file": evidence.target_file,
                "target_symbol": evidence.target_symbol,
                "context_mode": evidence.context_mode,
                "change_intent": evidence.change_intent,
                "expected_operation": evidence.expected_operation,
                "failure_code": classification.failure_code,
            },
        )

    def _build_retry_lesson_context(
        self,
        *,
        task=None,
        target_file=None,
        context=None,
        failure_code=None,
        interpretation=None,
    ):
        task = task or {}
        context = context or {}
        metadata = task.get("metadata") or {}
        target_symbol = (
            context.get("target_name")
            or (context.get("selected_block") or {}).get("name")
            or task.get("target_symbol")
            or metadata.get("target_symbol")
        )
        context_mode = context.get("mode") or metadata.get("context_mode")
        change_intent = task.get("change_intent") or metadata.get("change_intent")
        expected_operation = task.get("expected_operation") or metadata.get("expected_operation")

        trigger_pattern = None
        fix_strategy = None
        if interpretation is not None:
            trigger_pattern = interpretation.lesson.trigger_pattern
            fix_strategy = interpretation.lesson.fix_strategy
            failure_code = failure_code or interpretation.classification.failure_code

        if trigger_pattern is None and failure_code is not None:
            trigger_pattern = infer_trigger_pattern(
                interpretation.evidence if interpretation is not None else type("LessonEvidence", (), {
                    "change_intent": change_intent,
                    "expected_operation": expected_operation,
                    "context_mode": context_mode,
                })(),
                interpretation.classification if interpretation is not None else type("LessonClassification", (), {
                    "failure_family": "unknown",
                    "failure_class": "unknown",
                    "failure_code": failure_code,
                })(),
            )

        if fix_strategy is None and interpretation is not None:
            fix_strategy = infer_fix_strategy(
                interpretation.evidence,
                interpretation.classification,
                interpretation.revision,
            )

        current_context = {
            "file": target_file,
            "target_symbol": target_symbol,
            "context_mode": context_mode,
            "change_intent": change_intent,
            "expected_operation": expected_operation,
            "failure_code": failure_code,
            "trigger_pattern": trigger_pattern,
            "fix_strategy": fix_strategy,
        }
        return {
            "target_symbol": target_symbol,
            "context_mode": context_mode,
            "trigger_pattern": trigger_pattern,
            "fix_strategy": fix_strategy,
            "current_context": {
                key: value for key, value in current_context.items()
                if value not in (None, "", [], {})
            },
        }

    def _get_retry_lessons(
        self,
        *,
        task=None,
        target_file,
        context=None,
        failure_code=None,
        interpretation=None,
        limit=3,
    ):
        if not getattr(self, "_lessons_enabled", True):
            return []
        lookup = self._build_retry_lesson_context(
            task=task,
            target_file=target_file,
            context=context,
            failure_code=failure_code,
            interpretation=interpretation,
        )
        return self.lesson_memory.get_retry_lessons(
            file=target_file,
            change_type="diff_patch",
            failure_code=failure_code,
            target_symbol=lookup["target_symbol"],
            context_mode=lookup["context_mode"],
            trigger_pattern=lookup["trigger_pattern"],
            fix_strategy=lookup["fix_strategy"],
            current_context=lookup["current_context"],
            limit=limit,
        )

    def _interpret_failure(
        self,
        *,
        stage,
        error_text=None,
        task=None,
        patch_data=None,
        sandbox_report=None,
        reflection=None,
        recent_lessons=None,
        rejected_patches=None,
        attempt_index=None,
        context=None,
        source=None,
        metadata=None,
        raw_response=None,
    ):
        interpretation = interpret_failure(
            stage=stage,
            error_text=error_text,
            task=task,
            patch_data=patch_data,
            sandbox_report=sandbox_report,
            reflection=reflection,
            recent_lessons=recent_lessons,
            rejected_patches=rejected_patches,
            attempt_index=attempt_index,
            context=context,
            source=source,
            metadata=metadata,
            raw_response=raw_response,
        )
        self._record_failure_interpretation(interpretation)
        return interpretation
    
    def _select_context_for_intent(self, task, plan, target_file, full_file_text, revision=False):
        change_intent = self._get_change_intent(task, plan)

        if change_intent == "update_prompt_contract":
            return select_edit_context(
                task,
                plan,
                target_file,
                full_file_text,
                radius=0,
                padding_lines=120,
            )

        if change_intent == "insert_line_after_anchor":
            return select_edit_context(
                task,
                plan,
                target_file,
                full_file_text,
                radius=0,
                padding_lines=30,
            )

        if revision:
            return select_edit_context(
                task,
                plan,
                target_file,
                full_file_text,
                radius=0,
                padding_lines=50,
            )

        return select_edit_context(task, plan, target_file, full_file_text)

    def _should_use_symbol_locked_prompt(self, task, context):
        if not isinstance(context, dict):
            return False

        return (
            context.get("mode") == "exact_symbol_block"
            and bool(task.get("target_symbol") or (task.get("metadata") or {}).get("target_symbol"))
        )

    def _get_related_file_context(self, target_file, target_symbol=None, max_files=2):
        if self.state_manager is None:
            return []

        related_files = []
        if target_symbol:
            related_files = self.state_manager.get_related_files_for_symbol(
                target_symbol,
                depth=1,
            )
        else:
            related_files = self.state_manager.get_file_imports(target_file) + self.state_manager.get_file_imported_by(target_file)

        related_files = [f for f in related_files if f and f != target_file]
        seen = set()
        selected = []

        for f in related_files:
            if f in seen:
                continue
            seen.add(f)
            if len(selected) >= max_files:
                break
            try:
                content = self.state_manager.get_effective_file_text(f)
            except Exception:
                continue
            selected.append({"file": f, "content": content})

        return selected

    def _embed_related_context(self, primary_context, related_files):
        if not related_files:
            return primary_context

        extras = ["\n\n# Related files from repo graph:\n"]

        for entry in related_files:
            extras.append(f"# file: {entry['file']}\n")
            extras.append(entry["content"][:2400])
            extras.append("\n# end of related file\n")

        return primary_context + "\n" + "".join(extras)

    def _validate_patch_against_contract(self, patch_data: PatchData, task, plan, selected_block=None) -> None:
        task_metadata = task.get("metadata") or {}
        target_symbol = task.get("target_symbol") or task_metadata.get("target_symbol")
        change_intent = self._get_change_intent(task, plan)
        patch_text = patch_data.get("patch", "")

        if target_symbol:
            context_target = patch_data.get("context_target")

            if selected_block is not None:
                if selected_block.get("name") != target_symbol:
                    raise ValueError(
                        f"Patch does not match explicit task method. Expected {target_symbol}, got {selected_block.get('name')}"
                    )
            elif context_target and context_target != target_symbol:
                raise ValueError(
                    f"Patch does not match explicit task method. Expected {target_symbol}, got {context_target}"
                )

        if change_intent == "update_prompt_contract":
            forbidden = [
                '"task_type": "planning"',
                '"task_type": "planner_contract_update"',
            ]
            for token in forbidden:
                if token in patch_text:
                    raise ValueError(
                        "Patch does not satisfy prompt-contract intent cleanly; it introduced an unrelated task_type example value."
                    )

        # Patch confidence gating: require a minimal patch size and explicit anchor confirmation.
        if target_symbol and not selected_block and context_target is None:
            raise ValueError("Anchor confidence too low for symbol-bound change")

        if patch_text and len(patch_text.strip()) < 64:
            raise ValueError("Context sufficiency check failed: patch is too small")

    def _build_retry_directives(self, task, previous_patch_text, reflection, base_context):
        lines = [
            "Retry rules:",
            "- Revise the previous patch instead of starting over.",
            "- Prefer the smallest possible line edit that fixes the last failure.",
            "- Keep the same target file and patch shape unless the failure proves the shape itself is wrong.",
            "- Do not broaden the change into neighboring symbols or extra regions.",
        ]

        if previous_patch_text:
            lines.append("- Change fewer lines than the previous attempt whenever possible.")

        if self._should_use_symbol_locked_prompt(task, base_context):
            target_symbol = task.get("target_symbol") or (task.get("metadata") or {}).get("target_symbol")
            if target_symbol:
                lines.extend([
                    f"- Stay inside {target_symbol} only.",
                    f"- Do not replace the whole {target_symbol} block if a smaller in-method edit can fix the issue.",
                ])

        reflection_text = str((reflection or {}).get("reflection") or "").lower()
        if "too broad" in reflection_text or "broad" in reflection_text:
            lines.append("- Narrow scope further; remove replacement logic instead of adding more.")

        return "\n".join(lines)

    def _build_retry_profile(self, task, interpretation=None, *, repeated_failure_count=0):
        failure_code = (
            interpretation.classification.failure_code
            if interpretation is not None and interpretation.classification is not None
            else None
        ) or "unknown_failure"

        profile = {
            "failure_code": failure_code,
            "retry_objective": "Return a narrower corrected patch inside the same target file.",
            "allowed_patch_shape": [
                "same target file",
                "one localized diff",
            ],
            "forbidden_patch_shape": [
                "broader neighboring edits",
                "multi-symbol changes",
            ],
            "stop_condition": "Stop if the next retry would repeat the same invalid patch shape.",
            "prefer_smaller_retry": True,
            "shape_reset_allowed": False,
        }

        if self._is_symbol_locked_task(task):
            target_symbol = self._get_task_anchor(task).get("target_symbol")
            if target_symbol:
                profile["allowed_patch_shape"].append(f"exact symbol rewrite only: {target_symbol}")
                profile["forbidden_patch_shape"].append("new methods")

        overrides = {
            "symbol_anchor_drift": {
                "retry_objective": "Keep the patch on the same file and exact anchored symbol with exact symbol rewrite only.",
                "allowed_patch_shape": ["same file", "same symbol", "exact symbol rewrite only", "no new methods"],
                "forbidden_patch_shape": ["neighboring symbol edits", "renames", "new methods", "file-level fallback"],
                "stop_condition": "Stop if exact symbol identity cannot be proven before generation.",
            },
            "scope_alignment_mismatch": {
                "retry_objective": "Realign the patch to the exact requested task scope and strip unrelated changes.",
                "allowed_patch_shape": ["same file", "same symbol", "task-note-aligned lines only", "smaller localized diff"],
                "forbidden_patch_shape": ["neighboring logic edits", "extra helper changes", "broad scope padding"],
                "stop_condition": "Stop if the retry still cannot align to the requested task scope without unrelated edits.",
            },
            "missing_diff_headers": {
                "retry_objective": "Fix parser contract only while preserving the same content objective.",
                "allowed_patch_shape": ["same target file", "same content objective", "one unified diff with ---/+++ headers"],
                "forbidden_patch_shape": ["scope expansion", "rewriting task objective", "multiple PATCH sections"],
                "stop_condition": "Stop if the response still violates the patch contract after one correction attempt.",
                "prefer_smaller_retry": False,
                "shape_reset_allowed": True,
            },
            "missing_patch_section": {
                "retry_objective": "Fix parser contract only while preserving the same content objective.",
                "allowed_patch_shape": ["same target file", "same content objective", "exactly one PATCH section"],
                "forbidden_patch_shape": ["scope expansion", "prose output", "multiple patch bodies"],
                "stop_condition": "Stop if the response still omits PATCH after one correction attempt.",
                "prefer_smaller_retry": False,
                "shape_reset_allowed": True,
            },
            "multiple_patch_sections": {
                "retry_objective": "Return one valid patch contract only.",
                "allowed_patch_shape": ["same target file", "exactly one PATCH section"],
                "forbidden_patch_shape": ["alternate patches", "fallback diff variants"],
                "stop_condition": "Stop if the response still returns multiple patch bodies.",
                "prefer_smaller_retry": False,
                "shape_reset_allowed": True,
            },
            "non_diff_commentary": {
                "retry_objective": "Remove commentary and return diff-only output.",
                "allowed_patch_shape": ["same target file", "diff-only output"],
                "forbidden_patch_shape": ["markdown fences", "analysis text", "commentary outside diff"],
                "stop_condition": "Stop if the response still contains non-diff commentary.",
                "prefer_smaller_retry": False,
                "shape_reset_allowed": True,
            },
            "too_many_new_methods": {
                "retry_objective": "Shrink the patch into one smaller in-place edit.",
                "allowed_patch_shape": ["one localized edit", "modify existing lines", "at most one method definition change"],
                "forbidden_patch_shape": ["multiple new methods", "broad helper insertion"],
                "stop_condition": "Stop if the retry still requires a broad helper-shaped rewrite.",
            },
            "bad_method_insertion_point": {
                "retry_objective": "Convert the retry to an in-place edit that avoids bad insertion points.",
                "allowed_patch_shape": ["same target file", "in-place method edit only", "no new methods"],
                "forbidden_patch_shape": ["method insertion after return", "new def lines"],
                "stop_condition": "Stop if a clean in-place edit cannot satisfy the task.",
            },
            "inserted_after_terminal_statement": {
                "retry_objective": "Move the change above the terminal boundary or rewrite in place.",
                "allowed_patch_shape": ["same block", "pre-terminal edit", "no new methods"],
                "forbidden_patch_shape": ["lines after return/raise", "new methods"],
                "stop_condition": "Stop if the required behavior still needs post-terminal code.",
            },
            "mixed_scope_patch": {
                "retry_objective": "Keep the retry inside one structural scope boundary.",
                "allowed_patch_shape": ["one indentation boundary", "same anchored scope", "single hunk when possible"],
                "forbidden_patch_shape": ["mixed module and nested scope edits", "scope-crossing additions"],
                "stop_condition": "Stop if the patch still requires mixed scope placement.",
            },
            "structural_scope_invalid": {
                "retry_objective": "Repair structure with the smallest valid in-place change.",
                "allowed_patch_shape": ["same target file", "valid existing scope", "single localized correction"],
                "forbidden_patch_shape": ["stray executable nodes", "invalid class/module scope structure"],
                "stop_condition": "Stop if the resulting structure cannot be kept valid with a localized edit.",
            },
            "block_rewrite_wrong_method": {
                "retry_objective": "Return the exact anchored method only.",
                "allowed_patch_shape": ["same file", "same symbol", "exact block rewrite only", "original method name preserved"],
                "forbidden_patch_shape": ["neighboring method rewrite", "helper method output", "renamed method"],
                "stop_condition": "Stop if block rewrite cannot stay on the anchored method exactly.",
            },
            "block_rewrite_contract_failure": {
                "retry_objective": "Repair the selected-method block rewrite contract without widening scope.",
                "allowed_patch_shape": ["same file", "same symbol", "non-empty method rewrite", "original def line preserved"],
                "forbidden_patch_shape": ["empty block", "signature change", "unchanged echoed block"],
                "stop_condition": "Stop if the block rewrite still cannot satisfy the selected-method contract.",
            },
            "sandbox_semantic_failed": {
                "retry_objective": "Reduce the retry to a smaller semantically safe in-place change.",
                "allowed_patch_shape": ["same target file", "smaller in-place edit", "existing symbols only"],
                "forbidden_patch_shape": ["undefined helpers", "structural expansion", "speculative abstractions"],
                "stop_condition": "Stop if semantic safety still fails for the same shape twice.",
            },
            "stagnant_retry_patch": {
                "retry_objective": "Return a materially different patch on the same symbol with fewer changed lines.",
                "allowed_patch_shape": ["same file", "same symbol", "materially different changed lines", "smaller scope"],
                "forbidden_patch_shape": ["same patch text", "same broad patch shape"],
                "stop_condition": "Stop if the retry would repeat the same lines again.",
            },
            "non_meaningful_patch": {
                "retry_objective": "Produce a cue-bearing substantive change or block.",
                "allowed_patch_shape": ["same target file", "substantive cue-bearing change", "smallest meaningful diff"],
                "forbidden_patch_shape": ["punctuation-only edit", "whitespace-only edit", "cosmetic-only patch"],
                "stop_condition": "Stop with blocked status if no meaningful change can satisfy the task.",
            },
            "missing_context_block": {
                "retry_objective": "Restore a real context block without broadening scope.",
                "allowed_patch_shape": ["same file", "real contiguous context lines", "same anchored region"],
                "forbidden_patch_shape": ["additions-only diff", "guessed insertion point"],
                "stop_condition": "Stop if real file context cannot be anchored exactly.",
            },
        }

        profile.update(overrides.get(failure_code, {}))

        if repeated_failure_count > 0:
            profile["stop_condition"] = (
                "Stop if the retry would reuse the same failure shape again; choose one tighter corrective rule only."
            )

        return profile

    def _format_retry_profile(self, profile):
        lines = [
            "RETRY TRANSFORM:",
            f"- Failure code: {profile['failure_code']}",
            f"- Retry objective: {profile['retry_objective']}",
            "- Allowed patch shape:",
        ]
        lines.extend(f"  - {item}" for item in profile.get("allowed_patch_shape", []))
        lines.append("- Forbidden patch shape:")
        lines.extend(f"  - {item}" for item in profile.get("forbidden_patch_shape", []))
        lines.append(f"- Stop condition: {profile['stop_condition']}")
        if profile.get("prefer_smaller_retry"):
            lines.append("- Retry size rule: Make this retry smaller than the first attempt unless the failure proves the patch shape itself is wrong.")
        else:
            lines.append("- Retry size rule: You may keep patch size similar only to repair the response contract; do not broaden the content objective.")
        return "\n".join(lines)

    def _should_stop_retry(self, interpretation):
        if interpretation is None:
            return False

        if interpretation.revision is not None and not interpretation.revision.retry_recommended:
            return True

        return interpretation.classification.failure_code == "completion_cue_mismatch"

    def _build_retry_prompt(self, task, plan, target_file, revision_file_text, previous_patch_text, reflection, lesson_text, base_context, interpretation=None, repeated_failure_count=0):
        last_error = reflection.get("reflection", "")
        retry_directives = self._build_retry_directives(
            task,
            previous_patch_text,
            reflection,
            base_context,
        )
        retry_profile = self._build_retry_profile(
            task,
            interpretation,
            repeated_failure_count=repeated_failure_count,
        )
        combined_lesson_text = (
            f"{self._format_retry_profile(retry_profile)}\n\n{retry_directives}\n\n{lesson_text}"
        ).strip()
        pilot_retry_context = self._build_pilot_retry_context(task)
        if pilot_retry_context:
            combined_lesson_text = f"{pilot_retry_context}\n\n{combined_lesson_text}"

        if self._should_use_symbol_locked_prompt(task, base_context):
            symbol_retry = None
            if classify_failure(last_error) == "symbol_anchor_drift":
                symbol_retry = build_symbol_drift_retry(task, target_file)

            prompt = build_symbol_locked_prompt(
                task,
                target_file,
                base_context.get("prompt_context_text") or base_context.get("context_text") or revision_file_text,
                lesson_text=f"{symbol_retry or ''}\n\n{combined_lesson_text}".strip(),
            )
            if previous_patch_text:
                prompt += f"\n\nPrevious patch excerpt:\n{previous_patch_text[:1200]}"
            return prompt

        return build_revision_prompt(
            task,
            plan,
            target_file,
            revision_file_text,
            previous_patch_text,
            reflection,
            lesson_text=combined_lesson_text,
        )

    def _apply_prompt_budget(self, task, plan, target_file, context, full_file_text, *, prompt_kind):
        file_summary = self.state_manager.get_file_summary(target_file) if self.state_manager is not None else None
        related_context_text = ""
        if context.get("mode") != "exact_symbol_block":
            related = self._get_related_file_context(
                target_file,
                target_symbol=self._get_task_anchor(task, plan).get("target_symbol"),
                max_files=2,
            )
            if related:
                related_context_text = self._embed_related_context("", related).strip()

        prompt_context_text, budget_metadata = prepare_context_for_prompt(
            target_file=target_file,
            context=context,
            full_file_text=full_file_text,
            related_context_text=related_context_text,
            prompt_kind=prompt_kind,
            task=task,
            plan=plan,
            file_summary=file_summary,
        )

        prepared_context = dict(context)
        prepared_context["prompt_context_text"] = prompt_context_text
        prepared_context["context_budget"] = budget_metadata
        if budget_metadata.get("under_anchored_after_trim"):
            raise ValueError(
                f"Context under-anchored after trim for {target_file}: "
                f"mode={context.get('mode')} budget_decision={budget_metadata.get('budget_decision')}"
            )
        return prepared_context

    def _get_task_anchor(self, task, plan=None):
        task_metadata = task.get("metadata") or {}
        anchor = dict(task_metadata.get("anchor") or {})

        direct_target_file = task.get("target_file")
        direct_target_symbol = task.get("target_symbol")
        direct_target_symbol_id = task.get("target_symbol_id")

        if not anchor and isinstance(plan, dict):
            plan_metadata = plan.get("metadata") or {}
            anchor = dict(plan_metadata.get("anchor") or {})

        resolved = {
            "target_file": direct_target_file or anchor.get("target_file"),
            "target_symbol": direct_target_symbol or anchor.get("target_symbol"),
            "target_symbol_id": direct_target_symbol_id or anchor.get("target_symbol_id"),
            "lineno": task.get("lineno") if task.get("lineno") is not None else anchor.get("lineno"),
            "end_lineno": task.get("end_lineno") if task.get("end_lineno") is not None else anchor.get("end_lineno"),
            "col_offset": task.get("col_offset") if task.get("col_offset") is not None else anchor.get("col_offset"),
            "end_col_offset": task.get("end_col_offset") if task.get("end_col_offset") is not None else anchor.get("end_col_offset"),
            "scope": anchor.get("scope") or "single_file",
            "anchor_source": anchor.get("anchor_source") or "unknown",
        }

        if resolved.get("target_symbol"):
            resolved_target_file = resolved.get("target_file")
            span = None
            if self.state_manager is not None:
                try:
                    span = self.state_manager.get_symbol_span(
                        resolved_target_file,
                        resolved.get("target_symbol"),
                    )
                except Exception:
                    span = None

            if not isinstance(span, dict) and resolved_target_file:
                try:
                    file_text = None
                    if self.state_manager is not None:
                        file_text = self.state_manager.get_effective_file_text(resolved_target_file)
                    if not file_text:
                        file_text = Path(resolved_target_file).read_text(encoding="utf-8")

                    blocks = extract_code_blocks(file_text, target_file=resolved_target_file)
                    span = next(
                        (
                            block for block in blocks
                            if block.get("name") == resolved.get("target_symbol")
                        ),
                        None,
                    )
                except Exception:
                    span = None

            if isinstance(span, dict):
                resolved["target_symbol_id"] = resolved.get("target_symbol_id") or span.get("symbol_id")
                for field in ("lineno", "end_lineno", "col_offset", "end_col_offset"):
                    if resolved.get(field) is None and span.get(field) is not None:
                        resolved[field] = span.get(field)

        return resolved

    def _is_symbol_locked_task(self, task, plan=None):
        return bool(self._get_task_anchor(task, plan).get("target_symbol"))

    def _get_work_mode(self, task, plan=None):
        task = task or {}
        metadata = task.get("metadata") or {}
        plan = plan or {}
        return normalize_work_mode(
            task.get("work_mode") or task.get("task_kind") or metadata.get("work_mode") or metadata.get("task_kind") or plan.get("work_mode") or plan.get("task_kind"),
            task_type=task.get("task_type") or metadata.get("task_type") or plan.get("task_type"),
            text=" ".join(str(value or "") for value in (task.get("note"), task.get("description"), plan.get("goal"), plan.get("next_action"))),
        )

    def _allows_file_level_work(self, task, plan=None):
        if self._is_symbol_locked_task(task, plan):
            return False
        return self._get_work_mode(task, plan) in FILE_LEVEL_WORK_MODES

    def _blocked_anchor_patch(self, task, plan, target_file, reason, error_text):
        fallback = self._fallback_patch(task, plan, target_file)
        fallback["status"] = "blocked"
        fallback["risk_level"] = "high"
        fallback["reason"] = reason
        fallback["llm_error"] = error_text
        return fallback

    def _require_symbol_anchor_contract(self, task, plan, target_file, context):
        anchor = self._get_task_anchor(task, plan)
        target_symbol = anchor.get("target_symbol")
        if not target_symbol:
            return anchor

        required_anchor_fields = ("target_file", "target_symbol", "target_symbol_id", "lineno", "end_lineno")
        missing_anchor_fields = [field for field in required_anchor_fields if not anchor.get(field)]
        if missing_anchor_fields:
            raise ValueError(
                "symbol_anchor_drift: anchored task is missing required anchor proof fields "
                f"{missing_anchor_fields} for {target_symbol}."
            )

        if anchor.get("target_file") != target_file:
            raise ValueError(
                f"symbol_anchor_drift: anchored task file expected {anchor.get('target_file')}, got {target_file}."
            )

        if context.get("mode") != "exact_symbol_block":
            raise ValueError(
                f"symbol_anchor_drift: exact_symbol_block context required for {target_symbol}, got {context.get('mode')}."
            )

        selected_block = context.get("selected_block")
        if not isinstance(selected_block, dict):
            raise ValueError(
                f"symbol_anchor_drift: selected block missing for anchored symbol {target_symbol}."
            )

        if selected_block.get("name") != target_symbol:
            raise ValueError(
                f"symbol_anchor_drift: selected block expected {target_symbol}, got {selected_block.get('name')}."
            )

        if selected_block.get("symbol_id") != anchor.get("target_symbol_id"):
            raise ValueError(
                "symbol_anchor_drift: selected block symbol_id expected "
                f"{anchor.get('target_symbol_id')}, got {selected_block.get('symbol_id')}."
            )

        for field in ("lineno", "end_lineno", "col_offset", "end_col_offset"):
            anchor_value = anchor.get(field)
            block_value = selected_block.get(field)
            if anchor_value is None:
                continue
            if block_value != anchor_value:
                raise ValueError(
                    f"symbol_anchor_drift: selected block {field} expected {anchor_value}, got {block_value}."
                )

        return anchor

    def _prepare_revision_session(self, task, plan, target_file):
        full_file_text = self._get_current_file_text(target_file)
        print(f"[Coder] Read {target_file} ({len(full_file_text)} chars)")

        context = self._select_context_for_intent(
            task,
            plan,
            target_file,
            full_file_text,
            revision=True,
        )
        context = self._apply_prompt_budget(
            task,
            plan,
            target_file,
            context,
            full_file_text,
            prompt_kind="revision",
        )
        anchor = self._require_symbol_anchor_contract(task, plan, target_file, context)
        file_text = context.get("prompt_context_text") or context["context_text"]

        print(
            f"[Coder] Context mode: {context['mode']} | "
            f"target={context.get('target_name')} | "
            f"lines={context['window_start']}-{context['window_end']}"
        )
        print(f"[Coder] Context length: {len(file_text)} chars")
        print(f"[Coder] Context budget: {context.get('context_budget')}")

        use_block_rewrite = should_use_block_rewrite(task, plan, target_file)
        selected_block = context.get("selected_block")

        if use_block_rewrite and selected_block is None:
            anchored_symbol = anchor.get("target_symbol")
            selected_block = select_target_block(
                task,
                plan,
                target_file,
                full_file_text,
                anchored_symbol=anchored_symbol,
            )
            if anchored_symbol and selected_block is None:
                raise ValueError(
                    f"symbol_anchor_drift: exact anchored block required for block rewrite of {anchored_symbol}."
                )

        return {
            "full_file_text": full_file_text,
            "context": context,
            "anchor": anchor,
            "file_text": file_text,
            "revision_file_text": file_text,
            "use_block_rewrite": use_block_rewrite,
            "selected_block": selected_block,
            "block_budget": {},
        }

    def _build_generation_prompt(self, task, plan, target_file, session, lesson_text):
        context = session["context"]
        file_text = session["file_text"]
        selected_block = session["selected_block"]

        if session["use_block_rewrite"] and selected_block is not None:
            file_summary = self.state_manager.get_file_summary(target_file) if self.state_manager is not None else None
            block_prompt_text, block_budget = prepare_block_rewrite_input(
                target_file=target_file,
                block=selected_block,
                file_summary=file_summary,
            )
            prompt_block = dict(selected_block)
            prompt_block["text"] = block_prompt_text
            session["block_budget"] = block_budget
            return build_block_rewrite_prompt(
                task,
                plan,
                target_file,
                prompt_block,
                lesson_text=lesson_text,
            )

        session["block_budget"] = {}
        if self._should_use_symbol_locked_prompt(task, context):
            return build_symbol_locked_prompt(
                task,
                target_file,
                context.get("prompt_context_text") or context.get("context_text") or file_text,
                lesson_text=lesson_text,
            )

        return build_prompt(
            task,
            plan,
            target_file,
            file_text,
            lesson_text=lesson_text,
        )

    def _prepend_rejection_context(self, prompt, rejection_context):
        if rejection_context:
            return f"{rejection_context}\n\n{prompt}"
        return prompt

    def _prepend_pilot_retry_context(self, prompt, task):
        pilot_retry_context = self._build_pilot_retry_context(task)
        if pilot_retry_context:
            return f"{pilot_retry_context}\n\n{prompt}"
        return prompt

    def _generate_candidate_patch_data(self, task, plan, target_file, session, current_prompt, attempt):
        timeout = 120 if attempt == 0 else 45
        raw_response = self._strip_markdown_fences_harder(
            ask_hive(current_prompt, role="coder", timeout=timeout),
            expect_patch_contract=not (
                session["use_block_rewrite"] and session["selected_block"] is not None
            ),
        )
        print("[Coder] Model returned response")
        print(f"[Coder] Response length: {len(raw_response)} chars")

        print("\n[DEBUG] Raw model response preview:")
        print(raw_response[:1500])
        print("\n-----------------------------\n")

        constraints = derive_patch_constraints(task, plan, target_file)
        context = session["context"]
        selected_block = session["selected_block"]
        full_file_text = session["full_file_text"]

        raw_rewrite = raw_response.lstrip()
        looks_like_selected_block = (
            selected_block is not None
            and raw_rewrite.startswith(f"def {selected_block['name']}(")
            and "PATCH:" not in raw_response
        )
        if (
            session["use_block_rewrite"] and selected_block is not None and "PATCH:" not in raw_response
        ) or looks_like_selected_block:
            rewritten_block = self._prepare_rewritten_block(
                raw_response,
                selected_block["text"],
                selected_block["name"],
                expected_operation=task.get("expected_operation") or (task.get("metadata") or {}).get("expected_operation"),
            )

            if not self._rewrite_preserves_parse(full_file_text, selected_block, rewritten_block):
                raise ValueError("Block rewrite does not preserve valid Python structure.")

            print("\n[DEBUG] Raw model response:")
            print(raw_response)
            print("\n-----------------------------\n")

            print("[DEBUG] Selected block name:", selected_block["name"])
            print("[DEBUG] Selected block start:", selected_block["start"])
            print("[DEBUG] Selected block end:", selected_block["end"])
            print("\n-----------------------------\n")

            print("[DEBUG] Original selected block:")
            print(selected_block["text"])
            print("\n-----------------------------\n")

            print("[DEBUG] Rewritten block from model:")
            print(rewritten_block)
            print("\n=============================\n")

            candidate_patch_data = self._build_block_rewrite_patch_data(
                task,
                plan,
                target_file,
                context,
                selected_block,
                full_file_text,
                rewritten_block,
            )
            candidate_patch_data["context_budget"] = {
                **dict(context.get("context_budget") or {}),
                **session.get("block_budget", {}),
            }

            anchor = self._get_task_anchor(task, plan)

            validate_patch_data(candidate_patch_data, task=task)
            validate_patch_against_anchor(candidate_patch_data, anchor)
            validate_symbol_locked_patch(candidate_patch_data, task, selected_block=selected_block)
            validate_patch_matches_task_intent(candidate_patch_data, task)
            self._validate_patch_against_contract(
                candidate_patch_data,
                task,
                plan,
                selected_block=selected_block,
            )

            print(f"[Coder] Built diff from rewritten block: {selected_block['name']}")
            return candidate_patch_data

        preflight_patch_contract(raw_response, constraints=constraints)
        print("[Coder] Patch contract preflight passed")

        candidate_patch_data: PatchData = dict(self._parse_patch_response(raw_response, task))
        print("[Coder] Parsed patch response")
        candidate_patch_data["context_mode"] = context.get("mode")
        candidate_patch_data["context_target"] = context.get("target_name")
        candidate_patch_data["context_window"] = [context.get("window_start"), context.get("window_end")]
        candidate_patch_data["context_symbol_id"] = (context.get("selected_block") or {}).get("symbol_id")
        candidate_patch_data["context_budget"] = dict(context.get("context_budget") or {})
        candidate_patch_data["context_priority"] = list(context.get("context_priority") or [])
        candidate_patch_data["anchoring_confidence"] = context.get("anchoring_confidence")
        candidate_patch_data["large_file_policy_applied"] = (context.get("context_budget") or {}).get("large_file_policy_applied")
        candidate_patch_data["under_anchored_after_trim"] = (context.get("context_budget") or {}).get("under_anchored_after_trim")
        candidate_patch_data["planner_source"] = plan.get("source") if isinstance(plan, dict) else None
        candidate_patch_data["benchmark_case_id"] = (task.get("metadata") or {}).get("benchmark_case_id")
        candidate_patch_data["context_span"] = {
            "lineno": (context.get("selected_block") or {}).get("lineno"),
            "end_lineno": (context.get("selected_block") or {}).get("end_lineno"),
            "col_offset": (context.get("selected_block") or {}).get("col_offset"),
            "end_col_offset": (context.get("selected_block") or {}).get("end_col_offset"),
        }

        anchor = self._get_task_anchor(task, plan)

        validate_patch_data(candidate_patch_data, task=task)
        validate_patch_against_anchor(candidate_patch_data, anchor)
        validate_symbol_locked_patch(
            candidate_patch_data,
            task,
            selected_block=context.get("selected_block"),
        )
        validate_patch_matches_task_intent(candidate_patch_data, task)
        self._validate_patch_against_contract(
            candidate_patch_data,
            task,
            plan,
            selected_block=context.get("selected_block"),
        )
        return candidate_patch_data

    def _patch_has_meaningful_changes(self, patch_data, task):
        patch_text = patch_data.get("patch", "")
        patch_lines = [
            line for line in patch_text.splitlines()
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        ]

        meaningful_changes = []
        for line in patch_lines:
            content = line[1:].strip()
            if not content:
                continue
            if content.startswith("#") and task_allows_comment_only_change(task):
                meaningful_changes.append(line)
                continue
            if content in {"(", ")", ",", ":", "]", "[", "{", "}"}:
                continue
            meaningful_changes.append(line)

        return len(meaningful_changes) > 0

    def _lookup_retry_materials(
        self,
        *,
        task,
        target_file,
        context,
        failure_code,
        interpretation,
        last_error,
        rejected_patches,
        limit=3,
    ):
        recent_lessons = self._get_retry_lessons(
            task=task,
            target_file=target_file,
            context=context,
            failure_code=failure_code,
            interpretation=interpretation,
            limit=limit,
        )
        retry_lesson_package = self._compose_retry_lesson_text(
            last_error,
            recent_lessons,
            rejected_patches=rejected_patches,
        )
        return recent_lessons, retry_lesson_package

    def _activate_retry_lessons(self, recent_lessons, retry_lesson_package):
        return self._record_retry_lesson_use(
            recent_lessons,
            guidance_changed=retry_lesson_package["guidance_changed"],
        )

    def _build_retry_prompt_with_rejections(
        self,
        *,
        task,
        plan,
        target_file,
        revision_file_text,
        previous_patch_text,
        reflection,
        lesson_text,
        context,
        rejection_context,
        interpretation=None,
        repeated_failure_count=0,
    ):
        prompt = self._build_retry_prompt(
            task,
            plan,
            target_file,
            revision_file_text,
            previous_patch_text,
            reflection,
            lesson_text,
            context,
            interpretation=interpretation,
            repeated_failure_count=repeated_failure_count,
        )
        return self._prepend_rejection_context(prompt, rejection_context)

    def _finalize_generation_result(
        self,
        *,
        task,
        plan,
        target_file,
        last_error,
        best_patch_data,
        best_reflection,
        best_confidence,
        candidate_patch_data,
        recent_lessons,
        rejected_patches,
        context,
        max_revisions,
    ):
        if best_patch_data is not None and best_confidence >= 0.6:
            best_patch_data["reflection"] = best_reflection or {
                "reflection": "Returning best validated patch after later revision attempts failed.",
                "confidence": best_confidence,
                "next_step": "Pilot review recommended before apply.",
                "verdict": "revise",
            }
            best_patch_data["status"] = "proposed"
            best_patch_data["reason"] = (
                (best_patch_data.get("reason") or "").strip()
                + " | Returning best validated patch after revision failure."
            ).strip(" |")
            best_patch_data["source"] = "best_candidate"
            best_patch_data["needs_review"] = True
            print("[Coder] Returning best validated patch candidate instead of empty fallback")
            return best_patch_data

        if self._is_symbol_locked_task(task, plan):
            fallback = self._blocked_anchor_patch(
                task,
                plan,
                target_file,
                f"Hard anchor enforcement blocked patch for {self._get_task_anchor(task, plan).get('target_symbol')}",
                last_error or "Patch generation failed after revision attempts.",
            )
        else:
            fallback = self._fallback_patch(task, plan, target_file)
            fallback["llm_error"] = last_error or "Patch generation failed after revision attempts."

        if last_error:
            self._interpret_failure(
                stage="retry_exhausted",
                error_text=f"Retry exhausted: {last_error}",
                task=task,
                patch_data=candidate_patch_data,
                recent_lessons=recent_lessons,
                rejected_patches=rejected_patches,
                attempt_index=max_revisions + 1,
                context=context,
                source="retry_exhausted",
                metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
            )
        return fallback

    def _build_initial_pass_reflector(self):
        class _InitialPassReflector:
            @staticmethod
            def evaluate(candidate_patch_data, **kwargs):
                return {
                    "reflection": "Initial pass accepted after validation.",
                    "confidence": 1.0,
                    "next_step": "Return validated patch.",
                    "verdict": "accept",
                }

        return _InitialPassReflector()


    def _select_target_file(self, plan, target_file=None, task=None):
        """
        Determine the target file for patching.
        Priority:
        1. Canonical task anchor target_file
        2. Repo-resolved target file from anchored symbol
        3. Explicit target_file passed to the method
        4. First dependency in plan
        5. Default to 'main.py'
        """
        anchor = self._get_task_anchor(task or {}, plan)
        anchored_file = anchor.get("target_file")
        anchored_symbol = anchor.get("target_symbol")

        if anchored_file:
            return anchored_file

        if anchored_symbol and self.state_manager is not None:
            resolved = self.state_manager.resolve_symbol_to_file(anchored_symbol)
            if resolved:
                return resolved

            related = self.state_manager.get_related_files_for_symbol(anchored_symbol, depth=1)
            for related_file in related:
                if related_file != anchored_file:
                    return related_file

        if target_file is not None:
            return target_file

        dependencies = plan.get("dependencies", [])
        if dependencies:
            return dependencies[0]

        return "main.py"

    def _get_current_file_text(self, target_file):
        """
        Get the latest effective file text from shared state first,
        then fall back to disk.
        """
        if self.state_manager is not None:
            return self.state_manager.get_effective_file_text(target_file)

        return Path(target_file).read_text(encoding="utf-8")

    def _fallback_patch(self, task, plan, target_file=None):
        dependencies = set(plan.get("dependencies", []))
        goal = get_plan_goal_text(plan).lower()
        next_action = plan.get("next_action", "").lower()

        intended_file = target_file or self._select_target_file(plan, task=task)

        if (
            intended_file == "router.py"
            and ("router.py" in dependencies or "route" in goal or "route" in next_action)
        ):
            patch = textwrap.dedent("""\
            --- router.py
            +++ router.py
             def route(self, user_input, message):
            -        intent = message["intent"]
            +        intent = message.get("intent")
                     text = user_input.lower().strip()
            """)

            return {
                "task_id": task["id"],
                "target_file": "router.py",
                "change_type": "diff_patch",
                "patch": patch,
                "reason": "Make route() use safer intent lookup inside the function scope",
                "risk_level": "low",
                "status": "proposed",
                "source": "fallback",
            }

        return {
            "task_id": task["id"],
            "target_file": intended_file,
            "change_type": "diff_patch",
            "patch": f"--- {intended_file}\n+++ {intended_file}\n",
            "reason": f"No safe fallback patch available for task {task['id']}; LLM output was invalid or insufficiently anchored.",
            "risk_level": "high",
            "status": "blocked",
            "source": "fallback",
        }

    def _parse_patch_response(self, raw_response, task) -> PatchData:
        raw_response = self._strip_markdown_fences_harder(
            raw_response,
            expect_patch_contract=True,
        )
        lines = raw_response.splitlines()

        fields: PatchData = {
            "target_file": None,
            "change_type": None,
            "risk_level": None,
            "status": None,
            "reason": None,
            }

        patch_start = None

        for i, line in enumerate(lines):
            if line.startswith("TARGET_FILE:"):
                fields["target_file"] = line.split(":", 1)[1].strip()
            elif line.startswith("CHANGE_TYPE:"):
                fields["change_type"] = line.split(":", 1)[1].strip()
            elif line.startswith("RISK_LEVEL:"):
                fields["risk_level"] = line.split(":", 1)[1].strip()
            elif line.startswith("STATUS:"):
                fields["status"] = line.split(":", 1)[1].strip()
            elif line.startswith("REASON:"):
                fields["reason"] = line.split(":", 1)[1].strip()
            elif line.strip() == "PATCH:":
                patch_start = i + 1
                break

        if patch_start is None:
            raise ValueError("No PATCH: section found in model response.")

        patch_text = self._strip_markdown_fences_harder(
            "\n".join(lines[patch_start:]),
            expect_patch_contract=True,
        )

        if not patch_text:
            raise ValueError("PATCH section is empty.")

        fields["patch"] = patch_text
        fields["task_id"] = task["id"]
        fields["source"] = "llm"

        required_fields = [
            "target_file",
            "change_type",
            "risk_level",
            "status",
            "reason",
            "patch",
        ]

        for field in required_fields:
            if not fields.get(field):
                raise ValueError(f"Missing field in model response: {field}")

        return fields

    def _strip_markdown_fences_harder(self, text, expect_patch_contract=False):
        text = (text or "").strip()
        if not text:
            return ""

        fenced_blocks = re.findall(
            r"```(?:[A-Za-z0-9_+-]+)?\s*\n(.*?)\n```",
            text,
            flags=re.DOTALL,
        )
        if fenced_blocks:
            preferred = None
            if expect_patch_contract:
                for block in fenced_blocks:
                    if "PATCH:" in block:
                        preferred = block
                        break
            text = (preferred or fenced_blocks[0]).strip()

        for _ in range(3):
            lines = text.splitlines()
            if not lines:
                break

            first = lines[0].strip().lower()
            if first.startswith("```"):
                lines = lines[1:]
            elif first in {"python", "diff", "patch", "text", "markdown"}:
                lines = lines[1:]
            else:
                break

            while lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            text = "\n".join(lines).strip()

        text = re.sub(r"\n```+\s*$", "", text, flags=re.DOTALL).strip()
        return text

    def _sanitize_block_response(self, text):
        """
        Clean LLM block rewrite output so only raw Python remains.
        """
        return self._strip_markdown_fences_harder(text, expect_patch_contract=False)

    def _reindent_block_to_match(self, rewritten_block, original_block_text):
        """
        Re-indent a rewritten block so it matches the indentation
        level of the original block being replaced.
        """
        rewritten_lines = rewritten_block.splitlines()
        original_lines = original_block_text.splitlines()

        if not rewritten_lines or not original_lines:
            return rewritten_block

        original_first = original_lines[0]
        original_indent = len(original_first) - len(original_first.lstrip())

        normalized = []
        for line in rewritten_lines:
            stripped = line.lstrip()

            if not stripped:
                normalized.append("")
                continue

            current_indent = len(line) - len(stripped)
            adjusted_indent = max(0, current_indent - 4)
            normalized.append((" " * (original_indent + adjusted_indent)) + stripped)

        return "\n".join(normalized)

    def _prepare_rewritten_block(self, raw_response, original_block_text, expected_name, expected_operation=None):
        """
        Normalize and validate a block rewrite before converting it to a diff.
        """
        rewritten_block = self._sanitize_block_response(raw_response)
        original_lines = original_block_text.splitlines()
        rewritten_lines = rewritten_block.splitlines()

        if not original_lines or not rewritten_lines:
            raise ValueError("block_rewrite_contract_failure: Block rewrite returned an empty block.")

        if not rewritten_block.lstrip().startswith(f"def {expected_name}("):
            raise ValueError(
                f"block_rewrite_wrong_method: Block rewrite returned incorrect method. Expected {expected_name}"
            )

        if rewritten_lines[0].strip() != original_lines[0].strip():
            raise ValueError(
                "block_rewrite_contract_failure: Block rewrite changed the target method signature. Preserve the original def line and rewrite only the in-method logic."
            )

        if rewritten_block.strip() == original_block_text.strip():
            raise ValueError("block_rewrite_contract_failure: Block rewrite produced no meaningful change.")

        rewritten_block = self._reindent_block_to_match(
            rewritten_block,
            original_block_text,
        )

        validate_block_rewrite_minimality(
            original_block_text,
            rewritten_block,
            expected_operation=expected_operation,
        )

        return rewritten_block

    def _build_block_rewrite_patch_data(self, task, plan, target_file, context, selected_block, full_file_text, rewritten_block) -> PatchData:
        patch_text = rewrite_block_to_diff(
            full_file_text,
            selected_block,
            rewritten_block,
            target_file,
        )

        block_window = [selected_block["start"], selected_block["end"]]
        return {
            "task_id": task["id"],
            "target_file": target_file,
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "reason": f"Rewrite existing method {selected_block['name']} in place",
            "patch": patch_text,
            "source": "llm",
            "context_mode": context.get("mode") or "block_rewrite",
            "context_target": selected_block["name"],
            "context_symbol_id": selected_block.get("symbol_id"),
            "context_span": {
                "lineno": selected_block.get("lineno"),
                "end_lineno": selected_block.get("end_lineno"),
                "col_offset": selected_block.get("col_offset"),
                "end_col_offset": selected_block.get("end_col_offset"),
            },
            "context_window": block_window,
            "context_budget": dict(context.get("context_budget") or {}),
            "context_priority": list(context.get("context_priority") or []),
            "anchoring_confidence": context.get("anchoring_confidence"),
            "large_file_policy_applied": (context.get("context_budget") or {}).get("large_file_policy_applied"),
            "under_anchored_after_trim": (context.get("context_budget") or {}).get("under_anchored_after_trim"),
            "planner_source": plan.get("source") if isinstance(plan, dict) else None,
            "benchmark_case_id": (task.get("metadata") or {}).get("benchmark_case_id"),
        }

    def _rewrite_preserves_parse(self, full_file_text, block, rewritten_block):
        """
        Check whether replacing the selected block with the rewritten block
        still produces a syntactically valid Python file.
        """
        import ast

        old_lines = full_file_text.splitlines()
        new_lines = old_lines[:]
        new_lines[block["start"]:block["end"]] = rewritten_block.splitlines()
        candidate_text = "\n".join(new_lines)

        try:
            ast.parse(candidate_text)
            return True
        except SyntaxError:
            return False

    def generate_patch(self, task, plan):
        reflector = self._build_initial_pass_reflector()
        return self.generate_patch_with_revisions(
            task,
            plan,
            reflector,
            max_revisions=0,
        )

    def _advance_retry_state(
        self, task, plan, target_file, context, session,
        failure_code, interpretation, last_error,
        rejected_patches, reflection, repeated_failure_count,
        lesson_prefix="",
    ):
        """
        Consolidate the repeated pattern: lookup retry materials →
        format rejection context → build retry prompt.
        Returns (recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches).
        Called at the end of every failed attempt branch.
        """
        recent_lessons, retry_lesson_package = self._lookup_retry_materials(
            task=task,
            target_file=target_file,
            context=context,
            failure_code=failure_code,
            interpretation=interpretation,
            last_error=last_error,
            rejected_patches=rejected_patches,
            limit=3,
        )
        rejection_context, rejected_patches = self._format_rejection_context(task["id"], target_file)
        lesson_text = lesson_prefix + retry_lesson_package["text"]

        current_prompt = self._build_retry_prompt_with_rejections(
            task=task,
            plan=plan,
            target_file=target_file,
            revision_file_text=session["revision_file_text"],
            previous_patch_text=session.get("previous_patch_text", ""),
            reflection=reflection,
            lesson_text=lesson_text,
            context=context,
            rejection_context=rejection_context,
            interpretation=interpretation,
            repeated_failure_count=repeated_failure_count,
        )
        active_retry_lesson_ids = self._activate_retry_lessons(recent_lessons, retry_lesson_package)
        return recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches

    def _handle_repeated_patch(
        self, attempt, max_revisions, task, plan, target_file,
        context, session, candidate_patch_data, recent_lessons,
        rejected_patches, active_retry_lesson_ids,
        previous_failure_code, repeated_failure_count,
    ):
        """Handle the case where the retry returned the same patch. Returns updated state dict."""
        last_error = "Retry returned the same patch as the previous failed attempt."
        interpretation = self._interpret_failure(
            stage="exception", error_text=last_error, task=task,
            patch_data=candidate_patch_data, recent_lessons=recent_lessons,
            rejected_patches=rejected_patches, attempt_index=attempt + 1,
            context=context, source="coder_retry_guard",
            metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
        )
        should_break = attempt >= max_revisions
        if should_break:
            return {"should_break": True, "last_error": last_error,
                    "previous_failure_code": interpretation.classification.failure_code,
                    "repeated_failure_count": repeated_failure_count}

        recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches = (
            self._advance_retry_state(
                task, plan, target_file, context, session,
                interpretation.classification.failure_code, interpretation, last_error,
                rejected_patches,
                {"reflection": last_error, "confidence": 0.15,
                 "next_step": "Revise the patch by applying one tight corrective rule and changing only the failing lines.",
                 "verdict": "revise"},
                repeated_failure_count,
            )
        )
        return {
            "should_continue": True, "last_error": last_error,
            "recent_lessons": recent_lessons, "current_prompt": current_prompt,
            "active_retry_lesson_ids": active_retry_lesson_ids,
            "rejected_patches": rejected_patches,
            "previous_failure_code": interpretation.classification.failure_code,
            "repeated_failure_count": repeated_failure_count,
        }

    def _handle_sandbox_failure(
        self, attempt, max_revisions, task, plan, target_file,
        context, session, candidate_patch_data, sandbox_report,
        recent_lessons, rejected_patches, active_retry_lesson_ids,
        previous_failure_code, repeated_failure_count,
    ):
        """Handle sandbox failure. Returns updated state dict."""
        self._record_retry_lesson_outcome(active_retry_lesson_ids, success=False,
                                          outcome_note="failed_again", reuse_helped="hurt")
        sandbox_errors = sandbox_report.get("errors", [])
        notes = sandbox_report.get("notes", "")
        err_str = " | ".join(sandbox_errors) if sandbox_errors else notes
        if sandbox_report.get("applied") is not True:
            last_error = f"Sandbox apply failed: {err_str}"
        elif sandbox_report.get("syntax_valid") is not True:
            last_error = f"Sandbox syntax failed: {err_str}"
        else:
            last_error = f"Sandbox semantic failed: {err_str}"

        interpretation = self._interpret_failure(
            stage="sandbox", error_text=last_error, task=task,
            patch_data=candidate_patch_data, sandbox_report=sandbox_report,
            recent_lessons=recent_lessons, rejected_patches=rejected_patches,
            attempt_index=attempt + 1, context=context, source="sandbox",
            metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
        )
        print(f"[Coder] Lesson recorded: {interpretation.classification.failure_code}")

        new_repeated = (repeated_failure_count + 1
                        if interpretation.classification.failure_code == previous_failure_code
                        else 0)

        should_break = self._should_stop_retry(interpretation) or attempt >= max_revisions
        if should_break:
            return {"should_break": True, "last_error": last_error,
                    "previous_failure_code": interpretation.classification.failure_code,
                    "repeated_failure_count": new_repeated,
                    "active_retry_lesson_ids": []}

        lesson_prefix = (
            "The last retry failed for the same reason again. Apply one specific corrective rule "
            "instead of restating the same patch. Preserve the same target symbol and modify only the failing lines.\n\n"
            if new_repeated > 0 else ""
        ) + f"{interpretation.revision.retry_instruction}\n\n"

        recent_lessons, current_prompt, active_retry_lesson_ids, _, rejected_patches = (
            self._advance_retry_state(
                task, plan, target_file, context, session,
                interpretation.classification.failure_code, interpretation, last_error,
                rejected_patches,
                {"reflection": last_error, "confidence": interpretation.classification.confidence,
                 "next_step": "Revise the patch so it passes sandbox application, syntax, and semantic validation.",
                 "verdict": "revise"},
                new_repeated, lesson_prefix=lesson_prefix,
            )
        )
        return {
            "should_continue": True, "last_error": last_error,
            "recent_lessons": recent_lessons, "current_prompt": current_prompt,
            "active_retry_lesson_ids": active_retry_lesson_ids,
            "rejected_patches": rejected_patches,
            "previous_failure_code": interpretation.classification.failure_code,
            "repeated_failure_count": new_repeated,
        }

    def _handle_reflector_verdict(
        self, attempt, max_revisions, task, plan, target_file,
        context, session, candidate_patch_data, reflection,
        recent_lessons, rejected_patches, active_retry_lesson_ids,
        previous_failure_code, repeated_failure_count,
    ):
        """Handle reflector reject/revise verdict. Returns updated state dict or accept signal."""
        verdict = reflection.get("verdict", "revise")
        confidence = float(reflection.get("confidence", 0.0))

        if verdict == "accept" and confidence >= 0.7:
            self._record_retry_lesson_outcome(active_retry_lesson_ids, success=True,
                                              outcome_note="retry_success", reuse_helped="helped")
            candidate_patch_data["reflection"] = reflection
            return {"should_accept": True, "patch_data": candidate_patch_data}

        self._record_retry_lesson_outcome(active_retry_lesson_ids, success=False,
                                          outcome_note="failed_again", reuse_helped="hurt")
        if verdict == "reject":
            last_error = f"Reflector rejected patch: {reflection.get('reflection')}"
            stage = "reflector"
        else:
            last_error = f"Reflector requested revision: {reflection.get('reflection')}"
            stage = "reflector"

        interpretation = self._interpret_failure(
            stage=stage, error_text=last_error, task=task,
            patch_data=candidate_patch_data, reflection=reflection,
            recent_lessons=recent_lessons, rejected_patches=rejected_patches,
            attempt_index=attempt + 1, context=context, source="reflector",
            metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
        )
        print(f"[Coder] Lesson recorded: {interpretation.classification.failure_code}")

        new_repeated = (repeated_failure_count + 1
                        if interpretation.classification.failure_code == previous_failure_code
                        else 0)

        should_break = self._should_stop_retry(interpretation) or attempt >= max_revisions
        if should_break:
            return {"should_break": True, "last_error": last_error,
                    "previous_failure_code": interpretation.classification.failure_code,
                    "repeated_failure_count": new_repeated,
                    "active_retry_lesson_ids": []}

        lesson_prefix = (
            "The last retry failed for the same reason again. Apply one specific corrective rule "
            "instead of repeating the prior patch shape. Preserve the same target symbol and modify only the failing lines.\n\n"
            if new_repeated > 0 else ""
        ) + (f"{interpretation.revision.retry_instruction}\n\n" if interpretation else "")

        recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches = (
            self._advance_retry_state(
                task, plan, target_file, context, session,
                interpretation.classification.failure_code, interpretation, last_error,
                rejected_patches, reflection, new_repeated, lesson_prefix=lesson_prefix,
            )
        )
        return {
            "should_continue": True, "last_error": last_error,
            "recent_lessons": recent_lessons, "current_prompt": current_prompt,
            "active_retry_lesson_ids": active_retry_lesson_ids,
            "rejected_patches": rejected_patches,
            "previous_failure_code": interpretation.classification.failure_code,
            "repeated_failure_count": new_repeated,
        }

    def generate_patch_with_revisions(self, task, plan, reflector, max_revisions=2):
        print("[Coder DEBUG] task note:", task.get("note"))
        print("[Coder DEBUG] task target_file:", task.get("target_file"))
        print("[Coder DEBUG] plan dependencies:", plan.get("dependencies"))

        target_file = self._select_target_file(plan, target_file=task.get("target_file"), task=task)
        print(f"[Coder] Selected target file: {target_file}")
        task = self._attach_pilot_guardrails(task, plan=plan, target_file=target_file)

        target_symbol = task.get("target_symbol") or (task.get("metadata") or {}).get("target_symbol")
        if not target_symbol and not self._allows_file_level_work(task, plan):
            raise ValueError(f"Task is missing target_symbol. Refusing to generate patch.\nTask: {task}")

        try:
            session = self._prepare_revision_session(task, plan, target_file)
        except Exception as e:
            if self._is_symbol_locked_task(task, plan):
                return self._blocked_anchor_patch(
                    task, plan, target_file,
                    f"Hard anchor enforcement blocked patch for {self._get_task_anchor(task, plan).get('target_symbol')}",
                    f"Could not read target file {target_file}: {e}",
                )
            fallback = self._fallback_patch(task, plan, target_file)
            fallback["llm_error"] = f"Could not read target file {target_file}: {e}"
            return fallback

        context = session["context"]
        revision_file_text = session["revision_file_text"]
        use_block_rewrite = session["use_block_rewrite"]
        selected_block = session["selected_block"]

        recent_lessons = self._get_retry_lessons(task=task, target_file=target_file, context=context, limit=15)
        initial_lesson_package = self._compose_retry_lesson_text("", recent_lessons)
        lesson_text = initial_lesson_package["text"]

        rejection_context, rejected_patches = self._format_rejection_context(task["id"], target_file)
        current_prompt = self._build_generation_prompt(task, plan, target_file, session, lesson_text)
        current_prompt = self._prepend_rejection_context(current_prompt, rejection_context)
        current_prompt = self._prepend_pilot_retry_context(current_prompt, task)
        active_retry_lesson_ids = self._record_retry_lesson_use(
            recent_lessons, guidance_changed=initial_lesson_package["guidance_changed"]
        )

        reflection = {"reflection": "No reflection yet.", "confidence": 0.0,
                      "next_step": "Generate first patch attempt.", "verdict": "revise"}
        best_patch_data = None
        best_reflection = None
        best_confidence = -1.0
        candidate_patch_data = None
        previous_failure_code = None
        repeated_failure_count = 0
        previous_patch_text = ""
        last_error = None

        for attempt in range(max_revisions + 1):
            print(f"[Coder] Patch attempt {attempt + 1}")
            candidate_patch_data = None
            session["previous_patch_text"] = previous_patch_text

            try:
                candidate_patch_data = self._generate_candidate_patch_data(
                    task, plan, target_file, session, current_prompt, attempt
                )
                candidate_patch_text = candidate_patch_data.get("patch", "")

                # Branch 1: same patch repeated
                if attempt > 0 and previous_patch_text and candidate_patch_text == previous_patch_text:
                    state = self._handle_repeated_patch(
                        attempt, max_revisions, task, plan, target_file, context, session,
                        candidate_patch_data, recent_lessons, rejected_patches,
                        active_retry_lesson_ids, previous_failure_code, repeated_failure_count,
                    )
                    last_error = state["last_error"]
                    previous_failure_code = state["previous_failure_code"]
                    repeated_failure_count = state["repeated_failure_count"]
                    if state.get("should_break"):
                        break
                    recent_lessons = state["recent_lessons"]
                    current_prompt = state["current_prompt"]
                    active_retry_lesson_ids = state["active_retry_lesson_ids"]
                    rejected_patches = state["rejected_patches"]
                    continue

                print("[Coder] Patch validation passed")
                sandbox_report = self._sandbox_test_patch(candidate_patch_data)
                if (
                    sandbox_report.get("applied") is True
                    and sandbox_report.get("syntax_valid") is True
                    and sandbox_report.get("semantic_valid") is True
                ):
                    sandbox_report = self._attach_behavioral_intent_gate(
                        candidate_patch_data,
                        task,
                        sandbox_report,
                    )
                print(f"[Coder] Sandbox report: {sandbox_report}")
                candidate_patch_data["sandbox_report"] = sandbox_report

                sandbox_ok = (
                    sandbox_report.get("applied") is True
                    and sandbox_report.get("syntax_valid") is True
                    and sandbox_report.get("semantic_valid") is True
                )

                # Branch 2: sandbox failure
                if not sandbox_ok:
                    state = self._handle_sandbox_failure(
                        attempt, max_revisions, task, plan, target_file, context, session,
                        candidate_patch_data, sandbox_report, recent_lessons, rejected_patches,
                        active_retry_lesson_ids, previous_failure_code, repeated_failure_count,
                    )
                    last_error = state["last_error"]
                    previous_failure_code = state["previous_failure_code"]
                    repeated_failure_count = state["repeated_failure_count"]
                    active_retry_lesson_ids = state.get("active_retry_lesson_ids", [])
                    if state.get("should_break"):
                        break
                    recent_lessons = state["recent_lessons"]
                    current_prompt = state["current_prompt"]
                    rejected_patches = state["rejected_patches"]
                    continue

                patch_is_meaningful = self._patch_has_meaningful_changes(candidate_patch_data, task)
                patch_is_blocked = candidate_patch_data.get("status") == "blocked"

                # Branch 3a: not meaningful
                if not patch_is_meaningful:
                    self._record_retry_lesson_outcome(active_retry_lesson_ids, success=False,
                                                      outcome_note="failed_again", reuse_helped="hurt")
                    active_retry_lesson_ids = []
                    last_error = "Patch failed usefulness check: no meaningful code changes detected."
                    print(f"[Coder] {last_error}")
                    interpretation = self._interpret_failure(
                        stage="exception", error_text=last_error, task=task,
                        patch_data=candidate_patch_data, recent_lessons=recent_lessons,
                        rejected_patches=rejected_patches, attempt_index=attempt + 1,
                        context=context, source="coder_usefulness",
                        metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
                    )
                    print(f"[Coder] Lesson recorded: {interpretation.classification.failure_code}")
                    previous_failure_code = interpretation.classification.failure_code
                    previous_patch_text = candidate_patch_text
                    if attempt >= max_revisions:
                        break
                    recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches = (
                        self._advance_retry_state(
                            task, plan, target_file, context, session,
                            interpretation.classification.failure_code, interpretation, last_error,
                            rejected_patches,
                            {"reflection": last_error, "confidence": 0.2,
                             "next_step": "Revise the patch so it makes a meaningful logic change.",
                             "verdict": "revise"},
                            repeated_failure_count,
                        )
                    )
                    continue

                reflection = reflector.evaluate(
                    candidate_patch_data, task=task, plan=plan,
                    pilot_guardrails=(task.get("metadata") or {}).get("pilot_guardrails"),
                )
                confidence = float(reflection.get("confidence", 0.0))

                # Track best candidate
                if patch_is_meaningful and not patch_is_blocked and confidence >= 0.5:
                    if confidence > best_confidence:
                        best_patch_data = dict(candidate_patch_data)
                        best_reflection = dict(reflection)
                        best_confidence = confidence
                        print(f"[Coder] Best patch candidate updated (confidence={confidence})")
                print(f"[Coder] Reflector verdict: {reflection.get('verdict')}")

                # Branch 3b: reflector verdict
                state = self._handle_reflector_verdict(
                    attempt, max_revisions, task, plan, target_file, context, session,
                    candidate_patch_data, reflection, recent_lessons, rejected_patches,
                    active_retry_lesson_ids, previous_failure_code, repeated_failure_count,
                )
                if state.get("should_accept"):
                    return state["patch_data"]

                last_error = state["last_error"]
                previous_failure_code = state["previous_failure_code"]
                repeated_failure_count = state["repeated_failure_count"]
                active_retry_lesson_ids = state.get("active_retry_lesson_ids", [])
                if state.get("should_break"):
                    break
                recent_lessons = state["recent_lessons"]
                current_prompt = state["current_prompt"]
                rejected_patches = state["rejected_patches"]
                previous_patch_text = candidate_patch_data.get("patch", "")

            except CreditsExhaustedError as e:
                # Don't retry — no amount of retrying will work without credits.
                # Park the task cleanly without burning the retry budget or recording lessons.
                print(f"[Coder] Credits exhausted — parking task immediately: {e}")
                last_error = str(e)
                if candidate_patch_data:
                    candidate_patch_data["llm_error"] = last_error
                    candidate_patch_data["source"] = "credits_exhausted"
                break

            except Exception as e:
                print(f"[Coder] Exception: {e}")
                self._record_retry_lesson_outcome(active_retry_lesson_ids, success=False,
                                                  outcome_note="failed_again", reuse_helped="hurt")
                active_retry_lesson_ids = []
                last_error = str(e)
                interpretation = self._interpret_failure(
                    stage="exception", error_text=last_error, task=task,
                    patch_data=candidate_patch_data, recent_lessons=recent_lessons,
                    rejected_patches=rejected_patches, attempt_index=attempt + 1,
                    context=context, source="coder_exception",
                    metadata={"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None},
                )
                print(f"[Coder] Lesson recorded: {interpretation.classification.failure_code}")
                repeated_failure_count = (
                    repeated_failure_count + 1
                    if interpretation.classification.failure_code == previous_failure_code
                    else 0
                )
                previous_failure_code = interpretation.classification.failure_code
                if self._should_stop_retry(interpretation):
                    break
                if (use_block_rewrite and selected_block is not None
                        and attempt < 2 and "no meaningful change" in last_error.lower()):
                    current_prompt = (
                        "Your previous rewrite returned the original method or no meaningful behavioral change.\n"
                        "Rewrite the SAME method again.\n"
                        "You must preserve the same method name, but make a real behavioral improvement.\n"
                        "Do not return the original method unchanged.\n"
                        "Do not return markdown.\n"
                        "Do not add any new method.\n\n"
                        + build_block_rewrite_prompt(task, plan, target_file, selected_block, lesson_text=lesson_text)
                    )
                    active_retry_lesson_ids = self._record_retry_lesson_use(
                        recent_lessons, guidance_changed=bool(recent_lessons)
                    )
                    continue
                if attempt >= max_revisions:
                    break
                recent_lessons, current_prompt, active_retry_lesson_ids, rejection_context, rejected_patches = (
                    self._advance_retry_state(
                        task, plan, target_file, context, session,
                        interpretation.classification.failure_code, interpretation, last_error,
                        rejected_patches, reflection, repeated_failure_count,
                        lesson_prefix=(
                            "The last retry failed for the same reason again. Apply one specific corrective rule "
                            "instead of reusing the same malformed response.\n\n"
                            if repeated_failure_count > 0 else ""
                        ) + f"{interpretation.revision.retry_instruction}\n\n",
                    )
                )

        self._record_retry_lesson_outcome(active_retry_lesson_ids, success=False,
                                          outcome_note="failed_again", reuse_helped="hurt")
        return self._finalize_generation_result(
            task=task, plan=plan, target_file=target_file, last_error=last_error,
            best_patch_data=best_patch_data, best_reflection=best_reflection,
            best_confidence=best_confidence, candidate_patch_data=candidate_patch_data,
            recent_lessons=recent_lessons, rejected_patches=rejected_patches,
            context=context if "context" in locals() else None, max_revisions=max_revisions,
        )
