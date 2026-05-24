import json
import os
import re
import tempfile
import uuid
from datetime import datetime

# Failure families whose lessons are universal — they apply to any Python
# codebase, not just Hive's own code.
_UNIVERSAL_FAMILIES = {
    "formatting",   # missing PATCH section, empty patch, wrong format
    "orchestration", # retry exhausted, budget exceeded
    "doctrine",     # no new methods, in-place rewrite only
    "runtime",      # rate limits, timeouts, empty responses
}

# Patterns that indicate a lesson is domain-specific (references a specific
# file, symbol, or codebase artifact).
_DOMAIN_HINT_RE = re.compile(
    r"\b\w+\.py\b"              # specific .py file reference
    r"|\bsymbol\s+[a-z_]\w+"   # "symbol normalize_command" etc.
    r"|\bfunction\s+[a-z_]\w+" # "function validate_patch" etc.
    r"|\bmodify\s+[a-z_]\w+"   # "modify requested symbol X"
    r"|\bdoes not modify\s+\w+" # anchor drift messages
, re.IGNORECASE)


def _classify_lesson_scope(lesson):
    """Return 'universal', 'domain', or 'unclassified' for a lesson."""
    family = (lesson.get("failure_family") or "").split("/")[0].lower()
    if family in _UNIVERSAL_FAMILIES:
        return "universal"

    pattern = lesson.get("failure_pattern") or ""
    reason = lesson.get("failure_reason") or ""
    combined = f"{pattern} {reason}"
    if _DOMAIN_HINT_RE.search(combined):
        return "domain"

    return "unclassified"


