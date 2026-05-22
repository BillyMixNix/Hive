import copy
import torch
import torch.nn as nn
import random


class HiveAgent(nn.Module):
    def __init__(self, name, model, feature_fn, output_fn, optimizer=None, loss_fn=None):
        super().__init__()
        self.name = name
        self.model = model
        self.feature_fn = feature_fn
        self.output_fn = output_fn
        self.optimizer = optimizer
        self.loss_fn = loss_fn
        self.history = []
        self._last_input = None

    def process(self, images):
        self.model.train()
        self._last_input = images
        features = self.feature_fn(images)
        outputs = self.output_fn(features)
        return features, outputs

    def receive_feedback(self, refined_features):
        self.history.append(refined_features.detach().cpu())

        if self.optimizer is not None and self._last_input is not None:
            import torch.nn.functional as F
            self.model.train()
            current_features = self.feature_fn(self._last_input)
            loss = F.mse_loss(current_features, refined_features.to(current_features.device))
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
    
    def extract_features(self, x):
        if self.name == "vision":
            x = self.model.conv1(x)
            x = self.model.bn1(x)
            x = self.model.relu(x)
            x = self.model.maxpool(x)
            x = self.model.layer1(x)
            x = self.model.layer2(x)
            x = self.model.layer3(x)
            x = self.model.layer4(x)
            x = self.model.avgpool(x)
            return torch.flatten(x, 1)
        elif self.name == "transformer":
            return self.model.forward_features(x)[:, 0]
    
    def forward(self, x):
        return self.output_fn(self.feature_fn(x))

    def mutate(self, mutation_rate=0.01):
        """Return a mutated copy of the agent."""
        mutated = copy.deepcopy(self)
        with torch.no_grad():
            for param in mutated.model.parameters():
                noise = torch.randn_like(param) * mutation_rate
                param.add_(noise)
        return mutated

    def respond(self, prompt):
        from transformers import DistilBertTokenizer
        tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")

        inputs = tokenizer([prompt], return_tensors="pt", padding=True, truncation=True)
        input_ids = inputs["input_ids"].to(self.model.device)
        attention_mask = inputs["attention_mask"].to(self.model.device)

        with torch.no_grad():
            output = self.output_fn(self.feature_fn((input_ids, attention_mask)))

        return f"<latent_vector_mean: {output.mean().item():.4f}>"


# ---------------------------------------------------------------------------
# MathResearchAgent
# ---------------------------------------------------------------------------

class MathResearchAgent:
    """
    Base class for Hive's mathematical research agents.

    Each specialization implements `run(context)` and returns a structured
    result that the reflector can evaluate for rigor and falsifiability.

    Roles:
    - exploratory: search for numerical patterns
    - symbolic:    transform patterns into algebra
    - adversarial: hunt for counterexamples
    - formal:      produce verifiable proof fragments
    - strategic:   evaluate proof architecture
    """

    VALID_ROLES = {"exploratory", "symbolic", "adversarial", "formal", "strategic"}

    def __init__(self, role: str, llm_fn=None):
        if role not in self.VALID_ROLES:
            raise ValueError(f"Invalid MathResearchAgent role '{role}'. Must be one of {self.VALID_ROLES}")
        self.role = role
        self.llm_fn = llm_fn  # callable: prompt -> str, or None for symbolic-only agents
        self.session_log: list[dict] = []

    def run(self, context: dict) -> dict:
        """
        Execute this agent's research role on the given context.
        Must be overridden by specialization subclasses.

        context keys (role-dependent):
        - conjecture: Conjecture object or statement string
        - explorer:   CollatzExplorer instance
        - n_range:    (start, end) tuple for numerical search
        - lessons:    list of past failure lessons
        - prompt:     override prompt for LLM-backed agents

        Returns a dict with at minimum:
        - role: str
        - output: str or dict
        - confidence: float
        - next_step: str
        """
        raise NotImplementedError(f"MathResearchAgent subclass '{self.role}' must implement run()")

    def _ask(self, prompt: str) -> str:
        """Invoke the LLM with the given prompt."""
        if self.llm_fn is None:
            raise RuntimeError(f"Agent '{self.role}' has no LLM function configured.")
        return self.llm_fn(prompt)

    def _log(self, entry: dict):
        """Append a structured entry to this agent's session log."""
        import time
        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["role"] = self.role
        self.session_log.append(entry)

    def session_summary(self) -> list[dict]:
        """Return this agent's full session log for inspection or memory storage."""
        return self.session_log

