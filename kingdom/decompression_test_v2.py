"""Minimal Protocol v2 for the sealed Hive Decompression Test smoke.

The v1 worlds, questions, representations, retrieval, codec, batches, runtime,
and scoring thresholds remain frozen.  V2 changes only the shared model-output
contract: each case contributes one constrained enum label.
"""

from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import OLLAMA_URL, ask_hive
from kingdom import decompression_test as v1
from kingdom.protocol_v2_audit import ProtocolV2AuditStore
from kingdom.webnovel_benchmark import _ollama_model_digest


PROTOCOL_ID = "hive-decompression-smoke-v2"
SCHEMA_VERSION = 2
FROZEN_V1_COMMIT = "f0023177cd8036750c21aaaa957cc073ab3699f3"
FROZEN_CASE_PACK_SHA256 = (
    "73e4684c1889a1e0d0a5f084d1e8b29f0241ce332baa4f6c6c5c92b5688ce2ed"
)
FROZEN_EXPANDED_PACK_SHA256 = (
    "da81bae7eb4df4f19f045400a1a03e72cb3595f1531288e6f139d01080ca8dc9"
)
FROZEN_V1_INVENTORY_SHA256 = (
    "c4b0fc0d84ffbb0bb2d39e833e35140c73ad73eb719ac7a249174ad2bf3c54e1"
)
FROZEN_V1_FILE_COUNT = 47
FROZEN_V1_TOTAL_BYTES = 2_351_156

MODEL = v1.MODEL
MODEL_DIGEST = v1.MODEL_DIGEST
NUM_CTX = v1.NUM_CTX
NUM_PREDICT = v1.NUM_PREDICT
TEMPERATURE = v1.TEMPERATURE
SEED = v1.SEED
TIMEOUT_SECONDS = v1.TIMEOUT_SECONDS
CONDITIONS = v1.CONDITIONS
TOTAL_CALLS = v1.TOTAL_CALLS
LABELS = ("A", "B", "C", "D", "INSUFFICIENT")
JSON_WS = "[ \\t\\r\\n]*"
OUTPUT_SCHEMA = {
    "type": "array",
    "items": {"type": "string", "enum": list(LABELS)},
    "minItems": 3,
    "maxItems": 5,
}
NEW_SOURCE_FILES = (
    "kingdom/decompression_test_v2.py",
    "benchmarks/decompression_test/PROTOCOL_V2.md",
    "tests/test_decompression_test_v2.py",
)


class ConstrainedInterfaceFailure(RuntimeError):
    pass


