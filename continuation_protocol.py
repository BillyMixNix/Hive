from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ContinuationStatus(str, Enum):
    CONTINUE = "CONTINUE"
    WAIT_EXTERNAL = "WAIT_EXTERNAL"
    HUMAN_AUTHORITY_REQUIRED = "HUMAN_AUTHORITY_REQUIRED"
    HUMAN_EVALUATION_REQUIRED = "HUMAN_EVALUATION_REQUIRED"
    BLOCKED = "BLOCKED"
    MILESTONE_COMPLETE = "MILESTONE_COMPLETE"


TERMINAL_FOR_SUPERVISOR = {
    ContinuationStatus.HUMAN_AUTHORITY_REQUIRED,
    ContinuationStatus.HUMAN_EVALUATION_REQUIRED,
    ContinuationStatus.BLOCKED,
    ContinuationStatus.MILESTONE_COMPLETE,
}


@dataclass(frozen=True)
class ContinuationDecision:
    status: ContinuationStatus
    reason: str
    next_objective: str | None = None
    human_input_required: bool = False
    milestone_reached: bool = False
    blocked: bool = False
    wait_condition: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ContinuationDecision":
        status = ContinuationStatus(str(value.get("status") or "").strip())
        reason = str(value.get("reason") or "").strip()
        if not reason:
            raise ValueError("continuation decision requires a reason")
        decision = cls(
            status=status,
            reason=reason,
            next_objective=str(value["next_objective"]).strip() if value.get("next_objective") else None,
            human_input_required=bool(value.get("human_input_required", False)),
            milestone_reached=bool(value.get("milestone_reached", False)),
            blocked=bool(value.get("blocked", False)),
            wait_condition=str(value["wait_condition"]).strip() if value.get("wait_condition") else None,
        )
        decision.validate()
        return decision

    def validate(self) -> None:
        if self.status is ContinuationStatus.CONTINUE:
            if not self.next_objective:
                raise ValueError("CONTINUE requires next_objective")
            if self.human_input_required or self.milestone_reached or self.blocked:
                raise ValueError("CONTINUE cannot claim human input, milestone completion, or blockage")
        elif self.status is ContinuationStatus.WAIT_EXTERNAL:
            if not self.wait_condition:
                raise ValueError("WAIT_EXTERNAL requires wait_condition")
            if self.human_input_required or self.milestone_reached or self.blocked:
                raise ValueError("WAIT_EXTERNAL is non-terminal and cannot claim a terminal condition")
        elif self.status is ContinuationStatus.HUMAN_AUTHORITY_REQUIRED:
            if not self.human_input_required:
                raise ValueError("HUMAN_AUTHORITY_REQUIRED must set human_input_required")
        elif self.status is ContinuationStatus.HUMAN_EVALUATION_REQUIRED:
            if not self.human_input_required:
                raise ValueError("HUMAN_EVALUATION_REQUIRED must set human_input_required")
        elif self.status is ContinuationStatus.BLOCKED:
            if not self.blocked:
                raise ValueError("BLOCKED must set blocked")
        elif self.status is ContinuationStatus.MILESTONE_COMPLETE:
            if not self.milestone_reached:
                raise ValueError("MILESTONE_COMPLETE must set milestone_reached")

    @property
    def should_reinvoke(self) -> bool:
        return self.status is ContinuationStatus.CONTINUE

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_FOR_SUPERVISOR

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result
