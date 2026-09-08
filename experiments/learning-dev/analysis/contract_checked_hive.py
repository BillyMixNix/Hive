"""Opt-in public contract enforcement after the completed lesson experiment.

The frozen experiment adapters remain unchanged. This adapter is ready for a
future, separately specified run; importing it makes no provider request.
"""
from dataclasses import asdict
from pathlib import Path

from hive_orchestrator import HiveConfig, snapshot_repository
from hive_learning.ledger import canonical, digest
from analysis.indexed_checkpoint import IndexedCheckpointHive
from analysis.lesson_checkpoint import ContextHiveExecutive
from analysis.public_contracts import PublicContractGate


class ContractCheckedExecutive(ContextHiveExecutive):
    def __init__(self, *args, public_contract_gate, acceptance_oracle=None, **kwargs):
        if type(public_contract_gate) is not PublicContractGate:
            raise ValueError("an explicit controller-owned public contract gate is required")
        self.public_contract_gate = public_contract_gate
        self.public_contract_reports = []
        self._additional_acceptance = acceptance_oracle
        super().__init__(*args, acceptance_oracle=self._checked_acceptance, **kwargs)
        if self.objective.baseline_snapshot != self.public_contract_gate.baseline:
            raise ValueError("contract baseline differs from the objective baseline")

    def _payload(self):
        return {**super()._payload(), "public_contract_policy": self.public_contract_gate.policy,
                "public_contract_policy_sha256": self.public_contract_gate.policy_sha256}

    def _restore(self, data):
        if (data.get("public_contract_policy_sha256") != self.public_contract_gate.policy_sha256
                or data.get("public_contract_policy") != self.public_contract_gate.policy):
            raise ValueError("resume requires the original public contract policy and baseline")
        super()._restore(data)

    @classmethod
    def resume(cls, root, objective_id, *, public_contract_gate, **kwargs):
        return cls(root=root, objective_id=objective_id, public_contract_gate=public_contract_gate, **kwargs)

    def _check_contracts(self, workspace):
        report = self.public_contract_gate.check(workspace)
        self.public_contract_reports.append(report)
        self.store.trace("public_contract_checked", **report)
        return report

    @staticmethod
    def _feedback(report):
        violations = [{"source_file": c["contract"]["source_file"],
                       "symbol": c["contract"]["symbol"], **v}
                      for c in report.get("checks", []) for v in c["violations"]]
        return canonical({"status": report["status"], "candidate_sha256": report.get("candidate_sha256"),
                          "observed_calls": report["observed_calls"], "violations": violations[:1],
                          "error_code": report.get("error_code"),
                          "instruction": "Preserve the declared caller arguments. A missing or incomplete check cannot establish completion."})

    def _checked_acceptance(self, workspace):
        report = self._check_contracts(workspace)
        if not report["accepted"]:
            # A failing public test or incomplete observation does not establish
            # an input mutation or a new callable-level behavioral counterexample.
            # The repair gate and review snapshot carry the actual measured report.
            return False
        if self._additional_acceptance is None:
            return True
        # Preserve the caller's separate acceptance oracle and its original feedback.
        return self._additional_acceptance(workspace)

    def _verify_repair(self, current_snapshot, run, require_source_edit=True):
        passed, output = super()._verify_repair(current_snapshot, run, require_source_edit)
        if not passed:
            return passed, output
        report = self._check_contracts(self.root)
        expected = digest({p: current_snapshot.get(p) for p in self.public_contract_gate.baseline})
        if not report["accepted"] or report["candidate_sha256"] != expected:
            state = self.objective.task_state
            state.source_repaired = False
            state.review_pass = False
            state.acceptance_oracle_pass = False
            # This gate rolls back the bad proposal to the accepted regression.
            # Do not freeze a contract-breaking patch as a successful partial repair.
            self._gate_failure("source_repaired", "Public input contract failed: " + self._feedback(report))
        return passed, output

    def _compile_repair_packet(self, task):
        packet = super()._compile_repair_packet(task)
        packet["repair_handoff"]["public_input_contracts"] = self.public_contract_gate.policy["contracts"]
        return packet

    def _compile_reviewer_packet(self, task, packet):
        result = super()._compile_reviewer_packet(task, packet)
        result["public_objective"] = self.objective.original_request
        result["public_input_contracts"] = self.public_contract_gate.policy["contracts"]
        result["instruction"] += " Evaluate the changed tokens against the public objective and input contracts included in review_snapshot."
        return result

    def _review_snapshot(self):
        snapshot = super()._review_snapshot()
        report = self._check_contracts(self.root)
        return ("PUBLIC OBJECTIVE:\n" + self.objective.original_request
                + "\nPUBLIC INPUT CONTRACTS:\n" + canonical(self.public_contract_gate.policy["contracts"])
                + "\n" + snapshot + "\nPUBLIC CONTRACT CHECK:\n" + self._feedback(report))


class ContractCheckedHive(IndexedCheckpointHive):
    """The normal 36-call adapter with mandatory, explicitly supplied contracts."""
    def __init__(self, *args, contracts, contract_timeout=10, **kwargs):
        self.contracts = tuple(contracts)
        self.contract_timeout = contract_timeout
        super().__init__(*args, **kwargs)

    def work(self, root, goal, lessons, calls, *, acceptance_oracle=None):
        if calls != 36:
            raise ValueError("recovered Hive adapter requires the frozen 36-call allocation")
        root = Path(root)
        gate = PublicContractGate(snapshot_repository(root), self.contracts, timeout=self.contract_timeout)
        self.memory = [{"id": digest(item), **item} for item in lessons]
        meter = self._new_meter(calls)

        def worker(messages, **kwargs):
            return meter.worker([messages[0], self.worker_guidance(lessons), *messages[1:]])

        config = HiveConfig.atomic(call_budget=calls, max_model_concurrency=1,
                                   worker_timeout_seconds=135, command_timeout_seconds=30)
        hive = ContractCheckedExecutive(root, goal, [goal], worker, meter, config,
            public_contract_gate=gate, acceptance_oracle=acceptance_oracle)
        paths = sorted(gate.baseline)
        hive.add_atomic_cycle(source_files=[p for p in paths if not Path(p).name.startswith("test_")],
                              test_files=[p for p in paths if Path(p).name.startswith("test_")])
        decision = hive.run_until_stable().value
        if meter.failed:
            raise RuntimeError("model transport or usage failure; episode invalid")
        return meter.usage, {"decision": decision, "objective_id": hive.objective.objective_id,
                            "blocker": hive.objective.blocker, "task_state": asdict(hive.objective.task_state),
                            "public_contract_policy_sha256": gate.policy_sha256,
                            "public_contract_checks": hive.public_contract_reports}
