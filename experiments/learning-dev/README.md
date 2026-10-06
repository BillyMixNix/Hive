# Hive Learning — development release 0.1.1

The hosted first-trial addition is described in [CLOUD_TRIAL.md](CLOUD_TRIAL.md).
Its dedicated entry point adds the $5 total guard; the generic CLI examples below
retain request limits only.

This release connects recovered Hive repair machinery to Jarvis and adds an
executable, evidence-recorded lesson learning loop. It is a separate development
line. It does not reproduce the missing current HoH experiment, its frozen arms,
or its K1/K2 lesson banks, and does not establish recursive self-improvement.

## What now runs

1. A failed Jarvis task supplies its recorded goal, error, checkpoint, and result.
2. A bounded proposer receives that failure and the existing machine lesson bank.
   It generates a candidate lesson; it never receives the validation suite.
3. The controller records the candidate before any confirmation trials.
4. Fresh recipient workspaces compare the existing bank, bank plus candidate,
   and bank plus neutral text, in an order fixed by the episode seed.
5. An independent evaluator copies each committed candidate and adds protected
   tests unavailable through the recipient's task interface. Public tests cannot
   change. Agent assertions of success do not determine the result.
6. Promotion requires all candidate-condition trigger, transfer, and retention
   cases to pass, a strict transfer improvement over the old bank, and no transfer
   improvement from neutral guidance. Invalid evaluation or transport blocks promotion.
7. Promoted real-model development lessons enter Jarvis's normal guidance, are
   returned by `/lessons`, and count toward the cockpit's learned-outcome total.
   Simulated lessons stay in a separate scope.
8. Later episodes inherit every case from earlier promoted suites as retention
   tests, including suites whose lesson has subsequently been retired.

No human writes the lesson or assigns its pass/fail verdict in a real run.
A person still selects and commits the evaluation suite and starts the bounded
episode. There is no unattended experiment scheduler or automatic paid retry.

## Run the offline demonstration

Use Python 3.10 or newer in a virtual environment outside any agent workspace.

```sh
python -m pip install .
python -m hive_learning demo
```

The demo executes a real failed Jarvis command, scripted proposal and repair
responses, nine independent test evaluations, promotion, restart, and guidance
retrieval. Its model responses and lesson are authored fixtures. Its outcome is
**integration verification only**. It uses temporary data and makes no model calls.
Simulated promotions are excluded from ordinary Jarvis guidance and its lesson view.

```sh
python -m pytest -q tests
```

The original Jarvis runtime tests are included alongside learning integration and
failure-path tests. Tests that emulate production-scope routing use temporary
databases and mocked adapters; they are not real-model measurements.

## Use the recovered Hive engine as Jarvis's worker

After installing this package, `hive-jarvis-agent` is the custom connector. Set
`JARVIS_AGENT_COMMAND_JSON` to a JSON array containing its **absolute executable
path**, then restart Jarvis. For example on Windows:

```powershell
$env:JARVIS_AGENT_COMMAND_JSON = '["C:\\HiveEnv\\Scripts\\hive-jarvis-agent.exe"]'
$env:JARVIS_AGENT_ALLOW_ENV = 'HIVE_MODEL,HIVE_OLLAMA_URL'
$env:HIVE_MODEL = 'qwen2.5-coder:7b'
$env:HIVE_OLLAMA_URL = 'http://localhost:11434/api/chat'
python -m jarvis start --open
```

Use your actual installed connector path. The default Jarvis Codex adapter remains
available when the custom-connector setting is absent. Existing mutation approvals
remain in force. The Hive connector records its decision, usage, and task-state
evidence and exits unsuccessfully when the recovered executive does not satisfy
the objective. A terminal failed task then becomes eligible for learning.

The recovered Hive adapter is a **trusted local development worker**. Its repository
tests run as local Python code; this release does not add an OS sandbox or protect
hidden tests from a hostile same-user process. Use trusted development fixtures in
an isolated environment. The lesson/evaluator separation is an interface boundary,
not a hostile-code security guarantee. Jarvis's approval gate is not a sandbox.

The connector can also use OpenAI: set `HIVE_PROVIDER=openai`, set `HIVE_MODEL`
to an exact supported model snapshot, and privately provision `OPENAI_API_KEY`
in the launching process. Add `HIVE_PROVIDER,HIVE_MODEL,OPENAI_API_KEY` to
`JARVIS_AGENT_ALLOW_ENV` (and `HIVE_MAX_OUTPUT_TOKENS` if overriding the default
4096). Each approved worker task allows at most 36 provider requests. The connector
removes the key from its environment before running repository tests. Keep any
credential file outside the worker's repository. This is still a trusted-code
workflow, not protection against a hostile same-user process.

## Run a real-model learning episode

Provide a suite following `examples/suite.development.json`. That supplied example
is intentionally seen, synthetic development material, not a held-out benchmark.
Each case includes public Python files, a public goal, and separate protected tests.
Include at least one trigger, transfer, and retention case. Distinct fixture bytes
are enforced; semantic novelty and lack of contamination require experimental design.

Commit the exact suite bytes before the proposal and retain the resulting SHA-256.
The supplied example's hash is in `examples/suite.development.sha256`.

```sh
python -m hive_learning run \
  --data /absolute/path/to/jarvis.db \
  --task FAILED_TASK_ID \
  --suite /absolute/path/to/suite.json \
  --suite-sha256 EXACT_SHA256 \
  --model PINNED_LOCAL_MODEL
```

The Ollama server must already be running with the selected model available.
No model is downloaded or invoked by installation, inspection, or the demo.
The live adapters have been checked with simulated HTTP responses. Neither has
been validated through a real provider in this build environment.

