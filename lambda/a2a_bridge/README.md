# a2a_bridge Lambda

Terminates incoming [A2A protocol](https://a2a-protocol.org) traffic in front of the
Bedrock AgentCore Runtime that hosts the SCF Compliance Agent. **Submit only** — it does
not call the runtime. `message/send` writes a `submitted` Task and enqueues it on SQS; the
[`a2a_worker`](../a2a_worker/) Lambda runs the agent out of band and advances the Task
`working → completed / failed`. Clients poll `tasks/get`.

- **Runtime:** `python3.13`, handler `handler.lambda_handler`, timeout 29s (must stay under
  the API Gateway HTTP API ~30s integration cap).
- **Dependencies:** none beyond the Lambda-provided `boto3`. Packaged by Terraform with
  `archive_file` straight from this directory — there is **no build step**.
- **Fronted by:** API Gateway HTTP API with per-route JWT authorizers (Cognito / Entra ID).
  The authorizer validates the token before this function runs.
- **Env:** `A2A_TASKS_TABLE` (DynamoDB), `A2A_QUEUE_URL` (SQS work queue), plus the Agent
  Card fields. **No `AGENT_RUNTIME_ARN`** — that moved to the worker.

Files:

| File | Purpose |
|------|---------|
| `handler.py` | Routing, JSON-RPC dispatch, `message/send` submit + enqueue, `tasks/get`, `tasks/cancel`, task store |
| `agent_card.py` | Builds the per-route A2A AgentCard from environment variables |

JSON-RPC methods:

| Method | Behaviour |
|--------|-----------|
| `message/send` | Non-blocking: returns a `submitted` Task; the worker runs the turn. `configuration.blocking` is ignored. |
| `tasks/get` | Reads the Task from DynamoDB — poll until the state is terminal to get the answer. |
| `tasks/cancel` | Conditionally marks a non-terminal Task `canceled`; terminal task → `-32002`. |
| `message/stream`, `tasks/resubscribe` | `-32004` — `capabilities.streaming = false`. |
| `tasks/pushNotificationConfig/*` | `-32003`. |

The AgentCore `runtimeSessionId` is `sha256(f"{caller}:{contextId}")` so two callers that
pass the same `contextId` do not share one session.

See [`docs/a2a-integration.md`](../../docs/a2a-integration.md) for the full picture, auth
setup, and sample calls, and [`docs/a2a-streaming.md`](../../docs/a2a-streaming.md) for why
it's async and not streaming.
