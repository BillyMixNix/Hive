from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


DEFAULT_GENERATION_CALLS = 3
DEFAULT_CHECKPOINTS = (5, 10)
DEFAULT_OLLAMA_NUM_CTX = 32_768
DEFAULT_OLLAMA_NUM_PREDICT = 2_048
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900
GENERATION_PROTOCOL_ID = "adi-001-3call-v1"
BASELINE_GENERATION_PIPELINE = (
    "conventional chapter plan",
    "sequential prose draft",
    "final conventional revision",
)
KINGDOM_GENERATION_PIPELINE = (
    "structured dependency plan",
    "prose synthesis",
    "critical-path prose revision",
)
STATE_FIELDS = (
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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = max(1, (limit - 80) // 2)
    return text[:half] + "\n\n...[context clipped by harness]...\n\n" + text[-half:]


class AskFunction(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        role: str = "default",
        timeout: int | None = None,
        model: str | None = None,
        system: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class ModelCallRecord:
    condition: str
    chapter: int
    purpose: str
    role: str
    model: str
    request_timeout_seconds: int
    ollama_num_ctx: int
    ollama_num_predict: int
    prompt_sha256: str
    response_sha256: str
    prompt_chars: int
    response_chars: int
    elapsed_seconds: float
    budget_class: str


class BudgetExceeded(RuntimeError):
    pass


class BudgetedModel:
    """Tracks generation and evaluation calls so the A/B comparison is auditable."""

    def __init__(
        self,
        ask: AskFunction,
        *,
        model: str,
        generation_calls_per_chapter: int = DEFAULT_GENERATION_CALLS,
        ollama_num_ctx: int = DEFAULT_OLLAMA_NUM_CTX,
        ollama_num_predict: int = DEFAULT_OLLAMA_NUM_PREDICT,
        request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        self.ask_fn = ask
        self.model = model
        self.generation_calls_per_chapter = generation_calls_per_chapter
        self.ollama_num_ctx = ollama_num_ctx
        self.ollama_num_predict = ollama_num_predict
        self.request_timeout_seconds = request_timeout_seconds
        self.records: list[ModelCallRecord] = []
        self._generation_counts: dict[tuple[str, int], int] = {}

    def ask(
        self,
        prompt: str,
        *,
        condition: str,
        chapter: int,
        purpose: str,
        role: str = "default",
        budget_class: str = "generation",
    ) -> str:
        if budget_class == "generation":
            key = (condition, chapter)
            used = self._generation_counts.get(key, 0)
            if used >= self.generation_calls_per_chapter:
                raise BudgetExceeded(
                    f"{condition} chapter {chapter} exceeded generation call budget "
                    f"({self.generation_calls_per_chapter})"
                )
            self._generation_counts[key] = used + 1

        started = time.monotonic()
        response = self.ask_fn(
            prompt,
            role=role,
            timeout=self.request_timeout_seconds,
            model=self.model,
            options={
                "num_ctx": self.ollama_num_ctx,
                "num_predict": self.ollama_num_predict,
            },
        )
        elapsed = time.monotonic() - started
        self.records.append(
            ModelCallRecord(
                condition=condition,
                chapter=chapter,
                purpose=purpose,
                role=role,
                model=self.model,
                request_timeout_seconds=self.request_timeout_seconds,
                ollama_num_ctx=self.ollama_num_ctx,
                ollama_num_predict=self.ollama_num_predict,
                prompt_sha256=_sha256_text(prompt),
                response_sha256=_sha256_text(response),
                prompt_chars=len(prompt),
                response_chars=len(response),
                elapsed_seconds=round(elapsed, 6),
                budget_class=budget_class,
            )
        )
        return response

    def generation_count(self, condition: str, chapter: int) -> int:
        return self._generation_counts.get((condition, chapter), 0)


@dataclass
class StoryState:
    facts: list[str] = field(default_factory=list)
    character_states: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    financial_state: list[str] = field(default_factory=list)
    cultivation_state: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    mysteries: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    tone: list[str] = field(default_factory=list)
    chapter_summaries: list[str] = field(default_factory=list)
    rolling_summary: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoryState":
        kwargs: dict[str, Any] = {}
        for name in STATE_FIELDS:
            raw = value.get(name, [])
            if isinstance(raw, list):
                kwargs[name] = [str(item).strip() for item in raw if str(item).strip()]
            else:
                kwargs[name] = []
        kwargs["rolling_summary"] = str(value.get("rolling_summary") or "").strip()
        return cls(**kwargs)

    def prompt_view(self, *, max_entries: int = 50) -> str:
        payload = asdict(self)
        for name in STATE_FIELDS:
            payload[name] = payload[name][-max_entries:]
        return json.dumps(payload, indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class ChapterArtifact:
    condition: str
    number: int
    text: str
    sha256: str
    state: StoryState


@dataclass(frozen=True)
class CheckpointScore:
    condition: str
    chapter: int
    continuity: float
    character_consistency: float
    progression_consistency: float
    setup_payoff: float
    causal_traceability: float
    intent_retention: float
    engagement: float
    contradiction_count: int
    unresolved_promised_thread_count: int
    total: float
    rationale: str


@dataclass(frozen=True)
class PairwisePreference:
    chapter: int
    label_a: str
    label_b: str
    preferred: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class BenchmarkConfig:
    benchmark_id: str = "ADI-001"
    title: str = "I Became the World's Richest Man by Breathing"
    chapters: int = 10
    checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS
    generation_calls_per_chapter: int = DEFAULT_GENERATION_CALLS
    context_char_limit: int = 120_000


class BaselineWriter:
    """Stage-matched conventional writer: ordinary plan, prose draft, holistic revision."""

    def __init__(self, model: BudgetedModel, seed: str, contract: str, config: BenchmarkConfig):
        self.model = model
        self.seed = seed
        self.contract = contract
        self.config = config

    def write(self, chapter: int, prior_state: StoryState, prior_tail: str) -> str:
        common = (
            f"CANONICAL HUMAN SEED (do not contradict):\n{self.seed}\n\n"
            f"BENCHMARK CONTRACT:\n{self.contract}\n\n"
            f"CONVENTIONAL ROLLING MEMORY:\n{prior_state.rolling_summary or '(none yet)'}\n\n"
            f"RECENT PROSE TAIL:\n{prior_tail or '(Chapter One is contained in the canonical seed.)'}\n\n"
        )
        plan = self.model.ask(
            _clip(
                common
                + f"Create a concise conventional novelist's plan for Chapter {chapter}. Continue naturally from the "
                  "existing novel using ordinary long-form reasoning. Cover the intended scene progression, character "
                  "work, continuity needs, and ending momentum. Return only a practical chapter plan, not prose.",
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose="conventional chapter plan",
            role="default",
        )
        draft = self.model.ask(
            _clip(
                common
                + f"CONVENTIONAL CHAPTER PLAN:\n{plan}\n\n"
                  f"Write Chapter {chapter} as finished serial-novel prose. Follow the plan where it remains consistent "
                  "with the supplied seed and memory. Return the complete chapter only.",
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose="sequential prose draft",
            role="default",
        )
        final = self.model.ask(
            _clip(
                common
                + f"CONVENTIONAL CHAPTER PLAN:\n{plan}\n\n"
                  f"CURRENT CHAPTER {chapter} DRAFT:\n{draft}\n\n"
                  "Perform one holistic conventional-novelist revision. Fix visible continuity, causality, pacing, "
                  "characterization, prose, and plan-to-draft problems using the supplied seed and memory. Preserve "
                  "earned story events and improve serial momentum. Return only the complete final chapter.",
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose="final conventional revision",
            role="default",
        )
        return final


class KingdomWriter:
    """Stage-matched decomposed writer: dependency plan, prose draft, Critical-Path revision."""

    def __init__(self, model: BudgetedModel, seed: str, contract: str, config: BenchmarkConfig):
        self.model = model
        self.seed = seed
        self.contract = contract
        self.config = config

    def write(self, chapter: int, state: StoryState, prior_tail: str) -> str:
        public_state = state.prompt_view()
        common = (
            f"CANONICAL HUMAN SEED (immutable intent):\n{self.seed}\n\n"
            f"BENCHMARK CONTRACT:\n{self.contract}\n\n"
            f"PERSISTENT NARRATIVE STATE:\n{public_state}\n\n"
            f"RECENT PROSE TAIL:\n{prior_tail or '(Chapter One is contained in the canonical seed.)'}\n\n"
        )
        plan = self.model.ask(
            _clip(
                common
                + f"Create a structured dependency plan for Chapter {chapter}. Decompress the chapter through these "
                  "lenses: continuity and chronology; who-knows-what; unresolved obligations and mysteries; "
                  "Money-Breathing math, finances, cultivation, assets, exchanges, and economic causality; Ren's "
                  "psychology and relationships; value-versus-price theme and tone trajectory; setup/payoff links; and "
                  "an adversarial search for lore leaks, unearned escalation, generic-system drift, or future damage. "
                  "Resolve conflicts against the immutable seed and persistent state. Return JSON with chapter_goal, "
                  "required_beats, forbidden_moves, setup_payoff_links, state_changes_if_earned, and intent_path_checks. "
                  "The plan is a proposal, not authority; do not write the chapter.",
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose="structured dependency plan",
            role="strategic",
        )

        draft = self.model.ask(
            _clip(
                common
                + f"STRUCTURED DEPENDENCY PLAN:\n{plan}\n\n"
                  f"Write Chapter {chapter} as finished webnovel prose. Earn progression; do not merely announce it. "
                  "Preserve Ren's voice and the comedy-to-serious trajectory. Treat the plan as subordinate to the "
                  "immutable seed and state. Return chapter prose only, with no planning notes.",
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose="prose synthesis",
            role="coder",
        )

        final = self.model.ask(
            _clip(
                common
                + f"STRUCTURED DEPENDENCY PLAN:\n{plan}\n\n"
                  f"DRAFT CHAPTER {chapter}:\n{draft}\n\n"
                  "Perform the terminal Critical-Path revision. Walk the immutable intent and dependency plan through "
                  "the actual prose. Repair every established contradiction, premature reveal, unearned escalation, "
                  "missing prerequisite, forgotten setup/payoff link, or thematic drift. A lower-level contradiction "
                  "cannot be waived by good prose. Return only the complete corrected chapter, with no plan, report, "
                  "explanation, or revision note.",
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose="critical-path prose revision",
            role="reflector",
        )
        return final


class StateExtractor:
    """Shared post-chapter extraction; same call is applied to both conditions."""

    def __init__(self, model: BudgetedModel, seed: str, contract: str, config: BenchmarkConfig):
        self.model = model
        self.seed = seed
        self.contract = contract
        self.config = config

    def update(self, condition: str, chapter: int, prior: StoryState, text: str) -> StoryState:
        prompt = _clip(
            f"CANONICAL SEED:\n{self.seed}\n\nBENCHMARK CONTRACT:\n{self.contract}\n\n"
            f"PRIOR STATE:\n{prior.prompt_view()}\n\nCHAPTER {chapter}:\n{text}\n\n"
            "Extract the post-chapter narrative state as JSON. Preserve prior unresolved information unless the chapter "
            "actually changes/resolves it. Required keys: facts, character_states, knowledge, financial_state, "
            "cultivation_state, assets, obligations, mysteries, themes, tone, chapter_summaries, rolling_summary. "
            "Each category except rolling_summary is a list of concise strings. rolling_summary must be a compact "
            "conventional writer memory of at most roughly 1200 words. Do not invent events not in the prose.",
            self.config.context_char_limit,
        )
        raw = self.model.ask(
            prompt,
            condition=condition,
            chapter=chapter,
            purpose="shared post-chapter state extraction",
            role="reflector",
            budget_class="evaluation",
        )
        try:
            return StoryState.from_mapping(_extract_json(raw))
        except Exception as exc:
            raise RuntimeError(
                f"state extractor returned malformed output for {condition} chapter {chapter}: {exc}"
            ) from exc


class CheckpointEvaluator:
    """Automatic evaluator. Useful for diagnostics, never a substitute for blind humans."""

    def __init__(self, model: BudgetedModel, seed: str, contract: str, config: BenchmarkConfig):
        self.model = model
        self.seed = seed
        self.contract = contract
        self.config = config

    def score(self, condition: str, chapter: int, state: StoryState) -> CheckpointScore:
        raw = self.model.ask(
            _clip(
                f"CANONICAL SEED:\n{self.seed}\n\nBENCHMARK CONTRACT:\n{self.contract}\n\n"
                f"POST-CHAPTER-{chapter} STATE FOR AN ANONYMOUS CONDITION:\n{state.prompt_view(max_entries=120)}\n\n"
                "Score the longitudinal story state. Return JSON only with numeric 0-100 keys continuity, "
                "character_consistency, progression_consistency, setup_payoff, causal_traceability, intent_retention, "
                "engagement; integer contradiction_count; integer unresolved_promised_thread_count; and rationale. "
                "Do not reward complexity or effort. Penalize premature lore, contradictions, forgotten promises, and "
                "a story that becomes generically different from the seed.",
                self.config.context_char_limit,
            ),
            condition=condition,
            chapter=chapter,
            purpose="automatic checkpoint score",
            role="reflector",
            budget_class="evaluation",
        )
        data = _extract_json(raw)
        dimensions = [
            float(data.get("continuity", 0)),
            float(data.get("character_consistency", 0)),
            float(data.get("progression_consistency", 0)),
            float(data.get("setup_payoff", 0)),
            float(data.get("causal_traceability", 0)),
            float(data.get("intent_retention", 0)),
            float(data.get("engagement", 0)),
        ]
        total = round(sum(dimensions) / len(dimensions), 3)
        return CheckpointScore(
            condition=condition,
            chapter=chapter,
            continuity=dimensions[0],
            character_consistency=dimensions[1],
            progression_consistency=dimensions[2],
            setup_payoff=dimensions[3],
            causal_traceability=dimensions[4],
            intent_retention=dimensions[5],
            engagement=dimensions[6],
            contradiction_count=int(data.get("contradiction_count", 0)),
            unresolved_promised_thread_count=int(data.get("unresolved_promised_thread_count", 0)),
            total=total,
            rationale=str(data.get("rationale") or ""),
        )

    def pairwise(
        self,
        chapter: int,
        baseline_state: StoryState,
        kingdom_state: StoryState,
        *,
        blind_seed: str,
    ) -> PairwisePreference:
        rng = random.Random(blind_seed + f":{chapter}")
        swap = bool(rng.getrandbits(1))
        if swap:
            label_a, state_a = "kingdom", kingdom_state
            label_b, state_b = "baseline", baseline_state
        else:
            label_a, state_a = "baseline", baseline_state
            label_b, state_b = "kingdom", kingdom_state
        raw = self.model.ask(
            _clip(
                f"CANONICAL SEED:\n{self.seed}\n\nBENCHMARK CONTRACT:\n{self.contract}\n\n"
                f"ANONYMOUS STORY A STATE AT CHAPTER {chapter}:\n{state_a.prompt_view(max_entries=120)}\n\n"
                f"ANONYMOUS STORY B STATE AT CHAPTER {chapter}:\n{state_b.prompt_view(max_entries=120)}\n\n"
                "Blindly compare A and B for long-horizon coherence, earned payoff, character consistency, progression "
                "logic, causal traceability, and original-intent retention. Return JSON only: preferred ('A', 'B', "
                "or 'tie'), confidence (0-1), rationale. Do not guess which architecture produced either story.",
                self.config.context_char_limit,
            ),
            condition="pairwise",
            chapter=chapter,
            purpose="blind automatic pairwise comparison",
            role="reflector",
            budget_class="evaluation",
        )
        data = _extract_json(raw)
        preferred = str(data.get("preferred") or "tie").upper()
        if preferred not in {"A", "B", "TIE"}:
            preferred = "TIE"
        return PairwisePreference(
            chapter=chapter,
            label_a=label_a,
            label_b=label_b,
            preferred=preferred,
            confidence=float(data.get("confidence", 0.0)),
            rationale=str(data.get("rationale") or ""),
        )


class WebNovelBenchmarkRunner:
    def __init__(
        self,
        *,
        seed: str,
        contract: str,
        output_dir: Path,
        model: BudgetedModel,
        config: BenchmarkConfig,
    ):
        self.seed = seed
        self.contract = contract
        self.output_dir = output_dir
        self.model = model
        self.config = config
        self.baseline = BaselineWriter(model, seed, contract, config)
        self.kingdom = KingdomWriter(model, seed, contract, config)
        self.extractor = StateExtractor(model, seed, contract, config)
        self.evaluator = CheckpointEvaluator(model, seed, contract, config)
        self.seed_hash = _sha256_text(seed)
        self.contract_hash = _sha256_text(contract)

    def _condition_dir(self, condition: str) -> Path:
        return self.output_dir / condition

    def _chapter_path(self, condition: str, chapter: int) -> Path:
        return self._condition_dir(condition) / "chapters" / f"chapter_{chapter:04d}.md"

    def _state_path(self, condition: str) -> Path:
        return self._condition_dir(condition) / "state.json"

    def _load_state(self, condition: str) -> StoryState:
        path = self._state_path(condition)
        if not path.exists():
            return StoryState()
        return StoryState.from_mapping(json.loads(path.read_text(encoding="utf-8")))

    def _last_completed_chapter(self, condition: str) -> int:
        folder = self._condition_dir(condition) / "chapters"
        if not folder.exists():
            return 1
        numbers = []
        for path in folder.glob("chapter_*.md"):
            try:
                numbers.append(int(path.stem.split("_")[-1]))
            except ValueError:
                continue
        return max(numbers, default=1)

    def _prior_tail(self, condition: str, chapter: int) -> str:
        previous = self._chapter_path(condition, chapter - 1)
        if not previous.exists():
            return ""
        return _clip(previous.read_text(encoding="utf-8"), 12_000)

    def _persist_manifest(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 2,
            "benchmark_id": self.config.benchmark_id,
            "title": self.config.title,
            "generation_protocol": GENERATION_PROTOCOL_ID,
            "baseline_generation_pipeline": list(BASELINE_GENERATION_PIPELINE),
            "kingdom_generation_pipeline": list(KINGDOM_GENERATION_PIPELINE),
            "seed_sha256": self.seed_hash,
            "contract_sha256": self.contract_hash,
            "model": self.model.model,
            "chapters": self.config.chapters,
            "checkpoints": list(self.config.checkpoints),
            "generation_calls_per_chapter_per_condition": self.config.generation_calls_per_chapter,
            "context_char_limit": self.config.context_char_limit,
            "ollama_num_ctx": self.model.ollama_num_ctx,
            "ollama_num_predict": self.model.ollama_num_predict,
            "request_timeout_seconds": self.model.request_timeout_seconds,
            "automatic_evaluation_is_not_human_blind_evidence": True,
        }
        path = self.output_dir / "manifest.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            for key in (
                "schema_version",
                "benchmark_id",
                "generation_protocol",
                "baseline_generation_pipeline",
                "kingdom_generation_pipeline",
                "seed_sha256",
                "contract_sha256",
                "model",
                "chapters",
                "checkpoints",
                "generation_calls_per_chapter_per_condition",
                "context_char_limit",
                "ollama_num_ctx",
                "ollama_num_predict",
                "request_timeout_seconds",
            ):
                if existing.get(key) != manifest.get(key):
                    raise RuntimeError(f"refusing resume: manifest {key} changed")
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _persist_state(self, condition: str, state: StoryState) -> None:
        path = self._state_path(condition)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _persist_calls(self) -> None:
        path = self.output_dir / "calls.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in self.model.records:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def _persist_checkpoint(
        self,
        chapter: int,
        baseline_score: CheckpointScore,
        kingdom_score: CheckpointScore,
        pairwise: PairwisePreference,
    ) -> None:
        payload = {
            "chapter": chapter,
            "baseline": asdict(baseline_score),
            "kingdom": asdict(kingdom_score),
            "kingdom_minus_baseline_total": round(kingdom_score.total - baseline_score.total, 3),
            "pairwise_blind": asdict(pairwise),
        }
        folder = self.output_dir / "checkpoints"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"checkpoint_{chapter:04d}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def run(self) -> None:
        if self.config.chapters < 2:
            raise ValueError("chapters must include at least Chapter 2")
        if self.config.generation_calls_per_chapter != DEFAULT_GENERATION_CALLS:
            raise ValueError(
                f"{GENERATION_PROTOCOL_ID} requires exactly {DEFAULT_GENERATION_CALLS} "
                "generation calls per chapter and condition"
            )
        self._persist_manifest()
        states = {
            "baseline": self._load_state("baseline"),
            "kingdom": self._load_state("kingdom"),
        }
        starts = {
            condition: max(2, self._last_completed_chapter(condition) + 1)
            for condition in ("baseline", "kingdom")
        }
        for chapter in range(2, self.config.chapters + 1):
            for condition, writer in (("baseline", self.baseline), ("kingdom", self.kingdom)):
                if chapter < starts[condition]:
                    continue
                chapter_path = self._chapter_path(condition, chapter)
                chapter_path.parent.mkdir(parents=True, exist_ok=True)
                text = writer.write(chapter, states[condition], self._prior_tail(condition, chapter))
                if self.model.generation_count(condition, chapter) != self.config.generation_calls_per_chapter:
                    raise RuntimeError(
                        f"{condition} chapter {chapter} used "
                        f"{self.model.generation_count(condition, chapter)} generation calls; expected "
                        f"{self.config.generation_calls_per_chapter}"
                    )
                chapter_path.write_text(text.rstrip() + "\n", encoding="utf-8")
                states[condition] = self.extractor.update(condition, chapter, states[condition], text)
                self._persist_state(condition, states[condition])
                self._persist_calls()

            if chapter in self.config.checkpoints:
                baseline_score = self.evaluator.score("baseline", chapter, states["baseline"])
                kingdom_score = self.evaluator.score("kingdom", chapter, states["kingdom"])
                pairwise = self.evaluator.pairwise(
                    chapter,
                    states["baseline"],
                    states["kingdom"],
                    blind_seed=self.seed_hash,
                )
                self._persist_checkpoint(chapter, baseline_score, kingdom_score, pairwise)
                self._persist_calls()
        self._write_summary()

    def _write_summary(self) -> None:
        rows = []
        for chapter in self.config.checkpoints:
            path = self.output_dir / "checkpoints" / f"checkpoint_{chapter:04d}.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append(
                (
                    chapter,
                    data["baseline"]["total"],
                    data["kingdom"]["total"],
                    data["kingdom_minus_baseline_total"],
                    data["pairwise_blind"]["preferred"],
                )
            )
        lines = [
            f"# {self.config.benchmark_id} Result",
            "",
            f"Model: `{self.model.model}`",
            f"Generation protocol: `{GENERATION_PROTOCOL_ID}`",
            f"Seed SHA-256: `{self.seed_hash}`",
            f"Matched generation calls/chapter/condition: {self.config.generation_calls_per_chapter}",
            f"Ollama context window: {self.model.ollama_num_ctx} tokens",
            f"Maximum output/call: {self.model.ollama_num_predict} tokens",
            f"Request timeout: {self.model.request_timeout_seconds} seconds for every call",
            "",
            "Automatic model scoring is diagnostic only. A theory claim requires longitudinal behavior and blind human evaluation.",
            "",
            "| Checkpoint | Baseline | Kingdom | Δ Kingdom-Baseline | Blind auto preference |",
            "| ---: | ---: | ---: | ---: | :--- |",
        ]
        for chapter, baseline, kingdom, delta, preferred in rows:
            lines.append(f"| {chapter} | {baseline:.3f} | {kingdom:.3f} | {delta:+.3f} | {preferred} |")
        lines.extend(
            [
                "",
                "## Critical prediction",
                "",
                "Evidence for the architecture requires the relative Kingdom advantage to persist or widen as narrative horizon/dependency density grows. A single higher score at Chapter 10 is not sufficient.",
                "",
                "## Human blind evaluation",
                "",
                "Not yet completed by this harness. Human readers should be given anonymized chapter sets without architecture labels and score coherence, payoff, character consistency, engagement, and perceived intentionality.",
            ]
        )
        (self.output_dir / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ADI long-horizon webnovel A/B benchmark")
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chapters", type=int, default=10)
    parser.add_argument("--checkpoint", action="append", type=int, dest="checkpoints")
    parser.add_argument(
        "--generation-calls",
        type=int,
        choices=(DEFAULT_GENERATION_CALLS,),
        default=DEFAULT_GENERATION_CALLS,
        help="Fixed by the ADI-001 three-call protocol",
    )
    parser.add_argument("--context-chars", type=int, default=120_000)
    parser.add_argument("--model", default=None, help="Explicit same model for both conditions; defaults to Hive DEFAULT_MODEL")
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
    runner = WebNovelBenchmarkRunner(
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
