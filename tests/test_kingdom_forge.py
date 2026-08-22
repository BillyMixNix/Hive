from __future__ import annotations

from kingdom.arena import ArenaRegistry, ToolRequest
from kingdom.construction import MindConstructor
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
from kingdom.forge import (
    CapabilityCandidate,
    CapabilityCase,
    CapabilityForge,
    SafeCapabilityValidator,
)


VALID_SOURCE = """
def execute(payload):
    return {"value": payload["x"] + 1}
""".strip()


class StaticAuthor:
    def __init__(self, candidate):
        self.candidate = candidate

    def author(self, target, request):
        return self.candidate


class StaticOracle:
    def __init__(self, cases):
        self._cases = tuple(cases)

    def cases(self, target, request, candidate):
        return self._cases


class ForgeProvider:
    def decompose(self, seed, config):
        return [
            BranchSpec(
                "forge-branch",
                "implementation",
                "Measure the missing quantity.",
                "require external measurement",
            )
        ]

    def explore(self, seed, branch):
        return BranchResult(
            branch_id=branch.branch_id,
            findings=("measurement is required",),
            evidence=(Evidence("measurement needed", "uncertain", 0.5, "model"),),
            assumptions=(branch.assumption_shift,),
            uncertainties=("missing measurement capability",),
        )

    def integrate(self, seed, branches, results):
        forge_observations = sum(
            1
            for result in results
            for evidence in result.evidence
            if evidence.stance == "observe" and evidence.source.startswith("forge:")
        )
        return StructureMap(
            invariants=("validated capabilities may close blockers",),
            disagreements=(),
            hinge_assumptions=(f"forge observations={forge_observations}",),
            causal_links=("missing tool -> forge -> retry -> evidence",),
            anomalies=(),
            unknowns=(),
            provenance={"validated capabilities may close blockers": ("forge-branch",)},
        )

    def encode(self, seed, structure, config):
        return CognitivePacket(
            title="forge",
            orientation="capability acquisition",
            load_bearing_insights=structure.invariants + structure.hinge_assumptions,
            uncertainty=(),
            next_moves=(),
            inspectable_refs=structure.provenance,
        )

    def make_probes(self, seed, structure, packet):
        return [ComprehensionProbe("p", "What changed?", "capability")]

    def assess(self, seed, structure, probes, answers):
        return ComprehensionAssessment(1.0, ("capability",), (), ())


class MissingPlanner:
    def plan(self, seed, branch, result, available_tools):
        return (
            ToolRequest(
                tool="missing_sensor",
                operation="measure",
                payload={"x": 2},
                purpose="derive a deterministic measurement",
                branch_id=branch.branch_id,
            ),
        )


def candidate(expected=3, source=VALID_SOURCE):
    return CapabilityCandidate(
        capability="missing_sensor",
        operation="measure",
        source=source,
        cases=(CapabilityCase({"x": 2}, {"value": expected}),),
    )


def request(x=8):
    return ToolRequest(
        "missing_sensor",
        "measure",
        {"x": x},
        purpose="test forged capability",
        branch_id="b",
    ).normalized()


def target():
    return type(
        "Target",
        (),
        {"target_id": "t", "statement": "build missing sensor"},
    )()


def test_policy_rejects_imports_before_regression_execution():
    unsafe = candidate(
        source="def execute(payload):\n    import os\n    return {\"value\": 3}\n"
    )

    validation = SafeCapabilityValidator().validate(unsafe)

    assert validation.passed is False
    assert validation.policy_passed is False
    assert "Import" in validation.detail


def test_wrong_candidate_is_rejected_by_regression_gate():
    validation = SafeCapabilityValidator().validate(candidate(expected=99))

    assert validation.passed is False
    assert validation.policy_passed is True
    assert validation.regression_passed is False
    assert validation.regression_report["failed_case_ids"]


def test_independent_oracle_can_veto_author_examples():
    arena = ArenaRegistry()
    oracle = StaticOracle((CapabilityCase({"x": 3}, {"value": 99}),))
    forge = CapabilityForge(arena, StaticAuthor(candidate()), oracle=oracle)

    attempt = forge.attempt(target(), request())

    assert attempt.status == "rejected"
    assert attempt.validation is not None
    assert attempt.validation.regression_passed is False
    assert "missing_sensor" not in arena.tool_names


def test_valid_candidate_passes_gate_registers_and_executes():
    arena = ArenaRegistry()
    forge = CapabilityForge(arena, StaticAuthor(candidate()))

    attempt = forge.attempt(target(), request())
    execution = arena.execute(request())

    assert attempt.status == "accepted"
    assert attempt.registered is True
    assert "missing_sensor" in arena.tool_names
    assert execution.observation.status == "verified"
    assert execution.observation.source.startswith("forge:")
    assert execution.observation.detail == '{"value": 9}'


def test_mind_constructor_forges_retries_and_closes_blocker(tmp_path):
    arena = ArenaRegistry()
    forge = CapabilityForge(arena, StaticAuthor(candidate()))
    engine = KingdomEngine(
        ForgeProvider(),
        config=KingdomConfig(max_branches=1, max_depth=0),
        run_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    constructor = MindConstructor(
        engine,
        arena,
        MissingPlanner(),
        capability_forge=forge,
    )

    run = constructor.run(Seed("acquire the missing capability"))

    assert len(run.forge_attempts) == 1
    assert run.forge_attempts[0].status == "accepted"
    assert run.missing_capabilities == ()
    assert "missing_sensor" in arena.tool_names
    assert "forge observations=1" in run.structure.hinge_assumptions
    assert any(
        execution.observation.status == "verified"
        and execution.observation.source.startswith("forge:")
        for execution in run.arena_executions
    )
