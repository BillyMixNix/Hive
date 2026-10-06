# HIVE-LOCAL-001 capability inventory (pre-execution)

- Ollama: 0.34.0; local-only endpoint `127.0.0.1:11434`.
- Selected installed model: `qwen2.5-coder:14b`, digest
  `9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849`,
  Q4_K_M, 14.8B parameters, model context limit 32,768.
- Non-benchmark smoke: `LOCAL_SMOKE_OK`, HTTP 200, 58.835 seconds including
  55.774 seconds loading; six generated tokens. No download occurred.
- Loaded Ollama runtime reported 32,768 context and 73% CPU / 27% GPU.
- Host: Acer Nitro AN515-54, eight logical CPUs, 17,009,004,544 bytes RAM;
  NVIDIA GeForce RTX 2060, 6,144 MiB VRAM, driver 610.47.
- C: free space at inventory: approximately 12.26 GB. The task preflight
  requires at least 8 GiB free and will stop if that bound is crossed.
- Workshop local Hive generation: temperature 0.1, structured Ollama JSON,
  no seed, no explicit `num_ctx` override, 900-second total generation limit,
  per-role `num_predict`: planner 2048; UI/backend/tests 6000; reviewer 1536.
- This is a known-task local characterization, not an unseen challenge set
  or a continuation of HIVE-ASTRA-001/002.