class GraderDisagreement(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelScore:
    case_id: str
    condition: str
    admissible: bool
    selected_label: str | None
    expected_label: str | None
    answer_correct: bool | None
    grader_status: str
    grader_agreement: bool | None
    truth_class: str | None
    chronology_authority_status: str
    chronology_authority_error: bool | None
    illegal_state_promotions: int | None
    secondary_status: str
    failure_reasons: tuple[str, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sealed(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result["payload_sha256"] = _sha256_text(_canonical_json(result))
    return result


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def parse_primary_value(raw: str) -> str:
    """Accept exactly one allowed scalar value plus frozen surrounding whitespace."""

    if not isinstance(raw, str):
        raise ConstrainedInterfaceFailure("answer must be text")
    match = re.fullmatch(JSON_WS + "(A|B|C|D|INSUFFICIENT)" + JSON_WS, raw)
    if match is None:
        raise ConstrainedInterfaceFailure("answer is not one exact allowed value")
    return match.group(1)


def parse_batch(raw: str, expected_count: int) -> tuple[str, ...]:
    """Strictly parse the positional wrapper required by v1's frozen batching."""

    if expected_count not in {3, 4, 5} or not isinstance(raw, str):
        raise ConstrainedInterfaceFailure("invalid frozen batch response")
    token = '"(?:A|B|C|D|INSUFFICIENT)"'
    body = token + (JSON_WS + "," + JSON_WS + token) * (expected_count - 1)
    grammar = JSON_WS + "\\[" + JSON_WS + body + JSON_WS + "\\]" + JSON_WS
    if re.fullmatch(grammar, raw) is None:
        raise ConstrainedInterfaceFailure("response violated the exact enum-array grammar")
    labels = tuple(re.findall('"(A|B|C|D|INSUFFICIENT)"', raw))
    if len(labels) != expected_count:
        raise ConstrainedInterfaceFailure("response length differs from frozen batch")
    return labels


_SEMANTIC_PREFIX = v1.SOLVER_PROMPT_PREFIX.split(
    "Return exactly one JSON object", 1
)[0].replace(
    "Allowed reasoning codes and meanings:",
    "Task reasoning rules (the rule names are not output fields):",
)
SOLVER_PROMPT_PREFIX = _SEMANTIC_PREFIX + """Return one answer value per supplied case, in the same order. Each value must
be exactly A, B, C, D, or INSUFFICIENT. The constrained response is a JSON
array containing only those values. Return no case IDs, answer text, reasoning,
event references, claim IDs, bookkeeping fields, markdown fences, or prose.
"""


def _input_part(prompt: str) -> str:
    marker = "\nINPUT:\n"
    if prompt.count(marker) != 1:
        raise RuntimeError("unexpected frozen prompt boundary")
    return prompt.split(marker, 1)[1]


def build_solver_prompt(cases: Sequence[v1.BenchmarkCase], condition: str) -> str:
    old = v1.build_solver_prompt(cases, condition)
    return SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + _input_part(old)


def build_ablation_prompt(
    entries: Sequence[tuple[v1.BenchmarkCase, str]],
) -> tuple[str, tuple[tuple[str, v1.BenchmarkCase, str], ...]]:
    old, blinded = v1.build_ablation_prompt(entries)
    return SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + _input_part(old), blinded


def verify_v1_artifacts(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise RuntimeError("sealed smoke-v1 evidence is missing")
    rows = [
        {
            "path": path.relative_to(run_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(item for item in run_dir.rglob("*") if item.is_file())
    ]
    total = sum(row["bytes"] for row in rows)
    digest = _sha256_text(_canonical_json(rows))
    if (
        len(rows) != FROZEN_V1_FILE_COUNT
        or total != FROZEN_V1_TOTAL_BYTES
        or digest != FROZEN_V1_INVENTORY_SHA256
    ):
        raise RuntimeError("sealed smoke-v1 artifacts or hashes changed")
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("source_revision") != FROZEN_V1_COMMIT
        or result.get("validity") != "VALID"
        or result.get("hypothesis_result") != "NOT_SUPPORTED"
    ):
        raise RuntimeError("sealed smoke-v1 identity or result changed")
    return {
        "source_commit": FROZEN_V1_COMMIT,
        "result": "VALID / NOT_SUPPORTED",
        "file_count": len(rows),
        "total_bytes": total,
        "inventory_sha256": digest,
    }


def _git_revision_and_sources(repo_root: Path) -> tuple[str, dict[str, str]]:
    revision, sources = v1._git_revision_and_sources(repo_root)
    for relative in NEW_SOURCE_FILES:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repo_root,
            capture_output=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(f"Protocol-v2 file is not tracked: {relative}")
        head_object = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        working_object = subprocess.run(
            ["git", "hash-object", "--path", relative, "--", relative],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head_object != working_object:
            raise RuntimeError(f"Protocol-v2 file differs from HEAD: {relative}")
        sources[relative] = _sha256_bytes(
            subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
        )
    return revision, dict(sorted(sources.items()))


def _replay_label(case: v1.BenchmarkCase) -> str:
    answer = v1._answer_from_replay(case)
    labels = [label for label, value in case.options.items() if value == answer]
    if len(labels) != 1:
        raise GraderDisagreement("replay answer does not map to one option")
    return labels[0]


def _ablation_replay_label(case: v1.BenchmarkCase, role: str) -> str:
    if role == "control":
        events = v1._without_last_effect(case.events, case.control_ablation_event_id)
        if v1.replay_events(events, through_time=case.query_time).state != v1.replay_events(
            case.events, through_time=case.query_time
        ).state:
            raise GraderDisagreement("ablation control changed current state")
        return _replay_label(case)
    if role == "essential":
        events = v1._without_last_effect(case.events, case.ablation_event_id)
        if v1._answer_from_replay(replace(case, events=events)) == v1._answer_from_replay(case):
            raise GraderDisagreement("essential ablation does not change the answer")
        return "INSUFFICIENT"
    raise GraderDisagreement("unknown ablation role")


def _secondary(case: v1.BenchmarkCase, label: str) -> tuple[str | None, str, bool | None, int]:
    if label == "INSUFFICIENT":
        return None, "not_assessable_insufficient", None, 0
    statement = case.options[label]
    claims = [claim for claim in case.claims if claim.statement == statement]
    if len(claims) != 1:
        raise RuntimeError("selected option does not map to one frozen claim")
    truth = claims[0].truth_class
    statuses = {
        "current": "current",
        "historical": "historical_state_selected",
        "planned": "planned_state_selected",
        "hallucinated": "unsupported_state_selected",
    }
    if truth not in statuses:
        raise RuntimeError("unknown frozen truth class")
    return truth, statuses[truth], truth != "current", int(truth != "current")


def grade_label(
    case: v1.BenchmarkCase,
    label: str,
    *,
    condition: str,
    ablation_role: str | None = None,
    secondary_fn: Callable[[v1.BenchmarkCase, str], tuple[str | None, str, bool | None, int]] = _secondary,
) -> LabelScore:
    fixture = "INSUFFICIENT" if ablation_role == "essential" else case.correct_choice
    replay = (
        _ablation_replay_label(case, ablation_role)
        if ablation_role is not None
        else _replay_label(case)
    )
    if fixture != replay:
        raise GraderDisagreement(f"fixture={fixture}, replay={replay}")
    correct = label == fixture
    reasons = [] if correct else ["answer_incorrect"]
    truth = None
    status = "secondary_failed"
    chronology_error = None
    promotions = None
    secondary_status = "ran"
    try:
        truth, status, chronology_error, promotions = secondary_fn(case, label)
        if chronology_error:
            reasons.append("chronology_or_authority_error")
        if promotions:
            reasons.append("illegal_state_promotion")
    except Exception:
        secondary_status = "failed"
        reasons.append("secondary_metadata_failure")
    return LabelScore(
        case_id=case.case_id,
        condition=condition,
        admissible=True,
        selected_label=label,
        expected_label=fixture,
        answer_correct=correct,
        grader_status="ran",
        grader_agreement=True,
        truth_class=truth,
        chronology_authority_status=status,
        chronology_authority_error=chronology_error,
        illegal_state_promotions=promotions,
        secondary_status=secondary_status,
        failure_reasons=tuple(reasons),
    )


def rejected_score(case: v1.BenchmarkCase, condition: str) -> LabelScore:
    return LabelScore(
        case_id=case.case_id,
        condition=condition,
        admissible=False,
        selected_label=None,
        expected_label=None,
        answer_correct=None,
        grader_status="not_run",
        grader_agreement=None,
        truth_class=None,
        chronology_authority_status="not_assessable_parser_failure",
        chronology_authority_error=None,
        illegal_state_promotions=None,
        secondary_status="not_run",
        failure_reasons=("constrained_interface_failure",),
    )


class DecompressionV2Runner(v1.DecompressionSmokeRunner):
    def __init__(self, *, v1_seal: Mapping[str, Any], ask_fn=None, **kwargs: Any) -> None:
        constrained_ask = ask_fn or functools.partial(
            ask_hive, response_format=copy.deepcopy(OUTPUT_SCHEMA)
        )
        super().__init__(ask_fn=constrained_ask, **kwargs)
        self.v1_seal = copy.deepcopy(dict(v1_seal))
        self.scores: list[LabelScore] = []
        self.ablation_scores: list[LabelScore] = []

    def _preflight(self) -> dict[str, Any]:
        base = super()._preflight()
        case_path = self.repo_root / "benchmarks" / "decompression_test" / "CASE_PACK.json"
        if _sha256_bytes(case_path.read_bytes()) != FROZEN_CASE_PACK_SHA256:
            raise RuntimeError("frozen case pack changed")
        if base["expanded_case_pack_sha256"] != FROZEN_EXPANDED_PACK_SHA256:
            raise RuntimeError("frozen expanded worlds changed")
        prompts: dict[str, dict[str, Any]] = {}
        for batch in self.case_pack_payload["batches"]:
            batch_id = str(batch["batch_id"])
            cases = [self.by_case[case_id] for case_id in batch["case_ids"]]
            prompts[batch_id] = {}
            for condition in CONDITIONS:
                old = v1.build_solver_prompt(cases, condition)
                new = build_solver_prompt(cases, condition)
                if _input_part(old) != _input_part(new):
                    raise RuntimeError("v2 changed a frozen semantic input")
                prompts[batch_id][condition] = {
                    "sha256": _sha256_text(new),
                    "chars": len(new),
                    "utf8_bytes": len(new.encode()),
                }
        ablation = []
        for number, plan in enumerate(
            self.case_pack_payload["ablation"]["counterbalanced_calls"], start=1
        ):
            entries = [
                (self.by_case[item["case_id"]], item["role"]) for item in plan
            ]
            old, _ = v1.build_ablation_prompt(entries)
            new, blinded = build_ablation_prompt(entries)
            if _input_part(old) != _input_part(new):
                raise RuntimeError("v2 changed a frozen ablation input")
            ablation.append(
                {
                    "call_number": number,
                    "sha256": _sha256_text(new),
                    "chars": len(new),
                    "utf8_bytes": len(new.encode()),
                    "blinded_aliases": [alias for alias, _, _ in blinded],
                }
            )
        return {
            **base,
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "solver_prompt_template_sha256": _sha256_text(SOLVER_PROMPT_PREFIX),
            "batch_prompts": prompts,
            "ablation_prompts": ablation,
            "output_schema": copy.deepcopy(OUTPUT_SCHEMA),
            "output_schema_sha256": _sha256_text(_canonical_json(OUTPUT_SCHEMA)),
            "sealed_v1": self.v1_seal,
        }

    def _manifest(self, preflight: Mapping[str, Any]) -> dict[str, Any]:
        assert self.audit is not None
        return _sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": self.source_revision,
                "source_file_sha256": dict(sorted(self.source_file_sha256.items())),
                "sealed_v1": self.v1_seal,
                "model": MODEL,
                "model_digest": self.model_digest,
                "runtime": {
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                    "temperature": TEMPERATURE,
                    "seed": SEED,
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "physical_attempts_per_call": 1,
                    "max_retries": 1,
                },
                "calls": {"raw": 6, "retrieval": 6, "compressed": 6, "ablation": 2, "total": 20},
                "output_schema": copy.deepcopy(OUTPUT_SCHEMA),
                "batch_plan": copy.deepcopy(self.case_pack_payload["batches"]),
                "ablation_plan": copy.deepcopy(self.case_pack_payload["ablation"]),
                "preflight_sha256": _sha256_text(_canonical_json(preflight)),
                "audit_config": self.audit.frozen_config,
                "model_judge_calls": 0,
                "only_material_change": "primary solver output interface",
            }
        )

    def _write_decision(self, sequence: int, payload: Mapping[str, Any]) -> None:
        _write_exclusive(
            self.decisions_dir / f"decision_{sequence:06d}.json",
            _pretty_json(_sealed(payload)),
        )

    def _ask_and_grade(
        self,
        *,
        prompt: str,
        condition: str,
        batch_id: int,
        cases: Sequence[v1.BenchmarkCase],
        roles: Sequence[str | None],
        purpose: str,
    ) -> None:
        assert self.audit is not None
        response = self.audit.ask(
            prompt,
            condition=condition,
            chapter=batch_id,
            purpose=purpose,
            role="default",
            budget_class="generation",
        )
        sequence = len(self.audit.records)
        decision: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "call_id": self.audit.last_call_id,
            "batch_id": batch_id,
            "condition": condition,
            "response_sha256": _sha256_text(response),
        }
        try:
            labels = parse_batch(response, len(cases))
        except ConstrainedInterfaceFailure as error:
            rejected = [rejected_score(case, condition) for case in cases]
            target = self.ablation_scores if condition == "compressed_ablation" else self.scores
            target.extend(rejected)
            decision.update(
                {
                    "status": "constrained_interface_failure",
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(error),
                    "scores": [asdict(score) for score in rejected],
                }
            )
            self._write_decision(sequence, decision)
            return
        scores = [
            grade_label(
                case,
                label,
                condition=condition,
                ablation_role=role,
            )
            for case, label, role in zip(cases, labels, roles)
        ]
        target = self.ablation_scores if condition == "compressed_ablation" else self.scores
        target.extend(scores)
        decision.update(
            {
                "status": "graded",
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in scores],
            }
        )
        self._write_decision(sequence, decision)

    def _verify_evidence(self, preflight: Mapping[str, Any]) -> dict[str, Any]:
        assert self.audit is not None
        records = self.audit.records
        calls = sorted(self.audit.calls_dir.glob("call_*.json"))
        decisions = sorted(self.decisions_dir.glob("decision_*.json"))
        if len(records) != TOTAL_CALLS or len(calls) != TOTAL_CALLS or len(decisions) != TOTAL_CALLS:
            raise RuntimeError("v2 evidence count differs from 20")
        hashes = {}
        for record, path in zip(records, calls):
            if record.status != "completed" or _sha256_bytes(path.read_bytes()) != record.artifact_file_sha256:
                raise RuntimeError("v2 call evidence is incomplete or changed")
            artifact = json.loads(path.read_text(encoding="utf-8"))
            metadata = artifact["transport"]["metadata"]
            if (
                metadata.get("physical_attempts") != 1
                or metadata.get("done") is not True
                or metadata.get("done_reason") != "stop"
                or metadata.get("response_format") != OUTPUT_SCHEMA
            ):
                raise RuntimeError("v2 constrained runtime metadata mismatch")
            hashes[record.call_id] = record.artifact_file_sha256
        events = self.audit.events_path.read_text(encoding="utf-8").splitlines()
        if len(events) != 40:
            raise RuntimeError("v2 audit journal differs from 40 events")
        return {
            "call_count": 20,
            "decision_count": 20,
            "call_file_sha256": hashes,
            "events_jsonl_sha256": _sha256_bytes(self.audit.events_path.read_bytes()),
            "output_schema_sha256": preflight["output_schema_sha256"],
            "sealed_v1_inventory_sha256": self.v1_seal["inventory_sha256"],
        }

    def _outcome(self, usage: Mapping[str, Any], preflight: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
        summaries = {}
        for condition in CONDITIONS:
            scores = [score for score in self.scores if score.condition == condition]
            summaries[condition] = {
                "total": len(scores),
                "admissible": sum(score.admissible for score in scores),
                "exact_correct": sum(score.answer_correct is True for score in scores),
                "chronology_authority_errors": sum(score.chronology_authority_error is True for score in scores),
                "illegal_promotions": sum(score.illegal_state_promotions or 0 for score in scores),
                "secondary_failures": sum(score.secondary_status == "failed" for score in scores),
                "parser_failures": sum(not score.admissible for score in scores),
                "grader_failures": sum(score.grader_status != "ran" for score in scores),
                "input_tokens": usage["totals"][condition]["input_tokens"],
                "output_tokens": usage["totals"][condition]["output_tokens"],
                "latency_seconds": usage["totals"][condition]["latency_seconds"],
                "calls": usage["totals"][condition]["calls"],
                "state_bytes": sum(item["representation_utf8_bytes"][condition] for item in preflight["representation_stats"]),
            }
        support_ids = {case.case_id for case in self.cases if case.load == "support_high"}
        distractor_ids = {case.case_id for case in self.cases if case.load == "distractor_high"}
        family_ids = {
            family: {case.case_id for case in self.cases if case.family == family}
            for family in {case.family for case in self.cases}
        }

        def correct(condition: str, ids: set[str]) -> int:
            return sum(score.answer_correct is True for score in self.scores if score.condition == condition and score.case_id in ids)

        support = {name: correct(name, support_ids) for name in CONDITIONS}
        distractor = {name: correct(name, distractor_ids) for name in CONDITIONS}
        family = {
            name: {condition: correct(condition, ids) for condition in CONDITIONS}
            for name, ids in family_ids.items()
        }
        order = [item for call in self.case_pack_payload["ablation"]["counterbalanced_calls"] for item in call]
        essential = sum(score.answer_correct is True for score, item in zip(self.ablation_scores, order) if item["role"] == "essential")
        controls = sum(score.answer_correct is True for score, item in zip(self.ablation_scores, order) if item["role"] == "control")
        criteria = {
            "compressed_exact_at_least_16": summaries["compressed"]["exact_correct"] >= 16,
            "compressed_not_worse_raw": summaries["compressed"]["exact_correct"] >= summaries["raw"]["exact_correct"],
            "compressed_not_worse_retrieval": summaries["compressed"]["exact_correct"] >= summaries["retrieval"]["exact_correct"],
            "compressed_support_high_at_least_4": support["compressed"] >= 4,
            "compressed_not_worse_baselines_support_high": all(support["compressed"] >= support[name] for name in ("raw", "retrieval")),
            "compressed_not_worse_baselines_distractor_high": all(distractor["compressed"] >= distractor[name] for name in ("raw", "retrieval")),
            "compressed_at_least_3_each_family": all(values["compressed"] >= 3 for values in family.values()),
            "compressed_zero_illegal_promotions": summaries["compressed"]["illegal_promotions"] == 0,
            "compressed_tokens_at_most_60_percent_raw": usage["median_compressed_to_raw_prompt_token_ratio"] <= 0.60,
            "compressed_tokens_not_above_retrieval": usage["median_compressed_to_retrieval_prompt_token_ratio"] <= 1.0,
            "codec_no_compression_loss": preflight["compression_loss_count"] == 0,
            "essential_ablation_at_least_4": essential >= 4,
            "ablation_controls_at_least_4": controls >= 4,
        }
        interface_failures = sum(
            not score.admissible for score in [*self.scores, *self.ablation_scores]
        )
        supported = interface_failures == 0 and all(criteria.values())
        validity = "INVALID" if interface_failures else "VALID"
        return {
            "validity": validity,
            "hypothesis_result": (
                "INCONCLUSIVE_INVALID_SMOKE"
                if interface_failures
                else ("SUPPORTED" if supported else "NOT_SUPPORTED")
            ),
            "evidence_level": "SUPPORTED" if supported else "SPECULATIVE",
            "proven": False,
            "condition_summaries": summaries,
            "case_scores": [asdict(score) for score in self.scores],
            "chronology_authority_note": "Derived from the selected option's frozen truth class; not a model reasoning trace.",
            "ablation": {
                "total": len(self.ablation_scores),
                "admissible": sum(score.admissible for score in self.ablation_scores),
                "exact_correct": sum(score.answer_correct is True for score in self.ablation_scores),
                "essential_detected": essential,
                "control_passes": controls,
                "chronology_authority_errors": sum(
                    score.chronology_authority_error is True
                    for score in self.ablation_scores
                ),
                "illegal_promotions": sum(
                    score.illegal_state_promotions or 0
                    for score in self.ablation_scores
                ),
                "secondary_failures": sum(
                    score.secondary_status == "failed"
                    for score in self.ablation_scores
                ),
                "parser_failures": sum(
                    not score.admissible for score in self.ablation_scores
                ),
                "grader_failures": sum(
                    score.grader_status != "ran" for score in self.ablation_scores
                ),
                "input_tokens": usage["totals"]["compressed_ablation"]["input_tokens"],
                "output_tokens": usage["totals"]["compressed_ablation"]["output_tokens"],
                "latency_seconds": usage["totals"]["compressed_ablation"]["latency_seconds"],
                "calls": usage["totals"]["compressed_ablation"]["calls"],
                "state_bytes": sum(
                    len(
                        _canonical_json(
                            v1._ablation_packet(
                                self.by_case[item["case_id"]],
                                control=item["role"] == "control",
                            )
                        ).encode()
                    )
                    for call in self.case_pack_payload["ablation"]["counterbalanced_calls"]
                    for item in call
                ),
                "scores": [asdict(score) for score in self.ablation_scores],
            },
            "criteria": criteria,
            "usage": copy.deepcopy(dict(usage)),
            "evidence": copy.deepcopy(dict(evidence)),
            "interpretation_boundary": "One frozen synthetic codec and one model digest; Hive is not broadly proven.",
        }

    @staticmethod
    def _markdown(result: Mapping[str, Any]) -> str:
        lines = [
            "# Hive Decompression Test — Protocol v2",
            "",
            f"- Validity: **{result['validity']}**",
            f"- Hypothesis: **{result['hypothesis_result']}**",
            f"- Evidence: **{result['evidence_level']}**",
            "",
            "| Condition | Admissible | Exact | Chronology/authority errors | Illegal promotions | Input | Output | State bytes | Latency | Calls | Parser failures | Grader failures |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for condition in CONDITIONS:
            row = (result.get("condition_summaries") or {}).get(condition)
            if row is None:
                lines.append(f"| {condition} | not completed | — | — | — | — | — | — | — | — | — | — |")
            else:
                lines.append(
                    f"| {condition} | {row['admissible']}/{row['total']} | {row['exact_correct']}/{row['total']} | "
                    f"{row['chronology_authority_errors']} | {row['illegal_promotions']} | {row['input_tokens']} | "
                    f"{row['output_tokens']} | {row['state_bytes']} | {row['latency_seconds']} | {row['calls']} | "
                    f"{row['parser_failures']} | {row['grader_failures']} |"
                )
        ablation = result.get("ablation") or {}
        lines.extend(
            [
                "",
                "## Ablation",
                "",
                f"- Admissible: {ablation.get('admissible', 'not completed')}/{ablation.get('total', '—')}",
                f"- Exact: {ablation.get('exact_correct', 'not completed')}/{ablation.get('total', '—')}",
                f"- Essential detected: {ablation.get('essential_detected', 'not completed')}/5",
                f"- Controls passed: {ablation.get('control_passes', 'not completed')}/5",
                "",
            ]
        )
        return "\n".join(lines)

    def _write_terminal(self, result: Mapping[str, Any], error: BaseException | None = None) -> None:
        payload = _sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": self.source_revision,
                **copy.deepcopy(dict(result)),
                "audit_index": None if self.audit is None else self.audit.manifest_index(),
            }
        )
        _write_exclusive(self.output_dir / "RESULT.json", _pretty_json(payload))
        _write_exclusive(self.output_dir / "RESULT.md", self._markdown(payload))
        _write_exclusive(
            self.output_dir / "RUN_STATUS.json",
            _pretty_json(
                _sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "source_revision": self.source_revision,
                        "validity": payload["validity"],
                        "hypothesis_result": payload["hypothesis_result"],
                        "evidence_level": payload["evidence_level"],
                        "call_count": 0 if self.audit is None else len(self.audit.records),
                        "result_file_sha256": _sha256_bytes((self.output_dir / "RESULT.json").read_bytes()),
                        "error": None if error is None else {"type": type(error).__name__, "message": str(error)},
                    }
                )
            ),
        )

    def run(self) -> Mapping[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=False)
        try:
            self.decisions_dir.mkdir(exist_ok=False)
            preflight = self._preflight()
            _write_exclusive(self.output_dir / "PRECHECK.json", _pretty_json(_sealed(preflight)))
            self.audit = ProtocolV2AuditStore(
                self.ask_fn,
                self.output_dir / "evidence",
                model=MODEL,
                model_digest=self.model_digest,
                generation_calls_per_chapter=1,
                request_timeout_seconds=TIMEOUT_SECONDS,
                ollama_num_ctx=NUM_CTX,
                ollama_num_predict=NUM_PREDICT,
                ollama_temperature=TEMPERATURE,
                ollama_seed=SEED,
                transport_name="ollama-constrained-enum-v2",
            )
            _write_exclusive(self.output_dir / "manifest.json", _pretty_json(self._manifest(preflight)))
            for batch in self.case_pack_payload["batches"]:
                batch_id = int(batch["batch_id"])
                cases = [self.by_case[case_id] for case_id in batch["case_ids"]]
                for condition in batch["condition_order"]:
                    self._ask_and_grade(
                        prompt=build_solver_prompt(cases, condition),
                        condition=condition,
                        batch_id=batch_id,
                        cases=cases,
                        roles=[None] * len(cases),
                        purpose="decompression v2 label batch",
                    )
            for number, plan in enumerate(self.case_pack_payload["ablation"]["counterbalanced_calls"], start=1):
                entries = [(self.by_case[item["case_id"]], item["role"]) for item in plan]
                prompt, blinded = build_ablation_prompt(entries)
                self._ask_and_grade(
                    prompt=prompt,
                    condition="compressed_ablation",
                    batch_id=6 + number,
                    cases=[case for _, case, _ in blinded],
                    roles=[role for _, _, role in blinded],
                    purpose=f"decompression v2 ablation {number}",
                )
            evidence = self._verify_evidence(preflight)
            result = self._outcome(self._call_usage(), preflight, evidence)
            self._write_terminal(result)
            return result
        except BaseException as error:
            if not (self.output_dir / "RESULT.json").exists():
                result = {
                    "validity": "INVALID",
                    "hypothesis_result": "INCONCLUSIVE_INVALID_SMOKE",
                    "evidence_level": "SPECULATIVE",
                    "proven": False,
                    "condition_summaries": {},
                    "case_scores": [asdict(score) for score in self.scores],
                    "ablation": {"scores": [asdict(score) for score in self.ablation_scores]},
                    "criteria": {},
                    "interpretation_boundary": "Apparatus failure; no condition winner or hypothesis conclusion.",
                }
                self._write_terminal(result, error)
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the one-shot Decompression Test Protocol-v2 smoke")
    parser.add_argument("--acknowledge-frozen-smoke-v2", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.acknowledge_frozen_smoke_v2:
        raise SystemExit("refusing live run without --acknowledge-frozen-smoke-v2")
    repo_root = Path(__file__).resolve().parents[1]
    revision, sources = _git_revision_and_sources(repo_root)
    v1_seal = verify_v1_artifacts(
        repo_root / ".hive" / "benchmarks" / "decompression_test" / "smoke-v1-001"
    )
    payload, cases = v1.load_case_pack(
        repo_root / "benchmarks" / "decompression_test" / "CASE_PACK.json"
    )
    digest = _ollama_model_digest(MODEL, generate_url=OLLAMA_URL)
    if digest != MODEL_DIGEST:
        raise RuntimeError("installed Ollama model digest differs from frozen digest")
    DecompressionV2Runner(
        repo_root=repo_root,
        output_dir=repo_root / ".hive" / "benchmarks" / "decompression_test" / "smoke-v2-001",
        case_pack_payload=payload,
        cases=cases,
        source_revision=revision,
        source_file_sha256=sources,
        model_digest=digest,
        v1_seal=v1_seal,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
