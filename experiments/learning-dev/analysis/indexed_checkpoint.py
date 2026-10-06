"""Schema-constrained, short memory handles after the observed hash-copy failure.

Content hashes remain in provenance. Models choose short handles; the controller
does not guess, repair, or replay malformed responses from the stopped study.
"""
from analysis.lesson_checkpoint import CheckpointHive, CheckpointMeter, checkpoint_tools


def indexed_tools(messages):
    offered = checkpoint_tools(messages)
    for tool in offered:
        tool["parameters"]["properties"]["memory_check"]["properties"]["memory_id"] = {
            "type": "string", "enum": ["none", "memory_1", "memory_2", "memory_3"]}
    return offered


class IndexedCheckpointMeter(CheckpointMeter):
    tool_builder = staticmethod(indexed_tools)


class IndexedCheckpointHive(CheckpointHive):
    meter_type = IndexedCheckpointMeter

    def _new_meter(self, *args, **kwargs):
        # CheckpointHive.work populates the original frozen content immediately
        # before creating its single recipient meter. Only public handles change.
        self.memory = [{**item, "id": f"memory_{i+1}"}
                       for i, item in enumerate(getattr(self, "memory", []))]
        if len(self.memory) > 3:
            raise ValueError("indexed checkpoint supports at most three memories")
        return super()._new_meter(*args, **kwargs)
