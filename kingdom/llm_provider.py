from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .core import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionAssessment,
    ComprehensionProbe,
    Evidence,
    KingdomConfig,
    Seed,
    StructureMap,
)


DEFAULT_LENSES = (
    "first_principles",
    "skeptic",
    "implementation",
    "evidence",
    "hidden_assumptions",
    "alternatives",
    "second_order_effects",
    "adversarial",
    "wildcard",
)


def _json_from_text(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [index for index in (cleaned.find("{"), cleaned.find("[")) if index >= 0]
        if not starts:
            raise
        start = min(starts)
        closing = "}" if cleaned[start] == "{" else "]"
        end = cleaned.rfind(closing)
        if end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _refs(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _tuple_strings(items)
        for key, items in value.items()
        if _tuple_strings(items)
    }


class HiveLLMProvider:
    """Live Kingdom-0 provider using Hive's existing role-aware model router."""

    def __init__(self, ask: Callable[..., str] | None = None):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask

    def _call_json(self, prompt: str, *, role: str) -> Any:
        suffix = (
            "\n\nReturn JSON only. Do not wrap it in markdown. "
            "Do not invent sources or claim tests you did not actually perform."
        )
        text = self.ask(prompt + suffix, role=role)
        return _json_from_text(text)

    def decompose(self, seed: Seed, config: KingdomConfig) -> Sequence[BranchSpec]:
        payload = self._call_json(
            f"KINGDOM-0 / DECOMPRESSION\n\n"
            f"Seed: {seed.text}\nContext: {seed.context}\nGoal: {seed.goal}\n\n"
            "Expand this compressed idea into genuinely divergent investigation branches. "
            "Prefer incompatible assumptions and different failure surfaces over paraphrases. "
            f"Use lenses drawn from {list(DEFAULT_LENSES)!r} when useful. "
            f"Return at most {config.max_branches} branches as a JSON object with key 'branches'. "
            "Each branch must contain: id, lens, question, assumption_shift.",
            role="planner",
        )
        records = payload.get("branches", []) if isinstance(payload, dict) else []
        branches: list[BranchSpec] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            branches.append(
                BranchSpec(
                    branch_id=str(record.get("id") or f"b{index + 1:03d}"),
                    lens=str(record.get("lens") or "general"),
                    question=str(record.get("question") or ""),
                    assumption_shift=str(record.get("assumption_shift") or ""),
                )
            )
        return branches

    def explore(self, seed: Seed, branch: BranchSpec) -> BranchResult:
        payload = self._call_json(
            f"KINGDOM-0 / BRANCH EXPLORATION\n\n"
            f"Seed: {seed.text}\nContext: {seed.context}\n"
            f"Branch id: {branch.branch_id}\nLens: {branch.lens}\n"
            f"Question: {branch.question}\nAssumption shift: {branch.assumption_shift}\n\n"
            "Explore this branch independently. Separate claims from evidence. "
            "When no external tool or executable test is available, mark evidence as uncertain rather than fabricated. "
            "Return JSON with findings, evidence, assumptions, uncertainties, next_branches. "
            "evidence items: claim, stance (support|contradict|observe|uncertain), confidence 0..1, source, detail. "
            "next_branches items: id, lens, question, assumption_shift.",
            role=self._role_for_lens(branch.lens),
        )
        evidence: list[Evidence] = []
        for item in payload.get("evidence", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = min(1.0, max(0.0, confidence))
            stance = str(item.get("stance") or "uncertain").lower()
            if stance not in {"support", "contradict", "observe", "uncertain"}:
                stance = "uncertain"
            evidence.append(
                Evidence(
                    claim=str(item.get("claim") or ""),
                    stance=stance,
                    confidence=confidence,
                    source=str(item.get("source") or ""),
                    detail=str(item.get("detail") or ""),
                )
            )

        children: list[BranchSpec] = []
        for index, item in enumerate(payload.get("next_branches", []) if isinstance(payload, dict) else []):
            if not isinstance(item, dict):
                continue
            children.append(
                BranchSpec(
                    branch_id=str(item.get("id") or f"{branch.branch_id}-n{index + 1}"),
                    lens=str(item.get("lens") or "general"),
                    question=str(item.get("question") or ""),
                    assumption_shift=str(item.get("assumption_shift") or ""),
                    parent_id=branch.branch_id,
                    depth=branch.depth + 1,
                )
            )

        return BranchResult(
            branch_id=branch.branch_id,
            findings=_tuple_strings(payload.get("findings") if isinstance(payload, dict) else None),
            evidence=tuple(evidence),
            assumptions=_tuple_strings(payload.get("assumptions") if isinstance(payload, dict) else None),
            uncertainties=_tuple_strings(payload.get("uncertainties") if isinstance(payload, dict) else None),
            next_branches=tuple(children),
        )

    def integrate(
        self,
        seed: Seed,
        branches: Sequence[BranchSpec],
        results: Sequence[BranchResult],
    ) -> StructureMap:
        branch_payload = []
        for branch in branches:
            result = next((item for item in results if item.branch_id == branch.branch_id), None)
            branch_payload.append(
                {
                    "id": branch.branch_id,
                    "lens": branch.lens,
                    "question": branch.question,
                    "assumption_shift": branch.assumption_shift,
                    "result": None if result is None else {
                        "findings": list(result.findings),
                        "evidence": [vars(item) for item in result.evidence],
                        "assumptions": list(result.assumptions),
                        "uncertainties": list(result.uncertainties),
                    },
                }
            )
        payload = self._call_json(
            "KINGDOM-0 / STRUCTURAL REINTEGRATION\n\n"
            f"Seed: {seed.text}\n\n"
            f"Branches: {json.dumps(branch_payload, default=str)}\n\n"
            "Do NOT summarize branch-by-branch and do NOT majority vote. Extract the structure that survives comparison. "
            "Return JSON keys: invariants, disagreements, hinge_assumptions, causal_links, anomalies, unknowns, provenance. "
            "provenance maps each structural statement to branch ids that support or expose it. Preserve disagreement and uncertainty.",
            role="reflector",
        )
        return StructureMap(
            invariants=_tuple_strings(payload.get("invariants")),
            disagreements=_tuple_strings(payload.get("disagreements")),
            hinge_assumptions=_tuple_strings(payload.get("hinge_assumptions")),
            causal_links=_tuple_strings(payload.get("causal_links")),
            anomalies=_tuple_strings(payload.get("anomalies")),
            unknowns=_tuple_strings(payload.get("unknowns")),
            provenance=_refs(payload.get("provenance")),
        )

    def encode(
        self,
        seed: Seed,
        structure: StructureMap,
        config: KingdomConfig,
    ) -> CognitivePacket:
        payload = self._call_json(
            "KINGDOM-0 / COGNITIVE CODEC\n\n"
            f"Seed: {seed.text}\nStructure: {json.dumps(vars(structure), default=list)}\n\n"
            f"Encode the important structure for a human operator. Use at most {config.codec_items} load-bearing insights. "
            "Optimize for reconstructable understanding, not brevity alone. Keep uncertainty visible and preserve inspectable provenance refs. "
            "Return JSON: title, orientation, load_bearing_insights, uncertainty, next_moves, inspectable_refs.",
            role="strategic",
        )
        return CognitivePacket(
            title=str(payload.get("title") or "Kingdom-0 cognitive packet"),
            orientation=str(payload.get("orientation") or ""),
            load_bearing_insights=_tuple_strings(payload.get("load_bearing_insights")),
            uncertainty=_tuple_strings(payload.get("uncertainty")),
            next_moves=_tuple_strings(payload.get("next_moves")),
            inspectable_refs=_refs(payload.get("inspectable_refs")),
        )

    def make_probes(
        self,
        seed: Seed,
        structure: StructureMap,
        packet: CognitivePacket,
    ) -> Sequence[ComprehensionProbe]:
        payload = self._call_json(
            "KINGDOM-0 / COMPREHENSION PROBE\n\n"
            f"Seed: {seed.text}\nStructure: {json.dumps(vars(structure), default=list)}\n"
            f"Packet: {json.dumps(vars(packet), default=list)}\n\n"
            "Create 3-5 transfer questions that test whether the operator reconstructed the important structure. "
            "Do not ask trivia or quote-recall questions. Each should require prediction, counterfactual reasoning, hinge-assumption identification, or transfer. "
            "Return JSON object key 'probes'; each probe has id, question, target.",
            role="reflector",
        )
        probes = []
        for index, item in enumerate(payload.get("probes", []) if isinstance(payload, dict) else []):
            if not isinstance(item, dict):
                continue
            probes.append(
                ComprehensionProbe(
                    probe_id=str(item.get("id") or f"p{index + 1}"),
                    question=str(item.get("question") or ""),
                    target=str(item.get("target") or ""),
                )
            )
        return probes

    def assess(
        self,
        seed: Seed,
        structure: StructureMap,
        probes: Sequence[ComprehensionProbe],
        answers: Mapping[str, str],
    ) -> ComprehensionAssessment:
        payload = self._call_json(
            "KINGDOM-0 / COMPREHENSION GATE\n\n"
            f"Seed: {seed.text}\nStructure: {json.dumps(vars(structure), default=list)}\n"
            f"Probes: {json.dumps([vars(item) for item in probes])}\n"
            f"Answers: {json.dumps(dict(answers))}\n\n"
            "Grade structural comprehension, not wording similarity. Identify concepts that need re-expansion. "
            "Return JSON: score (0..1), understood, missed, reexpand, feedback.",
            role="reflector",
        )
        try:
            score = float(payload.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return ComprehensionAssessment(
            score=min(1.0, max(0.0, score)),
            understood=_tuple_strings(payload.get("understood")),
            missed=_tuple_strings(payload.get("missed")),
            reexpand=_tuple_strings(payload.get("reexpand")),
            feedback=str(payload.get("feedback") or ""),
        )

    @staticmethod
    def _role_for_lens(lens: str) -> str:
        normalized = lens.lower()
        if "implement" in normalized:
            return "coder"
        if "evidence" in normalized or "first_principles" in normalized:
            return "math"
        if "skeptic" in normalized or "adversarial" in normalized or "assumption" in normalized:
            return "reflector"
        if "second" in normalized or "alternative" in normalized or "wild" in normalized:
            return "strategic"
        return "default"
