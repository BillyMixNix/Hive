from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Protocol, Sequence

from .adi_story_boundary import (
    BOUNDARY_PROTOCOL_ID,
    ADIStoryBoundary,
    BoundaryGuardReport,
    canonical_sha256,
    load_adi_story_boundary,
)
from .story_map import CanonicalState, StoryMap as ChapterStoryMap, load_story_map


DEFAULT_GENERATION_CALLS = 3
DEFAULT_CHECKPOINTS = (5, 10)
DEFAULT_OLLAMA_NUM_CTX = 32_768
DEFAULT_OLLAMA_NUM_PREDICT = 2_048
DEFAULT_OLLAMA_TEMPERATURE = 0.2
DEFAULT_OLLAMA_SEED = 42_001
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900
GENERATION_PROTOCOL_ID = "adi-001-3call-story-map-v1"
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


def _ollama_model_digest(model: str, *, generate_url: str) -> str:
    import requests

    base_url = generate_url.rsplit("/api/", 1)[0]
    response = requests.get(f"{base_url}/api/tags", timeout=15)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(models, list):
        raise RuntimeError("Ollama /api/tags response does not contain a model list")
    for item in models:
        if not isinstance(item, Mapping):
            continue
        if model not in {item.get("name"), item.get("model")}:
            continue
        digest = str(item.get("digest") or "")
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
        raise RuntimeError(f"Ollama model {model!r} has no valid digest")
    raise RuntimeError(f"Ollama model {model!r} is not installed")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


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
        max_retries: int | None = None,
        metadata: MutableMapping[str, Any] | None = None,
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
    ollama_temperature: float
    ollama_seed: int
    prompt_sha256: str
    response_sha256: str
    prompt_chars: int
    response_chars: int
    elapsed_seconds: float
    budget_class: str
    physical_attempts: int
    transport_done: bool
    transport_done_reason: str
    prompt_eval_tokens: int
    response_eval_tokens: int
    error_type: str
    error_message: str


class BudgetExceeded(RuntimeError):
    pass


