from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class KnowledgeRecord:
    key: str
    statement: str
    observations: int = 0
    confirmations: int = 0
    contradictions: int = 0
    status: str = "observed"

    @property
    def confidence(self):
        total = self.confirmations + self.contradictions
        if total == 0:
            return 0.0
        return self.confirmations / total


class WorldKnowledge:
    """Evidence memory. Records cannot affect simulation until promoted."""

    def __init__(self, records=None):
        self.records = records or {}

    def observe(self, key, statement, confirmed=True):
        record = self.records.setdefault(key, KnowledgeRecord(key=key, statement=statement))
        record.observations += 1
        if confirmed:
            record.confirmations += 1
        else:
            record.contradictions += 1
        return record

    def promote(self, key, min_observations=3, min_confidence=0.8):
        record = self.records[key]
        if record.observations < min_observations:
            raise ValueError("insufficient observations for promotion")
        if record.confidence < min_confidence:
            raise ValueError("insufficient confidence for promotion")
        record.status = "promoted"
        return record

    def is_promoted(self, key):
        record = self.records.get(key)
        return bool(record and record.status == "promoted")

    def to_dict(self):
        return {key: asdict(record) for key, record in self.records.items()}

    @classmethod
    def from_dict(cls, data):
        return cls({
            key: KnowledgeRecord(**record)
            for key, record in (data or {}).items()
        })