### Hosted OpenAI episode

The OpenAI adapter uses the Responses API. It needs a privately provisioned key,
an explicit total request limit, and an exact supported model snapshot. After
secure setup, an example invocation is:

```sh
python -m hive_learning run \
  --provider openai \
  --data /absolute/path/to/jarvis.db \
  --task FAILED_TASK_ID \
  --suite /absolute/path/to/suite.json \
  --suite-sha256 EXACT_SHA256 \
  --model EXACT_SUPPORTED_MODEL_SNAPSHOT \
  --env-file /absolute/private/path/to/.env.local \
  --max-requests 325 \
  --max-output-tokens 4096
```

The 325-request limit is the maximum for three cases; it is not a recommendation
to spend that budget. Include inherited cases when budgeting later episodes.
Agree on the model, current pricing, and spending allowance before a paid run.
Request limits and per-request output limits do **not** guarantee a dollar cap.
Choosing a smaller request limit can invalidate an episode before it finishes;
its suite will remain consumed. No provider calls were made to prepare this release.

The key is read from the explicitly selected env file, or from `OPENAI_API_KEY`
when `--env-file` is absent. It is never accepted on the command line or recorded
in experiment evidence. The loader removes that environment variable before
Hive runs local repository tests. No env file or credential is included in this ZIP.

Every request is stateless with `store=false`; no prior response ID or provider
tools are used. The proposer uses a strict lesson JSON schema and judges return
JSON objects. Workers use one forced native `hive_action` function call with
parallel tool calls disabled. The adapter translates its arguments into the
recovered controller's existing JSON action format; only Hive executes it and
supplies the observed result on the next turn. Text claims never execute actions.
These formats follow the [OpenAI structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs)
and [function calling guide](https://developers.openai.com/api/docs/guides/function-calling).

The recovered atomic profile also requires a deterministic acceptance checker
before it can declare completion. Python callers can supply a trusted,
goal-specific `acceptance_oracle` to `OpenAIHive.work`. Its result is measured from
the candidate; a model's assertion is not a checker. The frozen development repair
probe supplies one, retains its observations and separately grades protected tests.
See [the recorded continuations](CONTINUATIONS.md) for the current live results
and the limitations of the original learning fixtures.
The adapter handles reasoning items before the assistant's text, as described in
the [text generation guide](https://developers.openai.com/api/docs/guides/text).

The requested model must match the provider's returned model identifier exactly;
aliases that resolve to another identifier invalidate the episode. Requests have a
250 KB input limit and bounded output. Errors, refusals, missing usage, truncated
responses, or nonconforming JSON stop further provider calls and block promotion.
Measured usage from incomplete responses is retained when available; a network
failure can leave billable usage unknown. There are no automatic retries, redirects,
or substitute models. The episode seed orders trials only; OpenAI calls are not
claimed to be deterministic.

Each real recipient gets the recovered 36-call responsibility allocation; the
proposer gets one call. For N new plus inherited cases, the maximum is
`1 + 3 * N * 36` model requests (325 for the three-case example). Calls, provider
prompt/output token counts, and incomplete transport usage are recorded. The
transport has no hidden retry. Every recipient is a new executive, while judge
calls share its total budget. Judges do not receive lesson guidance.

Neutral guidance is padded to the candidate's character count. This is a limited
control, not token equality or proof that semantic content caused the difference.
One episode is preliminary development evidence. Establishing a reliable effect
requires prospectively specified repeats, stronger controls, uncontaminated tasks,
and all-in resource comparisons. Improving the policy that produces lessons is
a further stage; this release does not implement or demonstrate that recursion.

## Persistence, rejection, and rollback

Learning events use Jarvis's existing SQLite transaction and anchored hash chain.
Candidate bytes, suite bytes, hashes, schedule, metering, evaluation decisions,
and implementation hashes are retained. Machine promotion never fabricates a
human `OUTCOME_RECORDED` event. A tampered chain blocks lesson reuse.

An episode consumes its suite before the first provider call. Rejection and
failure do not allow replay of that suite under a new episode ID. A process crash
leaves an unfinished episode and blocks another episode on that database until
explicit adjudication. Automated crash resumption/adjudication is intentionally
not implemented; preserve the database rather than deleting the consumption record.

Only one learning episode can be active per database. The final parent-bank check
is transactional. Retiring a parent lesson during a run invalidates that run.
Limits of 19 active lessons, 60 KB guidance, and 36 combined cases fail explicitly
instead of silently deleting retained knowledge or tests.

To stop a promoted lesson from guiding later tasks while preserving its evidence:

```sh
python -m hive_learning retire --data /absolute/path/to/jarvis.db \
  --episode EPISODE_ID --reason "Observed regression; investigating"
```

Retirement does not undo edits already made by an agent. The ledger detects
accidental or partial alteration; an administrator able to rewrite the complete
database and anchor remains outside its authentication guarantees.

## Recovered foundations

- Jarvis v0.3 from the supplied `Hive-Jarvis-v0.3.zip`; original instructions are
  preserved in `JARVIS_V03_README.md`.
- `hive_orchestrator.py` and `local_agent.py` from `local-agent-test.zip`.
  The recovered controller is unchanged, SHA-256
  `c879b5f236b321f03660c21c466530156ba6cc53e8bca488342737ab8b7031e8`.
- New integration is under `hive_learning/`, with small Jarvis store changes for
  verified lesson retrieval and visibility. Original frozen research artifacts
  and source uploads have not been modified.

This package is sufficient to run and inspect the development loop. It is not an
always-on hosted deployment, and no actual learned lesson is bundled as verified.
