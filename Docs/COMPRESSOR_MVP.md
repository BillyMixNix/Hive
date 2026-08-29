# Hive Compressor MVP v0.1

This is the first product shell around Hive's **tested structured-state compression idea**.

It deliberately starts with the thing we can defend today: a deterministic C1 projection of canonical semantic-ledger records. It does **not** claim to safely compress arbitrary free-form prompts yet.

## What it does

- `POST /v1/compress` — compress structured Hive records
- `GET /v1/usage` — show usage/savings for the current API key
- `GET /v1/health` — readiness check
- API keys are compared by SHA-256 hash; raw keys do not need server-side storage
- SQLite stores only metering numbers, not customer request content
- C1 fails closed if an unknown field would be dropped
- no new Python dependency is required beyond the repo's existing test tooling

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

## 3. Send a compression request

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

Hive's strongest evidence so far is about **state representation compression**: keeping semantic control fields such as time, authority, status, dependencies, and effects while omitting lower-value representation overhead. Treating any giant text blob as safely compressible would jump ahead of that evidence.

The next product step is an **adapter** that turns real coding-agent history into these canonical records, with Raw-vs-Hive comparison and automatic fallback when the adapter is uncertain.

## Security note

This is an MVP, not an internet-hardened deployment. Before public exposure we still need TLS termination, a real secret store/key lifecycle, rate limiting, account management, deployment isolation, and abuse controls.
