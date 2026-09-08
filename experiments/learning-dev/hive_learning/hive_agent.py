"""Jarvis custom connector. JSON request on stdin, evidence on stdout."""
import json
import os
from pathlib import Path
import sys

from .adapter import OllamaHive
from .evaluate import strict_json


def main():
    request = strict_json(sys.stdin.read(100_001))
    if (request.get("contract_version") != 1 or request.get("mutating") is not True
            or request.get("approval") != "APPROVED"):
        raise ValueError("Hive connector requires an approved mutating Jarvis task")
    root = Path(request["workspace"]).resolve()
    if root != Path.cwd().resolve():
        raise ValueError("workspace must equal connector working directory")
    provider = os.environ.get("HIVE_PROVIDER", "ollama")
    if provider == "openai":
        from .openai_adapter import OpenAIHive, load_api_key
        # Jarvis passes only explicitly allowed variables to a custom connector.
        # Capture and remove the credential before Hive runs any repository tests.
        adapter = OpenAIHive(os.environ.get("HIVE_MODEL"), load_api_key(),
                             max_requests=36,
                             max_output_tokens=int(os.environ.get("HIVE_MAX_OUTPUT_TOKENS", "4096")))
    elif provider == "ollama":
        adapter = OllamaHive(os.environ.get("HIVE_MODEL", "qwen2.5-coder:7b"),
                            os.environ.get("HIVE_OLLAMA_URL", "http://localhost:11434/api/chat"))
    else:
        raise ValueError("HIVE_PROVIDER must be ollama or openai")
    usage, evidence = adapter.work(root, request["goal"], request.get("lessons", []), 36)
    print(json.dumps({"schema": "hive.jarvis.failure-evidence.v1", "usage": usage, **evidence}))
    return 0 if evidence["decision"] == "SATISFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
