from kingdom.arena import ArenaRegistry, RepositoryReadTool, ToolRequest
from kingdom.construction import (
    ConstructionGraph,
    ConstructionRun,
    TargetDecomposition,
    TargetDraft,
)
from kingdom.core import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionAssessment,
    ComprehensionProbe,
    Evidence,
    KingdomConfig,
    KingdomEngine,
    KingdomRun,
    Seed,
    StructureMap,
)
from kingdom.resume import ConstructionResumer


class ResumeProvider:
    def decompose(self, seed, config):
        return ()

    def explore(self, seed, branch):
        raise AssertionError("resume must not replay branch exploration")

    def integrate(self, seed, branches, results):
        observations = sum(
            evidence.stance == "observe"
            for result in results
            for evidence in result.evidence
        )
        return StructureMap(
            invariants=("resumed evidence is reintegrated",),
            hinge_assumptions=(f"observations={observations}",),
        )

    def encode(self, seed, structure, config):
        return CognitivePacket(
            title="resume",
            orientation="continue frontier",
            load_bearing_insights=structure.invariants + structure.hinge_assumptions,
            uncertainty=(),
            next_moves=(),
        )

    def make_probes(self, seed, structure, packet):
        return (ComprehensionProbe("p", "Did evidence change?", "observations"),)

    def assess(self, seed, structure, probes, answers):
        return ComprehensionAssessment(1.0, ("observations",), (), ())


class ResumePlanner:
    def plan(self, seed, target, available_tools):
        return (
            ToolRequest(
                "repo_read",
                "read",
                {"path": "fact.txt"},
                purpose=target.statement,
                branch_id=target.origin_branch_id,
            ),
        )


class IntentRepairDecomposer:
    def decompose(self, target, available_capabilities):
        assert target.origin_branch_id == "intent-path"
        return TargetDecomposition(
            mode="all",
            targets=(
                TargetDraft(
                    "Re-run the repaired end-to-end path against the repository fixture",
                    kind="experiment",
                    status="executable",
                    reason="prove the critical path now composes",
                ),
            ),
        )


def _base_run():
    seed = Seed("continue the build")
    branch = BranchSpec("b", "implementation", "Verify the next leaf", "use reality")
    result = BranchResult(
        branch_id="b",
        findings=("leaf exists",),
        evidence=(Evidence("not yet checked", "uncertain", 0.5, "model"),),
    )
    structure = StructureMap(invariants=("prior structure",))
    packet = CognitivePacket("prior", "prior", ("prior structure",), (), ())
    return KingdomRun(
        run_id="kingdom-resume-test",
        seed=seed,
        branches=(branch,),
        results=(result,),
        structure=structure,
        packet=packet,
        probes=(),
        started_at=1.0,
        finished_at=2.0,
    ), result


def test_resume_executes_saved_frontier_without_replaying_search(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    base, result = _base_run()
    graph = ConstructionGraph()
    root = graph.add(base.seed.text, kind="goal", status="open")
    branch_target = graph.add(
        "Verify the next leaf",
        kind="branch",
        parent_id=root.target_id,
        status="open",
        origin_branch_id="b",
    )
    leaf = graph.add(
        "Read the repository fact",
        kind="experiment",
        parent_id=branch_target.target_id,
        status="executable",
    )
    prior = ConstructionRun(
        base_run=base,
        verified_results=(result,),
        arena_executions=(),
        graph=graph,
        structure=base.structure,
        packet=base.packet,
        probes=(),
    )
    engine = KingdomEngine(
        ResumeProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    resumed = ConstructionResumer(
        engine,
        ArenaRegistry([RepositoryReadTool(tmp_path)]),
        target_planner=ResumePlanner(),
        construction_rounds=1,
    ).advance(prior)

    assert resumed.graph.targets[leaf.target_id].status == "verified"
    assert len(resumed.arena_executions) == 1
    assert resumed.verified_results[0].evidence[-1].source == "repo:fact.txt"
    assert "observations=1" in resumed.structure.hinge_assumptions


def test_resume_demotes_ephemeral_capability_that_is_not_in_new_arena(tmp_path):
    base, result = _base_run()
    graph = ConstructionGraph()
    root = graph.add(base.seed.text, kind="goal", status="open")
    capability = graph.add(
        "Use acquired ephemeral capability",
        kind="capability",
        parent_id=root.target_id,
        status="verified",
        capability="ephemeral_tool",
        origin_branch_id="b",
    )
    prior = ConstructionRun(
        base_run=base,
        verified_results=(result,),
        arena_executions=(),
        graph=graph,
        structure=base.structure,
        packet=base.packet,
        probes=(),
    )
    engine = KingdomEngine(
        ResumeProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )

    resumed = ConstructionResumer(engine, ArenaRegistry()).advance(prior)

    assert resumed.graph.targets[capability.target_id].status == "blocked"
    assert resumed.missing_capabilities[0].capability == "ephemeral_tool"


def test_resume_decomposes_and_executes_blocked_intent_path_repair(tmp_path):
    (tmp_path / "fact.txt").write_text("ground truth", encoding="utf-8")
    base, result = _base_run()
    graph = ConstructionGraph()
    root = graph.add(base.seed.text, kind="goal", status="blocked")
    repair = graph.add(
        "Critical path repair: complete the user-facing journey",
        kind="experiment",
        parent_id=root.target_id,
        status="blocked",
        reason="the terminal walk exposed a broken handoff",
        origin_branch_id="intent-path",
    )
    prior = ConstructionRun(
        base_run=base,
        verified_results=(result,),
        arena_executions=(),
        graph=graph,
        structure=base.structure,
        packet=base.packet,
        probes=(),
    )
    engine = KingdomEngine(
        ResumeProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )

    resumed = ConstructionResumer(
        engine,
        ArenaRegistry([RepositoryReadTool(tmp_path)]),
        target_decomposer=IntentRepairDecomposer(),
        target_planner=ResumePlanner(),
        construction_depth=2,
        construction_rounds=1,
    ).advance(prior)

    assert resumed.graph.targets[repair.target_id].status == "verified"
    children = resumed.graph.children[repair.target_id]
    assert len(children) == 1
    assert resumed.graph.targets[children[0]].status == "verified"
    assert resumed.graph.targets[children[0]].origin_branch_id == "intent-path"
    assert len(resumed.arena_executions) == 1