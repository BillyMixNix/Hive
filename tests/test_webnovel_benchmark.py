import json
import re
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
from kingdom.adi_story_boundary import load_adi_story_boundary


BENCHMARK_DIR = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "adi_001_richest_man_breathing"
)


def benchmark_inputs(*, extend_frontiers=False):
    seed = (BENCHMARK_DIR / "SEED.md").read_text(encoding="utf-8")
    contract = (BENCHMARK_DIR / "CONTRACT.md").read_text(encoding="utf-8")
    source_map_text = (BENCHMARK_DIR / "STORY_MAP.json").read_text(encoding="utf-8")
    if extend_frontiers:
        source_map = json.loads(source_map_text)
        for chapter in range(3, 11):
            key = str(chapter)
            source_map["chapter_frontiers"][key] = list(
                source_map["chapter_frontiers"]["2"]
            )
            source_map["locked_terms_by_chapter"][key] = list(
                source_map["locked_terms_by_chapter"]["2"]
            )
            source_map["forbidden_patterns_by_chapter"][key] = [
                dict(item)
                for item in source_map["forbidden_patterns_by_chapter"]["2"]
            ]
        source_map_text = json.dumps(source_map, ensure_ascii=False, sort_keys=True)
    boundary = load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=source_map_text,
    )
    return seed, contract, boundary


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
        max_retries=None,
        metadata=None,
    ):
        if metadata is not None:
            metadata.update(
                {
                    "physical_attempts": 1,
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 10,
                    "eval_count": 20,
                }
            )
        self.calls.append(
            {
                "prompt": prompt,
                "role": role,
                "timeout": timeout,
                "model": model,
                "options": options,
                "max_retries": max_retries,
            }
        )
        if "state DELTA PROPOSER" in prompt:
            chapter = int(
                re.search(
                    r'The exact top-level schema is: \{"schema_version": 1, "chapter": (\d+)',
                    prompt,
                ).group(1)
            )
            source_hash = re.search(r'source_sha256 must be "([0-9a-f]{64})"', prompt).group(1)
            source_id = f"chapter:{chapter:04d}"
            evidence = "Ren recorded the result."
            claim = {
                "claim_id": f"ch{chapter}.fact.recorded",
                "statement": evidence,
                "status": "current",
                "depends_on": [],
                "evidence": {
                    "source_id": source_id,
                    "source_sha256": source_hash,
                    "chapter": chapter,
                    "quote": evidence,
                },
            }
            summary = {
                "claim_id": f"ch{chapter}.summary.recorded",
                "statement": evidence,
                "status": "current",
                "depends_on": [claim["claim_id"]],
                "evidence": dict(claim["evidence"]),
            }
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
            categories["facts"] = [claim]
            categories["chapter_summaries"] = [summary]
            return json.dumps(
                {"schema_version": 1, "chapter": chapter, "claims": categories}
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
            return "# BASELINE_FINAL_MARKER\n\nAt the Walmart parking lot, Ren steadied his breath. Ren recorded the result."
        if "STRUCTURED DEPENDENCY PLAN" in prompt and "DRAFT CHAPTER" in prompt:
            return "# KINGDOM_FINAL_MARKER\n\nAt the Walmart parking lot, Ren steadied his breath. Ren recorded the result."
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
    assert {call["options"]["temperature"] for call in fake.calls} == {0.2}
    assert {call["options"]["seed"] for call in fake.calls} == {42001}
    assert {call["max_retries"] for call in fake.calls} == {1}
    assert {record.request_timeout_seconds for record in model.records} == {900}
    assert {record.ollama_num_ctx for record in model.records} == {32768}
    assert {record.ollama_num_predict for record in model.records} == {2048}
    assert {record.ollama_temperature for record in model.records} == {0.2}
    assert {record.ollama_seed for record in model.records} == {42001}
    assert {record.physical_attempts for record in model.records} == {1}
    assert {record.transport_done_reason for record in model.records} == {"stop"}


def test_budgeted_model_records_failed_physical_request():
    def failing_ask(prompt, *, metadata=None, **kwargs):
        if metadata is not None:
            metadata.update(
                {
                    "physical_attempts": 1,
                    "done": False,
                    "done_reason": "transport_error",
                }
            )
        raise TimeoutError("fixture timeout")

    model = BudgetedModel(
        failing_ask,
        model="same-model",
        generation_calls_per_chapter=3,
    )

    with pytest.raises(TimeoutError, match="fixture timeout"):
        model.ask(
            "prompt",
            condition="baseline",
            chapter=2,
            purpose="conventional chapter plan",
        )

    assert len(model.records) == 1
    record = model.records[0]
    assert record.physical_attempts == 1
    assert record.transport_done is False
    assert record.error_type == "TimeoutError"
    assert record.response_chars == 0


def test_runner_fails_before_writing_when_requested_frontiers_are_not_frozen(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=3, checkpoints=(), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()
    output_dir = tmp_path / "missing-frontier"
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=output_dir,
        model=model,
        config=config,
    )

    with pytest.raises(ValueError, match="frontiers for Chapters 3"):
        runner.run()

    assert fake.calls == []
    assert not output_dir.exists()


def test_direct_runner_rejects_seed_or_contract_outside_frozen_boundary(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()

    with pytest.raises(ValueError, match="runner seed"):
        WebNovelBenchmarkRunner(
            seed=seed + "changed",
            contract=contract,
            story_boundary=boundary,
            output_dir=tmp_path / "run",
            model=model,
            config=config,
        )


def test_runner_uses_exact_matched_budget_and_stage_matched_pipelines(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
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
        if "CONVENTIONAL PRIOR-CHAPTER MEMORY" in call["prompt"]
        and "state DELTA PROPOSER" not in call["prompt"]
    ]
    kingdom_prompts = [
        call["prompt"] for call in fake.calls
        if "KINGDOM STRUCTURED CLAIM LEDGER" in call["prompt"]
        and "state DELTA PROPOSER" not in call["prompt"]
    ]
    assert len(baseline_prompts) == len(kingdom_prompts) == 3
    shared_authority = boundary.shared_writer_packet(chapter=2)
    assert all(prompt.startswith(shared_authority) for prompt in baseline_prompts)
    assert all(prompt.startswith(shared_authority) for prompt in kingdom_prompts)
    assert "BASELINE_PLAN_MARKER" in baseline_prompts[1]
    assert "BASELINE_PLAN_MARKER" in baseline_prompts[2]
    assert "BASELINE_DRAFT_MARKER" in baseline_prompts[2]
    assert "KINGDOM_PLAN_MARKER" in kingdom_prompts[1]
    assert "KINGDOM_PLAN_MARKER" in kingdom_prompts[2]
    assert "KINGDOM_DRAFT_MARKER" in kingdom_prompts[2]
    assert all("SHARED STATIC STORY AUTHORITY PACKET" in prompt for prompt in baseline_prompts)
    assert all("SHARED STATIC STORY AUTHORITY PACKET" in prompt for prompt in kingdom_prompts)
    assert all('"provenance"' not in prompt for prompt in baseline_prompts)
    assert all('"provenance"' in prompt for prompt in kingdom_prompts)
    assert not any(
        "Kingdom" in prompt or "Critical-Path" in prompt or "dependency plan" in prompt
        for prompt in baseline_prompts
    )
    extractor_prompts = [
        call["prompt"]
        for call in fake.calls
        if "state DELTA PROPOSER" in call["prompt"]
    ]
    assert len(extractor_prompts) == 2
    assert extractor_prompts[0].split("FINAL CHAPTER", 1)[0] == extractor_prompts[1].split(
        "FINAL CHAPTER", 1
    )[0]
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
    assert manifest["model_digest"] == "unverified-test-double"
    assert manifest["schema_version"] == 3
    assert manifest["generation_protocol"] == "adi-001-3call-story-map-v1"
    assert manifest["story_boundary_protocol"] == "adi-story-boundary-v1"
    assert manifest["story_map_sha256"] == boundary.source_map_sha256
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
    assert manifest["ollama_temperature"] == 0.2
    assert manifest["ollama_seed"] == 42001
    assert manifest["request_timeout_seconds"] == 900
    assert manifest["transport_attempt_limit"] == 1
    assert (tmp_path / "run" / "baseline" / "artifacts" / "chapter_0002.json").is_file()
    assert (tmp_path / "run" / "kingdom" / "artifacts" / "chapter_0002.json").is_file()


def test_checkpoint_artifact_records_delta_and_blind_comparison(tmp_path):
    fake = FakeAsk()
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    config = BenchmarkConfig(chapters=2, checkpoints=(2,), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
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
    assert len(checkpoint["call_records"]) == 3
    assert len(model.records) == 11
    assert sum(record.budget_class == "generation" for record in model.records) == 6
    assert sum(record.purpose == "shared Story Map state extraction" for record in model.records) == 2
    assert sum(record.purpose == "automatic checkpoint score" for record in model.records) == 2
    assert sum(record.purpose == "blind automatic pairwise comparison" for record in model.records) == 1
    assert {record.physical_attempts for record in model.records} == {1}
    ledger = [
        json.loads(line)
        for line in (tmp_path / "run" / "calls.jsonl").read_text().splitlines()
    ]
    assert len(ledger) == 11
    assert sum(row["budget_class"] == "generation" for row in ledger) == 6
    assert all(row["physical_attempts"] == 1 for row in ledger)
    result = (tmp_path / "run" / "RESULT.md").read_text()
    assert "A single higher score at Chapter 10 is not sufficient" in result


def test_failed_checkpoint_is_preserved_and_cannot_be_silently_resumed(tmp_path):
    class PairwiseFailure(FakeAsk):
        def __call__(self, prompt, *, metadata=None, **kwargs):
            if "Blindly compare A and B" in prompt:
                if metadata is not None:
                    metadata.update(
                        {
                            "physical_attempts": 1,
                            "done": False,
                            "done_reason": "transport_error",
                        }
                    )
                raise TimeoutError("pairwise fixture timeout")
            return super().__call__(prompt, metadata=metadata, **kwargs)

    seed, contract, boundary = benchmark_inputs()
    config = BenchmarkConfig(chapters=2, checkpoints=(2,), generation_calls_per_chapter=3)
    output_dir = tmp_path / "run"
    first = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=output_dir,
        model=BudgetedModel(
            PairwiseFailure(), model="same-model", generation_calls_per_chapter=3
        ),
        config=config,
    )

    with pytest.raises(TimeoutError, match="pairwise fixture timeout"):
        first.run()

    ledger = [json.loads(line) for line in (output_dir / "calls.jsonl").read_text().splitlines()]
    assert len(ledger) == 11
    assert ledger[-1]["error_type"] == "TimeoutError"
    assert not (output_dir / "checkpoints" / "checkpoint_0002.json").exists()

    resumed_ask = FakeAsk()
    resumed = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=output_dir,
        model=BudgetedModel(
            resumed_ask, model="same-model", generation_calls_per_chapter=3
        ),
        config=config,
    )
    with pytest.raises(RuntimeError, match="missing its checkpoint"):
        resumed.run()
    assert resumed_ask.calls == []
    assert not (output_dir / "RESULT.md").exists()


def test_resume_refuses_changed_seed(tmp_path):
    fake = FakeAsk()
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()
    first_model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=3)
    first = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=tmp_path / "run",
        model=first_model,
        config=config,
    )
    first.run()

    manifest_path = tmp_path / "run" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["seed_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))

    second_model = BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3)
    changed = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=tmp_path / "run",
        model=second_model,
        config=config,
    )
    with pytest.raises(RuntimeError, match="seed_sha256 changed"):
        changed.run()


