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


# ---------------------------------------------------------------------------
# MathResearchAgent Specializations
# ---------------------------------------------------------------------------

class ExploratoryAgent(MathResearchAgent):
    """Numerical pattern search — finds longest trajectories, parity clusters, cycle candidates."""

    def __init__(self, llm_fn=None):
        super().__init__("exploratory", llm_fn)

    def run(self, context: dict) -> dict:
        from math_domain import CollatzExplorer

        explorer = context.get("explorer") or CollatzExplorer()
        start, end = context.get("n_range", (1, 10_000))

        longest_n, longest_t = explorer.find_longest_trajectory(start, end)
        patterns = explorer.parity_patterns(start, min(start + 499, end), prefix_length=6)
        cycle_candidate = explorer.search_for_cycle(start, end)

        output = {
            "range": [start, end],
            "longest_trajectory": {"n": longest_n, "stopping_time": longest_t},
            "parity_pattern_count": len(patterns),
            "top_patterns": sorted(patterns.items(), key=lambda x: -len(x[1]))[:3],
            "cycle_found": cycle_candidate,
        }
        confidence = 0.0 if cycle_candidate else 0.7
        next_step = (
            f"ALERT: Potential counterexample at n={cycle_candidate}. Escalate to adversarial agent."
            if cycle_candidate
            else "Pass longest-trajectory finding and parity clusters to symbolic agent for algebraic form."
        )
        entry = {"role": self.role, "output": output, "confidence": confidence, "next_step": next_step}
        self._log(entry)
        return entry


class AdversarialMathAgent(MathResearchAgent):
    """Hunts for counterexamples — trajectories that fail to reach 1."""

    def __init__(self, llm_fn=None):
        super().__init__("adversarial", llm_fn)

    def run(self, context: dict) -> dict:
        from math_domain import CollatzExplorer, Conjecture

        explorer = context.get("explorer") or CollatzExplorer()
        start, end = context.get("n_range", (1, 100_000))
        conjecture = context.get("conjecture")

        cycle_candidate = explorer.search_for_cycle(start, end)
        falsified = cycle_candidate is not None

        if isinstance(conjecture, Conjecture):
            conjecture.record_falsification_attempt(
                f"Cycle/divergence search in [{start}, {end}]", succeeded=falsified
            )

        output = {
            "range": [start, end],
            "counterexample": cycle_candidate,
            "verdict": "FALSIFIED" if falsified else f"No counterexample in [{start}, {end}]",
        }
        confidence = 0.0 if falsified else 0.6
        next_step = (
            f"Conjecture falsified at n={cycle_candidate}. Record lesson and restart search."
            if falsified
            else "No counterexample found. Increase range or elevate to formal agent."
        )
        entry = {"role": self.role, "output": output, "confidence": confidence, "next_step": next_step}
        self._log(entry)
        return entry


class SymbolicMathAgent(MathResearchAgent):
    """Transforms numerical observations into algebraic expressions via SymPy."""

    def __init__(self, llm_fn=None):
        super().__init__("symbolic", llm_fn)

    def run(self, context: dict) -> dict:
        from math_domain import SymbolicAgent

        agent = SymbolicAgent()
        task = context.get("task", "stopping_time_model")

        if task == "gap_formula":
            output = agent.gap_formula()
        elif task == "verify_identity":
            output = agent.verify_identity(context.get("lhs", ""), context.get("rhs", ""))
        elif task == "check_approximation":
            output = agent.check_approximation_error(
                context.get("exact", "log(3*n + 1)"),
                context.get("approx", "log(3*n)"),
                context.get("subs"),
            )
        elif task == "series_expand":
            output = agent.series_expand(context.get("expr", "log(n)"))
        else:
            output = agent.stopping_time_model()

        verdict = output.get("verdict", "") or output.get("status", "")
        confidence = 0.8 if any(w in verdict for w in ("supported", "IDENTICAL", "safe")) else 0.5
        next_step = "Pass algebraic form to formal agent for Z3 verification of finite cases."

        entry = {"role": self.role, "output": output, "confidence": confidence, "next_step": next_step}
        self._log(entry)
        return entry


class FormalMathAgent(MathResearchAgent):
    """Produces machine-checkable proof fragments using Z3."""

    def __init__(self, llm_fn=None):
        super().__init__("formal", llm_fn)

    def run(self, context: dict) -> dict:
        from math_domain import FormalVerifier

        verifier = FormalVerifier()
        task = context.get("task", "run_all")

        if task == "v2_geq_k":
            output = verifier.verify_v2_geq_k(context.get("k", 3))
        elif task == "geometric_distribution":
            output = verifier.verify_geometric_distribution(context.get("max_k", 6))
        elif task == "even_after_odd":
            output = verifier.verify_collatz_always_even_after_odd()
        elif task == "syracuse_growth":
            output = verifier.verify_syracuse_growth_v1()
        elif task == "syracuse_reduction":
            output = verifier.verify_syracuse_reduction_v2()
        else:
            output = verifier.run_all()

        status = output.get("status", "")
        confidence = 0.95 if status in ("PROVED", "all_verified") else 0.5 if status == "PARTIAL" else 0.1
        next_step = (
            "All fragments verified. Elevate conjecture and pass to strategic agent for architecture review."
            if status in ("PROVED", "all_verified")
            else "Some fragments failed — return to symbolic agent to tighten preconditions."
        )
        entry = {"role": self.role, "output": output, "confidence": confidence, "next_step": next_step}
        self._log(entry)
        return entry


class StrategicMathAgent(MathResearchAgent):
    """Evaluates proof architecture and prescribes the highest-leverage next step."""

    def __init__(self, llm_fn=None):
        super().__init__("strategic", llm_fn)

    def run(self, context: dict) -> dict:
        from math_domain import MathProgressTracker

        tracker = MathProgressTracker()
        conjectures = list(context.get("conjectures", []))
        single = context.get("conjecture")
        if single is not None:
            conjectures.append(single)

        if not conjectures:
            output = {"scores": [], "verdict": "No conjectures provided — nothing to evaluate."}
            confidence = 0.0
            next_step = "Provide at least one conjecture for strategic evaluation."
        else:
            scores = tracker.score_all(conjectures)
            best = scores[0]
            output = {
                "scores": scores,
                "best_conjecture": best.get("conjecture"),
                "best_level": best.get("level_name"),
                "best_next_action": best.get("next_action"),
            }
            confidence = min(0.9, best.get("score", 0) / 6)
            next_step = best.get("next_action", "No actionable next step found.")

        entry = {"role": self.role, "output": output, "confidence": confidence, "next_step": next_step}
        self._log(entry)
        return entry

