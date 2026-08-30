"""Luna compression frontier v1.1 completion repair.

This module preserves v1 and its sealed executions.  It reuses the exact v1
worlds, prompts, schemas, ordering, grading, and one-attempt call plan.  The
only inference-policy changes are a symmetric 4,096-token output allowance
and an explicit score-and-continue rule for a provider response whose sole
failure is ``incomplete: max_output_tokens``.
"""

from __future__ import annotations

import argparse
import copy
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import ask_hive
from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-compression-frontier-v1.1"
PROTOCOL_VERSION = "1.1"
SCHEMA_VERSION = 2
V1_MAX_OUTPUT_TOKENS = 2_048
MAX_OUTPUT_TOKENS = 4_096
AUTHORIZED_COST_CEILING_USD = 0.30
RUN_DIR = Path(".hive/benchmarks/decompression_test/luna-frontier-v1-1-001")
BUDGET_FAILURE_REASON = "solver_output_budget_exhausted"
SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *v1.SOURCE_FILES,
            "kingdom/decompression_frontier_luna_v1_1.py",
            "benchmarks/decompression_test/PROTOCOL_LUNA_FRONTIER_V1_1.md",
            "tests/test_decompression_frontier_luna_v1_1.py",
        )
    )
)
_V1_SCORE_SUMMARY = v1._score_summary


class SolverBudgetExhausted(RuntimeError):
    """A measured solver failure, not a transport retry opportunity."""


def solver_config():
    """Return v1's frozen configuration with only the symmetric cap changed."""

    return replace(v1.solver_config(), max_output_tokens=MAX_OUTPUT_TOKENS)


def _budget_score(case: worlds.BenchmarkCase, condition: str) -> grading.LabelScore:
    return grading.LabelScore(
        case_id=case.case_id,
        condition=condition,
        admissible=False,
        selected_label=None,
        expected_label=case.correct_choice,
        answer_correct=False,
        grader_status="not_run",
        grader_agreement=None,
        truth_class=None,
        chronology_authority_status="not_assessable_solver_budget_exhausted",
        chronology_authority_error=None,
        illegal_state_promotions=None,
        secondary_status="not_run",
        failure_reasons=(BUDGET_FAILURE_REASON,),
    )


def _score_summary(
    scores: Sequence[grading.LabelScore],
    by_case: Mapping[str, worlds.BenchmarkCase],
) -> dict[str, Any]:
    result = _V1_SCORE_SUMMARY(scores, by_case)
    result["solver_budget_exhaustions"] = sum(
        BUDGET_FAILURE_REASON in score.failure_reasons for score in scores
    )
    return result


def _is_exact_budget_exhaustion(
    error: BaseException | None, metadata: Mapping[str, Any]
) -> bool:
    details = metadata.get("incomplete_details")
    return (
        error is not None
        and metadata.get("adapter_status") == "rejected"
        and metadata.get("response_status") == "incomplete"
        and isinstance(details, Mapping)
        and details.get("reason") == "max_output_tokens"
        and set(details) == {"reason"}
    )


def _validate_budget_metadata(
    metadata: Mapping[str, Any],
    *,
    config,
    expected_text_format: Mapping[str, Any],
    expected_returned_model: str | None,
) -> tuple[str, str]:
    required = {
        "provider": "openai",
        "api": "responses",
        "provider_fallback": False,
        "sdk_max_retries": 0,
        "physical_attempts": 1,
        "adapter_status": "rejected",
        "response_status": "incomplete",
        "requested_model": config.model,
        "configuration_hash": config.configuration_hash,
        "sdk_version": v1.EXPECTED_OPENAI_SDK,
        "returned_service_tier": config.service_tier,
    }
    for name, value in required.items():
        if metadata.get(name) != value:
            raise v1.ApparatusFailure(f"OpenAI budget metadata mismatch for {name}")
    details = metadata.get("incomplete_details")
    if not isinstance(details, Mapping) or dict(details) != {
        "reason": "max_output_tokens"
    }:
        raise v1.ApparatusFailure("budget exhaustion reason is not exact")
    if metadata.get("response_error") is not None:
        raise v1.ApparatusFailure("budget-exhausted response contains an error object")
    if not isinstance(metadata.get("partial_output_text"), str):
        raise v1.ApparatusFailure("budget-exhausted partial output was not preserved")
    expected_hash = v1._sha256_text(v1._canonical_json(expected_text_format))
    if metadata.get("openai_text_format_sha256") != expected_hash:
        raise v1.ApparatusFailure("structured-output format hash mismatch")
    returned_model = metadata.get("returned_model")
    response_id = metadata.get("response_id")
    if not isinstance(returned_model, str) or not returned_model:
        raise v1.ApparatusFailure("returned model identity is missing")
    if expected_returned_model is not None and returned_model != expected_returned_model:
        raise v1.ApparatusFailure("returned model identity drifted within the run")
    if not isinstance(response_id, str) or not response_id:
        raise v1.ApparatusFailure("response ID is missing")
    counters = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    if any(
        isinstance(metadata.get(name), bool)
        or not isinstance(metadata.get(name), int)
        or metadata[name] < 0
        for name in counters
    ):
        raise v1.ApparatusFailure("OpenAI token accounting is missing or invalid")
    if metadata["cached_input_tokens"] != 0 or metadata["cache_write_input_tokens"] != 0:
        raise v1.ApparatusFailure("explicit no-breakpoint cache policy was violated")
    if metadata["output_tokens"] != config.max_output_tokens:
        raise v1.ApparatusFailure("budget response did not consume the frozen allowance")
    if metadata["reasoning_tokens"] > metadata["output_tokens"]:
        raise v1.ApparatusFailure("reasoning tokens exceed output tokens")
    if metadata["total_tokens"] != metadata["input_tokens"] + metadata["output_tokens"]:
        raise v1.ApparatusFailure("total token accounting is incoherent")
    return returned_model, response_id