def test_runner_rejects_non_protocol_generation_budget(tmp_path):
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=7)
    seed, contract, boundary = benchmark_inputs()
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
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
        "--story-map-file", "story-map.json",
        "--output-dir", "run",
        "--generation-calls", "7",
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(argv)


def test_parser_preserves_original_command_with_sibling_story_map_default():
    args = build_parser().parse_args(
        [
            "--seed-file",
            "benchmark/SEED.md",
            "--benchmark-file",
            "benchmark/CONTRACT.md",
            "--output-dir",
            "run",
            "--chapters",
            "2",
            "--checkpoint",
            "2",
        ]
    )

    assert args.story_map_file is None
    assert args.generation_calls == 3


def test_resume_refuses_changed_generation_protocol_manifest(tmp_path):
    config = BenchmarkConfig(chapters=2, checkpoints=(), generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs()
    first = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
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
        seed=seed,
        contract=contract,
        story_boundary=boundary,
        output_dir=tmp_path / "run",
        model=BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3),
        config=config,
    )
    with pytest.raises(RuntimeError, match="generation_protocol changed"):
        second.run()


def test_clean_ten_chapter_run_has_exact_78_call_ledger(tmp_path):
    model = BudgetedModel(FakeAsk(), model="same-model", generation_calls_per_chapter=3)
    seed, contract, boundary = benchmark_inputs(extend_frontiers=True)
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=boundary,
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
        if record.purpose == "shared Story Map state extraction"
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
