import hive_llm


def _mock_ask_model(
    prompt,
    model=None,
    timeout=120,
    options=None,
    max_retries=None,
    metadata=None,
):
    # Return a simple JSON reflection for any prompt to keep tests deterministic.
    if metadata is not None:
        metadata.update(
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 1,
                "eval_count": 1,
            }
        )
    return '{"reflection": "Auto-reflection OK", "confidence": 0.9, "next_step": "none", "verdict": "accept"}'


# Patch hive_llm functions used by the code under test.
hive_llm.ask_model = _mock_ask_model
def _ask_hive(
    prompt,
    role="default",
    timeout=None,
    model=None,
    system=None,
    options=None,
    max_retries=None,
    metadata=None,
):
    return _mock_ask_model(
        prompt,
        model=model,
        timeout=timeout,
        options=options,
        max_retries=max_retries,
        metadata=metadata,
    )

hive_llm.ask_hive = _ask_hive
