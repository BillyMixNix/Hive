"""GROW-0 mutable workshop component.

G0 intentionally preserves all evidence values but does not preserve their
provenance labels in the model-facing packet. The experiment may evolve this
constructor; the evaluator and cases remain outside the candidate workspace.
"""

from __future__ import annotations


def build_repair_packet(case: dict, *, presentation_order: str = "stored_first") -> str:
    stored = case["stored_value"]
    current = case["current_value"]
    ordered = [stored, current] if presentation_order == "stored_first" else [current, stored]
    return "\n".join(
        [
            "REPAIR DECISION PACKET",
            f"Goal: {case['goal']}",
            f"Candidate value A: {ordered[0]!r}",
            f"Candidate value B: {ordered[1]!r}",
            "Choose the value that belongs to the active/current operation.",
            "Return JSON only with keys selected_source and selected_value.",
        ]
    )
