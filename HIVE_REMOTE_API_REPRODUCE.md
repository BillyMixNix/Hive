# Initiate and inspect remote Hive infrastructure

## What can run now

The new provider and runner use Python's standard library. They require no local Ollama installation, GPU or large model. The supplied workflow can execute provider smoke, preflight and task preparation on GitHub without your computer remaining on. A real Hive coding task remains blocked because the historical apparatus cannot currently be reproduced remotely.

The workflow has only `workflow_dispatch`; no push, PR, timer or replicated experiment trigger was added. GitHub requires a dispatch workflow on the default branch before it appears in the Actions interface. This implementation is published on a separate branch; **it does not merge or change `main`**. First review the branch and arrange the infrastructure workflow on the default branch, or invoke the CLI on your chosen remote host. The default branch's existing CI is not this apparatus and does not qualify it.

## One API connection test through GitHub

1. Review the exact remote API branch commit and the workflow. Make the manual infrastructure workflow available on the default branch through your normal review process.
2. Configure the protected GitHub environment `hive-api-infrastructure` and its platform secret `OPENAI_API_KEY`, using a credential managed through the secure OpenAI Platform flow. No key value is needed by this chat or in the repository. Account/model access is not established by this implementation.
3. Open **Actions → Hive remote API infrastructure → Run workflow**. Select the remote API branch and enter its exact reviewed 40-character commit.
4. Choose `smoke`, provide an exact Responses-compatible model ID your API project can access, and leave the output cap at 32. Provide reasoning effort only if that model supports it; reasoning may consume the cap and produce an incomplete response. No model is selected automatically. One generation plus one count request is attempted; no retries or fallback occur.
5. Open that run's **Artifacts** and download `hive-remote-api-<run-id>-<attempt>`. Inspect `HIVE_REMOTE_API_SMOKE.json`, `provider/budget.json`, `provider/call-0001/`, `run-identity.json`, `outcome.json` and `evidence-index.json`. A PASS is infrastructure evidence only.

After setup, those steps can be performed from a browser/phone. The local computer does not run inference or the workflow. Artifacts expire after 30 days: download them or arrange approved persistent archival before expiry. Failed/blocked jobs also upload their evidence; a red preflight job is expected while qualification is unavailable.

Optional GitHub CLI dispatch, after workflow availability and platform secret setup:

```bash
gh workflow run hive-remote-api.yml --repo BillyMixNix/Hive \
  --ref remote/hive-api-qualification \
  -f commit=<exact-reviewed-40-character-commit> \
  -f mode=smoke -f model=<exact-supported-model-id>
gh run list --repo BillyMixNix/Hive --workflow hive-remote-api.yml
gh run download <run-id> --repo BillyMixNix/Hive \
  --name hive-remote-api-<run-id>-<attempt> --dir ./hive-api-evidence
```

The angle-bracket values are placeholders to replace, not literal shell commands. `gh` is optional; the Actions UI is sufficient.

## Remote CLI without GitHub Actions

On a trusted disposable remote host, with Python 3.12+ and Git, clone the public repository and checkout the exact reviewed commit. Do not configure a key until the infrastructure smoke needs it. Use output storage outside the checkout. With `HIVE_COMMIT` set to the reviewed commit:

```bash
git clone https://github.com/BillyMixNix/Hive.git
cd Hive
git checkout --detach "$HIVE_COMMIT"
python3 -B -m hive_remote.runner preflight \
  --expected-commit "$HIVE_COMMIT" --output-root /srv/hive-evidence
python3 -B -m hive_remote.runner prepare \
  --expected-commit "$HIVE_COMMIT" --output-root /srv/hive-evidence
```

Each invocation creates a unique external evidence directory. Exit code 2 means blocked or failed infrastructure, never coding failure. `prepare` writes `J001-PREPARED.json` without hidden test contents or model calls. On a host where the platform injects the API key only into the smoke process, use `smoke --model <supported-model-id>` with the same commit/output arguments. No setup script writes a key to disk.

An optional `--environment-root <sealed-relocation-root>` asks preflight to verify the old inventory and all 4,873 layout files. Supply it only after resolving transfer rights and authorized staging. This is hash-verified relocation, not independent acquisition. It cannot make the launch gate pass. Do not build a replacement image or redownload newer dependencies and describe them as byte-identical. No paid VM provisioning or artifact transfer is performed by this change.

## First real API-backed J001 experiment

There is currently **no command that launches a real coding run**. `experiment` fails before loading a key, staging a candidate, calling a model or claiming RECOVERY-002. Do not bypass it by calling the controller manually on an unqualified cloud host.

The smallest remaining setup sequence is:

1. Resolve whether the exact host-local image/cache/NFRT artifacts may be transferred. Obtain verified approved bytes through an authorized source, or stop. If independent reconstruction produces different bytes, create and label a separate functional-reconstruction apparatus.
2. On the chosen remote host, seal Python/interpreter/stdlib/import-path/dependency hashes, image ID, full cache layout/payload hashes, NFRT provenance, Java, Gradle, source/test/task identities, network policy and build inputs. Preserve separate evidence for each component.
3. Run model-free unchanged J001 baseline control: three frozen cases, expected one failure, no timeout under the same 240-second targeted deadline. Then reproduce the unchanged full gate against a provenance-bound known-good control candidate under the existing limits. Perform live secret-isolation and cancellation probes. A baseline failure alone does not qualify a verifier.
4. Review a new **remote/API contract** that binds those observed identities, source-only scope, safe diagnostics, no promotion, permitted run root, one-run cardinality, explicit budget and persistent claim. Implement its qualified launcher without altering historical recovery evidence. The current provider slots directly into the controller's existing callable boundary.
5. Complete the tiny real API smoke and inspect usage/model/request IDs. Freeze a supported model snapshot and experiment configuration.
6. Separately authorize exactly one controlled **remote J001 API** run at that contract and exact commit. No RECOVERY-002 authorization is reused. The prepared plan's budget is a proposal only; freeze the same budgets for both future local and API comparison arms.

Only after those steps should a launcher allow coding execution. Candidate diff, changed-file scope, targeted/full evidence and candidate hash must be preserved along with provider and environment evidence. No production promotion is part of this sequence.

## Offline checks

Provider-only tests need no third-party packages:

```bash
python3 -B -m unittest discover -s tests/remote_api -p test_provider.py -v
```

For all new tests plus the recovery suite, use an isolated test environment with pytest, requests, PyYAML, httpx, fastapi and jsonschema, then run:

```bash
python -B -m pytest -q tests/remote_api tests/recovery
python -B recovery/rc1-replay/verify_source.py verify
```

Test dependency installation is not an attested remote runtime. One historical Windows-Python error-message assertion fails on this Linux apparatus. The historical source-verification command also fails because Windows and Linux sort two groups of manifest paths differently; the file identities themselves match. Both failures reproduce at the untouched recovery anchor. See the qualification report. Neither historical result is overwritten or treated as a passing gate.
