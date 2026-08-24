"""ADI-001 Protocol v2: matched causal-degradation experiment.

Protocol v2 is fresh-only and deliberately separate from the frozen Protocol-v1
runner/evidence.  It tests generation procedure under one shared canonical Story
Map interface and one shared deterministic promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adi_story_boundary import (
    BOUNDARY_PROTOCOL_ID,
    ADIStoryBoundary,
    StoryBoundaryError,
    canonical_sha256,
    load_adi_story_boundary,
)
from .protocol_v2_audit import ProtocolV2AuditStore
from .protocol_v2_metrics import (
    METRICS_SCHEMA_VERSION,
    ChapterMetrics,
    ConditionTrajectory,
    MetricJudgment,
    RevisionChange,
)
from .story_map import (
    CanonicalState,
    STATE_CATEGORIES,
    StoryMap,
    StoryMapError,
    load_story_map,
)
from .webnovel_benchmark import (
    ValidatedStateUpdate,
    _atomic_write_text,
    _extract_json,
    _ollama_model_digest,
    _sha256_text,
)


PROTOCOL_V2_ID = "adi-001-causal-degradation-v2.0.0"
PROTOCOL_V2_SCHEMA_VERSION = 1
PROTOCOL_V2_GENERATION_CALLS = 3
PROTOCOL_V2_CONTEXT_CHAR_LIMIT = 60_000
PROTOCOL_V2_CONDITION_ORDER = ("baseline", "kingdom")
PROTOCOL_V2_EXPECTED_SMOKE_CALLS = 10
PROTOCOL_V2_MODEL = "qwen2.5-coder:7b"
PROTOCOL_V2_MODEL_DIGEST = (
    "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"
)
PROTOCOL_V2_REQUEST_TIMEOUT_SECONDS = 900
PROTOCOL_V2_OLLAMA_NUM_CTX = 32_768
PROTOCOL_V2_OLLAMA_NUM_PREDICT = 2_048
PROTOCOL_V2_OLLAMA_TEMPERATURE = 0.2
PROTOCOL_V2_OLLAMA_SEED = 42_001
FROZEN_V1_REVISION = "32e44a66acab25320ac5aa7e508e55018128043a"
FROZEN_V1_RELATIVE_DIR = Path(
    ".hive/benchmarks/adi_001/smoke-story-map-v1-32e44a6"
)
PROTOCOL_V2_SMOKE_RELATIVE_OUTPUT = Path(
    ".hive/benchmarks/adi_001/protocol-v2-smoke-ch2-v2-001"
)
PROTOCOL_V2_LONGITUDINAL_RELATIVE_OUTPUT = Path(
    ".hive/benchmarks/adi_001/protocol-v2-longitudinal-10-v2-001"
)
FROZEN_V1_FILES: Mapping[str, tuple[int, str]] = {
    "calls.jsonl": (
        2_153,
        "9b5fb364da1421041ab34a2013967b92907b5f9f8f7931d43cf58009faaf9c47",
    ),
    "manifest.json": (
        2_155,
        "1510f8634e078bd341173397108ea83ece3b9cd4179cda860b45387d912b80e2",
    ),
    "rejected/baseline/chapter_0002-0a220aedce4a.json": (
        10_464,
        "eb6c88a5765f437747dc6a41c894f0287da8fca72f77c65ac31b16baf827b650",
    ),
}
PROTOCOL_V2_CRITICAL_SOURCE_FILES = (
    "hive_llm.py",
    "kingdom/adi_story_boundary.py",
    "kingdom/story_map.py",
    "kingdom/webnovel_benchmark.py",
    "kingdom/protocol_v2_audit.py",
    "kingdom/protocol_v2_metrics.py",
    "kingdom/webnovel_benchmark_v2.py",
)
PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS = (
    *PROTOCOL_V2_CRITICAL_SOURCE_FILES,
    "benchmarks/adi_001_richest_man_breathing/SEED.md",
    "benchmarks/adi_001_richest_man_breathing/CONTRACT.md",
    "benchmarks/adi_001_richest_man_breathing/STORY_MAP.json",
    "benchmarks/adi_001_richest_man_breathing/PROTOCOL_V2.md",
)
PROTOCOL_V2_PIPELINES = {
    "baseline": (
        "ordinary causal chapter outline",
        "sequential prose draft",
        "ordinary holistic revision",
    ),
    "kingdom": (
        "dependency-obligation-intent construction plan",
        "prose synthesis",
        "terminal critical-path revision",
    ),
}


BASELINE_PLAN_INSTRUCTION = """Create an ordinary novelist's causal outline for Chapter {chapter}.
Use the canonical Story Map as authority and continue naturally from the verified prose tail.
Cover scene causality, established character behavior, open story pressure, and a grounded ending.
Material labeled locked future intent is direction, not a current fact, ability, possession, or piece
of character knowledge. Return only a practical outline, not prose."""

BASELINE_DRAFT_INSTRUCTION = """Write Chapter {chapter} as finished serial-novel prose from the
ordinary outline. The outline is subordinate to the canonical Story Map. Earn every new result in
the scene, preserve the verified boundary, and return only the complete chapter."""

BASELINE_REVISION_INSTRUCTION = """Perform the one pre-registered ordinary holistic revision.
Fix continuity, causality, characterization, pacing, prose, and outline-to-draft problems against the
canonical Story Map. Do not treat locked future intent as current canon. Return only the complete
final chapter; there is no later repair call."""

KINGDOM_PLAN_INSTRUCTION = """Construct a dependency/obligation/intent plan for Chapter {chapter}.
Walk the canonical Story Map through continuity and chronology, who-knows-what, causal prerequisites,
open obligations and mysteries, progression/economic math, character pressure, setup/payoff, and
original intent. Adversarially identify lore leaks, unearned escalation, and future-to-current promotion.
Return JSON with chapter_goal, causal_chain, prerequisites, obligations, progression_checks,
forbidden_moves, setup_payoff_links, and terminal_intent_checks. The plan is not canon and is not prose."""

KINGDOM_DRAFT_INSTRUCTION = """Synthesize Chapter {chapter} as finished serial-novel prose from the
construction plan. The plan is subordinate to the canonical Story Map. Earn every state change and
return only the complete chapter, with no plan or commentary."""

KINGDOM_REVISION_INSTRUCTION = """Perform the one pre-registered terminal Critical-Path revision.
Walk every dependency, obligation, progression/economic claim, setup/payoff, and original-intent check
through the actual draft. Repair contradictions, missing prerequisites, premature reveals, and intent
drift. Return only the complete final chapter; there is no guard-triggered repair call."""

METRICS_JUDGE_INSTRUCTION = """You are a condition-blind causal-degradation judge, not a prose
preference judge. Evaluate only the admitted chapter/state against labeled authority and the prior
accepted state. Split continuity failures into mutually exclusive counts: factual continuity
contradictions; missing, broken, or reversed causal prerequisites; and obligations that are
contradicted, falsely resolved, or silently dropped after they are due. An open obligation is
dependency load, not automatically an error. continuity_violations must equal the sum of those
three subcounts. Separately count concrete progression/economic errors.
Score intent drift from 0 (fully aligned) to 100 (maximal drift). Score repair burden from 0 (draft
needed no further substantive repair) to 100 (the admitted final still requires reconstruction).
Judge residual post-final repair debt only: do not penalize how much the pre-registered revision
changed the draft. Evidence items must identify exact chapter/state facts; do not reward prettier
prose, complexity, architecture, or effort. Return exactly one JSON object with keys
schema_version, chapter, continuity_violations, factual_continuity_violations,
causal_prerequisite_violations, obligation_violations, progression_economic_errors,
intent_drift_score, repair_burden_score, rationale, evidence. schema_version is 1; counts are
nonnegative integers; scores are numbers from 0 to 100; rationale is a nonempty list of strings;
evidence is a list of strings. Do not name or infer the generating condition."""

PROTOCOL_V2_FROZEN_PROMPT_SHA256: Mapping[str, str] = {
    "baseline_plan": "060b3118ed7dd06414133d25282e1969773bb44ee4ae1b6fbf0bfdce26243899",
    "baseline_draft": "18d866d263f4c7917e840ba6554b2f5f2751c5d069e6ae606b1af77b004c8d2a",
    "baseline_revision": "70683e209c4ca9ce16cf7050debcad4020977845f96e1b2ba497c6b567e5cedd",
    "kingdom_plan": "ce58b163786a2511468f76124e2777acd7e82af60396f103a3fe17782d498c2e",
    "kingdom_draft": "af14d8b69838dc98779b2cb906c1f2dc4d4707f149802726a3d3192a797fc09d",
    "kingdom_revision": "7b0e15cd842b392738447df3d9c118d248164d392636fb1ceadbbbc29fd66d64",
    "metrics_judge": "19bfd35b889c5a9ee931a2085a050da824e273e97989496355ff54ab4b7a6d88",
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_mapping(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _story_map_frozen_core_sha256(raw: Mapping[str, Any]) -> str:
    """Hash everything except newly added, post-smoke Chapter 3+ coverage."""

    def thaw(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): thaw(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [thaw(item) for item in value]
        return value

    copied = thaw(raw)
    coverage_fields = (
        "chapter_frontiers",
        "locked_terms_by_chapter",
        "forbidden_patterns_by_chapter",
        "opening_requirements_by_chapter",
    )
    for field in coverage_fields:
        value = copied.get(field)
        if not isinstance(value, dict):
            raise ValueError(f"Story Map {field} must be an object")
        retained: dict[str, Any] = {}
        for chapter_text, entry in value.items():
            try:
                chapter = int(chapter_text)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Story Map {field} contains invalid chapter key "
                    f"{chapter_text!r}"
                ) from error
            if chapter < 3:
                retained[str(chapter)] = entry
        copied[field] = retained
    return _hash_mapping(copied)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _prompt_template_hashes() -> dict[str, str]:
    templates = {
        "baseline_plan": BASELINE_PLAN_INSTRUCTION,
        "baseline_draft": BASELINE_DRAFT_INSTRUCTION,
        "baseline_revision": BASELINE_REVISION_INSTRUCTION,
        "kingdom_plan": KINGDOM_PLAN_INSTRUCTION,
        "kingdom_draft": KINGDOM_DRAFT_INSTRUCTION,
        "kingdom_revision": KINGDOM_REVISION_INSTRUCTION,
        "metrics_judge": METRICS_JUDGE_INSTRUCTION,
    }
    observed = {name: _sha256_text(text) for name, text in templates.items()}
    if observed != dict(PROTOCOL_V2_FROZEN_PROMPT_SHA256):
        raise RuntimeError(
            "Protocol-v2 prompt templates changed without a protocol identity bump"
        )
    return observed


def _require_complete_prompt(text: str, *, label: str, limit: int) -> str:
    """Fail closed instead of clipping any authority-bearing prompt."""

    if len(text) > limit:
        raise RuntimeError(
            f"Protocol v2 {label} prompt is {len(text)} characters, above the "
            f"frozen {limit}-character safety limit; authority cannot be clipped"
        )
    return text


def _authority_prompt(text: str, limit: int) -> str:
    return _require_complete_prompt(
        text,
        label="authority-bearing",
        limit=limit,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_v1_evidence(
    evidence_dir: Path,
    *,
    expected_files: Mapping[str, tuple[int, str]] = FROZEN_V1_FILES,
) -> dict[str, dict[str, Any]]:
    """Read-only verification that the sealed Protocol-v1 smoke is untouched."""

    root = evidence_dir.resolve()
    if not root.is_dir():
        raise RuntimeError(f"sealed Protocol-v1 evidence directory is missing: {root}")
    observed_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    expected_names = set(expected_files)
    if observed_files != expected_names:
        raise RuntimeError(
            "sealed Protocol-v1 evidence file set changed: "
            f"missing={sorted(expected_names - observed_files)}, "
            f"unexpected={sorted(observed_files - expected_names)}"
        )
    verified: dict[str, dict[str, Any]] = {}
    for relative_name in sorted(expected_files):
        expected_bytes, expected_sha256 = expected_files[relative_name]
        path = root / Path(relative_name)
        actual_bytes = path.stat().st_size
        actual_sha256 = _file_sha256(path)
        if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"sealed Protocol-v1 evidence changed: {relative_name}; "
                f"expected bytes={expected_bytes}, sha256={expected_sha256}; "
                f"observed bytes={actual_bytes}, sha256={actual_sha256}"
            )
        verified[relative_name] = {
            "bytes": actual_bytes,
            "sha256": actual_sha256,
        }
    return verified


def verify_smoke_qualification(
    path: Path,
    *,
    current_source_file_sha256: Mapping[str, str],
    current_story_map_frozen_core_sha256: str,
) -> dict[str, Any]:
    """Verify a completed symmetric Chapter-2 smoke for a later long run."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"longitudinal qualification is unreadable: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("longitudinal qualification must be a JSON object")
    unhashed = dict(payload)
    stored_hash = unhashed.pop("status_payload_sha256", None)
    if stored_hash != _hash_mapping(unhashed):
        raise RuntimeError("longitudinal qualification status hash is invalid")
    required = {
        "protocol_id": PROTOCOL_V2_ID,
        "status": "symmetric_smoke_passed",
        "symmetric_smoke_passed": True,
        "winner": None,
        "model": PROTOCOL_V2_MODEL,
        "model_digest": PROTOCOL_V2_MODEL_DIGEST,
        "prompt_template_sha256": _prompt_template_hashes(),
        "completed_paired_admitted_chapters": [2],
        "story_map_frozen_core_sha256": (
            current_story_map_frozen_core_sha256
        ),
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise RuntimeError(
                f"longitudinal qualification has invalid {key}: "
                f"expected {expected!r}, got {payload.get(key)!r}"
            )
    audit = payload.get("audit_index")
    if not isinstance(audit, dict) or audit.get("call_count") != 10:
        raise RuntimeError(
            "longitudinal qualification must index exactly ten smoke calls"
        )
    calls = audit.get("calls")
    if not isinstance(calls, list) or len(calls) != 10:
        raise RuntimeError(
            "longitudinal qualification must index ten call artifacts"
        )
    run_root = path.resolve().parent
    for expected_sequence, record in enumerate(calls, start=1):
        expected_call_id = f"call_{expected_sequence:06d}"
        if not isinstance(record, dict) or record.get("call_id") != expected_call_id:
            raise RuntimeError(
                "longitudinal qualification call index is not contiguous"
            )
        expected_digest = record.get("artifact_file_sha256")
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            raise RuntimeError(
                f"longitudinal qualification {expected_call_id} lacks an artifact hash"
            )
        artifact_path = (
            run_root / "evidence" / "calls" / f"{expected_call_id}.json"
        )
        if not artifact_path.is_file() or _file_sha256(
            artifact_path
        ) != expected_digest:
            raise RuntimeError(
                f"longitudinal qualification call evidence changed: "
                f"{expected_call_id}"
            )
    result_path = path.with_name("RESULT.md")
    if not result_path.is_file():
        raise RuntimeError("longitudinal qualification RESULT.md is missing")
    smoke_sources = payload.get("source_file_sha256")
    if not isinstance(smoke_sources, dict):
        raise RuntimeError(
            "longitudinal qualification lacks protocol source bindings"
        )
    allowed_story_map_change = (
        "benchmarks/adi_001_richest_man_breathing/STORY_MAP.json"
    )
    fixed_paths = set(PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS) - {
        allowed_story_map_change
    }
    if set(smoke_sources) != set(PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS):
        raise RuntimeError(
            "longitudinal qualification source binding set is incomplete"
        )
    changed_fixed = sorted(
        relative
        for relative in fixed_paths
        if smoke_sources.get(relative) != current_source_file_sha256.get(relative)
    )
    if changed_fixed:
        raise RuntimeError(
            "longitudinal Protocol v2 code/prompts/authority changed after the "
            f"smoke: {changed_fixed}"
        )
    return {
        "run_status_path": str(path.resolve()),
        "run_status_sha256": _file_sha256(path),
        "result_sha256": _file_sha256(result_path),
        "source_revision": payload.get("source_revision"),
        "story_map_sha256": payload.get("story_map_sha256"),
        "allowed_post_smoke_change": allowed_story_map_change,
        "current_story_map_sha256": current_source_file_sha256[
            allowed_story_map_change
        ],
        "call_count": 10,
    }


def _require_canonical_cli_output(
    repo_root: Path,
    output_dir: Path,
    *,
    chapters: int,
) -> Path:
    """Give each pre-registered CLI phase exactly one canonical attempt path."""

    if chapters == 2:
        relative = PROTOCOL_V2_SMOKE_RELATIVE_OUTPUT
    elif chapters == 10:
        relative = PROTOCOL_V2_LONGITUDINAL_RELATIVE_OUTPUT
    else:
        raise ValueError("Protocol v2 CLI permits only the 2- or 10-chapter phase")
    expected = (repo_root / relative).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(
            f"Protocol v2 canonical {chapters}-chapter output is {expected}; "
            "a different directory would create an unregistered retry"
        )
    return expected


def canonical_story_map_interface(
    boundary: ADIStoryBoundary,
    state: CanonicalState,
    *,
    chapter: int,
    prior_tail: str,
) -> str:
    """Render the one byte-identical writer interface consumed by both arms."""

    return (
        boundary.shared_writer_packet(chapter=chapter)
        + "\n\nCANONICAL STORY MAP — CURRENT CLAIM LEDGER\n"
        + "This complete typed ledger is the only dynamic current-canon authority. "
        + "Statuses, dependencies, and provenance are evidence, not optional suggestions.\n"
        + json.dumps(state.to_mapping(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n\nVERIFIED RECENT PROSE TAIL\n"
        + prior_tail
    )


def _story_map_mapping(story_map: StoryMap) -> dict[str, Any]:
    claims: dict[str, list[dict[str, Any]]] = {
        category: [] for category in STATE_CATEGORIES
    }
    for claim in story_map.claims:
        evidence: dict[str, Any] = {
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


def _open_obligation_count(state: CanonicalState) -> int:
    return sum(
        claim.category == "obligations"
        and claim.status not in {"resolved", "failed", "cancelled"}
        for claim in state.claims
    )


@dataclass(frozen=True)
class ProtocolV2Config:
    chapters: int = 2
    generation_calls_per_chapter: int = PROTOCOL_V2_GENERATION_CALLS
    context_char_limit: int = PROTOCOL_V2_CONTEXT_CHAR_LIMIT
    condition_order: tuple[str, ...] = PROTOCOL_V2_CONDITION_ORDER


@dataclass(frozen=True)
class GenerationBundle:
    condition: str
    chapter: int
    plan: str
    draft: str
    final_response: str
    call_ids: tuple[str, str, str]

    @property
    def normalized_final(self) -> str:
        return self.final_response.rstrip() + "\n"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "chapter": self.chapter,
            "plan": self.plan,
            "plan_sha256": _sha256_text(self.plan),
            "draft": self.draft,
            "draft_sha256": _sha256_text(self.draft),
            "raw_final_response": self.final_response,
            "raw_final_response_sha256": _sha256_text(self.final_response),
            "normalized_final": self.normalized_final,
            "normalized_final_sha256": _sha256_text(self.normalized_final),
            "normalization": "raw_final_response.rstrip() + single LF",
            "call_ids": list(self.call_ids),
        }


@dataclass(frozen=True)
class ProtocolV2Outcome:
    status: str
    exit_code: int
    chapter: int | None
    condition: str | None
    reason: str


class BaselineV2Writer:
    def __init__(
        self,
        model: ProtocolV2AuditStore,
        boundary: ADIStoryBoundary,
        config: ProtocolV2Config,
    ) -> None:
        self.model = model
        self.boundary = boundary
        self.config = config

    def write(
        self,
        chapter: int,
        state: CanonicalState,
        prior_tail: str,
    ) -> GenerationBundle:
        common = canonical_story_map_interface(
            self.boundary, state, chapter=chapter, prior_tail=prior_tail
        )
        plan = self.model.ask(
            _authority_prompt(
                common + "\n\n" + BASELINE_PLAN_INSTRUCTION.format(chapter=chapter),
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["baseline"][0],
            role="default",
        )
        plan_call = self.model.last_call_id
        draft = self.model.ask(
            _authority_prompt(
                common
                + "\n\nORDINARY OUTLINE\n"
                + plan
                + "\n\n"
                + BASELINE_DRAFT_INSTRUCTION.format(chapter=chapter),
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["baseline"][1],
            role="default",
        )
        draft_call = self.model.last_call_id
        final = self.model.ask(
            _authority_prompt(
                common
                + "\n\nORDINARY OUTLINE\n"
                + plan
                + "\n\nDRAFT CHAPTER\n"
                + draft
                + "\n\n"
                + BASELINE_REVISION_INSTRUCTION,
                self.config.context_char_limit,
            ),
            condition="baseline",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["baseline"][2],
            role="default",
        )
        final_call = self.model.last_call_id
        assert plan_call and draft_call and final_call
        return GenerationBundle(
            condition="baseline",
            chapter=chapter,
            plan=plan,
            draft=draft,
            final_response=final,
            call_ids=(plan_call, draft_call, final_call),
        )


class KingdomV2Writer:
    def __init__(
        self,
        model: ProtocolV2AuditStore,
        boundary: ADIStoryBoundary,
        config: ProtocolV2Config,
    ) -> None:
        self.model = model
        self.boundary = boundary
        self.config = config

    def write(
        self,
        chapter: int,
        state: CanonicalState,
        prior_tail: str,
    ) -> GenerationBundle:
        common = canonical_story_map_interface(
            self.boundary, state, chapter=chapter, prior_tail=prior_tail
        )
        plan = self.model.ask(
            _authority_prompt(
                common + "\n\n" + KINGDOM_PLAN_INSTRUCTION.format(chapter=chapter),
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["kingdom"][0],
            role="strategic",
        )
        plan_call = self.model.last_call_id
        draft = self.model.ask(
            _authority_prompt(
                common
                + "\n\nCONSTRUCTION PLAN\n"
                + plan
                + "\n\n"
                + KINGDOM_DRAFT_INSTRUCTION.format(chapter=chapter),
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["kingdom"][1],
            role="coder",
        )
        draft_call = self.model.last_call_id
        final = self.model.ask(
            _authority_prompt(
                common
                + "\n\nCONSTRUCTION PLAN\n"
                + plan
                + "\n\nDRAFT CHAPTER\n"
                + draft
                + "\n\n"
                + KINGDOM_REVISION_INSTRUCTION,
                self.config.context_char_limit,
            ),
            condition="kingdom",
            chapter=chapter,
            purpose=PROTOCOL_V2_PIPELINES["kingdom"][2],
            role="reflector",
        )
        final_call = self.model.last_call_id
        assert plan_call and draft_call and final_call
        return GenerationBundle(
            condition="kingdom",
            chapter=chapter,
            plan=plan,
            draft=draft,
            final_response=final,
            call_ids=(plan_call, draft_call, final_call),
        )


class ProtocolV2StateProposalRejected(RuntimeError):
    """A model branch failed to supply an admissible canonical-state delta."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str,
        classification: str,
        illegal_state_promotions: int,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.classification = classification
        self.illegal_state_promotions = illegal_state_promotions


class ProtocolV2StateExtractor:
    """Shared proposal interface; deterministic code alone may promote state."""

    def __init__(
        self,
        model: ProtocolV2AuditStore,
        boundary: ADIStoryBoundary,
        config: ProtocolV2Config,
    ) -> None:
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
        empty_categories = ", ".join(
            f'"{name}": []' for name in STATE_CATEGORIES
        )
        prompt = _authority_prompt(
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
            missing_categories = [
                category
                for category in ("facts", "chapter_summaries")
                if not any(claim.category == category for claim in proposed.claims)
            ]
            if missing_categories:
                raise ValueError(
                    "state delta lacks required evidence-backed categories: "
                    + ", ".join(missing_categories)
                )
        except (ValueError, StoryMapError) as error:
            raise ProtocolV2StateProposalRejected(
                f"state proposal invalid for {condition} Chapter {chapter}: {error}",
                raw_response=raw,
                classification="candidate_state_schema_rejected",
                illegal_state_promotions=0,
            ) from error

        try:
            state, report = self.boundary.validate_and_update(
                prior,
                proposed,
                chapter_text=text,
                chapter=chapter,
            )
        except (StoryBoundaryError, StoryMapError) as error:
            raise ProtocolV2StateProposalRejected(
                f"Story Map promotion guard rejected {condition} Chapter {chapter}: {error}",
                raw_response=raw,
                classification="deterministic_promotion_guard_rejected",
                illegal_state_promotions=1,
            ) from error
        return ValidatedStateUpdate(
            state=state,
            proposed_map=proposed,
            guard_report=report,
        )


class ProtocolV2MetricsJudge:
    def __init__(
        self,
        model: ProtocolV2AuditStore,
        boundary: ADIStoryBoundary,
        contract: str,
        config: ProtocolV2Config,
    ) -> None:
        self.model = model
        self.boundary = boundary
        self.contract = contract
        self.config = config

    def judge(
        self,
        *,
        chapter: int,
        condition: str,
        prior_state: CanonicalState,
        accepted_state: CanonicalState,
        bundle: GenerationBundle,
    ) -> tuple[MetricJudgment, str]:
        prompt = _authority_prompt(
            self.boundary.shared_writer_packet(chapter=chapter)
            + "\n\nAUTHORIAL CONTRACT — INTENT AUTHORITY, NOT CURRENT CANON\n"
            + self.contract
            + "\n\nPRIOR ACCEPTED STATE\n"
            + _canonical_json(prior_state.to_mapping())
            + "\n\nPOST-CHAPTER ACCEPTED STATE\n"
            + _canonical_json(accepted_state.to_mapping())
            + "\n\nADMITTED FINAL CHAPTER\n"
            + bundle.normalized_final
            + "\n\n"
            + METRICS_JUDGE_INSTRUCTION,
            self.config.context_char_limit,
        )
        raw = self.model.ask(
            prompt,
            condition=condition,
            chapter=chapter,
            purpose="condition-blind causal degradation metrics",
            role="reflector",
            budget_class="evaluation",
        )
        call_id = self.model.last_call_id
        assert call_id
        judgment = MetricJudgment.from_mapping(_extract_json(raw))
        if judgment.chapter != chapter:
            raise ValueError(
                f"metrics judge returned Chapter {judgment.chapter}, expected {chapter}"
            )
        return judgment, call_id


class ProtocolV2Runner:
    def __init__(
        self,
        *,
        seed: str,
        contract: str,
        protocol_document: str,
        story_boundary: ADIStoryBoundary,
        output_dir: Path,
        ask_fn: Any,
        model_name: str,
        model_digest: str,
        source_revision: str,
        source_file_sha256: Mapping[str, str],
        frozen_v1_evidence_dir: Path,
        config: ProtocolV2Config,
        frozen_v1_expected_files: Mapping[str, tuple[int, str]] = FROZEN_V1_FILES,
        smoke_qualification_file: Path | None = None,
    ) -> None:
        self.seed = seed
        self.contract = contract
        self.protocol_document = protocol_document
        self.boundary = story_boundary
        self.output_dir = output_dir
        self.ask_fn = ask_fn
        self.model_name = model_name
        self.model_digest = model_digest
        self.source_revision = source_revision
        self.source_file_sha256 = dict(source_file_sha256)
        self.frozen_v1_evidence_dir = frozen_v1_evidence_dir
        self.frozen_v1_expected_files = dict(frozen_v1_expected_files)
        self.smoke_qualification_file = smoke_qualification_file
        self.config = config
        self.seed_sha256 = _sha256_text(seed)
        self.contract_sha256 = _sha256_text(contract)
        self.model: ProtocolV2AuditStore | None = None
        self.verified_v1_evidence: dict[str, dict[str, Any]] | None = None
        self.verified_smoke_qualification: dict[str, Any] | None = None
        self._final_status_written = False

        if story_boundary.seed_sha256 != self.seed_sha256:
            raise ValueError("runner seed does not match the frozen Story Map")
        if story_boundary.contract_sha256 != self.contract_sha256:
            raise ValueError("runner contract does not match the frozen Story Map")

    def _preflight(self) -> None:
        if self.model_name != PROTOCOL_V2_MODEL:
            raise ValueError(
                f"Protocol v2 requires model {PROTOCOL_V2_MODEL!r}, got "
                f"{self.model_name!r}"
            )
        if self.model_digest != PROTOCOL_V2_MODEL_DIGEST:
            raise ValueError(
                "Protocol v2 requires the frozen qwen2.5-coder:7b model digest"
            )
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_revision):
            raise ValueError("Protocol v2 requires an exact source Git SHA")
        if self.source_revision == FROZEN_V1_REVISION:
            raise ValueError("Protocol v2 cannot claim the Protocol-v1 source revision")
        if set(self.source_file_sha256) != set(
            PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS
        ):
            raise ValueError("Protocol v2 source-file binding set is incomplete")
        if not all(
            re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in self.source_file_sha256.values()
        ):
            raise ValueError("Protocol v2 source-file bindings must be SHA-256 digests")
        if self.output_dir.exists():
            raise FileExistsError(
                f"Protocol v2 requires a fresh run directory: {self.output_dir}"
            )
        sealed_root = self.frozen_v1_evidence_dir.resolve()
        output_root = self.output_dir.resolve()
        if output_root == sealed_root or sealed_root in output_root.parents:
            raise ValueError(
                "Protocol v2 output cannot be inside the sealed Protocol-v1 evidence"
            )
        self.verified_v1_evidence = verify_frozen_v1_evidence(
            self.frozen_v1_evidence_dir,
            expected_files=self.frozen_v1_expected_files,
        )
        if self.config.chapters < 2:
            raise ValueError("Protocol v2 must include at least Chapter 2")
        if self.config.chapters == 2:
            if self.smoke_qualification_file is not None:
                raise ValueError(
                    "the Chapter-2 smoke must not consume a prior qualification"
                )
        else:
            if self.smoke_qualification_file is None:
                raise ValueError(
                    "longitudinal Protocol v2 requires a verified passing "
                    "Chapter-2 smoke qualification"
                )
            self.verified_smoke_qualification = verify_smoke_qualification(
                self.smoke_qualification_file,
                current_source_file_sha256=self.source_file_sha256,
                current_story_map_frozen_core_sha256=(
                    _story_map_frozen_core_sha256(self.boundary.raw)
                ),
            )
        if self.config.context_char_limit != PROTOCOL_V2_CONTEXT_CHAR_LIMIT:
            raise ValueError("Protocol v2 context character safety limit is frozen")
        if self.config.generation_calls_per_chapter != PROTOCOL_V2_GENERATION_CALLS:
            raise ValueError("Protocol v2 requires exactly three generation calls")
        if self.config.condition_order != PROTOCOL_V2_CONDITION_ORDER:
            raise ValueError("Protocol v2 condition order is frozen as baseline then Kingdom")
        requested = range(2, self.config.chapters + 1)
        missing_frontiers = [
            chapter for chapter in requested if chapter not in self.boundary.chapter_frontiers
        ]
        missing_locks = [
            chapter
            for chapter in requested
            if chapter not in self.boundary.locked_terms_by_chapter
        ]
        missing_rules = [
            chapter
            for chapter in requested
            if chapter not in self.boundary.forbidden_patterns_by_chapter
        ]
        missing_openings = [
            chapter
            for chapter in requested
            if chapter not in self.boundary.opening_requirements_by_chapter
        ]
        if missing_frontiers or missing_locks or missing_rules or missing_openings:
            raise ValueError(
                "Protocol v2 lacks reviewed Story Map coverage: "
                f"frontiers={missing_frontiers}, locks={missing_locks}, "
                f"rules={missing_rules}, openings={missing_openings}"
            )

    def _manifest(self) -> dict[str, Any]:
        assert self.model is not None
        initial_interface = canonical_story_map_interface(
            self.boundary,
            self.boundary.initial_state,
            chapter=2,
            prior_tail=self.boundary.chapter_one_tail,
        )
        return {
            "schema_version": PROTOCOL_V2_SCHEMA_VERSION,
            "protocol_id": PROTOCOL_V2_ID,
            "source_revision": self.source_revision,
            "source_file_sha256": dict(sorted(self.source_file_sha256.items())),
            "fresh_only_no_resume": True,
            "frozen_v1_predecessor_revision": FROZEN_V1_REVISION,
            "frozen_v1_evidence_directory": str(
                self.frozen_v1_evidence_dir.resolve()
            ),
            "frozen_v1_evidence_verified": self.verified_v1_evidence,
            "smoke_qualification": self.verified_smoke_qualification,
            "purpose": (
                "test whether Kingdom's causal-dependency procedure degrades more "
                "slowly than ordinary generation under shared Story Map authority"
            ),
            "no_chapter_two_winner_claim": True,
            "seed_sha256": self.seed_sha256,
            "contract_sha256": self.contract_sha256,
            "story_map_sha256": self.boundary.source_map_sha256,
            "story_map_frozen_core_sha256": (
                _story_map_frozen_core_sha256(self.boundary.raw)
            ),
            "initial_state_sha256": self.boundary.initial_state_sha256,
            "chapter_one_sha256": self.boundary.chapter_one_sha256,
            "chapter_one_tail_sha256": self.boundary.chapter_one_tail_sha256,
            "story_boundary_protocol": BOUNDARY_PROTOCOL_ID,
            "protocol_document_sha256": _sha256_text(self.protocol_document),
            "canonical_writer_interface": {
                "same_renderer_for_both_conditions": True,
                "initial_chapter_two_sha256": _sha256_text(initial_interface),
                "contains_complete_typed_claim_ledger": True,
            },
            "condition_order": list(self.config.condition_order),
            "generation_calls_per_chapter_per_condition": (
                self.config.generation_calls_per_chapter
            ),
            "generation_pipelines": {
                name: list(pipeline) for name, pipeline in PROTOCOL_V2_PIPELINES.items()
            },
            "prompt_template_sha256": _prompt_template_hashes(),
            "model": self.model_name,
            "model_digest": self.model_digest,
            "runtime": self.model.frozen_config,
            "chapters": self.config.chapters,
            "context_char_limit": self.config.context_char_limit,
            "state_proposals_per_admitted_condition_chapter": 1,
            "metrics_judges_per_admitted_condition_chapter": 1,
            "pairwise_preference_calls": 0,
            "expected_chapter_two_smoke_physical_calls_if_admitted": (
                PROTOCOL_V2_EXPECTED_SMOKE_CALLS
            ),
            "expected_total_physical_calls_if_all_requested_chapters_admitted": (
                (self.config.chapters - 1) * PROTOCOL_V2_EXPECTED_SMOKE_CALLS
            ),
            "stop_on_first_branch_rejection": True,
            "guard_repair_calls": 0,
            "metrics_schema_version": METRICS_SCHEMA_VERSION,
            "degradation_slope": "least-squares error-index units per chapter",
        }

    def _write_final_status(self, payload: Mapping[str, Any]) -> None:
        if self._final_status_written:
            raise RuntimeError("Protocol v2 final status is immutable")
        enriched = dict(payload)
        enriched["schema_version"] = PROTOCOL_V2_SCHEMA_VERSION
        enriched["protocol_id"] = PROTOCOL_V2_ID
        enriched["source_revision"] = self.source_revision
        enriched["source_file_sha256"] = dict(
            sorted(self.source_file_sha256.items())
        )
        enriched["model"] = self.model_name
        enriched["model_digest"] = self.model_digest
        enriched["story_map_sha256"] = self.boundary.source_map_sha256
        enriched["story_map_frozen_core_sha256"] = (
            _story_map_frozen_core_sha256(self.boundary.raw)
        )
        enriched["prompt_template_sha256"] = _prompt_template_hashes()
        if self.model is not None:
            enriched["audit_index"] = self.model.manifest_index()
        enriched["status_payload_sha256"] = _hash_mapping(enriched)
        path = self.output_dir / "RUN_STATUS.json"
        if path.exists():
            raise RuntimeError("Protocol v2 RUN_STATUS.json already exists")
        _write_json(path, enriched)
        self._final_status_written = True

    def _prior_tail(
        self,
        accepted_bundles: Mapping[str, Mapping[int, GenerationBundle]],
        condition: str,
        chapter: int,
    ) -> str:
        if chapter == 2:
            return self.boundary.chapter_one_tail
        return accepted_bundles[condition][chapter - 1].normalized_final[-12_000:]

    def _persist_guard_decision(
        self,
        *,
        condition: str,
        chapter: int,
        accepted: bool,
        decision_id: str,
        stage: str,
        bundle: GenerationBundle,
        error: Exception | None = None,
        report: Mapping[str, Any] | None = None,
        state_proposal_call_id: str | None = None,
        classification: str | None = None,
        illegal_state_promotions: int = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "protocol_id": PROTOCOL_V2_ID,
            "condition": condition,
            "chapter": chapter,
            "accepted": accepted,
            "decision_id": decision_id,
            "stage": stage,
            "candidate_sha256": _sha256_text(bundle.normalized_final),
            "generation_call_ids": list(bundle.call_ids),
            "state_proposal_call_id": state_proposal_call_id,
            "classification": classification,
            "illegal_state_promotions": illegal_state_promotions,
            "report": dict(report) if report is not None else None,
            "error": (
                None
                if error is None
                else {
                    "type": f"{type(error).__module__}.{type(error).__qualname__}",
                    "message": str(error),
                }
            ),
            "guard_repair_calls": 0,
        }
        payload["decision_sha256"] = _hash_mapping(payload)
        path = (
            self.output_dir
            / "branches"
            / condition
            / f"chapter_{chapter:04d}"
            / f"guard_{decision_id}.json"
        )
        if path.exists():
            raise RuntimeError(f"refusing to overwrite guard decision {path}")
        _write_json(path, payload)
        return payload

    def _persist_rejected_branch(
        self,
        *,
        bundle: GenerationBundle,
        decisions: Sequence[Mapping[str, Any]],
    ) -> None:
        state_decision = next(
            (
                decision
                for decision in decisions
                if decision.get("decision_id") == "state_promotion"
            ),
            None,
        )
        payload = {
            "schema_version": 1,
            "protocol_id": PROTOCOL_V2_ID,
            "result": "rejected",
            "generation": bundle.to_mapping(),
            "guard_decisions": [dict(decision) for decision in decisions],
            "state_proposal_status": (
                "rejected"
                if state_decision is not None
                else "not_run_due_prose_rejection"
            ),
            "state_proposal_call_id": (
                state_decision.get("state_proposal_call_id")
                if state_decision is not None
                else None
            ),
            "canonical_promotion_occurred": False,
        }
        payload["rejected_branch_sha256"] = _hash_mapping(payload)
        _write_json(
            self.output_dir
            / "branches"
            / bundle.condition
            / f"chapter_{bundle.chapter:04d}"
            / "rejected_branch.json",
            payload,
        )

    def _persist_accepted_branch(
        self,
        *,
        bundle: GenerationBundle,
        prior_state: CanonicalState,
        update: ValidatedStateUpdate,
        decisions: Sequence[Mapping[str, Any]],
        state_proposal_call_id: str,
    ) -> None:
        payload = {
            "schema_version": 1,
            "protocol_id": PROTOCOL_V2_ID,
            "result": "admitted",
            "generation": bundle.to_mapping(),
            "prior_state_sha256": canonical_sha256(prior_state.to_mapping()),
            "state_proposal_call_id": state_proposal_call_id,
            "proposed_state": _story_map_mapping(update.proposed_map),
            "accepted_state": update.state.to_mapping(),
            "accepted_state_sha256": canonical_sha256(update.state.to_mapping()),
            "guard_decisions": [dict(decision) for decision in decisions],
            "canonical_promotion_occurred": True,
        }
        payload["accepted_branch_sha256"] = _hash_mapping(payload)
        _write_json(
            self.output_dir
            / "branches"
            / bundle.condition
            / f"chapter_{bundle.chapter:04d}"
            / "accepted_branch.json",
            payload,
        )

    def _branch_rejection(
        self,
        *,
        bundle: GenerationBundle,
        decisions: Sequence[Mapping[str, Any]],
        error: Exception,
        admitted_through: Mapping[str, int],
        completed_paired_chapters: Sequence[int],
        trajectories: Mapping[str, Sequence[ChapterMetrics]],
    ) -> ProtocolV2Outcome:
        self._persist_rejected_branch(bundle=bundle, decisions=decisions)
        illegal_promotions = sum(
            int(decision.get("illegal_state_promotions", 0))
            for decision in decisions
        )
        condition_status: dict[str, dict[str, Any]] = {}
        for condition in self.config.condition_order:
            if condition == bundle.condition:
                terminal_status = "rejected"
                first_rejection_chapter: int | None = bundle.chapter
            elif admitted_through[condition] >= bundle.chapter:
                terminal_status = "right_censored_after_admission_due_symmetric_stop"
                first_rejection_chapter = None
            else:
                terminal_status = "unattempted_due_symmetric_stop"
                first_rejection_chapter = None
            condition_status[condition] = {
                "terminal_status": terminal_status,
                "admitted_through_chapter": admitted_through[condition],
                "first_rejection_chapter": first_rejection_chapter,
            }
        survivor_trajectories = {
            condition: (
                ConditionTrajectory.aggregate(
                    condition, trajectories[condition]
                ).to_mapping()
                if trajectories[condition]
                else None
            )
            for condition in self.config.condition_order
        }
        is_smoke = self.config.chapters == 2
        outcome = ProtocolV2Outcome(
            status=(
                "symmetric_smoke_rejected"
                if is_smoke
                else "longitudinal_branch_rejected"
            ),
            exit_code=2,
            chapter=bundle.chapter,
            condition=bundle.condition,
            reason=str(error),
        )
        self._write_final_status(
            {
                **asdict(outcome),
                "winner": None,
                "phase": "smoke" if is_smoke else "longitudinal",
                "symmetric_smoke_passed": False,
                "longitudinal_run_completed": False,
                "longitudinal_run_authorized": not is_smoke,
                "smoke_qualification_consumed": not is_smoke,
                "interpretation": (
                    "a smoke branch rejection is an experimental result; no A/B "
                    "winner exists"
                    if is_smoke
                    else "first rejection is the longitudinal terminal endpoint; "
                    "no automatic winner is declared"
                ),
                "guard_decisions": [dict(decision) for decision in decisions],
                "condition_terminal_status": condition_status,
                "completed_paired_admitted_chapters": list(
                    completed_paired_chapters
                ),
                "longitudinal_censoring": (
                    "first rejection is a primary terminal endpoint; any slope "
                    "uses only completed paired admitted chapters and is survivor-only"
                ),
                "paired_survivor_trajectories": survivor_trajectories,
                "rejection_metrics": {
                    "continuity_violations": None,
                    "illegal_state_promotions": illegal_promotions,
                    "unresolved_obligations": None,
                    "progression_economic_errors": None,
                    "intent_drift_score": None,
                    "repair_burden_score": None,
                    "degradation_index": None,
                    "degradation_slope": None,
                    "not_judged_because_run_stopped": True,
                },
            }
        )
        return outcome

    def run(self) -> ProtocolV2Outcome:
        self._preflight()
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.model = ProtocolV2AuditStore(
            self.ask_fn,
            self.output_dir / "evidence",
            model=self.model_name,
            model_digest=self.model_digest,
            generation_calls_per_chapter=self.config.generation_calls_per_chapter,
            request_timeout_seconds=PROTOCOL_V2_REQUEST_TIMEOUT_SECONDS,
            ollama_num_ctx=PROTOCOL_V2_OLLAMA_NUM_CTX,
            ollama_num_predict=PROTOCOL_V2_OLLAMA_NUM_PREDICT,
            ollama_temperature=PROTOCOL_V2_OLLAMA_TEMPERATURE,
            ollama_seed=PROTOCOL_V2_OLLAMA_SEED,
        )
        manifest = self._manifest()
        manifest["manifest_payload_sha256"] = _hash_mapping(manifest)
        _write_json(self.output_dir / "manifest.json", manifest)

        baseline = BaselineV2Writer(self.model, self.boundary, self.config)
        kingdom = KingdomV2Writer(self.model, self.boundary, self.config)
        writers = {"baseline": baseline, "kingdom": kingdom}
        extractor = ProtocolV2StateExtractor(
            self.model, self.boundary, self.config
        )
        metrics_judge = ProtocolV2MetricsJudge(
            self.model, self.boundary, self.contract, self.config
        )
        states = {
            "baseline": self.boundary.initial_state,
            "kingdom": self.boundary.initial_state,
        }
        accepted_bundles: dict[str, dict[int, GenerationBundle]] = {
            "baseline": {},
            "kingdom": {},
        }
        trajectories: dict[str, list[ChapterMetrics]] = {
            "baseline": [],
            "kingdom": [],
        }
        admitted_through = {"baseline": 1, "kingdom": 1}
        completed_paired_chapters: list[int] = []

        try:
            for chapter in range(2, self.config.chapters + 1):
                prior_states = dict(states)
                for condition in self.config.condition_order:
                    bundle = writers[condition].write(
                        chapter,
                        states[condition],
                        self._prior_tail(accepted_bundles, condition, chapter),
                    )
                    if self.model.generation_count(condition, chapter) != 3:
                        raise RuntimeError(
                            f"{condition} Chapter {chapter} did not use exactly three "
                            "generation calls"
                        )
                    try:
                        self.boundary.validate_chapter_text(
                            bundle.normalized_final, chapter=chapter
                        )
                    except StoryBoundaryError as error:
                        decision = self._persist_guard_decision(
                            condition=condition,
                            chapter=chapter,
                            accepted=False,
                            decision_id="prose_precheck",
                            stage="final-prose temporal precheck",
                            bundle=bundle,
                            error=error,
                            classification="deterministic_prose_guard_rejected",
                        )
                        return self._branch_rejection(
                            bundle=bundle,
                            decisions=(decision,),
                            error=error,
                            admitted_through=admitted_through,
                            completed_paired_chapters=completed_paired_chapters,
                            trajectories=trajectories,
                        )
                    prose_decision = self._persist_guard_decision(
                        condition=condition,
                        chapter=chapter,
                        accepted=True,
                        decision_id="prose_precheck",
                        stage="final-prose temporal precheck",
                        bundle=bundle,
                        report={"deterministic_precheck": "passed"},
                        classification="deterministic_prose_guard_accepted",
                    )

                    try:
                        update = extractor.update(
                            condition,
                            chapter,
                            states[condition],
                            bundle.normalized_final,
                        )
                        proposal_call_id = self.model.last_call_id
                        assert proposal_call_id
                    except ProtocolV2StateProposalRejected as error:
                        proposal_call_id = self.model.last_call_id
                        decision = self._persist_guard_decision(
                            condition=condition,
                            chapter=chapter,
                            accepted=False,
                            decision_id="state_promotion",
                            stage="state proposal deterministic promotion",
                            bundle=bundle,
                            error=error,
                            state_proposal_call_id=proposal_call_id,
                            classification=error.classification,
                            illegal_state_promotions=(
                                error.illegal_state_promotions
                            ),
                        )
                        return self._branch_rejection(
                            bundle=bundle,
                            decisions=(prose_decision, decision),
                            error=error,
                            admitted_through=admitted_through,
                            completed_paired_chapters=completed_paired_chapters,
                            trajectories=trajectories,
                        )

                    promotion_decision = self._persist_guard_decision(
                        condition=condition,
                        chapter=chapter,
                        accepted=True,
                        decision_id="state_promotion",
                        stage="state proposal deterministic promotion",
                        bundle=bundle,
                        report=update.guard_report.to_mapping(),
                        state_proposal_call_id=proposal_call_id,
                        classification="deterministic_promotion_guard_accepted",
                    )
                    self._persist_accepted_branch(
                        bundle=bundle,
                        prior_state=states[condition],
                        update=update,
                        decisions=(prose_decision, promotion_decision),
                        state_proposal_call_id=proposal_call_id,
                    )
                    states[condition] = update.state
                    accepted_bundles[condition][chapter] = bundle
                    admitted_through[condition] = chapter

                completed_paired_chapters.append(chapter)

                # Metric judges run only after both branches are independently admitted.
                for condition in self.config.condition_order:
                    bundle = accepted_bundles[condition][chapter]
                    revision = RevisionChange.measure(bundle.draft, bundle.final_response)
                    judgment, judge_call_id = metrics_judge.judge(
                        chapter=chapter,
                        condition=condition,
                        prior_state=prior_states[condition],
                        accepted_state=states[condition],
                        bundle=bundle,
                    )
                    metrics = ChapterMetrics(
                        condition=condition,
                        admissible=True,
                        judgment=judgment,
                        illegal_state_promotions=0,
                        unresolved_obligations=_open_obligation_count(states[condition]),
                        revision_change=revision,
                    )
                    trajectories[condition].append(metrics)
                    payload = metrics.to_mapping()
                    payload["judge_call_id"] = judge_call_id
                    payload["metrics_payload_sha256"] = _hash_mapping(payload)
                    _write_json(
                        self.output_dir
                        / "metrics"
                        / condition
                        / f"chapter_{chapter:04d}.json",
                        payload,
                    )

            trajectory_objects = {
                condition: ConditionTrajectory.aggregate(condition, values)
                for condition, values in trajectories.items()
            }
            for condition, trajectory in trajectory_objects.items():
                _write_json(
                    self.output_dir / "metrics" / condition / "trajectory.json",
                    trajectory.to_mapping(),
                )

            expected_calls = (
                (self.config.chapters - 1) * PROTOCOL_V2_EXPECTED_SMOKE_CALLS
            )
            if len(self.model.records) != expected_calls:
                raise RuntimeError(
                    "fully admitted Protocol-v2 run has the wrong call count: "
                    f"expected {expected_calls}, observed {len(self.model.records)}"
                )
            is_smoke = self.config.chapters == 2
            outcome = ProtocolV2Outcome(
                status=(
                    "symmetric_smoke_passed"
                    if is_smoke
                    else "longitudinal_completed"
                ),
                exit_code=0,
                chapter=self.config.chapters,
                condition=None,
                reason=(
                    "both branches produced admissible Chapter-2 prose and state"
                    if is_smoke
                    else "both longitudinal branches completed all admitted chapters"
                ),
            )
            final_index_heading = (
                "Chapter-2 degradation index"
                if is_smoke
                else f"Chapter-{self.config.chapters} degradation index"
            )
            result_lines = [
                "# ADI-001 Protocol v2 Result",
                "",
                f"Status: `{outcome.status}`",
                f"Source revision: `{self.source_revision}`",
                f"Model: `{self.model_name}`",
                f"Model digest: `{self.model_digest}`",
                "",
                "Both branches passed the shared deterministic Story Map authority.",
                (
                    "This qualifies the apparatus only. It does not declare a "
                    "Chapter-2 winner."
                    if is_smoke
                    else "This report records the pre-registered trajectories and "
                    "does not use prose preference or an automatic winner declaration."
                ),
                "The hypothesis concerns relative degradation slope as dependency load grows.",
                "",
                f"| Condition | {final_index_heading} | Degradation slope | Open obligations |",
                "| :--- | ---: | ---: | ---: |",
            ]
            for condition in self.config.condition_order:
                trajectory = trajectory_objects[condition]
                metric = trajectory.chapters[-1]
                slope = trajectory.degradation_slope
                slope_text = "n/a (one chapter)" if slope is None else f"{slope:.6f}"
                result_lines.append(
                    f"| {condition} | {metric.degradation_index:.6f} | "
                    f"{slope_text} | {metric.unresolved_obligations} |"
                )
            _atomic_write_text(
                self.output_dir / "RESULT.md", "\n".join(result_lines) + "\n"
            )
            self._write_final_status(
                {
                    **asdict(outcome),
                    "winner": None,
                    "phase": "smoke" if is_smoke else "longitudinal",
                    "symmetric_smoke_passed": is_smoke,
                    "longitudinal_run_completed": not is_smoke,
                    "longitudinal_run_authorized": not is_smoke,
                    "smoke_qualification_consumed": not is_smoke,
                    "longitudinal_blocker": (
                        "Chapters 3-10 still require reviewed Story Map frontier/guard coverage"
                        if is_smoke
                        else None
                    ),
                    "interpretation": (
                        "apparatus qualification only; Kingdom has not earned confidence"
                        if is_smoke
                        else "longitudinal evidence recorded; no prose-preference winner"
                    ),
                    "condition_terminal_status": {
                        condition: {
                            "terminal_status": "admitted",
                            "admitted_through_chapter": admitted_through[condition],
                            "first_rejection_chapter": None,
                        }
                        for condition in self.config.condition_order
                    },
                    "completed_paired_admitted_chapters": list(
                        completed_paired_chapters
                    ),
                    "longitudinal_censoring": (
                        "future slopes use only completed paired admitted chapters; "
                        "first rejection is a primary terminal endpoint"
                    ),
                    "trajectories": {
                        condition: trajectory.to_mapping()
                        for condition, trajectory in trajectory_objects.items()
                    },
                }
            )
            return outcome
        except Exception as error:
            if not self._final_status_written:
                self._write_final_status(
                    {
                        "status": "apparatus_failure",
                        "exit_code": 1,
                        "chapter": None,
                        "condition": None,
                        "reason": str(error),
                        "error_type": (
                            f"{type(error).__module__}.{type(error).__qualname__}"
                        ),
                        "winner": None,
                        "phase": (
                            "smoke" if self.config.chapters == 2 else "longitudinal"
                        ),
                        "symmetric_smoke_passed": False,
                        "longitudinal_run_completed": False,
                        "longitudinal_run_authorized": (
                            self.config.chapters > 2
                        ),
                        "smoke_qualification_consumed": (
                            self.config.chapters > 2
                        ),
                        "interpretation": (
                            "runtime/parser/persistence failure; no experimental winner"
                        ),
                    }
                )
            raise


def _git_revision_and_clean(
    workdir: Path,
    critical_paths: Mapping[str, Path],
) -> tuple[str, dict[str, str]]:
    """Bind every protocol-critical byte to a clean, tracked Git HEAD."""

    root = workdir.resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("Protocol v2 could not resolve an exact Git revision")
    tracked_checks = (
        ("git", "diff", "--quiet", "--", ".", ":(exclude,glob)**/*.pyc"),
        (
            "git",
            "diff",
            "--cached",
            "--quiet",
            "--",
            ".",
            ":(exclude,glob)**/*.pyc",
        ),
    )
    for args in tracked_checks:
        completed = subprocess.run(args, cwd=root)
        if completed.returncode != 0:
            raise RuntimeError(
                "Protocol v2 refuses to run with tracked or staged source changes"
            )

    observed: dict[str, str] = {}
    for label, supplied_path in critical_paths.items():
        path = supplied_path.resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise RuntimeError(
                f"Protocol v2 critical input is outside the repository: {path}"
            ) from error
        if relative != label:
            raise RuntimeError(
                f"Protocol v2 critical input path mismatch: expected {label}, "
                f"got {relative}"
            )
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(
                f"Protocol v2 critical input is not tracked by Git: {relative}"
            )
        head_object = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        filtered_working_object = subprocess.run(
            ["git", "hash-object", "--path", relative, "--", relative],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if filtered_working_object != head_object:
            raise RuntimeError(
                f"Protocol v2 critical input is not filter-equivalent to HEAD: "
                f"{relative}"
            )
        head_bytes = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        observed[relative] = hashlib.sha256(head_bytes).hexdigest()
    if set(observed) != set(PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS):
        raise RuntimeError("Protocol v2 critical source binding set is incomplete")
    return revision, dict(sorted(observed.items()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run frozen ADI-001 causal-degradation Protocol v2"
    )
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--story-map-file", type=Path)
    parser.add_argument("--protocol-file", type=Path)
    parser.add_argument("--smoke-qualification-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chapters", type=int, default=2)
    parser.add_argument("--model", default=PROTOCOL_V2_MODEL)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from hive_llm import OLLAMA_URL, ask_hive

    seed = args.seed_file.read_text(encoding="utf-8")
    contract = args.benchmark_file.read_text(encoding="utf-8")
    story_map_path = args.story_map_file or args.seed_file.with_name("STORY_MAP.json")
    protocol_path = args.protocol_file or args.seed_file.with_name("PROTOCOL_V2.md")
    repo_root = Path(__file__).resolve().parents[1]
    canonical_output_dir = _require_canonical_cli_output(
        repo_root,
        args.output_dir,
        chapters=args.chapters,
    )
    frozen_v1_dir = repo_root / FROZEN_V1_RELATIVE_DIR
    if args.model != PROTOCOL_V2_MODEL:
        raise ValueError(
            f"Protocol v2 model is frozen as {PROTOCOL_V2_MODEL!r}"
        )
    critical_paths = {
        relative: repo_root / relative
        for relative in PROTOCOL_V2_CRITICAL_SOURCE_FILES
    }
    critical_paths.update(
        {
            "benchmarks/adi_001_richest_man_breathing/SEED.md": args.seed_file,
            "benchmarks/adi_001_richest_man_breathing/CONTRACT.md": (
                args.benchmark_file
            ),
            "benchmarks/adi_001_richest_man_breathing/STORY_MAP.json": (
                story_map_path
            ),
            "benchmarks/adi_001_richest_man_breathing/PROTOCOL_V2.md": (
                protocol_path
            ),
        }
    )
    revision, source_file_sha256 = _git_revision_and_clean(
        repo_root, critical_paths
    )
    verify_frozen_v1_evidence(frozen_v1_dir)
    boundary = load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=story_map_path.read_text(encoding="utf-8"),
    )
    model_name = args.model
    model_digest = _ollama_model_digest(model_name, generate_url=OLLAMA_URL)
    if model_digest != PROTOCOL_V2_MODEL_DIGEST:
        raise RuntimeError(
            "installed qwen2.5-coder:7b digest does not match Protocol v2"
        )
    runner = ProtocolV2Runner(
        seed=seed,
        contract=contract,
        protocol_document=protocol_path.read_text(encoding="utf-8"),
        story_boundary=boundary,
        output_dir=canonical_output_dir,
        ask_fn=ask_hive,
        model_name=model_name,
        model_digest=model_digest,
        source_revision=revision,
        source_file_sha256=source_file_sha256,
        frozen_v1_evidence_dir=frozen_v1_dir,
        config=ProtocolV2Config(chapters=args.chapters),
        smoke_qualification_file=args.smoke_qualification_file,
    )
    return runner.run().exit_code


if __name__ == "__main__":
    raise SystemExit(main())
