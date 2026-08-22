from __future__ import annotations

import argparse
import json
from pathlib import Path

from .arena import ArenaRegistry, HiveArenaPlanner, RepositoryReadTool, RepositorySearchTool, SimulationTool
from .construction import HiveTargetDecomposer, MindConstructor
from .core import KingdomConfig, KingdomEngine, Seed
from .forge import CapabilityForge, HiveCapabilityAuthor, HiveCapabilityOracle
from .llm_provider import HiveLLMProvider
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


def _print_construction(run) -> None:
    _print_packet(run)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kingdom",
        description="Kingdom: decompress intent, explore worlds, contact reality, and recursively construct blockers.",
    )
    parser.add_argument("seed", help="compressed idea, goal, or question to decompress")
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
    parser.add_argument("--construction-depth", type=int, default=3, help="recursive levels below each blocker")
    parser.add_argument("--construction-rounds", type=int, default=3, help="maximum execute/decompose frontier cycles")
    parser.add_argument("--target-budget", type=int, default=40, help="maximum construction targets")
    parser.add_argument("--repo-root", default=".", help="repository root exposed to read/search Arena tools")
    parser.add_argument("--json", action="store_true", help="print complete base run JSON (standard mode only)")
    parser.add_argument("--run-dir", default=".hive/kingdom/runs")
    parser.add_argument("--ledger", default=".hive/kingdom/ledger.jsonl")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = KingdomConfig(
        max_branches=args.branches,
        max_depth=args.depth,
        workers=args.workers,
        codec_items=args.codec_items,
    )
    seed = Seed(text=args.seed, context=args.context, goal=args.goal)
    provider = HiveLLMProvider()

    if args.construct:
        provider = WorldBranchingProvider(provider, world_count=args.worlds)

    engine = KingdomEngine(
        provider,
        config=config,
        run_dir=Path(args.run_dir),
        ledger_path=Path(args.ledger),
    )

    if args.construct:
        repo_root = Path(args.repo_root)
        arena = ArenaRegistry(
            [
                RepositoryReadTool(repo_root),
                RepositorySearchTool(repo_root),
                SimulationTool(),
            ]
        )
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
        _print_construction(run)
        return 0

    run = engine.run(seed)
    if args.json:
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
    else:
        _print_packet(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
