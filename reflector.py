from hive_llm import ask_model
import json

from reflector_prompt import REFLECTOR_PROMPT_TEMPLATE


def _load_math_lessons(max_lessons: int = 6) -> str:
    """
    Load recent math failure lessons from math_lessons.jsonl.
    Returns a formatted string for injection into the reflector prompt.
    Returns empty string if no lessons exist.
    """
    try:
        with open("math_lessons.jsonl") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return ""
        recent = lines[-max_lessons:]
        parts = ["Prior math failure lessons (do not repeat these strategies):"]
        for line in recent:
            try:
                lesson = json.loads(line)
                parts.append(
                    f"  - Strategy: {lesson.get('strategy','?')} | "
                    f"Failed at: {lesson.get('failure_point','?')} | "
                    f"Insight: {lesson.get('insight','?')}"
                )
            except json.JSONDecodeError:
                continue
        return "\n".join(parts)
    except FileNotFoundError:
        return ""


def _load_code_lessons(max_lessons: int = 6) -> str:
    """
    Load recent code strategy failure lessons from code_lessons.jsonl.
    Returns a formatted string for injection into the reflector prompt.
    Returns empty string if no lessons exist.
    """
    try:
        with open("code_lessons.jsonl") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return ""
        recent = lines[-max_lessons:]
        parts = ["Prior code strategy failures (do not repeat these):"]
        for line in recent:
            try:
                lesson = json.loads(line)
                parts.append(
                    f"  - [{lesson.get('agent','?')}] "
                    f"Strategy: {lesson.get('strategy','?')} | "
                    f"Failed: {lesson.get('failure_point','?')} | "
                    f"Insight: {lesson.get('insight','?')}"
                )
            except json.JSONDecodeError:
                continue
        return "\n".join(parts)
    except FileNotFoundError:
        return ""


class Reflector:
    def _build_prompt(self, output_text, pilot_guardrails="No relevant pilot guardrails.", math_lessons=""):
        prompt = REFLECTOR_PROMPT_TEMPLATE.format(
            output=output_text,
            pilot_guardrails=pilot_guardrails,
        )
        if math_lessons:
            prompt = prompt + f"\n\n{math_lessons}"
        return prompt

    def _stringify_output(self, output):
        if isinstance(output, str):
            return output

        try:
            return json.dumps(output, ensure_ascii=False)
        except TypeError:
            return str(output)

    def _extract_json_object(self, raw_response):
        start = raw_response.find("{")
        end = raw_response.rfind("}")

        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model response.")

        return raw_response[start:end + 1]

    def _validate_reflection(self, reflection):
        required_fields = ["reflection", "confidence", "next_step", "verdict"]

        for field in required_fields:
            if field not in reflection:
                raise ValueError(f"Missing field in model response: {field}")

        confidence = reflection["confidence"]
        if not isinstance(confidence, (int, float)):
            raise ValueError("confidence must be numeric.")
        reflection["confidence"] = max(0.0, min(1.0, float(confidence)))

        verdict = reflection["verdict"]
        if verdict not in {"accept", "revise", "reject"}:
            raise ValueError("verdict must be one of: accept, revise, reject")

        return reflection

    def evaluate(self, output, task=None, plan=None, pilot_guardrails=None):
        """
        Evaluate Hive output safely and consistently.

        Handles patches, plans, errors, and unexpected types without crashing.
        Injects prior math failure lessons when evaluating mathematical output.
        """
        try:
            payload = output
            if task is not None or plan is not None or pilot_guardrails is not None:
                payload = {
                    "output": output,
                    "task": task,
                    "plan": plan,
                    "pilot_guardrails": pilot_guardrails or [],
                }

            output_text = self._stringify_output(payload)
            guardrail_text = "No relevant pilot guardrails."
            if isinstance(pilot_guardrails, list) and pilot_guardrails:
                lines = []
                for i, lesson in enumerate(pilot_guardrails, start=1):
                    category = lesson.get("guidance_category") or lesson.get("failure_code") or "pilot_guardrail"
                    text = lesson.get("guardrail_text") or lesson.get("retry_instruction") or lesson.get("failure_reason") or ""
                    lines.append(f"{i}. [{category}] {text}".strip())
                guardrail_text = "\n".join(lines) if lines else guardrail_text

            if "placeholder" in output_text.lower():
                return {
                    "reflection": "Placeholder patch detected",
                    "confidence": 0.0,
                    "next_step": "Remove placeholder logic and try again.",
                    "verdict": "reject",
                }

            # Inject math lessons when output is mathematical in nature
            math_lessons = ""
            math_signals = ("conjecture", "stopping time", "collatz", "trajectory",
                            "modular", "symbolic", "syracuse", "E[T", "gap")
            if any(sig in output_text.lower() for sig in math_signals):
                math_lessons = _load_math_lessons()

            # Inject code lessons when output is about code hypotheses or strategies
            code_lessons = ""
            code_signals = ("hypothesis", "complexity", "O(n", "benchmark", "profil",
                            "boundary", "invariant", "regression", "adversarial test",
                            "architecture trace", "nested loop", "call graph")
            if any(sig in output_text.lower() for sig in code_signals):
                code_lessons = _load_code_lessons()

            combined_lessons = "\n\n".join(
                x for x in [math_lessons, code_lessons] if x
            )

            prompt = self._build_prompt(
                output_text,
                pilot_guardrails=guardrail_text,
                math_lessons=combined_lessons,
            )
            raw_response = ask_model(prompt).strip()
            json_text = self._extract_json_object(raw_response)
            reflection = json.loads(json_text)

            if not isinstance(reflection, dict):
                raise ValueError("Reflection response must be a JSON object.")

            return self._validate_reflection(reflection)

        except Exception as e:
            return {
                "reflection": f"Reflection unavailable: {e}",
                "confidence": 0.4,
                "next_step": "Pilot review recommended. Check for scope drift, duplicated logic, or malformed model output.",
                "verdict": "revise",
            }

    def format_summary(self, reflection):
        return (
            f"Reflection: {reflection['reflection']}\n"
            f"Confidence: {reflection['confidence']:.2f}\n"
            f"Next Step: {reflection['next_step']}\n"
            f"Verdict: {reflection['verdict']}"
        )
