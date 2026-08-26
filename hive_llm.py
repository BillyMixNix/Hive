from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import re
import time

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


class CreditsExhaustedError(RuntimeError):
    """Raised when the Anthropic API refuses a request due to insufficient credits."""
    pass

# Default model used by Hive
DEFAULT_MODEL = "qwen2.5-coder:7b"
CLAUDE_MODEL = "claude-opus-4-7"
OPENAI_MODEL = "gpt-5.6-luna"
OPENAI_REASONING_EFFORT = "medium"
OPENAI_MAX_OUTPUT_TOKENS = 4096
OPENAI_REASONING_EFFORTS = frozenset(
    {"none", "low", "medium", "high", "xhigh", "max"}
)
OPENAI_UNFROZEN_TRANSPORT_ENV = ("OPENAI_BASE_URL", "OPENAI_CUSTOM_HEADERS")

# Retry configuration
_MAX_RETRIES = 3
_RETRY_BASE_WAIT = 2  # seconds — doubles each attempt: 2, 4, 8

# ---------------------------------------------------------------------------
# Role-aware model routing
#
# Roles listed in CLAUDE_ROLES are sent to the Claude API when
# ANTHROPIC_API_KEY is set in the environment; all others use Ollama.
# Passing model= explicitly bypasses this routing entirely.
# ---------------------------------------------------------------------------

CLAUDE_ROLES = {"reflector", "math", "strategic", "planner", "coder"}

# Per-role Claude model overrides.
# Planner and coder use Sonnet (5x cheaper, sufficient for code tasks).
# Reflector, math, strategic keep Opus for quality of judgment.
CLAUDE_ROLE_MODEL = {
    "planner":   "claude-sonnet-4-6",
    "coder":     "claude-sonnet-4-6",
    "reflector": "claude-opus-4-7",
    "math":      "claude-opus-4-7",
    "strategic": "claude-opus-4-7",
}

ROLE_MODEL = {
    "coder":      DEFAULT_MODEL,
    "planner":    DEFAULT_MODEL,
    "reflector":  DEFAULT_MODEL,
    "builder":    DEFAULT_MODEL,
    "math":       DEFAULT_MODEL,
    "strategic":  DEFAULT_MODEL,
    "default":    DEFAULT_MODEL,
}

ROLE_TIMEOUT = {
    "coder":      180,  # patch generation needs more time
    "planner":    120,
    "reflector":  120,
    "builder":    120,
    "math":       240,  # symbolic/formal work can be slow
    "strategic":  180,
    "default":    120,
}


@dataclass(frozen=True)
class FrozenSolverConfig:
    """Immutable, serializable settings for one matched OpenAI solver call."""

    provider: str = "openai"
    model: str = OPENAI_MODEL
    reasoning_effort: str = OPENAI_REASONING_EFFORT
    max_output_tokens: int = OPENAI_MAX_OUTPUT_TOKENS
    timeout_seconds: float = 120.0
    max_attempts: int = 1
    tool_permissions: tuple = ()
    store: bool = False
    truncation: str = "disabled"
    reasoning_context: str = "current_turn"

    def __post_init__(self):
        if self.provider != "openai":
            raise ValueError("FrozenSolverConfig currently supports provider='openai' only")
        if not isinstance(self.model, str) or not self.model or self.model.strip() != self.model:
            raise ValueError("model must be a non-empty canonical model ID")
        if self.reasoning_effort not in OPENAI_REASONING_EFFORTS:
            allowed = ", ".join(sorted(OPENAI_REASONING_EFFORTS))
            raise ValueError(f"reasoning_effort must be one of: {allowed}")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts != 1
        ):
            raise ValueError("OpenAI experiments require exactly one physical attempt")
        if not isinstance(self.tool_permissions, tuple):
            raise ValueError("tool_permissions must be an immutable tuple")
        if self.tool_permissions:
            raise ValueError("the current OpenAI adapter permits no tools")
        if self.store is not False:
            raise ValueError("the frozen OpenAI adapter requires store=False")
        if self.truncation != "disabled":
            raise ValueError("the frozen OpenAI adapter requires truncation='disabled'")
        if self.reasoning_context != "current_turn":
            raise ValueError(
                "the frozen OpenAI adapter requires reasoning_context='current_turn'"
            )

    def to_mapping(self):
        """Return the canonical, secret-free experiment configuration."""
        result = asdict(self)
        result["tool_permissions"] = list(self.tool_permissions)
        result.update(
            {
                "api": "responses",
                "provider_fallback": False,
                "sdk_max_retries": 0,
            }
        )
        return result

    @property
    def configuration_hash(self):
        encoded = json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _positive_int(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed < 1 or str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _positive_float(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _false_only(value, name):
    if isinstance(value, bool):
        parsed = value
    elif isinstance(value, str) and value.strip().lower() in {"0", "false", "no"}:
        parsed = False
    elif isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}:
        parsed = True
    else:
        raise ValueError(f"{name} must be false")
    if parsed:
        raise ValueError(f"{name} must be false")
    return False


def _reject_unfrozen_openai_transport(environ=None):
    env = os.environ if environ is None else environ
    configured = [
        name for name in OPENAI_UNFROZEN_TRANSPORT_ENV if str(env.get(name, "")).strip()
    ]
    if configured:
        raise ValueError(
            "unfrozen OpenAI transport override(s) are not permitted: "
            + ", ".join(configured)
        )


def _safe_error_message(exc, environ=None):
    """Retain useful transport evidence without persisting credentials."""
    env = os.environ if environ is None else environ
    message = str(exc)
    api_key = str(env.get("OPENAI_API_KEY", ""))
    if api_key:
        message = message.replace(api_key, "[REDACTED_OPENAI_KEY]")
    message = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED_OPENAI_KEY]",
        message,
    )
    message = re.sub(
        r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED_OPENAI_KEY]", message
    )
    return message[:4096]


