from __future__ import annotations

import json
import py_compile
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from grow.core import (
    AppendOnlyLedger,
    CandidateWorkspace,
    ExperimentInvalid,
    ForbiddenWriteError,
    GenerationRecord,
    IntegritySnapshot,
    LessonLedger,
    ModelConfig,
    hash_json,
    hash_paths,
    make_integrity_snapshot,
    marker_scan,
    normalize_relpath,
    stable_json,
    tree_manifest,
    manifest_hash,
    utc_now,
    verify_ancestor_and_kernel,
)
from grow.kernel.evaluator import counterbalanced_probe, evaluate_case, validate_workshop_source
from grow.kernel.promotion import PromotionEvidence, decide_promotion


@dataclass
class FailurePacket:
    failure_id: str
    generation: str
    task_id: str
    observed_behavior: str
    expected_behavior: str
    smallest_counterexample: dict[str, Any]
    relevant_actions: list[dict[str, Any]] = field(default_factory=list)
    rejected_actions: list[dict[str, Any]] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=dict)
    oracle_results: dict[str, Any] = field(default_factory=dict)
    source_context: dict[str, Any] = field(default_factory=dict)
    current_workshop_behavior: str = ""
    uncertainties: list[str] = field(default_factory=list)
    candidate_failure_classes: list[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    mechanism_failed: str
    supporting_evidence: list[str]
    competing_explanation: str
    predicted_behavioral_change: str
    status: str = "UNRESOLVED"


@dataclass
class ModificationManifest:
    hypothesis: str
    triggering_failure: str
    mechanism_changed: str
    expected_behavioral_change: str
    possible_regressions: list[str]
    files_allowed_to_change: list[str]
    files_forbidden_to_change: list[str]


class Grow0Experiment:
    def __init__(self, repo_root: str | Path, *, config_path: str = "grow/config.json"):
        self.repo_root = Path(repo_root).resolve()
        self.config_path = normalize_relpath(config_path)
        self.config = json.loads((self.repo_root / self.config_path).read_text(encoding="utf-8"))
        self.mutable_paths = tuple(self.config["mutable_paths"])
        self.immutable_paths = tuple(self.config["immutable_paths"])
        kernel = self.config["kernel"]
        self.trigger_path = kernel["trigger_path"]
        self.transfer_path = kernel["hidden_transfer_path"]
        self.evaluator_path = kernel["evaluator_path"]
        self.promotion_path = kernel["promotion_path"]
        lineage = self.config["lineage"]
        self.ledger = AppendOnlyLedger(self.repo_root / lineage["ledger_path"])
        self.lesson_ledger = LessonLedger(self.repo_root / lineage["lesson_ledger_path"])
        self.snapshot_dir = self.repo_root / lineage["snapshot_dir"]
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.model_config = ModelConfig(**self.config["model"])
        self.trigger = json.loads((self.repo_root / self.trigger_path).read_text(encoding="utf-8"))
        self._transfer = json.loads((self.repo_root / self.transfer_path).read_text(encoding="utf-8"))

    @property
    def workshop_path(self) -> str:
        if len(self.mutable_paths) != 1:
            raise ExperimentInvalid("GROW-0 vertical slice expects exactly one mutable workshop path")
        return self.mutable_paths[0]

    def _next_candidate_id(self, parent_id: str) -> str:
        match = re.fullmatch(r"G(\d+)(?:-[A-Z]+)?", parent_id)
        if not match:
            raise ExperimentInvalid(f"unsupported parent generation id: {parent_id}")
        next_number = int(match.group(1)) + 1
        prefix = f"G{next_number}-"
        used = {
            entry.get("generation_id")
            for entry in self.ledger.entries()
            if entry.get("record_type") == "generation" and entry.get("parent_id") == parent_id
        }
        index = 0
        while True:
            n = index
            letters = ""
            while True:
                letters = chr(ord("A") + (n % 26)) + letters
                n = (n // 26) - 1
                if n < 0:
                    break
            candidate = prefix + letters
            if candidate not in used:
                return candidate
            index += 1

    def _archive_generation(
        self,
        record: GenerationRecord,
        *,
        workspace: CandidateWorkspace | None = None,
    ) -> Path:
        target = self.snapshot_dir / record.generation_id
        if target.exists():
            metadata_path = target / "generation.json"
            if metadata_path.is_file():
                existing = json.loads(metadata_path.read_text(encoding="utf-8"))
                if existing == asdict(record):
                    return target
            raise ExperimentInvalid(f"generation snapshot already exists with different contents: {record.generation_id}")
        target.mkdir(parents=True, exist_ok=False)
        (target / "generation.json").write_text(
            json.dumps(asdict(record), indent=2, sort_keys=True), encoding="utf-8"
        )
        if workspace is not None:
            for rel in self.mutable_paths:
                source = workspace.root / rel
                if not source.is_file():
                    continue
                destination = target / "workshop" / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        return target

    def freeze_g0(self, *, baseline_ref: str, prior_suite: dict[str, Any]) -> tuple[GenerationRecord, IntegritySnapshot]:
        if not prior_suite.get("passed"):
            raise ExperimentInvalid("baseline is failing required tests")
        snapshot = make_integrity_snapshot(
            repo_root=self.repo_root,
            immutable_paths=self.immutable_paths,
            benchmark_path=self.trigger_path,
            transfer_path=self.transfer_path,
            evaluator_path=self.evaluator_path,
            promotion_path=self.promotion_path,
            model_config_hash=self.model_config.config_hash,
        )
        existing = self.ledger.get_generation("G0")
        if existing is None:
            generation = GenerationRecord(
                generation_id="G0",
                parent_id=None,
                source_workshop_snapshot_hash=hash_json(hash_paths(self.repo_root, self.mutable_paths)),
                model_configuration_hash=self.model_config.config_hash,
                benchmark_bundle_id=self.config["benchmark_bundle_id"],
                creation_timestamp=utc_now(),
                validation_results={"baseline_ref": baseline_ref, "prior_suite": prior_suite},
                disposition="PROMOTED",
            )
            self.ledger.append({"record_type": "generation", **asdict(generation)})
            self._archive_generation(generation)
        else:
            if existing.get("disposition") != "PROMOTED":
                raise ExperimentInvalid("existing G0 ledger entry is not a valid frozen ancestor")
            if existing.get("model_configuration_hash") != self.model_config.config_hash:
                raise ExperimentInvalid("existing G0 model configuration does not match current lineage")
            generation = GenerationRecord(**{
                key: value for key, value in existing.items() if key != "record_type"
            })
            if not (self.snapshot_dir / "G0" / "generation.json").exists():
                self._archive_generation(generation)
        return generation, snapshot

    def build_failure_packet(self, g0_result: dict[str, Any]) -> FailurePacket:
        if g0_result.get("passed"):
            raise ExperimentInvalid("cannot create failure packet from a passing trigger case")
        case = self.trigger
        smallest = {
            "semantic_sources": ["stored", "current"],
            "presentation": "two positional candidate values with provenance erased",
        }
        return FailurePacket(
            failure_id=f"fail-{case['case_id']}",
            generation="G0",
            task_id=case["case_id"],
            observed_behavior=f"G0 returned an incorrect or unparsable active-value selection; output hash={g0_result.get('raw_output_sha256')}",
            expected_behavior="Select the value whose provenance is the current/active call, not stale stored state.",
            smallest_counterexample=smallest,
            test_results={"trigger_passed": False},
            oracle_results={"public_verdict": "FAIL"},
            source_context={
                "goal": case["goal"],
                "available_sources": ["stored_value", "current_value"],
                "surface_labels": case.get("surface_labels") or {},
            },
            current_workshop_behavior=(self.repo_root / self.workshop_path).read_text(encoding="utf-8"),
            uncertainties=["The base model may also be failing for a reason unrelated to provenance loss."],
            candidate_failure_classes=["state_provenance_loss", "instruction_following_failure"],
        )

    def diagnosis_template(self, packet: FailurePacket) -> Diagnosis:
        return Diagnosis(
            mechanism_failed="The workshop packet preserves both values but erases which value came from stored state versus the current call.",
            supporting_evidence=[
                "The run-visible source context contains distinct stored/current provenance.",
                "The model-facing packet renames both to positional candidates A/B.",
            ],
            competing_explanation="The model may understand provenance but fail strict JSON or instruction following.",
            predicted_behavioral_change="If provenance loss is causal, preserving source labels should make selection invariant to presentation order.",
            status="UNRESOLVED",
        )

    def run_probe(self, invoke_model: Callable[[str], str]) -> dict[str, Any]:
        return counterbalanced_probe(
            workshop_module=self.repo_root / self.workshop_path,
            case=self.trigger,
            invoke_model=invoke_model,
        )

    def build_modification_prompt(
        self,
        packet: FailurePacket,
        diagnosis: Diagnosis,
        probe: dict[str, Any],
        *,
        previous_rejections: list[dict[str, Any]] | None = None,
    ) -> str:
        if probe.get("status") != "DIAGNOSIS_SUPPORTED":
            raise ExperimentInvalid("diagnosis is not supported; mutation is forbidden")
        workshop_text = (self.repo_root / self.workshop_path).read_text(encoding="utf-8")
        safe_packet = asdict(packet)
        safe_packet["test_results"] = {"trigger_passed": False}
        safe_packet["oracle_results"] = {"public_verdict": "FAIL"}
        lessons = list(previous_rejections or [])
        prompt_payload = {
            "role": "Experiment Designer / Workshop Modifier",
            "objective": "Make the smallest generic workshop change justified by the supported failure diagnosis.",
            "failure_packet": safe_packet,
            "diagnosis": asdict(diagnosis),
            "probe": {
                "status": probe.get("status"),
                "stored_first_passed": (probe.get("stored_first") or {}).get("passed"),
                "current_first_passed": (probe.get("current_first") or {}).get("passed"),
            },
            "previous_rejection_lessons": lessons,
            "mutable_file": self.workshop_path,
            "mutable_file_content": workshop_text,
            "rules": [
                "Do not encode exact task values, expected constants, hidden cases, evaluator behavior, or task-specific branches.",
                "The change must still make conceptual sense if every task identifier and literal were renamed.",
                "Return JSON only: {hypothesis, mechanism_changed, expected_behavioral_change, possible_regressions, files:[{path,content}]}",
                "Only the listed mutable file may appear in files.",
            ],
        }
        prompt = stable_json(prompt_payload)
        self.assert_modification_prompt_isolated(prompt)
        return prompt

    def assert_modification_prompt_isolated(self, prompt: str) -> None:
        transfer_markers = self._sensitive_case_markers(self._transfer)
        if any(marker in prompt for marker in transfer_markers):
            raise ExperimentInvalid("hidden transfer details leaked into modification prompt")
        evaluator_text = (self.repo_root / self.evaluator_path).read_text(encoding="utf-8")
        fragments = [line.strip() for line in evaluator_text.splitlines() if len(line.strip()) > 60]
        if any(fragment in prompt for fragment in fragments[:20]):
            raise ExperimentInvalid("oracle implementation leaked into modification prompt")
        expected_literal = repr(self.trigger.get("expected_value"))
        explicit_answer_forms = [f'"expected_value":{expected_literal}', f'"expected_value": {expected_literal}']
        if any(form in prompt for form in explicit_answer_forms):
            raise ExperimentInvalid("benchmark expected answer leaked into modification prompt")

    @staticmethod
    def _parse_change_proposal(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) >= 3 else text
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip("\n")
        try:
            proposal = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExperimentInvalid(f"architectural modification response was not JSON: {exc}") from exc
        if not isinstance(proposal, dict) or not isinstance(proposal.get("files"), list):
            raise ExperimentInvalid("architectural modification response missing files list")
        return proposal

    def apply_proposal(self, workspace: CandidateWorkspace, raw: str, failure_id: str) -> ModificationManifest:
        proposal = self._parse_change_proposal(raw)
        files = proposal.get("files") or []
        if not files:
            raise ExperimentInvalid("candidate proposed no workshop change")
        for item in files:
            if not isinstance(item, dict):
                raise ExperimentInvalid("candidate file replacement must be an object")
            path = item.get("path")
            content = item.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise ExperimentInvalid("candidate file replacement requires string path/content")
            workspace.write_text(path, content)
        changed = workspace.changed_files()
        if not changed:
            raise ExperimentInvalid("candidate did not change the workshop snapshot")
        return ModificationManifest(
            hypothesis=str(proposal.get("hypothesis") or "").strip(),
            triggering_failure=failure_id,
            mechanism_changed=str(proposal.get("mechanism_changed") or "").strip(),
            expected_behavioral_change=str(proposal.get("expected_behavioral_change") or "").strip(),
            possible_regressions=[str(item) for item in proposal.get("possible_regressions") or []],
            files_allowed_to_change=list(self.mutable_paths),
            files_forbidden_to_change=list(self.immutable_paths),
        )

    @staticmethod
    def _sensitive_case_markers(case: dict[str, Any]) -> list[str]:
        markers = []
        for key in ("case_id", "expected_value", "stored_value", "current_value"):
            value = case.get(key)
            if value is not None:
                markers.append(str(value))
        for value in (case.get("surface_labels") or {}).values():
            if value:
                markers.append(str(value))
        return markers

    def anti_overfit_scan(self, workspace: CandidateWorkspace) -> dict[str, Any]:
        texts = {path: workspace.read_text(path) for path in workspace.changed_files()}
        markers = self._sensitive_case_markers(self.trigger) + self._sensitive_case_markers(self._transfer)
        return marker_scan(texts, markers)

    def validate_candidate_structure(self, workspace: CandidateWorkspace) -> dict[str, Any]:
        errors = []
        for path in workspace.changed_files():
            target = workspace.root / path
            if target.suffix == ".py":
                safety = validate_workshop_source(target.read_text(encoding="utf-8"))
                errors.extend(f"{path}: {error}" for error in safety["errors"])
        return {"passed": not errors, "errors": errors}

    def evaluate_candidate_integrity(
        self,
        workspace: CandidateWorkspace,
        snapshot: IntegritySnapshot,
    ) -> dict[str, Any]:
        ancestor = verify_ancestor_and_kernel(
            snapshot,
            repo_root=self.repo_root,
            immutable_paths=self.immutable_paths,
            benchmark_path=self.trigger_path,
            transfer_path=self.transfer_path,
            evaluator_path=self.evaluator_path,
            promotion_path=self.promotion_path,
            model_config_hash=self.model_config.config_hash,
        )
        structure = self.validate_candidate_structure(workspace)
        overfit = self.anti_overfit_scan(workspace)
        changed = workspace.changed_files()
        allowed = set(self.mutable_paths)
        diff_valid = bool(changed) and set(changed).issubset(allowed)
        checks = {
            **ancestor["checks"],
            "candidate_source_compiles": structure["passed"],
            "candidate_diff_structurally_valid": diff_valid,
            "anti_overfit_scan_passed": overfit["passed"],
            "forbidden_write_attempts_absent": not any(not item.get("allowed") for item in workspace.write_attempts),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "structure": structure,
            "overfit": overfit,
            "changed_files": changed,
        }

    def record_rejection_lesson(
        self,
        *,
        generation_id: str,
        manifest: ModificationManifest | None,
        prediction: str,
        contradicted_by: list[str],
        diagnosis_or_implementation: str,
        avoid: list[str],
    ) -> None:
        payload = {
            "record_type": "rejection_lesson",
            "generation_id": generation_id,
            "timestamp": utc_now(),
            "change": asdict(manifest) if manifest else None,
            "prediction": prediction,
            "contradicted_by": contradicted_by,
            "diagnosis_or_implementation": diagnosis_or_implementation,
            "future_candidates_should_avoid": avoid,
        }
        text = stable_json(payload)
        if any(marker in text for marker in self._sensitive_case_markers(self._transfer)):
            raise ExperimentInvalid("refusing to persist hidden transfer answer in rejection lesson")
        self.lesson_ledger.append(payload)

    def dry_run_rejection(self, *, snapshot: IntegritySnapshot) -> dict[str, Any]:
        ancestor_before = manifest_hash(tree_manifest(self.repo_root))
        result: dict[str, Any] = {"generation_id": "G1-DRY-REJECT", "disposition": None}
        with CandidateWorkspace(self.repo_root, self.mutable_paths) as workspace:
            try:
                workspace.write_text(self.transfer_path, "{}")
                result["disposition"] = "ERROR"
            except ForbiddenWriteError as exc:
                result["blocked_write"] = str(exc)
                result["disposition"] = "INVALID"
            result["ancestor_unchanged"] = manifest_hash(tree_manifest(self.repo_root)) == ancestor_before
            result["integrity"] = self.evaluate_candidate_integrity(workspace, snapshot)
        return result

    def evaluate_workshop_case(
        self,
        workshop_module: Path,
        case: dict[str, Any],
        invoke_model: Callable[[str], str],
    ) -> dict[str, Any]:
        return evaluate_case(workshop_module=workshop_module, case=case, invoke_model=invoke_model)

    def one_generation(
        self,
        *,
        snapshot: IntegritySnapshot,
        invoke_g0: Callable[[str], str],
        invoke_modifier: Callable[[str], str],
        invoke_g1: Callable[[str], str],
        prior_suite_g1: Callable[[Path], dict[str, Any]],
    ) -> dict[str, Any]:
        g0_trigger = self.evaluate_workshop_case(
            self.repo_root / self.workshop_path, self.trigger, invoke_g0
        )
        g0_transfer = self.evaluate_workshop_case(
            self.repo_root / self.workshop_path, self._transfer, invoke_g0
        )
        if g0_trigger["passed"]:
            raise ExperimentInvalid("chosen capability challenge did not demonstrate a G0 failure")

        packet = self.build_failure_packet(g0_trigger)
        diagnosis = self.diagnosis_template(packet)
        probe = self.run_probe(invoke_g0)
        diagnosis.status = probe["status"]
        if diagnosis.status != "DIAGNOSIS_SUPPORTED":
            raise ExperimentInvalid("diagnosis remains inconclusive")

        previous_lessons = self.lesson_ledger.sanitized_lessons(
            hidden_markers=self._sensitive_case_markers(self._transfer)
        )
        modifier_prompt = self.build_modification_prompt(
            packet, diagnosis, probe, previous_rejections=previous_lessons
        )
        proposal_raw = invoke_modifier(modifier_prompt)

        generation_id = self._next_candidate_id("G0")
        manifest: ModificationManifest | None = None
        with CandidateWorkspace(self.repo_root, self.mutable_paths) as workspace:
            before_hashes = workspace.before_hashes
            try:
                manifest = self.apply_proposal(workspace, proposal_raw, packet.failure_id)
            except (ExperimentInvalid, ForbiddenWriteError) as exc:
                self.record_rejection_lesson(
                    generation_id=generation_id,
                    manifest=manifest,
                    prediction="Candidate should produce a valid bounded architectural modification.",
                    contradicted_by=[str(exc)],
                    diagnosis_or_implementation="implementation",
                    avoid=["forbidden paths", "invalid modification envelopes"],
                )
                record = GenerationRecord(
                    generation_id=generation_id,
                    parent_id="G0",
                    source_workshop_snapshot_hash=hash_json(before_hashes),
                    model_configuration_hash=self.model_config.config_hash,
                    benchmark_bundle_id=self.config["benchmark_bundle_id"],
                    creation_timestamp=utc_now(),
                    triggering_failure_id=packet.failure_id,
                    before_hashes=before_hashes,
                    after_hashes=workspace.hashes(),
                    disposition="INVALID",
                    rejection_reason=str(exc),
                )
                self.ledger.append({"record_type": "generation", **asdict(record)})
                self._archive_generation(record, workspace=workspace)
                return {
                    "g0": {"trigger": g0_trigger, "transfer": g0_transfer},
                    "g1": None,
                    "failure_packet": asdict(packet),
                    "diagnosis": asdict(diagnosis),
                    "probe": probe,
                    "record": asdict(record),
                }

            integrity = self.evaluate_candidate_integrity(workspace, snapshot)
            if not integrity["passed"]:
                record = GenerationRecord(
                    generation_id=generation_id,
                    parent_id="G0",
                    source_workshop_snapshot_hash=hash_json(before_hashes),
                    model_configuration_hash=self.model_config.config_hash,
                    benchmark_bundle_id=self.config["benchmark_bundle_id"],
                    creation_timestamp=utc_now(),
                    triggering_failure_id=packet.failure_id,
                    proposed_architectural_change=asdict(manifest),
                    changed_files=workspace.changed_files(),
                    before_hashes=before_hashes,
                    after_hashes=workspace.hashes(),
                    validation_results={"integrity": integrity},
                    disposition="INVALID",
                    rejection_reason="candidate failed integrity",
                )
                self.record_rejection_lesson(
                    generation_id=generation_id,
                    manifest=manifest,
                    prediction=manifest.expected_behavioral_change,
                    contradicted_by=[key for key, value in integrity["checks"].items() if not value],
                    diagnosis_or_implementation="implementation",
                    avoid=["leakage", "forbidden writes", "syntax-invalid workshop changes"],
                )
                self.ledger.append({"record_type": "generation", **asdict(record)})
                self._archive_generation(record, workspace=workspace)
                return {
                    "g0": {"trigger": g0_trigger, "transfer": g0_transfer},
                    "g1": None,
                    "failure_packet": asdict(packet),
                    "diagnosis": asdict(diagnosis),
                    "probe": probe,
                    "record": asdict(record),
                }

            prior = prior_suite_g1(workspace.root)
            if not prior.get("passed"):
                g1_trigger = {"passed": False, "skipped": True}
                g1_transfer = {"passed": False, "skipped": True}
                mutation = {"passed": False, "skipped": True}
            else:
                candidate_module = workspace.root / self.workshop_path
                g1_trigger = self.evaluate_workshop_case(candidate_module, self.trigger, invoke_g1)
                mutation_probe = counterbalanced_probe(
                    workshop_module=candidate_module,
                    case=self.trigger,
                    invoke_model=invoke_g1,
                )
                mutation = {
                    "passed": (
                        mutation_probe["stored_first"]["passed"]
                        and mutation_probe["current_first"]["passed"]
                    ),
                    "details": mutation_probe,
                }
                g1_transfer = self.evaluate_workshop_case(candidate_module, self._transfer, invoke_g1)

            promotion = decide_promotion(
                PromotionEvidence(
                    integrity_passed=integrity["passed"],
                    prior_capabilities_preserved=bool(prior.get("passed")),
                    triggering_failure_solved=bool(g1_trigger.get("passed")),
                    mutation_checks_passed=bool(mutation.get("passed")),
                    g0_transfer_score=1 if g0_transfer.get("passed") else 0,
                    g1_transfer_score=1 if g1_transfer.get("passed") else 0,
                )
            )
            disposition = promotion["disposition"]
            rejection_reason = None if disposition == "PROMOTED" else ",".join(promotion["reasons"])
            record = GenerationRecord(
                generation_id=generation_id,
                parent_id="G0",
                source_workshop_snapshot_hash=hash_json(before_hashes),
                model_configuration_hash=self.model_config.config_hash,
                benchmark_bundle_id=self.config["benchmark_bundle_id"],
                creation_timestamp=utc_now(),
                triggering_failure_id=packet.failure_id,
                proposed_architectural_change=asdict(manifest),
                changed_files=workspace.changed_files(),
                before_hashes=before_hashes,
                after_hashes=workspace.hashes(),
                validation_results={"integrity": integrity, "trigger": g1_trigger, "mutation": mutation},
                regression_results=prior,
                transfer_results={"g0": g0_transfer, "g1": g1_transfer},
                disposition=disposition,
                rejection_reason=rejection_reason,
            )
            self.ledger.append({"record_type": "generation", **asdict(record)})
            self._archive_generation(record, workspace=workspace)
            if disposition != "PROMOTED":
                self.record_rejection_lesson(
                    generation_id=generation_id,
                    manifest=manifest,
                    prediction=manifest.expected_behavioral_change,
                    contradicted_by=list(promotion["reasons"]),
                    diagnosis_or_implementation="diagnosis_or_implementation_unresolved",
                    avoid=["repeat identical rejected architecture without new evidence"],
                )

            return {
                "g0": {"trigger": g0_trigger, "transfer": g0_transfer},
                "g1": {"trigger": g1_trigger, "transfer": g1_transfer, "prior": prior, "mutation": mutation},
                "failure_packet": asdict(packet),
                "diagnosis": asdict(diagnosis),
                "probe": probe,
                "manifest": asdict(manifest),
                "promotion": promotion,
                "record": asdict(record),
            }
