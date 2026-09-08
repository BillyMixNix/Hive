# Hive API access from GitHub

This check provides a credential path when the OpenAI Developers connector cannot
provision a key. The repository owner enters their own key directly into a GitHub
Actions secret. Chat and source files never receive the key.

The workflow performs one authenticated `GET /v1/models` request. It does not
generate model output, run a learning episode, or charge the approved $5 model
trial budget. It does not verify inference permissions, available API credits, or
Hive learning performance.

## Set up from a phone

1. Create a project API key in your own [OpenAI API key settings](https://platform.openai.com/api-keys).
   Keep its value private.
2. Open [Hive's Actions secrets](https://github.com/BillyMixNix/Hive/settings/secrets/actions).
   Select **New repository secret**.
3. Name the secret `HIVE_OPENAI_API_KEY`. Enter the key value only in GitHub's
   **Secret** field and select **Add secret**. Do not put it in a repository file,
   workflow input, issue, pull request, or chat.
4. Return to the existing **Hive API Access Check** run and select **Re-run jobs**,
   or ask the connected coding agent to rerun its failed job.

The initial branch push creates a visible run. If the secret is absent, that run
stops with `KEY_REQUIRED` before any OpenAI request. Re-running it after adding the
secret checks access using the same committed workflow. The manual **Run workflow**
button is available only after GitHub registers this dispatch workflow from the
default branch; merging is not needed to rerun the existing branch-push run.

## What runs

- A standard `ubuntu-24.04` GitHub-hosted runner, with a two-minute job timeout.
- A single inline Python script, using the standard library. No repository
  checkout, dependency installation, external action, or agent-generated code.
- The key is passed only to this step and removed from the process environment
  before the request. The bearer credential is sent only to the fixed OpenAI URL.
- Redirects and automatic retries are disabled. Reports include only a fixed
  status, HTTP status when available, and the number of listed models on success.
  Neither response bodies nor exception text are logged on failure.
- The workflow has no GitHub token permissions and does not run for pull requests.

`AUTHENTICATED` proves only that the supplied credential could list models from
this runner. A later inference attempt still needs metered spending controls and
the development learning protocol. All paid attempts must fit the user's existing
$5 total allowance; rerunning this access check does not authorize a new budget.

The earlier connector returned generic Platform rejections both before and after
reconnection. That does not identify the cause or establish that billing, the
account, or the user's setup is at fault.

References:

- [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [OpenAI model-listing endpoint](https://developers.openai.com/api/reference/resources/models/methods/list)
- [GitHub standard runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

GitHub documents standard hosted runner usage as free for public repositories.
This workflow uses that runner class and creates no artifacts or caches.
