from types import SimpleNamespace

from kingdom.arena import ArenaObservation, ArenaRegistry
from kingdom.construction import ConstructionGraph
from kingdom.core import CognitivePacket, HashChainLedger, Seed, StructureMap
from kingdom.intent_path import (
    IntentCapsule,
    IntentPathGate,
    IntentPathRecorder,
    IntentStep,
)


class StaticPlanner:
    def __init__(self, *steps):
        self.steps = tuple(steps)

    def plan(self, capsule, artifact_summary, available_tools):
        return self.steps


class StaticJudge:
    def __init__(self, verdict="pass", reason="original intent is satisfied"):
        self.verdict = verdict
        self.reason = reason

    def judge(self, capsule, artifact_summary, step_results):
        return self.verdict, self.reason


class WalkTool:
    name = "walk"

    def __init__(self, status="verified", detail="path works"):
        self.status = status
        self.detail = detail

    def execute(self, request):
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status=self.status,
            claim=f"walk {self.status}",
            detail=self.detail,
            source="walk:test",
            confidence=1.0,
        )


def _step(tool="walk"):
    return IntentStep(
        step_id="1",
        description="Follow the user-facing path from start to finish",
        tool=tool,
        operation="check",
        payload={"case": "representative"},
        purpose="exercise the assembled product as the original user would",
        success_criterion="the complete path succeeds without a handoff gap",
    )


def _run():
    seed = Seed(
        "A new user can submit a task and receive a verified result.",
        context="clean environment",
        goal="preserve the original user outcome",
    )
    graph = ConstructionGraph()
    graph.add(seed.text, kind="goal", status="open")
    return SimpleNamespace(
        base_run=SimpleNamespace(seed=seed, run_id="intent-run"),
        structure=StructureMap(
            invariants=("components are assembled",),
            unknowns=(),
        ),
        packet=CognitivePacket(
            title="candidate",
            orientation="assembled system",
            load_bearing_insights=("components are assembled",),
            uncertainty=(),
            next_moves=(),
        ),
        graph=graph,
        arena_executions=(),
        missing_capabilities=(),
    )


def _root(run):
    return next(
        target
        for target in run.graph.targets.values()
        if target.kind == "goal" and target.parent_id is None
    )


def test_intent_capsule_is_stable_and_changes_when_original_intent_changes():
    first = IntentCapsule.capture(Seed("build A", context="x", goal="g"))
    same = IntentCapsule.capture(Seed("build A", context="x", goal="g"))
    changed = IntentCapsule.capture(Seed("build B", context="x", goal="g"))

    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != changed.fingerprint
    assert first.original_request == "build A"


def test_verified_path_plus_semantic_pass_marks_original_goal_verified():
    run = _run()
    gate = IntentPathGate(StaticPlanner(_step()), StaticJudge("pass"))

    report = gate.walk_and_reopen(run, ArenaRegistry([WalkTool("verified")]))

    assert report.status == "passed"
    assert report.passed is True
    assert _root(run).status == "verified"
    assert report.reopened_target_ids == ()


def test_failed_path_reopens_exact_user_facing_step_even_if_judge_would_pass():
    run = _run()
    gate = IntentPathGate(StaticPlanner(_step()), StaticJudge("pass"))

    report = gate.walk_and_reopen(run, ArenaRegistry([WalkTool("failed", "handoff broke")]))

    assert report.status == "failed"
    assert _root(run).status == "blocked"
    repairs = [
        target
        for target in run.graph.targets.values()
        if target.origin_branch_id == "intent-path"
    ]
    assert len(repairs) == 1
    assert "Follow the user-facing path" in repairs[0].statement
    assert "handoff" in report.steps[0].execution.observation.detail


def test_missing_verification_capability_becomes_child_blocker_of_failed_path():
    run = _run()
    gate = IntentPathGate(StaticPlanner(_step(tool="journey_runner")), StaticJudge("pass"))

    report = gate.walk_and_reopen(run, ArenaRegistry())

    assert report.status == "incomplete"
    assert _root(run).status == "blocked"
    path_repairs = [
        target
        for target in run.graph.targets.values()
        if target.origin_branch_id == "intent-path" and target.kind == "experiment"
    ]
    capabilities = [
        target
        for target in run.graph.targets.values()
        if target.origin_branch_id == "intent-path" and target.kind == "capability"
    ]
    assert len(path_repairs) == 1
    assert len(capabilities) == 1
    assert capabilities[0].parent_id == path_repairs[0].target_id
    assert capabilities[0].capability == "journey_runner"


def test_semantic_drift_reopens_graph_after_all_technical_steps_pass():
    run = _run()
    gate = IntentPathGate(
        StaticPlanner(_step()),
        StaticJudge("fail", "the assembled behavior does not match the original user outcome"),
    )

    report = gate.walk_and_reopen(run, ArenaRegistry([WalkTool("verified")]))

    assert report.status == "failed"
    assert _root(run).status == "blocked"
    semantic = [
        target
        for target in run.graph.targets.values()
        if target.origin_branch_id == "intent-path"
    ]
    assert len(semantic) == 1
    assert "original-intent mismatch" in semantic[0].statement


def test_intent_path_record_is_hash_anchored_and_tamper_evident(tmp_path):
    run = _run()
    report = IntentPathGate(
        StaticPlanner(_step()), StaticJudge("pass")
    ).walk_and_reopen(run, ArenaRegistry([WalkTool("verified")]))
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    recorder = IntentPathRecorder(tmp_path / "intent", ledger=ledger)

    record = recorder.persist(run.base_run.run_id, report)

    assert recorder.verify(record) is True
    assert ledger.verify() is True
    assert record.status == "passed"
    with open(record.path, "a", encoding="utf-8") as handle:
        handle.write("tamper")
    assert recorder.verify(record) is False
