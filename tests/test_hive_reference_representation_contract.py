from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from hive_reference.demo import build_demo_ledger, build_demo_tasks
from hive_reference.model import FactKey, canonical_json
from hive_reference.representation import (
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationInvariantError,
    RepresentationRootCommitment,
    SelectiveDecompressor,
    SolveStatus,
    make_causal_rule_component,
)


def _representation():
    ledger, refs = build_demo_ledger()
    rule = make_causal_rule_component(
        component_id="component:rule:containment_owner_v1",
        keys=(FactKey("gem", "inside"), FactKey("chest", "owner")),
        rule_id="containment_owner_v1",
        rule="contained item inherits effective owner from container",
        source_event_ids=("e_inside", "e_owner_ari"),
        evidence=(refs["o_inside"], refs["o_owner"]),
        available_from_record=11,
    )
    return ledger, ReferenceCompressor().compress(
        ledger,
        representation_id="representation-contract-v1",
        extra_components=(rule,),
    )


def test_selective_decompression_obeys_knowledge_cutoff_and_counts_full_components() -> None:
    _, representation = _representation()
    query = build_demo_tasks(99)[0].query
    early_query = replace(query, known_at=10)
    root = RepresentationRootCommitment.from_trusted_representation(representation)
    decompressor = SelectiveDecompressor((root,))

    early = decompressor.decompress(representation, early_query)
    assert all(item.available_from_record <= 10 for item in early.selected_components)
    assert "component:event:e_inside" not in early.selected_component_ids
    assert "component:rule:containment_owner_v1" not in early.selected_component_ids
    assert DeterministicReferenceSolver().solve(early, early_query).status is SolveStatus.INCOMPLETE

    complete = decompressor.decompress(representation, replace(query, known_at=11))
    expected_bytes = len(
        canonical_json(
            {
                "components": [asdict(item) for item in complete.selected_components],
                "source_component_manifest": [
                    item.to_mapping()
                    for item in representation.source_component_manifest
                ],
                "source_component_manifest_hash": (
                    representation.source_component_manifest_hash
                ),
            }
        ).encode("utf-8")
    )
    assert complete.completeness is SolveStatus.COMPLETE
    assert complete.supporting_bytes_read == expected_bytes


def test_decompressor_configuration_is_bound_to_external_trusted_root() -> None:
    _, representation = _representation()
    root = RepresentationRootCommitment.from_trusted_representation(representation)
    changed_root = replace(root, schema_id=f"{root.schema_id}-other")

    assert SelectiveDecompressor((root,)).configuration_hash != (
        SelectiveDecompressor((changed_root,)).configuration_hash
    )
    with pytest.raises(
        RepresentationInvariantError,
        match="at least one external trusted root",
    ):
        SelectiveDecompressor(())


def test_tampered_causal_rule_cannot_escape_its_trusted_manifest() -> None:
    _, representation = _representation()
    rule = next(
        item
        for item in representation.components
        if item.component_id == "component:rule:containment_owner_v1"
    )
    payload = dict(rule.payload())
    payload["operator"] = "nonsense_operator"
    tampered_rule = replace(rule, payload_json=canonical_json(payload))
    with pytest.raises(RepresentationInvariantError, match="trusted manifest entries"):
        replace(
            representation,
            representation_id="representation-contract-bad-rule",
            components=tuple(
                tampered_rule if item.component_id == rule.component_id else item
                for item in representation.components
            ),
        )
