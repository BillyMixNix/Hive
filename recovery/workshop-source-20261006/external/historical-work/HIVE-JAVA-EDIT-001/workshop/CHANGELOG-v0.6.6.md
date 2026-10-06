# Nix Workshop v0.6.6

Local Qwen generation timeout and liveness hotfix. Ollama chat now allows up to 900 seconds of inactivity-free generation and reads the streaming response incrementally, so active token output keeps a slow request alive. A retry is attempted only for a true transport stall or retryable provider failure. Cloud/API timeout behavior and all safety, routing, budget, approval, verification, and apply gates are unchanged.
