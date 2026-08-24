from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "hive_reference" / "spec"


def _load(name: str):
    return json.loads((SPEC / name).read_text(encoding="utf-8"))


def test_architecture_graph_has_valid_nodes_edges_statuses_and_feedback_loops() -> None:
    graph = _load("architecture.json")
    node_ids = [item["id"] for item in graph["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    assert {
        "observation",
        "event_ledger",
        "authority",
        "state",
        "compression",
        "task",
        "decompression",
        "solver",
        "evaluation",
        "repair",
        "learning",
        "proposal_policy",
    } <= set(node_ids)
    statuses = set(graph["status_values"])
    assert all(item["status"] in statuses for item in graph["nodes"])
    assert all(
        edge["from"] in node_ids
        and edge["to"] in node_ids
        and edge["status"] in statuses
        for edge in graph["edges"]
    )
    assert all(set(loop) <= set(node_ids) and loop[0] == loop[-1] for loop in graph["feedback_loops"])


def test_research_dag_is_acyclic_and_every_node_has_a_falsification_path() -> None:
    graph = _load("research_dag.json")
    nodes = {item["id"]: item for item in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    assert all(item["cheapest_falsification"] for item in nodes.values())
    assert all(item["success_criteria"] for item in nodes.values())
    assert all(item["expected_cost"] for item in nodes.values())
    assert all(item["uncertainty_reduction"] for item in nodes.values())

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        assert node_id in nodes
        if node_id in visited:
            return
        assert node_id not in visiting, "research dependency cycle"
        visiting.add(node_id)
        for prerequisite in nodes[node_id]["prerequisites"]:
            visit(prerequisite)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)
    assert visited == set(nodes)
