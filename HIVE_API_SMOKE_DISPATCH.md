# Manual Hive API infrastructure dispatcher

This workflow has only a manual `workflow_dispatch` trigger. Review and merge
the workflow to `main` before using the Actions UI. Opening or merging the PR
does not send an API request. PR CI remains model-free.

`preflight` and `prepare` check out portable reconstruction commit
`205bd9cd5e16fff7a1e0786134fac41c44d0f564` and run without a key.
`smoke` checks out the exact workflow dispatch revision and executes
`scripts/hive_api_connection_smoke.py`. It makes **one** Responses generation
request, with no input-token count request, SDK retries, fallback, tools,
candidate, verifier, or coding task. It uses a fixed public prompt, pinned
`gpt-5.4-mini-2026-03-17`, Standard service tier, `reasoning.effort=none`, and
`max_output_tokens=16` (including reasoning). The script accepts no model,
prompt, price, or request-setting override. Account access is unverified.

## Cost basis, reviewed 2026-10-07

[OpenAI's model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
lists the pinned snapshot, Responses support, `none` reasoning, $0.75 per
million input tokens, $4.50 per million output tokens, and a 10% regional
uplift. [OpenAI's API pricing](https://developers.openai.com/api/docs/pricing)
says Responses has no separate API fee when no paid tools are used. The
[service tier reference](https://developers.openai.com/api/reference/typescript/resources/responses)
says `default` requests Standard pricing. [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
prices GPT-5.6-and-later cache writes at 1.25×; this estimate includes that
uplift conservatively even though this model is earlier. The
[Fast mode guide](https://developers.openai.com/api/docs/guides/fast-mode)
explains project-level Fast defaults; the estimate also allows a 2× tier
uplift even though the request selects Standard.

The fixed JSON request is at most 512 bytes. For planning, allow **4,096
input tokens**, far above its visible text, plus the API-enforced **16 output
tokens**. With 1.25× cache-write, 1.10× regional and 2× tier allowances, the
conservative one-request calculation is
`(4096 × $0.75 × 1.25 × 1.10 × 2 + 16 × $4.50 × 1.10 × 2) / 1,000,000 = $0.0086064`.
The script checks this calculation and the price-review expiry before it can
connect. It fails closed after **2026-10-14** until the rates and assumptions
are reviewed. A failed or timed-out response is never retried.

This is a **planning bound below $0.01, not a guaranteed account billing cap**.
The API does not enforce the 4,096 input-token planning envelope before this
call, and hidden request framing or future price changes could invalidate it.
Returned usage above the envelope fails the smoke after the call; it cannot
undo a charge. Do not dispatch if an actual hard $0.01 account ceiling is
required. This isolated connection check does not qualify Hive's existing
provider, its separate count request, the full verifier gate, or a J001 run.

## Key and dispatch

The key observed in a laptop process is not automatically available on
GitHub. After reviewing this PR, create the protected GitHub environment
`hive-api-infrastructure`, configure required reviewers, and add its
`OPENAI_API_KEY` environment secret through **Settings → Environments →
hive-api-infrastructure → Environment secrets → Add secret**. A workflow
reference alone can create an unprotected environment; see
[GitHub's environment instructions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
Never put the key in a workflow input, PR, or artifact.

After separate approval to spend and dispatch, use **Actions → Hive remote API
infrastructure → Run workflow → smoke** on the reviewed revision. The job
uploads `HIVE_API_CONNECTION_SMOKE.json` even on a classified failure. It
contains only safe classification, model, service tier, usage, and planning
metadata; it contains no prompt, raw response, headers, or credential. A
connectivity PASS is infrastructure evidence only. Artifacts expire after
30 days.
