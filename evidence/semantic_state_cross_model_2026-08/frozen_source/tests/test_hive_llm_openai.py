from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

import hive_llm


HIVE_LLM_PATH = Path(hive_llm.__file__)
HIVE_ENV_KEYS = (
    "HIVE_PROVIDER",
    "HIVE_OPENAI_MODEL",
    "HIVE_REASONING_EFFORT",
    "HIVE_MAX_OUTPUT_TOKENS",
    "HIVE_TIMEOUT_SECONDS",
    "HIVE_MAX_ATTEMPTS",
    "HIVE_TOOL_PERMISSIONS",
    "HIVE_OPENAI_STORE",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_CUSTOM_HEADERS",
    "ANTHROPIC_API_KEY",
)


def _live_adapter():
    spec = importlib.util.spec_from_file_location(
        "hive_llm_openai_adapter_under_test", HIVE_LLM_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def adapter(monkeypatch):
    for key in HIVE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return _live_adapter()


def _response(*, status="completed", output_text="A", usage=True):
    token_usage = None
    if usage:
        token_usage = SimpleNamespace(
            input_tokens=31,
            output_tokens=7,
            total_tokens=38,
            input_tokens_details=SimpleNamespace(
                cached_tokens=11,
                cache_write_tokens=3,
            ),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        )
    return SimpleNamespace(
        id="resp_test",
        model="gpt-5.6-luna-2026-08-01",
        service_tier="default",
        status=status,
        output_text=output_text,
        usage=token_usage,
        incomplete_details=(
            SimpleNamespace(reason="max_output_tokens")
            if status == "incomplete"
            else None
        ),
        error=None,
    )


def _install_fake_sdk(monkeypatch, adapter, *, response=None, create_error=None):
    observed = {"client_calls": [], "requests": []}

    class Responses:
        def create(self, **kwargs):
            observed["requests"].append(kwargs)
            if create_error is not None:
                raise create_error
            return response or _response()

    class Client:
        def __init__(self, **kwargs):
            observed["client_calls"].append(kwargs)
            self.responses = Responses()

    sdk = SimpleNamespace(__version__="3.3.1")
    monkeypatch.setattr(adapter, "_load_openai_sdk", lambda: (sdk, Client))
    return observed


def test_openai_success_uses_frozen_request_and_captures_metadata(
    adapter, monkeypatch
):
    monkeypatch.setenv("HIVE_PROVIDER", "openai")
    monkeypatch.setenv("HIVE_OPENAI_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("HIVE_REASONING_EFFORT", "high")
    monkeypatch.setenv("HIVE_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("HIVE_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("HIVE_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-change-routing")
    observed = _install_fake_sdk(
        monkeypatch, adapter, response=_response(output_text=" A\n")
    )
    metadata = {"stale": True}

    result = adapter.ask_hive(
        "question",
        role="coder",
        system="system contract",
        metadata=metadata,
    )

    assert result == " A\n"
    assert observed["client_calls"] == [{"timeout": 45.0, "max_retries": 0}]
    assert observed["requests"] == [
        {
            "model": "gpt-5.6-luna",
            "instructions": "system contract",
            "input": "question",
            "reasoning": {"effort": "high", "context": "current_turn"},
            "max_output_tokens": 2048,
            "tools": [],
            "store": False,
            "truncation": "disabled",
            "service_tier": "default",
            "prompt_cache_options": {"mode": "explicit"},
        }
    ]
    assert metadata["provider"] == "openai"
    assert metadata["api"] == "responses"
    assert metadata["provider_fallback"] is False
    assert metadata["physical_attempts"] == 1
    assert metadata["adapter_status"] == "completed"
    assert metadata["response_status"] == "completed"
    assert metadata["requested_model"] == "gpt-5.6-luna"
    assert metadata["returned_model"] == "gpt-5.6-luna-2026-08-01"
    assert metadata["returned_service_tier"] == "default"
    assert metadata["response_id"] == "resp_test"
    assert metadata["input_tokens"] == 31
    assert metadata["cached_input_tokens"] == 11
    assert metadata["cache_write_input_tokens"] == 3
    assert metadata["output_tokens"] == 7
    assert metadata["reasoning_tokens"] == 5
    assert metadata["total_tokens"] == 38
    assert metadata["sdk_version"] == "3.3.1"
    assert metadata["latency_seconds"] >= 0
    assert "stale" not in metadata


def test_frozen_config_is_immutable_secret_free_and_environment_independent(adapter):
    environment = {
        "HIVE_PROVIDER": "openai",
        "HIVE_OPENAI_MODEL": "gpt-5.6-luna",
        "HIVE_REASONING_EFFORT": "medium",
        "HIVE_MAX_OUTPUT_TOKENS": "4096",
        "HIVE_TIMEOUT_SECONDS": "90",
        "HIVE_MAX_ATTEMPTS": "1",
        "OPENAI_API_KEY": "never-record-this-secret",
    }
    config = adapter.freeze_openai_solver_config(environment)
    frozen_mapping = config.to_mapping()
    frozen_hash = config.configuration_hash

    environment["HIVE_OPENAI_MODEL"] = "changed-after-freeze"
    environment["OPENAI_API_KEY"] = "a-different-secret"

    assert config.model == "gpt-5.6-luna"
    assert config.to_mapping() == frozen_mapping
    assert config.configuration_hash == frozen_hash
    serialized = json.dumps(frozen_mapping, sort_keys=True) + repr(config) + frozen_hash
    assert "never-record-this-secret" not in serialized
    assert "a-different-secret" not in serialized
    with pytest.raises(FrozenInstanceError):
        config.model = "mutable"


@pytest.mark.parametrize(
    "environment",
    [
        {"HIVE_PROVIDER": "mystery"},
        {"HIVE_REASONING_EFFORT": "ultra"},
        {"HIVE_MAX_OUTPUT_TOKENS": "0"},
        {"HIVE_MAX_ATTEMPTS": "2"},
        {"HIVE_TOOL_PERMISSIONS": "web"},
        {"HIVE_OPENAI_STORE": "true"},
        {"OPENAI_BASE_URL": "https://example.invalid/v1"},
        {"OPENAI_CUSTOM_HEADERS": '{"X-Test":"not-frozen"}'},
    ],
)
def test_invalid_openai_experiment_settings_fail_closed(adapter, environment):
    with pytest.raises(ValueError):
        adapter.freeze_openai_solver_config(environment)


def test_provider_selection_is_explicit_and_preserves_legacy_routes(adapter, monkeypatch):
    calls = []
    monkeypatch.setattr(
        adapter,
        "ask_model",
        lambda prompt, **kwargs: calls.append(("ollama", prompt, kwargs)) or "local",
    )
    monkeypatch.setattr(
        adapter,
        "_ask_claude",
        lambda prompt, **kwargs: calls.append(("anthropic", prompt, kwargs)) or "claude",
    )

    monkeypatch.setenv("OPENAI_API_KEY", "does-not-enable-openai")
    assert adapter.ask_hive("default") == "local"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key")
    assert adapter.ask_hive("role route", role="coder") == "claude"
    assert adapter.ask_hive("explicit model", role="coder", model="local-test") == "local"

    monkeypatch.setenv("HIVE_PROVIDER", "ollama")
    assert adapter.ask_hive("forced local", role="coder") == "local"
    assert [call[0] for call in calls] == [
        "ollama",
        "anthropic",
        "ollama",
        "ollama",
    ]

    monkeypatch.setenv("HIVE_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unknown HIVE_PROVIDER"):
        adapter.ask_hive("must fail")


def test_openai_transport_error_is_one_attempt_and_never_falls_back(
    adapter, monkeypatch
):
    observed = _install_fake_sdk(
        monkeypatch, adapter, create_error=ConnectionError("offline")
    )
    monkeypatch.setattr(
        adapter,
        "ask_model",
        lambda *args, **kwargs: pytest.fail("must not fall back to Ollama"),
    )
    monkeypatch.setattr(
        adapter,
        "_ask_claude",
        lambda *args, **kwargs: pytest.fail("must not fall back to Anthropic"),
    )
    metadata = {}

    with pytest.raises(RuntimeError, match="OpenAI Responses API error"):
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )

    assert len(observed["requests"]) == 1
    assert observed["client_calls"] == [{"timeout": 120.0, "max_retries": 0}]
    assert metadata["physical_attempts"] == 1
    assert metadata["adapter_status"] == "transport_error"
    assert metadata["error_type"] == "ConnectionError"


@pytest.mark.parametrize("failure_stage", ["sdk", "constructor"])
def test_openai_preflight_failures_record_zero_attempts(adapter, monkeypatch, failure_stage):
    if failure_stage == "sdk":
        def fail_loader():
            raise RuntimeError("SDK unavailable")

        monkeypatch.setattr(adapter, "_load_openai_sdk", fail_loader)
    else:
        class BrokenClient:
            def __init__(self, **kwargs):
                raise ValueError("bad client")

        monkeypatch.setattr(
            adapter,
            "_load_openai_sdk",
            lambda: (SimpleNamespace(__version__="3.3.1"), BrokenClient),
        )
    metadata = {}

    with pytest.raises(RuntimeError):
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )

    assert metadata["physical_attempts"] == 0
    assert metadata["adapter_status"] == "client_error"


@pytest.mark.parametrize("status", ["incomplete", "failed", "queued"])
def test_only_completed_responses_are_admitted(adapter, monkeypatch, status):
    observed = _install_fake_sdk(
        monkeypatch,
        adapter,
        response=_response(status=status, output_text="partial evidence"),
    )
    metadata = {}

    with pytest.raises(RuntimeError, match="OpenAI response rejected"):
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )

    assert len(observed["requests"]) == 1
    assert metadata["physical_attempts"] == 1
    assert metadata["response_status"] == status
    assert metadata["adapter_status"] == "rejected"
    assert metadata["partial_output_text"] == "partial evidence"
    if status == "incomplete":
        assert "max_output_tokens" in str(metadata["incomplete_details"])


