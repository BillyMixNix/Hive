"""Protocol v1.2 for the frozen Luna semantic-authority decomposition study.

Relative to sealed v1.1, the response ceiling is 16,384 tokens and isolated
single-call failures are recorded and skipped without retry while the frozen
schedule continues.  Primary tests run only when all eight replication-level
C1/condition pairs are complete; missing data are never imputed or salvaged.
"""

from __future__ import annotations

import argparse
import json
import re
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as v1
from kingdom import decompression_semantic_authority_luna_v1_1 as v1_1
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-semantic-authority-decomposition-v1-2"
PROTOCOL_VERSION = "1.2"
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-semantic-authority-decomposition-v1-2-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-semantic-authority-decomposition-v1-2"
MAX_OUTPUT_TOKENS = 16_384
FROZEN_REQUEST_PLAN_SHA256 = (
    "93c985e268921314687da40830d82d4d016720c2b5c8d9567beff1639b6ae5f2"
)
FROZEN_SOLVER_CONFIG_SHA256 = (
    "0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54"
)
FROZEN_INPUT_TOKEN_UPPER_BOUND = 10_092_160
FROZEN_OUTPUT_TOKEN_UPPER_BOUND = 6_291_456
FROZEN_COST_UPPER_BOUND_USD = 9.5681792

SEALED_V1_1_EVIDENCE_COMMIT = "b5ec200dec75ff60aa930b0dc0df18e136efcb62"
SEALED_V1_1_IMPLEMENTATION_COMMIT = "961ee50c0362a3abab2569837ac6425fe55cba6b"
SEALED_V1_1_RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-semantic-authority-decomposition-v1-1-001"
)
SEALED_V1_1_EVIDENCE_TREE_OID = "49221942851f4cf173c292af018cbd0e72ff86b2"
SEALED_V1_1_RESULT_SHA256 = (
    "ec42f58aed89513bca3294a33a504d38b02dc9b6eb34d7c0bb39a3e1cf2f21aa"
)
SEALED_V1_1_INDEX_SHA256 = (
    "5c9cfb45ca7a58210633f7fc73d180b4aa757eff04f49df5909792b839f7e707"
)

SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *v1_1.SOURCE_FILES,
            "kingdom/decompression_semantic_authority_luna_v1_2.py",
            "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1_2.md",
            "tests/test_decompression_semantic_authority_luna_v1_2.py",
        )
    )
)

_BASE_CONSTANTS = {
    name: getattr(v1, name)
    for name in (
        "PROTOCOL_ID",
        "PROTOCOL_VERSION",
        "RUN_DIR",
        "SOURCE_FILES",
        "MAX_OUTPUT_TOKENS",
        "FROZEN_REQUEST_PLAN_SHA256",
    )
}
_BASE_VERIFY_PARENT = v1.verify_sealed_parent
_BASE_PREFLIGHT = v1.deterministic_preflight


class IsolatedParserFailure(luna_v1.ApparatusFailure):
    pass


def _git_revision_and_sources(repo_root: Path):
    return v1_1._git_revision_and_sources(repo_root, SOURCE_FILES)


def _assert_sources_unchanged(repo_root: Path, preflight: Mapping[str, Any]) -> None:
    v1_1._assert_sources_unchanged(repo_root, preflight, SOURCE_FILES)


def verify_sealed_v1_1(repo_root: Path) -> Mapping[str, Any]:
    evidence = v1_1._git(
        repo_root, "rev-parse", f"{SEALED_V1_1_EVIDENCE_COMMIT}^{{commit}}"
    ).stdout.strip()
    implementation = v1_1._git(
        repo_root, "rev-parse", f"{SEALED_V1_1_IMPLEMENTATION_COMMIT}^{{commit}}"
    ).stdout.strip()
    if evidence != SEALED_V1_1_EVIDENCE_COMMIT or implementation != SEALED_V1_1_IMPLEMENTATION_COMMIT:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1.1 lineage resolved unexpectedly")
    parents = v1_1._git(
        repo_root, "show", "-s", "--format=%P", evidence
    ).stdout.strip().split()
    if parents != [implementation]:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1.1 evidence parent changed")
    current = v1_1._git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if v1_1._git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        evidence,
        current,
        check=False,
    ).returncode != 0:
        raise luna_v1.ApparatusFailure("current source does not descend from sealed v1.1")
    tree = v1_1._git(
        repo_root, "rev-parse", f"{evidence}:{SEALED_V1_1_RUN_DIR.as_posix()}"
    ).stdout.strip()
    if tree != SEALED_V1_1_EVIDENCE_TREE_OID:
        raise luna_v1.ApparatusFailure("sealed Protocol-v1.1 evidence tree changed")
    run_dir = repo_root / SEALED_V1_1_RUN_DIR
    if (
        luna_v1._sha256_bytes((run_dir / "RESULT.json").read_bytes())
        != SEALED_V1_1_RESULT_SHA256
        or luna_v1._sha256_bytes((run_dir / "EVIDENCE_INDEX.json").read_bytes())
        != SEALED_V1_1_INDEX_SHA256
    ):
        raise luna_v1.ApparatusFailure("sealed Protocol-v1.1 result/index changed")
    active_request_hash = v1.FROZEN_REQUEST_PLAN_SHA256
    v1.FROZEN_REQUEST_PLAN_SHA256 = _BASE_CONSTANTS["FROZEN_REQUEST_PLAN_SHA256"]
    try:
        verified = v1_1.verify_run(run_dir)
    finally:
        v1.FROZEN_REQUEST_PLAN_SHA256 = active_request_hash
    if (
        verified["validity"] != "INVALID"
        or verified["result_code"] != "INVALID_APPARATUS"
        or verified["physical_generation_calls"] != 35
        or verified["unique_response_ids"] != 35
        or verified["returned_models"] != ["gpt-5.6-luna"]
        or verified["returned_service_tiers"] != ["default"]
        or verified["source_revision"] != implementation
    ):
        raise luna_v1.ApparatusFailure("sealed Protocol-v1.1 evidence no longer verifies")
    return {
        "sealed_v1_1_evidence_commit": evidence,
        "sealed_v1_1_implementation_commit": implementation,
        "sealed_v1_1_evidence_tree_oid": tree,
        "sealed_v1_1_result_sha256": SEALED_V1_1_RESULT_SHA256,
        "sealed_v1_1_evidence_index_sha256": SEALED_V1_1_INDEX_SHA256,
        "sealed_v1_1_verification": verified,
    }


