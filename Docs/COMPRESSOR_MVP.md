# Hive Compressor MVP v0.1

This is the first product shell around Hive's **tested structured-state compression idea**.

It deliberately starts with the thing we can defend today: a deterministic C1 projection of canonical semantic-ledger records.

## Hard product law

> **Human language is preserved. Machine state is compressed. Source remains recoverable.**

Hive Compressor is not a generic prose shortener. Exact human wording remains source evidence. Adapters may derive operational state from that evidence, but they must keep a stable source reference so the original wording can always be recovered.

See `Docs/COMPRESSOR_DOCTRINE.md` for the frozen boundary.

## What it does

- `POST /v1/compress` — compress structured Hive records
- `GET /v1/usage` — show usage/savings for the current API key
- `GET /v1/health` — readiness check
- source-preserving adapter contract for separating verbatim evidence from compressible machine state
- API keys are compared by SHA-256 hash; raw keys do not need server-side storage
- SQLite stores only metering numbers, not customer request content
- C1 fails closed if an unknown field would be dropped
- no new Python dependency is required beyond the repo's existing test tooling

## Data flow

```text
human message
    |
    +--> verbatim source evidence + stable ref + integrity hash
    |
    +--> adapter derives machine-state record(s)
             |
             +--> source lineage kept outside compressed state
             |
             +--> C1 compressor
                      |
                      +--> compact operating state for the next model call
```

If exact wording matters, Hive follows the source reference back to the untouched evidence instead of trusting a paraphrase.

## 1. Create a key

```bash
python -m hive_compressor.keygen
```

Copy the printed `HIVE_API_KEY_SHA256=...` into the server environment. Keep the raw `hive_...` key for the client.

## 2. Start it

```bash
export HIVE_API_KEY_SHA256=<printed hash>
python -m hive_compressor.server
```

Windows PowerShell:

```powershell
$env:HIVE_API_KEY_SHA256="<printed hash>"
python -m hive_compressor.server
```

Default address: `http://127.0.0.1:8787`.

## 3. Preserve source and derive state

The adapter API intentionally does **not** interpret human language automatically yet. It establishes the boundary that future coding-agent adapters must obey:

```python
from hive_compressor import build_adapter_packet, preserve_source

source = preserve_source(
    "msg-184",
    "Keep the old login system working for now. Don't touch auth in this patch.",
)

packet = build_adapter_packet(
    [source],
    [{
        "record": {
            "ref": "state-42",
            "effective_t": 184,
            "kind": "constraint",
            "authority": "user_instruction",
            "status": "active",
            "requires": [],
            "effects": ["do_not_modify_auth"],
        },
        "source_refs": ["msg-184"],
    }],
)
```

`packet["compression_records"]` may go to the compressor. `packet["source_evidence"]` does not get shortened or silently rewritten.

## 4. Send a compression request

```bash
curl http://127.0.0.1:8787/v1/compress \
  -H "Authorization: Bearer hive_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "mode":"c1",
    "records":[{
      "ref":"evt-1",
      "effective_t":10,
      "record_t":12,
      "kind":"fact",
      "authority":"observed",
      "status":"active",
      "requires":[],
      "effects":["door=open"]
    }]
  }'
```

The response includes the compressed records, omitted-field disclosure, byte reduction, rough provider-neutral token estimates, and latency.

## Why the input is structured records instead of arbitrary text

Hive's strongest evidence so far is about **state representation compression**: keeping semantic control fields such as time, authority, status, dependencies, and effects while omitting lower-value representation overhead. Treating any giant text blob as safely compressible would jump ahead of that evidence and violate the source-preservation doctrine.

The next product step is a real **coding-agent history adapter** that preserves human messages verbatim, derives source-linked machine state, runs Raw-vs-Hive shadow comparison, and automatically falls back when interpretation is uncertain.

## Security note

This is an MVP, not an internet-hardened deployment. Before public exposure we still need TLS termination, a real secret store/key lifecycle, rate limiting, account management, deployment isolation, and abuse controls.
