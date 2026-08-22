import json
from pathlib import Path

import pytest

from kingdom.webnovel_benchmark import (
    BenchmarkConfig,
    BudgetExceeded,
    BudgetedModel,
    StoryState,
    WebNovelBenchmarkRunner,
    _extract_json,
)


class FakeAsk:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt, *, role="default", timeout=None, model=None, system=None):
        self.calls.append((prompt, role, model))
        if "Extract the post-chapter narrative state as JSON" in prompt:
            return json.dumps(
                {
                    "facts": ["Ren continues the experiment"],
                    "character_states": ["Ren remains curious and cautious"],
                    "knowledge": ["Ren knows the breathing rule works"],
                    "financial_state": ["balance changed through breathing"],
                    "cultivation_state": ["Money-Breathing remains foundational"],
                    "assets": [],
                    "obligations": ["sleep test remains unresolved"],
                    "mysteries": ["source of the technique remains unknown"],
                    "themes": ["value is not identical to price"],
                    "tone": ["comedic mundane escalation"],
                    "chapter_summaries": ["Ren tests the ability without hidden-world revelation"],
                    "rolling_summary": "Ren is still in the mundane testing phase.",
                }
            )
        if "Score the longitudinal story state" in prompt:
            return json.dumps(
                {
                    "continuity": 80,
                    "character_consistency": 81,
                    "progression_consistency": 82,
                    "setup_payoff": 83,
                    "causal_traceability": 84,
                    "intent_retention": 85,
                    "engagement": 86,
                    "contradiction_count": 1,
                    "unresolved_promised_thread_count": 2,
                    "rationale": "fixture",
                }
            )
        if "Blindly compare A and B" in prompt:
            return json.dumps({"preferred": "tie", "confidence": 0.5, "rationale": "fixture"})
        if "Synthesize a Chapter" in prompt:
            return json.dumps(
                {
                    "chapter_goal": "test safely",
                    "required_beats": ["experiment"],
                    "forbidden_moves": ["premature hidden world"],
                    "setup_payoff_links": [],
                    "state_changes_if_earned": [],
                    "intent_path_checks": ["still Ren"],
                }
            )
        return "# Chapter\n\nRen tested one more thing and wrote it down."


def test_extract_json_accepts_fenced_object():
    assert _extract_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_budget_rejects_extra_generation_call():
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=1)
    model.ask("a", condition="baseline", chapter=2, purpose="one")
    with pytest.raises(BudgetExceeded):
        model.ask("b", condition="baseline", chapter=2, purpose="two")


def test_runner_uses_exact_matched_generation_budget_and_mandatory_subagents(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=7)
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=7)
    runner = WebNovelBenchmarkRunner(
        seed="canonical seed",
        contract="benchmark contract",
        output_dir=tmp_path / "run",
        model=model,
        config=config,
    )

    runner.run()

    assert model.generation_count("baseline", 2) == 7
    assert model.generation_count("kingdom", 2) == 7
    baseline_generation = [
        record for record in model.records
        if record.condition == "baseline" and record.budget_class == "generation"
    ]
    kingdom_generation = [
        record for record in model.records
        if record.condition == "kingdom" and record.budget_class == "generation"
    ]
    assert len(baseline_generation) == len(kingdom_generation) == 7
    assert not any(record.purpose.startswith("subagent:") for record in baseline_generation)
    assert {
        "subagent:continuity",
        "subagent:progression_economics",
        "subagent:character_theme",
        "subagent:adversarial",
        "subagent:synthesis",
    }.issubset({record.purpose for record in kingdom_generation})
    assert (tmp_path / "run" / "baseline" / "chapters" / "chapter_0002.md").is_file()
    assert (tmp_path / "run" / "kingdom" / "chapters" / "chapter_0002.md").is_file()
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["model"] == "same-model"
    assert manifest["generation_calls_per_chapter_per_condition"] == 7


def test_checkpoint_artifact_records_delta_and_blind_comparison(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=7)
    config = BenchmarkConfig(chapters=2, checkpoints=(2,), generation_calls_per_chapter=7)
    runner = WebNovelBenchmarkRunner(
        seed="canonical seed",
        contract="benchmark contract",
        output_dir=tmp_path / "run",
        model=model,
        config=config,
    )

    runner.run()

    checkpoint = json.loads(
        (tmp_path / "run" / "checkpoints" / "checkpoint_0002.json").read_text()
    )
    assert checkpoint["baseline"]["total"] == 83.0
    assert checkpoint["kingdom"]["total"] == 83.0
    assert checkpoint["kingdom_minus_baseline_total"] == 0.0
    assert checkpoint["pairwise_blind"]["preferred"] == "TIE"
    result = (tmp_path / "run" / "RESULT.md").read_text()
    assert "A single higher score at Chapter 10 is not sufficient" in result


def test_resume_refuses_changed_seed(tmp_path):
    fake = FakeAsk()
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=7)
    first_model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=7)
    first = WebNovelBenchmarkRunner(
        seed="seed one",
        contract="contract",
        output_dir=tmp_path / "run",
        model=first_model,
        config=config,
    )
    first.run()

    second_model = BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=7)
    changed = WebNovelBenchmarkRunner(
        seed="seed two",
        contract="contract",
        output_dir=tmp_path / "run",
        model=second_model,
        config=config,
    )
    with pytest.raises(RuntimeError, match="seed_sha256 changed"):
        changed.run()
