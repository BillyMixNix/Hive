from hive_llm import ask_model
import json

from reflector_prompt import REFLECTOR_PROMPT_TEMPLATE


class Reflector:
    def _build_prompt(self, output_text, pilot_guardrails="No relevant pilot guardrails."):
        return REFLECTOR_PROMPT_TEMPLATE.format(
            output=output_text,
            pilot_guardrails=pilot_guardrails,
        )

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

            prompt = self._build_prompt(output_text, pilot_guardrails=guardrail_text)
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
