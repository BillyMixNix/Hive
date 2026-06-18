from twin_realms import LLMIntentInterpreter, LLMNPCPlanner, TwinRealmsEngine


def test_intent_prompt_contains_exact_contract_and_item_rule():
    engine = TwinRealmsEngine()
    interpreter = LLMIntentInterpreter(lambda prompt: "{}")

    prompt = interpreter.build_prompt(
        "Drop the iron sword.",
        engine.state,
        "char:player",
    )

    assert '"destination_id":null' in prompt
    assert '"action":"ACTION"' in prompt
    assert '"action":"rest"' in prompt
    assert '"action":"space_fold"' in prompt
    assert "Use null for an unused nullable field" in prompt
    assert "parameters.item_id" in prompt
    assert "Do not copy or repeat the input packet" in prompt


def test_npc_prompt_contains_minimal_examples_and_no_copy_rule():
    engine = TwinRealmsEngine()
    planner = LLMNPCPlanner(lambda prompt: "{}")

    prompt = planner.build_prompt("char:malformed", engine.state)

    assert '"action":"attack"' in prompt
    assert '"action":"move"' in prompt
    assert "Do not repeat or copy the world state" in prompt
    assert "Never include actor_id, health, stamina" in prompt
