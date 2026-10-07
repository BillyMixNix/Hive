# Manual Hive API infrastructure dispatcher

This dispatcher makes the existing model-free infrastructure checks available
from GitHub Actions after review and merge to `main`. It checks out the exact
portable reconstruction commit `205bd9cd5e16fff7a1e0786134fac41c44d0f564`.
The only trigger is `workflow_dispatch`; opening or merging the PR does not
start it. Existing model-free PR CI may run.

`preflight` and `prepare` do not inject an API key or call a model. The `smoke`
choice **fails before credential injection or any API request**. It is retained
as an explicit blocked state so a reviewer cannot mistake a model-free check
for a live provider qualification. No coding experiment, candidate generation,
or verifier run is enabled.

The reviewed provider normally issues one
[input-token count request](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)
before reserving the generation budget. The [published OpenAI pricing](https://developers.openai.com/api/docs/pricing)
does not establish a charge ceiling for that count request. Its optional
`--max-cost-usd` bound therefore covers the generation reservation, not a
guaranteed total bill. A failed or timed-out response can also have unknown
charges. Since the approved ceiling is **$0.01 total**, this dispatcher
performs zero API requests until the total cost policy can be verified and
reviewed. An acknowledgment flag or an assumed free count request cannot
unlock it.

A later change must verify the count-request billing bound, choose and price
an exact model available to the API project, enforce the $0.01 total before
the first potentially billable request, and receive separate approval to run
the smoke. The full remote verifier gate and controlled API J001 run need
additional qualification and authorization.

For that later reviewed workflow, the intended environment is
`hive-api-infrastructure` and its secret name is `OPENAI_API_KEY`. The key
observed in a laptop process is not automatically available to GitHub. Do
not enter it in a workflow input or PR. When the cost gate is resolved, the
repository owner can configure it under **Settings → Environments →
hive-api-infrastructure → Environment secrets → Add secret**. Create the
environment and set required reviewers first; a workflow reference alone
can create an unprotected environment. See [GitHub's environment instructions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
