from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

import requests

from grow.core import ExperimentInvalid, ModelConfig


class FixedOllamaInvoker:
    """Ollama adapter that makes inference settings explicit and auditable."""

    def __init__(self, config: ModelConfig, *, base_url: str = "http://localhost:11434"):
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.calls = 0
        self.input_chars = 0
        self.output_chars = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.wall_time = 0.0
        self._verify_model_digest()

    def _verify_model_digest(self) -> None:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models") or []
        except Exception as exc:
            raise ExperimentInvalid(f"fixed base model unavailable: {exc}") from exc
        match = next((item for item in models if item.get("name") == self.config.identity), None)
        if not match:
            raise ExperimentInvalid(f"configured model not installed: {self.config.identity}")
        digest = str(match.get("digest") or "")
        if digest != self.config.digest:
            raise ExperimentInvalid(
                f"model digest changed: expected {self.config.digest}, observed {digest or '<missing>'}"
            )

    def invoke(self, prompt: str) -> str:
        if self.calls >= self.config.max_calls_per_case:
            raise ExperimentInvalid("fixed model call budget exhausted")
        payload = {
            "model": self.config.identity,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "seed": self.config.seed,
                "num_ctx": self.config.context_tokens,
                "num_predict": self.config.max_output_tokens,
            },
        }
        start = time.perf_counter()
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=180)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ExperimentInvalid(f"model invocation failed: {exc}") from exc
        elapsed = time.perf_counter() - start
        output = str(data.get("response") or "")
        self.calls += 1
        self.input_tokens += int(data.get("prompt_eval_count") or 0)
        self.output_tokens += int(data.get("eval_count") or 0)
        self.input_chars += len(prompt)
        self.output_chars += len(output)
        self.wall_time += elapsed
        return output

    def metrics(self) -> dict[str, Any]:
        return {
            "model_calls": self.calls,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time": self.wall_time,
            "model_config": asdict(self.config),
        }
