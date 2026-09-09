"""Opt-in, request-time state packets using the existing repair controllers.

No paid launch entry point. Raw and packet arms receive identical public state;
the lesson arm adds the caller's frozen advice through the existing memory path.
"""
from copy import deepcopy
import json
from pathlib import Path

from hive_orchestrator import snapshot_repository
from hive_learning.evaluate import candidate_snapshot, strict_json
from analysis.contract_checked_hive import ContractCheckedHive
from analysis.indexed_checkpoint import IndexedCheckpointHive, indexed_tools
from analysis.state_packet import canonical, compile_packet, digest, verify_packet


class PacketIntegration:
    def __init__(self, *args, condition, packet_observer=None, **kwargs):
        if condition not in {"raw", "lessons", "packet"}:
            raise ValueError("unknown state experiment condition")
        self.condition = condition
        self.packet_observer = packet_observer
        self.packet_records = []
        self._packet_started = False
        super().__init__(*args, **kwargs)

    def work(self, root, goal, lessons, calls, *, acceptance_oracle=None):
        if self._packet_started:
            raise ValueError("one recipient per adapter; state cannot cross recipients")
        if self.condition != "lessons" and lessons:
            raise ValueError("non-lesson arms must receive empty memory")
        self._packet_started = True
        self._packet_root = Path(root)
        self._packet_baseline = snapshot_repository(self._packet_root)
        self._packet_goal = goal
        return super().work(root, goal, lessons, calls, acceptance_oracle=acceptance_oracle)

    def _prepare_packet_messages(self, messages):
        # Controller messages and this recipient's public files only. Never read
        # final scoring results, reference patches or prior-recipient artifacts.
        initial = next(i for i, m in enumerate(messages) if m["role"] == "user")
        task = strict_json(messages[initial]["content"])
        if "hive_state_context" in task:
            raise ValueError("state context collision")
        before_tools = indexed_tools(messages)
        files = candidate_snapshot(self._packet_root, self._packet_baseline)
        events = []
        for i, message in enumerate(messages):
            if i <= initial:
                continue
            # Preserve text as attributed context, not established truth. Even
            # user-role broker feedback is not promoted by role alone.
            events.append({"id": f"message-{i}", "sequence": i,
                "kind": "claim", "status": "unverified",
                "source": f"controller-message:{i}:{message['role']}",
                "text": message["content"] or "[empty message]"})
        snapshot = {"objective": self._packet_goal, "files": files,
            "constraints": [canonical(task.get("authority", {})),
                canonical(task.get("repair_handoff", {}).get("public_input_contracts", []))],
            "allowed_actions": [t["name"] for t in before_tools],
            "events": events,
            "uncertainties": ["Message claims are not independent verification; final correctness is unknown."],
            "verification": ["Existing controller gates and the separate final evaluator remain required."]}
        packet = compile_packet(snapshot)
        verify_packet(packet, snapshot)
        content = (canonical(packet) if self.condition == "packet" else
                   json.dumps(packet, indent=2, ensure_ascii=False))
        transformed = deepcopy(messages)
        task["hive_state_context"] = content
        transformed[initial]["content"] = canonical(task)
        if indexed_tools(transformed) != before_tools:
            raise ValueError("packet changed tool schemas or authority")
        record = {"condition": self.condition, "snapshot_sha256": digest(snapshot),
            "packet": packet, "input_messages_sha256": digest(messages),
            "output_messages_sha256": digest(transformed),
            "input_bytes": len(canonical(messages).encode()),
            "output_bytes": len(canonical(transformed).encode()),
            "tools_sha256": digest(before_tools)}
        self.packet_records.append(record)
        if self.packet_observer is not None:
            self.packet_observer(deepcopy(record))
        return transformed

    def _new_meter(self, *args, **kwargs):
        meter = super()._new_meter(*args, **kwargs)
        original_worker = meter.worker
        def worker(messages):
            return original_worker(self._prepare_packet_messages(messages))
        meter.worker = worker
        return meter


class PacketContractHive(PacketIntegration, ContractCheckedHive):
    pass


class PacketIteratorHive(PacketIntegration, IndexedCheckpointHive):
    pass


def recipient_adapter(*args, condition, contracts=(), **kwargs):
    """Keep the existing iterator exception and contract gate in every arm."""
    contracts = tuple(contracts)
    if contracts:
        return PacketContractHive(*args, condition=condition, contracts=contracts, **kwargs)
    return PacketIteratorHive(*args, condition=condition, **kwargs)
