from __future__ import annotations

import json

import pytest

from kingdom import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionAssessment,
    ComprehensionProbe,
    Evidence,
    HashChainLedger,
    KingdomConfig,
    KingdomEngine,
    Seed,
    StructureMap,
)


class FakeProvider:
    def __init__(self):
        self.explored = []

    def decompose(self, seed, config):
        return [
            BranchSpec("a", "skeptic", "What breaks?", "assume the core claim is false"),
            BranchSpec("dup", "skeptic", "What breaks?", "assume the core claim is false"),
            BranchSpec("b", "implementation", "What is buildable now?", "assume no new hardware"),
            BranchSpec("c", "evidence", "What would falsify it?", "require measurement"),
        ]

    def explore(self, seed, branch):
        self.explored.append(branch.branch_id)
        child = ()
        if branch.branch_id == "a":
            child = (
                BranchSpec("a1", "alternatives", "What if compression is lossy?", "allow bounded loss"),
            )
        return BranchResult(
            branch_id=branch.branch_id,
            findings=(f"finding:{branch.branch_id}",),
            evidence=(Evidence("testable", "observe", 0.8, "fixture"),),
            assumptions=(branch.assumption_shift,),
            uncertainties=("unknown bandwidth",),
            next_branches=child,
        )

    def integrate(self, seed, branches, results):
        return StructureMap(
            invariants=("branching can preserve distinct hypotheses",),
            disagreements=("loss tolerance remains unresolved",),
            hinge_assumptions=("human comprehension can be measured",),
            causal_links=("better encoding -> better transfer",),
            anomalies=(),
            unknowns=("scaling law",),
            provenance={"human comprehension can be measured": ("a", "c")},
        )

    def encode(self, seed, structure, config):
        return CognitivePacket(
            title="Crown",
            orientation="The bottleneck is reintegration.",
            load_bearing_insights=structure.invariants + structure.hinge_assumptions,
            uncertainty=structure.unknowns,
            next_moves=("run a human transfer test",),
            inspectable_refs=structure.provenance,
        )

    def make_probes(self, seed, structure, packet):
        return [ComprehensionProbe("p1", "What is the bottleneck?", "reintegration")]

    def assess(self, seed, structure, probes, answers):
        answer = answers.get("p1", "").lower()
        ok = "reintegration" in answer
        return ComprehensionAssessment(
            score=1.0 if ok else 0.0,
            understood=("reintegration",) if ok else (),
            missed=() if ok else ("reintegration",),
            reexpand=() if ok else ("reintegration",),
        )


def test_engine_deduplicates_branches_obeys_budget_and_recurses(tmp_path):
    provider = FakeProvider()
    engine = KingdomEngine(
        provider,
        config=KingdomConfig(max_branches=4, max_depth=1, workers=2),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )

    run = engine.run(Seed("Can cognition be externally extensible?"))

    assert [branch.branch_id for branch in run.branches] == ["a", "b", "c", "a1"]
    assert set(provider.explored) == {"a", "b", "c", "a1"}
    assert run.packet.title == "Crown"
    assert run.structure.provenance["human comprehension can be measured"] == ("a", "c")
    assert (tmp_path / "runs" / f"{run.run_id}.json").exists()


def test_comprehension_gate_records_reexpansion_target(tmp_path):
    engine = KingdomEngine(
        FakeProvider(),
        config=KingdomConfig(max_branches=3, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    run = engine.run(Seed("seed"))

    assessment = engine.assess(run, {"p1": "I think the bottleneck is reintegration."})

    assert assessment.score == 1.0
    assert assessment.reexpand == ()
    assert engine.ledger.verify() is True


def test_hash_chain_ledger_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append("one", {"value": 1})
    ledger.append("two", {"value": 2})
    assert ledger.verify() is True

    records = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(records[0])
    first["payload"]["value"] = 999
    records[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")

    assert ledger.verify() is False


def test_amplification_metric_rewards_transfer_without_free_attention():
    from kingdom.benchmark import TransferTrial, best_condition, compare_transfer

    baseline = TransferTrial("flat-summary", correct=6, total=10, attention_units=10)
    assisted = TransferTrial("kingdom-codec", correct=9, total=10, attention_units=10)
    bloated = TransferTrial("raw-branches", correct=10, total=10, attention_units=30)

    report = compare_transfer(baseline, assisted)

    assert report.accuracy_gain == pytest.approx(0.3)
    assert report.gain_per_assisted_attention == pytest.approx(0.03)
    assert best_condition([baseline, assisted, bloated]).condition == "kingdom-codec"
