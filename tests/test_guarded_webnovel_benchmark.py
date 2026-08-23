import json

import pytest

from kingdom.guarded_webnovel_benchmark import (
    GuardedStateExtractor,
    GuardedWebNovelBenchmarkRunner,
    TemporalStoryState,
)
from kingdom.webnovel_benchmark import BenchmarkConfig, BudgetedModel


class GuardAsk:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def __call__(self, prompt, *, role="default", timeout=None, model=None, system=None):
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def _state_payload(status, evidence, chapter):
    return {
        "facts": [],
        "character_states": [],
        "knowledge": [],
        "financial_state": [],
        "cultivation_state": [],
        "assets": [],
        "obligations": [],
        "mysteries": [],
        "themes": [],
        "tone": [],
        "chapter_summaries": [],
        "rolling_summary": "",
        "events": [
            {
                "event_id": "ask-father-thomas",
                "description": "Ren asks Father Thomas about the furnace",
                "status": status,
                "evidence": evidence,
                "chapter": chapter,
            }
        ],
    }


def _prior_planned():
    return TemporalStoryState.from_mapping(
        _state_payload(
            "planned",
            "Ren resolves to ask Father Thomas tomorrow.",
            1,
        )
    )


def test_guarded_extractor_rejects_future_plan_promoted_to_completed():
    evidence = "Ren resolves to ask Father Thomas tomorrow."
    fake = GuardAsk(_state_payload("completed", evidence, 2))
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=7)
    extractor = GuardedStateExtractor(
        model,
        seed="seed",
        contract="contract",
        config=BenchmarkConfig(chapters=2, checkpoints=()),
    )

    with pytest.raises(RuntimeError, match="future-oriented"):
        extractor.update(
            "baseline",
            2,
            _prior_planned(),
            evidence,
        )


def test_guarded_extractor_accepts_completed_event_with_current_evidence():
    evidence = "The next morning, Ren asked Father Thomas about the furnace."
    fake = GuardAsk(_state_payload("completed", evidence, 2))
    model = BudgetedModel(fake, model="same-model", generation_calls_per_chapter=7)
    extractor = GuardedStateExtractor(
        model,
        seed="seed",
        contract="contract",
        config=BenchmarkConfig(chapters=2, checkpoints=()),
    )

    state = extractor.update(
        "kingdom",
        2,
        _prior_planned(),
        f"{evidence} Father Thomas frowned.",
    )

    assert state.events[0]["status"] == "completed"
    assert model.records[-1].budget_class == "evaluation"


def test_temporal_story_state_round_trips_typed_events_into_prompt_view():
    state = _prior_planned()

    rendered = json.loads(state.prompt_view())

    assert rendered["events"][0]["event_id"] == "ask-father-thomas"
    assert rendered["events"][0]["status"] == "planned"


def test_guarded_manifest_rejects_legacy_resume(tmp_path):
    model = BudgetedModel(
        GuardAsk({}),
        model="same-model",
        generation_calls_per_chapter=7,
    )
    runner = GuardedWebNovelBenchmarkRunner(
        seed="seed",
        contract="contract",
        output_dir=tmp_path / "run",
        model=model,
        config=BenchmarkConfig(chapters=2, checkpoints=()),
    )

    runner._persist_manifest()
    manifest_path = tmp_path / "run" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["temporal_state_schema"] == 1
    assert manifest["temporal_evidence_required"] is True

    del manifest["temporal_state_schema"]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="use a fresh output directory"):
        runner._persist_manifest()