@pytest.mark.parametrize(
    "response, reason",
    [
        (_response(output_text="", usage=True), "no output text"),
        (_response(output_text=" \r\n", usage=True), "no output text"),
        (_response(output_text="A", usage=False), "usage accounting is missing"),
    ],
)
def test_completed_but_unusable_responses_fail_closed(
    adapter, monkeypatch, response, reason
):
    _install_fake_sdk(monkeypatch, adapter, response=response)
    metadata = {}
    with pytest.raises(RuntimeError, match=reason):
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )
    assert metadata["physical_attempts"] == 1
    assert metadata["adapter_status"] == "rejected"


@pytest.mark.parametrize(
    "container,field",
    [
        ("input_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cache_write_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    ],
)
def test_missing_detailed_usage_fails_closed(
    adapter, monkeypatch, container, field
):
    response = _response()
    setattr(getattr(response.usage, container), field, None)
    _install_fake_sdk(monkeypatch, adapter, response=response)
    with pytest.raises(RuntimeError, match="detailed usage accounting is missing"):
        adapter._ask_openai("prompt", config=adapter.FrozenSolverConfig())


@pytest.mark.parametrize(
    "container,field,value",
    [
        (None, "input_tokens", True),
        (None, "output_tokens", -1),
        ("input_tokens_details", "cached_tokens", -1),
        ("output_tokens_details", "reasoning_tokens", True),
    ],
)
def test_invalid_usage_counter_types_and_ranges_fail_closed(
    adapter, monkeypatch, container, field, value
):
    response = _response()
    target = response.usage if container is None else getattr(response.usage, container)
    setattr(target, field, value)
    _install_fake_sdk(monkeypatch, adapter, response=response)
    with pytest.raises(RuntimeError, match="invalid usage"):
        adapter._ask_openai("prompt", config=adapter.FrozenSolverConfig())


@pytest.mark.parametrize(
    "container,field,value,reason",
    [
        ("input_tokens_details", "cached_tokens", 32, "cached input tokens exceed"),
        ("input_tokens_details", "cache_write_tokens", 32, "cache-write tokens exceed"),
        ("output_tokens_details", "reasoning_tokens", 8, "reasoning tokens exceed"),
        (None, "total_tokens", 37, "total tokens do not equal"),
    ],
)
def test_incoherent_usage_accounting_fails_closed(
    adapter, monkeypatch, container, field, value, reason
):
    response = _response()
    target = response.usage if container is None else getattr(response.usage, container)
    setattr(target, field, value)
    _install_fake_sdk(monkeypatch, adapter, response=response)
    with pytest.raises(RuntimeError, match=reason):
        adapter._ask_openai("prompt", config=adapter.FrozenSolverConfig())


@pytest.mark.parametrize("contradiction", ["error", "incomplete_details"])
def test_completed_response_with_contradictory_state_fails_closed(
    adapter, monkeypatch, contradiction
):
    response = _response()
    setattr(response, contradiction, {"reason": "contradiction"})
    _install_fake_sdk(monkeypatch, adapter, response=response)
    metadata = {}
    with pytest.raises(RuntimeError, match="OpenAI response rejected"):
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )
    assert metadata["physical_attempts"] == 1
    assert metadata["adapter_status"] == "rejected"


def test_runtime_error_metadata_redacts_openai_credentials(adapter, monkeypatch):
    secret = "sk-test-1234567890abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _install_fake_sdk(
        monkeypatch,
        adapter,
        create_error=ConnectionError(f"Authorization: Bearer {secret}"),
    )
    metadata = {}
    with pytest.raises(RuntimeError) as raised:
        adapter._ask_openai(
            "prompt", config=adapter.FrozenSolverConfig(), metadata=metadata
        )
    rendered_traceback = "".join(
        traceback.format_exception(raised.type, raised.value, raised.tb)
    )
    recorded = json.dumps(metadata, sort_keys=True) + rendered_traceback
    assert secret not in recorded
    assert "[REDACTED_OPENAI_KEY]" in recorded


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENAI_BASE_URL", "https://example.invalid/v1"),
        ("OPENAI_CUSTOM_HEADERS", '{"X-Route":"alternate"}'),
    ],
)
def test_ambient_transport_change_after_freeze_fails_before_client(
    adapter, monkeypatch, name, value
):
    config = adapter.FrozenSolverConfig()
    observed = _install_fake_sdk(monkeypatch, adapter)
    monkeypatch.setenv(name, value)
    metadata = {}
    with pytest.raises(ValueError, match="unfrozen OpenAI transport override"):
        adapter._ask_openai("prompt", config=config, metadata=metadata)
    assert observed["client_calls"] == []
    assert observed["requests"] == []
    assert metadata["physical_attempts"] == 0
    assert metadata["adapter_status"] == "configuration_error"