def _verify_lineage(repo_root: Path) -> Mapping[str, Any]:
    lineage = dict(_BASE_VERIFY_PARENT(repo_root))
    lineage["sealed_protocol_v1_1_invalid_evidence"] = verify_sealed_v1_1(repo_root)
    return lineage


def _deterministic_preflight_impl(
    repo_root: Path, *, require_committed: bool = True
):
    payload, cases, calls, sealed = _BASE_PREFLIGHT(
        repo_root, require_committed=require_committed
    )
    preflight = dict(sealed)
    preflight.pop("payload_sha256", None)
    if require_committed:
        revision, sha256, blob_oids = v1_1._source_maps(repo_root, SOURCE_FILES)
        if revision != preflight["source_revision"] or sha256 != preflight["source_file_sha256"]:
            raise luna_v1.ApparatusFailure("Protocol-v1.2 source reporting is inconsistent")
    else:
        preflight["source_file_sha256"] = {
            relative: "TEST_UNCOMMITTED" for relative in SOURCE_FILES
        }
        blob_oids = {relative: "TEST_UNCOMMITTED" for relative in SOURCE_FILES}
    preflight["source_file_git_blob_oid"] = blob_oids
    preflight["source_guard"] = {
        "version": "direct-crlf-normalized-bytes-v1.1",
        "head_revision_required": True,
        "head_blob_must_match_preflight": True,
        "direct_worktree_crlf_to_lf_must_equal_committed_bytes": True,
        "canonical_git_show_sha256_must_match_preflight": True,
        "git_clean_filters_consulted_for_worktree_equality": False,
    }
    preflight["protocol_v1_2_frozen_changes"] = {
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "isolated_call_failures_continue": True,
        "primary_requires_all_eight_complete_matched_pairs": True,
        "no_imputation_or_salvage": True,
    }
    if (
        preflight["solver_config_sha256"] != FROZEN_SOLVER_CONFIG_SHA256
        or preflight["request_plan_sha256"] != FROZEN_REQUEST_PLAN_SHA256
        or preflight["cost"]["request_utf8_bytes_input_token_upper_bound"]
        != FROZEN_INPUT_TOKEN_UPPER_BOUND
        or preflight["cost"]["output_token_upper_bound"] != FROZEN_OUTPUT_TOKEN_UPPER_BOUND
        or preflight["cost"]["conservative_generation_cost_upper_bound_usd"]
        != FROZEN_COST_UPPER_BOUND_USD
    ):
        raise luna_v1.ApparatusFailure("Protocol-v1.2 frozen request/cost contract drifted")
    return payload, cases, calls, luna_v1._sealed(preflight)


