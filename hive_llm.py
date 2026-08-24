import os
import requests
import time

OLLAMA_URL = "http://localhost:11434/api/generate"


class CreditsExhaustedError(RuntimeError):
    """Raised when the Anthropic API refuses a request due to insufficient credits."""
    pass

# Default model used by Hive
DEFAULT_MODEL = "qwen2.5-coder:7b"
CLAUDE_MODEL = "claude-opus-4-7"

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
    )


def ask_model(
    prompt,
    model=None,
    timeout=120,
    options=None,
    max_retries=None,
    metadata=None,
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
