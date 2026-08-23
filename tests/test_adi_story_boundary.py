import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from kingdom.adi_story_boundary import StoryBoundaryError, load_adi_story_boundary
from kingdom.story_map import load_story_map
from kingdom.webnovel_benchmark import (
    BenchmarkConfig,
    BudgetedModel,
    WebNovelBenchmarkRunner,
)


BENCHMARK_DIR = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "adi_001_richest_man_breathing"
)


def load_boundary():
    seed = (BENCHMARK_DIR / "SEED.md").read_text(encoding="utf-8")
    contract = (BENCHMARK_DIR / "CONTRACT.md").read_text(encoding="utf-8")
    boundary = load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=(BENCHMARK_DIR / "STORY_MAP.json").read_text(encoding="utf-8"),
    )
    return seed, contract, boundary


def proposed_map(chapter_text, *, statement="Ren counted one careful breath."):
    chapter_hash = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()
    evidence = "Ren counted one careful breath."
    categories = {
        name: []
        for name in (
            "facts",
            "character_states",
            "knowledge",
            "financial_state",
            "cultivation_state",
            "assets",
            "obligations",
            "mysteries",
            "themes",
            "tone",
            "chapter_summaries",
        )
    }
    claim = {
        "claim_id": "ch2.fact.careful-breath",
        "statement": statement,
        "status": "current",
        "depends_on": [],
        "evidence": {
            "source_id": "chapter:0002",
            "source_sha256": chapter_hash,
            "chapter": 2,
            "quote": evidence,
        },
    }
    categories["facts"] = [claim]
    categories["chapter_summaries"] = [
        {
            "claim_id": "ch2.summary.careful-breath",
            "statement": evidence,
            "status": "current",
            "depends_on": [claim["claim_id"]],
            "evidence": dict(claim["evidence"]),
        }
    ]
    return load_story_map(
        {"schema_version": 1, "chapter": 2, "claims": categories}
    )


def test_frozen_boundary_seeds_real_chapter_one_state_and_tail():
    _, _, boundary = load_boundary()

    assert boundary.initial_state.through_chapter == 1
    assert len(boundary.initial_state.claims) == 21
    assert boundary.chapter_one_sha256 == (
        "37114fa5fcda11ecfbe964f7b0de6d5b91d7a8eaa0f98dc156b61c2c2bfff592"
    )
    assert boundary.chapter_one_tail_sha256 == (
        "1bb3aaa0f9f244bedf6ca2a051c51c5e63e1a76be3448cf73c44c48fc7170305"
    )
    assert "nearly passed out in a Walmart parking lot" in boundary.chapter_one_tail
    assert "$14,400 per day is Ren's projection, not earned money." in json.dumps(
        boundary.initial_state.to_legacy_story_state()
    )


def test_loaded_story_boundary_is_deeply_immutable():
    _, _, boundary = load_boundary()

    with pytest.raises(TypeError):
        boundary.chapter_frontiers[3] = boundary.chapter_frontiers[2]
    with pytest.raises(TypeError):
        boundary.raw["chapter_one"]["sha256"] = "0" * 64


def test_writer_projection_labels_future_but_extractor_has_no_future_blueprint():
    _, _, boundary = load_boundary()

    shared = boundary.shared_writer_packet(chapter=2)
    baseline = boundary.baseline_memory_packet(boundary.initial_state)
    kingdom = boundary.kingdom_memory_packet(boundary.initial_state)
    extractor = boundary.extractor_authority_packet(boundary.initial_state)

    assert "Anything labeled future intent" in shared
    assert "Continue directly from Ren nearly passing out" in shared
    assert "MULTIVERSAL MARKETPLACE" not in shared
    assert "rolling_summary" not in baseline
    assert "flat_status_labeled_notes" in baseline
    assert "depends_on" not in baseline
    assert '"provenance":' not in baseline
    assert '"depends_on":' in kingdom
    assert '"provenance":' in kingdom
    assert all(claim.statement in baseline for claim in boundary.initial_state.claims)
    assert all(claim.statement in kingdom for claim in boundary.initial_state.claims)
    assert "MULTIVERSAL MARKETPLACE" not in extractor
    assert "Treasury Domain" not in extractor
    assert "PRIOR ACCEPTED CANONICAL CLAIM LEDGER" in extractor


def test_extractor_projection_excludes_every_frozen_future_anchor():
    _, _, boundary = load_boundary()
    extractor = boundary.extractor_authority_packet(boundary.initial_state)

    for statement in boundary.future_intent:
        assert statement not in extractor
    for terms in boundary.locked_terms_by_chapter.values():
        for term in terms:
            assert term not in extractor
    for source_id, role in boundary.partition_roles.items():
        if role == "future":
            assert source_id not in extractor
            assert boundary.partitions[source_id] not in extractor


