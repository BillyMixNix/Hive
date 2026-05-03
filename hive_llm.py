import requests
import time

OLLAMA_URL = "http://localhost:11434/api/generate"

# Default model used by Hive
DEFAULT_MODEL = "qwen2.5-coder:7b"

# Retry configuration
_MAX_RETRIES = 3
_RETRY_BASE_WAIT = 2  # seconds — doubles each attempt: 2, 4, 8

# ---------------------------------------------------------------------------
# Role-aware model routing
#
# Each agent role maps to a model and default timeout.
# To upgrade math/strategic agents to a stronger model:
#   change ROLE_MODEL['math'] = 'your-stronger-model'
# All other roles continue using the local fast model.
# ---------------------------------------------------------------------------

ROLE_MODEL = {
    "coder":      DEFAULT_MODEL,
    "planner":    DEFAULT_MODEL,
    "reflector":  DEFAULT_MODEL,
    "builder":    DEFAULT_MODEL,
    "math":       DEFAULT_MODEL,  # swap to stronger model when available
    "strategic":  DEFAULT_MODEL,  # swap to stronger model when available
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


def ask_hive(prompt, role="default", timeout=None, model=None):
    """
    Role-aware LLM interface for all Hive agents.

    Use this instead of ask_model() for new code.
    Existing ask_model() calls continue to work unchanged.

    role: 'coder' | 'planner' | 'reflector' | 'math' | 'strategic' | 'default'
    timeout: override default role timeout
    model: override role model (for testing)
    """
    resolved_model   = model   or ROLE_MODEL.get(role,   DEFAULT_MODEL)
    resolved_timeout = timeout or ROLE_TIMEOUT.get(role, 120)
    return ask_model(prompt, model=resolved_model, timeout=resolved_timeout)


def ask_model(prompt, model=None, timeout=120):
    model = model or DEFAULT_MODEL

    print(f"[LLM] Sending request to {model}")
    print(f"[LLM] Prompt length: {len(prompt)} chars")

    last_error = None

    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            wait = _RETRY_BASE_WAIT * (2 ** (attempt - 1))
            print(f"[LLM] Retry {attempt}/{_MAX_RETRIES - 1} after {wait}s wait...")
            time.sleep(wait)

        start = time.time()

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=timeout,
            )

            elapsed = time.time() - start
            print(f"[LLM] Response received in {elapsed:.2f}s with status {response.status_code}")

            response.raise_for_status()
            data = response.json()

            if "response" not in data:
                raise ValueError(f"Ollama response missing 'response': {data}")

            print(f"[LLM] Model output length: {len(data['response'])} chars")
            return data["response"]

        except requests.exceptions.Timeout as e:
            last_error = TimeoutError(f"Ollama request timed out after {timeout} seconds.")
            print(f"[LLM] Timeout on attempt {attempt + 1}/{_MAX_RETRIES}")

        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Ollama request failed: {e}")
            print(f"[LLM] Request error on attempt {attempt + 1}/{_MAX_RETRIES}: {e}")

    raise last_error or RuntimeError(f"ask_model failed after {_MAX_RETRIES} attempts.")