def freeze_openai_solver_config(
    environ=None,
    *,
    model=None,
    timeout_seconds=None,
    max_attempts=None,
    default_timeout=120,
):
    """Snapshot the OpenAI experimental settings without retaining credentials."""
    env = os.environ if environ is None else environ
    declared_provider = str(env.get("HIVE_PROVIDER", "")).strip().lower()
    if declared_provider not in {"", "openai"}:
        raise ValueError(
            "freeze_openai_solver_config requires HIVE_PROVIDER=openai when set"
        )
    _reject_unfrozen_openai_transport(env)

    resolved_model = model or str(env.get("HIVE_OPENAI_MODEL", OPENAI_MODEL)).strip()
    reasoning_effort = str(
        env.get("HIVE_REASONING_EFFORT", OPENAI_REASONING_EFFORT)
    ).strip().lower()
    max_output_tokens = _positive_int(
        env.get("HIVE_MAX_OUTPUT_TOKENS", OPENAI_MAX_OUTPUT_TOKENS),
        "HIVE_MAX_OUTPUT_TOKENS",
    )
    resolved_timeout = _positive_float(
        timeout_seconds
        if timeout_seconds is not None
        else env.get("HIVE_TIMEOUT_SECONDS", default_timeout),
        "HIVE_TIMEOUT_SECONDS",
    )
    resolved_attempts = _positive_int(
        max_attempts
        if max_attempts is not None
        else env.get("HIVE_MAX_ATTEMPTS", 1),
        "HIVE_MAX_ATTEMPTS",
    )
    permissions_text = str(env.get("HIVE_TOOL_PERMISSIONS", "")).strip()
    tool_permissions = tuple(
        item.strip() for item in permissions_text.split(",") if item.strip()
    )
    store = _false_only(env.get("HIVE_OPENAI_STORE", "false"), "HIVE_OPENAI_STORE")

    return FrozenSolverConfig(
        model=resolved_model,
        reasoning_effort=reasoning_effort,
        max_output_tokens=max_output_tokens,
        timeout_seconds=resolved_timeout,
        max_attempts=resolved_attempts,
        tool_permissions=tool_permissions,
        store=store,
    )


def _load_openai_sdk():
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed. Run: pip install -r requirements.txt"
        ) from exc
    return openai, openai.OpenAI


def _field(value, name, default=None):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _optional_nonnegative_int(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"OpenAI response contains invalid {name}")
    return value


