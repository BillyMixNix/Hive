
from dataclasses import dataclass

PRICES = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (4.00, 20.00),
    "gpt-6-astra": (10.00, 50.00),
}

@dataclass
class Route:
    provider: str
    model: str
    reason: str

def estimate_cost(model, input_tokens, output_tokens):
    p = PRICES.get(model)
    if not p:
        return 0.0
    return (input_tokens / 1_000_000 * p[0]) + (output_tokens / 1_000_000 * p[1])

def choose(mode, manual_model, ollama_ok, local_model, web_enabled=False):
    if mode == "local":
        return Route("ollama", local_model, "Local mode forced by user.")
    if mode == "manual":
        if manual_model.startswith("local:"):
            return Route("ollama", manual_model.split(":",1)[1] or local_model, "Manual local model.")
        return Route("openai", manual_model, "Manual cloud model.")
    # AUTO: hosted tools currently require the cloud adapter.
    if web_enabled:
        return Route("openai", "gpt-5.6-luna", "Web search requested; using cheapest configured OpenAI text tier.")
    if ollama_ok:
        return Route("ollama", local_model, "AUTO local-first: zero API-token cost.")
    return Route("openai", "gpt-5.6-luna", "No local runtime detected; using cheapest OpenAI text tier.")