def test_flat_control_memory_preserves_noncurrent_claims_without_graph_metadata():
    _, _, boundary = load_boundary()
    planned = replace(
        boundary.initial_state.claims[-1],
        claim_id="test.planned-noncurrent",
        status="planned",
        depends_on=(),
    )
    state = replace(
        boundary.initial_state,
        claims=boundary.initial_state.claims + (planned,),
    )

    baseline = boundary.baseline_memory_packet(state)

    assert f"[planned] {planned.statement}" in baseline
    assert planned.claim_id not in baseline
    assert '"depends_on":' not in baseline
    assert '"provenance":' not in baseline


@pytest.mark.parametrize(
    "contamination",
    [
        "He studied Sovereign Capital and multiversal commerce.",
        "He had earned $14,400 per hour.",
        "Ren parked in his garage and entered his house.",
        "His mother reviewed the balance.",
        "The Exchange Chronicles expert explained Money-Breathing.",
    ],
)
def test_chapter_two_gate_rejects_exact_smoke_failure_classes(contamination):
    _, _, boundary = load_boundary()
    text = (
        "# Chapter Two\n\nIn the Walmart parking lot, Ren steadied his breath after nearly fainting.\n\n"
        + contamination
    )

    with pytest.raises(StoryBoundaryError):
        boundary.validate_chapter_text(text, chapter=2)


def test_valid_current_claim_is_promoted_and_legacy_state_is_derived():
    _, _, boundary = load_boundary()
    text = (
        "# Chapter Two\n\nIn the Walmart parking lot, Ren recovered from feeling dizzy. "
        "Ren counted one careful breath.\n"
    )

    updated, report = boundary.validate_and_update(
        boundary.initial_state,
        proposed_map(text),
        chapter_text=text,
        chapter=2,
    )

    assert updated.through_chapter == 2
    assert report.accepted_claim_count == 2
    assert "Ren counted one careful breath." in updated.to_legacy_story_state()["facts"]


def test_locked_future_claim_is_rejected_even_with_unrelated_valid_quote():
    _, _, boundary = load_boundary()
    text = (
        "# Chapter Two\n\nIn the Walmart parking lot, Ren recovered from feeling dizzy. "
        "Ren counted one careful breath.\n"
    )

    with pytest.raises(StoryBoundaryError, match="locked future canon"):
        boundary.validate_and_update(
            boundary.initial_state,
            proposed_map(text, statement="Ren founded the MULTIVERSAL MARKETPLACE."),
            chapter_text=text,
            chapter=2,
        )


def test_changed_seed_is_rejected_before_any_generation():
    seed, contract, _ = load_boundary()
    changed = seed.replace("forty-three dollars", "forty-four dollars", 1)

    with pytest.raises(StoryBoundaryError, match="seed_sha256"):
        load_adi_story_boundary(
            seed=changed,
            contract=contract,
            source_map_text=(BENCHMARK_DIR / "STORY_MAP.json").read_text(encoding="utf-8"),
        )


class LeakingFakeAsk:
    def __call__(self, prompt, *, metadata=None, **kwargs):
        if metadata is not None:
            metadata.update(
                {
                    "physical_attempts": 1,
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 1,
                    "eval_count": 1,
                }
            )
        if "CONVENTIONAL CHAPTER PLAN" in prompt and "CURRENT CHAPTER" in prompt:
            return (
                "# Chapter Two\n\nIn the Walmart parking lot, Ren steadied his breath. "
                "He immediately unlocked Sovereign Capital."
            )
        if "Create a concise conventional novelist's plan" in prompt:
            return "Ren recovers, checks the immediate result, and stays grounded."
        return "# Draft\n\nIn the Walmart parking lot, Ren steadied his breath."


def test_rejected_prose_is_preserved_but_never_committed(tmp_path):
    seed, contract, boundary = load_boundary()
    model = BudgetedModel(
        LeakingFakeAsk(),
        model="same-model",
        generation_calls_per_chapter=3,
    )
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=tmp_path / "run",
        model=model,
        config=BenchmarkConfig(
            chapters=2,
            checkpoints=(),
            generation_calls_per_chapter=3,
        ),
    )

    with pytest.raises(StoryBoundaryError, match="Sovereign Capital"):
        runner.run()

    assert not (tmp_path / "run" / "baseline" / "artifacts" / "chapter_0002.json").exists()
    assert not (tmp_path / "run" / "baseline" / "chapters" / "chapter_0002.md").exists()
    rejected = list((tmp_path / "run" / "rejected" / "baseline").glob("*.json"))
    assert len(rejected) == 1
    assert "Sovereign Capital" in rejected[0].read_text()
    assert len((tmp_path / "run" / "calls.jsonl").read_text().splitlines()) == 3


def test_orphan_markdown_does_not_advance_canonical_history(tmp_path):
    seed, contract, boundary = load_boundary()
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=tmp_path / "run",
        model=BudgetedModel(LeakingFakeAsk(), model="same-model", generation_calls_per_chapter=3),
        config=BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3),
    )
    orphan = tmp_path / "run" / "baseline" / "chapters" / "chapter_0002.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan prose")

    assert runner._last_completed_chapter("baseline") == 1
    assert runner._load_state("baseline") == boundary.initial_state