class CompletionAuditStore(v1.OpenAIAuditStore):
    """Append-only v1 store with one explicit measured-budget outcome."""

    def __init__(self, root: Path, *, ask_fn: Callable[..., str], config) -> None:
        super().__init__(root, ask_fn=ask_fn, config=config)
        v1._write_exclusive(
            root / "PROTOCOL_REPAIR.json",
            v1._pretty_json(
                v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "material_changes": {
                            "max_output_tokens": {
                                "from": V1_MAX_OUTPUT_TOKENS,
                                "to": MAX_OUTPUT_TOKENS,
                                "applies_identically_to_every_condition": True,
                            },
                            "max_output_token_exhaustion": (
                                "score every unanswered case in that batch incorrect, "
                                "preserve the incomplete response, and continue"
                            ),
                        },
                        "partial_output_salvage": False,
                        "retry": False,
                        "all_other_transport_or_contract_failures": "INVALID_APPARATUS",
                    }
                )
            ),
        )

    def ask(self, planned: v1.PlannedCall) -> str:
        if planned.sequence != len(self.records) + 1:
            raise v1.ApparatusFailure("call sequence is not contiguous")
        call_id = f"call_{planned.sequence:06d}"
        started = v1._utc_now()
        self._append_event(
            {
                "event": "call_started",
                "at_utc": started,
                "call_id": call_id,
                "sequence": planned.sequence,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "prompt_sha256": v1._sha256_text(planned.prompt),
            }
        )
        metadata: dict[str, Any] = {}
        response: str | None = None
        error: BaseException | None = None
        admission_error: BaseException | None = None
        try:
            response = self.ask_fn(
                planned.prompt,
                role="default",
                solver_config=self.config,
                metadata=metadata,
                openai_text_format=planned.text_format,
            )
        except BaseException as exc:  # preserve every failed physical request
            error = exc
        budget_exhausted = _is_exact_budget_exhaustion(error, metadata)
        if error is None:
            try:
                returned_model, _ = v1._validate_metadata(
                    metadata,
                    config=self.config,
                    expected_text_format=planned.text_format,
                    expected_returned_model=self.returned_model,
                )
                if self.returned_model is None:
                    self.returned_model = returned_model
            except BaseException as exc:
                admission_error = exc
        elif budget_exhausted:
            try:
                returned_model, _ = _validate_budget_metadata(
                    metadata,
                    config=self.config,
                    expected_text_format=planned.text_format,
                    expected_returned_model=self.returned_model,
                )
                if self.returned_model is None:
                    self.returned_model = returned_model
            except BaseException as exc:
                admission_error = exc
        status = (
            "completed"
            if error is None and admission_error is None
            else "solver_budget_exhausted"
            if budget_exhausted and admission_error is None
            else "metadata_rejected"
            if admission_error is not None
            else "transport_error"
        )
        artifact = v1._sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "call_id": call_id,
                "sequence": planned.sequence,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "case_ids": list(planned.case_ids),
                "started_at_utc": started,
                "finished_at_utc": v1._utc_now(),
                "status": status,
                "request": {
                    "prompt": planned.prompt,
                    "prompt_sha256": v1._sha256_text(planned.prompt),
                    "openai_text_format": planned.text_format,
                    "openai_text_format_sha256": v1._sha256_text(
                        v1._canonical_json(planned.text_format)
                    ),
                    "solver_config": self.config.to_mapping(),
                    "solver_config_sha256": self.config.configuration_hash,
                },
                "response": {
                    "raw_text": response,
                    "sha256": v1._sha256_text(response) if response is not None else None,
                },
                "transport_metadata": v1._json_safe(metadata),
                "transport_error": v1._safe_error(error),
                "admission_error": v1._safe_error(admission_error),
            }
        )
        path = self.calls_dir / f"{call_id}.json"
        v1._write_exclusive(path, v1._pretty_json(artifact))
        file_hash = v1._sha256_bytes(path.read_bytes())
        record = v1.CallRecord(
            sequence=planned.sequence,
            call_id=call_id,
            stage=planned.stage,
            batch_id=planned.batch_id,
            condition=planned.condition,
            artifact_path=path.relative_to(self.root).as_posix(),
            artifact_file_sha256=file_hash,
            status=status,
            metadata=copy.deepcopy(metadata),
        )
        self.records.append(record)
        self._append_event(
            {
                "event": "call_finished",
                "at_utc": v1._utc_now(),
                "call_id": call_id,
                "sequence": planned.sequence,
                "status": status,
                "artifact_path": record.artifact_path,
                "artifact_file_sha256": file_hash,
            }
        )
        if admission_error is not None:
            raise v1.ApparatusFailure(
                f"{call_id} metadata rejected: {admission_error}"
            ) from None
        if budget_exhausted:
            raise SolverBudgetExhausted(call_id)
        if error is not None:
            raise v1.ApparatusFailure(f"{call_id} transport failed: {error}") from None
        assert response is not None
        return response


