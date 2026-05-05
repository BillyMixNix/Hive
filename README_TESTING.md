# Hive Testing & Stress Harness

Quick instructions to run the newly added stress and fuzz harnesses.

1) Create and activate a Python virtualenv (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Run unit tests:

```powershell
pytest -q
```

3) Generate adversarial tasks:

```powershell
python scripts\adversarial_task_generator.py
```

4) Run integration harness (concurrent sandbox tests):

```powershell
python -m tests.integration_harness
```

5) Run stress runner (fuzzed patches):

```powershell
python scripts\stress_runner.py
```

Notes:
- The harnesses use `ExecutorAgent.test_patch_in_sandbox()` to avoid touching live files.
- The test LLM is mocked in `tests/conftest.py` for deterministic reflector behavior.