class BudgetedModel:
    """Tracks generation and evaluation calls so the A/B comparison is auditable."""

    def __init__(
        self,
        ask: AskFunction,
        *,
        model: str,
        model_digest: str = "unverified-test-double",
        generation_calls_per_chapter: int = DEFAULT_GENERATION_CALLS,
        ollama_num_ctx: int = DEFAULT_OLLAMA_NUM_CTX,
        ollama_num_predict: int = DEFAULT_OLLAMA_NUM_PREDICT,
        ollama_temperature: float = DEFAULT_OLLAMA_TEMPERATURE,
        ollama_seed: int = DEFAULT_OLLAMA_SEED,
        request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        self.ask_fn = ask
        self.model = model
        self.model_digest = model_digest
        self.generation_calls_per_chapter = generation_calls_per_chapter
        self.ollama_num_ctx = ollama_num_ctx
        self.ollama_num_predict = ollama_num_predict
        self.ollama_temperature = ollama_temperature
        self.ollama_seed = ollama_seed
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
        transport: dict[str, Any] = {}
        response = ""
        failure: Exception | None = None
        try:
            response = self.ask_fn(
                prompt,
                role=role,
                timeout=self.request_timeout_seconds,
                model=self.model,
                options={
                    "num_ctx": self.ollama_num_ctx,
                    "num_predict": self.ollama_num_predict,
                    "temperature": self.ollama_temperature,
                    "seed": self.ollama_seed,
                },
                max_retries=1,
                metadata=transport,
            )
        except Exception as exc:
            failure = exc
        elapsed = time.monotonic() - started
        record = ModelCallRecord(
            condition=condition,
            chapter=chapter,
            purpose=purpose,
            role=role,
            model=self.model,
            request_timeout_seconds=self.request_timeout_seconds,
            ollama_num_ctx=self.ollama_num_ctx,
            ollama_num_predict=self.ollama_num_predict,
            ollama_temperature=self.ollama_temperature,
            ollama_seed=self.ollama_seed,
            prompt_sha256=_sha256_text(prompt),
            response_sha256=_sha256_text(response),
            prompt_chars=len(prompt),
            response_chars=len(response),
            elapsed_seconds=round(elapsed, 6),
            budget_class=budget_class,
            physical_attempts=int(transport.get("physical_attempts", 1)),
            transport_done=bool(transport.get("done", failure is None)),
            transport_done_reason=str(
                transport.get("done_reason")
                or ("transport_error" if failure is not None else "unreported")
            ),
            prompt_eval_tokens=int(transport.get("prompt_eval_count") or 0),
            response_eval_tokens=int(transport.get("eval_count") or 0),
            error_type=type(failure).__name__ if failure is not None else "",
            error_message=str(failure) if failure is not None else "",
        )
        self.records.append(record)
        if failure is not None:
            raise failure
        if record.physical_attempts != 1:
            raise RuntimeError("benchmark call used a hidden transport retry")
        if not record.transport_done:
            raise RuntimeError("benchmark call did not report transport completion")
        if record.transport_done_reason.casefold() in {"length", "max_tokens"}:
            raise RuntimeError(
                f"benchmark call was truncated at {self.ollama_num_predict} output tokens"
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
class ValidatedStateUpdate:
    state: CanonicalState
    proposed_map: ChapterStoryMap
    guard_report: BoundaryGuardReport


class StateProposalRejected(RuntimeError):
    """Preserves the raw extractor proposal when deterministic promotion fails."""

    def __init__(self, message: str, *, raw_response: str):
        super().__init__(message)
        self.raw_response = raw_response


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

    def __init__(
        self,
        model: BudgetedModel,
        boundary: ADIStoryBoundary,
        config: BenchmarkConfig,
    ):
        self.model = model
        self.boundary = boundary
        self.config = config

    def write(self, chapter: int, prior_state: CanonicalState, prior_tail: str) -> str:
        authority = self.boundary.shared_writer_packet(chapter=chapter)
        memory = self.boundary.baseline_memory_packet(prior_state)
        common = (
            f"{authority}\n\n"
            f"{memory}\n\n"
            f"VERIFIED RECENT PROSE TAIL:\n{prior_tail}\n\n"
        )
        plan = self.model.ask(
            _clip(
                common
                + f"Create a concise conventional novelist's plan for Chapter {chapter}. Continue naturally from the "
                  "verified current boundary using ordinary long-form reasoning. Cover the intended scene progression, character "
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
                  "with the shared authority packet and verified memory. Return the complete chapter only.",
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
                  "characterization, prose, and plan-to-draft problems using the shared authority packet. Preserve "
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

    def __init__(
        self,
        model: BudgetedModel,
        boundary: ADIStoryBoundary,
        config: BenchmarkConfig,
    ):
        self.model = model
        self.boundary = boundary
        self.config = config

    def write(self, chapter: int, state: CanonicalState, prior_tail: str) -> str:
        authority = self.boundary.shared_writer_packet(chapter=chapter)
        memory = self.boundary.kingdom_memory_packet(state)
        common = (
            f"{authority}\n\n"
            f"{memory}\n\n"
            f"VERIFIED RECENT PROSE TAIL:\n{prior_tail}\n\n"
        )
        plan = self.model.ask(
            _clip(
                common
                + f"Create a structured dependency plan for Chapter {chapter}. Decompress the chapter through these "
                  "lenses: continuity and chronology; who-knows-what; unresolved obligations and mysteries; "
                  "Money-Breathing math, finances, cultivation, assets, exchanges, and economic causality; Ren's "
                  "psychology and relationships; value-versus-price theme and tone trajectory; setup/payoff links; and "
                  "an adversarial search for lore leaks, unearned escalation, generic-system drift, or future damage. "
                  "Resolve conflicts against the verified current boundary and locked future labels. Return JSON with chapter_goal, "
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
                  "shared authority packet. Return chapter prose only, with no planning notes.",
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
                  "Perform the terminal Critical-Path revision. Walk the locked authorial intent and dependency plan through "
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
    """Shared delta proposer; deterministic code alone may promote claims to canon."""

    def __init__(
        self,
        model: BudgetedModel,
        boundary: ADIStoryBoundary,
        config: BenchmarkConfig,
    ):
        self.model = model
        self.boundary = boundary
        self.config = config

    def update(
        self,
        condition: str,
        chapter: int,
        prior: CanonicalState,
        text: str,
    ) -> ValidatedStateUpdate:
        chapter_hash = _sha256_text(text)
        empty_categories = ", ".join(f'"{name}": []' for name in STATE_FIELDS)
        prompt = _clip(
            f"{self.boundary.extractor_authority_packet(prior)}\n\n"
            f"FINAL CHAPTER {chapter} — THE ONLY SOURCE FOR NEW CURRENT CLAIMS:\n{text}\n\n"
            "You are a condition-blind state DELTA PROPOSER, not an authority. Return one strict JSON object only. "
            "Do not repeat unchanged prior claims. Every new or changed claim must cite one exact, unique verbatim quote "
            "from the final chapter. Never cite author plans, the frozen seed, or prior state as proof that something "
            "happened. Use status 'current' only for what the prose actually establishes; intentions and unresolved "
            "tasks use 'planned' or 'attempted'. A concise statement must retain every number and distinctive named "
            "concept from its evidence. Use existing claim IDs only for real status transitions, with the exact prior "
            "statement and dependencies unchanged. Include at least one factual claim and one chapter_summaries claim.\n\n"
            f"The exact top-level schema is: {{\"schema_version\": 1, \"chapter\": {chapter}, "
            f"\"claims\": {{{empty_categories}}}}}. Each claim object has exactly claim_id, statement, status, "
            "depends_on, evidence. evidence has exactly source_id, source_sha256, chapter, quote. For this chapter, "
            f"source_id must be \"chapter:{chapter:04d}\", source_sha256 must be \"{chapter_hash}\", and chapter "
            f"must be {chapter}. depends_on is a list of existing or simultaneously proposed claim IDs. All category "
            "keys must be present even when empty. Do not output rolling_summary; the harness derives all legacy memory "
            "from accepted typed claims.",
            self.config.context_char_limit,
        )
        raw = self.model.ask(
            prompt,
            condition=condition,
            chapter=chapter,
            purpose="shared Story Map state extraction",
            role="reflector",
            budget_class="evaluation",
        )
        try:
            proposed = load_story_map(_extract_json(raw))
            if not any(claim.category == "facts" for claim in proposed.claims):
                raise ValueError(
                    "state delta must contain at least one evidence-backed factual claim"
                )
            state, report = self.boundary.validate_and_update(
                prior,
                proposed,
                chapter_text=text,
                chapter=chapter,
            )
            return ValidatedStateUpdate(
                state=state,
                proposed_map=proposed,
                guard_report=report,
            )
        except Exception as exc:
            raise StateProposalRejected(
                f"Story Map gate rejected {condition} chapter {chapter}: {exc}",
                raw_response=raw,
            ) from exc


class CheckpointEvaluator:
    """Automatic evaluator. Useful for diagnostics, never a substitute for blind humans."""

    def __init__(
        self,
        model: BudgetedModel,
        boundary: ADIStoryBoundary,
        contract: str,
        config: BenchmarkConfig,
    ):
        self.model = model
        self.authority = boundary.evaluator_packet(contract)
        self.config = config

    def score(self, condition: str, chapter: int, state: StoryState) -> CheckpointScore:
        raw = self.model.ask(
            _clip(
                f"{self.authority}\n\n"
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
                f"{self.authority}\n\n"
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
        story_boundary: ADIStoryBoundary,
        output_dir: Path,
        model: BudgetedModel,
        config: BenchmarkConfig,
    ):
        self.seed = seed
        self.contract = contract
        self.story_boundary = story_boundary
        self.output_dir = output_dir
        self.model = model
        self.config = config
        self.seed_hash = _sha256_text(seed)
        self.contract_hash = _sha256_text(contract)
        if story_boundary.seed_sha256 != self.seed_hash:
            raise ValueError("runner seed does not match the frozen Story Map authority")
        if story_boundary.contract_sha256 != self.contract_hash:
            raise ValueError("runner contract does not match the frozen Story Map authority")
        self.baseline = BaselineWriter(model, story_boundary, config)
        self.kingdom = KingdomWriter(model, story_boundary, config)
        self.extractor = StateExtractor(model, story_boundary, config)
        self.evaluator = CheckpointEvaluator(model, story_boundary, contract, config)
        self._persisted_current_records = 0

    def _condition_dir(self, condition: str) -> Path:
        return self.output_dir / condition

    def _chapter_path(self, condition: str, chapter: int) -> Path:
        return self._condition_dir(condition) / "chapters" / f"chapter_{chapter:04d}.md"

    def _state_path(self, condition: str) -> Path:
        return self._condition_dir(condition) / "state.json"

    def _artifact_path(self, condition: str, chapter: int) -> Path:
        return self._condition_dir(condition) / "artifacts" / f"chapter_{chapter:04d}.json"

    def _artifact_numbers(self, condition: str) -> list[int]:
        folder = self._condition_dir(condition) / "artifacts"
        if not folder.exists():
            return []
        numbers: list[int] = []
        for path in folder.glob("chapter_*.json"):
            try:
                numbers.append(int(path.stem.split("_")[-1]))
            except ValueError:
                continue
        numbers.sort()
        if numbers and numbers != list(range(2, numbers[-1] + 1)):
            raise RuntimeError(f"{condition} canonical artifact history is not contiguous")
        return numbers

    @staticmethod
    def _verify_artifact_hash(payload: Mapping[str, Any]) -> None:
        stored = str(payload.get("artifact_sha256") or "")
        body = dict(payload)
        body.pop("artifact_sha256", None)
        if stored != canonical_sha256(body):
            raise RuntimeError("canonical chapter artifact hash mismatch")

    def _load_artifact(self, condition: str, chapter: int) -> dict[str, Any]:
        path = self._artifact_path(condition, chapter)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"{path} is not a canonical artifact object")
        self._verify_artifact_hash(payload)
        if payload.get("schema_version") != 1:
            raise RuntimeError("unsupported canonical chapter artifact schema")
        if payload.get("condition") != condition or payload.get("chapter") != chapter:
            raise RuntimeError("canonical chapter artifact identity mismatch")
        chapter_text = str(payload.get("chapter_text") or "")
        if payload.get("chapter_sha256") != _sha256_text(chapter_text):
            raise RuntimeError("canonical chapter prose hash mismatch")
        raw_final = str(payload.get("raw_final_response") or "")
        if payload.get("raw_final_response_sha256") != _sha256_text(raw_final):
            raise RuntimeError("canonical artifact raw final-response hash mismatch")
        if chapter_text != raw_final.rstrip() + "\n":
            raise RuntimeError("canonical artifact prose normalization mismatch")
        generation_records = [
            record
            for record in payload.get("call_records", [])
            if isinstance(record, Mapping) and record.get("budget_class") == "generation"
        ]
        if not generation_records or generation_records[-1].get(
            "response_sha256"
        ) != payload.get("raw_final_response_sha256"):
            raise RuntimeError("canonical artifact is not linked to its final generation call")
        state_payload = payload.get("canonical_state")
        state = CanonicalState.from_mapping(state_payload)
        if payload.get("canonical_state_sha256") != canonical_sha256(state.to_mapping()):
            raise RuntimeError("canonical chapter state hash mismatch")
        expected_prior = self.story_boundary.initial_state_sha256
        if chapter > 2:
            expected_prior = self._load_artifact(condition, chapter - 1)["artifact_sha256"]
        if payload.get("prior_artifact_sha256") != expected_prior:
            raise RuntimeError("canonical chapter artifact ancestry mismatch")
        return payload

    def _load_state(self, condition: str) -> CanonicalState:
        numbers = self._artifact_numbers(condition)
        if not numbers:
            return self.story_boundary.initial_state
        payload = self._load_artifact(condition, numbers[-1])
        return CanonicalState.from_mapping(payload["canonical_state"])

    def _last_completed_chapter(self, condition: str) -> int:
        numbers = self._artifact_numbers(condition)
        for chapter in numbers:
            self._load_artifact(condition, chapter)
        return numbers[-1] if numbers else 1

    def _prior_tail(self, condition: str, chapter: int) -> str:
        if chapter == 2:
            return self.story_boundary.chapter_one_tail
        previous = self._load_artifact(condition, chapter - 1)
        return _clip(str(previous["chapter_text"]), 12_000)

    def _persist_manifest(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        initial_shared_writer_packet = self.story_boundary.shared_writer_packet(chapter=2)
        initial_baseline_memory = self.story_boundary.baseline_memory_packet(
            self.story_boundary.initial_state
        )
        initial_kingdom_memory = self.story_boundary.kingdom_memory_packet(
            self.story_boundary.initial_state
        )
        initial_extractor_packet = self.story_boundary.extractor_authority_packet(
            self.story_boundary.initial_state
        )
        evaluator_packet = self.story_boundary.evaluator_packet(self.contract)
        manifest = {
            "schema_version": 3,
            "benchmark_id": self.config.benchmark_id,
            "title": self.config.title,
            "generation_protocol": GENERATION_PROTOCOL_ID,
            "story_boundary_protocol": BOUNDARY_PROTOCOL_ID,
            "baseline_generation_pipeline": list(BASELINE_GENERATION_PIPELINE),
            "kingdom_generation_pipeline": list(KINGDOM_GENERATION_PIPELINE),
            "seed_sha256": self.seed_hash,
            "contract_sha256": self.contract_hash,
            "story_map_sha256": self.story_boundary.source_map_sha256,
            "initial_state_sha256": self.story_boundary.initial_state_sha256,
            "chapter_one_sha256": self.story_boundary.chapter_one_sha256,
            "chapter_one_tail_sha256": self.story_boundary.chapter_one_tail_sha256,
            "initial_shared_writer_projection_sha256": _sha256_text(
                initial_shared_writer_packet
            ),
            "initial_baseline_memory_projection_sha256": _sha256_text(
                initial_baseline_memory
            ),
            "initial_kingdom_memory_projection_sha256": _sha256_text(
                initial_kingdom_memory
            ),
            "initial_extractor_projection_sha256": _sha256_text(initial_extractor_packet),
            "evaluator_projection_sha256": _sha256_text(evaluator_packet),
            "model": self.model.model,
            "model_digest": self.model.model_digest,
            "chapters": self.config.chapters,
            "checkpoints": list(self.config.checkpoints),
            "generation_calls_per_chapter_per_condition": self.config.generation_calls_per_chapter,
            "context_char_limit": self.config.context_char_limit,
            "ollama_num_ctx": self.model.ollama_num_ctx,
            "ollama_num_predict": self.model.ollama_num_predict,
            "ollama_temperature": self.model.ollama_temperature,
            "ollama_seed": self.model.ollama_seed,
            "request_timeout_seconds": self.model.request_timeout_seconds,
            "transport_attempt_limit": 1,
            "canonical_chapter_artifact_schema": 1,
            "canonical_claim_state_schema": 1,
            "automatic_evaluation_is_not_human_blind_evidence": True,
        }
        path = self.output_dir / "manifest.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            for key in (
                "schema_version",
                "benchmark_id",
                "generation_protocol",
                "story_boundary_protocol",
                "baseline_generation_pipeline",
                "kingdom_generation_pipeline",
                "seed_sha256",
                "contract_sha256",
                "story_map_sha256",
                "initial_state_sha256",
                "chapter_one_sha256",
                "chapter_one_tail_sha256",
                "initial_shared_writer_projection_sha256",
                "initial_baseline_memory_projection_sha256",
                "initial_kingdom_memory_projection_sha256",
                "initial_extractor_projection_sha256",
                "evaluator_projection_sha256",
                "model",
                "model_digest",
                "chapters",
                "checkpoints",
                "generation_calls_per_chapter_per_condition",
                "context_char_limit",
                "ollama_num_ctx",
                "ollama_num_predict",
                "ollama_temperature",
                "ollama_seed",
                "request_timeout_seconds",
                "transport_attempt_limit",
                "canonical_chapter_artifact_schema",
                "canonical_claim_state_schema",
            ):
                if existing.get(key) != manifest.get(key):
                    raise RuntimeError(f"refusing resume: manifest {key} changed")
        _atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def _persist_state(self, condition: str, state: CanonicalState) -> None:
        path = self._state_path(condition)
        payload = state.to_legacy_story_state()
        payload["_canonical_state"] = state.to_mapping()
        payload["_canonical_state_sha256"] = canonical_sha256(state.to_mapping())
        _atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )

    def _persist_calls(self) -> None:
        path = self.output_dir / "calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.model.records[self._persisted_current_records :]
        if not pending:
            return
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in pending:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._persisted_current_records = len(self.model.records)

    def _read_call_ledger(self) -> list[dict[str, Any]]:
        path = self.output_dir / "calls.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                raise RuntimeError(f"call ledger contains an empty row at line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"call ledger contains malformed JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise RuntimeError(f"call ledger row {line_number} is not an object")
            records.append(record)
        return records

    def _expected_committed_call_records(self, last_chapter: int) -> list[dict[str, Any]]:
        expected: list[dict[str, Any]] = []
        for chapter in range(2, last_chapter + 1):
            for condition in ("baseline", "kingdom"):
                artifact = self._load_artifact(condition, chapter)
                call_records = artifact.get("call_records")
                if not isinstance(call_records, list) or len(call_records) != 4:
                    raise RuntimeError(
                        f"{condition} Chapter {chapter} artifact must contain exactly "
                        "three generation calls and one state-extraction call"
                    )
                expected.extend(call_records)
            if chapter in self.config.checkpoints:
                checkpoint_path = (
                    self.output_dir / "checkpoints" / f"checkpoint_{chapter:04d}.json"
                )
                if not checkpoint_path.exists():
                    raise RuntimeError(
                        f"refusing resume: completed Chapter {chapter} is missing its "
                        "checkpoint; archive this run and restart fresh"
                    )
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                call_records = checkpoint.get("call_records")
                if not isinstance(call_records, list) or len(call_records) != 3:
                    raise RuntimeError(
                        f"checkpoint {chapter} must contain exactly three evaluator calls"
                    )
                expected.extend(call_records)
        return expected

    def _validate_resume_ledger(self, last_chapter: int) -> None:
        actual = self._read_call_ledger()
        expected = self._expected_committed_call_records(last_chapter)
        if actual != expected:
            raise RuntimeError(
                "refusing resume: call ledger does not exactly match hash-linked canonical "
                "artifacts/checkpoints; archive this run and restart fresh"
            )

    def _sync_derived_views(self, condition: str) -> None:
        numbers = self._artifact_numbers(condition)
        for chapter in numbers:
            artifact = self._load_artifact(condition, chapter)
            chapter_path = self._chapter_path(condition, chapter)
            chapter_text = str(artifact["chapter_text"])
            if not chapter_path.exists() or chapter_path.read_text(
                encoding="utf-8"
            ) != chapter_text:
                _atomic_write_text(chapter_path, chapter_text)
        if numbers:
            latest = self._load_artifact(condition, numbers[-1])
            self._persist_state(
                condition,
                CanonicalState.from_mapping(latest["canonical_state"]),
            )

    @staticmethod
    def _story_map_mapping(story_map: ChapterStoryMap) -> dict[str, Any]:
        claims: dict[str, list[dict[str, Any]]] = {name: [] for name in STATE_FIELDS}
        for claim in story_map.claims:
            evidence = {
                "source_id": claim.evidence.source_id,
                "source_sha256": claim.evidence.source_sha256,
                "chapter": claim.evidence.chapter,
                "quote": claim.evidence.quote,
            }
            if claim.evidence.start is not None:
                evidence["start"] = claim.evidence.start
                evidence["end"] = claim.evidence.end
            claims[claim.category].append(
                {
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "status": claim.status,
                    "depends_on": list(claim.depends_on),
                    "evidence": evidence,
                }
            )
        return {
            "schema_version": story_map.schema_version,
            "chapter": story_map.chapter,
            "claims": claims,
        }

    def _condition_call_records(self, condition: str, chapter: int) -> list[dict[str, Any]]:
        return [
            asdict(record)
            for record in self.model.records
            if record.condition == condition and record.chapter == chapter
        ]

    def _commit_chapter(
        self,
        condition: str,
        chapter: int,
        text: str,
        raw_final_response: str,
        update: ValidatedStateUpdate,
    ) -> None:
        prior_hash = self.story_boundary.initial_state_sha256
        if chapter > 2:
            prior_hash = self._load_artifact(condition, chapter - 1)["artifact_sha256"]
        body: dict[str, Any] = {
            "schema_version": 1,
            "condition": condition,
            "chapter": chapter,
            "prior_artifact_sha256": prior_hash,
            "raw_final_response": raw_final_response,
            "raw_final_response_sha256": _sha256_text(raw_final_response),
            "prose_normalization": "raw_final_response.rstrip() + single LF",
            "chapter_text": text.rstrip() + "\n",
            "chapter_sha256": _sha256_text(text.rstrip() + "\n"),
            "proposed_story_map": self._story_map_mapping(update.proposed_map),
            "canonical_state": update.state.to_mapping(),
            "canonical_state_sha256": canonical_sha256(update.state.to_mapping()),
            "guard_report": update.guard_report.to_mapping(),
            "call_records": self._condition_call_records(condition, chapter),
        }
        body["artifact_sha256"] = canonical_sha256(body)
        artifact_path = self._artifact_path(condition, chapter)
        if artifact_path.exists():
            raise RuntimeError(f"refusing to overwrite canonical artifact {artifact_path}")
        _atomic_write_text(
            artifact_path,
            json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
        _atomic_write_text(self._chapter_path(condition, chapter), body["chapter_text"])
        self._persist_state(condition, update.state)

    def _archive_rejected_candidate(
        self,
        condition: str,
        chapter: int,
        text: str,
        error: Exception,
        *,
        raw_final_response: str,
    ) -> None:
        payload = {
            "schema_version": 1,
            "condition": condition,
            "chapter": chapter,
            "raw_final_response": raw_final_response,
            "raw_final_response_sha256": _sha256_text(raw_final_response),
            "prose_normalization": "raw_final_response.rstrip() + single LF",
            "chapter_text": text.rstrip() + "\n",
            "chapter_sha256": _sha256_text(text.rstrip() + "\n"),
            "error_type": type(error).__name__,
            "error": str(error),
            "call_records": self._condition_call_records(condition, chapter),
        }
        raw_response = getattr(error, "raw_response", None)
        if isinstance(raw_response, str):
            payload["rejected_state_proposal"] = raw_response
            payload["rejected_state_proposal_sha256"] = _sha256_text(raw_response)
        payload["rejection_sha256"] = canonical_sha256(payload)
        digest = payload["rejection_sha256"][:12]
        path = (
            self.output_dir
            / "rejected"
            / condition
            / f"chapter_{chapter:04d}-{digest}.json"
        )
        _atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )

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
            "call_records": [
                asdict(record)
                for record in self.model.records
                if record.chapter == chapter
                and record.purpose
                in {
                    "automatic checkpoint score",
                    "blind automatic pairwise comparison",
                }
            ],
        }
        if len(payload["call_records"]) != 3:
            raise RuntimeError(
                f"checkpoint {chapter} must contain exactly three evaluator call records"
            )
        folder = self.output_dir / "checkpoints"
        folder.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            folder / f"checkpoint_{chapter:04d}.json",
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )

    def run(self) -> None:
        if self.config.chapters < 2:
            raise ValueError("chapters must include at least Chapter 2")
        if self.config.generation_calls_per_chapter != DEFAULT_GENERATION_CALLS:
            raise ValueError(
                f"{GENERATION_PROTOCOL_ID} requires exactly {DEFAULT_GENERATION_CALLS} "
                "generation calls per chapter and condition"
            )
        missing_frontiers = [
            chapter
            for chapter in range(2, self.config.chapters + 1)
            if chapter not in self.story_boundary.chapter_frontiers
        ]
        if missing_frontiers:
            missing = ", ".join(str(chapter) for chapter in missing_frontiers)
            raise ValueError(
                "Story Map lacks frozen story frontiers for Chapters " + missing
            )
        missing_locks = [
            chapter
            for chapter in range(2, self.config.chapters + 1)
            if chapter not in self.story_boundary.locked_terms_by_chapter
        ]
        missing_rules = [
            chapter
            for chapter in range(2, self.config.chapters + 1)
            if chapter not in self.story_boundary.forbidden_patterns_by_chapter
        ]
        if missing_locks or missing_rules:
            details = []
            if missing_locks:
                details.append(
                    "locked-term coverage for Chapters "
                    + ", ".join(str(chapter) for chapter in missing_locks)
                )
            if missing_rules:
                details.append(
                    "forbidden-rule coverage for Chapters "
                    + ", ".join(str(chapter) for chapter in missing_rules)
                )
            raise ValueError("Story Map lacks explicit guard coverage: " + "; ".join(details))
        self._persist_manifest()
        try:
            last = {
                condition: self._last_completed_chapter(condition)
                for condition in ("baseline", "kingdom")
            }
            if last["baseline"] != last["kingdom"]:
                raise RuntimeError(
                    "refusing asymmetric resume: baseline and Kingdom canonical histories differ; "
                    "archive this run and restart fresh"
                )
            self._validate_resume_ledger(last["baseline"])
            for condition in ("baseline", "kingdom"):
                self._sync_derived_views(condition)
            states = {
                "baseline": self._load_state("baseline"),
                "kingdom": self._load_state("kingdom"),
            }
            for chapter in range(max(2, last["baseline"] + 1), self.config.chapters + 1):
                for condition, writer in (("baseline", self.baseline), ("kingdom", self.kingdom)):
                    raw_final_response = writer.write(
                        chapter,
                        states[condition],
                        self._prior_tail(condition, chapter),
                    )
                    text = raw_final_response.rstrip() + "\n"
                    if self.model.generation_count(condition, chapter) != self.config.generation_calls_per_chapter:
                        raise RuntimeError(
                            f"{condition} chapter {chapter} used "
                            f"{self.model.generation_count(condition, chapter)} generation calls; expected "
                            f"{self.config.generation_calls_per_chapter}"
                        )
                    try:
                        self.story_boundary.validate_chapter_text(
                            text,
                            chapter=chapter,
                        )
                        update = self.extractor.update(
                            condition,
                            chapter,
                            states[condition],
                            text,
                        )
                    except Exception as exc:
                        self._archive_rejected_candidate(
                            condition,
                            chapter,
                            text,
                            exc,
                            raw_final_response=raw_final_response,
                        )
                        raise
                    states[condition] = update.state
                    self._commit_chapter(
                        condition,
                        chapter,
                        text,
                        raw_final_response,
                        update,
                    )
                    self._persist_calls()

                if chapter in self.config.checkpoints:
                    baseline_state = StoryState.from_mapping(
                        states["baseline"].to_legacy_story_state()
                    )
                    kingdom_state = StoryState.from_mapping(
                        states["kingdom"].to_legacy_story_state()
                    )
                    baseline_score = self.evaluator.score(
                        "baseline", chapter, baseline_state
                    )
                    kingdom_score = self.evaluator.score(
                        "kingdom", chapter, kingdom_state
                    )
                    pairwise = self.evaluator.pairwise(
                        chapter,
                        baseline_state,
                        kingdom_state,
                        blind_seed=self.seed_hash,
                    )
                    self._persist_calls()
                    self._persist_checkpoint(
                        chapter,
                        baseline_score,
                        kingdom_score,
                        pairwise,
                    )
            self._write_summary()
        finally:
            self._persist_calls()

    def _write_summary(self) -> None:
        rows = []
        for chapter in self.config.checkpoints:
            path = self.output_dir / "checkpoints" / f"checkpoint_{chapter:04d}.json"
            if not path.exists():
                raise RuntimeError(
                    f"cannot write RESULT.md: configured checkpoint {chapter} is missing"
                )
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
            f"Model digest: `{self.model.model_digest}`",
            f"Generation protocol: `{GENERATION_PROTOCOL_ID}`",
            f"Story boundary protocol: `{BOUNDARY_PROTOCOL_ID}`",
            f"Seed SHA-256: `{self.seed_hash}`",
            f"Story Map SHA-256: `{self.story_boundary.source_map_sha256}`",
            f"Initial Chapter-One state SHA-256: `{self.story_boundary.initial_state_sha256}`",
            f"Matched generation calls/chapter/condition: {self.config.generation_calls_per_chapter}",
            f"Ollama context window: {self.model.ollama_num_ctx} tokens",
            f"Maximum output/call: {self.model.ollama_num_predict} tokens",
            f"Ollama temperature/seed: {self.model.ollama_temperature} / {self.model.ollama_seed}",
            f"Request timeout: {self.model.request_timeout_seconds} seconds for every call",
            "Transport retries: disabled; every ledger row is one physical Ollama request",
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
        _atomic_write_text(self.output_dir / "RESULT.md", "\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ADI long-horizon webnovel A/B benchmark")
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument(
        "--story-map-file",
        type=Path,
        help=(
            "Frozen current/future authority map shared by both conditions "
            "(defaults to STORY_MAP.json beside --seed-file)"
        ),
    )
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
    from hive_llm import DEFAULT_MODEL, OLLAMA_URL, ask_hive

    seed = args.seed_file.read_text(encoding="utf-8")
    contract = args.benchmark_file.read_text(encoding="utf-8")
    story_map_file = args.story_map_file or args.seed_file.with_name("STORY_MAP.json")
    story_boundary = load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=story_map_file.read_text(encoding="utf-8"),
    )
    checkpoints = tuple(sorted(set(args.checkpoints or DEFAULT_CHECKPOINTS)))
    checkpoints = tuple(value for value in checkpoints if 2 <= value <= args.chapters)
    config = BenchmarkConfig(
        chapters=args.chapters,
        checkpoints=checkpoints,
        generation_calls_per_chapter=args.generation_calls,
        context_char_limit=args.context_chars,
    )
    resolved_model = args.model or DEFAULT_MODEL
    model = BudgetedModel(
        ask_hive,
        model=resolved_model,
        model_digest=_ollama_model_digest(
            resolved_model,
            generate_url=OLLAMA_URL,
        ),
        generation_calls_per_chapter=config.generation_calls_per_chapter,
    )
    runner = WebNovelBenchmarkRunner(
        seed=seed,
        contract=contract,
        story_boundary=story_boundary,
        output_dir=args.output_dir,
        model=model,
        config=config,
    )
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
