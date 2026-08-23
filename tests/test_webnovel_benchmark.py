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
    build_parser,
)


class FakeAsk:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        prompt,
        *,
        role="default",
        timeout=None,
        model=None,
        system=None,
        options=None,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "role": role,
                "timeout": timeout,
                "model": model,
                "options": options,
            }
        )
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
        if "Create a concise conventional novelist's plan" in prompt:
            return "BASELINE_PLAN_MARKER"
        if "Create a structured dependency plan" in prompt:
            return json.dumps(
                {
                    "chapter_goal": "KINGDOM_PLAN_MARKER",
                    "required_beats": ["experiment"],
                    "forbidden_moves": ["premature hidden world"],
                    "setup_payoff_links": [],
                    "state_changes_if_earned": [],
                    "intent_path_checks": ["still Ren"],
                }
            )
        if "CONVENTIONAL CHAPTER PLAN" in prompt and "CURRENT CHAPTER" not in prompt:
            return "# BASELINE_DRAFT_MARKER\n\nRen tested one more thing."
        if "STRUCTURED DEPENDENCY PLAN" in prompt and "DRAFT CHAPTER" not in prompt:
            return "# KINGDOM_DRAFT_MARKER\n\nRen tested one more thing."
        if "CONVENTIONAL CHAPTER PLAN" in prompt and "CURRENT CHAPTER" in prompt:
            return "# BASELINE_FINAL_MARKER\n\nRen recorded the result."
        if "STRUCTURED DEPENDENCY PLAN" in prompt and "DRAFT CHAPTER" in prompt:
            return "# KINGDOM_FINAL_MARKER\n\nRen recorded the result."
        return "# Chapter\n\nRen tested one more thing and wrote it down."


def test_extract_json_accepts_fenced_object():
    assert _extract_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_budget_rejects_extra_generation_call():
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=1)
    model.ask("a", condition="baseline", chapter=2, purpose="one")
    with pytest.raises(BudgetExceeded):
        model.ask("b", condition="baseline", chapter=2, purpose="two")


def test_budgeted_model_forces_identical_full_context_runtime_settings():
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=1)

    model.ask("baseline", condition="baseline", chapter=2, purpose="draft")
    model.ask(
        "kingdom",
        condition="kingdom",
        chapter=2,
        purpose="structured dependency plan",
        role="planner",
    )
    model.ask(
        "evaluation",
        condition="shared",
        chapter=2,
        purpose="automatic checkpoint score",
        budget_class="evaluation",
        role="reflector",
    )

    assert {call["model"] for call in fake.calls} == {"same-model"}
    assert {call["timeout"] for call in fake.calls} == {900}
    assert {call["options"]["num_ctx"] for call in fake.calls} == {32768}
    assert {call["options"]["num_predict"] for call in fake.calls} == {2048}
    assert {record.request_timeout_seconds for record in model.records} == {900}
    assert {record.ollama_num_ctx for record in model.records} == {32768}
    assert {record.ollama_num_predict for record in model.records} == {2048}


