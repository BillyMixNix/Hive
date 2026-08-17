from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable


class EvaluationError(RuntimeError):
    pass


def _load_builder(module_path: str | Path) -> Callable[..., str]:
    path = Path(module_path)
    spec = importlib.util.spec_from_file_location("_grow0_candidate_repair_packet", path)
    if spec is None or spec.loader is None:
        raise EvaluationError(f"cannot load candidate workshop: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = getattr(module, "build_repair_packet", None)
    if not callable(builder):
        raise EvaluationError("candidate workshop must define build_repair_packet(case, ...)")
    return builder


def parse_model_answer(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1])
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip("\n")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"model output was not strict JSON: {text[:240]}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError("model answer must be a JSON object")
    return payload


def evaluate_case(
    *,
    workshop_module: str | Path,
    case: dict[str, Any],
    invoke_model: Callable[[str], str],
    presentation_order: str = "stored_first",
) -> dict[str, Any]:
    builder = _load_builder(workshop_module)
    prompt = builder(case, presentation_order=presentation_order)
    raw = invoke_model(prompt)
    try:
        answer = parse_model_answer(raw)
        selected_source = str(answer.get("selected_source") or "").strip().lower()
        selected_value = answer.get("selected_value")
        passed = selected_source == case["expected_source"] and selected_value == case["expected_value"]
        error = None
    except EvaluationError as exc:
        answer = None
        passed = False
        error = str(exc)
    return {
        "case_id": case["case_id"],
        "passed": passed,
        "answer": answer,
        "error": error,
        "prompt_sha256": __import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest(),
        "raw_output_sha256": __import__("hashlib").sha256((raw or "").encode("utf-8")).hexdigest(),
    }


def counterbalanced_probe(
    *,
    workshop_module: str | Path,
    case: dict[str, Any],
    invoke_model: Callable[[str], str],
) -> dict[str, Any]:
    first = evaluate_case(
        workshop_module=workshop_module,
        case=case,
        invoke_model=invoke_model,
        presentation_order="stored_first",
    )
    second = evaluate_case(
        workshop_module=workshop_module,
        case=case,
        invoke_model=invoke_model,
        presentation_order="current_first",
    )
    # A provenance-loss diagnosis is supported when order changes correctness or
    # the selected value while the underlying semantic case is unchanged.
    first_value = (first.get("answer") or {}).get("selected_value")
    second_value = (second.get("answer") or {}).get("selected_value")
    supported = first["passed"] != second["passed"] or first_value != second_value
    return {
        "status": "DIAGNOSIS_SUPPORTED" if supported else "DIAGNOSIS_INCONCLUSIVE",
        "stored_first": first,
        "current_first": second,
    }
