import json

from twin_realms import (
    IntentInterpreter,
    LLMIntentInterpreter,
    LLMKnowledgeAgent,
    LLMNPCPlanner,
    NarrativeGenerator,
    TwinRealmsBenchmark,
    TwinRealmsEngine,
    TwinRealmsRuntime,
)


def _json_response(**values):
    return json.dumps(values)


def test_assisted_mode_uses_llm_for_intent_npc_decisions_and_narration():
    intent_model = lambda prompt: _json_response(
        action="observe",
        target_id="char:malformed",
        confidence=0.97,
        parameters={},
    )
    npc_model = lambda prompt: _json_response(
        action="attack",
        target_id="char:player",
        confidence=0.88,
        parameters={},
    )
    narration_calls = []
    narrator = NarrativeGenerator(
        llm=lambda prompt: narration_calls.append(prompt) or "The resolved moment holds."
    )
    engine = TwinRealmsEngine(
        interpreter=LLMIntentInterpreter(intent_model, fallback=IntentInterpreter()),
        narrator=narrator,
    )
    runtime = TwinRealmsRuntime(
        engine,
        mode="assisted",
        npc_planner=LLMNPCPlanner(npc_model),
        npc_ids=["char:malformed"],
    )

    result = runtime.turn("Carefully assess the warped creature.")

    assert result.player_result.intent.action == "observe"
    assert result.player_result.intent.parameters["proposal_source"] == "llm_intent"
    assert result.npc_results[0].intent.action == "attack"
    assert result.npc_results[0].intent.parameters["proposal_source"] == "llm_npc"
    assert engine.state.characters["char:player"].health < 100
    assert len(narration_calls) == 2
    assert engine.verify_replay()


def test_invalid_llm_intent_falls_back_to_bounded_interpreter():
    interpreter = LLMIntentInterpreter(
        lambda prompt: '{"action": "rewrite_reality"}',
        fallback=IntentInterpreter(),
    )
    engine = TwinRealmsEngine(interpreter=interpreter)

    result = engine.turn("Rest and recover.")

    assert result.intent.action == "rest"
    assert result.event.accepted
    assert interpreter.metrics.invalid == 1
    assert interpreter.metrics.fallbacks == 1


def test_adaptive_mode_promotes_evidence_then_changes_future_resolution(tmp_path):
    intent_model = lambda prompt: _json_response(
        action="space_fold",
        target_id="char:malformed",
        distance=12,
        confidence=0.95,
        parameters={},
    )
    knowledge_model = lambda prompt: _json_response(
        key="space_fold_overreach_strain",
        confidence=0.91,
    )
    engine = TwinRealmsEngine(
        interpreter=LLMIntentInterpreter(intent_model, fallback=IntentInterpreter())
    )
    runtime = TwinRealmsRuntime(
        engine,
        mode="adaptive",
        knowledge_agent=LLMKnowledgeAgent(knowledge_model),
    )

    first_three = [runtime.turn("Fold beyond the known boundary.") for _ in range(3)]
    fourth = runtime.turn("Try the twelve-meter fold again.")

    assert all(not turn.player_result.event.accepted for turn in first_three)
    assert engine.knowledge.is_promoted("space_fold_overreach_strain")
    assert fourth.player_result.event.accepted
    assert fourth.player_result.event.facts["overreach_strain"]
    assert "overextended_meridian" in engine.state.characters["char:player"].injuries
    assert len(engine.knowledge_events) == 4
    assert runtime.metrics()["knowledge_evidence"] == {
        "supported": 4,
        "promoted": 1,
        "support_rate": 1.0,
    }
    assert engine.verify_replay()

    path = tmp_path / "adaptive-world.json"
    engine.save(path)
    loaded = TwinRealmsEngine.load(path)
    assert loaded.snapshot() == engine.snapshot()
    assert loaded.verify_replay()


def test_three_mode_benchmark_reports_proposal_quality_and_replay():
    inputs = [
        ("Observe the malformed.", "observe"),
        ("Rest and recover.", "rest"),
    ]
    baseline = TwinRealmsBenchmark().run(inputs, mode="baseline")

    responses = iter([
        _json_response(
            action="observe",
            target_id="char:malformed",
            confidence=0.9,
            parameters={},
        ),
        _json_response(action="rest", confidence=0.9, parameters={}),
    ])
    assisted_engine = TwinRealmsEngine(
        interpreter=LLMIntentInterpreter(
            lambda prompt: next(responses),
            fallback=IntentInterpreter(),
        )
    )
    assisted = TwinRealmsBenchmark().run(
        inputs,
        mode="assisted",
        engine=assisted_engine,
    )

    assert baseline.replay_consistent
    assert assisted.replay_consistent
    assert assisted.metrics["interpretation_accuracy"] == 1.0
    assert assisted.metrics["intent_proposals"]["validity_rate"] == 1.0