class LessonMemory:
    GENERALIZATION_MIN_SUCCESS = 2

    def __init__(self, path="hive_lessons.jsonl", max_entries=500):
        self.path = path
        self.max_entries = max_entries
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                pass

    def add_lesson(
        self,
        file,
        change_type,
        failure_reason,
        retry_instruction,
        task_id=None,
        goal_id=None,
        plan_id=None,
        patch_id=None,
        apply_id=None,
        failure_pattern=None,
        source="validator",
        severity="medium",
        promote_candidate=False,
        **extra_fields,
    ):
        lesson = {
            "lesson_id": extra_fields.pop("lesson_id", str(uuid.uuid4())),
            "timestamp": datetime.now().isoformat(),
            "task_id": task_id,
            "goal_id": goal_id,
            "plan_id": plan_id,
            "patch_id": patch_id,
            "apply_id": apply_id,
            "file": file,
            "change_type": change_type,
            "failure_reason": failure_reason,
            "failure_pattern": failure_pattern,
            "retry_instruction": retry_instruction,
            "source": source,
            "severity": severity,
            "promote_candidate": promote_candidate,
            "times_used": extra_fields.pop("times_used", 0),
            "success_after_use": extra_fields.pop("success_after_use", 0),
            "failure_after_use": extra_fields.pop("failure_after_use", 0),
            "promotion_state": extra_fields.pop("promotion_state", "raw"),
            "trigger_pattern": extra_fields.pop("trigger_pattern", None),
            "fix_strategy": extra_fields.pop("fix_strategy", None),
            "context_requirements": extra_fields.pop("context_requirements", {}),
            "do_not_apply_when": extra_fields.pop("do_not_apply_when", []),
            "lesson_level": extra_fields.pop("lesson_level", "exact"),
            "scope": extra_fields.pop("scope", None),
        }
        if lesson["scope"] is None:
            lesson["scope"] = _classify_lesson_scope(lesson)
        lesson.update(extra_fields)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(lesson) + "\n")

        self._trim()
    
    def _trim(self):
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) > self.max_entries:
            lines = lines[-self.max_entries:]
            with open(self.path, "w", encoding="utf-8") as f:
                f.writelines(lines)

    def _normalize_lesson_record(self, lesson):
        normalized = dict(lesson)
        normalized["lesson_id"] = normalized.get("lesson_id") or str(uuid.uuid4())
        normalized["times_used"] = int(normalized.get("times_used", 0) or 0)
        normalized["lesson_level"] = str(normalized.get("lesson_level") or "exact").strip().lower()
        if normalized["lesson_level"] not in {"exact", "generalized"}:
            normalized["lesson_level"] = "exact"
        normalized["trigger_pattern"] = normalized.get("trigger_pattern") or None
        normalized["fix_strategy"] = normalized.get("fix_strategy") or None

        context_requirements = normalized.get("context_requirements")
        normalized["context_requirements"] = (
            dict(context_requirements)
            if isinstance(context_requirements, dict)
            else {}
        )

        do_not_apply_when = normalized.get("do_not_apply_when")
        if isinstance(do_not_apply_when, list):
            normalized["do_not_apply_when"] = [
                item for item in do_not_apply_when if isinstance(item, dict)
            ]
        else:
            normalized["do_not_apply_when"] = []

        success_after_use = normalized.get("success_after_use")
        failure_after_use = normalized.get("failure_after_use")
        last_outcome = normalized.get("last_outcome")
        last_outcome_note = normalized.get("last_outcome_note")

        if success_after_use is None and failure_after_use is None:
            success_after_use = 1 if (
                last_outcome == "success"
                or last_outcome_note == "retry_success"
            ) else 0
            failure_after_use = 1 if (
                last_outcome == "failure"
                or last_outcome_note == "failed_again"
            ) else 0

        normalized["success_after_use"] = int(success_after_use or 0)
        normalized["failure_after_use"] = int(failure_after_use or 0)

        promotion_state = normalized.get("promotion_state", "raw") or "raw"
        if promotion_state == "promoted":
            promotion_state = "trusted"
        normalized["promotion_state"] = promotion_state

        if normalized.get("failure_code") is None and normalized.get("failure_reason") is not None:
            normalized["failure_code"] = normalized["failure_reason"]

        if normalized.get("scope") not in {"universal", "domain", "unclassified"}:
            normalized["scope"] = _classify_lesson_scope(normalized)

        return normalized

    def _build_runtime_context(
        self,
        *,
        file=None,
        change_type=None,
        failure_code=None,
        target_symbol=None,
        context_mode=None,
        trigger_pattern=None,
        fix_strategy=None,
        lesson_level=None,
        source=None,
        lesson_family=None,
        current_context=None,
    ):
        context = dict(current_context) if isinstance(current_context, dict) else {}
        context.setdefault("file", file)
        context.setdefault("change_type", change_type)
        context.setdefault("failure_code", failure_code)
        context.setdefault("target_symbol", target_symbol)
        context.setdefault("context_mode", context_mode)
        context.setdefault("trigger_pattern", trigger_pattern)
        context.setdefault("fix_strategy", fix_strategy)
        context.setdefault("lesson_level", lesson_level)
        context.setdefault("source", source)
        context.setdefault("lesson_family", lesson_family)
        return {
            key: value
            for key, value in context.items()
            if value not in (None, "", [], {})
        }

    def _context_field_matches(self, expected, actual):
        if expected in (None, "", [], {}):
            return True
        if isinstance(expected, list):
            return actual in expected
        return actual == expected

    def _do_not_apply_condition_hit(self, condition, current_context):
        field = condition.get("field")
        op = condition.get("op")
        expected = condition.get("value")
        actual = current_context.get(field)

        if op == "missing_or_different":
            return actual in (None, "") or actual != expected
        if op == "not_equal":
            return actual not in (expected,)
        if op == "equal":
            return actual == expected
        if op == "in":
            return actual in (expected or [])
        return False

    def _generalized_lesson_allowed(self, lesson, current_context):
        if lesson.get("lesson_level") != "generalized":
            return True, []

        reasons = []
        for field, expected in (lesson.get("context_requirements") or {}).items():
            actual = current_context.get(field)
            if not self._context_field_matches(expected, actual):
                return False, [f"context_requirements:{field}"]
            reasons.append(f"context_requirements:{field}")

        for condition in lesson.get("do_not_apply_when") or []:
            if self._do_not_apply_condition_hit(condition, current_context):
                field = condition.get("field") or "unknown"
                return False, [f"do_not_apply_when:{field}"]

        return True, reasons

    def _is_reusable_lesson(self, lesson):
        failure_code = lesson.get("failure_code") or lesson.get("failure_reason")
        if failure_code and failure_code != "unknown_failure":
            return True

        return any(
            lesson.get(field)
            for field in (
                "failure_family",
                "failure_class",
                "target_symbol",
                "change_intent",
                "context_mode",
            )
        )

    def _compute_promotion_state(self, lesson):
        times_used = int(lesson.get("times_used", 0) or 0)
        success_after_use = int(lesson.get("success_after_use", 0) or 0)
        failure_after_use = int(lesson.get("failure_after_use", 0) or 0)
        success_rate = success_after_use / max(times_used, 1)

        if (
            (times_used >= 4 and failure_after_use > success_after_use and success_rate <= 0.34)
            or (times_used >= 6 and failure_after_use >= success_after_use * 2 and failure_after_use > 0)
        ):
            return "retired"

        if not self._is_reusable_lesson(lesson):
            return "raw"

        if (
            times_used >= 4
            and success_after_use >= 3
            and success_rate >= 0.65
        ):
            return "trusted"

        if (
            times_used >= 2
            and success_after_use >= 1
            and success_after_use >= failure_after_use
        ):
            return "candidate"

        return "raw"

    def _score_lesson_match(
        self,
        lesson,
        file=None,
        change_type=None,
        failure_code=None,
        target_symbol=None,
        context_mode=None,
        trigger_pattern=None,
        fix_strategy=None,
        lesson_level=None,
        source=None,
        lesson_family=None,
        current_context=None,
    ):
        score = 0
        reasons = []
        runtime_context = self._build_runtime_context(
            file=file,
            change_type=change_type,
            failure_code=failure_code,
            target_symbol=target_symbol,
            context_mode=context_mode,
            trigger_pattern=trigger_pattern,
            fix_strategy=fix_strategy,
            lesson_level=lesson_level,
            source=source,
            lesson_family=lesson_family,
            current_context=current_context,
        )

        allowed, gating_reasons = self._generalized_lesson_allowed(lesson, runtime_context)
        if not allowed:
            return -1, gating_reasons

        if file is not None:
            if lesson.get("lesson_level") != "generalized" and lesson.get("file") != file:
                return -1, reasons
            if lesson.get("file") == file:
                score += 5
                reasons.append("file")

        if change_type is not None:
            if lesson.get("change_type") != change_type:
                return -1, reasons
            score += 4
            reasons.append("change_type")

        if source is not None:
            if lesson.get("source") != source:
                return -1, reasons
            score += 2
            reasons.append("source")

        if lesson_family is not None:
            if lesson.get("lesson_family") != lesson_family:
                return -1, reasons
            score += 2
            reasons.append("lesson_family")

        if failure_code is not None:
            lesson_failure = lesson.get("failure_code") or lesson.get("failure_reason")
            if lesson_failure != failure_code:
                return -1, reasons
            score += 6
            reasons.append("failure_code")

        if target_symbol is not None:
            if lesson.get("target_symbol") == target_symbol:
                score += 2
                reasons.append("target_symbol")
            elif lesson.get("lesson_level") != "generalized" and lesson.get("target_symbol"):
                return -1, reasons

        if context_mode is not None:
            if lesson.get("context_mode") == context_mode:
                score += 1
                reasons.append("context_mode")
            elif lesson.get("lesson_level") == "generalized":
                pass

        if trigger_pattern is not None and lesson.get("trigger_pattern") == trigger_pattern:
            score += 5
            reasons.append("trigger_pattern")

        if fix_strategy is not None and lesson.get("fix_strategy") == fix_strategy:
            score += 3
            reasons.append("fix_strategy")

        if lesson_level is not None and lesson.get("lesson_level") == lesson_level:
            score += 2
            reasons.append("lesson_level")

        if lesson.get("lesson_level") == "exact":
            score += 3
        elif lesson.get("lesson_level") == "generalized":
            score += 1
            reasons.append("generalized")

        times_used = int(lesson.get("times_used", 0) or 0)
        success_after_use = int(lesson.get("success_after_use", 0) or 0)
        failure_after_use = int(lesson.get("failure_after_use", 0) or 0)

        score += min(times_used, 2)
        score += min(success_after_use * 3, 12)
        score -= min(failure_after_use * 2, 10)

        promotion_state = lesson.get("promotion_state")
        if promotion_state == "trusted":
            score += 5
        elif promotion_state == "candidate":
            score += 2
        elif promotion_state == "retired":
            score -= 8

        return score, reasons

    def find_relevant_lessons(
        self,
        file=None,
        change_type=None,
        failure_code=None,
        target_symbol=None,
        context_mode=None,
        trigger_pattern=None,
        fix_strategy=None,
        lesson_level=None,
        source=None,
        lesson_family=None,
        current_context=None,
        limit=3,
    ):
        ranked_lessons = []

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lesson = json.loads(line)
                except json.JSONDecodeError:
                    continue

                normalized = self._normalize_lesson_record(lesson)
                score, reasons = self._score_lesson_match(
                    normalized,
                    file=file,
                    change_type=change_type,
                    failure_code=failure_code,
                    target_symbol=target_symbol,
                    context_mode=context_mode,
                    trigger_pattern=trigger_pattern,
                    fix_strategy=fix_strategy,
                    lesson_level=lesson_level,
                    source=source,
                    lesson_family=lesson_family,
                    current_context=current_context,
                )
                if score < 0:
                    continue

                normalized["_match_score"] = score
                normalized["_match_reasons"] = reasons
                ranked_lessons.append((score, normalized))

        ranked_lessons.sort(
            key=lambda item: (item[0], item[1].get("timestamp", "")),
            reverse=True,
        )
        return [lesson for _, lesson in ranked_lessons[:limit]]

    def _dedupe_lessons(self, lessons):
        deduped = []
        seen = set()

        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue

            normalized = self._normalize_lesson_record(lesson)
            lesson_id = normalized.get("lesson_id")
            key = lesson_id or (
                normalized.get("timestamp"),
                normalized.get("file"),
                normalized.get("failure_code") or normalized.get("failure_reason"),
                normalized.get("target_symbol"),
                normalized.get("context_mode"),
                normalized.get("lesson_level"),
                normalized.get("trigger_pattern"),
                normalized.get("fix_strategy"),
            )

            if key in seen:
                continue

            seen.add(key)
            deduped.append(normalized)

        return deduped

    def get_retry_lessons(
        self,
        *,
        file=None,
        change_type=None,
        failure_code=None,
        target_symbol=None,
        context_mode=None,
        trigger_pattern=None,
        fix_strategy=None,
        lesson_level=None,
        current_context=None,
        limit=3,
    ):
        ranked = []

        if file is not None and change_type is not None and failure_code is not None:
            ranked.extend(
                self.find_relevant_lessons(
                    file=file,
                    change_type=change_type,
                    failure_code=failure_code,
                    target_symbol=target_symbol,
                    context_mode=context_mode,
                    trigger_pattern=trigger_pattern,
                    fix_strategy=fix_strategy,
                    lesson_level=lesson_level,
                    current_context=current_context,
                    limit=limit,
                )
            )
            ranked.extend(
                self.find_relevant_lessons(
                    file=file,
                    change_type=change_type,
                    failure_code=failure_code,
                    trigger_pattern=trigger_pattern,
                    fix_strategy=fix_strategy,
                    lesson_level=lesson_level,
                    current_context=current_context,
                    limit=limit,
                )
            )

        ranked.extend(
            self.get_recent_lessons(
                file=file,
                change_type=change_type,
                failure_code=failure_code,
                target_symbol=target_symbol,
                context_mode=context_mode,
                trigger_pattern=trigger_pattern,
                fix_strategy=fix_strategy,
                lesson_level=lesson_level,
                limit=limit,
            )
        )
        ranked.extend(
            self.get_recent_lessons(
                file=file,
                change_type=change_type,
                trigger_pattern=trigger_pattern,
                fix_strategy=fix_strategy,
                lesson_level=lesson_level,
                limit=limit,
            )
        )

        return self._dedupe_lessons(ranked)[:limit]

    def get_pilot_guardrails(
        self,
        *,
        file=None,
        change_type=None,
        target_symbol=None,
        lesson_level=None,
        preferred_recovery_action=None,
        current_context=None,
        limit=5,
    ):
        runtime_context = dict(current_context or {})
        if preferred_recovery_action:
            runtime_context["preferred_recovery_action"] = preferred_recovery_action
        ranked = []
        ranked.extend(
            self.find_relevant_lessons(
                file=file,
                change_type=change_type,
                target_symbol=target_symbol,
                lesson_level=lesson_level,
                source="pilot",
                lesson_family="pilot_guardrail",
                current_context=runtime_context,
                limit=limit,
            )
        )
        ranked.extend(
            self.get_recent_lessons(
                file=file,
                change_type=change_type,
                target_symbol=target_symbol,
                lesson_level=lesson_level,
                source="pilot",
                lesson_family="pilot_guardrail",
                limit=limit,
            )
        )
        filtered = []
        for lesson in self._dedupe_lessons(ranked):
            expected_action = lesson.get("preferred_recovery_action")
            if preferred_recovery_action and expected_action and expected_action != preferred_recovery_action:
                continue
            filtered.append(lesson)
        return filtered[:limit]

    def get_universal_lessons(self, min_promotion_state="trusted", limit=20):
        """Return universal-scope lessons at or above the given promotion state.

        These lessons apply to any Python codebase and can be loaded as a
        portable knowledge base when Hive starts on an unfamiliar project.
        """
        rank = {"trusted": 3, "candidate": 2, "raw": 1, "retired": 0}
        min_rank = rank.get(min_promotion_state, 1)
        results = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lesson = self._normalize_lesson_record(json.loads(line))
                    except Exception:
                        continue
                    if lesson.get("scope") != "universal":
                        continue
                    if rank.get(lesson.get("promotion_state", "raw"), 0) < min_rank:
                        continue
                    results.append(lesson)
        except Exception:
            pass
        results.sort(key=lambda l: (
            rank.get(l.get("promotion_state", "raw"), 0),
            l.get("success_after_use", 0),
        ), reverse=True)
        return results[:limit]

    def format_pilot_guardrails_for_prompt(self, lessons):
        if not lessons:
            return "No relevant pilot guardrails."

        lines = []
        for i, lesson in enumerate(lessons, start=1):
            category = lesson.get("guidance_category") or lesson.get("failure_code") or "pilot_guardrail"
            instruction = (
                lesson.get("guardrail_text")
                or lesson.get("retry_instruction")
                or lesson.get("failure_reason")
                or "Stay aligned with the pilot-reviewed task intent."
            )
            lines.append(f"{i}. [{category}] {instruction}")

        return "\n".join(lines)

    def _rewrite_lessons(self, update_fn):
        fd, temp_path = tempfile.mkstemp(
            prefix="hive_lessons_",
            suffix=".jsonl",
            dir=os.path.dirname(os.path.abspath(self.path)) or None,
            text=True,
        )
        updated = False

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                with open(self.path, "r", encoding="utf-8") as source_file:
                    for line in source_file:
                        raw_line = line.strip()
                        if not raw_line:
                            continue
                        try:
                            lesson = json.loads(raw_line)
                        except json.JSONDecodeError:
                            temp_file.write(line)
                            continue

                        lesson = self._normalize_lesson_record(lesson)
                        lesson, changed = update_fn(lesson)
                        if changed:
                            updated = True
                        temp_file.write(json.dumps(lesson) + "\n")

            if updated:
                os.replace(temp_path, self.path)
            else:
                os.remove(temp_path)
            return updated
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def record_lesson_use(self, lesson_id, used_at=None, match_reasons=None, guidance_changed=None, reuse_context=None):
        used_timestamp = used_at or datetime.now().isoformat()

        def update_fn(lesson):
            if lesson.get("lesson_id") != lesson_id:
                return lesson, False

            lesson["times_used"] = int(lesson.get("times_used", 0)) + 1
            lesson["last_used_at"] = used_timestamp
            if match_reasons is not None:
                lesson["last_match_reasons"] = list(match_reasons)
            if guidance_changed is not None:
                lesson["last_guidance_changed"] = bool(guidance_changed)
            if isinstance(reuse_context, dict) and reuse_context:
                lesson["last_reuse_context"] = dict(reuse_context)
            return lesson, True

        return self._rewrite_lessons(update_fn)

    def record_lesson_outcome(
        self,
        lesson_id,
        success,
        outcome_note=None,
        promotion_state=None,
        recorded_at=None,
        reuse_helped=None,
        reuse_context=None,
    ):
        outcome_timestamp = recorded_at or datetime.now().isoformat()

        def update_fn(lesson):
            if lesson.get("lesson_id") != lesson_id:
                return lesson, False

            if success:
                lesson["success_after_use"] = int(lesson.get("success_after_use", 0)) + 1
            else:
                lesson["failure_after_use"] = int(lesson.get("failure_after_use", 0)) + 1
            lesson["last_outcome"] = "success" if success else "failure"
            lesson["last_outcome_at"] = outcome_timestamp
            if outcome_note is not None:
                lesson["last_outcome_note"] = outcome_note
            if reuse_helped is not None:
                lesson["last_reuse_outcome"] = reuse_helped
            if isinstance(reuse_context, dict) and reuse_context:
                lesson["last_reuse_context"] = dict(reuse_context)
            if promotion_state is not None:
                lesson["promotion_state"] = promotion_state
            else:
                lesson["promotion_state"] = self._compute_promotion_state(lesson)
            return lesson, True

        updated = self._rewrite_lessons(update_fn)
        if updated and success:
            self._promote_generalized_lesson_from_evidence(lesson_id)
        return updated

    def _generalized_candidate_from_lesson(self, lesson):
        lesson = self._normalize_lesson_record(lesson)
        if lesson.get("lesson_level") == "generalized":
            return None

        success_after_use = int(lesson.get("success_after_use", 0) or 0)
        failure_after_use = int(lesson.get("failure_after_use", 0) or 0)
        if (
            success_after_use < self.GENERALIZATION_MIN_SUCCESS
            or failure_after_use > success_after_use
        ):
            return None

        trigger_pattern = lesson.get("trigger_pattern")
        fix_strategy = lesson.get("fix_strategy")
        if not trigger_pattern or not fix_strategy:
            return None

        generalized = dict(lesson)
        generalized["lesson_id"] = f"generalized::{trigger_pattern}::{fix_strategy}"
        generalized["lesson_level"] = "generalized"
        generalized["file"] = None
        generalized["target_symbol"] = None
        generalized["context_requirements"] = {
            key: value
            for key, value in (lesson.get("context_requirements") or {}).items()
            if key in {"context_mode", "change_intent", "expected_operation"}
            and value not in (None, "", [], {})
        }
        generalized["do_not_apply_when"] = [
            condition
            for condition in (lesson.get("do_not_apply_when") or [])
            if isinstance(condition, dict)
            and condition.get("field") in {"context_mode", "change_intent", "expected_operation"}
        ]
        generalized["last_condensed_from"] = lesson.get("lesson_id")
        generalized["last_condensed_at"] = datetime.now().isoformat()
        generalized["promotion_state"] = self._compute_promotion_state(generalized)
        return generalized

    def _promote_generalized_lesson_from_evidence(self, lesson_id):
        source_lesson = None
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if not raw_line:
                    continue
                try:
                    lesson = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                normalized = self._normalize_lesson_record(lesson)
                if normalized.get("lesson_id") == lesson_id:
                    source_lesson = normalized
                    break

        candidate = self._generalized_candidate_from_lesson(source_lesson or {})
        if candidate is None:
            return False

        existing_id = candidate["lesson_id"]
        existing = self.find_lesson_by_id(existing_id)
        if existing:
            def update_fn(lesson):
                if lesson.get("lesson_id") != existing_id:
                    return lesson, False
                merged = dict(lesson)
                merged.update({
                    "retry_instruction": candidate.get("retry_instruction") or lesson.get("retry_instruction"),
                    "failure_reason": candidate.get("failure_reason") or lesson.get("failure_reason"),
                    "failure_code": candidate.get("failure_code") or lesson.get("failure_code"),
                    "failure_family": candidate.get("failure_family") or lesson.get("failure_family"),
                    "failure_class": candidate.get("failure_class") or lesson.get("failure_class"),
                    "failure_summary": candidate.get("failure_summary") or lesson.get("failure_summary"),
                    "trigger_pattern": candidate.get("trigger_pattern"),
                    "fix_strategy": candidate.get("fix_strategy"),
                    "context_requirements": candidate.get("context_requirements", {}),
                    "do_not_apply_when": candidate.get("do_not_apply_when", []),
                    "lesson_level": "generalized",
                    "times_used": max(int(lesson.get("times_used", 0) or 0), int(candidate.get("times_used", 0) or 0)),
                    "success_after_use": max(int(lesson.get("success_after_use", 0) or 0), int(candidate.get("success_after_use", 0) or 0)),
                    "failure_after_use": min(int(lesson.get("failure_after_use", 0) or 0), int(candidate.get("failure_after_use", 0) or 0)),
                    "promotion_state": candidate.get("promotion_state") or lesson.get("promotion_state"),
                    "last_condensed_from": candidate.get("last_condensed_from"),
                    "last_condensed_at": candidate.get("last_condensed_at"),
                })
                return merged, True

            return self._rewrite_lessons(update_fn)

        self.add_lesson(**candidate)
        return True

    def find_lesson_by_id(self, lesson_id):
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if not raw_line:
                    continue
                try:
                    lesson = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                normalized = self._normalize_lesson_record(lesson)
                if normalized.get("lesson_id") == lesson_id:
                    return normalized
        return None

    def get_recent_lessons(self, file=None, change_type=None, limit=3, failure_code=None, target_symbol=None, context_mode=None, trigger_pattern=None, fix_strategy=None, lesson_level=None, source=None, lesson_family=None):
        lessons = []

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lesson = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if file is not None and lesson.get("file") != file:
                    continue
                if change_type is not None and lesson.get("change_type") != change_type:
                    continue
                if failure_code is not None and (
                    lesson.get("failure_code") != failure_code
                    and lesson.get("failure_reason") != failure_code
                ):
                    continue
                if target_symbol is not None and lesson.get("target_symbol") != target_symbol:
                    continue
                if context_mode is not None and lesson.get("context_mode") != context_mode:
                    continue
                if trigger_pattern is not None and lesson.get("trigger_pattern") != trigger_pattern:
                    continue
                if fix_strategy is not None and lesson.get("fix_strategy") != fix_strategy:
                    continue
                if lesson_level is not None and lesson.get("lesson_level", "exact") != lesson_level:
                    continue
                if source is not None and lesson.get("source") != source:
                    continue
                if lesson_family is not None and lesson.get("lesson_family") != lesson_family:
                    continue

                lessons.append(self._normalize_lesson_record(lesson))

        return lessons[-limit:]

    def format_lessons_for_prompt(self, lessons):
        if not lessons:
            return "No relevant recent failure lessons."

        lines = []
        for i, lesson in enumerate(lessons, start=1):
            instruction = lesson.get("retry_instruction", "Avoid repeating this failure.")
            reason = lesson.get("failure_code") or lesson.get("failure_reason", "unknown_failure")
            lesson_level = lesson.get("lesson_level", "exact")
            fix_strategy = lesson.get("fix_strategy")
            suffix = f" strategy={fix_strategy}" if fix_strategy else ""
            lines.append(f"{i}. [{reason} | {lesson_level}]{suffix} {instruction}")

        return "\n".join(lines)
