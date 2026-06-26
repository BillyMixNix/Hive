from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from coder_failures import (
    FAILURE_TAXONOMY,
    UNKNOWN_FAILURE_CODE,
    build_retry_instruction as legacy_build_retry_instruction,
    build_retry_why,
    classify_failure as legacy_classify_failure,
    dispatch_flag,
)


@dataclass
class FailureEvidence:
    stage: Optional[str] = None
    source: Optional[str] = None
    raw_error_text: Optional[str] = None
    task_id: Optional[str] = None
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    patch_id: Optional[str] = None
    apply_id: Optional[str] = None
    target_file: Optional[str] = None
    target_symbol: Optional[str] = None
    change_intent: Optional[str] = None
    expected_operation: Optional[str] = None
    context_mode: Optional[str] = None
    context_target: Optional[str] = None
    context_window: Optional[List[Any]] = None
    context_budget: Dict[str, Any] = field(default_factory=dict)
    context_priority: List[str] = field(default_factory=list)
    anchoring_confidence: Optional[str] = None
    large_file_policy_applied: Optional[bool] = None
    under_anchored_after_trim: Optional[bool] = None
    planner_source: Optional[str] = None
    benchmark_case_id: Optional[str] = None
    attempt_index: Optional[int] = None
    raw_response: Optional[str] = None
    patch_text: Optional[str] = None
    task_metadata: Dict[str, Any] = field(default_factory=dict)
    patch_metadata: Dict[str, Any] = field(default_factory=dict)
    sandbox_report: Dict[str, Any] = field(default_factory=dict)
    reflection_verdict: Optional[str] = None
    reflection_reason: Optional[str] = None
    recent_lessons: List[Dict[str, Any]] = field(default_factory=list)
    rejected_patches: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureClassification:
    failure_family: str = "unknown"
    failure_class: str = "unknown"
    failure_code: str = UNKNOWN_FAILURE_CODE
    confidence: float = 0.0
    summary: str = ""
    matched_rule: Optional[str] = None
    retry_template_key: Optional[str] = None


@dataclass
class RevisionStrategy:
    strategy_code: str = "fallback_retry"
    retry_instruction: str = ""
    emphasis_tags: List[str] = field(default_factory=list)
    extra_constraints: List[str] = field(default_factory=list)
    retry_recommended: bool = True


@dataclass
class LessonPayload:
    file: Optional[str] = None
    change_type: str = "diff_patch"
    failure_reason: str = UNKNOWN_FAILURE_CODE
    failure_family: Optional[str] = None
    failure_class: Optional[str] = None
    failure_code: Optional[str] = None
    failure_pattern: Optional[str] = None
    retry_instruction: Optional[str] = None
    source: str = "failure_intelligence"
    severity: str = "medium"
    target_symbol: Optional[str] = None
    change_intent: Optional[str] = None
    context_mode: Optional[str] = None
    confidence: float = 0.0
    task_id: Optional[str] = None
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    patch_id: Optional[str] = None
    apply_id: Optional[str] = None
    expected_operation: Optional[str] = None
    promote_candidate: bool = True
    attempt_index: Optional[int] = None
    failure_summary: Optional[str] = None
    planner_source: Optional[str] = None
    budget_decision: Optional[str] = None
    benchmark_case_id: Optional[str] = None
    anchoring_confidence: Optional[str] = None
    trigger_pattern: Optional[str] = None
    fix_strategy: Optional[str] = None
    context_requirements: Dict[str, Any] = field(default_factory=dict)
    do_not_apply_when: List[Dict[str, Any]] = field(default_factory=list)
    lesson_level: str = "exact"
    why: Optional[str] = None


@dataclass
class FailureInterpretation:
    evidence: FailureEvidence = field(default_factory=FailureEvidence)
    classification: FailureClassification = field(default_factory=FailureClassification)
    revision: RevisionStrategy = field(default_factory=RevisionStrategy)
    lesson: LessonPayload = field(default_factory=LessonPayload)
    observability: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "evidence": asdict(self.evidence),
            "classification": asdict(self.classification),
            "revision": asdict(self.revision),
            "lesson": asdict(self.lesson),
            "observability": dict(self.observability),
        }


