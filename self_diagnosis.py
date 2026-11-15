from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


REQUIRED_EVIDENCE_FIELDS = ("source", "observation")


@dataclass(frozen=True)
class Evidence:
    source: str
    observation: str
    artifact: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Evidence":
        missing = [key for key in REQUIRED_EVIDENCE_FIELDS if not str(value.get(key) or "").strip()]
        if missing:
            raise ValueError(f"evidence missing required fields: {missing}")
        return cls(
            source=str(value["source"]).strip(),
            observation=str(value["observation"]).strip(),
            artifact=str(value["artifact"]).strip() if value.get("artifact") else None,
        )


@dataclass(frozen=True)
class SelfDiagnosis:
    run_id: str
    goal: str
    observed: str
    expected: str
    divergence: str
    contributing_component: str
    scope: str
    cause: str
    proposed_change: str
    expected_improvement: str
    risks: tuple[str, ...]
    falsification_test: str
    evidence: tuple[Evidence, ...]
    confidence: float
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SelfDiagnosis":
        required = (
            "run_id", "goal", "observed", "expected", "divergence",
            "contributing_component", "scope", "cause", "proposed_change",
            "expected_improvement", "falsification_test",
        )
        missing = [key for key in required if not str(value.get(key) or "").strip()]
        if missing:
            raise ValueError(f"diagnosis missing required fields: {missing}")
        evidence = tuple(Evidence.from_dict(item) for item in value.get("evidence", []))
        if not evidence:
            raise ValueError("diagnosis requires at least one evidence item")
        confidence = float(value.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        scope = str(value["scope"]).strip().lower()
        if scope not in {"local", "systemic", "unknown"}:
            raise ValueError("scope must be local, systemic, or unknown")
        return cls(
            run_id=str(value["run_id"]).strip(),
            goal=str(value["goal"]).strip(),
            observed=str(value["observed"]).strip(),
            expected=str(value["expected"]).strip(),
            divergence=str(value["divergence"]).strip(),
            contributing_component=str(value["contributing_component"]).strip(),
            scope=scope,
            cause=str(value["cause"]).strip(),
            proposed_change=str(value["proposed_change"]).strip(),
            expected_improvement=str(value["expected_improvement"]).strip(),
            risks=tuple(str(item).strip() for item in value.get("risks", []) if str(item).strip()),
            falsification_test=str(value["falsification_test"]).strip(),
            evidence=evidence,
            confidence=confidence,
            created_at=str(value.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["risks"] = list(self.risks)
        result["evidence"] = [asdict(item) for item in self.evidence]
        return result


class SelfDiagnosisLedger:
    """Append-only evidence ledger for Level-2 self-diagnosis.

    This does not let Hive modify itself. It creates a falsifiable, inspectable
    artifact that candidate-generation can later consume.
    """

    def __init__(self, path: str | Path = "validation/self_diagnoses.jsonl"):
        self.path = Path(path)

    def append(self, diagnosis: SelfDiagnosis) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(diagnosis.to_dict(), sort_keys=True) + "\n")

    def load(self) -> list[SelfDiagnosis]:
        if not self.path.exists():
            return []
        records: list[SelfDiagnosis] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(SelfDiagnosis.from_dict(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"invalid diagnosis ledger entry at line {line_number}: {exc}") from exc
        return records