@contextmanager
def _activated_protocol() -> Iterator[None]:
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "MAX_OUTPUT_TOKENS": MAX_OUTPUT_TOKENS,
        "FROZEN_REQUEST_PLAN_SHA256": FROZEN_REQUEST_PLAN_SHA256,
        "_git_revision_and_sources": _git_revision_and_sources,
        "_assert_sources_unchanged": _assert_sources_unchanged,
        "verify_sealed_parent": _verify_lineage,
        "deterministic_preflight": _deterministic_preflight_impl,
    }
    originals = {name: getattr(v1, name) for name in replacements}
    for name, value in replacements.items():
        setattr(v1, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(v1, name, value)


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _activated_protocol():
        return _deterministic_preflight_impl(
            repo_root, require_committed=require_committed
        )


def _complete_condition(scores: Sequence[grading.LabelScore]) -> bool:
    return len(scores) == v1.CASES_PER_CONDITION and len({row.case_id for row in scores}) == v1.CASES_PER_CONDITION


def _missing_test_row(*, test: str, matched: Sequence[int], missing: Sequence[int]):
    return {
        "test": test,
        "test_status": "not_run_incomplete_matched_replications",
        "differences": [],
        "raw_p_value": None,
        "p_value": 1.0,
        "p_value_is_conservative_holm_placeholder": True,
        "effect": None,
        "matched_replications": list(matched),
        "missing_matched_replications": list(missing),
        "requires_all_eight_matched_replications": True,
    }


def matched_primary_analysis(
    scores: Mapping[int, Mapping[str, Sequence[grading.LabelScore]]]
) -> Mapping[str, Any]:
    correct: dict[int, dict[str, int | None]] = {}
    complete: dict[int, dict[str, bool]] = {}
    for replication in range(1, v1.REPLICATION_COUNT + 1):
        correct[replication] = {}
        complete[replication] = {}
        for condition in v1.CONDITIONS:
            selected = list(scores[replication][condition])
            is_complete = _complete_condition(selected)
            complete[replication][condition] = is_complete
            correct[replication][condition] = (
                sum(row.answer_correct is True for row in selected) if is_complete else None
            )
    unadjusted: dict[str, Mapping[str, Any]] = {}
    for hypothesis, condition in v1.PRIMARY_COMPARISONS.items():
        matched = [
            replication
            for replication in range(1, v1.REPLICATION_COUNT + 1)
            if complete[replication]["C1"] and complete[replication][condition]
        ]
        missing = [replication for replication in range(1, 9) if replication not in matched]
        if len(matched) == 8:
            differences = [
                int(correct[replication][condition]) - int(correct[replication]["C1"])
                for replication in matched
            ]
            row = {
                **v1.exact_two_sided_sign_flip(differences),
                "test_status": "ran",
                "raw_p_value": v1.exact_two_sided_sign_flip(differences)["p_value"],
                "effect": v1._effect_summary(differences),
                "matched_replications": matched,
                "missing_matched_replications": missing,
                "requires_all_eight_matched_replications": True,
            }
        else:
            row = _missing_test_row(
                test="exact_two_sided_replication_sign_flip",
                matched=matched,
                missing=missing,
            )
        unadjusted[hypothesis] = {
            **row,
            "control": "C1",
            "condition": condition,
        }
    adjusted = v1.holm_adjust(unadjusted)
    return {
        "replication_correct": {
            str(replication): correct[replication] for replication in correct
        },
        "replication_complete": {
            str(replication): complete[replication] for replication in complete
        },
        "primary": adjusted,
    }


def matched_secondary_analysis(primary_analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    complete = primary_analysis["replication_complete"]
    correct = primary_analysis["replication_correct"]
    requirements = {
        "I_KA": ("C1", "K-", "A-", "KA-"),
        "I_KS": ("C1", "K-", "S-", "KS-"),
        "I_AS": ("C1", "A-", "S-", "AS-"),
        "I_KAS": tuple(v1.CONDITIONS),
    }
    raw: dict[str, Mapping[str, Any]] = {}
    for name, required in requirements.items():
        matched = [
            replication
            for replication in range(1, 9)
            if all(complete[str(replication)][condition] for condition in required)
        ]
        missing = [replication for replication in range(1, 9) if replication not in matched]
        if len(matched) != 8:
            raw[name] = {
                **_missing_test_row(
                    test="exact_two_sided_replication_sign_flip",
                    matched=matched,
                    missing=missing,
                ),
                "required_conditions": list(required),
                "inferential_role": "secondary_mechanistic_separate_Holm_family",
            }
            continue
        vector = []
        for replication in matched:
            row = correct[str(replication)]
            if name == "I_KA":
                value = row["KA-"] - row["K-"] - row["A-"] + row["C1"]
            elif name == "I_KS":
                value = row["KS-"] - row["K-"] - row["S-"] + row["C1"]
            elif name == "I_AS":
                value = row["AS-"] - row["A-"] - row["S-"] + row["C1"]
            else:
                value = (
                    row["KAS-"]
                    - row["KA-"]
                    - row["KS-"]
                    - row["AS-"]
                    + row["K-"]
                    + row["A-"]
                    + row["S-"]
                    - row["C1"]
                )
            vector.append(value)
        exact = v1.exact_two_sided_sign_flip(vector)
        raw[name] = {
            **exact,
            "test_status": "ran",
            "raw_p_value": exact["p_value"],
            "effect": v1._effect_summary(
                vector, definition=f"{name}_factorial_accuracy_contrast_out_of_20"
            ),
            "matched_replications": matched,
            "missing_matched_replications": missing,
            "requires_all_eight_matched_replications": True,
            "required_conditions": list(required),
            "inferential_role": "secondary_mechanistic_separate_Holm_family",
        }
    return v1.holm_adjust(raw)


def kas_replication_analysis(primary_analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    complete = primary_analysis["replication_complete"]
    correct = primary_analysis["replication_correct"]
    matched = [
        replication
        for replication in range(1, 9)
        if complete[str(replication)]["C1"] and complete[str(replication)]["KAS-"]
    ]
    missing = [replication for replication in range(1, 9) if replication not in matched]
    if len(matched) != 8:
        return {
            "test_status": "not_run_incomplete_matched_replications",
            "raw_p_value": None,
            "matched_replications": matched,
            "missing_matched_replications": missing,
            "requires_all_eight_matched_replications": True,
        }
    differences = [
        correct[str(replication)]["KAS-"] - correct[str(replication)]["C1"]
        for replication in matched
    ]
    return {
        **v1.exact_kas_replication_permutation(differences),
        "test_status": "ran",
        "matched_replications": matched,
        "missing_matched_replications": [],
        "requires_all_eight_matched_replications": True,
    }


def _classification(
    analysis: Mapping[str, Any],
    secondary: Mapping[str, Mapping[str, Any]],
    kas: Mapping[str, Any],
) -> Mapping[str, Any]:
    primary = analysis["primary"]
    incomplete = [name for name, row in primary.items() if row["test_status"] != "ran"]
    analyzable = [name for name, row in primary.items() if row["test_status"] == "ran"]
    harmful = [
        name
        for name in analyzable
        if primary[name]["holm_adjusted_p_value"] <= 0.05
        and primary[name]["effect"]["mean_answers_out_of_20"] < 0
    ]
    incomplete_interactions = [
        name for name, row in secondary.items() if row["test_status"] != "ran"
    ]
    analyzable_interactions = [
        name for name, row in secondary.items() if row["test_status"] == "ran"
    ]
    harmful_interactions = [
        name
        for name in analyzable_interactions
        if secondary[name]["holm_adjusted_p_value"] <= 0.05
        and secondary[name]["effect"]["mean_answers_out_of_20"] < 0
    ]
    c1_complete = all(
        analysis["replication_complete"][str(replication)]["C1"]
        for replication in range(1, 9)
    )
    c1_total = (
        sum(
            int(analysis["replication_correct"][str(replication)]["C1"])
            for replication in range(1, 9)
        )
        if c1_complete
        else None
    )
    baseline_drift = c1_complete and int(c1_total) < v1.BASELINE_STABILITY_MIN_CORRECT
    common = {
        "baseline_drift": baseline_drift,
        "baseline_c1_exact_correct": c1_total,
        "baseline_threshold": "C1 exact_correct < 144/160",
        "incomplete_primary_hypotheses": incomplete,
        "analyzable_primary_hypotheses": analyzable,
        "harmful_single_field_hypotheses": harmful,
        "incomplete_secondary_interactions": incomplete_interactions,
        "analyzable_secondary_interactions": analyzable_interactions,
        "harmful_secondary_interactions": harmful_interactions,
        "kas_replication_analyzable": kas.get("test_status") == "ran",
    }
    if baseline_drift:
        return {
            **common,
            "result_code": "VALID_BASELINE_DRIFT",
            "evidence_label": "INCONCLUSIVE",
            "semantic_conclusion_licensed": False,
        }
    if kas.get("test_status") == "ran" and kas.get("replication_failure") is True:
        return {
            **common,
            "result_code": "VALID_KAS_REPLICATION_FAILURE",
            "evidence_label": "INCONCLUSIVE",
            "semantic_conclusion_licensed": False,
        }
    if harmful:
        if incomplete:
            return {
                **common,
                "result_code": "VALID_PARTIAL_PRIMARY_SUPPORTED",
                "evidence_label": "SUPPORTED",
                "semantic_conclusion_licensed": True,
                "claim_limited_to_analyzable_hypotheses": True,
            }
        if len(harmful) >= 2:
            code = "VALID_SUPPORTED_DISTRIBUTED_BUNDLE"
        else:
            code = {
                "H_KIND": "VALID_SUPPORTED_KIND_LOAD_BEARING",
                "H_AUTHORITY": "VALID_SUPPORTED_AUTHORITY_LOAD_BEARING",
                "H_STATUS": "VALID_SUPPORTED_STATUS_LOAD_BEARING",
            }[harmful[0]]
        return {
            **common,
            "result_code": code,
            "evidence_label": "SUPPORTED",
            "semantic_conclusion_licensed": True,
        }
    if harmful_interactions:
        return {
            **common,
            "result_code": "VALID_SUPPORTED_MULTIFIELD_INTERACTION",
            "evidence_label": "SUPPORTED",
            "semantic_conclusion_licensed": True,
        }
    if not analyzable:
        return {
            **common,
            "result_code": "VALID_NO_ANALYZABLE_PRIMARY",
            "evidence_label": "INCONCLUSIVE",
            "semantic_conclusion_licensed": False,
        }
    if incomplete:
        return {
            **common,
            "result_code": "VALID_PARTIAL_PRIMARY_NOT_SUPPORTED",
            "evidence_label": "NOT_SUPPORTED",
            "semantic_conclusion_licensed": True,
            "claim_limited_to_analyzable_hypotheses": True,
        }
    if all(row["holm_adjusted_p_value"] > 0.05 for row in primary.values()):
        code = "VALID_NO_SINGLE_FIELD_EFFECT"
    else:
        code = "VALID_NOT_SUPPORTED"
    return {
        **common,
        "result_code": code,
        "evidence_label": "NOT_SUPPORTED",
        "semantic_conclusion_licensed": True,
    }


def aggregate_partial_result(
    *,
    cases: Sequence[worlds.BenchmarkCase],
    scores: Mapping[int, Mapping[str, Sequence[grading.LabelScore]]],
    records: Sequence[Any],
    preflight: Mapping[str, Any],
    isolated_failures: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    def record_metadata(record: Any) -> Mapping[str, Any]:
        return record.metadata if hasattr(record, "metadata") else record["metadata"]

    if not isolated_failures and all(
        _complete_condition(scores[replication][condition])
        for replication in range(1, 9)
        for condition in v1.CONDITIONS
    ):
        complete = dict(v1.aggregate_valid_result(
            cases=cases, scores=scores, records=records, preflight=preflight
        ))
        complete["execution_disposition"] = "VALID_COMPLETE_CALLS"
        complete["isolated_call_failures"] = []
        complete["isolated_call_failure_count"] = 0
        return complete
    by_case = {case.case_id: case for case in cases}
    analysis = matched_primary_analysis(scores)
    secondary = matched_secondary_analysis(analysis)
    kas = kas_replication_analysis(analysis)
    conditions = {}
    for condition in v1.CONDITIONS:
        available = [
            score
            for replication in range(1, 9)
            for score in scores[replication][condition]
        ]
        summary = dict(v1._score_summary(available, by_case))
        summary["complete_replications"] = [
            replication
            for replication in range(1, 9)
            if analysis["replication_complete"][str(replication)][condition]
        ]
        summary["incomplete_replications"] = [
            replication
            for replication in range(1, 9)
            if not analysis["replication_complete"][str(replication)][condition]
        ]
        summary["scheduled_total"] = v1.TRIALS_PER_CONDITION
        summary["missing_scores_not_imputed"] = v1.TRIALS_PER_CONDITION - len(available)
        conditions[condition] = summary
    classification = _classification(analysis, secondary, kas)
    return {
        "schema_version": v1.SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "source_revision": preflight["source_revision"],
        "validity": "VALID",
        "result_code": classification["result_code"],
        "evidence_label": classification["evidence_label"],
        "classification": classification,
        "estimand": preflight["estimand"],
        "replication_count": 8,
        "fixed_world_count": 20,
        "replication_scores": analysis["replication_correct"],
        "replication_complete": analysis["replication_complete"],
        "conditions": conditions,
        "primary_single_field_hypotheses": analysis["primary"],
        "secondary_interactions": secondary,
        "kas_behavioral_replication": kas,
        "isolated_call_failures": list(isolated_failures),
        "isolated_call_failure_count": len(isolated_failures),
        "execution_disposition": "VALID_WITH_ISOLATED_CALL_FAILURES",
        "missing_scores_imputed": False,
        "malformed_outputs_salvaged": False,
        "usage": v1._usage_from_records(records),
        "returned_model": sorted(
            {
                record_metadata(record).get("returned_model")
                for record in records
                if record_metadata(record).get("returned_model")
            }
        ),
        "returned_service_tier": sorted(
            {
                record_metadata(record).get("returned_service_tier")
                for record in records
                if record_metadata(record).get("returned_service_tier")
            }
        ),
        "claim_scope": (
            "only complete matched replication units in this frozen benchmark and solver"
        ),
    }


def _call_artifact(audit: luna_v1.OpenAIAuditStore, record) -> Mapping[str, Any]:
    return json.loads((audit.root / record.artifact_path).read_text(encoding="utf-8"))


def _failure_text(call: Mapping[str, Any]) -> str:
    error = call.get("transport_error")
    if not isinstance(error, Mapping):
        return ""
    return " ".join(
        str(error.get(name, "")) for name in ("type", "message")
    ).lower()


def _classify_isolated_call_failure(
    call: Mapping[str, Any], decision: Mapping[str, Any] | None = None
) -> str | None:
    if decision and decision.get("failure_category") == "parser_failure":
        return "parser_failure"
    if call.get("status") != "transport_error":
        return None
    metadata = call.get("transport_metadata", {})
    text = _failure_text(call)
    systemic_markers = (
        "insufficient_quota",
        "credit_balance_exhausted",
        "no credits",
        "quota",
        "billing",
        "payment",
        "permission",
        "forbidden",
        "unauthorized",
        "authentication",
        "invalid_api_key",
        "api key",
        "wrong model",
        "model_not_found",
        "service tier",
    )
    if any(marker in text for marker in systemic_markers):
        return None
    if metadata.get("response_status") == "incomplete":
        return "incomplete_response"
    if any(
        marker in text
        for marker in (
            "timeouterror",
            "apitimeouterror",
            "timed out",
            "timeout",
        )
    ):
        return "transient_timeout"
    if any(
        marker in text
        for marker in (
            "apiconnectionerror",
            "connectionerror",
            "networkerror",
            "connection reset",
            "connection aborted",
            "temporary network",
            "name resolution",
        )
    ):
        return "transient_network"
    if re.search(r"(?:status(?: code)?[^0-9]{0,8}|http[^0-9]{0,8})5\d\d\b", text):
        return "transient_http_5xx"
    if (
        re.search(r"\b429\b", text)
        and any(marker in text for marker in ("rate", "too many requests", "temporar"))
    ):
        return "transient_http_429"
    return None


def _validate_attempt_contract(
    call: Mapping[str, Any],
    config,
    *,
    require_response_identity: bool,
    expected_text_format: Mapping[str, Any],
    failure_category: str | None = None,
) -> str | None:
    metadata = call.get("transport_metadata")
    if not isinstance(metadata, Mapping):
        raise luna_v1.ApparatusFailure("call transport metadata is missing")
    for name, value in config.to_mapping().items():
        if metadata.get(name) != value:
            raise luna_v1.ApparatusFailure(
                f"call metadata violates frozen {name} configuration"
            )
    if metadata.get("physical_attempts") != 1:
        raise luna_v1.ApparatusFailure("call did not use exactly one physical attempt")
    if (
        metadata.get("provider") != "openai"
        or metadata.get("api") != "responses"
        or metadata.get("provider_fallback") is not False
        or metadata.get("sdk_max_retries") != 0
        or metadata.get("requested_model") != config.model
        or metadata.get("configuration_hash") != config.configuration_hash
        or metadata.get("sdk_version") != luna_v1.EXPECTED_OPENAI_SDK
    ):
        raise luna_v1.ApparatusFailure("call provider/fallback contract changed")
    expected_format_hash = luna_v1._sha256_text(
        luna_v1._canonical_json(expected_text_format)
    )
    if metadata.get("openai_text_format_sha256") != expected_format_hash:
        raise luna_v1.ApparatusFailure("structured-output format hash changed")
    returned_model = metadata.get("returned_model")
    returned_tier = metadata.get("returned_service_tier")
    response_id = metadata.get("response_id")
    if returned_model not in {None, config.model}:
        raise luna_v1.ApparatusFailure("returned model differs from requested Luna")
    if returned_tier not in {None, config.service_tier}:
        raise luna_v1.ApparatusFailure("returned service tier differs from frozen tier")
    if require_response_identity:
        if not isinstance(response_id, str) or not response_id:
            raise luna_v1.ApparatusFailure("provider response identity is missing")
        if returned_model != config.model or returned_tier != config.service_tier:
            raise luna_v1.ApparatusFailure(
                "provider response lacks exact requested model/service identity"
            )
    counters = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    true_no_response_transients = {
        "transient_timeout",
        "transient_network",
        "transient_http_5xx",
        "transient_http_429",
    }
    if failure_category in true_no_response_transients:
        if (
            call.get("status") != "transport_error"
            or metadata.get("adapter_status") != "transport_error"
            or metadata.get("response_status") is not None
            or response_id is not None
            or returned_model is not None
            or returned_tier is not None
            or any(metadata.get(name) is not None for name in counters)
        ):
            raise luna_v1.ApparatusFailure(
                "pre-response transient envelope contains response or usage data"
            )
        return None
    if call.get("status") == "completed":
        luna_v1._validate_metadata(
            metadata,
            config=config,
            expected_text_format=expected_text_format,
            expected_returned_model=config.model,
        )
    elif failure_category == "incomplete_response":
        required = {
            "adapter_status": "rejected",
            "response_status": "incomplete",
        }
        if any(metadata.get(name) != value for name, value in required.items()):
            raise luna_v1.ApparatusFailure("incomplete response envelope is incoherent")
        if (
            metadata.get("openai_text_format_sha256") != expected_format_hash
            or metadata.get("response_error") is not None
            or not isinstance(metadata.get("incomplete_details"), Mapping)
        ):
            raise luna_v1.ApparatusFailure("incomplete response metadata is invalid")
    else:
        raise luna_v1.ApparatusFailure("call status/adapter envelope is not recognized")
    if any(type(metadata.get(name)) is not int or metadata[name] < 0 for name in counters):
        raise luna_v1.ApparatusFailure("call token accounting is invalid")
    if metadata["cached_input_tokens"] != 0 or metadata["cache_write_input_tokens"] != 0:
        raise luna_v1.ApparatusFailure("explicit no-cache contract was violated")
    if metadata["total_tokens"] != metadata["input_tokens"] + metadata["output_tokens"]:
        raise luna_v1.ApparatusFailure("call token accounting is incoherent")
    if metadata["reasoning_tokens"] > metadata["output_tokens"]:
        raise luna_v1.ApparatusFailure("call reasoning tokens exceed output tokens")
    return response_id if isinstance(response_id, str) and response_id else None


def _isolated_failure(
    audit: luna_v1.OpenAIAuditStore,
    planned: v1.ExperimentCall,
    exc: BaseException,
    response_ids_before: set[str],
    response_ids: set[str],
    config,
) -> Mapping[str, Any] | None:
    if not audit.records or audit.records[-1].sequence != planned.sequence:
        return None
    record = audit.records[-1]
    decision_path = audit.root / "decisions" / f"decision_{record.call_id[5:]}.json"
    call = _call_artifact(audit, record)
    decision = (
        json.loads(decision_path.read_text(encoding="utf-8"))
        if decision_path.is_file()
        else None
    )
    category = _classify_isolated_call_failure(call, decision)
    if category is None:
        return None
    require_identity = call.get("transport_metadata", {}).get("response_status") == "incomplete"
    response_id = _validate_attempt_contract(
        call,
        config,
        require_response_identity=require_identity,
        expected_text_format=planned.text_format,
        failure_category=category,
    )
    if response_id is not None:
        if response_id in response_ids_before:
            raise luna_v1.ApparatusFailure("response ID was reused")
        response_ids.add(response_id)
    if not decision_path.is_file():
        audit.write_decision(
            record,
            {
                "schema_version": v1.SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "call_id": record.call_id,
                "status": "isolated_call_failure",
                "failure_category": category,
                "replication": planned.replication,
                "condition_position": planned.condition_position,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "parser_status": "not_run",
                "grader_status": "not_run",
                "grader_agreement": None,
                "response_sha256": call.get("response", {}).get("sha256"),
                "scores": [],
                "physical_attempts": call.get("transport_metadata", {}).get(
                    "physical_attempts"
                ),
                "retry_attempted": False,
                "repair_attempted": False,
            },
        )
    return {
        "call_id": record.call_id,
        "sequence": planned.sequence,
        "replication": planned.replication,
        "condition": planned.condition,
        "batch_id": planned.batch_id,
        "category": category,
        "reason": v1._safe_reason(exc),
        "physical_attempts": record.metadata.get("physical_attempts"),
        "continued_without_retry": True,
    }


class SemanticDecompositionV12Runner(v1.SemanticDecompositionRunner):
    def __init__(self, *args, **kwargs) -> None:
        with _activated_protocol():
            super().__init__(*args, **kwargs)

    def _run_call_v1_2(
        self,
        audit: luna_v1.OpenAIAuditStore,
        planned: v1.ExperimentCall,
        by_case: Mapping[str, worlds.BenchmarkCase],
    ) -> None:
        response = audit.ask(planned)
        record = audit.records[-1]
        call = _call_artifact(audit, record)
        response_id = _validate_attempt_contract(
            call,
            self.config,
            require_response_identity=True,
            expected_text_format=planned.text_format,
        )
        assert response_id is not None
        if response_id in self.response_ids:
            raise luna_v1.ApparatusFailure("response ID was reused")
        self.response_ids.add(response_id)
        cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = luna_v1.parse_structured_labels(response, len(cases))
        except grading.ConstrainedInterfaceFailure as exc:
            audit.write_decision(
                record,
                {
                    "schema_version": v1.SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "call_id": record.call_id,
                    "status": "isolated_call_failure",
                    "failure_category": "parser_failure",
                    "replication": planned.replication,
                    "condition_position": planned.condition_position,
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "response_sha256": luna_v1._sha256_text(response),
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(exc),
                    "scores": [],
                    "physical_attempts": 1,
                    "retry_attempted": False,
                    "repair_attempted": False,
                },
            )
            raise IsolatedParserFailure(str(exc)) from None
        scores = [
            grading.grade_label(case, label, condition=planned.condition)
            for case, label in zip(cases, labels)
        ]
        if any(score.secondary_status != "ran" for score in scores):
            raise luna_v1.ApparatusFailure(
                f"{record.call_id} deterministic secondary evaluation failed"
            )
        self.scores[planned.replication][planned.condition].extend(scores)
        audit.write_decision(
            record,
            {
                "schema_version": v1.SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "call_id": record.call_id,
                "status": "graded",
                "replication": planned.replication,
                "condition_position": planned.condition_position,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "response_sha256": luna_v1._sha256_text(response),
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in scores],
            },
        )

    def run(self) -> Mapping[str, Any]:
        with _activated_protocol():
            expected = (self.repo_root / RUN_DIR).resolve()
            if self.require_committed and self.output_dir.resolve() != expected:
                raise luna_v1.ApparatusFailure("live Protocol-v1.2 execution is locked to its frozen directory")
            if self.output_dir.exists():
                raise luna_v1.ApparatusFailure("Protocol-v1.2 run directory already exists")
            payload, cases, calls, preflight = _deterministic_preflight_impl(
                self.repo_root, require_committed=self.require_committed
            )
            del payload
            audit = luna_v1.OpenAIAuditStore(
                self.output_dir, ask_fn=self.ask_fn, config=self.config
            )
            luna_v1._write_exclusive(
                self.output_dir / "PRECHECK.json", luna_v1._pretty_json(preflight)
            )
            for name, content in {
                "PROTOCOL.json": {
                    "schema_version": v1.SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "protocol_version": PROTOCOL_VERSION,
                    "calls": v1.MAX_GENERATION_CALLS,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                    "isolated_failures_continue": True,
                    "no_retry": True,
                    "no_repair": True,
                    "no_fallback": True,
                    "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
                },
                "MANIFEST.json": {
                    "schema_version": v1.SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "protocol_version": PROTOCOL_VERSION,
                    "created_at_utc": luna_v1._utc_now(),
                    "source_revision": preflight["source_revision"],
                    "precheck_sha256": preflight["payload_sha256"],
                    "solver_config": self.config.to_mapping(),
                    "solver_config_sha256": self.config.configuration_hash,
                    "maximum_physical_generation_calls": v1.MAX_GENERATION_CALLS,
                    "attempts_per_call": 1,
                    "no_retry": True,
                    "no_resume": True,
                    "no_overwrite": True,
                },
            }.items():
                luna_v1._write_exclusive(
                    self.output_dir / name,
                    luna_v1._pretty_json(luna_v1._sealed(content)),
                )
            by_case = {case.case_id: case for case in cases}
            isolated = []
            for planned in calls:
                before = len(self.scores[planned.replication][planned.condition])
                response_ids_before = set(self.response_ids)
                try:
                    _assert_sources_unchanged(self.repo_root, preflight)
                except BaseException as exc:
                    return self._invalid(
                        audit, preflight=preflight, failed_call=planned, exc=exc
                    )
                try:
                    self._run_call_v1_2(audit, planned, by_case)
                except BaseException as exc:
                    try:
                        failure = _isolated_failure(
                            audit,
                            planned,
                            exc,
                            response_ids_before,
                            self.response_ids,
                            self.config,
                        )
                    except BaseException as systemic_exc:
                        return self._invalid(
                            audit,
                            preflight=preflight,
                            failed_call=planned,
                            exc=systemic_exc,
                        )
                    if failure is None:
                        return self._invalid(
                            audit, preflight=preflight, failed_call=planned, exc=exc
                        )
                    del self.scores[planned.replication][planned.condition][before:]
                    isolated.append(failure)
                try:
                    _assert_sources_unchanged(self.repo_root, preflight)
                except BaseException as exc:
                    return self._invalid(
                        audit, preflight=preflight, failed_call=planned, exc=exc
                    )
            try:
                if len(audit.records) != v1.MAX_GENERATION_CALLS:
                    raise luna_v1.ApparatusFailure("completed schedule has wrong call count")
                result = aggregate_partial_result(
                    cases=cases,
                    scores=self.scores,
                    records=audit.records,
                    preflight=preflight,
                    isolated_failures=isolated,
                )
            except BaseException as exc:
                return self._invalid(
                    audit, preflight=preflight, failed_call=calls[-1], exc=exc
                )
            return self._finish(audit, preflight=preflight, result=result)


def _verify_run_impl(run_dir: Path) -> Mapping[str, Any]:
    index = v1._verify_index(run_dir)
    preflight = json.loads((run_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "RUN_STATUS.json").read_text(encoding="utf-8"))
    if any(
        payload.get("protocol_id") != PROTOCOL_ID
        for payload in (index, preflight, result, status)
    ) or preflight.get("protocol_version") != PROTOCOL_VERSION:
        raise luna_v1.ApparatusFailure("Protocol-v1.2 artifact identity mismatch")
    if preflight.get("source_revision") != index.get("source_revision"):
        raise luna_v1.ApparatusFailure("Protocol-v1.2 source revision binding mismatch")
    if (
        not preflight.get("source_file_sha256")
        or not preflight.get("source_file_git_blob_oid")
        or set(preflight["source_file_sha256"]) != set(SOURCE_FILES)
        or set(preflight["source_file_git_blob_oid"]) != set(SOURCE_FILES)
        or preflight.get("request_plan_sha256") != FROZEN_REQUEST_PLAN_SHA256
        or preflight.get("solver_config_sha256") != FROZEN_SOLVER_CONFIG_SHA256
    ):
        raise luna_v1.ApparatusFailure("Protocol-v1.2 preflight source/request binding failed")
    cost = preflight.get("cost", {})
    if (
        cost.get("pricing_usd_per_million")
        != {
            "input": v1.INPUT_USD_PER_MILLION,
            "output_including_reasoning": v1.OUTPUT_USD_PER_MILLION,
        }
        or cost.get("request_utf8_bytes_input_token_upper_bound")
        != FROZEN_INPUT_TOKEN_UPPER_BOUND
        or cost.get("output_token_upper_bound") != FROZEN_OUTPUT_TOKEN_UPPER_BOUND
        or cost.get("conservative_generation_cost_upper_bound_usd")
        != FROZEN_COST_UPPER_BOUND_USD
        or cost.get("authorized_cost_ceiling_usd") != v1.AUTHORIZED_COST_CEILING_USD
    ):
        raise luna_v1.ApparatusFailure("Protocol-v1.2 frozen cost tuple/ceiling changed")
    if result.get("validity") != "VALID":
        if result.get("result_code") != "INVALID_APPARATUS":
            raise luna_v1.ApparatusFailure("invalid run has a semantic disposition")
        return {
            "verified": True,
            "protocol_id": PROTOCOL_ID,
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "physical_generation_calls": result["usage"]["total"][
                "physical_generation_calls"
            ],
            "unique_response_ids": status["unique_response_ids"],
        }
    call_paths = sorted((run_dir / "calls").glob("call_*.json"))
    decision_paths = sorted((run_dir / "decisions").glob("decision_*.json"))
    if len(call_paths) != 384 or len(decision_paths) != 384:
        raise luna_v1.ApparatusFailure(
            "valid Protocol-v1.2 run must preserve all 384 calls and decisions"
        )
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(events) != 768:
        raise luna_v1.ApparatusFailure("valid Protocol-v1.2 journal is not 768 events")
    payload, cases = worlds.load_case_pack(
        Path(__file__).resolve().parents[1]
        / "benchmarks/decompression_test/CASE_PACK.json"
    )
    planned_calls = v1.build_call_plan(payload, cases)
    config = v1.solver_config()
    if config.configuration_hash != FROZEN_SOLVER_CONFIG_SHA256:
        raise luna_v1.ApparatusFailure("verifier solver configuration drifted")
    scores: dict[int, dict[str, list[grading.LabelScore]]] = {
        replication: {condition: [] for condition in v1.CONDITIONS}
        for replication in range(1, 9)
    }
    by_case = {case.case_id: case for case in cases}
    response_ids: set[str] = set()
    records = []
    isolated = []
    for sequence, (call_path, decision_path, planned) in enumerate(
        zip(call_paths, decision_paths, planned_calls), start=1
    ):
        call = json.loads(call_path.read_text(encoding="utf-8"))
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        expected_call_id = f"call_{sequence:06d}"
        if (
            call.get("sequence") != sequence
            or call.get("call_id") != expected_call_id
            or call.get("stage") != planned.stage
            or call.get("batch_id") != planned.batch_id
            or call.get("condition") != planned.condition
            or call.get("case_ids") != list(planned.case_ids)
            or decision.get("call_id") != expected_call_id
            or decision.get("replication") != planned.replication
            or decision.get("condition") != planned.condition
            or decision.get("batch_id") != planned.batch_id
        ):
            raise luna_v1.ApparatusFailure("call/decision sequence differs from frozen plan")
        request = call.get("request", {})
        if (
            request.get("prompt") != planned.prompt
            or request.get("prompt_sha256") != luna_v1._sha256_text(planned.prompt)
            or request.get("openai_text_format") != planned.text_format
            or request.get("solver_config") != config.to_mapping()
            or request.get("solver_config_sha256") != config.configuration_hash
        ):
            raise luna_v1.ApparatusFailure("stored request differs from frozen Protocol v1.2")
        raw = call.get("response", {}).get("raw_text")
        raw_sha = luna_v1._sha256_text(raw) if isinstance(raw, str) else None
        if call.get("response", {}).get("sha256") != raw_sha or decision.get(
            "response_sha256"
        ) != raw_sha:
            raise luna_v1.ApparatusFailure("call/decision raw response binding failed")
        started, finished = events[2 * (sequence - 1) : 2 * sequence]
        relative = call_path.relative_to(run_dir).as_posix()
        if (
            started.get("event") != "call_started"
            or started.get("sequence") != sequence
            or started.get("call_id") != expected_call_id
            or started.get("prompt_sha256") != request.get("prompt_sha256")
            or finished.get("event") != "call_finished"
            or finished.get("sequence") != sequence
            or finished.get("call_id") != expected_call_id
            or finished.get("status") != call.get("status")
            or finished.get("artifact_path") != relative
            or finished.get("artifact_file_sha256")
            != luna_v1._sha256_bytes(call_path.read_bytes())
        ):
            raise luna_v1.ApparatusFailure("call journal binding failed")
        metadata = call.get("transport_metadata", {})
        category = _classify_isolated_call_failure(call, decision)
        response_status = metadata.get("response_status")
        require_identity = call.get("status") == "completed" or response_status == "incomplete"
        response_id = _validate_attempt_contract(
            call,
            config,
            require_response_identity=require_identity,
            expected_text_format=planned.text_format,
            failure_category=category,
        )
        if response_id is not None:
            if response_id in response_ids:
                raise luna_v1.ApparatusFailure("response ID was reused")
            response_ids.add(response_id)
        records.append({"condition": planned.condition, "metadata": metadata})
        if call.get("status") == "completed" and decision.get("status") == "graded":
            if call.get("transport_error") is not None or call.get("admission_error") is not None:
                raise luna_v1.ApparatusFailure("completed call contains an error envelope")
            try:
                labels = luna_v1.parse_structured_labels(raw, len(planned.case_ids))
            except grading.ConstrainedInterfaceFailure as exc:
                raise luna_v1.ApparatusFailure("graded call fails strict reparsing") from exc
            if decision.get("labels") != list(labels):
                raise luna_v1.ApparatusFailure("decision labels differ from raw response")
            regenerated = [
                grading.grade_label(
                    by_case[case_id], label, condition=planned.condition
                )
                for case_id, label in zip(planned.case_ids, labels)
            ]
            if decision.get("scores") != [v1._score_mapping(score) for score in regenerated]:
                raise luna_v1.ApparatusFailure("decision scores fail deterministic regrading")
            scores[planned.replication][planned.condition].extend(regenerated)
            continue
        if category is None or decision.get("scores") != []:
            raise luna_v1.ApparatusFailure(
                "failed call is unrecognized or contains imputed/salvaged scores"
            )
        if decision.get("status") != "isolated_call_failure" or decision.get(
            "failure_category"
        ) != category:
            raise luna_v1.ApparatusFailure("isolated failure decision taxonomy changed")
        if category == "parser_failure":
            if call.get("status") != "completed":
                raise luna_v1.ApparatusFailure("parser failure lacks a completed response")
            try:
                luna_v1.parse_structured_labels(raw, len(planned.case_ids))
            except grading.ConstrainedInterfaceFailure:
                pass
            else:
                raise luna_v1.ApparatusFailure("claimed parser failure is admissible")
            reason = decision.get("error")
        else:
            reason = (
                f"{expected_call_id} transport failed: "
                f"{call.get('transport_error', {}).get('message')}"
            )
        isolated.append(
            {
                "call_id": expected_call_id,
                "sequence": sequence,
                "replication": planned.replication,
                "condition": planned.condition,
                "batch_id": planned.batch_id,
                "category": category,
                "reason": reason,
                "physical_attempts": metadata.get("physical_attempts"),
                "continued_without_retry": True,
            }
        )
    expected_result = aggregate_partial_result(
        cases=cases,
        scores=scores,
        records=records,
        preflight=preflight,
        isolated_failures=isolated,
    )
    observed = dict(result)
    observed.pop("payload_sha256", None)
    if observed != expected_result:
        raise luna_v1.ApparatusFailure("result is not derivable from all sealed call evidence")
    expected_execution_disposition = (
        "VALID_WITH_ISOLATED_CALL_FAILURES"
        if isolated
        else "VALID_COMPLETE_CALLS"
    )
    if (
        result.get("execution_disposition") != expected_execution_disposition
        or result.get("isolated_call_failure_count") != len(isolated)
        or result.get("isolated_call_failures") != isolated
    ):
        raise luna_v1.ApparatusFailure(
            "execution disposition/failure count is not derivable"
        )
    usage = expected_result["usage"]["total"]
    if (
        usage["physical_generation_calls"] != 384
        or status.get("call_artifacts") != 384
        or status.get("physical_generation_calls") != 384
        or status.get("unique_response_ids") != len(response_ids)
        or status.get("result_code") != result.get("result_code")
    ):
        raise luna_v1.ApparatusFailure("RUN_STATUS counts/disposition are not derivable")
    return {
        "verified": True,
        "protocol_id": PROTOCOL_ID,
        "validity": "VALID",
        "result_code": result["result_code"],
        "call_artifacts": 384,
        "decision_artifacts": 384,
        "physical_generation_calls": 384,
        "unique_response_ids": len(response_ids),
        "isolated_call_failures": len(isolated),
        "execution_disposition": expected_execution_disposition,
        "source_revision": index["source_revision"],
    }


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    with _activated_protocol():
        return _verify_run_impl(run_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(ACKNOWLEDGEMENT, dest="acknowledge", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(luna_v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge:
        parser.error(f"{ACKNOWLEDGEMENT} is required")
    luna_v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = SemanticDecompositionV12Runner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(luna_v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
