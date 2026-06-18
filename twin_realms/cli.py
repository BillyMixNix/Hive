from __future__ import annotations

import argparse
from pathlib import Path

from .ai import LLMIntentInterpreter, LLMKnowledgeAgent, LLMNPCPlanner
from .content import build_complexity_world, build_foundation_world
from .engine import TwinRealmsEngine
from .intent import IntentInterpreter
from .narrative import NarrativeGenerator
from .runtime import TwinRealmsRuntime
from .tarrow import run_tarrow_heartbeat
from .tarrow import build_tarrow_aftermath_world
from .hive_adapter import TwinRealmsHiveAdapter
from .play import TerminalPlayer


def _print_tarrow_heartbeat_report(report):
    print("Tarrow heartbeat report")
    print(f"Scenario: {report.scenario_id}")
    print(f"Days: {report.start_day} -> {report.end_day}")
    print(f"World ticks: {report.turns_advanced}")
    print("Village pressures:")
    for key in sorted(report.pressure_before):
        before = report.pressure_before[key]
        after = report.pressure_after.get(key, before)
        delta = after - before
        print(f"  {key}: {before} -> {after} ({delta:+d})")
    print(f"Memory drift: {report.memory_delta:+d}")
    changed = "yes" if report.changed_without_player_force else "no"
    replay = "yes" if report.replay_consistent else "no"
    print(f"Changed without player force: {changed}")
    print(f"Replay consistent: {replay}")
    print(f"State digest: {report.state_digest}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Twin Realms simulation slice.")
    parser.add_argument(
        "--heartbeat-report",
        action="store_true",
        help="Print the Tarrow day-1 to day-7 heartbeat proof and exit.",
    )
    parser.add_argument(
        "--heartbeat-days",
        type=int,
        default=7,
        help="Number of in-game days to advance for --heartbeat-report.",
    )
    parser.add_argument("--save", default="twin_realms_save.json")
    parser.add_argument(
        "--scenario",
        choices=["foundation", "complexity", "tarrow"],
        default="foundation",
        help="World scenario to start when --new is used or no save exists.",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh world even if the save path already exists.",
    )
    parser.add_argument(
        "--mode",
        choices=[
            "baseline",
            "assisted",
            "adaptive",
            "hive",
            "hive_learning",
        ],
        default="baseline",
    )
    parser.add_argument("--tier", type=int, choices=[0, 1, 2, 3], default=0)
    parser.add_argument(
        "--npc-limit",
        type=int,
        default=0,
        help="Maximum NPC minds acting per player turn; 0 means no cap.",
    )
    parser.add_argument(
        "--npc-scope",
        choices=["local", "all"],
        default="local",
        help="Run Hive for NPCs near the player or every active NPC.",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use Hive for prose narration; otherwise narration is deterministic.",
    )
    parser.add_argument(
        "--hive-model",
        default=None,
        help="Override the Ollama model used by Hive NPCs and narration.",
    )
    parser.add_argument(
        "--hive-url",
        default=None,
        help="Use an OpenAI-compatible chat endpoint instead of Ollama.",
    )
    parser.add_argument(
        "--player-control",
        choices=["human", "agent"],
        default="human",
        help="Human accepts direct commands; agent gives control to Hive cognition.",
    )
    args = parser.parse_args(argv)
    if args.heartbeat_report:
        _print_tarrow_heartbeat_report(
            run_tarrow_heartbeat(days=args.heartbeat_days)
        )
        return
    if args.player_control == "agent" and args.mode not in {
        "hive",
        "hive_learning",
    }:
        parser.error("--player-control agent requires --mode hive or hive_learning")
    save_path = Path(args.save)
    if args.hive_url:
        from .llm_client import OpenAIChatClient

        hive_llm = OpenAIChatClient(
            args.hive_url,
            args.hive_model or "local-model",
        )
    else:
        from hive_llm import ask_hive

        hive_llm = lambda prompt, role="default": ask_hive(
            prompt,
            role=role,
            model=args.hive_model,
        )
    if args.llm:
        narrator = NarrativeGenerator(
            llm=lambda prompt: hive_llm(prompt, role="default")
        )
    else:
        narrator = NarrativeGenerator()
    engine = (
        TwinRealmsEngine.load(save_path, narrator=narrator)
        if save_path.exists() and not args.new
        else TwinRealmsEngine(
            _build_world_for_args(args),
            narrator=narrator,
        )
    )
    npc_planner = None
    knowledge_agent = None
    player_agent = None
    if args.mode in {"assisted", "adaptive"}:
        engine.interpreter = LLMIntentInterpreter.using_hive(
            fallback=IntentInterpreter()
        )
        npc_planner = LLMNPCPlanner.using_hive()
    if args.mode == "adaptive":
        knowledge_agent = LLMKnowledgeAgent.using_hive()
    if args.mode in {"hive", "hive_learning"}:
        from HiveLessonMemory import LessonMemory

        hive_agent = TwinRealmsHiveAdapter(
            hive_llm,
            learning=args.mode == "hive_learning",
            lesson_memory=LessonMemory("twin_realms_lessons.jsonl"),
        )
        npc_planner = hive_agent
        if args.player_control == "agent":
            player_agent = hive_agent
    runtime = TwinRealmsRuntime(
        engine,
        mode=args.mode,
        npc_planner=npc_planner,
        knowledge_agent=knowledge_agent,
        npc_scope=args.npc_scope,
        npc_limit=args.npc_limit or None,
    )
    if player_agent:
        print("Twin Realms autonomous player. Type a goal or 'quit'.")
        while True:
            text = input("> ").strip()
            if text.lower() in {"quit", "exit"}:
                break
            player_agent.set_goal(engine.state.player_id, text)
            result = runtime.agent_turn(player_agent)
            print(result.player_result.narrative)
            for npc_result in result.npc_results:
                print(f"[World] {npc_result.narrative}")
        engine.save(save_path)
        print(f"Saved turn {engine.state.turn} to {save_path}.")
        return
    TerminalPlayer(runtime, save_path=save_path).run()


def _build_world_for_args(args):
    if args.scenario == "tarrow":
        return build_tarrow_aftermath_world()
    if args.scenario == "complexity" or args.tier > 0:
        return build_complexity_world(args.tier)
    return build_foundation_world()


if __name__ == "__main__":
    main()
