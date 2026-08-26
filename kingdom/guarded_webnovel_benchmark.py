from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .temporal_guard import (
    TemporalEvent,
    temporal_events_from_mapping,
    validate_temporal_transition,
)
from .webnovel_benchmark import (
    DEFAULT_CHECKPOINTS,
    DEFAULT_GENERATION_CALLS,
    STATE_FIELDS,
    BenchmarkConfig,
    BudgetedModel,
    StoryState,
    WebNovelBenchmarkRunner,
    _clip,
    _extract_json,
)


@dataclass
class TemporalStoryState(StoryState):
    """Story state with typed event status and provenance evidence."""

    events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TemporalStoryState":
        base = StoryState.from_mapping(value)
        raw_events = value.get("events", [])
        events: list[dict[str, Any]] = []
        if isinstance(raw_events, list):
            for raw in raw_events:
                if not isinstance(raw, Mapping):
                    continue
                event = TemporalEvent.from_mapping(raw)
                events.append(
                    {
                        "event_id": event.event_id,
                        "description": event.description,
                        "status": event.status,
                        "evidence": event.evidence,
                        "chapter": event.chapter,
                    }
                )
        return cls(**asdict(base), events=events)

    def prompt_view(self, *, max_entries: int = 50) -> str:
        payload = asdict(self)
        for name in STATE_FIELDS:
            payload[name] = payload[name][-max_entries:]
        payload["events"] = payload["events"][-max_entries:]
        return json.dumps(payload, indent=2, ensure_ascii=False)


class GuardedStateExtractor:
    """Shared state extractor that refuses unsupported temporal promotions."""

    def __init__(self, model: BudgetedModel, seed: str, contract: str, config: BenchmarkConfig):
        self.model = model
        self.seed = seed
        self.contract = contract
        self.config = config

    def update(
        self,
        condition: str,
        chapter: int,
        prior: StoryState,
        text: str,
    ) -> TemporalStoryState:
        if isinstance(prior, TemporalStoryState):
            temporal_prior = prior
        else:
            temporal_prior = TemporalStoryState.from_mapping(asdict(prior))

        prompt = _clip(
            f"CANONICAL SEED:\n{self.seed}\n\nBENCHMARK CONTRACT:\n{self.contract}\n\n"
            f"PRIOR STATE:\n{temporal_prior.prompt_view()}\n\nCHAPTER {chapter}:\n{text}\n\n"
            "Extract the post-chapter narrative state as JSON. Preserve prior unresolved information unless the "
            "chapter actually changes/resolves it. Required keys: facts, character_states, knowledge, "
            "financial_state, cultivation_state, assets, obligations, mysteries, themes, tone, "
            "chapter_summaries, rolling_summary, events. Each category except rolling_summary and events is a "
            "list of concise strings. rolling_summary must be a compact conventional writer memory of at most "
            "roughly 1200 words. events must be a list of objects with exactly: event_id, description, status, "
            "evidence, chapter. status must be one of planned, attempted, completed, failed, cancelled. Preserve "
            "stable event_id values across chapters. evidence must be a short verbatim quote from the CURRENT "
            "chapter when an event changes status; do not cite the seed, prior state, or a future plan as evidence "
            "that an event completed. A plan, intention, promise, decision, or 'tomorrow' statement is planned, "
            "not completed. Do not invent events not in the prose.",
            self.config.context_char_limit,
        )
        raw = self.model.ask(
            prompt,
            condition=condition,
            chapter=chapter,
            purpose="shared guarded post-chapter state extraction",
            role="reflector",
            budget_class="evaluation",
        )
        try:
            candidate = TemporalStoryState.from_mapping(_extract_json(raw))
            validate_temporal_transition(
                temporal_events_from_mapping(temporal_prior.events),
                temporal_events_from_mapping(candidate.events),
                chapter_text=text,
                chapter=chapter,
            )
            return candidate
        except Exception as exc:
            raise RuntimeError(
                f"guarded state extractor rejected {condition} chapter {chapter}: {exc}"
            ) from exc


class GuardedWebNovelBenchmarkRunner(WebNovelBenchmarkRunner):
    """ADI benchmark runner with temporal evidence as a hard state invariant."""

    def __init__(
        self,
        *,
        seed: str,
        contract: str,
        output_dir: Path,
        model: BudgetedModel,
        config: BenchmarkConfig,
    ):
        super().__init__(
            seed=seed,
            contract=contract,
            output_dir=output_dir,
            model=model,
            config=config,
        )
        self.extractor = GuardedStateExtractor(model, seed, contract, config)

    def _persist_manifest(self) -> None:
        path = self.output_dir / "manifest.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("temporal_state_schema") != 1:
                raise RuntimeError(
                    "refusing guarded resume: manifest lacks temporal_state_schema=1; "
                    "use a fresh output directory"
                )
        super()._persist_manifest()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["temporal_state_schema"] = 1
        manifest["temporal_evidence_required"] = True
        path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _load_state(self, condition: str) -> TemporalStoryState:
        path = self._state_path(condition)
        if not path.exists():
            return TemporalStoryState()
        return TemporalStoryState.from_mapping(json.loads(path.read_text(encoding="utf-8")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ADI-001 with hard temporal-state evidence validation"
    )
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chapters", type=int, default=10)
    parser.add_argument("--checkpoint", action="append", type=int, dest="checkpoints")
    parser.add_argument("--generation-calls", type=int, default=DEFAULT_GENERATION_CALLS)
    parser.add_argument("--context-chars", type=int, default=120_000)
    parser.add_argument(
        "--model",
        default=None,
        help="Explicit same model for both conditions; defaults to Hive DEFAULT_MODEL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from hive_llm import DEFAULT_MODEL, ask_hive

    seed = args.seed_file.read_text(encoding="utf-8")
    contract = args.benchmark_file.read_text(encoding="utf-8")
    checkpoints = tuple(sorted(set(args.checkpoints or DEFAULT_CHECKPOINTS)))
    checkpoints = tuple(value for value in checkpoints if 2 <= value <= args.chapters)
    config = BenchmarkConfig(
        chapters=args.chapters,
        checkpoints=checkpoints,
        generation_calls_per_chapter=args.generation_calls,
        context_char_limit=args.context_chars,
    )
    model = BudgetedModel(
        ask_hive,
        model=args.model or DEFAULT_MODEL,
        generation_calls_per_chapter=config.generation_calls_per_chapter,
    )
    runner = GuardedWebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        output_dir=args.output_dir,
        model=model,
        config=config,
    )
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
