from twin_realms import IntentInterpreter, LLMIntentInterpreter, LLMNPCPlanner, TwinRealmsEngine
from twin_realms.models import ActionIntent
from validation.twin_realms_live_study import (
    configure_scenario,
    summarize_actors,
)


def test_nullable_model_parameters_are_normalized():
    interpreter = LLMIntentInterpreter(
        lambda prompt: (
            '{"action":"observe","target_id":"char:malformed",'
            '"confidence":0.9,"parameters":null}'
        ),
        fallback=IntentInterpreter(),
    )
    engine = TwinRealmsEngine(interpreter=interpreter)

    result = engine.turn("Observe the malformed.")

    assert result.intent.parameters == {"proposal_source": "llm_intent"}
    assert result.event.accepted


def test_nullable_npc_parameters_are_normalized():
    planner = LLMNPCPlanner(
        lambda prompt: '{"action":"wait","confidence":0.9,"parameters":null}'
    )
    engine = TwinRealmsEngine()

    intent = planner.propose("char:malformed", engine.state)

    assert intent.parameters == {"proposal_source": "llm_npc"}


def test_live_study_summarizes_each_actor_independently():
    engine = TwinRealmsEngine()
    engine.apply_intent(ActionIntent("wait", "char:player"))
    engine.apply_intent(ActionIntent("wait", "char:malformed"))
    engine.apply_intent(ActionIntent("wait", "char:malformed"))

    summaries = summarize_actors(engine)

    assert summaries["char:player"]["events"] == 1
    assert summaries["char:malformed"]["events"] == 2
    assert summaries["char:malformed"]["action_counts"] == {"wait": 2}
    assert summaries["char:malformed"]["max_repeated_action_streak"] == 2


def test_hostile_contact_scenario_activates_and_colocates_malformed():
    engine = TwinRealmsEngine()
    state = configure_scenario(engine.state, "hostile_contact")

    malformed = state.characters["char:malformed"]
    player = state.characters[state.player_id]
    assert malformed.active
    assert malformed.spawn_turn is None
    assert malformed.location_id == player.location_id
    assert state.flags["hostile_contact_scenario"]
