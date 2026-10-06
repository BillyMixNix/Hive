# Persistent Agents backend (experimental)

Hive can now use OpenAI Managed Agents as an execution backend while retaining Hive's planner/worker contracts, deterministic edit validation, verification, review, and promotion gates.

POST `/api/hive/build` with the existing cloud opt-in plus:

```json
{
  "request": "your build request",
  "allow_cloud": true,
  "agent_backend": "persistent",
  "persistent_agent_model": "gpt-6-astra"
}
```

`agent_backend` defaults to `classic`, so existing local Ollama/cloud-escalation behavior is unchanged.

The persistent backend creates one Managed Agents session per Hive role and reuses that role session for correction, repair, and replan calls during the build. The managed agent is deliberately not granted promotion authority; its output returns through the existing Hive gates.

Requirements: an OpenAI API key configured through the existing Workshop mechanism and Agents API access for the selected model. Managed-agent usage is cloud usage. The existing `max_cost` admission estimator currently applies to the classic Responses API escalation path, not Managed Agents; use this backend only with an intentional cloud budget while the experiment is being characterized.

Recommended experiment: replay the frozen GENERALIZATION-003–010 tasks under `classic` and `persistent` conditions without changing acceptance criteria, then compare completion rate, dropped obligations, repairs, wall time, and token usage.
