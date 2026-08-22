from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import KingdomConfig, KingdomEngine, Seed
from .llm_provider import HiveLLMProvider


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
    print(f"\nRun id: {run.run_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kingdom",
        description="Kingdom-0: decompress an idea, explore branches, reintegrate structure, and test comprehension.",
    )
    parser.add_argument("seed", help="compressed idea or question to decompress")
    parser.add_argument("--context", default="", help="optional operator context")
    parser.add_argument("--goal", default="increase operator understanding")
    parser.add_argument("--branches", type=int, default=12, help="maximum total branches")
    parser.add_argument("--depth", type=int, default=1, help="maximum branch depth")
    parser.add_argument("--workers", type=int, default=4, help="parallel branch workers")
    parser.add_argument("--codec-items", type=int, default=10, help="maximum load-bearing insights")
    parser.add_argument("--json", action="store_true", help="print complete run JSON")
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
    engine = KingdomEngine(
        HiveLLMProvider(),
        config=config,
        run_dir=Path(args.run_dir),
        ledger_path=Path(args.ledger),
    )
    run = engine.run(Seed(text=args.seed, context=args.context, goal=args.goal))
    if args.json:
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
    else:
        _print_packet(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
