from __future__ import annotations

from kingdom.arena import ArenaRegistry, RepositoryReadTool, ToolRequest
from kingdom.construction import MindConstructor, TargetDecomposition, TargetDraft
from kingdom.core import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionAssessment,
    ComprehensionProbe,
    Evidence,
    KingdomConfig,
    KingdomEngine,
    Seed,
    StructureMap,
)
from kingdom.navigation import CognitiveNavigator
from kingdom.worlds import WorldBranchingProvider


class TinyProvider:
    def decompose(self, seed, config):
        return [BranchSpec("base", "implementation", "What can be executed?", "current tools only")]

    def explore(self, seed, branch):
        return BranchResult(
            branch_id=branch.branch_id,
            findings=(f"finding from {branch.branch_id}",),
            evidence=(Evidence("initial model claim", "uncertain", 0.4, "model"),),
            assumptions=(branch.assumption_shift,),
            uncertainties=("needs external verification",),
        )

    def integrate(self, seed, branches, results):
        provenance = {}
        if results:
            provenance["reality contact changes the evidence state"] = (results[0].branch_id,)
        verified_count = sum(
            1
            for result in results
            for evidence in result.evidence
            if evidence.stance == "observe" and evidence.source.startswith("repo:")
        )
        return StructureMap(
            invariants=("reality contact changes the evidence state",),
            disagreements=(),
            hinge_assumptions=(f"verified observations={verified_count}",),
            causal_links=("tool result -> evidence -> reintegration",),
            anomalies=(),
            unknowns=(),
            provenance=provenance,
        )

    def encode(self, seed, structure, config):
        return CognitivePacket(
            title="constructor",
            orientation="verified structure",
            load_bearing_insights=structure.invariants + structure.hinge_assumptions,
            uncertainty=structure.unknowns,
            next_moves=("decompose blockers",),
            inspectable_refs=structure.provenance,
        )

    def make_probes(self, seed, structure, packet):
        return [ComprehensionProbe("p", "What changed?", "evidence")]

    def assess(self, seed, structure, probes, answers):
        return ComprehensionAssessment(1.0, ("evidence",), (), ())


class Planner:
    def plan(self, seed, branch, result, available_tools):
        if branch.branch_id == "base":
            return (
                ToolRequest(
                    tool="repo_read",
                    operation="read",
                    payload={"path": "fact.txt"},
                    purpose="verify repository reality",
                    branch_id=branch.branch_id,
                ),
                ToolRequest(
                    tool="missing_sensor",
                    operation="measure",
                    payload={},
                    purpose="measure an unavailable quantity",
                    branch_id=branch.branch_id,
                ),
            )
        return ()


class Decomposer:
    def decompose(self, target, available_capabilities):
        if target.capability == "missing_sensor":
            return TargetDecomposition(
                "all",
                (
                    TargetDraft(
                        "Define a deterministic proxy measurement using an available repository fixture",
                        kind="experiment",
                        status="executable",
                        reason="nearest testable predecessor",
                    ),
                ),
            )
        return TargetDecomposition("all", ())


class FrontierPlanner:
    def plan(self, seed, target, available_tools):
        return (
            ToolRequest(
                tool="repo_read",
                operation="read",
                payload={"path": "fact.txt"},
                purpose=target.statement,
                branch_id=target.origin_branch_id,
            ),
        )


def test_world_wrapper_forces_incompatible_premises_before_generated_branches():
    wrapped = WorldBranchingProvider(TinyProvider(), world_count=2)
    branches = wrapped.decompose(Seed("build the impossible"), KingdomConfig(max_branches=3))

    assert len(branches) == 3
    assert branches[0].lens == "world:premise_true"
    assert branches[1].lens == "world:premise_false"
    assert "substantially correct" in branches[0].assumption_shift
    assert "wrong or misleading" in branches[1].assumption_shift
    assert branches[2].branch_id == "base"


def test_arena_verified_observation_and_missing_capability(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    arena = ArenaRegistry([RepositoryReadTool(tmp_path)])

    verified = arena.execute(
        ToolRequest("repo_read", "read", {"path": "fact.txt"}, branch_id="b")
    )
    missing = arena.execute(
        ToolRequest("spectrometer", "measure", {}, purpose="measure spectrum", branch_id="b")
    )

    assert verified.observation.status == "verified"
    assert verified.observation.detail == "ground truth"
    assert verified.observation.as_evidence().stance == "observe"
    assert missing.observation.status == "unavailable"
    assert missing.missing is not None
    assert missing.missing.name == "spectrometer"


def test_mind_constructor_reintegrates_verified_evidence_and_promotes_blockers(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    engine = KingdomEngine(
        TinyProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    constructor = MindConstructor(
        engine,
        ArenaRegistry([RepositoryReadTool(tmp_path)]),
        Planner(),
    )

    run = constructor.run(Seed("construct the target"))

    assert any("verified observations=1" == item for item in run.structure.hinge_assumptions)
    assert len(run.missing_capabilities) == 1
    blocker = run.missing_capabilities[0]
    assert blocker.capability == "missing_sensor"
    assert blocker.status == "blocked"
    path = run.graph.path_to(blocker.target_id)
    assert [item.kind for item in path] == ["goal", "branch", "capability"]


def test_mind_constructor_recursively_reduces_blocker_to_executable_frontier(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    engine = KingdomEngine(
        TinyProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    constructor = MindConstructor(
        engine,
        ArenaRegistry([RepositoryReadTool(tmp_path)]),
        Planner(),
        target_decomposer=Decomposer(),
        construction_depth=4,
    )

    run = constructor.run(Seed("construct the target"))
    executable = [target for target in run.graph.frontier() if target.status == "executable"]

    assert len(executable) == 1
    path = run.graph.path_to(executable[0].target_id)
    assert [item.kind for item in path] == ["goal", "branch", "capability", "experiment"]
    assert "proxy measurement" in executable[0].statement
    assert executable[0].origin_branch_id == "base"
    assert len(run.missing_capabilities) == 1


def test_executable_frontier_returns_to_arena_reintegrates_and_closes_dependency(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    engine = KingdomEngine(
        TinyProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    constructor = MindConstructor(
        engine,
        ArenaRegistry([RepositoryReadTool(tmp_path)]),
        Planner(),
        target_decomposer=Decomposer(),
        target_planner=FrontierPlanner(),
        construction_depth=4,
        construction_rounds=2,
    )

    run = constructor.run(Seed("construct the target"))
    proxy = next(
        target
        for target in run.graph.targets.values()
        if "proxy measurement" in target.statement
    )
    capability = next(
        target
        for target in run.graph.targets.values()
        if target.capability == "missing_sensor"
    )

    assert proxy.status == "verified"
    assert capability.status == "verified"
    assert run.missing_capabilities == ()
    assert proxy.origin_branch_id == "base"
    assert "verified observations=2" in run.structure.hinge_assumptions
    assert sum(
        execution.observation.source.startswith("repo:")
        for execution in run.arena_executions
    ) == 2


def test_navigator_expands_structural_claim_back_to_branch_provenance(tmp_path):
    engine = KingdomEngine(
        TinyProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    run = engine.run(Seed("seed"))
    navigator = CognitiveNavigator.from_run(run)

    invariant = next(node for node in navigator.nodes.values() if node.kind == "invariant")
    expanded = navigator.expand(invariant.ref)

    assert invariant.label == "reality contact changes the evidence state"
    assert [node.ref for node in expanded] == ["base"]
    assert "finding from base" in expanded[0].detail
