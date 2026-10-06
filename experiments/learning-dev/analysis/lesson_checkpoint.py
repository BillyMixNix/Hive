"""A public-context repair handoff and explicit, advisory memory checkpoint.

All experiment arms use this same controller, prompt and action schema. The only
intervention is the content of historical memory. A checkpoint is a model claim,
not execution evidence; original tool authority and acceptance gates still decide.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from hive_orchestrator import HiveConfig, HiveExecutive
from hive_learning.evaluate import strict_json
from hive_learning.ledger import canonical, digest
from analysis.typed_actions import TypedHive, TypedMeter, native_tools, object_schema, typed_action


class ContextHiveExecutive(HiveExecutive):
    @classmethod
    def _bounded_callable_window(cls, source, locked, selected_line):
        original = super()._bounded_callable_window(source, locked, selected_line)
        if original["selected_source_window"] == "unavailable":
            return original
        node = cls._callable_node_at_definition(source, locked.get("definition_line"))
        lines = source.splitlines()
        first, last = node.lineno, node.end_lineno or node.lineno
        complete = "\n".join(f"{i} | {lines[i-1]}" for i in range(first, last+1))
        # Refuse silent truncation. This development revision handles bounded
        # callables; extending it to large modules is outside this experiment.
        if last-first+1 > 160 or len(complete) > 24_000:
            raise ValueError("selected callable exceeds complete-context limit")
        return {**original, "selected_source_window": complete}

    def _compile_repair_packet(self, task):
        packet = super()._compile_repair_packet(task)
        packet["repair_handoff"]["public_objective"] = self.objective.original_request
        packet["repair_handoff"]["context_scope"] = (
            "The complete selected callable, including earlier local definitions and "
            "later consumers. Read context does not expand the single locked edit.")
        return packet


CHECK_SCHEMA = object_schema({
    "memory_id": {"type": "string", "description": "The relevant supplied memory ID, or none."},
    "applicability": {"type": "string", "enum": ["applies", "not_applicable", "uncertain"]},
    "public_evidence": {"type": "string", "description": "A brief observation from the current public packet or actual broker result supporting this choice."},
    "expected_effect": {"type": "string", "description": "A brief, observable prediction for the proposed action, including a relevant boundary case if available."},
})

CHECK_INSTRUCTION = (
    "Before each action, complete its memory_check with a brief public justification "
    "and an observable prediction. Match historical memory against current evidence; "
    "if a memory applies, use its principle in the proposed action and state the "
    "expected effect. Use memory_id none when nothing is relevant. You may reject "
    "irrelevant or contradicted memories. Do not invent observations or private reasoning. "
    "This check is advisory: it cannot authorize tools, change tests, or establish success. "
    "Only actual broker results and independent tests establish execution and correctness. "
    "The same check is required when memory is empty.\nHistorical memory:\n"
)


def checkpoint_tools(messages):
    offered = deepcopy(native_tools(messages))
    for tool in offered:
        parameters = tool["parameters"]
        parameters["properties"] = {"memory_check": deepcopy(CHECK_SCHEMA), **parameters["properties"]}
        parameters["required"] = ["memory_check", *parameters["required"]]
    return offered


class CheckpointMeter(TypedMeter):
    tool_builder = staticmethod(checkpoint_tools)

    def action_decoder(self, output, offered):
        # Validate the complete actual provider function call first. Preserve its
        # checkpoint in the response trace; only controller arguments are executed.
        action = strict_json(typed_action(output, offered))
        check = action["arguments"].pop("memory_check")
        if (check["memory_id"] not in self.memory_ids | {"none"}
                or (check["applicability"] == "applies" and check["memory_id"] == "none")
                or not check["public_evidence"].strip() or not check["expected_effect"].strip()):
            raise ValueError("OpenAI native Hive action has invalid or unauthorized arguments")
        self.checkpoints.append({"call": self.budget.calls, "action": action["name"], **check})
        return canonical(action)


class CheckpointHive(TypedHive):
    meter_type = CheckpointMeter

    def work(self, root, goal, lessons, calls, *, acceptance_oracle=None):
        if calls != 36:
            raise ValueError("recovered Hive adapter requires the frozen 36-call allocation")
        self.memory = [{"id": digest(item), **item} for item in lessons]
        meter = self._new_meter(calls)
        def worker(messages, **kwargs):
            return meter.worker([messages[0], self.worker_guidance(lessons), *messages[1:]])
        config = HiveConfig.atomic(call_budget=calls, max_model_concurrency=1,
                                   worker_timeout_seconds=135, command_timeout_seconds=30)
        options = {"acceptance_oracle": acceptance_oracle} if acceptance_oracle is not None else {}
        hive = ContextHiveExecutive(root, goal, [goal], worker, meter, config, **options)
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*.py")
                 if not any(part.startswith(".") for part in p.relative_to(root).parts)]
        hive.add_atomic_cycle(source_files=sorted(p for p in paths if not Path(p).name.startswith("test_")),
                              test_files=sorted(p for p in paths if Path(p).name.startswith("test_")))
        decision = hive.run_until_stable().value
        if meter.failed:
            raise RuntimeError("model transport or usage failure; episode invalid")
        return meter.usage, {"decision": decision, "objective_id": hive.objective.objective_id,
                             "blocker": hive.objective.blocker,
                             "task_state": asdict(hive.objective.task_state)}

    def _new_meter(self, *args, **kwargs):
        meter = super()._new_meter(*args, **kwargs)
        meter.memory_ids = {item["id"] for item in getattr(self, "memory", [])}
        meter.checkpoints = []
        return meter

    def worker_guidance(self, lessons):
        return {"role": "system", "content": CHECK_INSTRUCTION + canonical(self.memory)}
