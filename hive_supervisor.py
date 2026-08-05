from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from continuation_protocol import ContinuationDecision, ContinuationStatus


@dataclass(frozen=True)
class SupervisorResult:
    status: ContinuationStatus
    iterations: int
    unnecessary_human_interventions: int
    last_decision: ContinuationDecision
    history: tuple[dict[str, Any], ...]


class HiveSupervisor:
    """Owns continuation; a worker invocation owns only one reasoning step."""

    def __init__(self, *, max_iterations: int = 20, max_stagnant_iterations: int = 2):
        if max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if max_stagnant_iterations < 1:
            raise ValueError("max_stagnant_iterations must be positive")
        self.max_iterations = max_iterations
        self.max_stagnant_iterations = max_stagnant_iterations

    def run(
        self,
        initial_state: dict[str, Any],
        worker: Callable[[dict[str, Any]], dict[str, Any]],
        verify: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ) -> SupervisorResult:
        state = dict(initial_state)
        history: list[dict[str, Any]] = []
        stagnant = 0
        previous_fingerprint: tuple[Any, ...] | None = None

        for iteration in range(1, self.max_iterations + 1):
            worker_result = worker(dict(state))
            decision = ContinuationDecision.from_dict(worker_result["continuation"])
            evidence = verify(dict(state), worker_result)
            next_state = dict(state)
            next_state.update(worker_result.get("state_updates") or {})
            next_state["last_evidence"] = evidence

            fingerprint = (
                decision.status.value,
                decision.next_objective,
                repr(sorted((worker_result.get("state_updates") or {}).items())),
                repr(sorted(evidence.items())),
            )
            stagnant = stagnant + 1 if fingerprint == previous_fingerprint else 0
            previous_fingerprint = fingerprint

            history.append({
                "iteration": iteration,
                "decision": decision.to_dict(),
                "evidence": evidence,
            })

            if decision.is_terminal:
                return SupervisorResult(decision.status, iteration, 0, decision, tuple(history))

            if decision.status is ContinuationStatus.WAIT_EXTERNAL:
                return SupervisorResult(decision.status, iteration, 0, decision, tuple(history))

            if stagnant >= self.max_stagnant_iterations:
                blocked = ContinuationDecision.from_dict({
                    "status": "BLOCKED",
                    "reason": "Supervisor detected repeated identical continuation state without measurable progress.",
                    "blocked": True,
                })
                history.append({"iteration": iteration, "decision": blocked.to_dict(), "evidence": evidence})
                return SupervisorResult(blocked.status, iteration, 0, blocked, tuple(history))

            state = next_state

        blocked = ContinuationDecision.from_dict({
            "status": "BLOCKED",
            "reason": "Supervisor iteration budget exhausted before a legitimate checkpoint.",
            "blocked": True,
        })
        history.append({"iteration": self.max_iterations, "decision": blocked.to_dict(), "evidence": {}})
        return SupervisorResult(blocked.status, self.max_iterations, 0, blocked, tuple(history))
