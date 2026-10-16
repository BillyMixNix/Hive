"""Prospective continuation of GROW workshop generations.

This is an opt-in development API, not a restart of the frozen GROW-0 run.
It reuses that experiment's diagnosis, candidate evaluator and promotion rule.
Controller callbacks and the initial lineage/episode commitments are trusted;
hash checks do not authenticate those roots or prove scientific preregistration.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from grow.core import (
    CandidateWorkspace, ExperimentInvalid, GenerationRecord, IntegritySnapshot,
    file_hash, hash_json, hash_paths, tree_manifest, utc_now,
    verify_ancestor_and_kernel,
)
from grow.experiment import Grow0Experiment
from grow.kernel.evaluator import counterbalanced_probe
from grow.kernel.promotion import PromotionEvidence, decide_promotion


EPISODE_SCHEMA = "hive.grow.continuation-episode.v1"


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ExperimentInvalid(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ExperimentInvalid(f"non-finite JSON number: {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        _invalid_constant(value)
    return number


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object,
                          parse_constant=_invalid_constant, parse_float=_finite_float)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ExperimentInvalid(f"cannot read committed JSON: {path}") from exc


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is not None


def _episode(path: Path, expected_hash: str) -> dict:
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise ExperimentInvalid("episode requires a SHA-256 commitment")
    if not path.is_file() or file_hash(path) != expected_hash:
        raise ExperimentInvalid("episode bytes differ from their commitment")
    value = _read_json(path)
    fields = {"schema", "episode_id", "parent_id", "trigger", "transfer"}
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != EPISODE_SCHEMA:
        raise ExperimentInvalid("invalid continuation episode schema")
    if not _identifier(value["episode_id"]) or not _identifier(value["parent_id"]):
        raise ExperimentInvalid("invalid episode or parent identifier")
    for name in ("trigger", "transfer"):
        case = value[name]
        required = {"case_id", "goal", "stored_value", "current_value", "expected_source", "expected_value"}
        if (not isinstance(case, dict) or not required.issubset(case)
                or set(case) - required - {"failure_class", "surface_labels", "bundle_id"}):
            raise ExperimentInvalid(f"invalid {name} case schema")
        if not _identifier(case["case_id"]) or not isinstance(case["goal"], str) or not case["goal"].strip():
            raise ExperimentInvalid(f"invalid {name} case identity")
        # The inherited GROW evaluator/diagnosis is specifically a provenance task.
        if (case["expected_source"] != "current"
                or hash_json(case["expected_value"]) != hash_json(case["current_value"])
                or hash_json(case["stored_value"]) == hash_json(case["current_value"])):
            raise ExperimentInvalid("episode does not match the GROW provenance task contract")
    if value["trigger"]["case_id"] == value["transfer"]["case_id"]:
        raise ExperimentInvalid("trigger and transfer identities must differ")
    return value


def _contains_marker(text: str, marker: str) -> bool:
    # Short numeric answers commonly occur *inside* ordinary output SHA-256s.
    # Recognize complete tokens, so retaining an output hash is not a leak.
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"(?![A-Za-z0-9_])", text) is not None


def _archive_root(exp: Grow0Experiment, generation_id: str) -> Path:
    if not re.fullmatch(r"G\d+(?:-[A-Z]+)?", generation_id):
        raise ExperimentInvalid("invalid generation identifier")
    archive = exp.snapshot_dir / generation_id
    # Archives are controller-owned ordinary files, never symlinked sources.
    if archive.is_symlink() or not archive.is_dir():
        raise ExperimentInvalid(f"missing or symlinked generation archive: {generation_id}")
    if any(item.is_symlink() for item in archive.rglob("*")):
        raise ExperimentInvalid(f"symlink in generation archive: {generation_id}")
    if not archive.resolve().is_relative_to(exp.repo_root):
        raise ExperimentInvalid("generation archive escaped the repository")
    return archive


class GrowContinuationExperiment(Grow0Experiment):
    """Run one new episode from an explicitly chosen, promoted generation.

    ``run`` consumes its episode before the first callback. An interruption or
    rejection cannot silently become another attempt on the same protected case.
    Calls use a single controller; this API is not a multi-process scheduler.
    """

    def __init__(self, repo_root: str | Path, *, parent_id: str,
                 episode_path: str | Path, episode_sha256: str,
                 config_path: str = "grow/config.json"):
        super().__init__(repo_root, config_path=config_path)
        self._parent_id = parent_id
        self._episode_path = Path(episode_path).resolve()
        self._episode_hash = episode_sha256
        self._episode = _episode(self._episode_path, episode_sha256)
        if self._episode["parent_id"] != parent_id or parent_id == "G0":
            raise ExperimentInvalid("continuation episode must name its promoted descendant parent")
        self._original_cases = (self.trigger, self._transfer)
        self._chain = self._verified_chain(parent_id)
        root = self._chain[-1]
        try:
            self._snapshot = IntegritySnapshot(**root["validation_results"]["integrity_snapshot"])
        except (KeyError, TypeError) as exc:
            raise ExperimentInvalid("G0 lacks its frozen integrity snapshot") from exc
        self._retention_cases = self._inherited_cases()
        inherited_ids = {case["case_id"] for case in self._retention_cases}
        if any(self._episode[key]["case_id"] in inherited_ids for key in ("trigger", "transfer")):
            raise ExperimentInvalid("continuation must use new case identities")
        self.trigger = self._episode["trigger"]
        self._transfer = self._episode["transfer"]
        self._config_hash = hash_json(self.config)
        self._cases_hash = hash_json([self.trigger, self._transfer, self._retention_cases])
        self._candidate_root: Path | None = None
        self._candidate_manifest: dict | None = None
        self._running = False
        self._calls = {"parent": 0, "modifier": 0, "candidate": 0}
        self._verify_continuation()

    @property
    def parent_generation_id(self) -> str:
        return self._parent_id

    @property
    def workshop_root(self) -> Path:
        return self.snapshot_dir / self._parent_id / "workshop"

    @property
    def required_call_budgets(self) -> dict[str, int]:
        """Maximum model callbacks, including both orders of inherited cases."""
        return {"parent": 4, "modifier": 1, "candidate": 4 + 2 * len(self._retention_cases)}

    def freeze_g0(self, **kwargs):
        raise ExperimentInvalid("continuation cannot refreeze or replace G0")

    def one_generation(self, **kwargs):
        raise ExperimentInvalid("use run() with a committed continuation episode")

    def _verified_chain(self, generation_id: str) -> list[dict]:
        generations = {}
        for entry in self.ledger.entries():
            if entry.get("record_type") != "generation":
                continue
            key = entry.get("generation_id")
            if key in generations:
                raise ExperimentInvalid("duplicate generation identity in lineage")
            generations[key] = entry
        chain = []
        seen = set()
        while generation_id is not None:
            if generation_id in seen or generation_id not in generations:
                raise ExperimentInvalid("cyclic or incomplete parent lineage")
            seen.add(generation_id)
            record = generations[generation_id]
            if record.get("disposition") != "PROMOTED":
                raise ExperimentInvalid("only promoted generations can be inherited")
            if record.get("model_configuration_hash") != self.model_config.config_hash:
                raise ExperimentInvalid("parent model configuration differs")
            archive = _archive_root(self, generation_id)
            expected_metadata = {key: value for key, value in record.items() if key != "record_type"}
            if _read_json(archive / "generation.json") != expected_metadata:
                raise ExperimentInvalid("parent metadata differs from lineage")
            actual = hash_paths(archive / "workshop", self.mutable_paths)
            if any(value is None for value in actual.values()):
                raise ExperimentInvalid("parent workshop is incomplete")
            if generation_id == "G0":
                if record.get("parent_id") is not None or hash_json(actual) != record.get("source_workshop_snapshot_hash"):
                    raise ExperimentInvalid("G0 workshop differs from its commitment")
            elif actual != record.get("after_hashes"):
                raise ExperimentInvalid("parent workshop differs from promoted bytes")
            else:
                try:
                    validation = record["validation_results"]
                    transfer = record["transfer_results"]
                    verdicts = [validation["integrity"]["passed"], record["regression_results"]["passed"],
                                validation["trigger"]["passed"], validation["mutation"]["passed"],
                                transfer["g0"]["passed"], transfer["g1"]["passed"]]
                    if any(type(value) is not bool for value in verdicts):
                        raise ExperimentInvalid("parent promotion verdicts must be booleans")
                    evidence = PromotionEvidence(*verdicts[:4], int(verdicts[4]), int(verdicts[5]))
                except (KeyError, TypeError) as exc:
                    raise ExperimentInvalid("parent lacks promotion evidence") from exc
                if not decide_promotion(evidence)["promoted"]:
                    raise ExperimentInvalid("parent evidence does not satisfy the promotion rule")
            chain.append(record)
            generation_id = record.get("parent_id")
        if not chain or chain[-1]["generation_id"] != "G0":
            raise ExperimentInvalid("parent lineage must terminate at G0")
        for child, parent in zip(chain, chain[1:]):
            parent_root = _archive_root(self, parent["generation_id"]) / "workshop"
            inherited = hash_paths(parent_root, self.mutable_paths)
            if (child.get("before_hashes") != inherited
                    or child.get("source_workshop_snapshot_hash") != hash_json(inherited)):
                raise ExperimentInvalid("child was not created from its named parent")
            context = child["validation_results"].get("continuation")
            if context and context.get("parent_record_sha256") != hash_json(parent):
                raise ExperimentInvalid("continuation parent record commitment differs")
        return chain

    def _inherited_cases(self) -> list[dict]:
        cases = {}
        for record in reversed(self._chain[:-1]):
            context = record["validation_results"].get("continuation")
            if context:
                episode = _episode(Path(context["episode_path"]), context["episode_sha256"])
                if episode["parent_id"] != record["parent_id"]:
                    raise ExperimentInvalid("ancestor episode has a different parent")
                inherited = (episode["trigger"], episode["transfer"])
            else:
                if record["parent_id"] != "G0" or record["benchmark_bundle_id"] != self.config["benchmark_bundle_id"]:
                    raise ExperimentInvalid("unrecognized ancestor evaluation contract")
                inherited = self._original_cases
            for case in inherited:
                key = case["case_id"]
                if key in cases and hash_json(cases[key]) != hash_json(case):
                    raise ExperimentInvalid("ancestor case identity was reused with different content")
                cases[key] = case
        return list(cases.values())

    def _verify_continuation(self) -> None:
        if _episode(self._episode_path, self._episode_hash) != self._episode:
            raise ExperimentInvalid("episode configuration changed")
        if hash_json(self.config) != self._config_hash:
            raise ExperimentInvalid("experiment configuration changed")
        if hash_json([self.trigger, self._transfer, self._retention_cases]) != self._cases_hash:
            raise ExperimentInvalid("case configuration changed")
        if self._verified_chain(self._parent_id) != self._chain:
            raise ExperimentInvalid("committed parent lineage changed")
        if self._inherited_cases() != self._retention_cases:
            raise ExperimentInvalid("inherited protected cases changed")
        checks = verify_ancestor_and_kernel(
            self._snapshot, repo_root=self.repo_root, immutable_paths=self.immutable_paths,
            benchmark_path=self.trigger_path, transfer_path=self.transfer_path,
            evaluator_path=self.evaluator_path, promotion_path=self.promotion_path,
            model_config_hash=self.model_config.config_hash,
        )
        if not checks["passed"]:
            raise ExperimentInvalid("frozen ancestor or kernel changed")
        if self._candidate_root is not None and self._candidate_manifest != self._candidate_tree():
            raise ExperimentInvalid("candidate changed during evaluation")

    def _candidate_tree(self) -> dict:
        if any(path.is_symlink() for path in self._candidate_root.rglob("*")):
            raise ExperimentInvalid("symlink in candidate workspace")
        return tree_manifest(self._candidate_root, ignore_parts=(), ignore_rel_prefixes=())

    def _invoke(self, callback: Callable, argument, *, role: str | None = None):
        self._verify_continuation()
        if role is not None:
            if self._calls[role] >= self.required_call_budgets[role]:
                raise ExperimentInvalid(f"{role} call budget exhausted")
            self._calls[role] += 1
        before = hash_json(self.ledger.entries())
        try:
            return callback(argument)
        finally:
            self._verify_continuation()
            if hash_json(self.ledger.entries()) != before:
                raise ExperimentInvalid("callback changed the controller lineage")

    def assert_modification_prompt_isolated(self, prompt: str) -> None:
        super().assert_modification_prompt_isolated(prompt)
        for case in self._retention_cases:
            if any(_contains_marker(prompt, marker) for marker in self._sensitive_case_markers(case)):
                raise ExperimentInvalid("inherited protected material entered modifier prompt")

    def evaluate_candidate_integrity(self, workspace, snapshot):
        self._verify_continuation()
        self._candidate_root = workspace.root
        self._candidate_manifest = self._candidate_tree()
        result = super().evaluate_candidate_integrity(workspace, snapshot)
        # The inherited protected identities/answers must not be hardcoded either.
        text = "\n".join(workspace.read_text(path) for path in workspace.changed_files())
        leaked = any(_contains_marker(text, marker) for case in self._retention_cases
                     for marker in self._sensitive_case_markers(case))
        result["checks"]["inherited_material_absent"] = not leaked
        result["passed"] = all(result["checks"].values())
        return result

    def _record_generation(self, record: GenerationRecord, workspace: CandidateWorkspace) -> None:
        self._verify_continuation()
        record.benchmark_bundle_id = "continuation:" + self._episode_hash
        record.validation_results["continuation"] = {
            "schema": EPISODE_SCHEMA,
            "evidence_scope": "development_continuation_not_rsi_evidence",
            "episode_id": self._episode["episode_id"],
            "episode_path": str(self._episode_path),
            "episode_sha256": self._episode_hash,
            "parent_record_sha256": hash_json(self._chain[0]),
            "retention_manifest_sha256": hash_json(self._retention_cases),
            "call_budgets": self.required_call_budgets,
            "calls": dict(self._calls),
        }
        # A ledger entry must never make an unarchived child eligible as a parent.
        self._archive_generation(record, workspace=workspace)
        self.ledger.append({"record_type": "generation", **asdict(record)})

    def run(self, *, invoke_parent: Callable[[str], str],
            invoke_modifier: Callable[[str], str], invoke_candidate: Callable[[str], str],
            prior_suite: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
        self._verify_continuation()
        if self._running:
            raise ExperimentInvalid("continuation already running")
        for record in self.ledger.entries():
            if record.get("record_type") == "continuation_attempt" and (
                record.get("episode_id") == self._episode["episode_id"]
                or record.get("episode_sha256") == self._episode_hash
                or set(record.get("case_ids", ())) & {self.trigger["case_id"], self._transfer["case_id"]}
            ):
                raise ExperimentInvalid("continuation episode was already attempted")
        self.ledger.append({
            "record_type": "continuation_attempt", "episode_id": self._episode["episode_id"],
            "episode_sha256": self._episode_hash, "parent_id": self._parent_id,
            "case_ids": [self.trigger["case_id"], self._transfer["case_id"]], "timestamp": utc_now(),
        })
        self._running = True

        def retained(candidate_root):
            prior = self._invoke(prior_suite, candidate_root)
            if not isinstance(prior, dict) or type(prior.get("passed")) is not bool:
                raise ExperimentInvalid("prior suite must return a boolean passed verdict")
            results = []
            if prior["passed"]:
                for case in self._retention_cases:
                    probe = counterbalanced_probe(
                        workshop_module=candidate_root / self.workshop_path, case=case,
                        invoke_model=lambda prompt: self._invoke(invoke_candidate, prompt, role="candidate"),
                    )
                    results.append({"case_id": case["case_id"], **probe})
            passed = prior["passed"] and len(results) == len(self._retention_cases) and all(
                result[order]["passed"] for result in results for order in ("stored_first", "current_first")
            )
            return {"passed": passed, "prior_suite": prior, "inherited_retention": results}

        try:
            return super().one_generation(
                snapshot=self._snapshot,
                invoke_g0=lambda prompt: self._invoke(invoke_parent, prompt, role="parent"),
                invoke_modifier=lambda prompt: self._invoke(invoke_modifier, prompt, role="modifier"),
                invoke_g1=lambda prompt: self._invoke(invoke_candidate, prompt, role="candidate"),
                prior_suite_g1=retained,
            )
        finally:
            self._running = False
            self._candidate_root = None
            self._candidate_manifest = None
