# Hive Compressor MVP v0.2

This is the first product shell around Hive's **tested structured-state compression idea**.

It deliberately starts with the thing we can defend today: a deterministic C1 projection of canonical semantic-ledger records.

## Hard product law

> **Human language is preserved. Machine state is compressed. Source remains recoverable.**

Hive Compressor is not a generic prose shortener. Exact human wording remains source evidence. Adapters may derive operational state from that evidence, but they must keep a stable source reference so the original wording can always be recovered.

See `Docs/COMPRESSOR_DOCTRINE.md` for the frozen boundary.

## What it does

- `POST /v1/compress` — compress already-structured Hive records
- `POST /v1/adapt/coding` — turn coding-agent history into source-linked machine state, then compress only that state
- `GET /v1/usage` — show usage/savings for the current API key
- `GET /v1/health` — readiness check
- exact human messages are preserved separately from machine state
- the newest human message is always kept verbatim in the next model context
- older human messages leave repeated context only when structured directives clear the confidence gate
- unknown, malformed, or low-confidence events fall back to verbatim source evidence
- machine tool output can be huge without being copied into the compressed state
- Raw-vs-Hive byte shadow measurements are returned without making a quality claim
- API keys are compared by SHA-256 hash; raw keys do not need server-side storage
- SQLite stores only metering numbers, not customer request content
- C1 fails closed if an unknown field would be dropped

## Data flow

```text
coding-agent history
    |
    +--> human messages: preserve exact text
    |
    +--> machine events: preserve recoverable evidence
    |
    +--> derive operational state records
             |
             +--> confidence / schema gate
             |       |
             |       +--> uncertain? keep source verbatim in model context
             |
             +--> source lineage
             |
             +--> C1 compressor
                      |
                      +--> latest human message verbatim
                      +--> compact machine state
                      +--> only fallback evidence that still matters
```

The adapter does **not** shorten human prose. A human message is only removable from repeated context after a structured interpretation exists; even then the original text remains recoverable as evidence.

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

## 3. Send coding-agent history

The coding adapter accepts normalized events. Machine events are interpreted deterministically. Human messages can include structured `directives` supplied by the coding-agent integration's interpretation step.

```bash
curl http://127.0.0.1:8787/v1/adapt/coding \
  -H "Authorization: Bearer hive_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "mode":"c1",
    "min_confidence":0.90,
    "events":[
      {
        "id":"msg-1",
        "kind":"human_message",
        "text":"Keep auth untouched until checkout passes.",
        "directives":[{
          "kind":"constraint",
          "confidence":0.99,
          "effects":{"op":"set","path":"auth.change_allowed","value":false}
        }]
      },
      {
        "id":"test-1",
        "kind":"test_run",
        "suite":"checkout",
        "passed":18,
        "failed":0
      }
    ]
  }'
```

The response contains:

- `source_evidence` — exact recoverable evidence and integrity hashes
- `lineage` — which source(s) justify each machine-state record
- `compression` — C1 output and state-size statistics
- `model_context.verbatim_sources` — newest human message plus any evidence Hive is not safe to omit
- `model_context.compressed_state` — machine state eligible to send repeatedly
- `fallback` — whether anything was retained verbatim because interpretation was uncertain
- `shadow` — Raw-vs-Hive byte comparison, explicitly marked as size-only until task quality is measured

## Supported coding-agent events

`human_message`, `tool_call`, `tool_result`, `file_change`, `test_run`, `plan`, `decision`, `failure`, and `status`.

Large raw tool output remains in evidence and is not copied into compressed state. Unknown event kinds are not guessed; they remain fallback evidence.

## Human directives

Hive itself does not use regexes to pretend it understands arbitrary human prose. The adapter accepts a structured sidecar from the agent's interpretation step:

```json
{
  "kind": "human_message",
  "text": "Start the OAuth migration now.",
  "directives": [
    {
      "kind": "task",
      "status": "active",
      "confidence": 0.98,
      "effects": {
        "op": "set",
        "path": "task.current",
        "value": "oauth_migration"
      }
    }
  ]
}
```

If confidence is below the configured gate, that directive does not become machine truth and the original human message stays verbatim in model context.

## Direct structured compression

`POST /v1/compress` remains available when the caller already has canonical Hive records.

## Security note

This is an MVP, not an internet-hardened deployment. Before public exposure we still need TLS termination, a real secret store/key lifecycle, rate limiting, account management, deployment isolation, and abuse controls.

## Next engineering gate

Run this adapter against real coding-agent traces and perform **paired Raw-vs-Hive task execution**, not just byte comparison. Promotion requires evidence that the compact state preserves task quality while reducing supplied context/cost. Until then, `shadow.quality_status` remains `not_measured`.
