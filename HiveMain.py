# === HiveMain.py ===

import torch
from HiveMemoryAgent import MemoryAgent
from HiveLanguageAgent import LanguageAgent
from HiveVisionAgent import VisionAgent
from HiveTimeAgent import TimeAgent
from HiveBridge import HiveBridge

class HiveMain:
    def __init__(self, agents, bridge):
        self.agents = {agent.name: agent for agent in agents}
        self.bridge = bridge

    def run_cycle(self, input_data):
        # Step 1: Broadcast input to all agents
        for agent in self.agents.values():
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
        for name, data in responses.items():
            print(f"  - {name}: {data.shape if hasattr(data, 'shape') else data}")
        # Broadcast responses to memory agent, if present
        if "memory_agent" in self.agents:
            messages = []
            for name, data in responses.items():
                if name != "memory_agent" and isinstance(data, torch.Tensor):
                    messages.append((data, f"from_{name}"))
            self.agents["memory_agent"].receive_signal(messages)

    def add_agent(self, agent):
        self.agents[agent.name] = agent

    def remove_agent(self, name):
        if name in self.agents:
            del self.agents[name]

    def step(self, new_input):
        self.run_cycle(new_input)
