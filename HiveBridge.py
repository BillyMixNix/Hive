# === HiveBridge.py (Message-Passing Architecture) ===
import time 
import torch
import torch.nn as nn

class HiveBridge:
    def __init__(self):
        self.agent_outputs = {}  # format: {agent_name: {'vector': tensor, 'tag': str}}
        self.sent_cache = set()  # used for duplicate suppression

    
    def send(self, agent_name, vector, tag=None):
        key = (agent_name, tag, vector.sum().item())
        if key in self.sent_cache:
            return  # duplicate, skip storing
        self.sent_cache.add(key)

        self.agent_outputs[agent_name] = {
            'vector': vector,
            'tag': tag or "untagged",
            'timestamp': time.time()
        }
        

    def register_output(self, agent_name, vector, tag=None):
        self.agent_outputs[agent_name] = {
            'vector': vector,
            'tag': tag or "untagged"
        }

    def clear(self):
        self.agent_outputs = {}
        self.sent_cache.clear()

    def receive(self, agent_name):
        """
        Retrieve the last stored output for an agent.
        Returns dict with keys: vector, tag, timestamp (if present), or None.
        """
        return self.agent_outputs.get(agent_name)

    def route_to(self, target_agent_name, attention=False):
        """
        Returns a list of (vector, tag, score) tuples.
        If attention=True, uses time-based attention weighting.
        """
        routed = []
        now = time.time()
        for name, data in self.agent_outputs.items():
            if name == target_agent_name:
                continue
            vector = data['vector']
            tag = data['tag']
            timestamp = data['timestamp']
            age = now - timestamp
            score = 1.0 / (1.0 + age) if attention else 1.0
            routed.append((vector * score, tag, score))
        return routed


# === Example Agent Behavior ===
# Agent receives messages:
#   messages = hive_bridge.route_to("time_agent")
#   for vector, tag in messages:
#       do_something_with(vector, tag)

# Optional extension: scoring, attention, tagging, time-weighted memory, etc.
