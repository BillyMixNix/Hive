from __future__ import annotations

import argparse
import json
from pathlib import Path

from HiveLessonMemory import LessonMemory

from twin_realms import (
    TwinRealmsEngine,
    TwinRealmsHiveAdapter,
    build_complexity_world,
)
from twin_realms.models import ActionIntent
from validation.twin_realms_live_study import LiveModelClient


def run_probe(*, output, server_url, model):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = output.with_suffix(".checkpoint.json")
    lesson_path = output.with_suffix(".lessons.jsonl")
    if lesson_path.exists():
        lesson_path.unlink()

    state = build_complexity_world(tier=3, seed=20260611)
    player = state.characters[state.player_id]
    malformed = state.characters["char:malformed"]
    malformed.active = True
    malformed.spawn_turn = None
    malformed.location_id = player.location_id
    player.stamina = 0

    client = LiveModelClient(
        server_url,
        model,
        max_tokens=256,
        fallback_text="{}",
    )
    memory = LessonMemory(lesson_path)
    engine = TwinRealmsEngine(state)
    adapter = TwinRealmsHiveAdapter(
        client,
        lesson_memory=memory,
        learning=True,
    )
    adapter.attach_engine(engine)
    adapter.ensure_actor(player.id, engine.state)

    rejected = engine.apply_intent(ActionIntent(
        "attack",
        player.id,
        target_id=malformed.id,
        parameters={"probe": "bounded_rejection"},
    ))
    adapter.reflect(rejected.event, engine.state)

    recovery = engine.apply_intent(ActionIntent("rest", player.id))
    adapter.observe_world_event(recovery.event, engine.state)

    proposed = adapter.propose(player.id, engine.state)
    resolved = engine.apply_intent(proposed)
    adapter.reflect(resolved.event, engine.state)
    engine.save(checkpoint)

    lessons = []
    if lesson_path.exists():
        lessons = [
            json.loads(line)
            for line in lesson_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    report = {
        "study": "twin_realms_hive_learning_probe",
        "model": model,
        "rejected_event": rejected.event.to_dict(),
        "recovery_event": recovery.event.to_dict(),
        "next_proposal": proposed.to_dict(),
        "next_event": resolved.event.to_dict(),
        "lesson_count": len(lessons),
        "lessons": lessons,
        "lesson_retrieved_on_next_proposal": bool(
            proposed.parameters.get("lesson_ids")
        ),
        "metrics": adapter.metrics_dict(),
        "client": client.metrics(),
        "replay_consistent": engine.verify_replay(),
        "checkpoint": str(checkpoint),
        "lesson_path": str(lesson_path),
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="results/twin_realms_hive_learning_probe.json",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:11435/v1/chat/completions",
    )
    parser.add_argument("--model", default="qwen2.5:3b")
    args = parser.parse_args(argv)
    print(json.dumps(run_probe(
        output=args.output,
        server_url=args.server_url,
        model=args.model,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
