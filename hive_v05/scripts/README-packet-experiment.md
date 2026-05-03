Packet Experiment
-----------------

Run `packet_experiment.py` to compare packetized prompting vs legacy prompting for one representative Hive task.

Requirements:
- A working LLM endpoint configured for `hive_llm.ask_model()` (e.g., Ollama or OpenAI with the project configuration).
- Python dependencies: see project venv (install `requests` if missing).

Run:
```bash
python scripts/packet_experiment.py
```

Output:
- `experiment_result.json` in repo root with the runs and simple metrics.

If your LLM endpoint is not running, the script will record the error messages in the JSON output for diagnosis.
