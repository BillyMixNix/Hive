from __future__ import annotations

import requests


class OpenAIChatClient:
    """Small callable adapter for a local OpenAI-compatible chat endpoint."""

    def __init__(self, url, model, *, timeout=180):
        self.url = url
        self.model = model
        self.timeout = timeout

    def __call__(self, prompt, role="default"):
        response = requests.post(
            self.url,
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 256,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
