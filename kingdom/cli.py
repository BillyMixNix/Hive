from __future__ import annotations

import argparse
import json
from pathlib import Path

from .arena import ArenaRegistry, HiveArenaPlanner, RepositoryReadTool, RepositorySearchTool, SimulationTool
from .arena_tools import PytestTool
from .construction import HiveTargetDecomposer, MindConstructor
from .core import KingdomConfig, KingdomEngine, Seed
from .diversity import NoveltyFilteringProvider, diversity_report
from .forge import CapabilityForge, HiveCapabilityAuthor, HiveCapabilityOracle
from .intent_path import (
    HiveIntentPathJudge,
    HiveIntentPathPlanner,
    IntentPathGate,
    IntentPathRecorder,
)
from .llm_provider import HiveLLMProvider
from .persistence import ConstructionRecorder
from .resume import ConstructionResumer
from .target_execution import HiveTargetExecutionPlanner
from .worlds import WorldBranchingProvider


def _print_packet(run) -> None:
    packet = run.packet
    print(f"\n=== {packet.title} ===")
    if packet.orientation:
        print(packet.orientation)
    print("\nLOAD-BEARING INSIGHTS")
    for index, item in enumerate(packet.load_bearing_insights, 1):
        print(f"{index}. {item}")
    if packet.uncertainty:
        print("\nUNCERTAINTY")
        for item in packet.uncertainty:
            print(f"- {item}")
    if packet.next_moves:
        print("\nNEXT MOVES")
        for item in packet.next_moves:
            print(f"- {item}")
    if run.probes:
        print("\nCOMPREHENSION GATE")
        for probe in run.probes:
            print(f"[{probe.probe_id}] {probe.question}")
    run_id = getattr(run, "run_id", None)
    if run_id:
        print(f"\nRun id: {run_id}")


def _print_construction(run, record=None, intent_report=None, intent_record=None) -> None:
    _print_packet(run)
    diversity = diversity_report(run.base_run.branches)
    print("\nBRANCH DIVERSITY")
    print(
        f"- effective {diversity.effective_branch_count}/{diversity.branch_count} "
        f"({diversity.efficiency:.0%}); lenses={diversity.unique_lenses}; "
        f"assumption shifts={diversity.unique_assumption_shifts}"
    )
    if diversity.correlated_pairs:
        print(f"- correlated pairs still present: {len(diversity.correlated_pairs)}")
    if run.arena_executions:
        print("\nARENA")
        for execution in run.arena_executions:
            observation = execution.observation
            print(
                f"- [{observation.status}] {observation.tool}.{observation.operation}: "
                f"{observation.claim}"
            )
    if run.forge_attempts:
        print("\nCAPABILITY FORGE")
        for attempt in run.forge_attempts:
            suffix = " registered" if attempt.registered else ""
            print(
                f"- [{attempt.status}] {attempt.capability}.{attempt.operation}{suffix}: "
                f"{attempt.detail}"
            )
    if intent_report is not None:
        print("\nCRITICAL INTENT PATH")
        print(f"- [{intent_report.status}] {intent_report.reason}")
        for result in intent_report.steps:
            observation = result.execution.observation
            print(
                f"- step {result.step.step_id} [{result.status}] {result.step.description}: "
                f"{observation.claim}"
            )
        print(
            f"- semantic verdict [{intent_report.semantic_verdict}]: "
            f"{intent_report.semantic_reason}"
        )
        if intent_report.reopened_target_ids:
            print(f"- reopened construction targets: {len(intent_report.reopened_target_ids)}")
    frontier = run.graph.frontier()
    if frontier:
        print("\nCONSTRUCTION FRONTIER")
        for target in frontier:
            print(f"- [{target.kind}/{target.status}] {target.statement}")
    if run.missing_capabilities:
        print("\nMISSING CAPABILITIES")
        for target in run.missing_capabilities:
            print(f"- {target.capability}: {target.reason or target.statement}")
    print(f"\nBase Kingdom run id: {run.base_run.run_id}")
    if record is not None:
        print(f"Construction record: {record.path}")
        print(f"Construction SHA256: {record.sha256}")
    if intent_record is not None:
        print(f"Intent path record: {intent_record.path}")
        print(f"Intent path SHA256: {intent_record.sha256}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kingdom",
        description="Kingdom: decompress intent, explore worlds, contact reality, construct blockers, then walk the original intent end-to-end.",
    )
    parser.add_argument("seed", nargs="?", help="compressed idea, goal, or question to decompress")
    parser.add_argument("--resume-run-id", default="", help="continue the latest ledger-verified construction checkpoint for this Kingdom run id")
    parser.add_argument("--context", default="", help="optional operator context")
    parser.add_argument("--goal", default="convert intent into verified executable progress")
    parser.add_argument("--branches", type=int, default=12, help="maximum total branches")
    parser.add_argument("--depth", type=int, default=1, help="maximum branch depth")
    parser.add_argument("--workers", type=int, default=4, help="parallel branch workers")
    parser.add_argument("--codec-items", type=int, default=10, help="maximum load-bearing insights")
    parser.add_argument("--worlds", type=int, default=6, help="required incompatible world branches in construct mode")
    parser.add_argument("--construct", action="store_true", help="enable worlds + Arena + recursive blocker promotion")
    parser.add_argument(
        "--forge-missing",
        action="store_true",
        help="allow missing pure-function capabilities to be independently tested, regression-gated, isolated, registered, and retried",
    )
    parser.add_argument(
        "--skip-intent-path",
        action="store_true",
        help="debug escape hatch: skip the terminal critical-path walk of the original intent",
    )
    parser.add_argument("--construction-depth", type=int, default=3, help="recursive levels below each blocker")
    parser.add_argument("--construction-rounds", type=int, default=3, help="maximum execute/decompose frontier cycles")
    parser.add_argument("--target-budget", type=int, default=40, help="maximum construction targets")
    parser.add_argument("--repo-root", default=".", help="repository root exposed to read/search/test Arena tools")
    parser.add_argument("--json", action="store_true", help="print complete base run JSON (standard mode only)")
    parser.add_argument("--run-dir", default=".hive/kingdom/runs")
    parser.add_argument("--construction-run-dir", default=".hive/kingdom/construction_runs")
    parser.add_argument("--intent-path-run-dir", default=".hive/kingdom/intent_paths")
    parser.add_argument("--ledger", default=".hive/kingdom/ledger.jsonl")
    return parser


