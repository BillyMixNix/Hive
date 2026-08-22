from pathlib import Path

from kingdom.construction import ConstructionGraph, ConstructionRun
from kingdom.core import (
    CognitivePacket,
    HashChainLedger,
    KingdomRun,
    Seed,
    StructureMap,
)
from kingdom.persistence import ConstructionRecorder


def _construction_run(tmp_path):
    seed = Seed("build the target")
    structure = StructureMap(invariants=("one invariant",))
    packet = CognitivePacket(
        title="record",
        orientation="audit me",
        load_bearing_insights=("one invariant",),
        uncertainty=(),
        next_moves=(),
    )
    base = KingdomRun(
        run_id="kingdom-test-record",
        seed=seed,
        branches=(),
        results=(),
        structure=structure,
        packet=packet,
        probes=(),
        started_at=1.0,
        finished_at=2.0,
    )
    graph = ConstructionGraph()
    graph.add("build the target", kind="goal", status="open")
    return ConstructionRun(
        base_run=base,
        verified_results=(),
        arena_executions=(),
        graph=graph,
        structure=structure,
        packet=packet,
        probes=(),
    )


def test_construction_record_is_hashed_and_anchored_in_ledger(tmp_path):
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    recorder = ConstructionRecorder(tmp_path / "construction", ledger=ledger)

    record = recorder.persist(_construction_run(tmp_path))

    assert Path(record.path).exists()
    assert len(record.sha256) == 64
    assert recorder.verify(record) is True
    assert ledger.verify() is True
    ledger_text = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert '"kind": "construction_run"' in ledger_text
    assert record.sha256 in ledger_text


def test_construction_record_detects_artifact_tampering(tmp_path):
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    recorder = ConstructionRecorder(tmp_path / "construction", ledger=ledger)
    record = recorder.persist(_construction_run(tmp_path))

    Path(record.path).write_text("{}\n", encoding="utf-8")

    assert recorder.verify(record) is False
    assert ledger.verify() is True