class CompletionRunner(v1.LunaFrontierRunner):
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn: Callable[..., str] = ask_hive,
        require_committed: bool = True,
    ) -> None:
        super().__init__(
            repo_root=repo_root,
            output_dir=output_dir,
            ask_fn=ask_fn,
            require_committed=require_committed,
        )
        self.config = solver_config()

    def _run_call(
        self,
        audit: CompletionAuditStore,
        planned: v1.PlannedCall,
        by_case: Mapping[str, worlds.BenchmarkCase],
    ) -> None:
        try:
            response = audit.ask(planned)
        except SolverBudgetExhausted:
            record = audit.records[-1]
            cases = [by_case[case_id] for case_id in planned.case_ids]
            scores = [_budget_score(case, planned.condition) for case in cases]
            self.scores[planned.condition].extend(scores)
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "call_id": record.call_id,
                    "status": "solver_budget_exhausted",
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "response_sha256": None,
                    "partial_output_salvaged": False,
                    "parser_status": "not_run",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "labels": None,
                    "scores": [asdict(score) for score in scores],
                },
            )
            return
        record = audit.records[-1]
        cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = v1.parse_structured_labels(response, len(cases))
        except grading.ConstrainedInterfaceFailure as exc:
            rejected = [grading.rejected_score(case, planned.condition) for case in cases]
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "call_id": record.call_id,
                    "status": "parser_rejected",
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "response_sha256": v1._sha256_text(response),
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(exc),
                    "scores": [asdict(score) for score in rejected],
                },
            )
            self.scores[planned.condition].extend(rejected)
            raise v1.ApparatusFailure(
                f"{record.call_id} strict parser rejected output"
            ) from None
        scores = [
            grading.grade_label(case, label, condition=planned.condition)
            for case, label in zip(cases, labels)
        ]
        self.scores[planned.condition].extend(scores)
        secondary_failed = any(score.secondary_status != "ran" for score in scores)
        audit.write_decision(
            record,
            {
                "schema_version": SCHEMA_VERSION,
                "call_id": record.call_id,
                "status": "secondary_failed" if secondary_failed else "graded",
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "response_sha256": v1._sha256_text(response),
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in scores],
            },
        )
        if secondary_failed:
            raise v1.ApparatusFailure(
                f"{record.call_id} deterministic secondary evaluation failed"
            )

    def run(self) -> Mapping[str, Any]:
        with _v1_1_bindings():
            return super().run()


@contextmanager
def _v1_1_bindings():
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "MAX_OUTPUT_TOKENS": MAX_OUTPUT_TOKENS,
        "AUTHORIZED_COST_CEILING_USD": AUTHORIZED_COST_CEILING_USD,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "OpenAIAuditStore": CompletionAuditStore,
        "_score_summary": _score_summary,
    }
    originals = {name: getattr(v1, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v1, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(v1, name, value)


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _v1_1_bindings():
        return v1.deterministic_preflight(
            repo_root, require_committed=require_committed
        )


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    verified = dict(v1.verify_run(run_dir))
    index = json.loads((run_dir / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    if index.get("protocol_id") != PROTOCOL_ID:
        raise v1.ApparatusFailure("evidence index is not Protocol v1.1")
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    if result.get("protocol_id") != PROTOCOL_ID:
        raise v1.ApparatusFailure("result is not Protocol v1.1")
    verified["protocol_id"] = PROTOCOL_ID
    return verified


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-frozen-luna-frontier-v1-1",
        action="store_true",
        help="required acknowledgement that this is the one frozen v1.1 run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge_frozen_luna_frontier_v1_1:
        parser.error("--acknowledge-frozen-luna-frontier-v1-1 is required")
    v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = CompletionRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