def _coerce_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _build_error_text(stage: Optional[str], raw_error_text: Optional[str], sandbox_report: Dict[str, Any], reflection: Dict[str, Any]) -> str:
    if raw_error_text:
        return str(raw_error_text).strip()

    if sandbox_report:
        errors = sandbox_report.get("errors") or []
        notes = sandbox_report.get("notes") or ""
        joined = " | ".join(str(item) for item in errors if str(item).strip())
        if stage == "sandbox":
            if sandbox_report.get("applied") is not True:
                return f"Sandbox apply failed: {joined or notes}".strip()
            if sandbox_report.get("syntax_valid") is not True:
                return f"Sandbox syntax failed: {joined or notes}".strip()
            if sandbox_report.get("semantic_valid") is not True:
                return f"Sandbox semantic failed: {joined or notes}".strip()

    if reflection:
        verdict = str(reflection.get("verdict") or "").strip().lower()
        detail = str(reflection.get("reflection") or "").strip()
        if verdict == "reject":
            return f"Reflector rejected patch: {detail}".strip()
        if verdict == "revise":
            return f"Reflector requested revision: {detail}".strip()

    return ""


def _normalize_pattern_value(*parts: Any) -> Optional[str]:
    tokens: List[str] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip().lower()
        if not text:
            continue
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
        cleaned = "_".join(segment for segment in cleaned.split("_") if segment)
        if cleaned:
            tokens.append(cleaned)

    if not tokens:
        return None

    seen = set()
    ordered = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)

    return "::".join(ordered)


def infer_trigger_pattern(
    evidence: FailureEvidence,
    classification: FailureClassification,
) -> Optional[str]:
    return _normalize_pattern_value(
        classification.failure_family,
        classification.failure_class,
        classification.failure_code,
        evidence.change_intent,
        evidence.expected_operation,
        evidence.context_mode,
    )


def infer_fix_strategy(
    evidence: FailureEvidence,
    classification: FailureClassification,
    revision: RevisionStrategy,
) -> Optional[str]:
    return _normalize_pattern_value(
        revision.strategy_code,
        classification.failure_code,
        evidence.change_intent,
    )


def build_context_requirements(evidence: FailureEvidence) -> Dict[str, Any]:
    requirements = {
        "context_mode": evidence.context_mode,
        "change_intent": evidence.change_intent,
        "expected_operation": evidence.expected_operation,
    }
    if evidence.target_file:
        requirements["file"] = evidence.target_file
    if evidence.target_symbol:
        requirements["target_symbol"] = evidence.target_symbol
    return {
        key: value
        for key, value in requirements.items()
        if value not in (None, "", [], {})
    }