@pytest.mark.parametrize(
    "unsupported",
    [
        {"options": {"temperature": 0}},
        {"response_format": {"type": "json"}},
    ],
)
def test_openai_rejects_foreign_request_settings_before_call(
    adapter, monkeypatch, unsupported
):
    observed = _install_fake_sdk(monkeypatch, adapter)
    metadata = {}
    with pytest.raises(ValueError):
        adapter._ask_openai(
            "prompt",
            config=adapter.FrozenSolverConfig(),
            metadata=metadata,
            **unsupported,
        )
    assert observed["client_calls"] == []
    assert observed["requests"] == []
    assert metadata["physical_attempts"] == 0
    assert metadata["adapter_status"] == "configuration_error"


def test_openai_strict_text_format_is_forwarded_and_hashed(adapter, monkeypatch):
    observed = _install_fake_sdk(monkeypatch, adapter)
    text_format = {
        "type": "json_schema",
        "name": "hive_labels_3",
        "schema": {
            "type": "array",
            "items": {"type": "string", "enum": ["A", "B"]},
            "minItems": 3,
            "maxItems": 3,
        },
        "strict": True,
    }
    metadata = {}

    assert adapter.ask_hive(
        "prompt",
        solver_config=adapter.FrozenSolverConfig(),
        metadata=metadata,
        openai_text_format=text_format,
    ) == "A"

    assert observed["requests"][0]["text"] == {"format": text_format}
    assert metadata["openai_text_format"] == text_format
    assert metadata["openai_text_format_sha256"] == adapter.hashlib.sha256(
        adapter.json.dumps(
            text_format,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize(
    "bad_format",
    [
        {"type": "json_schema", "name": "x", "schema": {}, "strict": False},
        {"type": "json_schema", "name": "bad name", "schema": {}, "strict": True},
        {"type": "json_schema", "name": "x", "schema": {}},
    ],
)
def test_invalid_openai_text_format_fails_before_call(
    adapter, monkeypatch, bad_format
):
    observed = _install_fake_sdk(monkeypatch, adapter)
    metadata = {}
    with pytest.raises(ValueError):
        adapter._ask_openai(
            "prompt",
            config=adapter.FrozenSolverConfig(),
            metadata=metadata,
            openai_text_format=bad_format,
        )
    assert observed["requests"] == []
    assert metadata["physical_attempts"] == 0
    assert metadata["adapter_status"] == "configuration_error"


def test_explicit_frozen_config_rejects_mutable_overrides(adapter, monkeypatch):
    _install_fake_sdk(monkeypatch, adapter)
    config = adapter.FrozenSolverConfig()
    with pytest.raises(ValueError, match="cannot be combined"):
        adapter.ask_hive("prompt", solver_config=config, timeout=30)
    monkeypatch.setenv("HIVE_PROVIDER", "ollama")
    with pytest.raises(ValueError, match="conflicts"):
        adapter.ask_hive("prompt", solver_config=config)
