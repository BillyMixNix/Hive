
from workshop import providers

def test_response_body_includes_max_output_tokens():
    body = providers.build_openai_response_body(
        model="gpt-5.6-luna",
        messages=[{"role":"user","content":"hello"}],
        instructions="test",
        effort="medium",
        web=False,
        max_output_tokens=1234,
    )
    assert body["max_output_tokens"] == 1234

def test_response_body_omits_limit_when_none():
    body = providers.build_openai_response_body(
        model="gpt-5.6-luna",
        messages=[{"role":"user","content":"hello"}],
        instructions="test",
        max_output_tokens=None,
    )
    assert "max_output_tokens" not in body

def test_response_body_rejects_invalid_limit():
    try:
        providers.build_openai_response_body(
            model="gpt-5.6-luna",
            messages=[{"role":"user","content":"hello"}],
            instructions="test",
            max_output_tokens=0,
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