def _metadata_value(value):
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def _ask_openai(
    prompt,
    *,
    system=None,
    config,
    metadata=None,
    options=None,
    response_format=None,
):
    """Make one fail-closed Responses API call with no retries or fallback."""
    if not isinstance(config, FrozenSolverConfig):
        raise TypeError("config must be a FrozenSolverConfig")

    if metadata is not None:
        metadata.clear()
        metadata.update(config.to_mapping())
        metadata.update(
            {
                "configuration_hash": config.configuration_hash,
                "requested_model": config.model,
                "returned_model": None,
                "response_id": None,
                "response_status": None,
                "physical_attempts": 0,
                "latency_seconds": None,
                "input_tokens": None,
                "cached_input_tokens": None,
                "cache_write_input_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": None,
                "total_tokens": None,
                "sdk_version": None,
                "adapter_status": "not_started",
            }
        )

    if options:
        if metadata is not None:
            metadata["adapter_status"] = "configuration_error"
        raise ValueError("Ollama options are not supported by the OpenAI adapter")
    if response_format is not None:
        if metadata is not None:
            metadata["adapter_status"] = "configuration_error"
        raise ValueError(
            "response_format is Ollama-specific and is not supported by the OpenAI adapter"
        )

    try:
        _reject_unfrozen_openai_transport()
    except ValueError as exc:
        if metadata is not None:
            metadata.update(
                {
                    "adapter_status": "configuration_error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
        raise

    try:
        openai_module, client_class = _load_openai_sdk()
        if metadata is not None:
            metadata["sdk_version"] = getattr(openai_module, "__version__", None)
        client = client_class(timeout=float(config.timeout_seconds), max_retries=0)
    except Exception as exc:
        if metadata is not None:
            metadata.update(
                {
                    "adapter_status": "client_error",
                    "error_type": type(exc).__name__,
                    "error_message": _safe_error_message(exc),
                }
            )
        safe_message = _safe_error_message(exc)
        raise RuntimeError(f"OpenAI client initialization failed: {safe_message}") from None

    request = {
        "model": config.model,
        "input": prompt,
        "reasoning": {
            "effort": config.reasoning_effort,
            "context": config.reasoning_context,
        },
        "max_output_tokens": config.max_output_tokens,
        "tools": [],
        "store": config.store,
        "truncation": config.truncation,
    }
    if system is not None:
        request["instructions"] = system

    start = time.perf_counter()
    if metadata is not None:
        metadata["physical_attempts"] = 1
        metadata["adapter_status"] = "in_flight"
    try:
        response = client.responses.create(**request)
    except Exception as exc:
        elapsed = time.perf_counter() - start
        if metadata is not None:
            metadata.update(
                {
                    "adapter_status": "transport_error",
                    "latency_seconds": elapsed,
                    "error_type": type(exc).__name__,
                    "error_message": _safe_error_message(exc),
                }
            )
        safe_message = _safe_error_message(exc)
        raise RuntimeError(f"OpenAI Responses API error: {safe_message}") from None

    elapsed = time.perf_counter() - start
    status = _field(response, "status")
    output_text = _field(response, "output_text")
    usage = _field(response, "usage")
    input_details = _field(usage, "input_tokens_details")
    output_details = _field(usage, "output_tokens_details")

    try:
        input_tokens = _optional_nonnegative_int(
            _field(usage, "input_tokens"), "usage.input_tokens"
        )
        cached_tokens = _optional_nonnegative_int(
            _field(input_details, "cached_tokens"),
            "usage.input_tokens_details.cached_tokens",
        )
        cache_write_tokens = _optional_nonnegative_int(
            _field(input_details, "cache_write_tokens"),
            "usage.input_tokens_details.cache_write_tokens",
        )
        output_tokens = _optional_nonnegative_int(
            _field(usage, "output_tokens"), "usage.output_tokens"
        )
        reasoning_tokens = _optional_nonnegative_int(
            _field(output_details, "reasoning_tokens"),
            "usage.output_tokens_details.reasoning_tokens",
        )
        total_tokens = _optional_nonnegative_int(
            _field(usage, "total_tokens"), "usage.total_tokens"
        )
    except RuntimeError as exc:
        if metadata is not None:
            metadata.update(
                {
                    "adapter_status": "invalid_response",
                    "response_status": status,
                    "latency_seconds": elapsed,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
        raise

    response_id = _field(response, "id")
    returned_model = _field(response, "model")
    incomplete_details = _field(response, "incomplete_details")
    response_error = _field(response, "error")

    if metadata is not None:
        metadata.update(
            {
                "returned_model": returned_model,
                "response_id": response_id,
                "response_status": status,
                "latency_seconds": elapsed,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "cache_write_input_tokens": cache_write_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
                "incomplete_details": _metadata_value(incomplete_details),
                "response_error": _metadata_value(response_error),
            }
        )

    rejection_reason = None
    if status != "completed":
        rejection_reason = f"response status is {status!r}, not 'completed'"
    elif response_error is not None:
        rejection_reason = "completed response contains an error object"
    elif incomplete_details is not None:
        rejection_reason = "completed response contains incomplete details"
    elif not isinstance(response_id, str) or not response_id:
        rejection_reason = "response ID is missing"
    elif not isinstance(returned_model, str) or not returned_model:
        rejection_reason = "returned model ID is missing"
    elif input_tokens is None or output_tokens is None or total_tokens is None:
        rejection_reason = "core usage accounting is missing"
    elif cached_tokens is None or cache_write_tokens is None or reasoning_tokens is None:
        rejection_reason = "detailed usage accounting is missing"
    elif cached_tokens > input_tokens:
        rejection_reason = "cached input tokens exceed total input tokens"
    elif cache_write_tokens > input_tokens:
        rejection_reason = "cache-write tokens exceed total input tokens"
    elif reasoning_tokens > output_tokens:
        rejection_reason = "reasoning tokens exceed total output tokens"
    elif total_tokens != input_tokens + output_tokens:
        rejection_reason = "total tokens do not equal input plus output tokens"
    elif not isinstance(output_text, str) or output_text.strip() == "":
        rejection_reason = "completed response has no output text"

    if rejection_reason is not None:
        if metadata is not None:
            metadata.update(
                {
                    "adapter_status": "rejected",
                    "partial_output_text": output_text,
                    "error_type": "OpenAIResponseRejected",
                    "error_message": rejection_reason,
                }
            )
        raise RuntimeError(f"OpenAI response rejected: {rejection_reason}")

    if metadata is not None:
        metadata["adapter_status"] = "completed"
    return output_text


def _ask_claude(prompt, system=None, model=None, timeout=120):
    """
    Call Claude API for roles that benefit from stronger reasoning.

    system: stable system-prompt text; cached with ephemeral cache_control
            so repeated calls with the same system don't re-bill full tokens.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    resolved_model = model or CLAUDE_MODEL
    print(f"[LLM] Sending request to Claude ({resolved_model})")
    print(f"[LLM] Prompt length: {len(prompt)} chars")

    client = anthropic.Anthropic(timeout=float(timeout))
    start = time.time()

    kwargs = {
        "model": resolved_model,
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "messages": [{"role": "user", "content": prompt}],
    }

    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    try:
        response = client.messages.create(**kwargs)
    except Exception as exc:
        exc_text = str(exc).lower()
        if "credit balance" in exc_text or "too low" in exc_text:
            raise CreditsExhaustedError(
                "Anthropic API credits exhausted. Restore credits before retrying this task."
            ) from exc
        raise RuntimeError(f"Claude API error: {exc}") from exc
    elapsed = time.time() - start

    text = next(
        (block.text for block in response.content if hasattr(block, "text")),
        "",
    )
    print(f"[LLM] Claude response received in {elapsed:.2f}s, {len(text)} chars")
    return text


def ask_hive(
    prompt,
    role="default",
    timeout=None,
    model=None,
    system=None,
    options=None,
    max_retries=None,
    metadata=None,
    response_format=None,
    solver_config=None,
):
    """
    Role-aware LLM interface for all Hive agents.

    Use this instead of ask_model() for new code.
    Existing ask_model() calls continue to work unchanged.

    role:    'coder' | 'planner' | 'reflector' | 'math' | 'strategic' | 'default'
    timeout: override default role timeout
    model:   override role model entirely (bypasses Claude routing)
    system:  stable system-prompt for Claude roles; cached to save tokens
    """
    resolved_timeout = timeout or ROLE_TIMEOUT.get(role, 120)
    declared_provider = str(os.environ.get("HIVE_PROVIDER", "")).strip().lower()
    if declared_provider not in {"", "openai", "ollama", "anthropic"}:
        raise ValueError(f"Unknown HIVE_PROVIDER: {declared_provider!r}")

    if solver_config is not None:
        if not isinstance(solver_config, FrozenSolverConfig):
            raise TypeError("solver_config must be a FrozenSolverConfig")
        if declared_provider and declared_provider != solver_config.provider:
            raise ValueError("HIVE_PROVIDER conflicts with the frozen solver_config")
        conflicts = {
            "timeout": timeout,
            "model": model,
            "options": options,
            "max_retries": max_retries,
            "response_format": response_format,
        }
        supplied = [name for name, value in conflicts.items() if value is not None]
        if supplied:
            raise ValueError(
                "frozen solver_config cannot be combined with: " + ", ".join(supplied)
            )
        return _ask_openai(
            prompt,
            system=system,
            config=solver_config,
            metadata=metadata,
        )

    if declared_provider == "openai":
        try:
            config = freeze_openai_solver_config(
                model=model,
                timeout_seconds=timeout,
                max_attempts=max_retries,
                default_timeout=ROLE_TIMEOUT.get(role, 120),
            )
        except Exception as exc:
            if metadata is not None:
                metadata.clear()
                metadata.update(
                    {
                        "provider": "openai",
                        "physical_attempts": 0,
                        "adapter_status": "configuration_error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
            raise
        return _ask_openai(
            prompt,
            system=system,
            config=config,
            metadata=metadata,
            options=options,
            response_format=response_format,
        )

    if declared_provider == "anthropic":
        if options is not None or max_retries is not None or response_format is not None:
            raise ValueError(
                "explicit Anthropic routing does not support options, max_retries, "
                "or response_format"
            )
        claude_model = model or CLAUDE_ROLE_MODEL.get(role, CLAUDE_MODEL)
        return _ask_claude(
            prompt, system=system, model=claude_model, timeout=resolved_timeout
        )

    if declared_provider == "ollama":
        resolved_model = model or ROLE_MODEL.get(role, DEFAULT_MODEL)
        return ask_model(
            prompt,
            model=resolved_model,
            timeout=resolved_timeout,
            options=options,
            max_retries=max_retries,
            metadata=metadata,
            response_format=response_format,
        )

    # Route to Claude when the role calls for it and the API key is available.
    # An explicit model= override skips this path so callers can force Ollama.
    if model is None and role in CLAUDE_ROLES and os.environ.get("ANTHROPIC_API_KEY"):
        claude_model = CLAUDE_ROLE_MODEL.get(role, CLAUDE_MODEL)
        return _ask_claude(prompt, system=system, model=claude_model, timeout=resolved_timeout)

    resolved_model = model or ROLE_MODEL.get(role, DEFAULT_MODEL)
    return ask_model(
        prompt,
        model=resolved_model,
        timeout=resolved_timeout,
        options=options,
        max_retries=max_retries,
        metadata=metadata,
        response_format=response_format,
    )


def ask_model(
    prompt,
    model=None,
    timeout=120,
    options=None,
    max_retries=None,
    metadata=None,
    response_format=None,
):
    model = model or DEFAULT_MODEL
    attempts = _MAX_RETRIES if max_retries is None else int(max_retries)
    if attempts < 1:
        raise ValueError("max_retries must be at least 1")

    print(f"[LLM] Sending request to {model}")
    print(f"[LLM] Prompt length: {len(prompt)} chars")

    last_error = None

    for attempt in range(attempts):
        if attempt > 0:
            wait = _RETRY_BASE_WAIT * (2 ** (attempt - 1))
            print(f"[LLM] Retry {attempt}/{attempts - 1} after {wait}s wait...")
            time.sleep(wait)

        start = time.time()

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
            if options:
                payload["options"] = dict(options)
            if response_format is not None:
                payload["format"] = response_format
            response = requests.post(
                OLLAMA_URL,
                json=payload,
                timeout=timeout,
            )

            elapsed = time.time() - start
            print(f"[LLM] Response received in {elapsed:.2f}s with status {response.status_code}")

            response.raise_for_status()
            data = response.json()

            if "response" not in data:
                raise ValueError(f"Ollama response missing 'response': {data}")

            if metadata is not None:
                metadata.clear()
                metadata.update(
                    {
                        "physical_attempts": attempt + 1,
                        "done": bool(data.get("done", False)),
                        "done_reason": data.get("done_reason"),
                        "prompt_eval_count": (
                            None
                            if data.get("prompt_eval_count") is None
                            else int(data["prompt_eval_count"])
                        ),
                        "eval_count": (
                            None
                            if data.get("eval_count") is None
                            else int(data["eval_count"])
                        ),
                        "total_duration_ns": (
                            None
                            if data.get("total_duration") is None
                            else int(data["total_duration"])
                        ),
                        "response_format": response_format,
                    }
                )

            print(f"[LLM] Model output length: {len(data['response'])} chars")
            return data["response"]

        except requests.exceptions.Timeout as e:
            last_error = TimeoutError(f"Ollama request timed out after {timeout} seconds.")
            print(f"[LLM] Timeout on attempt {attempt + 1}/{attempts}")

        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Ollama request failed: {e}")
            print(f"[LLM] Request error on attempt {attempt + 1}/{attempts}: {e}")

    if metadata is not None:
        metadata.clear()
        metadata["physical_attempts"] = attempts
        metadata["done"] = False
        metadata["done_reason"] = "transport_error"
    raise last_error or RuntimeError(f"ask_model failed after {attempts} attempts.")
