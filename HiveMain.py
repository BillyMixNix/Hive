# === HiveMain.py ===

import time
import torch
from HiveBridge import HiveBridge
from HiveRouter import HiveRouter, RoutedDecision
from HiveReasoningHeads import ReasoningHead, Opinion

class HiveMain:
    def __init__(self, agents, bridge, reasoning_heads=None, router=None):
        self.agents = {agent.name: agent for agent in agents}
        self.bridge = bridge
        self.reasoning_heads = reasoning_heads or []
        self.router = router or HiveRouter()
        self.last_opinions = []
        self.last_decision = None

    def run_cycle(self, input_data):
        # Step 1: Broadcast input to all agents
        for agent in self.agents.values():
            if agent.name == "memory_agent":
                continue  # memory agent is passive; skip active processing
            agent_input = input_data.get(agent.name, input_data)
            agent_output = agent.process(agent_input)
            self.bridge.send(agent.name, agent_output)

        # Step 2: Collect responses from agents (if needed)
        responses = {}
        for name in self.agents:
            responses[name] = self.bridge.receive(name)

        # Optional: Handle coordination logic, conflicts, or reasoning steps
        self.coordination_logic(responses)

    def coordination_logic(self, responses):
        # Placeholder for custom multi-agent reasoning, arbitration, etc.
        print("[HiveMain] Responses received:")
        agent_vectors = {}
        for name, data in responses.items():
            vec = data["vector"] if isinstance(data, dict) and "vector" in data else data
            if vec is not None:
                agent_vectors[name] = vec
            shape = vec.shape if hasattr(vec, "shape") else vec
            print(f"  - {name}: {shape}")

        # Broadcast responses to memory agent, if present
        if "memory_agent" in self.agents:
            messages = []
            for name, data in responses.items():
                if name != "memory_agent" and isinstance(data, dict):
                    vec = data.get("vector")
                    if isinstance(vec, torch.Tensor):
                        messages.append((vec, f"from_{name}"))
            self.agents["memory_agent"].receive_signal(messages)

        # Run reasoning heads -> opinions
        if self.reasoning_heads:
            state = {
                "agent_vectors": agent_vectors,
                "timestamp": time.time(),
                "reference_time": time.time(),
            }
            if "language_agent" in agent_vectors:
                state["current_vector"] = agent_vectors["language_agent"]
            elif agent_vectors:
                # fallback to any available vector
                state["current_vector"] = next(iter(agent_vectors.values()))

            # attach memory for novelty
            if "memory_agent" in self.agents:
                mem = getattr(self.agents["memory_agent"], "memory", [])
                state["memory_vectors"] = [v for v, _ in mem]

            opinions = []
            for head in self.reasoning_heads:
                try:
                    opinions.append(head.evaluate(state))
                except Exception as e:
                    print(f"[HiveMain] Head {head.name} failed: {e}")

            decision: RoutedDecision = self.router.select(opinions)
            self.last_opinions = opinions
            self.last_decision = decision
            self._report_decision(decision)

    def add_agent(self, agent):
        self.agents[agent.name] = agent

    def remove_agent(self, name):
        if name in self.agents:
            del self.agents[name]

    def step(self, new_input):
        self.run_cycle(new_input)

    def _report_decision(self, decision: RoutedDecision):
        if decision.abstain:
            print(f"[HiveRouter] Abstain: reason={decision.reason}, confidence={decision.confidence:.3f}")
        else:
            print(
                f"[HiveRouter] Routed to '{decision.source}' "
                f"score={decision.score:.3f} conf={decision.confidence:.3f}"
            )