def build_do_not_apply_when(
    evidence: FailureEvidence,
    classification: FailureClassification,
) -> List[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []

    if evidence.target_symbol:
        conditions.append({
            "field": "target_symbol",
            "op": "missing_or_different",
            "value": evidence.target_symbol,
        })

    if evidence.context_mode == "exact_symbol_block":
        conditions.append({
            "field": "context_mode",
            "op": "not_equal",
            "value": "exact_symbol_block",
        })

    if classification.failure_code in {
        "symbol_anchor_drift",
        "scope_alignment_mismatch",
        "block_rewrite_wrong_method",
    }:
        conditions.append({
            "field": "change_intent",
            "op": "not_equal",
            "value": evidence.change_intent,
        })

    return conditions


def normalize_failure_event(
    *,
    stage: Optional[str] = None,
    error_text: Optional[str] = None,
    task: Optional[Dict[str, Any]] = None,
    patch_data: Optional[Dict[str, Any]] = None,
    sandbox_report: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
    recent_lessons: Optional[List[Dict[str, Any]]] = None,
    rejected_patches: Optional[List[str]] = None,
    attempt_index: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    raw_response: Optional[str] = None,
) -> FailureEvidence:
    task = _coerce_dict(task)
    patch_data = _coerce_dict(patch_data)
    sandbox_report = _coerce_dict(sandbox_report or patch_data.get("sandbox_report"))
    reflection = _coerce_dict(reflection or patch_data.get("reflection"))
    context = _coerce_dict(context)
    metadata = _coerce_dict(metadata)
    task_metadata = _coerce_dict(task.get("metadata"))

    target_file = _first_nonempty(
        patch_data.get("target_file"),
        patch_data.get("child_target_file"),
        task.get("target_file"),
        task_metadata.get("target_file"),
    )
    target_symbol = _first_nonempty(
        patch_data.get("target_symbol"),
        patch_data.get("child_target_symbol"),
        patch_data.get("context_target"),
        context.get("target_name"),
        task.get("target_symbol"),
        task_metadata.get("target_symbol"),
    )
    change_intent = _first_nonempty(
        patch_data.get("change_intent"),
        patch_data.get("child_change_intent"),
        task.get("change_intent"),
        task_metadata.get("change_intent"),
    )
    expected_operation = _first_nonempty(
        patch_data.get("expected_operation"),
        patch_data.get("child_expected_operation"),
        task.get("expected_operation"),
        task_metadata.get("expected_operation"),
    )
    context_mode = _first_nonempty(
        patch_data.get("context_mode"),
        context.get("mode"),
        task_metadata.get("context_mode"),
    )
    context_budget = _coerce_dict(
        patch_data.get("context_budget")
        or context.get("context_budget")
        or metadata.get("context_budget")
    )
    context_priority = list(
        patch_data.get("context_priority")
        or context.get("context_priority")
        or metadata.get("context_priority")
        or []
    )
    anchoring_confidence = _first_nonempty(
        patch_data.get("anchoring_confidence"),
        context.get("anchoring_confidence"),
        metadata.get("anchoring_confidence"),
    )
    large_file_policy_applied = _first_nonempty(
        patch_data.get("large_file_policy_applied"),
        context_budget.get("large_file_policy_applied"),
        metadata.get("large_file_policy_applied"),
    )
    under_anchored_after_trim = _first_nonempty(
        patch_data.get("under_anchored_after_trim"),
        context_budget.get("under_anchored_after_trim"),
        context.get("under_anchored"),
        metadata.get("under_anchored_after_trim"),
    )
    planner_source = _first_nonempty(
        patch_data.get("planner_source"),
        metadata.get("planner_source"),
        task_metadata.get("planner_source"),
    )
    benchmark_case_id = _first_nonempty(
        patch_data.get("benchmark_case_id"),
        metadata.get("benchmark_case_id"),
        task_metadata.get("benchmark_case_id"),
    )
    context_target = _first_nonempty(
        patch_data.get("context_target"),
        context.get("target_name"),
    )
    context_window = _first_nonempty(
        patch_data.get("context_window"),
        [
            context.get("window_start"),
            context.get("window_end"),
        ] if context else None,
    )
    stage = _first_nonempty(stage, metadata.get("stage"))
    source = _first_nonempty(source, metadata.get("source"), stage, "failure_intelligence")

    raw_error_text = _build_error_text(stage, error_text, sandbox_report, reflection)

    return FailureEvidence(
        stage=stage,
        source=source,
        raw_error_text=raw_error_text,
        task_id=_first_nonempty(patch_data.get("task_id"), task.get("id")),
        goal_id=_first_nonempty(patch_data.get("goal_id"), task.get("id")),
        plan_id=_first_nonempty(patch_data.get("plan_id"), metadata.get("plan_id")),
        patch_id=patch_data.get("patch_id"),
        apply_id=patch_data.get("apply_id"),
        target_file=target_file,
        target_symbol=target_symbol,
        change_intent=change_intent,
        expected_operation=expected_operation,
        context_mode=context_mode,
        context_target=context_target,
        context_window=context_window,
        context_budget=context_budget,
        context_priority=context_priority,
        anchoring_confidence=anchoring_confidence,
        large_file_policy_applied=large_file_policy_applied,
        under_anchored_after_trim=under_anchored_after_trim,
        planner_source=planner_source,
        benchmark_case_id=benchmark_case_id,
        attempt_index=attempt_index if attempt_index is not None else patch_data.get("attempt_index"),
        raw_response=_first_nonempty(raw_response, patch_data.get("raw_response")),
        patch_text=_first_nonempty(patch_data.get("patch"), patch_data.get("patch_text")),
        task_metadata=task_metadata,
        patch_metadata=patch_data,
        sandbox_report=sandbox_report,
        reflection_verdict=reflection.get("verdict"),
        reflection_reason=reflection.get("reflection"),
        recent_lessons=_coerce_list_of_dicts(recent_lessons),
        rejected_patches=[str(item) for item in (rejected_patches or []) if str(item).strip()],
        metadata=metadata,
    )


def _match(code: str, confidence: float, summary: str, matched_rule: str) -> FailureClassification:
    taxonomy = FAILURE_TAXONOMY.get(code) or FAILURE_TAXONOMY[UNKNOWN_FAILURE_CODE]
    return FailureClassification(
        failure_family=taxonomy["family"],
        failure_class=taxonomy["class"],
        failure_code=code,
        confidence=confidence,
        summary=summary,
        matched_rule=matched_rule,
        retry_template_key=code,
    )


def _task_allows_documentation_only_patch(evidence: FailureEvidence) -> bool:
    expected_operation = str(evidence.expected_operation or "").strip().lower()
    task_type = str((evidence.task_metadata or {}).get("task_type") or "").strip().lower()
    note = str((evidence.task_metadata or {}).get("note") or evidence.metadata.get("task_note") or "").strip().lower()

    if task_type == "docs":
        return True

    if expected_operation in {"insert_comment", "insert_docstring", "update_help_text"}:
        return True

    comment_tokens = (
        "comment",
        "docstring",
        "explain",
        "explanation",
        "clarify",
        "document",
        "documentation",
        "annotate",
        "annotation",
    )
    return any(token in note for token in comment_tokens)


def _classify_planner_evidence(text, details, evidence):
    """Classify planner-layer failures. Returns FailureClassification or None."""
    planner_failure_code = str((evidence.metadata or {}).get("planner_failure_code") or "").lower()
    budget_decision = str((evidence.context_budget or {}).get("budget_decision") or "").lower()

    if planner_failure_code == "invalid_llm_plan_shape":
        return _match("planner_invalid_json", 0.97, "Planner output did not contain valid JSON.", "planner_invalid_json")
    if planner_failure_code in {
        "planner_validation_failure",
        "planner_missing_target_symbol",
        "planner_unknown_file_reference",
    }:
        return _match("planner_validation_failure", 0.95, "Planner output failed validation for an anchored task.", "planner_validation_failure")
    if str(evidence.planner_source or "").lower() == "fallback_narrow_task":
        # Only classify as planner fallback when there is no specific sandbox/semantic
        # failure to report. If the sandbox caught a real error (details populated),
        # let the semantic or placement classifiers handle it — they run next and give
        # a more actionable retry instruction than the planner-level one.
        if not _coerce_dict(evidence.sandbox_report.get("details")):
            return _match("planner_fallback_used", 0.9, "Planner fallback was used to keep a narrow anchored task executable.", "planner_fallback_used")
    if evidence.under_anchored_after_trim:
        return _match("under_anchored_after_trim", 0.95, "Context trimming removed too much anchor confidence to continue safely.", "prompt_budget_under_anchored")
    if budget_decision == "summary_used" and evidence.stage in {"context_budget", "prompt_budget"}:
        return _match("oversized_context_trimmed", 0.88, "Large prompt context was trimmed to stay within budget.", "prompt_budget_summary")
    return None


def _classify_parser_evidence(text, details, evidence):
    """Classify patch parser and format failures. Returns FailureClassification or None."""
    if "multiple patch: sections" in text or "multiple patch sections" in text:
        return _match("multiple_patch_sections", 0.99, "Model returned more than one PATCH section.", "parser_multiple_patch_sections")
    if "missing diff file headers" in text or "missing diff headers" in text:
        return _match("missing_diff_headers", 0.99, "Patch response omitted unified diff headers.", "parser_missing_diff_headers")
    if "empty model response" in text:
        return _match("empty_model_response", 0.99, "Model returned an empty response.", "parser_empty_model_response")
    if "does not satisfy planner completion_cues" in text or "missing expected diff cues" in text:
        return _match("completion_cue_mismatch", 0.98, "Patch missed planner-provided completion cues.", "planner_completion_cues")
    if "no json object found" in text or "planner output was malformed" in text:
        return _match("planner_invalid_json", 0.97, "Planner output did not contain valid JSON.", "planner_invalid_json")
    if "planner output failed validation" in text:
        return _match("planner_validation_failure", 0.95, "Planner output failed validation.", "planner_validation_failure")
    if (
        "patch change too small or non-functional" in text
        or "no meaningful code changes detected" in text
    ) and _task_allows_documentation_only_patch(evidence):
        return _match(
            "comment_task_rejected_as_nonfunctional", 0.94,
            "A documentation-style task was incorrectly rejected by the generic meaningful-change guard.",
            "policy_comment_only_task",
        )
    if "retry returned the same patch as the previous failed attempt" in text:
        return _match(
            "stagnant_retry_patch", 0.97,
            "Retry reused the same failed patch instead of applying a narrower corrective rule.",
            "retry_same_patch_repeated",
        )
    if (
        "patch failed usefulness check" in text
        or "no meaningful code changes detected" in text
        or "punctuation-only" in text
        or "whitespace-only" in text
    ):
        return _match(
            "non_meaningful_patch", 0.92,
            "Patch did not make a meaningful requested change.",
            "policy_non_meaningful_patch",
        )
    return None


def _classify_targeting_evidence(text, details, evidence):
    """Classify file/symbol targeting drift failures. Returns FailureClassification or None."""
    if "does not match explicit task file" in text:
        return _match("explicit_file_mismatch", 0.98, "Patch drifted away from the explicitly targeted file.", "targeting_explicit_file_mismatch")
    if "does not match explicit task method" in text:
        return _match("explicit_method_mismatch", 0.98, "Patch drifted away from the explicitly targeted symbol.", "targeting_explicit_method_mismatch")
    if "symbol_anchor_drift" in text:
        return _match("symbol_anchor_drift", 0.98, "Patch modified the wrong symbol or failed to prove the target symbol edit.", "targeting_symbol_anchor_drift")
    if "patch appears misaligned with task scope" in text or "patch appears broader than the explicit task intent" in text:
        return _match("scope_alignment_mismatch", 0.95, "Patch drifted away from the requested task scope and intent.", "targeting_scope_alignment")
    if "block rewrite returned incorrect method" in text:
        return _match("block_rewrite_wrong_method", 0.98, "Block rewrite returned a different method than the anchored target.", "block_rewrite_wrong_method")
    if "block_rewrite_contract_failure" in text or "block rewrite returned an empty block" in text:
        return _match("block_rewrite_contract_failure", 0.95, "Block rewrite output violated the selected-method rewrite contract.", "block_rewrite_contract_failure")
    if "block rewrite changed the target method signature" in text:
        return _match("block_rewrite_contract_failure", 0.97, "Block rewrite changed the selected method signature instead of editing the body.", "block_rewrite_signature_changed")
    if "block rewrite produced no meaningful change" in text:
        return _match("block_rewrite_contract_failure", 0.94, "Block rewrite echoed the original block without a meaningful in-method change.", "block_rewrite_no_meaningful_change")
    return None


def _classify_placement_evidence(text, details, evidence):
    """Classify patch placement and context failures. Returns FailureClassification or None."""
    budget_decision = str((evidence.context_budget or {}).get("budget_decision") or "").lower()

    if "patch has no anchor context or removal lines" in text:
        return _match("missing_context_block", 0.97, "Patch omitted real context lines for placement.", "placement_missing_context_block")
    if (
        "anchor_found': false" in text
        or '"anchor_found": false' in text
        or "context_block_found': false" in text
        or '"context_block_found": false' in text
    ):
        return _match("missing_context_block", 0.91, "Patch verification could not find a real context block or anchor in the target file.", "placement_missing_context_block")
    if (
        "mixed_scope_detected': true" in text
        or '"mixed_scope_detected": true' in text
        or "mixed scope detected" in text
        or "mixed_scope_patch" in text
    ):
        return _match("mixed_scope_patch", 0.93, "Patch mixed incompatible indentation or scope levels in one change.", "placement_mixed_scope")
    if "access is denied" in text or "permission denied" in text or "winerror 5" in text:
        return _match("workspace_sandbox_permission_issue", 0.94, "Sandbox failed because the workspace path was not writable.", "sandbox_permission_issue")
    if "under-anchored after trim" in text:
        return _match("under_anchored_after_trim", 0.94, "Context trimming left the task under-anchored.", "prompt_budget_under_anchored")
    if ("context exceeded budget" in text or "context was trimmed" in text) or (
        budget_decision in {"trimmed_related_context", "trimmed_to_selected_block", "summary_used"}
        and evidence.stage in {"context_budget", "prompt_budget"}
    ):
        return _match("oversized_context_trimmed", 0.86, "Prompt context was trimmed to fit the configured budget.", "prompt_budget_trimmed")
    return None


def _classify_semantic_evidence(text, details, evidence):
    """Classify AST/scope semantic failures. Returns FailureClassification or None."""
    # Check details dict first — keys are only present when that specific check failed.
    # Do NOT use `"variable_scope_sanity" in text`: the sandbox serialises the entire
    # checks dict into the error string, so the key appears even when the check passed.

    scope_info = _coerce_dict(details.get("variable_scope_sanity"))
    if scope_info:
        scope_reason = str(scope_info.get("reason") or "").lower()
        scope_problematic = str(scope_info.get("problematic_line") or "").lower()
        if "module scope" in scope_reason or "module scope" in scope_problematic:
            return _match("local_assignment_at_module_scope", 0.93, "Patch introduced a local-style assignment at module scope.", "semantic_scope_local_assignment")
        return _match("local_assignment_at_module_scope", 0.82, "Patch inserted a method that references bare names not in scope; pass all needed variables as explicit parameters.", "semantic_scope_bare_name_ref")

    if "local variable referenced before assignment" in text:
        return _match("local_assignment_at_module_scope", 0.82, "Patch likely inserted a local assignment outside the intended function scope.", "semantic_scope_local_assignment")

    unreachable_info = _coerce_dict(details.get("no_unreachable_code_after_return"))
    if unreachable_info:
        return _match("inserted_after_terminal_statement", 0.95, "Patch inserted executable code after a terminal statement.", "placement_after_terminal_statement")

    structural_info = _coerce_dict(details.get("structural_scope_valid"))
    structural_reason = str(structural_info.get("reason") or "").lower()
    structural_issues = structural_info.get("issues") or []
    if structural_info:
        if "non-docstring expression found at class scope" in structural_reason:
            return _match("duplicate_docstring_instead_of_edit", 0.9, "Patch created a stray docstring-like expression at class scope instead of editing the existing block.", "structure_duplicate_docstring")
        for issue in structural_issues:
            if "non-docstring expression found at class scope" in str(_coerce_dict(issue).get("reason") or "").lower():
                return _match("duplicate_docstring_instead_of_edit", 0.92, "Patch inserted a duplicate docstring-style expression where only the existing docstring should be edited.", "structure_duplicate_docstring")
        return _match("structural_scope_invalid", 0.94, "Patch created invalid executable structure for the candidate file scope.", "structure_invalid_scope")

    if "patch appears to insert executable code after a terminal statement" in text:
        return _match("inserted_after_terminal_statement", 0.9, "Patch inserted code after a terminal statement.", "placement_after_terminal_statement")
    return None


def classify_failure_event(evidence: FailureEvidence) -> FailureClassification:
    text = str(evidence.raw_error_text or "").lower()
    details = _coerce_dict(evidence.sandbox_report.get("details"))
    reflection_verdict = str(evidence.reflection_verdict or "").lower()
    reflection_reason = str(evidence.reflection_reason or "")

    for classifier in (
        _classify_planner_evidence,
        _classify_parser_evidence,
        _classify_targeting_evidence,
        _classify_placement_evidence,
        _classify_semantic_evidence,
    ):
        result = classifier(text, details, evidence)
        if result is not None:
            return result

    if "reflector rejected patch" in text or reflection_verdict == "reject":
        return _match("reflector_reject", 0.9, reflection_reason or "Reflector rejected the patch.", "reflection_reject")

    if evidence.stage == "retry_exhausted" or "retry exhausted" in text:
        return _match("sandbox_retry_exhausted", 0.78, "Retry budget was exhausted without reaching a valid patch.", "orchestration_retry_exhausted")

    fallback_code = legacy_classify_failure(evidence.raw_error_text or "")
    if fallback_code and fallback_code != UNKNOWN_FAILURE_CODE:
        rule = FAILURE_TAXONOMY.get(fallback_code) or FAILURE_TAXONOMY[UNKNOWN_FAILURE_CODE]
        return FailureClassification(
            failure_family=rule["family"],
            failure_class=rule["class"],
            failure_code=fallback_code,
            confidence=0.55,
            summary=str(evidence.raw_error_text or "").strip() or "Classified by legacy fallback.",
            matched_rule="legacy_fallback",
            retry_template_key=fallback_code,
        )

    return _match(UNKNOWN_FAILURE_CODE, 0.2, str(evidence.raw_error_text or "").strip() or "Unknown failure.", "fallback_unknown")


def build_revision_strategy(evidence: FailureEvidence, classification: FailureClassification) -> RevisionStrategy:
    taxonomy = FAILURE_TAXONOMY.get(classification.failure_code) or FAILURE_TAXONOMY[UNKNOWN_FAILURE_CODE]
    retry_instruction = taxonomy.get("instruction") or legacy_build_retry_instruction(evidence.raw_error_text or "")
    extra_constraints = list(taxonomy.get("constraints") or [])
    emphasis_tags = [classification.failure_family, classification.failure_class, classification.failure_code]
    retry_recommended = classification.failure_code != "reflector_reject"

    if classification.failure_code == "local_assignment_at_module_scope":
        if classification.retry_template_key == "semantic_scope_bare_name_ref":
            retry_instruction = (
                "When adding a helper method, pass all needed variables from the parent "
                "function scope as explicit parameters — do not reference bare names from "
                "the enclosing scope."
            )
            extra_constraints.extend([
                "Do not reference variables from the enclosing function scope directly inside a helper.",
                "Pass all required values as explicit parameters to the new helper method.",
            ])
        else:
            retry_instruction = "Insert the assignment inside the target function body near existing local setup lines."
            extra_constraints.extend([
                "Do not add the assignment at module scope.",
                "Keep the edit inside the anchored function body.",
            ])
    elif classification.failure_code == "inserted_after_terminal_statement":
        retry_instruction = "Move the inserted lines above the return/raise boundary in the same block."
        extra_constraints.extend([
            "Do not add executable lines after return, raise, break, or continue.",
        ])
    elif classification.failure_code == "duplicate_docstring_instead_of_edit":
        retry_instruction = "Edit the existing docstring block instead of adding a second docstring or stray string expression."
        extra_constraints.extend([
            "Modify the existing docstring in place.",
            "Do not add a new standalone string expression at class scope.",
        ])
    elif classification.failure_code == "symbol_anchor_drift":
        retry_instruction = "Rewrite only the target symbol and do not modify unrelated symbols."
        extra_constraints.extend([
            "Touch the anchored symbol only.",
            "Do not rename the target symbol.",
        ])
    elif classification.failure_code == "scope_alignment_mismatch":
        retry_instruction = "Realign the patch to the exact requested task scope and remove unrelated changes."
        extra_constraints.extend([
            "Keep the patch inside the requested symbol and only the requested intent-bearing lines.",
            "Do not broaden the diff beyond the task note or explicit replacement tokens.",
        ])
    elif classification.failure_code == "block_rewrite_wrong_method":
        retry_instruction = "Return the exact anchored method only and rewrite that method in place."
        extra_constraints.extend([
            "Do not emit a neighboring method or helper method.",
            "Preserve the anchored method name exactly.",
        ])
    elif classification.failure_code == "block_rewrite_contract_failure":
        retry_instruction = "Repair the block rewrite contract for the selected method before retrying."
        extra_constraints.extend([
            "Return a non-empty rewrite of the selected method only.",
            "Preserve the original def line exactly and change only in-method logic.",
        ])
    elif classification.failure_code == "reflector_reject":
        retry_instruction = "Replace the rejected approach with a narrower patch that addresses only the reflector feedback."
        retry_recommended = False
    elif classification.failure_code == "completion_cue_mismatch":
        retry_instruction = "Stop retrying broad rewrites. Surface the completion cue mismatch instead of forcing unrelated diff lines."
        extra_constraints.extend([
            "Do not broaden the patch only to satisfy completion cue text.",
            "Escalate the planner cue mismatch instead of retrying the same patch shape.",
        ])
        retry_recommended = False
    elif classification.failure_code == "comment_task_rejected_as_nonfunctional":
        retry_instruction = "Allow the narrow comment/docstring/help-text patch. Do not force a documentation task into a logic change."
        extra_constraints.extend([
            "Keep the edit limited to the requested explanatory text.",
            "Do not broaden the patch to satisfy a generic logic-change heuristic.",
        ])
    elif classification.failure_code == "stagnant_retry_patch":
        retry_instruction = "Do not repeat the previous failed patch. Apply one specific corrective rule from the failure and change only the failing lines."
        extra_constraints.extend([
            "Return a materially different diff from the previous failed attempt.",
            "Keep the retry inside the same anchored symbol.",
        ])
    elif classification.failure_code == "non_meaningful_patch":
        retry_instruction = "Return a meaningful requested change instead of punctuation-only, bracket-only, or whitespace-only edits."
        extra_constraints.extend([
            "Modify only the lines needed for the requested behavior or explanatory text.",
            "Do not resubmit a cosmetic-only patch.",
        ])
    elif classification.failure_code == "planner_invalid_json":
        retry_instruction = "Do not send coder retries yet. Regenerate valid planner JSON or use the narrow anchored fallback plan."
        extra_constraints.extend([
            "Keep fallback planning single-file and single-symbol only.",
            "Preserve the anchored target_file and target_symbol exactly.",
        ])
        retry_recommended = False
    elif classification.failure_code == "planner_validation_failure":
        retry_instruction = "Fix planner validation issues or use the narrow fallback plan instead of retrying coder with an invalid plan."
        extra_constraints.extend([
            "Do not continue with missing target_symbol or unknown file references.",
            "Prefer deterministic fallback planning for narrow anchored tasks.",
        ])
        retry_recommended = False
    elif classification.failure_code == "planner_fallback_used":
        retry_instruction = "Keep execution narrow. Do not broaden the fallback plan into multi-file work until planner output stabilizes."
        extra_constraints.extend([
            "Stay on the anchored file and symbol only.",
            "Treat fallback planning as a conservative execution path.",
        ])
    elif classification.failure_code == "mixed_scope_patch":
        retry_instruction = "Rewrite the patch within one indentation boundary only."
        extra_constraints.extend([
            "Do not combine module-level and nested-scope additions in the same patch.",
            "Keep the edit inside the anchored scope.",
        ])
    elif classification.failure_code == "missing_context_block":
        retry_instruction = "Use real unchanged anchor/context lines from the current file before retrying the patch."
        extra_constraints.extend([
            "Do not submit additions-only placement guesses.",
            "Include a real contiguous context block or removal lines.",
        ])
    elif classification.failure_code == "workspace_sandbox_permission_issue":
        retry_instruction = "Escalate or switch to a writable workspace-local sandbox path before retrying."
        extra_constraints.extend([
            "Do not treat sandbox permission failures as patch-quality failures.",
        ])
        retry_recommended = False
    elif classification.failure_code == "oversized_context_trimmed":
        retry_instruction = "Keep the anchored symbol block and summary. Do not re-expand the prompt to a full large-file dump."
        extra_constraints.extend([
            "Prefer exact symbol context over broad raw file context.",
            "Use summary scaffolding for oversized files.",
        ])
    elif classification.failure_code == "under_anchored_after_trim":
        retry_instruction = "Stop early and require a narrower symbol or stronger route/block anchor before retrying."
        extra_constraints.extend([
            "Do not proceed with file-head fallback on large files.",
            "Prefer an exact symbol or block anchor before coding.",
        ])
        retry_recommended = False
    elif classification.failure_code == "sandbox_retry_exhausted":
        retry_instruction = "Stop repeating the same patch shape. Escalate or substantially change the approach before retrying."
        retry_recommended = False

    return RevisionStrategy(
        strategy_code=taxonomy.get("strategy_code") or classification.failure_code,
        retry_instruction=retry_instruction,
        emphasis_tags=emphasis_tags,
        extra_constraints=extra_constraints,
        retry_recommended=retry_recommended,
    )


def build_lesson_payload(
    evidence: FailureEvidence,
    classification: FailureClassification,
    revision: RevisionStrategy,
) -> LessonPayload:
    severity = "medium"
    if classification.failure_family in {"structure", "semantics", "orchestration"}:
        severity = "high"
    elif classification.failure_family in {"reflection", "targeting"}:
        severity = "medium"

    return LessonPayload(
        file=evidence.target_file,
        change_type="diff_patch",
        failure_reason=classification.failure_code,
        failure_family=classification.failure_family,
        failure_class=classification.failure_class,
        failure_code=classification.failure_code,
        failure_pattern=evidence.raw_error_text,
        retry_instruction=revision.retry_instruction,
        source=evidence.source or "failure_intelligence",
        severity=severity,
        target_symbol=evidence.target_symbol,
        change_intent=evidence.change_intent,
        context_mode=evidence.context_mode,
        confidence=classification.confidence,
        task_id=evidence.task_id,
        goal_id=evidence.goal_id,
        plan_id=evidence.plan_id,
        patch_id=evidence.patch_id,
        apply_id=evidence.apply_id,
        expected_operation=evidence.expected_operation,
        promote_candidate=revision.retry_recommended,
        attempt_index=evidence.attempt_index,
        failure_summary=classification.summary,
        planner_source=evidence.planner_source,
        budget_decision=(evidence.context_budget or {}).get("budget_decision"),
        benchmark_case_id=evidence.benchmark_case_id,
        anchoring_confidence=evidence.anchoring_confidence,
        trigger_pattern=infer_trigger_pattern(evidence, classification),
        fix_strategy=infer_fix_strategy(evidence, classification, revision),
        context_requirements=build_context_requirements(evidence),
        do_not_apply_when=build_do_not_apply_when(evidence, classification),
        lesson_level="exact",
        why=build_retry_why(evidence.raw_error_text or ""),
    )


def build_observability_payload(
    evidence: FailureEvidence,
    classification: FailureClassification,
    revision: RevisionStrategy,
) -> Dict[str, Any]:
    trigger_pattern = infer_trigger_pattern(evidence, classification)
    fix_strategy = infer_fix_strategy(evidence, classification, revision)
    return {
        "task_id": evidence.task_id,
        "target_file": evidence.target_file,
        "target_symbol": evidence.target_symbol,
        "change_intent": evidence.change_intent,
        "expected_operation": evidence.expected_operation,
        "failure_family": classification.failure_family,
        "failure_class": classification.failure_class,
        "failure_code": classification.failure_code,
        "failure_category": classification.failure_code,
        "confidence": classification.confidence,
        "retry_instruction": revision.retry_instruction,
        "reason": evidence.raw_error_text,
        "stage": evidence.stage,
        "source": evidence.source,
        "context_mode": evidence.context_mode,
        "planner_source": evidence.planner_source,
        "context_budget": dict(evidence.context_budget or {}),
        "budget_decision": (evidence.context_budget or {}).get("budget_decision"),
        "context_priority": list(evidence.context_priority or []),
        "anchoring_confidence": evidence.anchoring_confidence,
        "large_file_policy_applied": evidence.large_file_policy_applied,
        "under_anchored_after_trim": evidence.under_anchored_after_trim,
        "benchmark_case_id": evidence.benchmark_case_id,
        "attempt_index": evidence.attempt_index,
        "trigger_pattern": trigger_pattern,
        "fix_strategy": fix_strategy,
        "lesson_level": "exact",
    }


def interpret_failure(
    *,
    stage: Optional[str] = None,
    error_text: Optional[str] = None,
    task: Optional[Dict[str, Any]] = None,
    patch_data: Optional[Dict[str, Any]] = None,
    sandbox_report: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
    recent_lessons: Optional[List[Dict[str, Any]]] = None,
    rejected_patches: Optional[List[str]] = None,
    attempt_index: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    raw_response: Optional[str] = None,
) -> FailureInterpretation:
    evidence = normalize_failure_event(
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
    classification = classify_failure_event(evidence)
    revision = build_revision_strategy(evidence, classification)
    lesson = build_lesson_payload(evidence, classification, revision)
    observability = build_observability_payload(evidence, classification, revision)
    return FailureInterpretation(
        evidence=evidence,
        classification=classification,
        revision=revision,
        lesson=lesson,
        observability=observability,
    )
