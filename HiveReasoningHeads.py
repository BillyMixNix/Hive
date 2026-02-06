# === HiveReasoningHeads.py ===
# Read-only reasoning heads that score current Hive state without causing side‑effects.

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple, Union
import math
import torch
import torch.nn.functional as F

TensorLike = Union[torch.Tensor, List[float], Tuple[float, ...]]


@dataclass
class Opinion:
    score: float       # primary signal (0..1)
    confidence: float  # trust in this score (0..1)
    name: str          # head name


class ReasoningHead:
    name: str = "base"

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        raise NotImplementedError("Subclasses implement evaluate(state)")


# --- helpers ----------------------------------------------------

def _to_tensor(x: TensorLike) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        return x
    return torch.tensor(x, dtype=torch.float32)


def _pairwise_cosine(vectors: List[torch.Tensor]) -> List[float]:
    sims = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            a, b = vectors[i], vectors[j]
            # Align dimensions by truncating to the minimum width to avoid shape errors.
            if a.shape[-1] != b.shape[-1]:
                min_dim = min(a.shape[-1], b.shape[-1])
                a = a[..., :min_dim]
                b = b[..., :min_dim]
            sims.append(F.cosine_similarity(a, b, dim=-1).mean().item())
    return sims


# --- heads ------------------------------------------------------

class NoveltyHead(ReasoningHead):
    """
    Compares the current vector to a bank of memory vectors and emits how new it feels.
    Expect state keys:
      - current_vector: Tensor-like
      - memory_vectors: Iterable of Tensor-like
    """
    name = "novelty"

    def __init__(self, current_key="current_vector", memory_key="memory_vectors"):
        self.current_key = current_key
        self.memory_key = memory_key

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        cur = state.get(self.current_key)
        mem = state.get(self.memory_key, [])
        if cur is None or not mem:
            return Opinion(score=0.0, confidence=0.1, name=self.name)

        cur_t = _to_tensor(cur)
        mem_tensors = [_to_tensor(m) for m in mem if m is not None]
        if not mem_tensors:
            return Opinion(score=0.0, confidence=0.1, name=self.name)

        sims = [F.cosine_similarity(cur_t, m, dim=-1).mean().item() for m in mem_tensors]
        avg_sim = sum(sims) / len(sims)
        novelty = max(0.0, min(1.0, 1.0 - avg_sim))
        conf = min(1.0, 0.3 + 0.1 * len(mem_tensors))
        return Opinion(score=novelty, confidence=conf, name=self.name)


class CoherenceHead(ReasoningHead):
    """
    Measures how aligned agent vectors are with each other (agreement, not correctness).
    Expect state key:
      - agent_vectors: dict {agent_name: tensor}
    """
    name = "coherence"

    def __init__(self, agent_key="agent_vectors"):
        self.agent_key = agent_key

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        agent_vecs = state.get(self.agent_key, {})
        if not isinstance(agent_vecs, dict) or len(agent_vecs) < 2:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        vectors = [_to_tensor(v) for v in agent_vecs.values() if v is not None]
        if len(vectors) < 2:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        sims = _pairwise_cosine(vectors)
        if not sims:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        avg_sim = sum(sims) / len(sims)
        return Opinion(score=avg_sim, confidence=min(1.0, 0.2 + 0.1 * len(vectors)), name=self.name)


class AmbiguityHead(ReasoningHead):
    """
    Emits how uncertain a categorical distribution is (higher = more ambiguous).
    Accepts probabilities or logits under state key:
      - candidate_probs: iterable
    """
    name = "ambiguity"

    def __init__(self, probs_key="candidate_probs"):
        self.probs_key = probs_key

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        probs = state.get(self.probs_key)
        if probs is None:
            return Opinion(score=0.0, confidence=0.1, name=self.name)

        p = _to_tensor(probs).float().flatten()
        if p.numel() < 2:
            return Opinion(score=0.0, confidence=0.1, name=self.name)

        if (p < 0).any():  # treat as logits
            p = torch.softmax(p, dim=0)
        else:  # normalize if needed
            p = p / (p.sum() + 1e-8)

        entropy = -torch.sum(p * torch.log(p + 1e-8)).item()
        max_entropy = math.log(float(p.numel()))
        normalized = entropy / (max_entropy + 1e-8)
        return Opinion(score=normalized, confidence=min(1.0, 0.2 + 0.1 * p.numel()), name=self.name)


class ConsistencyHead(ReasoningHead):
    """
    Cross-agent agreement head (alias of coherence but kept separate for clarity).
    """
    name = "consistency"

    def __init__(self, agent_key="agent_vectors"):
        self.agent_key = agent_key

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        agent_vecs = state.get(self.agent_key, {})
        if not isinstance(agent_vecs, dict) or len(agent_vecs) < 2:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        vectors = [_to_tensor(v) for v in agent_vecs.values() if v is not None]
        if len(vectors) < 2:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        sims = _pairwise_cosine(vectors)
        if not sims:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        avg_sim = sum(sims) / len(sims)
        return Opinion(score=avg_sim, confidence=min(1.0, 0.3 + 0.05 * len(vectors)), name=self.name)


class TemporalFitHead(ReasoningHead):
    """
    Scores how well an event timestamp fits a reference time.
    Expect state keys:
      - timestamp: float seconds (event)
      - reference_time: float seconds (expected or now)
    """
    name = "temporal_fit"

    def __init__(self, timestamp_key="timestamp", reference_key="reference_time", tolerance_seconds=60.0):
        self.timestamp_key = timestamp_key
        self.reference_key = reference_key
        self.tolerance_seconds = tolerance_seconds

    def evaluate(self, state: Dict[str, Any]) -> Opinion:
        ts = state.get(self.timestamp_key)
        ref = state.get(self.reference_key)
        if ts is None or ref is None:
            return Opinion(score=0.5, confidence=0.1, name=self.name)

        delta = abs(float(ts) - float(ref))
        score = max(0.0, 1.0 - (delta / (self.tolerance_seconds + 1e-6)))
        confidence = 0.6 if delta <= self.tolerance_seconds else 0.3
        return Opinion(score=score, confidence=confidence, name=self.name)