def _arena(repo_root: Path) -> ArenaRegistry:
    return ArenaRegistry(
        [
            RepositoryReadTool(repo_root),
            RepositorySearchTool(repo_root),
            SimulationTool(),
            PytestTool(repo_root),
        ]
    )


def _walk_original_intent(run, arena, engine, args):
    if args.skip_intent_path:
        return None, None
    gate = IntentPathGate(
        HiveIntentPathPlanner(),
        HiveIntentPathJudge(),
    )
    report = gate.walk_and_reopen(run, arena)
    intent_recorder = IntentPathRecorder(
        Path(args.intent_path_run_dir),
        ledger=engine.ledger,
    )
    record = intent_recorder.persist(run.base_run.run_id, report)
    return report, record


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.seed and not args.resume_run_id:
        parser.error("provide a seed or --resume-run-id")

    config = KingdomConfig(
        max_branches=args.branches,
        max_depth=args.depth,
        workers=args.workers,
        codec_items=args.codec_items,
    )
    provider = HiveLLMProvider()
    if args.construct or args.resume_run_id:
        provider = NoveltyFilteringProvider(
            WorldBranchingProvider(provider, world_count=args.worlds)
        )

    engine = KingdomEngine(
        provider,
        config=config,
        run_dir=Path(args.run_dir),
        ledger_path=Path(args.ledger),
    )
    recorder = ConstructionRecorder(
        Path(args.construction_run_dir),
        ledger=engine.ledger,
    )

    if args.resume_run_id:
        arena = _arena(Path(args.repo_root))
        forge = (
            CapabilityForge(
                arena,
                HiveCapabilityAuthor(),
                oracle=HiveCapabilityOracle(),
            )
            if args.forge_missing
            else None
        )
        prior = recorder.load_verified(args.resume_run_id)
        resumer = ConstructionResumer(
            engine,
            arena,
            target_decomposer=HiveTargetDecomposer(),
            target_planner=HiveTargetExecutionPlanner(),
            capability_forge=forge,
            construction_depth=args.construction_depth,
            target_budget=args.target_budget,
            construction_rounds=args.construction_rounds,
        )
        run = resumer.advance(prior)
        intent_report, intent_record = _walk_original_intent(run, arena, engine, args)
        record = recorder.persist(run)
        _print_construction(run, record, intent_report, intent_record)
        return 0

    seed = Seed(text=args.seed or "", context=args.context, goal=args.goal)
    if args.construct:
        arena = _arena(Path(args.repo_root))
        forge = (
            CapabilityForge(
                arena,
                HiveCapabilityAuthor(),
                oracle=HiveCapabilityOracle(),
            )
            if args.forge_missing
            else None
        )
        constructor = MindConstructor(
            engine,
            arena,
            HiveArenaPlanner(),
            target_decomposer=HiveTargetDecomposer(),
            target_planner=HiveTargetExecutionPlanner(),
            capability_forge=forge,
            construction_depth=args.construction_depth,
            target_budget=args.target_budget,
            construction_rounds=args.construction_rounds,
        )
        run = constructor.run(seed)
        intent_report, intent_record = _walk_original_intent(run, arena, engine, args)
        record = recorder.persist(run)
        _print_construction(run, record, intent_report, intent_record)
        return 0

    run = engine.run(seed)
    if args.json:
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
    else:
        _print_packet(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())