# === HiveTestMain.py ===

import torch
from HiveMain import HiveMain
from HiveBridge import HiveBridge
from HiveTimeAgent import TimeAgent
from HiveLanguageAgent import LanguageAgent
from HiveVisionAgent import VisionAgent
from HiveMemoryAgent import MemoryAgent

device = torch.device("cuda" if torch.cuda.is_available() else "cpu" )


# === Initialize Agents ===
time_agent = TimeAgent(name="time_agent")
language_agent = LanguageAgent(name="language_agent", device=device,)
vision_agent = VisionAgent(name="vision_agent", )
memory_agent = MemoryAgent(name="memory_agent", memory_size=10, device=device)

# === Initialize Bridge ===
bridge = HiveBridge()

# === Initialize Hive ===
hive = HiveMain(agents=[time_agent, language_agent, vision_agent, memory_agent], bridge=bridge)

# === Simulated Input Data ===
test_input = {
    "time_agent": torch.randn(1, 768),
    "language_agent": "What is the capital of France?",
    "vision_agent": torch.randn(1, 512),
}

# === Run Hive Cycle ===
print("[Test] Running Hive cycle with test input...")
hive.step(test_input)
for agent in hive.agents.values():
    if agent.name == "time_agent":
        agent_output = agent.process(None)  # or just agent.process()
    else:
        agent_input = test_input.get(agent.name, test_input)
        agent_output = agent.process(agent_input)
    bridge.send(agent.name, agent_output)

print("[Test] Cycle complete.")
