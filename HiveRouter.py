# === HiveRouter.py ===
# Conservative, dumb-by-default router for ReasoningHead opinions.
# It compares opinions, brakes on disagreement, and can abstain.

from dataclasses import dataclass
from typing import List, Optional
import math
from HiveReasoningHeads import Opinion


@dataclass
class RoutedDecision:
    abstain: bool
    score: float
    confidence: float
    source: Optional[str]
    reason: str
    opinions: List[Opinion]


class HiveRouter:
    """
    Selection layer: decides which interpretation to trust right now.
    - favors opinions with higher confidence
    - brakes on disagreement
    - can abstain (returns abstain=True)
    Router does not learn, mutate state, or create heads.
    """

    def __init__(
        self,
        min_confidence: float = 0.2,
        disagreement_brake: float = 0.35,  # max allowed (max_score - min_score)
        require_heads: int = 1,
    ):
        self.min_confidence = min_confidence
        self.disagreement_brake = disagreement_brake
        self.require_heads = require_heads

    def select(self, opinions: List[Opinion]) -> RoutedDecision:
        if not opinions or len(opinions) < self.require_heads:
            return RoutedDecision(
                abstain=True,
                score=0.0,
                confidence=0.0,
                source=None,
                reason="insufficient_opinions",
                opinions=opinions or [],
            )

        # Filter out zero-confidence noise but keep at least one opinion
        filtered = [op for op in opinions if op.confidence > 0]
        if not filtered:
            filtered = opinions

        scores = [op.score for op in filtered]
        confidences = [max(op.confidence, 1e-6) for op in filtered]

        max_conf = max(confidences)
        if max_conf < self.min_confidence:
            return RoutedDecision(
                abstain=True,
                score=0.0,
                confidence=max_conf,
                source=None,
                reason="low_confidence",
                opinions=filtered,
            )

        max_score, min_score = max(scores), min(scores)
        disagreement = max_score - min_score
        if disagreement > self.disagreement_brake:
            return RoutedDecision(
                abstain=True,
                score=sum(scores) / len(scores),
                confidence=max_conf * (1.0 - min(1.0, disagreement)),
                source=None,
                reason="disagreement_brake",
                opinions=filtered,
            )

        # Weighted mean score (confidence as weight)
        weighted_score = sum(s * c for s, c in zip(scores, confidences)) / sum(confidences)

        # Pick champion closest to weighted_score but with strong confidence
        def champion_key(op: Opinion):
            proximity = 1.0 - abs(op.score - weighted_score)  # closer to 1 is better
            return op.confidence * proximity

        champion = max(filtered, key=champion_key)

        # Decision confidence: blend champion confidence with agreement
        agreement = 1.0 - disagreement  # 1 when aligned, drops as they diverge
        decision_conf = max(0.0, min(1.0, 0.5 * champion.confidence + 0.5 * agreement))

        return RoutedDecision(
            abstain=False,
            score=weighted_score,
            confidence=decision_conf,
            source=champion.name,
            reason="routed",
            opinions=filtered,
        )


# Convenience function
def route(opinions: List[Opinion], **kwargs) -> RoutedDecision:
    return HiveRouter(**kwargs).select(opinions)
