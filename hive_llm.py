import requests
import time

OLLAMA_URL = "http://localhost:11434/api/generate"

# Default model used by Hive
DEFAULT_MODEL = "qwen2.5-coder:7b"

def ask_model(prompt, model=None, timeout=120):
    model = model or DEFAULT_MODEL

    print(f"[LLM] Sending request to {model}")
    print(f"[LLM] Prompt length: {len(prompt)} chars")

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

    except requests.exceptions.Timeout:
        raise TimeoutError(f"Ollama request timed out after {timeout} seconds.")

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}")