def test_runner_uses_exact_matched_budget_and_stage_matched_pipelines(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    runner = WebNovelBenchmarkRunner(
        seed="canonical seed",
        contract="benchmark contract",
        output_dir=tmp_path / "run",
        model=model,
        config=config,
    )

    runner.run()

    assert model.generation_count("baseline", 2) == 3
    assert model.generation_count("kingdom", 2) == 3
    baseline_generation = [
        record for record in model.records
        if record.condition == "baseline" and record.budget_class == "generation"
    ]
    kingdom_generation = [
        record for record in model.records
        if record.condition == "kingdom" and record.budget_class == "generation"
    ]
    assert len(baseline_generation) == len(kingdom_generation) == 3
    assert [record.purpose for record in baseline_generation] == [
        "conventional chapter plan",
        "sequential prose draft",
        "final conventional revision",
    ]
    assert [record.purpose for record in kingdom_generation] == [
        "structured dependency plan",
        "prose synthesis",
        "critical-path prose revision",
    ]

    baseline_prompts = [
        call["prompt"] for call in fake.calls
        if "CONVENTIONAL ROLLING MEMORY" in call["prompt"]
        and "Extract the post-chapter narrative state" not in call["prompt"]
    ]
    kingdom_prompts = [
        call["prompt"] for call in fake.calls
        if "PERSISTENT NARRATIVE STATE" in call["prompt"]
    ]
    assert len(baseline_prompts) == len(kingdom_prompts) == 3
    assert "BASELINE_PLAN_MARKER" in baseline_prompts[1]
    assert "BASELINE_PLAN_MARKER" in baseline_prompts[2]
    assert "BASELINE_DRAFT_MARKER" in baseline_prompts[2]
    assert "KINGDOM_PLAN_MARKER" in kingdom_prompts[1]
    assert "KINGDOM_PLAN_MARKER" in kingdom_prompts[2]
    assert "KINGDOM_DRAFT_MARKER" in kingdom_prompts[2]
    assert not any(
        "Kingdom" in prompt or "Critical-Path" in prompt or "dependency plan" in prompt
        for prompt in baseline_prompts
    )
    assert (tmp_path / "run" / "baseline" / "chapters" / "chapter_0002.md").is_file()
    assert (tmp_path / "run" / "kingdom" / "chapters" / "chapter_0002.md").is_file()
    assert "BASELINE_FINAL_MARKER" in (
        tmp_path / "run" / "baseline" / "chapters" / "chapter_0002.md"
    ).read_text()
    assert "KINGDOM_FINAL_MARKER" in (
        tmp_path / "run" / "kingdom" / "chapters" / "chapter_0002.md"
    ).read_text()
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["model"] == "same-model"
    assert manifest["schema_version"] == 2
    assert manifest["generation_protocol"] == "adi-001-3call-v1"
    assert manifest["generation_calls_per_chapter_per_condition"] == 3
    assert manifest["baseline_generation_pipeline"] == [
        "conventional chapter plan",
        "sequential prose draft",
        "final conventional revision",
    ]
    assert manifest["kingdom_generation_pipeline"] == [
        "structured dependency plan",
        "prose synthesis",
        "critical-path prose revision",
    ]
    assert manifest["ollama_num_ctx"] == 32768
    assert manifest["ollama_num_predict"] == 2048
    assert manifest["request_timeout_seconds"] == 900


def test_checkpoint_artifact_records_delta_and_blind_comparison(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=2, checkpoints=(2,), generation_calls_per_chapter=3)
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
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    first_model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    first = WebNovelBenchmarkRunner(
        seed="seed one",
        contract="contract",
        output_dir=tmp_path / "run",
        model=first_model,
        config=config,
    )
    first.run()

    second_model = BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3)
    changed = WebNovelBenchmarkRunner(
        seed="seed two",
        contract="contract",
        output_dir=tmp_path / "run",
        model=second_model,
        config=config,
    )
    with pytest.raises(RuntimeError, match="seed_sha256 changed"):
        changed.run()


def test_runner_rejects_non_protocol_generation_budget(tmp_path):
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=7)
    runner = WebNovelBenchmarkRunner(
        seed="seed",
        contract="contract",
        output_dir=tmp_path / "run",
        model=BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=7),
        config=config,
    )

    with pytest.raises(ValueError, match="requires exactly 3 generation calls"):
        runner.run()


def test_parser_locks_generation_budget_to_three():
    parser = build_parser()
    argv = [
        "--seed-file", "seed.md",
        "--benchmark-file", "contract.md",
        "--output-dir", "run",
        "--generation-calls", "7",
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(argv)


def test_resume_refuses_changed_generation_protocol_manifest(tmp_path):
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    first = WebNovelBenchmarkRunner(
        seed="seed",
        contract="contract",
        output_dir=tmp_path / "run",
        model=BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3),
        config=config,
    )
    first.run()

    manifest_path = tmp_path / "run" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["generation_protocol"] = "different-protocol"
    manifest_path.write_text(json.dumps(manifest))

    second = WebNovelBenchmarkRunner(
        seed="seed",
        contract="contract",
        output_dir=tmp_path / "run",
        model=BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3),
        config=config,
    )
    with pytest.raises(RuntimeError, match="generation_protocol changed"):
        second.run()


def test_clean_ten_chapter_run_has_exact_78_call_ledger(tmp_path):
    model = BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3)
    runner = WebNovelBenchmarkRunner(
        seed="seed",
        contract="contract",
        output_dir=tmp_path / "run",
        model=model,
        config=BenchmarkConfig(
            chapters=10,
            checkpoints=(5, 10),
            generation_calls_per_chapter=3,
        ),
    )

    runner.run()

    generation = [record for record in model.records if record.budget_class == "generation"]
    evaluation = [record for record in model.records if record.budget_class == "evaluation"]
    assert len(generation) == 54
    assert len([record for record in generation if record.condition == "baseline"]) == 27
    assert len([record for record in generation if record.condition == "kingdom"]) == 27
    assert len(evaluation) == 24
    assert len([
        record for record in evaluation
        if record.purpose == "shared post-chapter state extraction"
    ]) == 18
    assert len([
        record for record in evaluation
        if record.purpose == "automatic checkpoint score"
    ]) == 4
    assert len([
        record for record in evaluation
        if record.purpose == "blind automatic pairwise comparison"
    ]) == 2
    assert len(model.records) == 78
    assert len((tmp_path / "run" / "calls.jsonl").read_text().splitlines()) == 78
