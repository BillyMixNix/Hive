"""GROW-0 mutable workshop component.

G0 intentionally preserves all evidence values but does not preserve their
provenance labels in the model-facing packet. The experiment may evolve this
constructor; the evaluator and cases remain outside the candidate workspace.
"""


def build_repair_packet(case, *, presentation_order="stored_first"):
    stored = case["stored_value"]
    current = case["current_value"]
    if presentation_order == "stored_first":
        first = stored
        second = current
    else:
        first = current
        second = stored
    return (
        "REPAIR DECISION PACKET\n"
        + f"Goal: {case['goal']}\n"
        + f"Candidate value A: {first!r}\n"
        + f"Candidate value B: {second!r}\n"
        + "Choose the value that belongs to the active/current operation.\n"
        + "Return JSON only with keys selected_source and selected_value."
    )
